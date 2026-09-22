#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] GE360 Control assets: {message}")


root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
html_path = root / "control" / "index.html"
js_path = root / "control" / "control.js"
css_path = root / "control" / "control.css"

for path in (html_path, js_path, css_path):
    if not path.is_file():
        fail(f"missing {path}")

html = html_path.read_text(encoding="utf-8")
js = js_path.read_text(encoding="utf-8")

required_html = (
    'data-view="settings"',
    'id="view-settings"',
    'id="settingsPairBtn"',
    'id="settingsPairQr"',
    'id="settingsDevices"',
)
required_js = (
    "async function pairSettingsDevice()",
    "$('#settingsPairBtn').onclick=pairSettingsDevice",
    "settingsApi('/bridge/devices'",
    "qr_png_base64",
)
for marker in required_html:
    if marker not in html:
        fail(f"index.html missing {marker}")
for marker in required_js:
    if marker not in js:
        fail(f"control.js missing {marker}")

html_build = re.search(r'<meta name="ge360-control-build" content="([^"]+)"', html)
js_build = re.search(r"const CONTROL_BUILD='([^']+)'", js)
if not html_build or not js_build:
    fail("missing Control build markers")
if html_build.group(1) != js_build.group(1):
    fail(f"build mismatch html={html_build.group(1)} js={js_build.group(1)}")

build = html_build.group(1)
if f"/control/control.js?v={build}" not in html:
    fail("index.html does not cache-bust control.js with the current build")
if f"/control/control.css?v={build}" not in html:
    fail("index.html does not cache-bust control.css with the current build")

print(f"[OK] GE360 Control assets aligned · build {build}")
