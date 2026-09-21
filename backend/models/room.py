from __future__ import annotations
from pydantic import BaseModel, Field
from .common import QualityStatus
from .node import PointMM


class RoomOpening(BaseModel):
    id: str
    type: str
    wallId: str
    widthMm: float
    heightMm: float
    sillHeightMm: float
    areaM2: float
    revealAreaM2: float
    connectsToRoomId: str | None = None


class RoomWallFace(BaseModel):
    """Una faccia di parete vista dall'interno della stanza."""

    wallId: str | None
    lengthMm: float
    heightMm: float
    grossAreaM2: float
    openingIds: list[str] = Field(default_factory=list)
    openingsAreaM2: float = 0.0
    netAreaM2: float = 0.0
    revealAreaM2: float = 0.0
    tilingAreaM2: float | None = None
    orientationDeg: float = 0.0
    shared: bool = False


class RoomModel(BaseModel):
    roomId: str
    name: str
    polygon: list[PointMM]
    wallIds: list[str]
    floorAreaM2: float            # netta calpestabile
    ceilingAreaM2: float
    perimeterM: float
    grossWallAreaM2: float        # perimetro x altezza (senza togliere aperture)
    quality: QualityStatus
    # --- dettaglio stanza ---
    type: str = "altro"
    grossFloorAreaM2: float = 0.0  # area sulle linee di rilievo (prima di togliere mezzi tramezzi)
    heightMm: float = 2700.0
    heightSource: str = "DEFAULT"
    volumeM3: float = 0.0
    widthM: float = 0.0
    depthM: float = 0.0
    ceilingType: str = "piano"
    skirtingM: float = 0.0
    openingsAreaM2: float = 0.0
    netWallAreaM2: float = 0.0
    revealsAreaM2: float = 0.0
    tilingHeightMm: float | None = None
    tilingAreaM2: float | None = None
    paintAreaM2: float = 0.0
    wallFaces: list[RoomWallFace] = Field(default_factory=list)
    openings: list[RoomOpening] = Field(default_factory=list)
    adjacentRoomIds: list[str] = Field(default_factory=list)
    estimatedWallIds: list[str] = Field(default_factory=list)   # lunghezza presa dallo schizzo
    calculatedWallIds: list[str] = Field(default_factory=list)  # non misurate ma ricavate dalle misure
    maxWallErrorMm: float = 0.0
    confidence: float = 1.0
    # compatibilità: l'agente non fa più domande, la lista resta vuota
    questions: list[str] = Field(default_factory=list)
    # decisioni autonome che riguardano questa stanza (cosa ha deciso e perché)
    decisions: list[str] = Field(default_factory=list)
    # intervallo 10°-90° percentile del pavimento dal Monte Carlo
    floorAreaRangeM2: list[float] | None = None
    floorAreaStdM2: float | None = None
