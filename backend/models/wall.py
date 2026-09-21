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
    sourceLengthCm: float | None = None
    heightMm: float
    thicknessMm: float
    sourceStroke: dict[str, Any] = Field(default_factory=dict)
    quality: str = "OK"
    orientation: str = "free"
    # Rilievo fedele v2
    measured: bool = True
    lengthErrorMm: float = 0.0
    toleranceMm: float = 0.0
    withinTolerance: bool = True
    suspect: bool = False
    suggestedLengthMm: float | None = None
    # MEASURED = misura di cantiere, CALCULATED = ricavata dalle altre misure, SKETCH = solo dallo schizzo
    lengthSource: str = "MEASURED"

    @property
    def lengthMm(self) -> float:
        return self.declaredLengthMm
