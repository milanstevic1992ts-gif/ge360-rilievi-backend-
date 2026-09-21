from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
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
    # GE360 reports use A4 portrait as the canonical print/export format.
    page = A4
    c = canvas.Canvas(str(path), pagesize=page, pageCompression=0)
    pw, ph = page
    margin = 34
    _draw_brand(c, pw, ph, margin, f"{model.name} · RILIEVO TECNICO")

    # Portrait-first composition: the drawing gets the full page width and
    # the summary is placed underneath instead of squeezing the plan sideways.
    plan_left = margin
    plan_bottom = 320
    plan_right = pw - margin
    plan_top = ph - 88
    panel_left = margin
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

    # Lower summary area: two balanced cards, optimized for A4 portrait.
    summary_top = plan_bottom - 14
    summary_bottom = 52
    gap = 10
    summary_width = panel_right - panel_left
    rooms_right = panel_left + summary_width * 0.61
    metrics_left = rooms_right + gap

    c.setFillColorRGB(0.97, 0.98, 0.99)
    c.roundRect(
        panel_left,
        summary_bottom,
        rooms_right - panel_left,
        summary_top - summary_bottom,
        10,
        stroke=0,
        fill=1,
    )
    c.roundRect(
        metrics_left,
        summary_bottom,
        panel_right - metrics_left,
        summary_top - summary_bottom,
        10,
        stroke=0,
        fill=1,
    )

    # Room overview card.
    x = panel_left + 12
    y = summary_top - 18
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x, y, "RIEPILOGO AMBIENTI")
    y -= 15
    total_floor = sum(room.floorAreaM2 for room in model.rooms)
    available_rows = max(1, int((y - summary_bottom - 22) / 19))
    shown_rooms = model.rooms[:available_rows]
    for room in shown_rooms:
        c.setFont("Helvetica-Bold", 7.2)
        c.drawString(x, y, room.name[:27])
        c.setFont("Helvetica", 6.6)
        c.drawRightString(rooms_right - 12, y, f"{room.floorAreaM2:.2f} m²")
        y -= 9
        dims = f"{room.widthM:.2f} × {room.depthM:.2f} m · perim. {room.perimeterM:.2f} m"
        c.setFillColorRGB(0.35, 0.39, 0.47)
        c.setFont("Helvetica", 5.6)
        c.drawString(x, y, dims[:52])
        c.setFillColorRGB(0.06, 0.09, 0.16)
        y -= 10
    remaining = len(model.rooms) - len(shown_rooms)
    if remaining > 0:
        c.setFillColorRGB(0.35, 0.39, 0.47)
        c.setFont("Helvetica-Oblique", 5.8)
        c.drawString(x, max(summary_bottom + 12, y), f"+ {remaining} ambienti nel computo dettagliato")

    # Key figures card.
    mx = metrics_left + 12
    my = summary_top - 18
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(mx, my, "DATI PRINCIPALI")
    my -= 20
    metrics = [
        ("Superficie totale", f"{total_floor:.2f} m²"),
        ("Pareti nette", f"{sum(r.netWallAreaM2 for r in model.rooms):.2f} m²"),
        ("Ambienti", str(len(model.rooms))),
        ("Porte", str(sum(1 for o in model.openings if o.type == "door"))),
        ("Finestre", str(sum(1 for o in model.openings if o.type == "window"))),
    ]
    for label, value in metrics:
        c.setFillColorRGB(0.35, 0.39, 0.47)
        c.setFont("Helvetica", 6.2)
        c.drawString(mx, my, label)
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(panel_right - 12, my, value)
        my -= 18

    c.setFillColorRGB(0.35, 0.39, 0.47)
    c.setFont("Helvetica", 5.5)
    c.drawString(margin, 21, "Quote in metri · geometria autorevole dal backend GE360 · verificare in cantiere gli elementi marcati DA VERIFICARE")
    c.drawRightString(pw - margin, 21, BRAND_TAGLINE)
    c.showPage()

    # Page 2+: room schedule, redesigned as readable portrait cards.
    c.setPageSize(page)
    _draw_brand(c, pw, ph, margin, f"{model.name} · COMPUTO STANZE")
    y = ph - 94

    c.setFillColorRGB(0.35, 0.39, 0.47)
    c.setFont("Helvetica", 6.2)
    c.drawString(
        margin,
        y,
        "Misure e quantità principali per ambiente. Le quote restano soggette a verifica diretta in cantiere.",
    )
    y -= 18

    card_w = pw - 2 * margin
    card_h = 48
    card_gap = 8

    for room in model.rooms:
        if y - card_h < 48:
            c.showPage()
            c.setPageSize(page)
            _draw_brand(c, pw, ph, margin, f"{model.name} · COMPUTO STANZE")
            y = ph - 94

        c.setFillColorRGB(0.97, 0.98, 0.99)
        c.roundRect(margin, y - card_h, card_w, card_h, 8, stroke=0, fill=1)

        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margin + 11, y - 14, room.name[:42])
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(pw - margin - 11, y - 14, f"{room.floorAreaM2:.2f} m²")

        c.setFont("Helvetica", 6.2)
        c.setFillColorRGB(0.25, 0.29, 0.36)
        line1 = (
            f"Perimetro {room.perimeterM:.2f} m  ·  Pareti nette {room.netWallAreaM2:.2f} m²"
            f"  ·  Soffitto {room.ceilingAreaM2:.2f} m²"
        )
        c.drawString(margin + 11, y - 28, line1)

        line2 = (
            f"Battiscopa {room.skirtingM:.2f} m  ·  Volume {room.volumeM3:.2f} m³"
            f"  ·  Aperture {len(room.openings)}  ·  Ingombro {room.widthM:.2f} × {room.depthM:.2f} m"
        )
        c.drawString(margin + 11, y - 39, line2)
        y -= card_h + card_gap

    c.setFillColorRGB(0.35, 0.39, 0.47)
    c.setFont("Helvetica", 5.8)
    c.drawString(margin, 25, "Documento A4 verticale generato dal backend GE360 Rilievi")

    works = list(model.metadata.get("works") or [])
    if works:
        c.showPage()
        c.setPageSize(page)
        _draw_brand(c, pw, ph, margin, f"{model.name} · LAVORAZIONI RILEVATE")
        y = ph - 96
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, "LAVORAZIONI RILEVATE IN CANTIERE")
        y -= 17
        c.setFont("Helvetica", 6.2)
        c.setFillColorRGB(0.35, 0.39, 0.47)
        c.drawString(margin, y, "Le quantità sono ricavate dalla geometria GE360 quando disponibile; le voci manuali restano da verificare.")
        y -= 20

        grouped = {}
        for row in works:
            names = row.get("targetNames") or []
            target = ", ".join(names) if names else ("TUTTA LA CASA" if row.get("targetType") == "plan" else "ALTRO")
            grouped.setdefault(target, []).append(row)

        for target, rows in grouped.items():
            if y < 92:
                c.showPage()
                c.setPageSize(page)
                _draw_brand(c, pw, ph, margin, f"{model.name} · LAVORAZIONI RILEVATE")
                y = ph - 96
            c.setFillColorRGB(0.06, 0.09, 0.16)
            c.setFont("Helvetica-Bold", 8.3)
            c.drawString(margin, y, target.upper()[:70])
            y -= 13
            for row in rows:
                if y < 72:
                    c.showPage()
                    c.setPageSize(page)
                    _draw_brand(c, pw, ph, margin, f"{model.name} · LAVORAZIONI RILEVATE")
                    y = ph - 96
                qty = row.get("quantity")
                unit = row.get("unit") or ""
                qty_text = "DA VERIFICARE" if qty is None else f"{qty:.2f} {unit}".replace(".", ",")
                c.setFillColorRGB(0.10, 0.14, 0.20)
                c.setFont("Helvetica", 7)
                c.drawString(margin + 8, y, str(row.get("label") or "")[:72])
                c.setFont("Helvetica-Bold", 7)
                c.drawRightString(pw - margin, y, qty_text)
                note = str(row.get("note") or "").strip()
                if note:
                    y -= 9
                    c.setFillColorRGB(0.38, 0.42, 0.49)
                    c.setFont("Helvetica-Oblique", 5.8)
                    c.drawString(margin + 14, y, note[:105])
                y -= 12
            y -= 5

    append_usage_terms_page(
        c,
        document_name=model.name,
        brand_name=BRAND_NAME,
        brand_subtitle=BRAND_SUBTITLE,
        brand_tagline=BRAND_TAGLINE,
    )
    c.save()
