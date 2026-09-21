from __future__ import annotations

from conftest import make_payload, solve_payload


def assert_lengths(model, tol=0.5):
    for w in model.walls:
        assert abs(w.calculatedLengthMm-w.lengthMm) <= tol, (w.id,w.calculatedLengthMm,w.lengthMm)


def test_case_a_rectangle_area(rect_2x3_walls):
    _,_,_,model,validation=solve_payload(make_payload(rect_2x3_walls))
    assert validation["maxLengthErrorMm"] < 0.5
    assert len(model.rooms)==1
    assert abs(model.rooms[0].floorAreaM2-6.0) < 0.01
    assert_lengths(model)


def test_case_b_distorted_rectangle_becomes_metric_rectangle():
    walls=[
        {"id":"w1","a":{"x":10,"y":15},"b":{"x":225,"y":31},"lengthCm":200},
        {"id":"w2","a":{"x":225,"y":31},"b":{"x":241,"y":337},"lengthCm":300},
        {"id":"w3","a":{"x":241,"y":337},"b":{"x":3,"y":316},"lengthCm":200},
        {"id":"w4","a":{"x":3,"y":316},"b":{"x":10,"y":15},"lengthCm":300},
    ]
    _,_,solved,model,_=solve_payload(make_payload(walls))
    assert len(model.rooms)==1
    assert abs(model.rooms[0].floorAreaM2-6.0)<0.02
    assert max(abs(solved.wall_meta[w.id]["angleErrorDeg"]) for w in model.walls) < 0.5
    assert_lengths(model)


def test_case_c_small_corner_gaps_are_connected():
    walls=[
        {"id":"w1","a":{"x":5,"y":0},"b":{"x":195,"y":0},"lengthCm":200},
        {"id":"w2","a":{"x":202,"y":5},"b":{"x":202,"y":295},"lengthCm":300},
        {"id":"w3","a":{"x":195,"y":302},"b":{"x":5,"y":302},"lengthCm":200},
        {"id":"w4","a":{"x":0,"y":295},"b":{"x":0,"y":5},"lengthCm":300},
    ]
    normalized,_,_,model,_=solve_payload(make_payload(walls))
    assert max(normalized.merged_gaps_mm)>0
    assert len(model.rooms)==1
    assert abs(model.rooms[0].floorAreaM2-6.0)<0.02
    assert_lengths(model)


def test_case_d_real_diagonal_is_not_axis_snapped():
    walls=[{"id":"diag","a":{"x":0,"y":0},"b":{"x":100,"y":72},"lengthCm":250}]
    _,_,solved,model,_=solve_payload(make_payload(walls))
    angle=abs(solved.wall_meta["diag"]["solvedAngleDeg"])
    assert 25 < angle < 50
    assert solved.wall_meta["diag"]["orientation"]=="free"
    assert_lengths(model)


def test_case_e_door_width_and_offset_preserved(rect_2x3_walls):
    openings=[{"id":"d1","type":"door","wallId":"w2","widthCm":80,"offsetCm":120,"referenceEnd":"a","position":0.5}]
    _,_,_,model,_=solve_payload(make_payload(rect_2x3_walls,openings=openings))
    d=model.openings[0]
    assert d.widthMm==800
    assert d.offsetMm==1200
    assert abs(d.centerFromStartMm-1600)<1e-6
    assert d.heightSource=="DEFAULT"


def test_case_f_window_preserved(rect_2x3_walls):
    openings=[{"id":"f1","type":"window","wallId":"w1","widthCm":120,"offsetCm":40,"referenceEnd":"a","heightCm":140,"sillHeightCm":90}]
    _,_,_,model,_=solve_payload(make_payload(rect_2x3_walls,openings=openings))
    w=model.openings[0]
    assert w.type=="window" and w.widthMm==1200 and w.offsetMm==400
    assert w.heightMm==1400 and w.sillHeightMm==900
    assert w.heightSource=="USER_CM" and w.sillHeightSource=="USER_CM"


def test_case_g_l_shape():
    walls=[
        {"id":"w1","a":{"x":0,"y":0},"b":{"x":400,"y":0},"lengthCm":400},
        {"id":"w2","a":{"x":400,"y":0},"b":{"x":400,"y":200},"lengthCm":200},
        {"id":"w3","a":{"x":400,"y":200},"b":{"x":200,"y":200},"lengthCm":200},
        {"id":"w4","a":{"x":200,"y":200},"b":{"x":200,"y":400},"lengthCm":200},
        {"id":"w5","a":{"x":200,"y":400},"b":{"x":0,"y":400},"lengthCm":200},
        {"id":"w6","a":{"x":0,"y":400},"b":{"x":0,"y":0},"lengthCm":400},
    ]
    _,_,_,model,_=solve_payload(make_payload(walls))
    assert len(model.rooms)==1
    assert abs(model.rooms[0].floorAreaM2-12)<0.03
    assert_lengths(model)


def test_case_h_two_rooms_shared_wall():
    walls=[
        {"id":"top","a":{"x":0,"y":0},"b":{"x":600,"y":0},"lengthCm":600},
        {"id":"right","a":{"x":600,"y":0},"b":{"x":600,"y":300},"lengthCm":300},
        {"id":"bottom","a":{"x":600,"y":300},"b":{"x":0,"y":300},"lengthCm":600},
        {"id":"left","a":{"x":0,"y":300},"b":{"x":0,"y":0},"lengthCm":300},
        {"id":"shared","a":{"x":300,"y":0},"b":{"x":300,"y":300},"lengthCm":300},
    ]
    _,_,_,model,_=solve_payload(make_payload(walls))
    assert len(model.rooms)==2
    areas=sorted(round(r.floorAreaM2,2) for r in model.rooms)
    assert areas==[9.0,9.0]
    assert all("shared" in r.wallIds for r in model.rooms)


def test_case_i_three_rooms():
    walls=[
        {"id":"top","a":{"x":0,"y":0},"b":{"x":900,"y":0},"lengthCm":900},
        {"id":"right","a":{"x":900,"y":0},"b":{"x":900,"y":300},"lengthCm":300},
        {"id":"bottom","a":{"x":900,"y":300},"b":{"x":0,"y":300},"lengthCm":900},
        {"id":"left","a":{"x":0,"y":300},"b":{"x":0,"y":0},"lengthCm":300},
        {"id":"s1","a":{"x":300,"y":0},"b":{"x":300,"y":300},"lengthCm":300},
        {"id":"s2","a":{"x":600,"y":0},"b":{"x":600,"y":300},"lengthCm":300},
    ]
    _,_,_,model,_=solve_payload(make_payload(walls))
    assert len(model.rooms)==3
    assert all(abs(r.floorAreaM2-9)<0.02 for r in model.rooms)


def test_case_j_incompatible_lengths_needs_review():
    walls=[
        {"id":"w1","a":{"x":0,"y":0},"b":{"x":200,"y":0},"lengthCm":200},
        {"id":"w2","a":{"x":200,"y":0},"b":{"x":200,"y":300},"lengthCm":300},
        {"id":"w3","a":{"x":200,"y":300},"b":{"x":0,"y":300},"lengthCm":200},
        {"id":"w4","a":{"x":0,"y":300},"b":{"x":0,"y":0},"lengthCm":290},
    ]
    _,_,solved,model,validation=solve_payload(make_payload(walls))
    assert solved.needs_review
    assert validation["needsReview"]
    assert solved.closure_error_mm > 50
    # le misure dichiarate non vengono mai toccate
    assert [w.declaredLengthMm for w in model.walls]==[2000,3000,2000,2900]
    # 300 contro 290 su lati opposti: il solver non può sapere quale sia sbagliata -> le segnala entrambe
    assert {s["wallId"] for s in solved.suspects}=={"w2","w4"}
    assert len(model.rooms)==1


def test_case_k_wildly_disproportionate_sketch_uses_measurements():
    walls=[
        {"id":"w1","a":{"x":0,"y":0},"b":{"x":80,"y":3},"lengthCm":200},
        {"id":"w2","a":{"x":80,"y":3},"b":{"x":86,"y":900},"lengthCm":300},
        {"id":"w3","a":{"x":86,"y":900},"b":{"x":-220,"y":890},"lengthCm":200},
        {"id":"w4","a":{"x":-220,"y":890},"b":{"x":0,"y":0},"lengthCm":300},
    ]
    _,_,_,model,_=solve_payload(make_payload(walls))
    assert len(model.rooms)==1
    assert abs(model.rooms[0].floorAreaM2-6.0)<0.05
    assert_lengths(model)
