from __future__ import annotations
class SemanticSceneGraph:
    def __init__(self,plan):
        self.plan=plan; self.nodes={}; self._build()
    def _add(self,i,k,**attrs): self.nodes.setdefault(i,{"id":i,"kind":k,"relations":[]}).update({key:v for key,v in attrs.items() if v is not None})
    def _link(self,a,t,b):
        if a in self.nodes and b in self.nodes and {"type":t,"target":b} not in self.nodes[a]["relations"]: self.nodes[a]["relations"].append({"type":t,"target":b})
    def _build(self):
        for r in self.plan.get("rooms",[]): self._add(str(r.get("roomId")),"room",name=r.get("name"),areaM2=r.get("floorAreaM2"))
        for w in self.plan.get("walls",[]): self._add(str(w.get("id")),"wall",lengthMm=w.get("declaredLengthMm"),thicknessMm=w.get("thicknessMm"))
        for o in self.plan.get("openings",[]):
            oid,wid=str(o.get("id")),str(o.get("wallId")); self._add(oid,"opening",openingType=o.get("type"),widthMm=o.get("widthMm")); self._link(oid,"hosted_by",wid); self._link(wid,"hosts",oid)
        for r in self.plan.get("rooms",[]):
            rid=str(r.get("roomId"))
            for wid in r.get("wallIds",[]): wid=str(wid); self._link(rid,"bounded_by",wid); self._link(wid,"belongs_to",rid)
    def compact(self): return {"nodes":[{**x,"relations":x["relations"][:6]} for x in self.nodes.values()]}
    def relations_for(self,i): return list(self.nodes.get(i,{}).get("relations",[]))
