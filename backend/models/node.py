from __future__ import annotations
from pydantic import BaseModel, Field

class PointMM(BaseModel):
    x: float
    y: float

class NodeModel(BaseModel):
    id: str
    point: PointMM
    sourceEndpoints: list[tuple[str, str]] = Field(default_factory=list)
