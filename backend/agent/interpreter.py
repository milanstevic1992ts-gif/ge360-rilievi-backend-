"""Interprete IA del rilievo.

La precisione metrica la fa il solver deterministico. L'IA serve dove il solver è cieco:
- dare un nome e un tipo alle stanze senza nome, usando note, dimensioni e aperture;
- trasformare incoerenze e stime in domande chiare per chi ha fatto il rilievo;
- scrivere un riassunto in italiano del rilievo.

Non riceve e non può modificare coordinate o misure: se Ollama è spento o risponde male,
il risultato deterministico resta valido così com'è.
"""
from __future__ import annotations

from typing import Any

from backend.geometry.rooms import ALLOWED_TYPES
from backend.models import PlanModel

INTERPRETER_VERSION = "ge360-survey-interpreter-v1"

SYSTEM_PROMPT = f"""Sei l'assistente tecnico di un'impresa edile italiana che fa rilievi di appartamenti.
Ricevi una planimetria GIÀ CALCOLATA (misure in metri, aree in m²) con stanze, aperture, note e avvisi.
Compiti:
1. Per ogni stanza con nome generico ("Ambiente N") proponi un nome e un tipo plausibili
   usando note, dimensioni, aperture e adiacenze. Tipi ammessi: {", ".join(sorted(ALLOWED_TYPES))}.
   Se non sei ragionevolmente sicuro usa tipo "altro" e lascia il nome generico.
2. Riformula avvisi e incoerenze in domande brevi e pratiche per chi ha misurato (massimo 6).
3. Scrivi un riassunto di 1-2 frasi del rilievo.
Regole: non inventare misure, non cambiare numeri, non proporre geometria.
Rispondi SOLO con JSON:
{{"rooms":[{{"roomId":"...","name":"...","type":"..."}}],"questions":["..."],"summary":"..."}}
"""


def build_context(model: PlanModel) -> dict[str, Any]:
    return {
        "plan": model.name,
        "notes": model.notes[:30],
        "warnings": model.warnings[:20],
        "rooms": [
            {
                "roomId": r.roomId, "name": r.name, "type": r.type,
                "floorM2": round(r.floorAreaM2, 2), "sizeM": [r.widthM, r.depthM],
                "doors": sum(1 for o in r.openings if o.type == "door"),
                "windows": sum(1 for o in r.openings if o.type == "window"),
                "adjacent": r.adjacentRoomIds, "questions": r.questions,
            }
            for r in model.rooms
        ],
    }


def interpret(client, model: PlanModel) -> dict[str, Any]:
    """Ritorna {"available", "roomHints", "questions", "summary"}; mai eccezioni."""
    result: dict[str, Any] = {"available": False, "version": INTERPRETER_VERSION,
                              "roomHints": {}, "questions": [], "summary": None}
    try:
        reply = client.propose(SYSTEM_PROMPT, build_context(model))
    except Exception as exc:  # pragma: no cover - difesa
        result["error"] = str(exc)
        return result
    if not isinstance(reply, dict):
        return result
    result["available"] = True
    known = {r.roomId: r for r in model.rooms}
    for row in reply.get("rooms") or []:
        if not isinstance(row, dict) or row.get("roomId") not in known:
            continue
        name = str(row.get("name") or "").strip()[:60]
        room_type = str(row.get("type") or "").strip().lower()
        hint = {}
        if name:
            hint["name"] = name
        if room_type in ALLOWED_TYPES:
            hint["type"] = room_type
        if hint:
            result["roomHints"][row["roomId"]] = hint
    result["questions"] = [str(q).strip()[:300] for q in (reply.get("questions") or []) if str(q).strip()][:6]
    summary = reply.get("summary")
    result["summary"] = str(summary).strip()[:600] if summary else None
    return result
