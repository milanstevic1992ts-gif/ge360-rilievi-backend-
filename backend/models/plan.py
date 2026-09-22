from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field
from .common import PlanStatus, QualityStatus
from .node import NodeModel
from .wall import WallModel
from .opening import OpeningModel
from .room import RoomModel
from .constraint import ConstraintModel

class GE360Plan(BaseModel):
    technicalSchema: Literal["ge360-technical-plan-v1"] = "ge360-technical-plan-v1"
    planId: str
    name: str
    units: Literal["mm"] = "mm"
    version: int = 1
    nodes: list[NodeModel] = Field(default_factory=list)
    walls: list[WallModel]
    openings: list[OpeningModel]
    rooms: list[RoomModel]
    constraints: list[ConstraintModel] = Field(default_factory=list)
    notes: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needsReview: bool = False
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

PlanModel = GE360Plan
