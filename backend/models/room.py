from __future__ import annotations
from pydantic import BaseModel
from .common import QualityStatus
from .node import PointMM

class RoomModel(BaseModel):
    roomId: str
    name: str
    polygon: list[PointMM]
    wallIds: list[str]
    floorAreaM2: float
    ceilingAreaM2: float
    perimeterM: float
    grossWallAreaM2: float
    quality: QualityStatus
