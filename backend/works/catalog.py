from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


def load_catalog() -> dict[str, Any]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def catalog_index() -> dict[str, dict[str, Any]]:
    data = load_catalog()
    return {row["id"]: row for row in data.get("works", [])}


def _room_value(room, rule: str) -> float | None:
    mapping = {
        "ROOM_FLOOR": room.floorAreaM2,
        "ROOM_CEILING": room.ceilingAreaM2,
        "ROOM_NET_WALLS": room.netWallAreaM2,
        "ROOM_GROSS_WALLS": room.grossWallAreaM2,
        "ROOM_WALLS_CEILING": room.netWallAreaM2 + room.ceilingAreaM2,
        "ROOM_SKIRTING": room.skirtingM,
        "ROOM_TILING": room.tilingAreaM2,
    }
    value = mapping.get(rule)
    return round(float(value), 4) if value is not None else None


def resolve_works(model, raw_works: list[Any] | None) -> list[dict[str, Any]]:
    """Resolve field notes/work intents against authoritative room geometry.

    The frontend chooses WHAT/WHERE. This function is the only place that
    derives quantities from the solved PlanModel.
    """
    idx = catalog_index()
    rooms = {r.roomId: r for r in model.rooms}
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
            item = {"id": catalog_id or "custom", "label": label, "category": "Altro",
                    "quantityRule": "MANUAL", "unit": str(raw.get("unit") or "")}

        rule = str(raw.get("quantityRule") or item.get("quantityRule") or "MANUAL")
        target_type = str(raw.get("targetType") or "room")
        target_id = raw.get("targetId")
        target_ids = [str(x) for x in (raw.get("targetIds") or []) if str(x)]
        if target_type == "room" and target_id:
            target_ids = [str(target_id)]
        elif target_type == "plan" and not target_ids:
            target_ids = list(rooms)

        manual = raw.get("manualQuantity")
        quantity: float | None = None
        source = "manual"

        if manual is not None:
            try:
                quantity = round(float(manual), 4)
            except (TypeError, ValueError):
                quantity = None
        elif rule == "COUNT":
            quantity = 1.0
            source = "catalog-count"
        elif rule.startswith("ROOM_"):
            selected = [rooms[rid] for rid in target_ids if rid in rooms]
            values = [_room_value(room, rule) for room in selected]
            usable = [v for v in values if v is not None]
            if usable:
                quantity = round(sum(usable), 4)
                source = "authoritative-room-geometry"
        elif rule.startswith("PLAN_"):
            room_rule = "ROOM_" + rule[len("PLAN_"):]
            values = [_room_value(room, room_rule) for room in rooms.values()]
            usable = [v for v in values if v is not None]
            if usable:
                quantity = round(sum(usable), 4)
                source = "authoritative-plan-geometry"

        room_names = [rooms[rid].name for rid in target_ids if rid in rooms]
        resolved = {
            "id": str(raw.get("id") or f"work-{pos}"),
            "catalogId": item["id"],
            "label": str(raw.get("label") or item["label"]),
            "category": item.get("category") or "Altro",
            "targetType": target_type,
            "targetId": str(target_id) if target_id else None,
            "targetIds": target_ids,
            "targetNames": room_names,
            "quantityRule": rule,
            "quantity": quantity,
            "unit": str(raw.get("unit") or item.get("unit") or ""),
            "quantitySource": source if quantity is not None else "unresolved",
            "note": str(raw.get("note") or "").strip()[:1000],
            "needsReview": quantity is None and rule != "MANUAL",
        }
        out.append(resolved)
    return out
