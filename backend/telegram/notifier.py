from __future__ import annotations

from pathlib import Path

import httpx


class TelegramNotifier:
    def __init__(self, enabled: bool, bot_token: str, chat_id: str, public_base_url: str = ""):
        self.enabled = enabled and bool(bot_token and chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.public_base_url = public_base_url.rstrip("/")

    def send_processed(self, *, plan_id: str, name: str, room_count: int, area_m2: float,
                       status: str, files_dir: Path) -> dict:
        if not self.enabled:
            return {"sent": False, "reason": "disabled"}
        base = f"https://api.telegram.org/bot{self.bot_token}"
        text = f"GE360 RILIEVO\n{name}\n\n✅ Elaborazione completata\n\nAmbienti: {room_count}\nSuperficie: {area_m2:.1f} m²\nStato: {status}"
        if self.public_base_url and (files_dir / "plan.glb").exists():
            text += f"\n\nVISTA 3D: {self.public_base_url}/viewer/?glb={self.public_base_url}/api/v1/plans/{plan_id}/glb"
        try:
            with httpx.Client(timeout=20) as client:
                client.post(base + "/sendMessage", data={"chat_id": self.chat_id, "text": text}).raise_for_status()
                for filename in ("preview.png", "plan.pdf", "plan.dxf"):
                    path = files_dir / filename
                    if not path.exists():
                        continue
                    with path.open("rb") as fh:
                        response = client.post(base + "/sendDocument", data={"chat_id": self.chat_id}, files={"document": (filename, fh)})
                        response.raise_for_status()
            return {"sent": True}
        except Exception as exc:
            return {"sent": False, "reason": str(exc)}
