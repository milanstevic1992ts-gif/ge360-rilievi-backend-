from __future__ import annotations

from backend.models import PlanModel


def to_plan3d(model: PlanModel) -> dict:
    return {
        "planId": model.planId,
        "name": model.name,
        "units": "mm",
        "walls": [
            {
                "id": w.id,
                "start": [w.start.x, w.start.y],
                "end": [w.end.x, w.end.y],
                "length": w.lengthMm,
                "height": w.heightMm,
                "thickness": w.thicknessMm,
                "openings": [o.id for o in model.openings if o.wallId == w.id],
            }
            for w in model.walls
        ],
        "doors": [
            {
                "id": o.id,
                "wallId": o.wallId,
                "width": o.widthMm,
                "height": o.heightMm,
                "offset": o.offsetMm,
                "referenceEnd": o.referenceEnd,
                "centerFromStart": o.centerFromStartMm,
            }
            for o in model.openings if o.type == "door"
        ],
        "windows": [
            {
                "id": o.id,
                "wallId": o.wallId,
                "width": o.widthMm,
                "height": o.heightMm,
                "sillHeight": o.sillHeightMm,
                "offset": o.offsetMm,
                "referenceEnd": o.referenceEnd,
                "centerFromStart": o.centerFromStartMm,
            }
            for o in model.openings if o.type == "window"
        ],
        "rooms": [
            {
                "id": r.roomId,
                "name": r.name,
                "polygon": [[p.x, p.y] for p in r.polygon],
                "floorAreaM2": r.floorAreaM2,
                "ceilingAreaM2": r.ceilingAreaM2,
                "perimeterM": r.perimeterM,
                "quality": r.quality.value,
            }
            for r in model.rooms
        ],
        "camera": {"up": [0, 0, 1], "defaultView": "perspective"},
    }
