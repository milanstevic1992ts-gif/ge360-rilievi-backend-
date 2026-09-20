from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from .node import PointMM

class WallModel(BaseModel):
    id: str
    startNodeId: str
    endNodeId: str
    start: PointMM
    end: PointMM
    declaredLengthMm: float
    calculatedLengthMm: float
    sourceLengthCm: float
    heightMm: float
    thicknessMm: float
    sourceStroke: dict[str, Any] = Field(default_factory=dict)
    quality: str = "OK"
    orientation: str = "free"

    @property
    def lengthMm(self) -> float:
        return self.declaredLengthMm
