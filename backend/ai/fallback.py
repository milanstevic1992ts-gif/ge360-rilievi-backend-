from __future__ import annotations
import re
from .schemas import CADOperation,CADToolName
_NUM=re.compile(r"(\d+(?:[\.,]\d+)?)\s*(mm|cm|m|metri|metro)?",re.I)
def _mm(text,opening=False):
    ms=list(_NUM.finditer(text))
    if not ms:return None
    m=ms[-1];v=float(m.group(1).replace(",","."));u=(m.group(2) or "").lower()
    if u in {"m","metro","metri"}:return v*1000
    if u=="cm":return v*10
    if opening and not u and 40<=v<=300:return v*10
    return v
def _criteria(q):
    room=next((x for x in ("bagno","cucina","camera","salotto","corridoio","wc") if x in q),None)
    side="left" if "sinistra" in q else "right" if "destra" in q else "top" if "sopra" in q else "bottom" if "sotto" in q else None
    orientation="vertical" if "vertical" in q else "horizontal" if "orizzont" in q else None
    m=re.search(r"(?:muro|parete)[^\d]{0,20}(\d+(?:[\.,]\d+)?)\s*(m|metri|cm)",q);length=None
    if m:length=float(m.group(1).replace(",","."))/(100 if m.group(2)=="cm" else 1)
    return dict(orientation=orientation,approx_length_m=length,room=room,side=side,near_opening_type="door" if "porta" in q else "window" if "finestra" in q else None)
class DeterministicFallbackPlanner:
    def _sel(self,r,k):
        xs=([r.selected_object] if r.selected_object else [])+list(r.selected_objects);return [x.id for x in xs if x and x.type==k and x.id]
    def _wall(self,c,r):
        s=self._sel(r,"wall")
        if s:return s[0],1.0
        rr=c.resolve_wall(**_criteria(r.instruction.casefold()))
        if rr.candidates:return rr.candidates[0].id,rr.candidates[0].confidence
        return (next(iter(c.walls)),.45) if len(c.walls)==1 else (None,0)
    def plan(self,c,r):
        t=r.instruction.strip();q=t.casefold();wid,conf=self._wall(c,r);sw=self._sel(r,"wall");so=self._sel(r,"opening")
        if ("da demolire" in q or "demolizione" in q) and wid:return [CADOperation(tool=CADToolName.ADD_ANNOTATION,arguments={"target_type":"wall","target_id":wid,"category":"demolition","text":t},confidence=max(conf,.55),reason="fallback_annotation")]
        if "controsoffitto" in q:return [CADOperation(tool=CADToolName.ADD_ANNOTATION,arguments={"target_type":"plan","category":"plasterboard","text":t},confidence=.75,reason="fallback_annotation")]
        if "piastrell" in q:return [CADOperation(tool=CADToolName.ADD_ANNOTATION,arguments={"target_type":"plan","category":"tiling","text":t},confidence=.7,reason="fallback_annotation")]
        if any(x in q for x in ("sistema la planimetria","sistema planimetria","correggi la planimetria","aggiusta la planimetria")):return [CADOperation(tool=CADToolName.SOLVE_PLAN,arguments={},confidence=.95),CADOperation(tool=CADToolName.VALIDATE_PLAN,arguments={},confidence=.95)]
        if "parallel" in q and len(sw)>=2:return [CADOperation(tool=CADToolName.ADD_CONSTRAINT,arguments={"kind":"parallel","wall_ids":sw[:2],"node_ids":[]})]
        if "perpendic" in q and len(sw)>=2:return [CADOperation(tool=CADToolName.ADD_CONSTRAINT,arguments={"kind":"perpendicular","wall_ids":sw[:2],"node_ids":[]})]
        if wid and any(x in q for x in ("cancella","elimina","rimuovi")) and any(x in q for x in ("muro","parete")):return [CADOperation(tool=CADToolName.DELETE_WALL,arguments={"wall_id":wid},confidence=max(conf,.51),reason="best_effort_target")]
        if wid and "90" in q and ("grad" in q or "°" in q):return [CADOperation(tool=CADToolName.MODIFY_WALL,arguments={"wall_id":wid,"angle_deg":90.0},confidence=max(conf,.6))]
        if wid and any(x in q for x in ("allunga","accorcia","lunghezza","porta il muro a","porta la parete a")):
            v=_mm(t)
            if v:return [CADOperation(tool=CADToolName.MODIFY_WALL,arguments={"wall_id":wid,"length_mm":v},confidence=max(conf,.6))]
        if so and "sposta" in q and ("destra" in q or "sinistra" in q):
            v=_mm(t)
            if v:return [CADOperation(tool=CADToolName.MODIFY_OPENING,arguments={"opening_id":so[0],"offset_delta_mm":v if "destra" in q else -v})]
        if wid and "porta" in q and any(x in q for x in ("metti","crea","aggiungi","inserisci")):
            v=_mm(t,True)
            if v:return [CADOperation(tool=CADToolName.CREATE_DOOR,arguments={"wall_id":wid,"width_mm":v},confidence=max(conf,.55),reason="backend_centers_opening")]
        if wid and "finestra" in q and any(x in q for x in ("metti","crea","aggiungi","inserisci")):
            v=_mm(t,True)
            if v:return [CADOperation(tool=CADToolName.CREATE_WINDOW,arguments={"wall_id":wid,"width_mm":v},confidence=max(conf,.55),reason="backend_centers_opening")]
        if "chiudi" in q and any(x in q for x in ("stanza","vano","locale")):return [CADOperation(tool=CADToolName.SOLVE_PLAN,arguments={},confidence=.65),CADOperation(tool=CADToolName.VALIDATE_PLAN,arguments={},confidence=.65)]
        return [CADOperation(tool=CADToolName.ADD_ANNOTATION,arguments={"target_type":"plan","category":"note","text":t},confidence=.35,reason="unrecognized_intent_preserved")]
