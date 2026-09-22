from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLAN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class XY(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


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
    constructionState: Literal["existing", "demolish", "new", "close-opening", "new-opening"] = "existing"
    constructionThicknessCm: float | None = None

    @field_validator("lengthCm")
    @classmethod
    def positive_length(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("lengthCm must be > 0")
        return value

    @field_validator("constructionThicknessCm")
    @classmethod
    def positive_construction_thickness(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("constructionThicknessCm must be > 0")
        return value

    @model_validator(mode="after")
    def construction_contract(self):
        if self.constructionState in {"demolish", "new"}:
            if self.constructionThicknessCm is None and self.thicknessMm is not None:
                self.constructionThicknessCm = self.thicknessMm / 10.0
            if self.constructionThicknessCm is None:
                raise ValueError("constructionThicknessCm is required for demolish/new walls")
        return self


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
    doorKind: Literal["internal", "double", "sliding", "armored", "armored-double"] | None = None
    windowKind: Literal["single", "double", "triple", "sliding", "balcony", "balcony-double"] | None = None
    category: Literal["interior", "armored"] | None = None
    leaves: int = Field(default=1, ge=1, le=3)
    sliding: bool = False
    armored: bool = False
    balconyDoor: bool = False
    hingeEnd: Literal["a", "b"] | None = None
    swingDirection: Literal["inward", "outward"] | None = None
    swingSide: Literal[-1, 1] | None = None
    slideTo: Literal["a", "b"] | None = None

    @model_validator(mode="after")
    def technical_opening_contract(self):
        if self.type == "door":
            if self.windowKind is not None:
                raise ValueError("windowKind is not valid for a door")
            kind = self.doorKind or ("armored" if self.armored else "internal")
            self.doorKind = kind
            self.armored = kind in {"armored", "armored-double"}
            self.sliding = kind == "sliding"
            self.leaves = 2 if kind in {"double", "armored-double"} else 1
            self.category = "armored" if self.armored else "interior"
            if self.sliding:
                self.hingeEnd = None
                self.swingDirection = None
                self.swingSide = None
                self.slideTo = self.slideTo or "b"
            else:
                self.slideTo = None
                self.hingeEnd = self.hingeEnd or "a"
                self.swingDirection = self.swingDirection or "inward"
                self.swingSide = self.swingSide or 1
        else:
            if self.doorKind is not None:
                raise ValueError("doorKind is not valid for a window")
            kind = self.windowKind or "single"
            self.windowKind = kind
            self.sliding = kind == "sliding"
            self.balconyDoor = kind in {"balcony", "balcony-double"}
            self.leaves = 3 if kind == "triple" else (2 if kind in {"double", "sliding", "balcony-double"} else 1)
            self.armored = False
            self.category = None
            self.hingeEnd = None
            self.swingDirection = None
            self.swingSide = None
            self.slideTo = None
            if self.balconyDoor:
                self.sillHeightCm = 0.0
                self.sillHeightMm = 0.0
        return self


class FrontendRoom(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str | None = None
    wallIds: list[str] = Field(default_factory=list)
    faceKey: str | None = None
    # campi opzionali accettati come extra (non alterano il RAW): type, heightCm, tilingHeightCm


class FrontendWork(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    catalogId: str
    label: str | None = None
    targetType: Literal["room", "plan", "wall", "opening"] = "room"
    targetId: str | None = None
    targetIds: list[str] = Field(default_factory=list)
    quantityRule: str | None = None
    manualQuantity: float | None = None
    unit: str | None = None
    note: str | None = None


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
    technicalSchema: Literal["ge360-technical-plan-v1"] = "ge360-technical-plan-v1"
    planId: str | None = Field(default=None, pattern=PLAN_ID_PATTERN)
    name: str = Field(default="Rilievo", max_length=200)
    updatedAt: str | None = None
    rawStrokes: list[Any] = Field(default_factory=list)
    walls: list[FrontendWall] = Field(default_factory=list, max_length=500)
    openings: list[FrontendOpening] = Field(default_factory=list, max_length=500)
    rooms: list[FrontendRoom] = Field(default_factory=list, max_length=200)
    diagonals: list[FrontendDiagonal] = Field(default_factory=list, max_length=500)
    notes: list[Any] = Field(default_factory=list)
    works: list[FrontendWork] = Field(default_factory=list, max_length=1000)
    wallHeightM: float = 2.70
    # interior        = ogni linea è il filo interno misurato (default, compatibile V1)
    # partitionAxis   = perimetro a filo interno, tramezzi disegnati in asse (si scala mezzo spessore per lato)
    # axis            = tutte le pareti disegnate in asse
    wallReference: Literal["interior", "partitionAxis", "axis"] = "interior"
    surfaces: dict[str, Any] | None = None
    construction: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_entity_ids(self):
        groups = {
            "wall": [row.id for row in self.walls],
            "opening": [row.id for row in self.openings],
            "diagonal": [row.id for row in self.diagonals],
            "work": [row.id for row in self.works],
            "room": [row.id for row in self.rooms if row.id],
        }
        for label, ids in groups.items():
            seen, duplicates = set(), set()
            for value in ids:
                if value in seen:
                    duplicates.add(value)
                seen.add(value)
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {', '.join(sorted(duplicates))}")
        return self
