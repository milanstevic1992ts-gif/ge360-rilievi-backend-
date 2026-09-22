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
    # Metadati tecnici dell'apertura, mantenuti dal frontend fino agli export.
    doorKind: Literal["internal", "double", "sliding", "armored", "armored-double"] | None = None
    windowKind: Literal["single", "double", "triple", "sliding", "balcony", "balcony-double"] | None = None
    category: str | None = None
    leaves: int = 1
    sliding: bool = False
    armored: bool = False
    balconyDoor: bool = False
    hingeEnd: Literal["a", "b"] | None = None
    swingDirection: Literal["inward", "outward"] | None = None
    swingSide: int | None = None
    slideTo: Literal["a", "b"] | None = None
