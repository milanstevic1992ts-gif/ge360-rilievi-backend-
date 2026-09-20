from conftest import make_payload, solve_payload
from backend.view3d.converter import to_plan3d
from backend.view3d.builder import build_scene


def test_3d_2x3_room(rect_2x3_walls):
    _,_,_,model,_=solve_payload(make_payload(rect_2x3_walls,wall_height_m=2.7))
    data=to_plan3d(model)
    assert [round(w["length"]) for w in data["walls"]]==[2000,3000,2000,3000]
    assert all(round(w["height"])==2700 for w in data["walls"])
    assert abs(data["rooms"][0]["floorAreaM2"]-6)<0.01
    scene=build_scene(model)
    assert len(scene.geometry)>=5
