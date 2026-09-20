from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    strokeId: str | None = None

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
    planId: str | None = None
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
