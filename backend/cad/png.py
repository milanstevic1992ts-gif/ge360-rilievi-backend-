from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.cad.renderer import model_bounds, point_along, wall_unit
from backend.models import PlanModel


def _font(size: int):
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def export_png(model: PlanModel, path: Path, width: int = 1600, height: int = 1100) -> None:
    b=model_bounds(model)
    img=Image.new("RGB",(width,height),"white")
    d=ImageDraw.Draw(img)
    margin=80
    scale=min((width-2*margin)/b.width,(height-2*margin)/b.height)
    def pt(x,y):
        return (margin+(x-b.min_x)*scale, height-margin-(y-b.min_y)*scale)
    wall_map={w.id:w for w in model.walls}
    for w in model.walls:
        d.line([pt(w.start.x,w.start.y),pt(w.end.x,w.end.y)],fill="black",width=max(3,int(w.thicknessMm*scale)))
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w: continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2); p2=point_along(w,o.centerFromStartMm+o.widthMm/2)
        d.line([pt(*p1),pt(*p2)],fill="white",width=max(5,int((w.thicknessMm+18)*scale)))
        if o.type=="door":
            ux,uy,_=wall_unit(w); nx,ny=-uy,ux
            leaf=(p1[0]+nx*o.widthMm,p1[1]+ny*o.widthMm)
            d.line([pt(*p1),pt(*leaf)],fill="black",width=2)
        else:
            d.line([pt(*p1),pt(*p2)],fill="black",width=2)
    room_font=_font(26); area_font=_font(22); dim_font=_font(18); title_font=_font(30)
    for room in model.rooms:
        cx=sum(p.x for p in room.polygon)/len(room.polygon); cy=sum(p.y for p in room.polygon)/len(room.polygon)
        x,y=pt(cx,cy)
        d.text((x,y-15),room.name,fill="black",font=room_font,anchor="mm")
        d.text((x,y+18),f"{room.floorAreaM2:.2f} m²",fill="black",font=area_font,anchor="mm")
    for w in model.walls:
        x,y=pt((w.start.x+w.end.x)/2,(w.start.y+w.end.y)/2)
        d.rectangle((x-45,y-13,x+45,y+13),fill="white")
        d.text((x,y),f"{w.lengthMm/1000:.2f} m",fill="black",font=dim_font,anchor="mm")
    d.text((margin,32),f"{model.name} · GE360 RILIEVO",fill="black",font=title_font)
    d.text((width-margin,40),"unità: mm",fill="black",font=dim_font,anchor="ra")
    img.save(path,format="PNG")
