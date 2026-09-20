from __future__ import annotations

from backend.agent.ollama import OllamaClient


NOTE_SYSTEM_PROMPT = """Sei l'assistente tecnico di un artigiano edile.
Riscrivi appunti grezzi di cantiere in italiano chiaro e professionale.
Non inventare lavorazioni, misure, quantità, materiali, cause, prezzi o dettagli.
Mantieni esattamente tutti i numeri e le misure. Se qualcosa è ambiguo, inseriscilo in needsClarification.
Restituisci solo JSON: {"cleanedText":"...","tasks":["..."],"needsClarification":["..."]}.
"""


def rewrite_note(client: OllamaClient, request: dict) -> dict | None:
    return client.propose(NOTE_SYSTEM_PROMPT, request)
