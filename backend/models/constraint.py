from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

class ConstraintKind(str, Enum):
    CONNECT = "connect"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    COLLINEAR = "collinear"

class ConstraintModel(BaseModel):
    id: str
    kind: ConstraintKind
    wallIds: list[str] = Field(default_factory=list)
    nodeIds: list[str] = Field(default_factory=list)
    source: str = "solver"
    metadata: dict[str, Any] = Field(default_factory=dict)
