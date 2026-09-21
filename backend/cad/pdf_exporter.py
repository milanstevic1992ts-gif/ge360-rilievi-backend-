from __future__ import annotations

import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from backend.cad.renderer import model_bounds, point_along, wall_unit
from backend.documents.usage_terms import append_usage_terms_page
from backend.models import PlanModel

MM = 72.0 / 25.4

BLUE = (23 / 255, 54 / 255, 93 / 255)
ORANGE = (242 / 255, 140 / 255, 40 / 255)
CHARCOAL = (47 / 255, 53 / 255, 64 / 255)
LIGHT = (243 / 255, 246 / 255, 248 / 255)
LINE = (217 / 255, 222 / 255, 227 / 255)
WHITE = (1, 1, 1)
MUTED = (0.40, 0.44, 0.50)

BRAND_NAME = os.getenv("GE360_BRAND_NAME", "EDIL MILAN STEVIC")
BRAND_SUBTITLE = os.getenv("GE360_BRAND_SUBTITLE", "Restauri & Costruzioni - Trieste e provincia")
BRAND_TAGLINE = os.getenv("GE360_BRAND_TAGLINE", "Un artigiano, un unico referente")
BRAND_LOGO = os.getenv(
    "GE360_BRAND_LOGO",
    "/opt/ge360/ge360-rilievi-backend/assets/branding/logo-edil-milan-stevic.jpg",
).strip()
BRAND_WHATSAPP_URL = os.getenv("GE360_BRAND_WHATSAPP_URL", "").strip()
BRAND_SITE_URL = os.getenv("GE360_BRAND_SITE_URL", "").strip()

COVER_INTRO = (
    "Ogni progetto ben riuscito comincia prima dei lavori: dal primo sopralluogo, "
    "dall'ascolto delle esigenze e da misure prese con cura. Questo rilievo è il "
    "punto di partenza su cui costruiamo insieme scelte, soluzioni e tempi, "
    "accompagnandovi passo dopo passo fino alla realizzazione."
)

COVER_VALUES = (
    (
        "Ascolto",
        "Il progetto parte da voi: da come vivete gli spazi, da cosa vorreste cambiare "
        "e da ciò che è importante conservare. Ogni misura raccolta serve a trasformare "
        "queste esigenze in soluzioni concrete.",
    ),
    (
        "Precisione",
        "Rilevare con attenzione ambienti, aperture e altezze permette di progettare "
        "senza sorprese, valutare correttamente materiali e superfici e ridurre "
        "imprevisti in cantiere.",
    ),
    (
        "Accompagnamento",
        "Dal rilievo alla progettazione, fino alla scelta delle finiture, vi seguiamo "
        "in ogni fase con un unico riferimento, così che ogni decisione sia chiara e condivisa.",
    ),
)

ESTIMATED_NOTE = (
    "* Misura ricavata per calcolo dalle altre dimensioni rilevate. "
    "Da verificare in loco prima di ordini o lavorazioni."
)


class NumberedCanvas(canvas.Canvas):
    """Canvas that adds the common footer once the final page count is known."""

    def __init__(self, *args, reference: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self._reference = reference

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        self._saved_page_states.append(dict(self.__dict__))
        page_count = len(self._saved_page_states)
        for page_num, state in enumerate(self._saved_page_states, 1):
            self.__dict__.update(state)
            if page_num > 1:
                self._draw_common_footer(page_num, page_count)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_common_footer(self, page_num: int, page_count: int) -> None:
        pw, _ = self._pagesize
        margin = 15 * MM
        self.setStrokeColorRGB(*LINE)
        self.setLineWidth(0.6)
        self.line(margin, 42, pw - margin, 42)
        self.setStrokeColorRGB(*ORANGE)
        self.setLineWidth(1.8)
        self.line(margin, 42, margin + 28, 42)

        self.setFillColorRGB(*MUTED)
        self.setFont("Helvetica", 7.5)
        self.drawString(margin, 27, f"{BRAND_NAME} - Restauri & Costruzioni")
        self.setFillColorRGB(*BLUE)
        self.setFont("Helvetica-Oblique", 7.5)
        self.drawCentredString(pw / 2, 27, "Misure precise, progetto chiaro.")
        self.setFillColorRGB(*MUTED)
        self.setFont("Helvetica", 7.5)
        ref = f"Rif. {self._reference} | " if self._reference else ""
        self.drawRightString(pw - margin, 27, f"{ref}Pagina {page_num} di {page_count}")


def _m(mm: float, digits: int = 3) -> str:
    return f"{mm / 1000:.{digits}f}".replace(".", ",") + " m"


def _m2(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " m²"


def _fmt_date(raw: Any) -> str:
    if raw in (None, ""):
        return datetime.now().strftime("%d/%m/%Y")
    text = str(raw).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return text[:24]


def _document_meta(model: PlanModel) -> dict[str, Any]:
    meta = dict(model.metadata.get("document") or {})
    meta.setdefault("reference", model.planId)
    meta.setdefault("surveyDate", datetime.now().isoformat())
    if not meta.get("whatsappUrl") and BRAND_WHATSAPP_URL:
        meta["whatsappUrl"] = BRAND_WHATSAPP_URL
    if not meta.get("siteUrl") and BRAND_SITE_URL:
        meta["siteUrl"] = BRAND_SITE_URL
    return meta


def _logo_path() -> Path | None:
    if not BRAND_LOGO:
        return None
    p = Path(BRAND_LOGO)
    return p if p.is_file() else None


def _draw_logo(c, x: float, y: float, w: float, h: float) -> None:
    p = _logo_path()
    if not p:
        return
    try:
        c.drawImage(ImageReader(str(p)), x, y, w, h, preserveAspectRatio=True, mask="auto", anchor="c")
    except Exception:
        pass


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped(
    c,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 9.5,
    leading: float = 13,
    color=CHARCOAL,
    max_lines: int | None = None,
) -> float:
    c.setFillColorRGB(*color)
    c.setFont(font, size)
    lines = _wrap(text, font, size, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line_text in lines:
        c.drawString(x, y, line_text)
        y -= leading
    return y


def _draw_internal_header(c, model: PlanModel, pw: float, ph: float) -> float:
    meta = _document_meta(model)
    mx = 15 * MM
    y = ph - 18 * MM + 10
    _draw_logo(c, mx, y - 13, 34, 24)
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(mx + 40, y, BRAND_NAME)
    c.setFillColorRGB(*CHARCOAL)
    c.setFont("Helvetica", 7.5)
    c.drawRightString(
        pw - mx,
        y,
        f"Rif. {meta.get('reference', model.planId)} | {_fmt_date(meta.get('surveyDate'))}",
    )
    c.setStrokeColorRGB(*LINE)
    c.setLineWidth(0.7)
    c.line(mx, y - 10, pw - mx, y - 10)
    c.setStrokeColorRGB(*ORANGE)
    c.setLineWidth(1.8)
    c.line(mx, y - 10, mx + 28, y - 10)
    return y - 26


def _draw_section_title(c, x: float, y: float, number: str, title: str) -> float:
    c.setFillColorRGB(*ORANGE)
    c.rect(x, y - 3, 3, 20, stroke=0, fill=1)
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(x + 10, y, f"{number}  {title}")
    return y - 28


def _draw_qr(c, value: str, x: float, y: float, size: float) -> bool:
    if not value:
        return False
    try:
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF

        code = qr.QrCodeWidget(value)
        bounds = code.getBounds()
        bw = bounds[2] - bounds[0]
        bh = bounds[3] - bounds[1]
        drawing = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
        drawing.add(code)
        renderPDF.draw(drawing, c, x, y)
        return True
    except Exception:
        return False


def _draw_cover(c, model: PlanModel) -> None:
    c.setPageSize(A4)
    pw, ph = A4
    mx = 15 * MM
    meta = _document_meta(model)

    # Compact brand header.
    header_h = 74
    c.setFillColorRGB(*BLUE)
    c.rect(0, ph - header_h, pw, header_h, stroke=0, fill=1)
    c.setFillColorRGB(*ORANGE)
    c.rect(0, ph - header_h, 4, header_h, stroke=0, fill=1)

    _draw_logo(c, mx, ph - 62, 52, 42)
    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica-Bold", 12.5)
    c.drawString(mx + 60, ph - 27, BRAND_NAME)
    c.setFont("Helvetica", 8)
    c.drawString(mx + 60, ph - 41, "Restauri & Costruzioni")
    c.drawString(mx + 60, ph - 53, "Trieste e provincia")
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(mx + 60, ph - 65, BRAND_TAGLINE)

    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(pw - mx, ph - 27, "RILIEVO")
    c.setFont("Helvetica", 7.5)
    c.drawRightString(pw - mx, ph - 42, f"Rif. {meta.get('reference', model.planId)}")
    c.drawRightString(pw - mx, ph - 55, _fmt_date(meta.get("surveyDate")))

    # Main title.
    y = ph - 118
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 25)
    c.drawString(mx, y, "RILIEVO METRICO E PLANIMETRIA")
    y -= 24
    object_text = str(meta.get("address") or model.name)
    c.setFillColorRGB(*CHARCOAL)
    c.setFont("Helvetica", 10)
    c.drawString(mx, y, object_text[:92])
    y -= 13
    c.setStrokeColorRGB(*ORANGE)
    c.setLineWidth(2.2)
    c.line(mx, y, mx + 74, y)
    y -= 24

    # Survey data.
    data_h = 104
    c.setFillColorRGB(*LIGHT)
    c.roundRect(mx, y - data_h, pw - 2 * mx, data_h, 7, stroke=0, fill=1)
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(mx + 12, y - 18, "DATI RILIEVO")

    fields = []
    for label, key in (
        ("Cliente", "client"),
        ("Indirizzo", "address"),
        ("Data sopralluogo", "surveyDate"),
        ("Riferimento rilievo", "reference"),
        ("Preventivo collegato", "linkedQuote"),
    ):
        value = meta.get(key)
        if value not in (None, ""):
            fields.append((label, _fmt_date(value) if key == "surveyDate" else str(value)))
    fields.insert(2 if len(fields) >= 2 else len(fields), ("Ambienti rilevati", str(len(model.rooms))))

    left_x = mx + 12
    col_w = (pw - 2 * mx - 28) / 2
    row_y = y - 36
    for idx, (label, value) in enumerate(fields[:6]):
        col = idx % 2
        row = idx // 2
        xx = left_x + col * (col_w + 8)
        yy = row_y - row * 22
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 6.8)
        c.drawString(xx, yy, label.upper())
        c.setFillColorRGB(*CHARCOAL)
        c.setFont("Helvetica", 8.5)
        c.drawString(xx, yy - 10, value[:48])
    y -= data_h + 14

    totals = (
        sum(room.floorAreaM2 for room in model.rooms),
        sum(room.netWallAreaM2 for room in model.rooms),
        sum(room.ceilingAreaM2 for room in model.rooms),
    )
    labels = ("PAVIMENTO TOTALE", "PARETI TOTALI", "SOFFITTO TOTALE")
    gap = 8
    box_w = (pw - 2 * mx - 2 * gap) / 3
    box_h = 60
    for idx, (label, value) in enumerate(zip(labels, totals)):
        xx = mx + idx * (box_w + gap)
        c.setFillColorRGB(*WHITE)
        c.setStrokeColorRGB(*LINE)
        c.setLineWidth(0.6)
        c.roundRect(xx, y - box_h, box_w, box_h, 6, stroke=1, fill=1)
        c.setFillColorRGB(*ORANGE)
        c.rect(xx, y - 4, 24, 2, stroke=0, fill=1)
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(xx + 10, y - 26, _m2(value))
        c.setFillColorRGB(*MUTED)
        c.setFont("Helvetica-Bold", 6.6)
        c.drawString(xx + 10, y - 43, label)
    y -= box_h + 17

    y = _draw_wrapped(c, COVER_INTRO, mx, y, pw - 2 * mx, size=9.3, leading=13.2)
    y -= 8

    value_gap = 8
    value_w = (pw - 2 * mx - 2 * value_gap) / 3
    value_h = 112
    for idx, (title, body) in enumerate(COVER_VALUES):
        xx = mx + idx * (value_w + value_gap)
        c.setFillColorRGB(*WHITE)
        c.setStrokeColorRGB(*LINE)
        c.setLineWidth(0.7)
        c.roundRect(xx, y - value_h, value_w, value_h, 6, stroke=1, fill=1)
        c.setFillColorRGB(*ORANGE if idx != 1 else BLUE)
        c.circle(xx + 16, y - 18, 6, stroke=0, fill=1)
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(xx + 28, y - 22, title)
        _draw_wrapped(
            c,
            body,
            xx + 10,
            y - 40,
            value_w - 20,
            size=7.6,
            leading=10.2,
            max_lines=7,
        )

    closing_y = 108
    c.setStrokeColorRGB(*ORANGE)
    c.setLineWidth(1.2)
    c.line(mx + 110, closing_y + 25, pw - mx - 110, closing_y + 25)
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Oblique", 9.2)
    c.drawCentredString(
        pw / 2,
        closing_y + 9,
        "Una buona casa nasce da un buon progetto, e un buon progetto nasce da misure giuste.",
    )

    # Optional QR block, only when the destination is actually configured.
    qr_items = [
        ("WhatsApp", meta.get("whatsappUrl"), "Per chiarimenti sul rilievo o sui prossimi passi."),
        ("Sito", meta.get("siteUrl"), "Scopri i nostri lavori e i servizi disponibili."),
    ]
    qr_items = [item for item in qr_items if item[1]]
    if qr_items:
        qsize = 22 * MM
        start_x = mx
        for idx, (label, url, desc) in enumerate(qr_items[:2]):
            xx = start_x + idx * 180
            if _draw_qr(c, str(url), xx, 20, qsize):
                c.setFillColorRGB(*BLUE)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawString(xx + qsize + 7, 58, label)
                _draw_wrapped(c, desc, xx + qsize + 7, 47, 95, size=6.5, leading=8)


def _wall_dimension_value(wall) -> tuple[float, bool]:
    source = str(getattr(wall, "lengthSource", "MEASURED") or "MEASURED").upper()
    estimated = source in {"CALCULATED", "SKETCH"}
    if source == "SUSPECT_MEASURED" and getattr(wall, "usedLengthMm", None):
        estimated = True
    if estimated:
        value = getattr(wall, "usedLengthMm", None) or wall.calculatedLengthMm
    else:
        value = wall.declaredLengthMm
    return float(value), estimated


def _dimension_wall(c, pt, wall, scale: float, center_xy: tuple[float, float]) -> bool:
    ux, uy, _ = wall_unit(wall)
    nx, ny = -uy, ux
    mxw = (wall.start.x + wall.end.x) / 2
    myw = (wall.start.y + wall.end.y) / 2
    cx, cy = center_xy
    if (mxw - cx) * nx + (myw - cy) * ny < 0:
        nx, ny = -nx, -ny

    offset = wall.thicknessMm / 2 + 250
    a0 = (wall.start.x + nx * offset, wall.start.y + ny * offset)
    b0 = (wall.end.x + nx * offset, wall.end.y + ny * offset)
    a = pt(*a0)
    b = pt(*b0)
    wa = pt(wall.start.x, wall.start.y)
    wb = pt(wall.end.x, wall.end.y)

    value_mm, estimated = _wall_dimension_value(wall)
    c.setStrokeColorRGB(*(ORANGE if estimated else CHARCOAL))
    c.setLineWidth(0.5)
    c.line(wa[0], wa[1], a[0], a[1])
    c.line(wb[0], wb[1], b[0], b[1])
    c.line(a[0], a[1], b[0], b[1])

    tick = 3.5
    c.line(a[0] - ny * tick, a[1] + nx * tick, a[0] + ny * tick, a[1] - nx * tick)
    c.line(b[0] - ny * tick, b[1] + nx * tick, b[0] + ny * tick, b[1] - nx * tick)

    tx, ty = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    c.setFillColorRGB(*(ORANGE if estimated else CHARCOAL))
    c.setFont("Helvetica-Oblique" if estimated else "Helvetica", 7.5)
    label = _m(value_mm) + ("*" if estimated else "")
    c.drawCentredString(tx, ty + 3, label)
    return estimated


def _draw_opening(c, pt, opening, wall, scale: float) -> None:
    ux, uy, _ = wall_unit(wall)
    nx, ny = -uy, ux
    p1 = point_along(wall, opening.centerFromStartMm - opening.widthMm / 2)
    p2 = point_along(wall, opening.centerFromStartMm + opening.widthMm / 2)

    # Clear the wall where the opening sits.
    c.setStrokeColorRGB(*WHITE)
    c.setLineWidth(max(3.0, min(10.0, (wall.thicknessMm + 30) * scale)))
    c.line(*pt(*p1), *pt(*p2))

    c.setStrokeColorRGB(*CHARCOAL)
    c.setLineWidth(1.1)
    a = pt(*p1)
    b = pt(*p2)

    if opening.type == "door":
        # Door leaf plus a light opening arc.
        radius = max(8.0, min(55.0, opening.widthMm * scale))
        hinge = a
        angle = math.degrees(math.atan2(uy, ux))
        leaf_angle = math.radians(angle + 90)
        leaf_end = (hinge[0] + math.cos(leaf_angle) * radius, hinge[1] + math.sin(leaf_angle) * radius)
        c.line(hinge[0], hinge[1], leaf_end[0], leaf_end[1])
        c.setLineWidth(0.7)
        c.arc(hinge[0] - radius, hinge[1] - radius, hinge[0] + radius, hinge[1] + radius, angle, 90)
    else:
        offset = 2.2
        c.line(a[0] + nx * offset, a[1] + ny * offset, b[0] + nx * offset, b[1] + ny * offset)
        c.line(a[0] - nx * offset, a[1] - ny * offset, b[0] - nx * offset, b[1] - ny * offset)


def _draw_scale_bar(c, x: float, y: float, scale: float) -> None:
    choices = (500, 1000, 2000, 5000)
    chosen = min(choices, key=lambda mm: abs(mm * scale - 75))
    width = chosen * scale
    c.setStrokeColorRGB(*CHARCOAL)
    c.setFillColorRGB(*CHARCOAL)
    c.setLineWidth(1)
    c.line(x, y, x + width, y)
    c.line(x, y - 4, x, y + 4)
    c.line(x + width / 2, y - 3, x + width / 2, y + 3)
    c.line(x + width, y - 4, x + width, y + 4)
    c.setFont("Helvetica", 7)
    c.drawString(x, y + 7, "0")
    c.drawCentredString(x + width / 2, y + 7, _m(chosen / 2, 2))
    c.drawRightString(x + width, y + 7, _m(chosen, 2))
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x, y - 13, "Scala grafica")


def _draw_north(c, x: float, y: float, angle_deg: float) -> None:
    c.saveState()
    c.translate(x, y)
    c.rotate(-angle_deg)
    c.setStrokeColorRGB(*BLUE)
    c.setFillColorRGB(*BLUE)
    c.setLineWidth(1)
    c.line(0, -14, 0, 14)
    p = c.beginPath()
    p.moveTo(0, 18)
    p.lineTo(-4, 10)
    p.lineTo(4, 10)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(0, 22, "N")
    c.restoreState()


def _draw_plan_page(c, model: PlanModel) -> None:
    b = model_bounds(model, margin_mm=1000)
    use_landscape = b.width > b.height * 1.18
    page = landscape(A4) if use_landscape else A4
    c.showPage()
    c.setPageSize(page)
    pw, ph = page
    mx = 15 * MM
    top = _draw_internal_header(c, model, pw, ph)
    title_y = _draw_section_title(c, mx, top - 5, "01", "Planimetria generale")

    plan_left = mx + 4
    plan_right = pw - mx - 4
    plan_top = title_y - 5
    plan_bottom = 126
    b = model_bounds(model, margin_mm=1050)
    scale = min((plan_right - plan_left) / b.width, (plan_top - plan_bottom) / b.height)
    ox = plan_left + ((plan_right - plan_left) - b.width * scale) / 2 - b.min_x * scale
    oy = plan_bottom + ((plan_top - plan_bottom) - b.height * scale) / 2 - b.min_y * scale

    def pt(x, y):
        return ox + x * scale, oy + y * scale

    # Architectural grid only around the margins.
    c.setStrokeColorRGB(0.94, 0.95, 0.96)
    c.setLineWidth(0.25)
    for xx in range(int(plan_left), int(plan_right) + 1, 28):
        c.line(xx, plan_bottom, xx, plan_bottom + 12)
        c.line(xx, plan_top - 12, xx, plan_top)
    for yy in range(int(plan_bottom), int(plan_top) + 1, 28):
        c.line(plan_left, yy, plan_left + 12, yy)
        c.line(plan_right - 12, yy, plan_right, yy)

    wall_map = {wall.id: wall for wall in model.walls}

    # Very light room fills.
    for room in model.rooms:
        if len(room.polygon) < 3:
            continue
        c.setFillColorRGB(0.985, 0.988, 0.992)
        path = c.beginPath()
        x0, y0 = pt(room.polygon[0].x, room.polygon[0].y)
        path.moveTo(x0, y0)
        for q in room.polygon[1:]:
            x, y = pt(q.x, q.y)
            path.lineTo(x, y)
        path.close()
        c.drawPath(path, stroke=0, fill=1)

    c.setStrokeColorRGB(*BLUE)
    c.setLineCap(0)
    for wall in model.walls:
        c.setLineWidth(max(2.0, min(8.0, wall.thicknessMm * scale)))
        c.line(*pt(wall.start.x, wall.start.y), *pt(wall.end.x, wall.end.y))

    for opening in model.openings:
        wall = wall_map.get(opening.wallId)
        if wall:
            _draw_opening(c, pt, opening, wall, scale)

    # Room labels.
    for room in model.rooms:
        if not room.polygon:
            continue
        cx = sum(p.x for p in room.polygon) / len(room.polygon)
        cy = sum(p.y for p in room.polygon) / len(room.polygon)
        x, y = pt(cx, cy)
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(x, y + 5, room.name)
        c.setFillColorRGB(*CHARCOAL)
        c.setFont("Helvetica", 8)
        c.drawCentredString(x, y - 7, _m2(room.floorAreaM2))

    center_xy = ((b.min_x + b.max_x) / 2, (b.min_y + b.max_y) / 2)
    estimated_on_page = False
    for wall in model.walls:
        estimated_on_page = _dimension_wall(c, pt, wall, scale, center_xy) or estimated_on_page

    # Legend and scale.
    legend_y = 88
    c.setFillColorRGB(*CHARCOAL)
    c.setFont("Helvetica", 7.5)
    c.drawString(mx, legend_y, "Misura rilevata")
    c.setStrokeColorRGB(*CHARCOAL)
    c.line(mx, legend_y - 5, mx + 24, legend_y - 5)
    c.setFillColorRGB(*ORANGE)
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(mx + 95, legend_y, "Misura stimata/calcolata*")
    c.setStrokeColorRGB(*ORANGE)
    c.line(mx + 95, legend_y - 5, mx + 119, legend_y - 5)
    c.setFillColorRGB(*CHARCOAL)
    c.setFont("Helvetica", 7.5)
    c.drawString(mx + 245, legend_y, "Porta")
    c.drawString(mx + 290, legend_y, "Finestra")

    _draw_scale_bar(c, mx, 61, scale)

    meta = _document_meta(model)
    if meta.get("northAngleDeg") is not None:
        try:
            _draw_north(c, plan_right - 18, plan_top - 20, float(meta["northAngleDeg"]))
        except Exception:
            pass

    # Title block.
    cart_w = min(212, pw * 0.36)
    cart_h = 50
    cart_x = pw - mx - cart_w
    cart_y = 55
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(0.7)
    c.rect(cart_x, cart_y, cart_w, cart_h, stroke=1, fill=0)
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cart_x + 7, cart_y + 35, f"Rif. {meta.get('reference', model.planId)}")
    c.setFont("Helvetica", 7)
    unit = str(meta.get("unitLabel") or "Unita rilevata")
    c.drawString(cart_x + 7, cart_y + 22, unit[:38])
    c.drawString(cart_x + 7, cart_y + 9, f"Data {_fmt_date(meta.get('surveyDate'))}")
    c.drawRightString(cart_x + cart_w - 7, cart_y + 35, "Scala grafica")
    c.drawRightString(cart_x + cart_w - 7, cart_y + 22, "Tavola 1 di 1")

    if estimated_on_page:
        c.setFillColorRGB(*ORANGE)
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(mx, 51, ESTIMATED_NOTE[:90])


def _room_has_estimates(room) -> bool:
    return bool(getattr(room, "estimatedWallIds", None) or getattr(room, "calculatedWallIds", None))


def _draw_room_card(c, model: PlanModel, room, number: int, x: float, y_top: float, width: float, height: float) -> None:
    c.setFillColorRGB(*WHITE)
    c.setStrokeColorRGB(*LINE)
    c.setLineWidth(0.7)
    c.roundRect(x, y_top - height, width, height, 7, stroke=1, fill=1)
    c.setFillColorRGB(*BLUE)
    c.rect(x, y_top - height, 4, height, stroke=0, fill=1)

    c.setFillColorRGB(*ORANGE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 14, y_top - 20, f"{number:02d}")
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x + 42, y_top - 22, room.name[:45])

    metric_y = y_top - 54
    gap = 7
    metric_w = (width - 28 - 2 * gap) / 3
    values = (
        ("PAVIMENTO", room.floorAreaM2),
        ("PARETI NETTE", room.netWallAreaM2),
        ("SOFFITTO", room.ceilingAreaM2),
    )
    for idx, (label, value) in enumerate(values):
        xx = x + 14 + idx * (metric_w + gap)
        c.setFillColorRGB(*LIGHT)
        c.roundRect(xx, metric_y - 46, metric_w, 46, 5, stroke=0, fill=1)
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(xx + 8, metric_y - 19, _m2(value))
        c.setFillColorRGB(*MUTED)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(xx + 8, metric_y - 34, label)

    yy = metric_y - 66
    rows = [
        ("Dimensioni", f"{room.widthM:.2f} x {room.depthM:.2f} m".replace(".", ",")),
        ("Altezza", _m(room.heightMm, 2)),
        ("Perimetro", f"{room.perimeterM:.2f} m".replace(".", ",")),
        ("Aperture detratte", _m2(room.openingsAreaM2)),
    ]
    c.setFont("Helvetica", 8.5)
    for label, value in rows:
        c.setFillColorRGB(*MUTED)
        c.drawString(x + 16, yy, label)
        c.setFillColorRGB(*CHARCOAL)
        c.drawRightString(x + width - 16, yy, value)
        c.setStrokeColorRGB(*LINE)
        c.setLineWidth(0.35)
        c.line(x + 16, yy - 5, x + width - 16, yy - 5)
        yy -= 20

    if room.openings:
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(x + 16, yy, "APERTURE")
        yy -= 14
        c.setFillColorRGB(*CHARCOAL)
        c.setFont("Helvetica", 7.8)
        for opening in room.openings[:4]:
            kind = "Porta" if opening.type == "door" else "Finestra"
            text = f"{kind} - {_m(opening.widthMm, 2)} x {_m(opening.heightMm, 2)}"
            c.drawString(x + 16, yy, text)
            yy -= 13

    if _room_has_estimates(room):
        c.setFillColorRGB(*ORANGE)
        c.setFont("Helvetica-Oblique", 8)
        _draw_wrapped(c, ESTIMATED_NOTE, x + 16, y_top - height + 22, width - 32, font="Helvetica-Oblique", size=8, leading=10, color=ORANGE, max_lines=2)


def _draw_room_pages(c, model: PlanModel) -> None:
    if not model.rooms:
        return
    page = A4
    pw, ph = page
    mx = 15 * MM
    rooms = list(model.rooms)
    page_index = 0
    for start in range(0, len(rooms), 2):
        c.showPage()
        c.setPageSize(page)
        top = _draw_internal_header(c, model, pw, ph)
        title_y = _draw_section_title(c, mx, top - 5, "02", "Schede ambiente")
        card_top = title_y - 2
        available = card_top - 64
        gap = 14
        card_h = (available - gap) / 2
        batch = rooms[start : start + 2]
        for offset, room in enumerate(batch):
            y_top = card_top - offset * (card_h + gap)
            _draw_room_card(c, model, room, start + offset + 1, mx, y_top, pw - 2 * mx, card_h)
        page_index += 1


def _draw_summary_page(c, model: PlanModel) -> None:
    c.showPage()
    c.setPageSize(A4)
    pw, ph = A4
    mx = 15 * MM
    top = _draw_internal_header(c, model, pw, ph)
    y = _draw_section_title(c, mx, top - 5, "03", "Riepilogo superfici")

    headers = ("Ambiente", "Pavimento m²", "Pareti m²", "Soffitto m²", "Perimetro m", "Altezza m")
    widths = [150, 72, 72, 72, 72, 65]
    table_w = sum(widths)
    x0 = mx

    def draw_header(row_y: float):
        c.setFillColorRGB(*BLUE)
        c.rect(x0, row_y - 22, table_w, 22, stroke=0, fill=1)
        xx = x0
        c.setFillColorRGB(*WHITE)
        c.setFont("Helvetica-Bold", 7.5)
        for label, width in zip(headers, widths):
            c.drawString(xx + 5, row_y - 14, label)
            xx += width

    draw_header(y)
    y -= 22
    row_h = 22

    for idx, room in enumerate(model.rooms):
        if y - row_h < 120:
            c.showPage()
            c.setPageSize(A4)
            top = _draw_internal_header(c, model, pw, ph)
            y = _draw_section_title(c, mx, top - 5, "03", "Riepilogo superfici - continua")
            draw_header(y)
            y -= 22

        if idx % 2:
            c.setFillColorRGB(*LIGHT)
            c.rect(x0, y - row_h, table_w, row_h, stroke=0, fill=1)

        values = (
            room.name,
            f"{room.floorAreaM2:.2f}".replace(".", ","),
            f"{room.netWallAreaM2:.2f}".replace(".", ","),
            f"{room.ceilingAreaM2:.2f}".replace(".", ","),
            f"{room.perimeterM:.2f}".replace(".", ","),
            f"{room.heightMm / 1000:.2f}".replace(".", ","),
        )
        xx = x0
        for col, (value, width) in enumerate(zip(values, widths)):
            c.setFillColorRGB(*CHARCOAL)
            c.setFont("Helvetica-Bold" if col == 0 else "Helvetica", 8)
            if col == 0:
                c.drawString(xx + 5, y - 14, str(value)[:27])
            else:
                c.drawRightString(xx + width - 5, y - 14, str(value))
            c.setStrokeColorRGB(*LINE)
            c.setLineWidth(0.3)
            c.line(xx, y - row_h, xx + width, y - row_h)
            xx += width
        y -= row_h

    totals_y = max(80, y - 84)
    c.setFillColorRGB(*LIGHT)
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(0.8)
    c.roundRect(mx, totals_y, pw - 2 * mx, 65, 6, stroke=1, fill=1)
    c.setFillColorRGB(*ORANGE)
    c.rect(mx, totals_y + 63, 42, 2, stroke=0, fill=1)

    totals = (
        ("Pavimento totale", sum(r.floorAreaM2 for r in model.rooms)),
        ("Pareti nette totali", sum(r.netWallAreaM2 for r in model.rooms)),
        ("Soffitto totale", sum(r.ceilingAreaM2 for r in model.rooms)),
    )
    box_w = (pw - 2 * mx) / 3
    for idx, (label, value) in enumerate(totals):
        xx = mx + idx * box_w
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(xx + 12, totals_y + 35, _m2(value))
        c.setFillColorRGB(*MUTED)
        c.setFont("Helvetica-Bold", 6.8)
        c.drawString(xx + 12, totals_y + 18, label.upper())


def _note_lines(model: PlanModel) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for note in model.notes:
        if isinstance(note, dict):
            label = str(note.get("targetLabel") or note.get("title") or note.get("label") or "Nota")
            text = str(
                note.get("text")
                or note.get("content")
                or note.get("note")
                or note.get("rawText")
                or note.get("description")
                or ""
            ).strip()
            if text:
                items.append((label, text))
        else:
            text = str(note).strip()
            if text:
                items.append(("Nota", text))

    works = list(model.metadata.get("works") or [])
    for work in works:
        label = str(work.get("label") or "Lavorazione rilevata").strip()
        qty = work.get("quantity")
        unit = str(work.get("unit") or "").strip()
        target_names = work.get("targetNames") or []
        target = ", ".join(str(x) for x in target_names if x)
        parts = []
        if target:
            parts.append(target)
        if qty is not None:
            parts.append((f"{float(qty):.2f}".replace(".", ",") + (f" {unit}" if unit else "")).strip())
        note = str(work.get("note") or "").strip()
        if note:
            parts.append(note)
        items.append((label, " - ".join(parts) if parts else "Voce rilevata nel sopralluogo."))
    return items


def _draw_notes_pages(c, model: PlanModel) -> None:
    notes = _note_lines(model)
    if not notes:
        return

    c.showPage()
    c.setPageSize(A4)
    pw, ph = A4
    mx = 15 * MM
    top = _draw_internal_header(c, model, pw, ph)
    y = _draw_section_title(c, mx, top - 5, "04", "Note di rilievo")

    for label, text in notes:
        lines = _wrap(text, "Helvetica", 8.5, pw - 2 * mx - 28)
        needed = 34 + len(lines) * 11
        if y - needed < 72:
            c.showPage()
            c.setPageSize(A4)
            top = _draw_internal_header(c, model, pw, ph)
            y = _draw_section_title(c, mx, top - 5, "04", "Note di rilievo - continua")

        c.setFillColorRGB(*LIGHT)
        c.setStrokeColorRGB(*LINE)
        c.setLineWidth(0.5)
        c.roundRect(mx, y - needed + 6, pw - 2 * mx, needed - 6, 6, stroke=1, fill=1)
        c.setFillColorRGB(*BLUE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(mx + 12, y - 16, label[:70])
        yy = y - 31
        c.setFillColorRGB(*CHARCOAL)
        c.setFont("Helvetica", 8.5)
        for line_text in lines:
            c.drawString(mx + 12, yy, line_text)
            yy -= 11
        y -= needed + 10


def export_pdf(model: PlanModel, path: Path) -> None:
    """Generate the branded GE360 survey PDF without altering survey data."""

    meta = _document_meta(model)
    reference = str(meta.get("reference") or model.planId)
    c = NumberedCanvas(
        str(path),
        pagesize=A4,
        pageCompression=0,
        reference=reference,
    )

    _draw_cover(c, model)
    _draw_plan_page(c, model)
    _draw_room_pages(c, model)
    _draw_summary_page(c, model)
    _draw_notes_pages(c, model)

    append_usage_terms_page(
        c,
        document_name=model.name,
        brand_name=BRAND_NAME,
        brand_subtitle=BRAND_SUBTITLE,
        brand_tagline=BRAND_TAGLINE,
        reference=reference,
        date_text=_fmt_date(meta.get("surveyDate")),
    )
    c.save()
