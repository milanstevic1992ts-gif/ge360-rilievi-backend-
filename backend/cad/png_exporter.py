from __future__ import annotations
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from backend.cad.renderer import model_bounds,point_along,wall_unit
from backend.models import PlanModel

def _font(size):
    for name in ('DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:return ImageFont.truetype(name,size=size)
        except Exception:pass
    return ImageFont.load_default()

def export_png(model:PlanModel,path:Path,width:int=1600,height:int=1100)->None:
    b=model_bounds(model,margin_mm=850);img=Image.new('RGB',(width,height),'white');d=ImageDraw.Draw(img);margin=80;scale=min((width-2*margin)/b.width,(height-2*margin)/b.height)
    def pt(x,y):return (margin+(x-b.min_x)*scale,height-margin-(y-b.min_y)*scale)
    wall_map={w.id:w for w in model.walls}
    for w in model.walls:d.line([pt(w.start.x,w.start.y),pt(w.end.x,w.end.y)],fill='black',width=max(3,int(w.thicknessMm*scale)))
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w:continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2);p2=point_along(w,o.centerFromStartMm+o.widthMm/2);d.line([pt(*p1),pt(*p2)],fill='white',width=max(5,int((w.thicknessMm+18)*scale)))
        ux,uy,_=wall_unit(w);nx,ny=-uy,ux
        if o.type=='door':
            leaf=(p1[0]+nx*o.widthMm,p1[1]+ny*o.widthMm);d.line([pt(*p1),pt(*leaf)],fill='black',width=2)
            # approximate 90° swing arc
            cx,cy=p1;start=math.atan2(p2[1]-cy,p2[0]-cx);end=math.atan2(leaf[1]-cy,leaf[0]-cx);delta=(end-start+math.pi*2)%(math.pi*2)
            if delta>math.pi:delta-=math.pi*2
            arc=[]
            for i in range(17):
                a=start+delta*i/16;arc.append(pt(cx+math.cos(a)*o.widthMm,cy+math.sin(a)*o.widthMm))
            d.line(arc,fill='gray',width=2)
        else:
            d.line([pt(*p1),pt(*p2)],fill='black',width=2)
    rf=_font(26);af=_font(22);df=_font(18);tf=_font(30)
    for r in model.rooms:
        cx=sum(p.x for p in r.polygon)/len(r.polygon);cy=sum(p.y for p in r.polygon)/len(r.polygon);x,y=pt(cx,cy);d.text((x,y-15),r.name,fill='black',font=rf,anchor='mm');d.text((x,y+18),f'{r.floorAreaM2:.2f} m²',fill='black',font=af,anchor='mm')
    for w in model.walls:
        ux,uy,_=wall_unit(w);nx,ny=-uy,ux;mx=(w.start.x+w.end.x)/2;my=(w.start.y+w.end.y)/2;x,y=pt(mx+nx*(w.thicknessMm/2+260),my+ny*(w.thicknessMm/2+260));text=f'{w.calculatedLengthMm/1000:.2f} m';box=d.textbbox((x,y),text,font=df,anchor='mm');d.rectangle((box[0]-6,box[1]-3,box[2]+6,box[3]+3),fill='white');d.text((x,y),text,fill='black',font=df,anchor='mm')
    d.text((margin,32),f'{model.name} · GE360 RILIEVO',fill='black',font=tf);d.text((width-margin,40),'unità: mm',fill='black',font=df,anchor='ra');img.save(path,'PNG')
