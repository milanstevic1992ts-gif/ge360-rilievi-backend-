from __future__ import annotations

from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth

DOCUMENT_TERMS_VERSION = "2026-09"


USAGE_TERMS: tuple[tuple[str, str], ...] = (
    (
        "Natura del rilievo.",
        "Il presente elaborato documenta misure, superfici e rappresentazioni grafiche raccolte per supportare la valutazione e la programmazione dei lavori. Non sostituisce un progetto esecutivo, un elaborato catastale o una certificazione tecnica.",
    ),
    (
        "Verifica prima di ordini e lavorazioni.",
        "Prima di ordinare materiali, serramenti, arredi su misura, sanitari o altri elementi vincolati alle dimensioni reali, le misure interessate devono essere verificate direttamente in loco. Lo stesso principio vale prima dell'avvio di lavorazioni che richiedono tolleranze specifiche.",
    ),
    (
        "Misure ricavate per calcolo.",
        "Le misure indicate come stimate o calcolate derivano dalle altre dimensioni disponibili e sono sempre contrassegnate nel documento. Devono essere verificate in loco prima di essere utilizzate per ordini o lavorazioni.",
    ),
    (
        "Stato dei luoghi.",
        "Il rilievo rappresenta lo stato degli ambienti alla data indicata nel documento. Modifiche successive, elementi non accessibili o condizioni non rilevabili durante il sopralluogo possono richiedere un aggiornamento.",
    ),
    (
        "Uso concordato e diffusione.",
        "Il documento è destinato all'uso concordato nell'ambito del rilievo e dei lavori collegati. La diffusione a terzi, la pubblicazione o l'impiego per finalità diverse devono essere preventivamente concordati con l'Impresa.",
    ),
)


def _wrap(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def append_usage_terms_page(
    c,
    *,
    document_name: str,
    brand_name: str,
    brand_subtitle: str,
    brand_tagline: str,
    reference: str = "",
    date_text: str = "",
    sections: Iterable[tuple[str, str]] = USAGE_TERMS,
) -> None:
    """Append the final conditions-of-use page for GE360 survey reports."""

    c.showPage()
    c.setPageSize(A4)
    pw, ph = A4
    mm = 72.0 / 25.4
    margin_x = 15 * mm
    top_margin = 18 * mm

    blue = (23 / 255, 54 / 255, 93 / 255)
    orange = (242 / 255, 140 / 255, 40 / 255)
    charcoal = (47 / 255, 53 / 255, 64 / 255)
    line = (217 / 255, 222 / 255, 227 / 255)

    # Compact internal header.
    y_top = ph - top_margin + 12
    c.setFillColorRGB(*blue)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(margin_x, y_top, brand_name)
    c.setFillColorRGB(*charcoal)
    c.setFont("Helvetica", 7.5)
    right = " · ".join(part for part in [f"Rif. {reference}" if reference else "", date_text] if part)
    if right:
        c.drawRightString(pw - margin_x, y_top, right)
    c.setStrokeColorRGB(*line)
    c.setLineWidth(0.7)
    c.line(margin_x, y_top - 9, pw - margin_x, y_top - 9)
    c.setStrokeColorRGB(*orange)
    c.setLineWidth(1.8)
    c.line(margin_x, y_top - 9, margin_x + 28, y_top - 9)

    y = y_top - 44
    c.setFillColorRGB(*orange)
    c.rect(margin_x, y - 2, 3, 19, stroke=0, fill=1)
    c.setFillColorRGB(*blue)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(margin_x + 10, y, "05  Condizioni d'uso del rilievo")
    y -= 30

    body_font = "Helvetica"
    body_size = 9.2
    body_leading = 13.2
    title_font = "Helvetica-Bold"
    title_size = 9.2
    max_width = pw - 2 * margin_x

    for title, body in sections:
        if y < 120:
            break
        c.setFillColorRGB(*blue)
        c.setFont(title_font, title_size)
        c.drawString(margin_x, y, title)
        y -= body_leading
        c.setFillColorRGB(*charcoal)
        c.setFont(body_font, body_size)
        for line_text in _wrap(body, body_font, body_size, max_width):
            c.drawString(margin_x, y, line_text)
            y -= body_leading
        y -= 9

    # Final signature only; no commercial closing content.
    c.setStrokeColorRGB(*line)
    c.setLineWidth(0.7)
    c.line(margin_x, 82, pw - margin_x, 82)
    c.setStrokeColorRGB(*orange)
    c.setLineWidth(1.8)
    c.line(margin_x, 82, margin_x + 28, 82)
    c.setFillColorRGB(*blue)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin_x, 62, f"{brand_name} — {brand_subtitle}")
