from __future__ import annotations
import json
from pydantic import Field
from .schemas import StrictModel
class CriticDecision(StrictModel):
    proceed:bool=True; confidence:float=Field(default=.5,ge=0,le=1); issues:list[str]=Field(default_factory=list,max_length=12)
class CADCritic:
    def __init__(self,provider,enabled=True):self.provider=provider;self.enabled=enabled
    def review(self,instruction,operations,semantic):
        if not self.enabled:return CriticDecision(proceed=True,confidence=1)
        try:
            return self.provider.structured_output([{"role":"system","content":"You are GE360 CAD Critic. Check proposed tool calls against the instruction. Do not invent IDs, coordinates, measurements or operations. Return JSON: proceed, confidence, issues. Geometry validity belongs to GE360."},{"role":"user","content":json.dumps({"instruction":instruction,"operations":[x.model_dump(mode="json") for x in operations],"semantic":semantic},ensure_ascii=False)}],CriticDecision)
        except Exception as exc:return CriticDecision(proceed=True,confidence=.2,issues=[f"critic_unavailable:{exc}"])
