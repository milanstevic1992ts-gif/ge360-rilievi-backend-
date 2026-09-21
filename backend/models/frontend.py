from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

PLAN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class XY(BaseModel):
    x: float
    y: float


class FrontendWall(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    a: XY
    b: XY
    # None = parete disegnata ma non misurata: la lunghezza viene stimata dallo schizzo.
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
    # campi opzionali accettati come extra (non alterano il RAW): type, heightCm, tilingHeightCm


class FrontendDiagonal(BaseModel):
    """Misura di controllo tra due angoli (diagonale o qualsiasi distanza punto-punto)."""

    model_config = ConfigDict(extra="allow")
    id: str
    a: XY
    b: XY
    lengthCm: float = Field(gt=0)


class PlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: int = 4
    kind: str = "ge360-rough-survey"
    planId: str | None = Field(default=None, pattern=PLAN_ID_PATTERN)
    name: str = Field(default="Rilievo", max_length=200)
    updatedAt: str | None = None
    rawStrokes: list[Any] = Field(default_factory=list)
    walls: list[FrontendWall] = Field(default_factory=list, max_length=500)
    openings: list[FrontendOpening] = Field(default_factory=list, max_length=500)
    rooms: list[FrontendRoom] = Field(default_factory=list, max_length=200)
    diagonals: list[FrontendDiagonal] = Field(default_factory=list, max_length=500)
    notes: list[Any] = Field(default_factory=list)
    wallHeightM: float = 2.70
    # interior        = ogni linea è il filo interno misurato (default, compatibile V1)
    # partitionAxis   = perimetro a filo interno, tramezzi disegnati in asse (si scala mezzo spessore per lato)
    # axis            = tutte le pareti disegnate in asse
    wallReference: Literal["interior", "partitionAxis", "axis"] = "interior"
    surfaces: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
