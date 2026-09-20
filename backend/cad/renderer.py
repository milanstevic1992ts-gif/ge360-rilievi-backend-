from __future__ import annotations
import math
from dataclasses import dataclass
from backend.models import PlanModel, WallModel

@dataclass
class Bounds:
    min_x:float; min_y:float; max_x:float; max_y:float
    @property
    def width(self): return max(1.0,self.max_x-self.min_x)
    @property
    def height(self): return max(1.0,self.max_y-self.min_y)

def model_bounds(model:PlanModel,margin_mm:float=600.0)->Bounds:
    xs=[]; ys=[]
    for w in model.walls: xs += [w.start.x,w.end.x]; ys += [w.start.y,w.end.y]
    if not xs: return Bounds(0,0,1000,1000)
    return Bounds(min(xs)-margin_mm,min(ys)-margin_mm,max(xs)+margin_mm,max(ys)+margin_mm)

def wall_unit(wall:WallModel):
    dx,dy=wall.end.x-wall.start.x,wall.end.y-wall.start.y; length=math.hypot(dx,dy) or 1.0
    return dx/length,dy/length,length

def point_along(wall:WallModel,distance_mm:float):
    ux,uy,_=wall_unit(wall); return wall.start.x+ux*distance_mm,wall.start.y+uy*distance_mm

def wall_outline(wall:WallModel):
    ux,uy,_=wall_unit(wall); nx,ny=-uy,ux; h=wall.thicknessMm/2
    return [(wall.start.x+nx*h,wall.start.y+ny*h),(wall.end.x+nx*h,wall.end.y+ny*h),(wall.end.x-nx*h,wall.end.y-ny*h),(wall.start.x-nx*h,wall.start.y-ny*h)]
