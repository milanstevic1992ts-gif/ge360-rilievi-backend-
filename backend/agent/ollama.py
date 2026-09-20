from __future__ import annotations

import json

import httpx


class OllamaClient:
    def __init__(self, url: str, model: str, timeout: float = 20.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def propose(self, system_prompt: str, context: dict) -> dict | None:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "options": {"temperature": 0.05},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.url + "/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            content = ((body.get("message") or {}).get("content") or "").strip()
            return json.loads(content) if content else None
        except Exception:
            return None
