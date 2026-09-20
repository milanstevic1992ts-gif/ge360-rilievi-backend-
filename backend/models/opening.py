from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from .node import PointMM

class OpeningModel(BaseModel):
    id: str
    type: Literal["door", "window"]
    wallId: str
    widthMm: float
    heightMm: float
    offsetMm: float
    referenceEnd: Literal["a", "b"]
    sillHeightMm: float = 0.0
    centerFromStartMm: float
    center: PointMM
    heightSource: str = "DEFAULT"
    sillHeightSource: str = "DEFAULT"
