from __future__ import annotations

import base64
import json
from io import BytesIO

import qrcode

PAIRING_FORMAT = "GE360_DIRECT_BRIDGE_V1"

def qr_png_base64(text: str) -> str:
    image = qrcode.make(text)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")

def wireguard_qr_png_base64(config_text: str) -> str:
    return qr_png_base64(config_text)

def ge360_pairing_payload(*, wireguard_config: str, backend_url: str, api_key: str, device_id: str) -> dict:
    return {
        "format": PAIRING_FORMAT,
        "version": 1,
        "device_id": device_id,
        "backend_url": backend_url,
        "api_key": api_key,
        "pairing": {
            "wireguard_config": wireguard_config,
            "backend_url": backend_url,
        },
    }

def ge360_pairing_text(*, wireguard_config: str, backend_url: str, api_key: str, device_id: str) -> str:
    return json.dumps(
        ge360_pairing_payload(
            wireguard_config=wireguard_config,
            backend_url=backend_url,
            api_key=api_key,
            device_id=device_id,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

def ge360_pairing_qr_png_base64(*, wireguard_config: str, backend_url: str, api_key: str, device_id: str) -> str:
    return qr_png_base64(
        ge360_pairing_text(
            wireguard_config=wireguard_config,
            backend_url=backend_url,
            api_key=api_key,
            device_id=device_id,
        )
    )
