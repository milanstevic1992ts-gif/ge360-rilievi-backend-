from __future__ import annotations
import json,uuid
from .critic import CADCritic
from .fallback import DeterministicFallbackPlanner
from .guards import is_unsafe_execution_request,validate_measurement_provenance
from .prompts import PROMPT_VERSION,load_cad_planner_prompt
from .provider import AIProviderError
from .schemas import CADCommandBatch,CADOperation,CADPlannerRequest,PlannerResult,TargetCandidate
from .tool_registry import REGISTRY

_TARGET={"wall_id","wall_a","wall_b","opening_id","constraint_id","node_id","start_node_id","end_node_id","target_id"}

class CADPlanner:
    def __init__(self,provider,audit,max_tool_rounds=4,registry=REGISTRY,*,memory=None,critic_enabled=True,best_effort=True):
        self.provider=provider;self.audit=audit;self.max_tool_rounds=max(1,min(int(max_tool_rounds),8));self.registry=registry;self.memory=memory;self.critic=CADCritic(provider,critic_enabled);self.best_effort=best_effort;self.fallback=DeterministicFallbackPlanner()
    def _mode(self,r):
        if r.mode!="AUTO":return r.mode
        q=r.instruction.casefold()
        if any(x in q for x in ("da demolire","controsoffitto","piastrell","pavimento da","cartongesso")):return "CONSTRUCTION_ANNOTATOR"
        if any(x in q for x in ("sistema la planimetria","correggi la planimetria","chiudi questa stanza","aggiusta la planimetria")):return "PLAN_REPAIR_PLANNER"
        if any(x in q for x in ("perché","spiega","errore solver","non chiude")):return "SOLVER_EXPLAINER"
        return "CAD_PLANNER"
    def _targets(self,args):
        out=set()
        for k,v in args.items():
            if k in _TARGET and isinstance(v,str) and v:out.add(v)
            if k in {"wall_ids","node_ids"} and isinstance(v,list):out.update(str(x) for x in v if x)
        return out
    def _trusted(self,c,r):
        out=c.explicitly_referenced_ids(r.instruction)
        for x in ([r.selected_object] if r.selected_object else [])+list(r.selected_objects):
            for i in (x.id,x.wall_id):
                if i and i in c.existing_ids():out.add(i)
        return out
    def _prepare(self,c,r,name,args,trusted):
        args=dict(args);sel=([r.selected_object] if r.selected_object else [])+list(r.selected_objects);one=sel[0] if len(sel)==1 else r.selected_object
        if one:
            if name in {"create_door","create_window"}:
                args.setdefault("wall_id",one.wall_id or (one.id if one.type=="wall" else None))
                if one.offset_mm is not None:args.setdefault("offset_mm",one.offset_mm)
            if name in {"modify_wall","delete_wall","move_wall","split_wall"} and one.type=="wall":args.setdefault("wall_id",one.id)
            if name in {"modify_opening","delete_opening"} and one.type=="opening":args.setdefault("opening_id",one.id)
            if name=="move_vertex" and one.type=="node":args.setdefault("node_id",one.id)
            if name=="add_annotation" and one.id:args.setdefault("target_id",one.id)
        sw=[x.id for x in sel if x.type=="wall" and x.id]
        if name=="add_constraint" and not args.get("wall_ids") and sw:args["wall_ids"]=sw
        if name=="connect_walls" and len(sw)>=2:args.setdefault("wall_a",sw[0]);args.setdefault("wall_b",sw[1])
        args={k:v for k,v in args.items() if v is not None};parsed=self.registry.validate_arguments(name,args).model_dump(mode="json")
        missing=self._targets(parsed)-c.existing_ids()
        if missing:raise ValueError(f"unknown target IDs: {sorted(missing)}")
        if self._targets(parsed)-trusted:raise ValueError("target IDs were not resolved from inspection/selection")
        op=CADOperation(tool=name,arguments=parsed);validate_measurement_provenance(op,r.instruction,[x.offset_mm for x in sel if x.offset_mm is not None]);return op
    def _ready(self,c,r,rid,ops,called,mode,degraded=False,best=False,msg=None):
        crit=self.critic.review(r.instruction,ops,c.semantic_summary())
        if not crit.proceed and not (self.best_effort and r.best_effort):
            x=PlannerResult(request_id=rid,status="invalid",mode=mode,critic=crit.model_dump(mode="json"),message="critic rejected",tools_called=called);self._audit(c,r,x);return x
        if not crit.proceed:degraded=True;best=True;msg=((msg or "")+" critic disagreed; preview anyway").strip()
        cmd=CADCommandBatch(request_id=rid,prompt_version=PROMPT_VERSION,operations=ops,requires_preview=True,requires_solver=any(o.tool.value!="add_annotation" for o in ops),destructive=any(o.tool.value in {"delete_wall","delete_opening"} for o in ops))
        x=PlannerResult(request_id=rid,status="ready",mode=mode,degraded=degraded,best_effort_used=best,critic=crit.model_dump(mode="json"),command=cmd,message=msg,tools_called=called)
        if self.memory:self.memory.remember_plan(rid,c.plan_id,r.instruction,[o.model_dump(mode="json") for o in ops],"ready")
        self._audit(c,r,x);return x
    def _fallback(self,c,r,rid,called,mode,cause):
        raw=self.fallback.plan(c,r);trusted=self._trusted(c,r)
        for x in raw:trusted.update(self._targets(x.arguments))
        ops=[]
        for x in raw:
            try:
                op=self._prepare(c,r,x.tool.value,x.arguments,trusted);op.confidence=x.confidence;op.reason=x.reason
            except Exception:
                op=CADOperation(tool="add_annotation",arguments={"target_type":"plan","category":"note","text":r.instruction},confidence=.2,reason="last_ditch_fallback")
            ops.append(op);called.append({"tool":op.tool.value,"arguments":op.arguments,"result":"deterministic_fallback"})
        return self._ready(c,r,rid,ops,called,mode,True,True,f"best-effort fallback: {cause}")
    def plan(self,c,r:CADPlannerRequest):
        rid=uuid.uuid4().hex;mode=self._mode(r)
        if is_unsafe_execution_request(r.instruction):
            x=PlannerResult(request_id=rid,status="invalid",mode=mode,message="outside GE360 CAD tool registry");self._audit(c,r,x);return x
        trusted=self._trusted(c,r);called=[];msgs=[{"role":"system","content":load_cad_planner_prompt()},{"role":"system","content":f"Mode={mode}; best_effort={r.best_effort and self.best_effort}"},{"role":"system","content":"Semantic context:\n"+json.dumps(c.semantic_summary(),ensure_ascii=False)}]
        if self.memory:
            ex=self.memory.similar_examples(r.instruction)
            if ex:msgs.append({"role":"system","content":"Local prior examples; never reuse IDs:\n"+json.dumps(ex,ensure_ascii=False)})
        sel=([r.selected_object] if r.selected_object else [])+list(r.selected_objects)
        if sel:msgs.append({"role":"system","content":"Trusted UI selection:\n"+json.dumps([x.model_dump(mode="json") for x in sel],ensure_ascii=False)})
        msgs.append({"role":"user","content":r.instruction})
        try:
            for _ in range(self.max_tool_rounds):
                reply=self.provider.tool_call(msgs,self.registry.openai_tools(include_control=False))
                if not reply.tool_calls:return self._fallback(c,r,rid,called,mode,"Qwen returned no tool") if self.best_effort and r.best_effort else PlannerResult(request_id=rid,status="no_action",mode=mode)
                parsed=[];assistant=[]
                for rc in reply.tool_calls:
                    name=str(rc.get("name") or "");cid=str(rc.get("id") or f"call_{uuid.uuid4().hex[:8]}");args=json.loads(rc.get("arguments") or "{}");spec=self.registry.get(name)
                    if spec.kind=="control":raise ValueError("control tool forbidden in planning")
                    if spec.kind=="read":args=self.registry.validate_arguments(name,args).model_dump(mode="json")
                    parsed.append((name,cid,args,spec));assistant.append({"id":cid,"type":"function","function":{"name":name,"arguments":json.dumps(args)}})
                kinds={x[3].kind for x in parsed}
                if len(kinds)>1:raise ValueError("separate inspection and mutation rounds")
                if kinds=={"read"}:
                    msgs.append({"role":"assistant","content":reply.content or "","tool_calls":assistant})
                    for name,cid,args,_ in parsed:
                        res=c.execute_read_tool(name,args);called.append({"tool":name,"arguments":args,"result":res})
                        if name=="find_nearest_wall":
                            cs=[TargetCandidate.model_validate(x) for x in res.get("candidates",[])]
                            if res.get("resolvedWallId"):trusted.add(str(res["resolvedWallId"]))
                            elif cs and self.best_effort and r.best_effort:trusted.add(cs[0].id);res["bestEffortSelectedWallId"]=cs[0].id
                            elif res.get("ambiguous"):
                                x=PlannerResult(request_id=rid,status="ambiguous",mode=mode,candidates=cs,tools_called=called);self._audit(c,r,x);return x
                        if name=="get_room":trusted.update(str(x) for x in res.get("wallIds",[]))
                        msgs.append({"role":"tool","tool_call_id":cid,"content":json.dumps(res,ensure_ascii=False)})
                    continue
                ops=[self._prepare(c,r,name,args,trusted) for name,_,args,_ in parsed]
                return self._ready(c,r,rid,ops,called+[{"tool":o.tool.value,"arguments":o.arguments,"result":"candidate_only"} for o in ops],mode)
            return self._fallback(c,r,rid,called,mode,"max tool rounds") if self.best_effort and r.best_effort else PlannerResult(request_id=rid,status="invalid",mode=mode)
        except (AIProviderError,ValueError,TypeError,json.JSONDecodeError,IndexError) as exc:
            return self._fallback(c,r,rid,called,mode,str(exc)) if self.best_effort and r.best_effort else PlannerResult(request_id=rid,status="invalid",mode=mode,message=str(exc))
    def _audit(self,c,r,x):
        cmd=x.command;self.audit.append(c.plan_id,{"request_id":x.request_id,"model":getattr(self.provider,"model","unknown"),"prompt_version":PROMPT_VERSION,"user_instruction":r.instruction,"mode":x.mode,"degraded":x.degraded,"best_effort_used":x.best_effort_used,"critic":x.critic,"tools_called":x.tools_called,"tool_arguments":[o.arguments for o in cmd.operations] if cmd else [],"candidate_version":None,"validation_result":None,"apply_status":"not_applied","planner_status":x.status})
