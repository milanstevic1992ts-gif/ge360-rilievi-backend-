from __future__ import annotations

import base64
from io import BytesIO

import qrcode


def wireguard_qr_png_base64(config_text: str) -> str:
    image = qrcode.make(config_text)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
