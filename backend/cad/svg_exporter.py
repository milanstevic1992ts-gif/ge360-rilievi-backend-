from __future__ import annotations
import html
from pathlib import Path
from backend.cad.renderer import model_bounds, point_along, wall_unit
from backend.models import PlanModel

def export_svg(model:PlanModel,path:Path)->None:
    b=model_bounds(model); parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{b.min_x:.2f} {b.min_y:.2f} {b.width:.2f} {b.height:.2f}">','<style>text{font-family:Arial,sans-serif;fill:#111}.dim{font-size:120px}.room{font-size:150px;font-weight:700}.area{font-size:120px}</style>',f'<rect x="{b.min_x:.2f}" y="{b.min_y:.2f}" width="{b.width:.2f}" height="{b.height:.2f}" fill="white"/>','<g id="walls" stroke="#111">']
    for w in model.walls: parts.append(f'<line x1="{w.start.x:.2f}" y1="{w.start.y:.2f}" x2="{w.end.x:.2f}" y2="{w.end.y:.2f}" stroke-width="{w.thicknessMm:.2f}"/>')
    parts.append('</g>'); wall_map={w.id:w for w in model.walls}; parts.append('<g id="openings">')
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w: continue
        ux,uy,_=wall_unit(w); nx,ny=-uy,ux; p1=point_along(w,o.centerFromStartMm-o.widthMm/2); p2=point_along(w,o.centerFromStartMm+o.widthMm/2); parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="white" stroke-width="{w.thicknessMm+12:.2f}"/>')
        if o.type=='door':
            leaf=(p1[0]+nx*o.widthMm,p1[1]+ny*o.widthMm); parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{leaf[0]:.2f}" y2="{leaf[1]:.2f}" stroke="#111" stroke-width="24"/>')
        else:
            parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="#111" stroke-width="18"/>')
    parts.append('</g><g id="rooms" text-anchor="middle">')
    for r in model.rooms:
        cx=sum(p.x for p in r.polygon)/len(r.polygon); cy=sum(p.y for p in r.polygon)/len(r.polygon); parts.append(f'<text class="room" x="{cx:.2f}" y="{cy:.2f}">{html.escape(r.name)}</text><text class="area" x="{cx:.2f}" y="{cy+150:.2f}">{r.floorAreaM2:.2f} m²</text>')
    parts.append('</g><g id="dimensions" text-anchor="middle">')
    for w in model.walls:
        mx=(w.start.x+w.end.x)/2; my=(w.start.y+w.end.y)/2; parts.append(f'<text class="dim" x="{mx:.2f}" y="{my:.2f}">{w.calculatedLengthMm/1000:.2f} m</text>')
    parts.append('</g>'); parts.append(f'<text x="{b.min_x+80:.2f}" y="{b.min_y+150:.2f}" font-size="150" font-weight="700">{html.escape(model.name)} · GE360 RILIEVO · unità mm</text></svg>'); path.write_text("\n".join(parts),encoding="utf-8")
