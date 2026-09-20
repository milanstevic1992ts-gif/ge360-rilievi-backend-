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


class Point2D(BaseModel):
    x: float
    y: float


class FrontendWall(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    strokeId: str | None = None
    a: Point2D
    b: Point2D
    lengthCm: float | None = None
    thicknessMm: float | None = None
    heightMm: float | None = None

    @field_validator("lengthCm")
    @classmethod
    def positive_length(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("lengthCm must be positive")
        return value


class FrontendOpening(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: Literal["door", "window"]
    wallId: str
    widthCm: float
    heightCm: float | None = None
    sillHeightCm: float | None = None
    offsetCm: float | None = None
    referenceEnd: Literal["a", "b"] = "a"
    position: float | None = None


class FrontendRoom(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str | None = None
    wallIds: list[str] = Field(default_factory=list)


class FrontendPlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: int = 4
    kind: str = "ge360-rough-survey"
    planId: str
    name: str = "Rilievo"
    createdAt: str | None = None
    updatedAt: str | None = None
    rawStrokes: list[Any] = Field(default_factory=list)
    walls: list[FrontendWall] = Field(default_factory=list)
    openings: list[FrontendOpening] = Field(default_factory=list)
    rooms: list[FrontendRoom] = Field(default_factory=list)
    notes: list[Any] = Field(default_factory=list)
    wallHeightM: float = 2.70
    surfaces: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class Node(BaseModel):
    id: str
    x: float
    y: float
    sourcePoints: list[Point2D] = Field(default_factory=list)
    snapDistanceMm: float = 0.0


class Wall(BaseModel):
    id: str
    startNodeId: str | None = None
    endNodeId: str | None = None
    start: Point2D
    end: Point2D
    lengthMm: float
    heightMm: float
    thicknessMm: float
    sourceLengthCm: float
    sourceA: Point2D
    sourceB: Point2D
    strokeId: str | None = None
    orientationClass: Literal["H", "V", "FREE"] = "FREE"
    solved: bool = True


class Opening(BaseModel):
    id: str
    type: Literal["door", "window"]
    wallId: str
    widthMm: float
    heightMm: float
    sillHeightMm: float = 0.0
    offsetMm: float
    referenceEnd: Literal["a", "b"]
    centerFromStartMm: float
    valid: bool = True
    warning: str | None = None


class Room(BaseModel):
    roomId: str
    name: str
    polygon: list[Point2D]
    wallIds: list[str] = Field(default_factory=list)
    floorAreaM2: float
    ceilingAreaM2: float
    perimeterM: float
    grossWallAreaM2: float
    quality: Literal["OK", "ESTIMATED", "NEEDS_REVIEW"]


class Floor(BaseModel):
    id: str = "floor-1"
    roomIds: list[str] = Field(default_factory=list)


class Ceiling(BaseModel):
    id: str = "ceiling-1"
    roomIds: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    status: Literal["OK", "ESTIMATED", "NEEDS_REVIEW"]
    closureErrorCm: float = 0.0
    maxLengthErrorMm: float = 0.0
    geometryScore: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class ProcessedPlan(BaseModel):
    planId: str
    name: str
    units: Literal["mm"] = "mm"
    version: int
    nodes: list[Node] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    floor: Floor = Field(default_factory=Floor)
    ceiling: Ceiling = Field(default_factory=Ceiling)
    quality: QualityReport
    needsReview: bool = False
    source: dict[str, Any] = Field(default_factory=dict)


class Plan3D(BaseModel):
    planId: str
    units: Literal["mm"] = "mm"
    walls: list[dict[str, Any]] = Field(default_factory=list)
    doors: list[dict[str, Any]] = Field(default_factory=list)
    windows: list[dict[str, Any]] = Field(default_factory=list)
    rooms: list[dict[str, Any]] = Field(default_factory=list)
    floor: list[dict[str, Any]] = Field(default_factory=list)


class PlanRecord(BaseModel):
    planId: str
    name: str
    createdAt: str
    updatedAt: str
    status: PlanStatus
    currentVersion: int = 0
    path: str
    quality: dict[str, Any] | None = None
    needsReview: bool = False
    error: str | None = None
