from __future__ import annotations

from backend.models import PlanPayload
from backend.geometry.normalizer import normalize_payload
from backend.geometry.topology import build_topology
from backend.geometry.solver import solve_geometry
from backend.cad import build_cad_model
from backend.works import load_catalog, resolve_works


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
