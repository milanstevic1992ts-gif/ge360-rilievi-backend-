from __future__ import annotations

from datetime import datetime
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth

DOCUMENT_TERMS_VERSION = "2026-09-21"

USAGE_TERMS: tuple[tuple[str, str], ...] = (
    (
        "Natura del documento.",
        "Il presente elaborato è una rappresentazione grafica indicativa, prodotta anche con l'ausilio di strumenti digitali e di intelligenza artificiale, sulla base di misure rilevate nelle condizioni presenti al momento del sopralluogo. Ha esclusivamente funzione orientativa e di supporto alla valutazione preliminare dei lavori. Non costituisce rilievo tecnico di precisione, progetto, né documento valido ai fini catastali, urbanistici, notarili o peritali.",
    ),
    (
        "Tolleranze ed errori.",
        "Le quote riportate possono presentare approssimazioni, arrotondamenti, deformazioni grafiche ed errori, anche evidenti, dovuti alle condizioni del rilievo (arredi presenti, pareti fuori squadra o fuori piombo, superfici irregolari, zone non accessibili o non ispezionabili) e all'elaborazione digitale. Proporzioni, angoli e dimensioni possono non corrispondere allo stato reale dei luoghi.",
    ),
    (
        "Usi non previsti.",
        "L'elaborato non è destinato e non deve essere utilizzato per: ordinare o realizzare cucine, mobili e arredi su misura; ordinare serramenti, porte, sanitari, box e piatti doccia, rivestimenti o pavimenti; calcolare quantità esatte di materiali; pratiche edilizie, catastali, compravendite o valutazioni immobiliari. Per tali finalità è necessario un rilievo diretto eseguito dal fornitore interessato o da un tecnico abilitato.",
    ),
    (
        "Verifica a cura del destinatario.",
        "Prima di qualsiasi acquisto, ordine o lavorazione, il destinatario è tenuto a verificare direttamente in loco le misure necessarie. Eventuali dubbi, incongruenze o differenze rispetto allo stato reale devono essere segnalati tempestivamente all'Impresa, che provvederà alle verifiche e, se necessario, all'aggiornamento dell'elaborato.",
    ),
    (
        "Limitazione di responsabilità.",
        "Nei limiti consentiti dalla legge, l'Impresa non risponde di danni, costi o errori di fornitura derivanti da un utilizzo dell'elaborato diverso da quello indicato o dall'omessa verifica delle misure. Restano salvi i diritti riconosciuti dalla legge, anche in favore dei consumatori, e la responsabilità per dolo o colpa grave.",
    ),
    (
        "Riservatezza e divieto di diffusione.",
        "L'elaborato è consegnato esclusivamente al destinatario, per uso personale e limitato ai lavori oggetto di trattativa con l'Impresa. Ne sono vietate la cessione, la distribuzione a terzi, la pubblicazione, anche online, e la riproduzione totale o parziale senza autorizzazione scritta dell'Impresa. Impaginazione, grafica e contenuti restano nella disponibilità dell'Impresa.",
    ),
    (
        "Validità.",
        "L'elaborato rappresenta lo stato dei luoghi alla data del sopralluogo. Qualsiasi modifica successiva all'immobile ne fa venire meno l'attendibilità.",
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
    sections: Iterable[tuple[str, str]] = USAGE_TERMS,
) -> None:
    """Append the mandatory final conditions-of-use page.

    This function is the single source of truth for GE360-generated PDF reports.
    Any future backend PDF/document renderer should reuse these same terms.
    """

    # Finish the previous report page, then switch only the last page to portrait A4.
    c.showPage()
    c.setPageSize(A4)
    pw, ph = A4
    margin = 42

    # Brand header.
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.rect(0, ph - 70, pw, 70, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, ph - 25, brand_name)
    c.setFont("Helvetica", 7.5)
    c.drawString(margin, ph - 39, brand_subtitle)
    c.setFont("Helvetica-Oblique", 7.2)
    c.drawString(margin, ph - 53, brand_tagline)

    y = ph - 98
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "NOTE E CONDIZIONI D'USO DEL PRESENTE ELABORATO")
    y -= 13
    c.setStrokeColorRGB(0.80, 0.83, 0.88)
    c.setLineWidth(0.8)
    c.line(margin, y, pw - margin, y)
    y -= 16

    body_font = "Helvetica"
    body_size = 7.35
    body_leading = 9.25
    title_font = "Helvetica-Bold"
    title_size = 7.55
    max_width = pw - 2 * margin

    for title, body in sections:
        title_width = stringWidth(title, title_font, title_size)
        words = body.split()
        first_words: list[str] = []
        rest_start = 0

        # Put as much of the first sentence body as possible on the title line.
        available = max_width - title_width - 4
        for idx, word in enumerate(words):
            candidate = " ".join(first_words + [word])
            if stringWidth(candidate, body_font, body_size) <= available:
                first_words.append(word)
                rest_start = idx + 1
            else:
                break

        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont(title_font, title_size)
        c.drawString(margin, y, title)
        if first_words:
            c.setFont(body_font, body_size)
            c.drawString(margin + title_width + 4, y, " ".join(first_words))
        y -= body_leading

        rest = " ".join(words[rest_start:])
        for line in _wrap(rest, body_font, body_size, max_width) if rest else []:
            c.setFont(body_font, body_size)
            c.drawString(margin, y, line)
            y -= body_leading

        y -= 6

    # Footer identifies both the report and the terms revision.
    footer_y = 24
    c.setStrokeColorRGB(0.84, 0.86, 0.90)
    c.line(margin, footer_y + 12, pw - margin, footer_y + 12)
    c.setFillColorRGB(0.38, 0.42, 0.49)
    c.setFont("Helvetica", 6.2)
    c.drawString(margin, footer_y, f"Documento: {document_name[:72]}")
    c.drawRightString(
        pw - margin,
        footer_y,
        f"Condizioni v. {DOCUMENT_TERMS_VERSION} · {datetime.now().strftime('%d/%m/%Y')}",
    )
