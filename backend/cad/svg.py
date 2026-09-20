from __future__ import annotations

import html
from pathlib import Path

from backend.cad.renderer import model_bounds, point_along, wall_unit
from backend.models import PlanModel


def export_svg(model: PlanModel, path: Path) -> None:
    b = model_bounds(model)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{b.min_x:.2f} {b.min_y:.2f} {b.width:.2f} {b.height:.2f}">',
        '<style>text{font-family:Arial,sans-serif;fill:#111} .dim{font-size:120px}.room{font-size:150px;font-weight:700}.area{font-size:120px}</style>',
        '<rect x="{:.2f}" y="{:.2f}" width="{:.2f}" height="{:.2f}" fill="white"/>'.format(b.min_x,b.min_y,b.width,b.height),
        '<g id="walls" stroke="#111" stroke-linecap="butt" stroke-linejoin="miter">',
    ]
    for w in model.walls:
        parts.append(f'<line x1="{w.start.x:.2f}" y1="{w.start.y:.2f}" x2="{w.end.x:.2f}" y2="{w.end.y:.2f}" stroke-width="{w.thicknessMm:.2f}"/>')
    parts.append('</g>')

    wall_map = {w.id: w for w in model.walls}
    parts.append('<g id="openings">')
    for o in model.openings:
        w = wall_map.get(o.wallId)
        if not w:
            continue
        ux, uy, _ = wall_unit(w)
        nx, ny = -uy, ux
        center = o.centerFromStartMm
        p1 = point_along(w, center - o.widthMm/2)
        p2 = point_along(w, center + o.widthMm/2)
        gap_width = w.thicknessMm + 12
        parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="white" stroke-width="{gap_width:.2f}"/>')
        if o.type == 'door':
            leaf_end = (p1[0] + nx*o.widthMm, p1[1] + ny*o.widthMm)
            parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{leaf_end[0]:.2f}" y2="{leaf_end[1]:.2f}" stroke="#111" stroke-width="24"/>')
            parts.append(f'<path d="M {p2[0]:.2f} {p2[1]:.2f} Q {p1[0]+(ux+nx)*o.widthMm:.2f} {p1[1]+(uy+ny)*o.widthMm:.2f} {leaf_end[0]:.2f} {leaf_end[1]:.2f}" fill="none" stroke="#777" stroke-width="12"/>')
        else:
            q1 = (p1[0] + nx*w.thicknessMm*.22, p1[1] + ny*w.thicknessMm*.22)
            q2 = (p2[0] + nx*w.thicknessMm*.22, p2[1] + ny*w.thicknessMm*.22)
            r1 = (p1[0] - nx*w.thicknessMm*.22, p1[1] - ny*w.thicknessMm*.22)
            r2 = (p2[0] - nx*w.thicknessMm*.22, p2[1] - ny*w.thicknessMm*.22)
            parts.append(f'<line x1="{q1[0]:.2f}" y1="{q1[1]:.2f}" x2="{q2[0]:.2f}" y2="{q2[1]:.2f}" stroke="#111" stroke-width="18"/>')
            parts.append(f'<line x1="{r1[0]:.2f}" y1="{r1[1]:.2f}" x2="{r2[0]:.2f}" y2="{r2[1]:.2f}" stroke="#111" stroke-width="18"/>')
    parts.append('</g>')

    parts.append('<g id="rooms" text-anchor="middle">')
    for room in model.rooms:
        xs=[p.x for p in room.polygon]; ys=[p.y for p in room.polygon]
        cx=sum(xs)/len(xs); cy=sum(ys)/len(ys)
        parts.append(f'<text class="room" x="{cx:.2f}" y="{cy:.2f}">{html.escape(room.name)}</text>')
        parts.append(f'<text class="area" x="{cx:.2f}" y="{cy+150:.2f}">{room.floorAreaM2:.2f} m²</text>')
    parts.append('</g>')

    parts.append('<g id="dimensions" text-anchor="middle">')
    for w in model.walls:
        mx=(w.start.x+w.end.x)/2; my=(w.start.y+w.end.y)/2
        ux,uy,_=wall_unit(w); nx,ny=-uy,ux
        x=mx+nx*(w.thicknessMm/2+180); y=my+ny*(w.thicknessMm/2+180)
        parts.append(f'<text class="dim" x="{x:.2f}" y="{y:.2f}">{w.lengthMm/1000:.2f} m</text>')
    parts.append('</g>')
    parts.append(f'<text x="{b.min_x+80:.2f}" y="{b.min_y+150:.2f}" font-size="150" font-weight="700">{html.escape(model.name)} · GE360 RILIEVO · unità mm</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")
