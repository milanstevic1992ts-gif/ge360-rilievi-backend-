from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.cad.renderer import model_bounds, point_along, wall_unit
from backend.documents.usage_terms import append_usage_terms_page
from backend.models import PlanModel

BRAND_NAME = os.getenv("GE360_BRAND_NAME", "EDIL MILAN STEVIC")
BRAND_SUBTITLE = os.getenv("GE360_BRAND_SUBTITLE", "Restauri & Costruzioni · Trieste e provincia")
BRAND_TAGLINE = os.getenv("GE360_BRAND_TAGLINE", "Un artigiano, un unico referente")
BRAND_LOGO = os.getenv("GE360_BRAND_LOGO", "").strip()


def _m(mm: float) -> str:
    return f"{mm / 1000:.3f}".replace(".", ",") + " m"


def _draw_brand(c, pw: float, ph: float, margin: float, title: str) -> None:
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.rect(0, ph - 70, pw, 70, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(margin, ph - 25, BRAND_NAME)
    c.setFont("Helvetica", 8)
    c.drawString(margin, ph - 39, BRAND_SUBTITLE)
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(margin, ph - 53, BRAND_TAGLINE)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(pw - margin, ph - 27, title)
    c.setFont("Helvetica", 7)
    c.drawRightString(pw - margin, ph - 42, datetime.now().strftime("%d/%m/%Y %H:%M"))
    if BRAND_LOGO:
        p = Path(BRAND_LOGO)
        if p.is_file():
            try:
                c.drawImage(ImageReader(str(p)), pw - margin - 74, ph - 62, 68, 48, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass


def _dimension_wall(c, pt, wall, scale: float) -> None:
    ux, uy, _ = wall_unit(wall)
    nx, ny = -uy, ux
    offset = wall.thicknessMm / 2 + 220
    a0 = (wall.start.x + nx * offset, wall.start.y + ny * offset)
    b0 = (wall.end.x + nx * offset, wall.end.y + ny * offset)
    a = pt(*a0)
    b = pt(*b0)
    wa = pt(wall.start.x, wall.start.y)
    wb = pt(wall.end.x, wall.end.y)
    c.setStrokeColorRGB(0.25, 0.29, 0.36)
    c.setLineWidth(0.45)
    c.line(wa[0], wa[1], a[0], a[1])
    c.line(wb[0], wb[1], b[0], b[1])
    c.line(a[0], a[1], b[0], b[1])
    tick = 4
    c.line(a[0] - ny * tick, a[1] + nx * tick, a[0] + ny * tick, a[1] - nx * tick)
    c.line(b[0] - ny * tick, b[1] + nx * tick, b[0] + ny * tick, b[1] - nx * tick)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    label = _m(wall.calculatedLengthMm)
    c.setFillColorRGB(0.12, 0.16, 0.23)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(mx, my + 3, label)


def export_pdf(model: PlanModel, path: Path) -> None:
    page = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=page, pageCompression=0)
    pw, ph = page
    margin = 34
    _draw_brand(c, pw, ph, margin, f"{model.name} · RILIEVO TECNICO")

    plan_left = margin
    plan_bottom = 45
    plan_right = pw * 0.69
    plan_top = ph - 88
    panel_left = plan_right + 18
    panel_right = pw - margin

    b = model_bounds(model, margin_mm=1050)
    scale = min((plan_right - plan_left) / b.width, (plan_top - plan_bottom) / b.height)
    ox = plan_left + ((plan_right - plan_left) - b.width * scale) / 2 - b.min_x * scale
    oy = plan_bottom + ((plan_top - plan_bottom) - b.height * scale) / 2 - b.min_y * scale

    def pt(x, y):
        return ox + x * scale, oy + y * scale

    # room fills
    fills = [(0.94, 0.97, 1), (0.94, 1, 0.96), (1, 0.98, 0.92), (0.98, 0.95, 1)]
    for idx, room in enumerate(model.rooms):
        if len(room.polygon) < 3:
            continue
        c.setFillColorRGB(*fills[idx % len(fills)])
        p = c.beginPath()
        x0, y0 = pt(room.polygon[0].x, room.polygon[0].y)
        p.moveTo(x0, y0)
        for q in room.polygon[1:]:
            x, y = pt(q.x, q.y)
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    wall_map = {w.id: w for w in model.walls}
    c.setStrokeColorRGB(0.06, 0.09, 0.16)
    for w in model.walls:
        c.setLineWidth(max(1.4, w.thicknessMm * scale))
        c.line(*pt(w.start.x, w.start.y), *pt(w.end.x, w.end.y))

    # opening voids
    c.setStrokeColorRGB(1, 1, 1)
    for o in model.openings:
        w = wall_map.get(o.wallId)
        if not w:
            continue
        p1 = point_along(w, o.centerFromStartMm - o.widthMm / 2)
        p2 = point_along(w, o.centerFromStartMm + o.widthMm / 2)
        c.setLineWidth(max(2.5, (w.thicknessMm + 22) * scale))
        c.line(*pt(*p1), *pt(*p2))

    # opening symbols and position quotes
    for o in model.openings:
        w = wall_map.get(o.wallId)
        if not w:
            continue
        ux, uy, _ = wall_unit(w)
        nx, ny = -uy, ux
        p1 = point_along(w, o.centerFromStartMm - o.widthMm / 2)
        p2 = point_along(w, o.centerFromStartMm + o.widthMm / 2)
        c.setStrokeColorRGB(0.08, 0.55, 0.42) if o.type == "door" else c.setStrokeColorRGB(0.03, 0.45, 0.65)
        c.setLineWidth(0.9)
        c.line(*pt(*p1), *pt(*p2))
        lx, ly = pt(o.center.x + nx * (w.thicknessMm / 2 + 115), o.center.y + ny * (w.thicknessMm / 2 + 115))
        ref = "A" if o.referenceEnd == "a" else "B"
        code = "P" if o.type == "door" else "F"
        label = f"{code} {_m(o.widthMm)} · {ref}→{_m(o.offsetMm)}"
        if o.type == "window":
            label += f" · h {_m(o.heightMm)} · dav. {_m(o.sillHeightMm)}"
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica", 5.7)
        c.drawCentredString(lx, ly, label)

    for w in model.walls:
        _dimension_wall(c, pt, w, scale)

    # room labels
    for room in model.rooms:
        if not room.polygon:
            continue
        cx = sum(p.x for p in room.polygon) / len(room.polygon)
        cy = sum(p.y for p in room.polygon) / len(room.polygon)
        x, y = pt(cx, cy)
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(x, y + 5, room.name)
        c.setFont("Helvetica", 7)
        c.drawCentredString(x, y - 6, f"{room.floorAreaM2:.2f} m² · {room.widthM:.2f} × {room.depthM:.2f} m")

    # right summary panel
    c.setFillColorRGB(0.97, 0.98, 0.99)
    c.roundRect(panel_left, plan_bottom, panel_right - panel_left, plan_top - plan_bottom, 10, stroke=0, fill=1)
    x = panel_left + 12
    y = plan_top - 18
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, "RIEPILOGO STANZE")
    y -= 16
    total_floor = 0.0
    for room in model.rooms:
        total_floor += room.floorAreaM2
        if y < plan_bottom + 80:
            break
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(x, y, room.name[:28])
        c.setFont("Helvetica", 6.5)
        c.drawRightString(panel_right - 12, y, f"{room.floorAreaM2:.2f} m²")
        y -= 10
        lengths = " · ".join(_m(face.lengthMm) for face in room.wallFaces[:6])
        c.setFillColorRGB(0.35, 0.39, 0.47)
        c.setFont("Helvetica", 5.5)
        c.drawString(x, y, ("Lati: " + lengths)[:58])
        c.setFillColorRGB(0.06, 0.09, 0.16)
        y -= 13
    c.setStrokeColorRGB(0.78, 0.82, 0.88)
    c.line(x, y, panel_right - 12, y)
    y -= 15
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, "Superficie totale")
    c.drawRightString(panel_right - 12, y, f"{total_floor:.2f} m²")
    y -= 18
    c.setFont("Helvetica", 6.2)
    c.drawString(x, y, f"Porte: {sum(1 for o in model.openings if o.type == 'door')}  ·  Finestre: {sum(1 for o in model.openings if o.type == 'window')}")
    y -= 11
    c.drawString(x, y, f"Pareti nette: {sum(r.netWallAreaM2 for r in model.rooms):.2f} m²")
    y -= 11
    c.drawString(x, y, f"Pavimenti: {sum(r.floorAreaM2 for r in model.rooms):.2f} m²")

    c.setFillColorRGB(0.35, 0.39, 0.47)
    c.setFont("Helvetica", 5.5)
    c.drawString(margin, 21, "Quote in metri · geometria autorevole dal backend GE360 · verificare in cantiere gli elementi marcati DA VERIFICARE")
    c.drawRightString(pw - margin, 21, BRAND_TAGLINE)
    c.showPage()

    # Page 2: room schedule
    _draw_brand(c, pw, ph, margin, f"{model.name} · COMPUTO STANZE")
    y = ph - 92
    cols = [margin, 190, 250, 315, 380, 450, 520, 600, pw - margin]
    headers = ["Ambiente", "Pav.", "Perim.", "Pareti nette", "Soffitto", "Battisc.", "Volume", "Aperture"]
    c.setFillColorRGB(0.92, 0.94, 0.97)
    c.rect(margin, y - 14, pw - 2 * margin, 19, stroke=0, fill=1)
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.setFont("Helvetica-Bold", 6.8)
    for i, h in enumerate(headers):
        c.drawString(cols[i] + 3, y - 7, h)
    y -= 22
    c.setFont("Helvetica", 6.6)
    for room in model.rooms:
        vals = [
            room.name,
            f"{room.floorAreaM2:.2f} m²",
            f"{room.perimeterM:.2f} m",
            f"{room.netWallAreaM2:.2f} m²",
            f"{room.ceilingAreaM2:.2f} m²",
            f"{room.skirtingM:.2f} m",
            f"{room.volumeM3:.2f} m³",
            str(len(room.openings)),
        ]
        for i, v in enumerate(vals):
            c.drawString(cols[i] + 3, y, str(v)[:24])
        c.setStrokeColorRGB(0.88, 0.90, 0.93)
        c.line(margin, y - 4, pw - margin, y - 4)
        y -= 16
        if y < 55:
            c.showPage()
            _draw_brand(c, pw, ph, margin, f"{model.name} · COMPUTO STANZE")
            y = ph - 92
    c.setFillColorRGB(0.35, 0.39, 0.47)
    c.setFont("Helvetica", 5.8)
    c.drawString(margin, 25, "Documento generato dal backend GE360 Rilievi")

    append_usage_terms_page(
        c,
        document_name=model.name,
        brand_name=BRAND_NAME,
        brand_subtitle=BRAND_SUBTITLE,
        brand_tagline=BRAND_TAGLINE,
    )
    c.save()
