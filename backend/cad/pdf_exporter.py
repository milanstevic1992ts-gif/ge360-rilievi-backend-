from __future__ import annotations
from pathlib import Path
from reportlab.lib.pagesizes import A4,landscape
from reportlab.pdfgen import canvas
from backend.cad.renderer import model_bounds,point_along,wall_unit
from backend.models import PlanModel

def export_pdf(model:PlanModel,path:Path)->None:
    page=landscape(A4);c=canvas.Canvas(str(path),pagesize=page);pw,ph=page;b=model_bounds(model,margin_mm=850);margin=55;scale=min((pw-2*margin)/b.width,(ph-2*margin)/b.height)
    def pt(x,y):return(margin+(x-b.min_x)*scale,margin+(y-b.min_y)*scale)
    c.setFont('Helvetica-Bold',14);c.drawString(margin,ph-35,f'{model.name} · GE360 RILIEVO');c.setFont('Helvetica',8);c.drawRightString(pw-margin,ph-35,'Planimetria tecnica · unità mm')
    wall_map={w.id:w for w in model.walls}
    for w in model.walls:c.setLineWidth(max(1,w.thicknessMm*scale));c.line(*pt(w.start.x,w.start.y),*pt(w.end.x,w.end.y))
    c.setStrokeColorRGB(1,1,1)
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w:continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2);p2=point_along(w,o.centerFromStartMm+o.widthMm/2);c.setLineWidth(max(2,(w.thicknessMm+14)*scale));c.line(*pt(*p1),*pt(*p2))
    c.setStrokeColorRGB(0,0,0)
    for o in model.openings:
        if o.type!='door':continue
        w=wall_map.get(o.wallId)
        if not w:continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2);ux,uy,_=wall_unit(w);nx,ny=-uy,ux;leaf=(p1[0]+nx*o.widthMm,p1[1]+ny*o.widthMm);c.setLineWidth(.8);c.line(*pt(*p1),*pt(*leaf))
    for r in model.rooms:
        cx=sum(p.x for p in r.polygon)/len(r.polygon);cy=sum(p.y for p in r.polygon)/len(r.polygon);x,y=pt(cx,cy);c.setFont('Helvetica-Bold',9);c.drawCentredString(x,y+5,r.name);c.setFont('Helvetica',8);c.drawCentredString(x,y-7,f'{r.floorAreaM2:.2f} m²')
    for w in model.walls:
        ux,uy,_=wall_unit(w);nx,ny=-uy,ux;mx=(w.start.x+w.end.x)/2;my=(w.start.y+w.end.y)/2;x,y=pt(mx+nx*(w.thicknessMm/2+260),my+ny*(w.thicknessMm/2+260));c.setFont('Helvetica',6);c.drawCentredString(x,y,f'{w.declaredLengthMm/1000:.2f} m')
    c.showPage();c.save()
