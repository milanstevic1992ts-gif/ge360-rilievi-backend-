from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


def load_catalog() -> dict[str, Any]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def catalog_index() -> dict[str, dict[str, Any]]:
    data = load_catalog()
    return {row["id"]: row for row in data.get("works", [])}


def _round(value: float | None) -> float | None:
    return round(float(value), 4) if value is not None else None


def _room_value(room, rule: str) -> tuple[float | None, str, bool]:
    """Return quantity, human-readable basis and review flag."""
    if rule == "ROOM_FLOOR":
        return _round(room.floorAreaM2), "superficie pavimento", False
    if rule == "ROOM_CEILING":
        return _round(room.ceilingAreaM2), "superficie soffitto", False
    if rule == "ROOM_NET_WALLS":
        return _round(room.netWallAreaM2), "pareti nette", False
    if rule == "ROOM_GROSS_WALLS":
        return _round(room.grossWallAreaM2), "pareti lorde", False
    if rule == "ROOM_WALLS_CEILING":
        return _round(room.netWallAreaM2 + room.ceilingAreaM2), "pareti nette + soffitto", False
    if rule == "ROOM_SKIRTING":
        return _round(room.skirtingM), "perimetro battiscopa", False
    if rule == "ROOM_TILING":
        value = room.tilingAreaM2
        return _round(value), "superficie rivestimento impostata", value is None
    if rule == "ROOM_TILING_OR_NET_WALLS":
        if room.tilingAreaM2 is not None:
            return _round(room.tilingAreaM2), "superficie rivestimento impostata", False
        return _round(room.netWallAreaM2), "pareti nette (altezza rivestimento non impostata)", True
    return None, "", True


def _wall_length_m(wall) -> float:
    return float(wall.calculatedLengthMm) / 1000.0


def _wall_opening_area(model, wall_id: str) -> float:
    return sum(
        (float(o.widthMm) * float(o.heightMm)) / 1_000_000.0
        for o in model.openings
        if o.wallId == wall_id
    )


def _wall_value(model, wall, rule: str) -> tuple[float | None, str]:
    length_m = _wall_length_m(wall)
    height_m = float(wall.heightMm) / 1000.0
    gross = length_m * height_m
    if rule == "WALL_GROSS_AREA":
        return _round(gross), "lunghezza muro × altezza"
    if rule == "WALL_NET_AREA":
        return _round(max(0.0, gross - _wall_opening_area(model, wall.id))), "muro lordo - aperture"
    if rule == "WALL_LENGTH":
        return _round(length_m), "lunghezza muro"
    return None, ""


def _rooms_by_wall(model) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = defaultdict(list)
    for room in model.rooms:
        for wall_id in room.wallIds:
            out[str(wall_id)].append(room)
    return out


def _target_label_for_wall(model, wall, rooms_for_wall: list[Any]) -> str:
    index = next((i for i, item in enumerate(model.walls, start=1) if item.id == wall.id), None)
    label = f"Muro {index}" if index else f"Muro {wall.id}"
    names = [room.name for room in rooms_for_wall]
    if names:
        label += " · " + " / ".join(names)
    return label


def summarize_works(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate equal work items without double counting room/wall display breakdowns."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows or []:
        key = (
            str(row.get("catalogId") or row.get("label") or ""),
            str(row.get("label") or ""),
            str(row.get("unit") or ""),
        )
        if key not in grouped:
            grouped[key] = {
                "catalogId": row.get("catalogId"),
                "label": row.get("label") or "",
                "category": row.get("category") or "Altro",
                "unit": row.get("unit") or "",
                "quantity": 0.0,
                "resolvedItems": 0,
                "unresolvedItems": 0,
                "needsReview": False,
            }
        target = grouped[key]
        quantity = row.get("quantity")
        if quantity is None:
            target["unresolvedItems"] += 1
        else:
            target["quantity"] = round(target["quantity"] + float(quantity), 4)
            target["resolvedItems"] += 1
        target["needsReview"] = bool(target["needsReview"] or row.get("needsReview"))
    return sorted(
        grouped.values(),
        key=lambda row: (str(row["category"]).lower(), str(row["label"]).lower()),
    )


def resolve_works(model, raw_works: list[Any] | None) -> list[dict[str, Any]]:
    """Resolve WHAT/WHERE chosen by the frontend against authoritative geometry.

    The frontend never calculates final quantities. This resolver supports room,
    whole-plan, wall and opening targets and emits a per-target breakdown that
    the PDF can display room by room without changing the authoritative total.
    """
    idx = catalog_index()
    rooms = {str(r.roomId): r for r in model.rooms}
    walls = {str(w.id): w for w in model.walls}
    openings = {str(o.id): o for o in model.openings}
    rooms_by_wall = _rooms_by_wall(model)
    out: list[dict[str, Any]] = []

    for pos, raw in enumerate(raw_works or [], start=1):
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        if not isinstance(raw, dict):
            continue

        catalog_id = str(raw.get("catalogId") or "").strip()
        item = idx.get(catalog_id)
        if item is None:
            label = str(raw.get("label") or "").strip()
            if not label:
                continue
            item = {
                "id": catalog_id or "custom",
                "label": label,
                "category": "Altro",
                "quantityRule": "MANUAL",
                "unit": str(raw.get("unit") or ""),
            }

        # For known catalog items the backend catalog is authoritative. This also
        # upgrades older frontend records that stored a now-obsolete MANUAL rule.
        rule = str(
            item.get("quantityRule")
            if catalog_id in idx
            else (raw.get("quantityRule") or item.get("quantityRule") or "MANUAL")
        )
        target_type = str(raw.get("targetType") or "room")
        target_id = str(raw.get("targetId")) if raw.get("targetId") not in (None, "") else None
        target_ids = [str(x) for x in (raw.get("targetIds") or []) if str(x)]

        if target_type in {"room", "wall", "opening"} and target_id:
            target_ids = [target_id]
        elif target_type == "plan" and not target_ids:
            target_ids = list(rooms)

        manual = raw.get("manualQuantity")
        quantity: float | None = None
        source = "manual"
        quantity_basis = ""
        needs_review = False
        breakdown: list[dict[str, Any]] = []
        target_names: list[str] = []

        if manual is not None:
            try:
                quantity = round(float(manual), 4)
                quantity_basis = "quantità manuale"
            except (TypeError, ValueError):
                quantity = None
                needs_review = True

        elif rule == "COUNT":
            if target_type == "opening" and target_ids:
                valid = [oid for oid in target_ids if oid in openings]
                quantity = float(len(valid)) if valid else 1.0
                target_names = [
                    ("Porta" if openings[oid].type == "door" else "Finestra") + " " + oid
                    for oid in valid
                ]
            else:
                quantity = 1.0
            source = "catalog-count"
            quantity_basis = "conteggio"

        elif target_type == "wall" and rule in {"ROOM_NET_WALLS", "ROOM_GROSS_WALLS", "ROOM_TILING", "ROOM_TILING_OR_NET_WALLS"}:
            translated = "WALL_GROSS_AREA" if rule == "ROOM_GROSS_WALLS" else "WALL_NET_AREA"
            selected_walls = [walls[wid] for wid in target_ids if wid in walls]
            values: list[float] = []
            for wall in selected_walls:
                value, basis = _wall_value(model, wall, translated)
                if value is None:
                    continue
                values.append(value)
                wall_rooms = rooms_by_wall.get(wall.id, [])
                wall_name = _target_label_for_wall(model, wall, wall_rooms)
                breakdown.append(
                    {
                        "targetType": "wall",
                        "targetId": wall.id,
                        "targetName": wall_name,
                        "roomIds": [room.roomId for room in wall_rooms],
                        "roomNames": [room.name for room in wall_rooms],
                        "quantity": value,
                        "unit": str(raw.get("unit") or item.get("unit") or ""),
                        "basis": "superficie netta muro selezionato" if translated == "WALL_NET_AREA" else "superficie lorda muro selezionato",
                        "lengthM": _round(_wall_length_m(wall)),
                        "heightM": _round(float(wall.heightMm) / 1000.0),
                        "thicknessMm": _round(float(wall.thicknessMm)),
                        "needsReview": rule in {"ROOM_TILING", "ROOM_TILING_OR_NET_WALLS"},
                    }
                )
                target_names.append(wall_name)
            if values:
                quantity = round(sum(values), 4)
                source = "authoritative-wall-geometry"
                quantity_basis = breakdown[0]["basis"] if len(breakdown) == 1 else "somma superfici muri selezionati"
            needs_review = rule in {"ROOM_TILING", "ROOM_TILING_OR_NET_WALLS"} or not bool(values)

        elif rule.startswith("ROOM_"):
            selected = (
                [rooms[rid] for rid in target_ids if rid in rooms]
                if target_type != "plan"
                else list(rooms.values())
            )
            values: list[float] = []
            review_flags: list[bool] = []
            for room in selected:
                value, basis, review = _room_value(room, rule)
                if value is None:
                    review_flags.append(True)
                    continue
                values.append(value)
                review_flags.append(review)
                breakdown.append(
                    {
                        "targetType": "room",
                        "targetId": room.roomId,
                        "targetName": room.name,
                        "quantity": value,
                        "unit": str(raw.get("unit") or item.get("unit") or ""),
                        "basis": basis,
                        "needsReview": review,
                    }
                )
            if values:
                quantity = round(sum(values), 4)
                source = "authoritative-plan-geometry" if target_type == "plan" else "authoritative-room-geometry"
                quantity_basis = breakdown[0]["basis"] if len(breakdown) == 1 else "somma delle superfici ambiente"
            needs_review = any(review_flags)
            target_names = [room.name for room in selected]

        elif rule.startswith("PLAN_"):
            room_rule = "ROOM_" + rule[len("PLAN_"):]
            values: list[float] = []
            review_flags: list[bool] = []
            for room in rooms.values():
                value, basis, review = _room_value(room, room_rule)
                if value is None:
                    review_flags.append(True)
                    continue
                values.append(value)
                review_flags.append(review)
                breakdown.append(
                    {
                        "targetType": "room",
                        "targetId": room.roomId,
                        "targetName": room.name,
                        "quantity": value,
                        "unit": str(raw.get("unit") or item.get("unit") or ""),
                        "basis": basis,
                        "needsReview": review,
                    }
                )
            if values:
                quantity = round(sum(values), 4)
                source = "authoritative-plan-geometry"
                quantity_basis = "somma delle superfici ambiente"
            needs_review = any(review_flags)
            target_names = [room.name for room in rooms.values()]

        elif rule.startswith("WALL_"):
            selected_walls = [walls[wid] for wid in target_ids if wid in walls]
            values: list[float] = []
            for wall in selected_walls:
                value, basis = _wall_value(model, wall, rule)
                if value is None:
                    continue
                values.append(value)
                wall_rooms = rooms_by_wall.get(wall.id, [])
                wall_name = _target_label_for_wall(model, wall, wall_rooms)
                breakdown.append(
                    {
                        "targetType": "wall",
                        "targetId": wall.id,
                        "targetName": wall_name,
                        "roomIds": [room.roomId for room in wall_rooms],
                        "roomNames": [room.name for room in wall_rooms],
                        "quantity": value,
                        "unit": str(raw.get("unit") or item.get("unit") or ""),
                        "basis": basis,
                        "lengthM": _round(_wall_length_m(wall)),
                        "heightM": _round(float(wall.heightMm) / 1000.0),
                        "thicknessMm": _round(float(wall.thicknessMm)),
                        "needsReview": False,
                    }
                )
                target_names.append(wall_name)
            if values:
                quantity = round(sum(values), 4)
                source = "authoritative-wall-geometry"
                quantity_basis = breakdown[0]["basis"] if len(breakdown) == 1 else "somma superfici muri selezionati"
            else:
                needs_review = True

        elif rule.startswith("OPENING_"):
            selected_openings = [openings[oid] for oid in target_ids if oid in openings]
            if rule == "OPENING_AREA":
                values = []
                for opening in selected_openings:
                    value = round(float(opening.widthMm) * float(opening.heightMm) / 1_000_000.0, 4)
                    values.append(value)
                    wall_rooms = rooms_by_wall.get(opening.wallId, [])
                    name = ("Porta" if opening.type == "door" else "Finestra") + f" {opening.id}"
                    breakdown.append(
                        {
                            "targetType": "opening",
                            "targetId": opening.id,
                            "targetName": name,
                            "roomIds": [room.roomId for room in wall_rooms],
                            "roomNames": [room.name for room in wall_rooms],
                            "quantity": value,
                            "unit": str(raw.get("unit") or item.get("unit") or ""),
                            "basis": "larghezza × altezza apertura",
                            "needsReview": False,
                        }
                    )
                    target_names.append(name)
                if values:
                    quantity = round(sum(values), 4)
                    source = "authoritative-opening-geometry"
                    quantity_basis = "superficie aperture"
                else:
                    needs_review = True

        # Plain MANUAL without a manualQuantity intentionally stays unresolved.
        if quantity is None and rule != "MANUAL":
            needs_review = True

        resolved = {
            "id": str(raw.get("id") or f"work-{pos}"),
            "catalogId": item["id"],
            "label": str(raw.get("label") or item["label"]),
            "category": item.get("category") or "Altro",
            "targetType": target_type,
            "targetId": target_id,
            "targetIds": target_ids,
            "targetNames": target_names,
            "quantityRule": rule,
            "quantity": quantity,
            "unit": str(raw.get("unit") or item.get("unit") or ""),
            "quantitySource": source if quantity is not None else "unresolved",
            "quantityBasis": quantity_basis,
            "breakdown": breakdown,
            "note": str(raw.get("note") or "").strip()[:1000],
            "needsReview": bool(needs_review or (quantity is None and rule != "MANUAL")),
        }
        out.append(resolved)

    return out
