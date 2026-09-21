from __future__ import annotations

from backend.models import PlanPayload
from backend.geometry.normalizer import normalize_payload
from backend.geometry.topology import build_topology
from backend.geometry.solver import solve_geometry
from backend.cad import build_cad_model
from backend.works import load_catalog, resolve_works, summarize_works


def wall(id,a,b,length):
    return {"id":id,"a":{"x":a[0],"y":a[1]},"b":{"x":b[0],"y":b[1]},"lengthCm":length}


def test_catalog_is_large_and_unique():
    data=load_catalog()
    ids=[x["id"] for x in data["works"]]
    assert len(ids) >= 60
    assert len(ids) == len(set(ids))
    assert data["version"]


def test_authoritative_work_quantities():
    p=PlanPayload.model_validate({
      "planId":"works-test","name":"Stanza","wallHeightM":2.7,
      "walls":[wall("w1",(0,0),(200,0),200),wall("w2",(200,0),(200,300),300),
               wall("w3",(200,300),(0,300),200),wall("w4",(0,300),(0,0),300)],
      "rooms":[{"id":"room-a","name":"Camera","wallIds":["w1","w2","w3","w4"]}],
      "works":[
        {"id":"a","catalogId":"tiles.install.floor","targetType":"room","targetId":"room-a"},
        {"id":"b","catalogId":"paint.walls_ceiling","targetType":"room","targetId":"room-a"},
        {"id":"c","catalogId":"door.sliding","targetType":"room","targetId":"room-a"},
      ]
    })
    n=normalize_payload(p); t=build_topology(n); s=solve_geometry(n,t); m=build_cad_model(n,s)
    rows=resolve_works(m,p.works)
    assert rows[0]["quantity"] == 6.0
    assert rows[0]["quantitySource"] == "authoritative-room-geometry"
    assert rows[1]["quantity"] > rows[0]["quantity"]
    assert rows[2]["quantity"] == 1.0 and rows[2]["unit"] == "cad."



def test_wall_demolition_uses_selected_wall_area():
    p=PlanPayload.model_validate({
      "planId":"wall-work","name":"Stanza","wallHeightM":2.7,
      "walls":[wall("w1",(0,0),(200,0),200),wall("w2",(200,0),(200,300),300),
               wall("w3",(200,300),(0,300),200),wall("w4",(0,300),(0,0),300)],
      "rooms":[{"id":"room-a","name":"Cucina","wallIds":["w1","w2","w3","w4"]}],
      "works":[
        {"id":"dem","catalogId":"wall.demolish","targetType":"wall","targetId":"w1"},
      ]
    })
    n=normalize_payload(p); t=build_topology(n); s=solve_geometry(n,t); m=build_cad_model(n,s)
    rows=resolve_works(m,p.works)
    assert len(rows)==1
    assert rows[0]["quantity"] == 5.4
    assert rows[0]["unit"] == "m²"
    assert rows[0]["quantitySource"] == "authoritative-wall-geometry"
    assert rows[0]["breakdown"][0]["lengthM"] == 2.0
    assert rows[0]["breakdown"][0]["heightM"] == 2.7
    assert "Cucina" in rows[0]["breakdown"][0]["roomNames"]


def test_wall_tiling_prefers_room_tiling_surface_and_flags_fallback():
    p=PlanPayload.model_validate({
      "planId":"tiling-work","name":"Cucina","wallHeightM":2.7,
      "walls":[wall("w1",(0,0),(200,0),200),wall("w2",(200,0),(200,300),300),
               wall("w3",(200,300),(0,300),200),wall("w4",(0,300),(0,0),300)],
      "rooms":[{"id":"room-a","name":"Cucina","wallIds":["w1","w2","w3","w4"]}],
      "works":[
        {"id":"tile","catalogId":"tiles.install.wall","targetType":"room","targetId":"room-a"},
      ]
    })
    n=normalize_payload(p); t=build_topology(n); s=solve_geometry(n,t); m=build_cad_model(n,s)
    m.rooms[0].tilingAreaM2 = 4.25
    rows=resolve_works(m,p.works)
    assert rows[0]["quantity"] == 4.25
    assert rows[0]["quantityBasis"] == "superficie rivestimento impostata"
    assert rows[0]["needsReview"] is False

    m.rooms[0].tilingAreaM2 = None
    rows=resolve_works(m,p.works)
    assert rows[0]["quantity"] == m.rooms[0].netWallAreaM2
    assert rows[0]["needsReview"] is True


def test_work_summary_aggregates_equal_items_without_breakdown_double_count():
    rows=[
      {"catalogId":"paint.walls","label":"Pitturazione pareti","category":"Pittura","unit":"m²","quantity":12.5,"needsReview":False},
      {"catalogId":"paint.walls","label":"Pitturazione pareti","category":"Pittura","unit":"m²","quantity":7.5,"needsReview":False},
      {"catalogId":"wall.demolish","label":"Demolizione parete","category":"Demolizioni","unit":"m²","quantity":5.4,"needsReview":False},
    ]
    summary=summarize_works(rows)
    paint=next(row for row in summary if row["catalogId"]=="paint.walls")
    assert paint["quantity"] == 20.0
    assert paint["resolvedItems"] == 2
