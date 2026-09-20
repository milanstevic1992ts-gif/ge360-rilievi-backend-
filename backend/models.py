from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlanStatus(str, Enum):
    RAW = "RAW"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"


class QualityStatus(str, Enum):
    OK = "OK"
    ESTIMATED = "ESTIMATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class XY(BaseModel):
    x: float
    y: float


class FrontendWall(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    a: XY
    b: XY
    lengthCm: float | None = None
    thicknessMm: float | None = None
    heightMm: float | None = None

    @field_validator("lengthCm")
    @classmethod
    def positive_length(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("lengthCm must be > 0")
        return value


class FrontendOpening(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: Literal["door", "window"]
    wallId: str
    position: float | None = None
    widthCm: float | None = None
    heightCm: float | None = None
    heightMm: float | None = None
    sillHeightCm: float | None = None
    sillHeightMm: float | None = None
    offsetCm: float | None = None
    referenceEnd: Literal["a", "b"] = "a"


class FrontendRoom(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str | None = None
    wallIds: list[str] = Field(default_factory=list)
    faceKey: str | None = None


class PlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: int = 4
    kind: str = "ge360-rough-survey"
    planId: str
    name: str = "Rilievo"
    updatedAt: str | None = None
    rawStrokes: list[Any] = Field(default_factory=list)
    walls: list[FrontendWall] = Field(default_factory=list)
    openings: list[FrontendOpening] = Field(default_factory=list)
    rooms: list[FrontendRoom] = Field(default_factory=list)
    notes: list[Any] = Field(default_factory=list)
    wallHeightM: float = 2.70
    surfaces: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class PointMM(BaseModel):
    x: float
    y: float


class WallModel(BaseModel):
    id: str
    startNodeId: str
    endNodeId: str
    start: PointMM
    end: PointMM
    lengthMm: float
    calculatedLengthMm: float
    sourceLengthCm: float
    heightMm: float
    thicknessMm: float
    sourceSketch: dict[str, Any] = Field(default_factory=dict)
    orientation: str = "free"


class OpeningModel(BaseModel):
    id: str
    type: Literal["door", "window"]
    wallId: str
    widthMm: float
    heightMm: float
    offsetMm: float
    referenceEnd: Literal["a", "b"]
    sillHeightMm: float = 0
    centerFromStartMm: float
    center: PointMM
    heightSource: str = "DEFAULT"
    sillHeightSource: str = "DEFAULT"


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


class PlanModel(BaseModel):
    planId: str
    name: str
    units: Literal["mm"] = "mm"
    version: int = 1
    walls: list[WallModel]
    openings: list[OpeningModel]
    rooms: list[RoomModel]
    notes: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needsReview: bool = False
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
