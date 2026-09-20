from __future__ import annotations
import math
from backend.models import PlanPayload
from backend.geometry.normalizer import normalize_payload
from backend.geometry.topology import build_topology
from backend.geometry.solver import solve_geometry
from backend.cad.model import build_cad_model


def process(payload: dict):
    p=PlanPayload.model_validate(payload)
    n=normalize_payload(p)
    t=build_topology(n)
    s=solve_geometry(n,t)
    m=build_cad_model(n,s)
    return n,t,s,m


def wall(id,a,b,length): return {"id":id,"a":{"x":a[0],"y":a[1]},"b":{"x":b[0],"y":b[1]},"lengthCm":length}

def test_rectangle_distorted_2x3():
    payload={"planId":"rect","walls":[
      wall("w1",(0,0),(202,11),200),
      wall("w2",(202,11),(216,307),300),
      wall("w3",(216,307),(6,298),200),
      wall("w4",(6,298),(0,0),300),
    ]}
    n,t,s,m=process(payload)
    assert not s.needs_review, s.warnings
    assert len(m.rooms)==1
    assert abs(m.rooms[0].floorAreaM2-6.0)<1e-5, m.rooms[0].floorAreaM2
    for w in m.walls:
        assert abs(w.calculatedLengthMm-w.declaredLengthMm)<0.5


def test_small_gaps_close():
    payload={"planId":"gaps","walls":[
      wall("w1",(10,0),(190,0),200),
      wall("w2",(200,10),(200,290),300),
      wall("w3",(190,300),(10,300),200),
      wall("w4",(0,290),(0,10),300),
    ]}
    n,t,s,m=process(payload)
    assert len(m.rooms)==1
    assert abs(m.rooms[0].floorAreaM2-6)<1e-4


def test_real_diagonal_stays_diagonal():
    # open polyline triangle-ish component with a deliberate ~37deg wall; no orthogonal component inference
    payload={"planId":"diag","walls":[
      wall("w1",(0,0),(80,60),100),
      wall("w2",(80,60),(170,130),114),
    ]}
    n,t,s,m=process(payload)
    w=m.walls[0]
    ang=math.degrees(math.atan2(w.end.y-w.start.y,w.end.x-w.start.x))
    assert 25 < abs(ang) < 50, ang
    assert w.orientation=="free"


def test_door_offset_preserved():
    payload={"planId":"door","walls":[
      wall("w1",(0,0),(303,9),300),
      wall("w2",(303,9),(310,210),200),
      wall("w3",(310,210),(8,200),300),
      wall("w4",(8,200),(0,0),200),
    ],"openings":[{"id":"d1","type":"door","wallId":"w1","widthCm":80,"offsetCm":120,"referenceEnd":"a"}]}
    _,_,_,m=process(payload)
    d=m.openings[0]
    assert d.widthMm==800
    assert d.offsetMm==1200
    assert d.centerFromStartMm==1600


def test_window_preserved():
    payload={"planId":"win","walls":[
      wall("w1",(0,0),(300,0),300), wall("w2",(300,0),(300,200),200), wall("w3",(300,200),(0,200),300), wall("w4",(0,200),(0,0),200),
    ],"openings":[{"id":"f1","type":"window","wallId":"w1","widthCm":120,"offsetCm":50,"referenceEnd":"a","heightCm":140,"sillHeightCm":90}]}
    _,_,_,m=process(payload)
    o=m.openings[0]
    assert (o.widthMm,o.offsetMm,o.heightMm,o.sillHeightMm)==(1200,500,1400,900)


def test_l_shape():
    # 4x4 square minus top-right 2x2 => 12m2
    pts=[(0,0),(400,0),(400,200),(200,200),(200,400),(0,400),(0,0)]
    lens=[400,200,200,200,200,400]
    walls=[wall(f"w{i+1}",pts[i],pts[i+1],lens[i]) for i in range(6)]
    _,_,s,m=process({"planId":"l","walls":walls})
    assert not s.needs_review, s.warnings
    assert len(m.rooms)==1
    assert abs(m.rooms[0].floorAreaM2-12)<1e-5, m.rooms[0].floorAreaM2


def test_two_rooms_shared_wall():
    # Outer 4x3 rectangle with vertical shared wall at x=2 => two 6m2 rooms
    walls=[
      wall("top",(0,0),(400,0),400),
      wall("right",(400,0),(400,300),300),
      wall("bottom",(400,300),(0,300),400),
      wall("left",(0,300),(0,0),300),
      wall("shared",(200,0),(200,300),300),
    ]
    _,_,s,m=process({"planId":"two","walls":walls})
    assert len(m.rooms)==2, [(r.floorAreaM2,r.wallIds) for r in m.rooms]
    assert sorted(round(r.floorAreaM2,6) for r in m.rooms)==[6.0,6.0]


def test_three_rooms():
    walls=[
      wall("top",(0,0),(600,0),600), wall("right",(600,0),(600,300),300),
      wall("bottom",(600,300),(0,300),600), wall("left",(0,300),(0,0),300),
      wall("s1",(200,0),(200,300),300), wall("s2",(400,0),(400,300),300),
    ]
    _,_,_,m=process({"planId":"three","walls":walls})
    assert len(m.rooms)==3
    assert all(abs(r.floorAreaM2-6)<1e-5 for r in m.rooms)


def test_incompatible_does_not_change_declared():
    payload={"planId":"bad","walls":[
      wall("w1",(0,0),(200,0),200), wall("w2",(200,0),(200,300),300),
      wall("w3",(200,300),(0,300),200), wall("w4",(0,300),(0,0),280),
    ]}
    _,_,s,m=process(payload)
    assert s.needs_review
    assert [w.declaredLengthMm for w in m.walls]==[2000,3000,2000,2800]
    assert [w.sourceLengthCm for w in m.walls]==[200,300,200,280]


def test_disproportionate_sketch_measurements_win():
    payload={"planId":"ugly","walls":[
      wall("w1",(0,0),(900,15),200),
      wall("w2",(900,15),(930,80),300),
      wall("w3",(930,80),(4,75),200),
      wall("w4",(4,75),(0,0),300),
    ]}
    _,_,s,m=process(payload)
    assert not s.needs_review, s.warnings
    assert len(m.rooms)==1
    assert abs(m.rooms[0].floorAreaM2-6)<1e-4


def test_plan3d_exact_dimensions():
    from backend.view3d import to_plan3d
    walls=[wall("w1",(0,0),(200,0),200),wall("w2",(200,0),(200,300),300),wall("w3",(200,300),(0,300),200),wall("w4",(0,300),(0,0),300)]
    _,_,_,m=process({"planId":"p3","wallHeightM":2.7,"walls":walls})
    p3=to_plan3d(m)
    got=sorted((round(x["length"]),round(x["height"]),round(x["thickness"])) for x in p3["walls"])
    assert got==[(2000,2700,120),(2000,2700,120),(3000,2700,120),(3000,2700,120)]
