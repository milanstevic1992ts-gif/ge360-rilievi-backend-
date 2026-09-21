"""Rilievo fedele: schizzi grezzi realistici -> planimetria metrica e computo per stanza."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import solve_payload
from backend.models import PlanPayload


def W(i, a, b, length=None, **extra):
    wall = {"id": i, "a": {"x": a[0], "y": a[1]}, "b": {"x": b[0], "y": b[1]}, **extra}
    if length is not None:
        wall["lengthCm"] = length
    return wall


def payload(walls, **extra):
    return PlanPayload.model_validate({"planId": "t", "name": "T", "walls": walls, "wallHeightM": 2.7, **extra})


def rooms_by_area(model):
    return sorted(model.rooms, key=lambda r: r.floorAreaM2)


def test_un_centimetro_di_scarto_non_manda_in_revisione():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300),
             W("w3", (400, 300), (0, 300), 401), W("w4", (0, 300), (0, 0), 300)]
    _, _, s, m, v = solve_payload(payload(walls))
    assert not s.needs_review, s.warnings
    assert not v["needsReview"]
    assert abs(m.rooms[0].floorAreaM2 - 12.015) < 0.01
    assert all(w.withinTolerance for w in m.walls)
    assert max(w.lengthErrorMm for w in m.walls) < 6  # l'errore è distribuito, non concentrato


def test_smusso_45_resta_a_45_anche_se_disegnato_storto():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 200), 200),
             W("w3", (400, 200), (310, 305), 141.42),  # disegnato a ~49°
             W("w4", (310, 305), (0, 300), 300), W("w5", (0, 300), (0, 0), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert not s.needs_review, s.warnings
    assert s.wall_meta["w3"]["orientation"] == "diagonal45"
    assert abs(m.rooms[0].floorAreaM2 - 11.5) < 0.01


def test_parete_obliqua_libera():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 250), 250),
             W("w3", (400, 250), (300, 300), 111.80), W("w4", (300, 300), (0, 300), 300),
             W("w5", (0, 300), (0, 0), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert s.wall_meta["w3"]["orientation"] == "free"
    assert not s.needs_review, s.warnings
    assert abs(m.rooms[0].floorAreaM2 - 11.75) < 0.01


def test_schizzo_grezzo_storto_con_varchi_e_lato_non_misurato():
    # linee storte di ~8-10°, angoli che non si chiudono (varchi 20-40 cm), un lato senza misura
    walls = [W("w1", (0, 0), (410, 55), 400), W("w2", (430, 70), (395, 360), 300),
             W("w3", (380, 380), (-20, 330), 400), W("w4", (-40, 310), (-10, 25))]
    n, _, s, m, v = solve_payload(payload(walls))
    assert n.closed_gaps, "i varchi devono essere chiusi automaticamente"
    assert len(m.rooms) == 1
    # w4 non è misurata ma è ricavabile (w2 = 300 e angoli retti): nessuna stima dallo schizzo
    w4 = next(w for w in m.walls if w.id == "w4")
    assert w4.measured is False and w4.lengthSource == "CALCULATED" and w4.quality == "CALCULATED"
    assert w4.declaredLengthMm == pytest.approx(3000, abs=1)
    assert m.rooms[0].floorAreaM2 == pytest.approx(12.0, abs=0.005)
    assert m.rooms[0].quality.value == "OK"
    assert m.rooms[0].calculatedWallIds == ["w4"] and m.rooms[0].estimatedWallIds == []
    assert not any("w4" in q for q in m.rooms[0].questions)


def test_tramezzo_che_non_tocca_le_pareti_diventa_innesto_a_T():
    walls = [W("top", (0, 0), (600, 0), 600), W("right", (600, 0), (600, 300), 300),
             W("bottom", (600, 300), (0, 300), 600), W("left", (0, 300), (0, 0), 300),
             W("mid", (302, 18), (298, 282), 300)]
    n, _, s, m, _ = solve_payload(payload(walls))
    assert {t["node"] for t in n.tees} and len(n.tees) == 2
    assert len(m.rooms) == 2
    assert sorted(round(r.floorAreaM2, 2) for r in m.rooms) == [9.0, 9.0]
    assert all(r.adjacentRoomIds for r in m.rooms)


def test_tramezzi_in_asse_scalano_mezzo_spessore():
    walls = [W("top", (0, 0), (600, 0), 600), W("right", (600, 0), (600, 300), 300),
             W("bottom", (600, 300), (0, 300), 600), W("left", (0, 300), (0, 0), 300),
             W("mid", (300, 0), (300, 300), 300, thicknessMm=100)]
    _, _, _, m, _ = solve_payload(payload(walls, wallReference="partitionAxis"))
    for r in m.rooms:
        assert r.grossFloorAreaM2 == pytest.approx(9.0, abs=1e-3)
        assert r.floorAreaM2 == pytest.approx(2.95 * 3.0, abs=1e-3)


def test_misura_sbagliata_viene_individuata():
    walls = [W("top", (0, 0), (900, 0), 900), W("right", (900, 0), (900, 300), 300),
             W("bottom", (900, 300), (0, 300), 900), W("left", (0, 300), (0, 0), 300),
             W("s1", (300, 0), (300, 300), 330), W("s2", (600, 0), (600, 300), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert [x["wallId"] for x in s.suspects] == ["s1"]
    assert s.suspects[0]["suggestedLengthMm"] == pytest.approx(3000, abs=10)
    assert s.suspects[0]["probability"] > 0.8
    assert not s.needs_review  # deciso in autonomia
    s1 = next(w for w in m.walls if w.id == "s1")
    assert s1.declaredLengthMm == 3300 and s1.suspect  # la misura dichiarata resta scritta
    # la geometria adottata è quella coerente con il resto del rilievo
    assert all(abs(r.floorAreaM2 - 9.0) < 0.02 for r in m.rooms)
    assert any("s1" in t for r in m.rooms for t in r.decisions)
    assert all(r.questions == [] for r in m.rooms)


def test_diagonale_fissa_una_stanza_fuori_squadra():
    # stanza reale: (0,0) (400,0) (410,300) (0,300) -> disegnata come un rettangolo
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300.17),
             W("w3", (400, 300), (0, 300), 410), W("w4", (0, 300), (0, 0), 300)]
    no_diag = solve_payload(payload(walls))
    # anche senza diagonale le misure indicano una stanza fuori squadra: nessuna revisione
    assert not no_diag[2].needs_review
    assert no_diag[3].rooms[0].floorAreaM2 == pytest.approx(12.15, abs=0.05)
    diag = [{"id": "d1", "a": {"x": 0, "y": 0}, "b": {"x": 400, "y": 300}, "lengthCm": 508.04}]
    _, _, s, m, v = solve_payload(payload(walls, diagonals=diag))
    assert not s.needs_review, s.warnings
    assert m.rooms[0].floorAreaM2 == pytest.approx(12.15, abs=0.02)
    assert s.diagonal_meta[0]["withinTolerance"]


def test_computo_bagno():
    walls = [W("w1", (0, 0), (200, 0), 200), W("w2", (200, 0), (200, 250), 250),
             W("w3", (200, 250), (0, 250), 200), W("w4", (0, 250), (0, 0), 250)]
    openings = [
        {"id": "p1", "type": "door", "wallId": "w1", "widthCm": 80, "offsetCm": 60, "heightCm": 210},
        {"id": "f1", "type": "window", "wallId": "w3", "widthCm": 60, "offsetCm": 70, "heightCm": 120, "sillHeightCm": 100},
    ]
    rooms = [{"id": "bagno-1", "name": "Bagno padronale", "wallIds": ["w1", "w2", "w3", "w4"]}]
    _, _, _, m, _ = solve_payload(payload(walls, openings=openings, rooms=rooms))
    r = m.rooms[0]
    assert r.type == "bagno" and r.roomId == "bagno-1"
    assert r.floorAreaM2 == pytest.approx(5.0, abs=1e-3)
    assert r.ceilingAreaM2 == pytest.approx(5.0, abs=1e-3)
    assert r.perimeterM == pytest.approx(9.0, abs=1e-3)
    assert r.volumeM3 == pytest.approx(13.5, abs=1e-2)
    assert r.grossWallAreaM2 == pytest.approx(24.3, abs=1e-2)
    assert r.openingsAreaM2 == pytest.approx(2.40, abs=1e-3)
    assert r.netWallAreaM2 == pytest.approx(21.9, abs=1e-2)
    assert r.skirtingM == pytest.approx(8.2, abs=1e-3)
    assert r.tilingHeightMm == 2200
    assert r.tilingAreaM2 == pytest.approx(19.8 - 1.68 - 0.72, abs=1e-2)
    assert {r.widthM, r.depthM} == {2.0, 2.5}
    assert {o.id for o in r.openings} == {"p1", "f1"}
    assert len(r.wallFaces) == 4


def test_porta_sul_tramezzo_collega_le_stanze():
    walls = [W("top", (0, 0), (600, 0), 600), W("right", (600, 0), (600, 300), 300),
             W("bottom", (600, 300), (0, 300), 600), W("left", (0, 300), (0, 0), 300),
             W("mid", (300, 0), (300, 300), 300)]
    openings = [{"id": "p1", "type": "door", "wallId": "mid", "widthCm": 80, "offsetCm": 100}]
    _, _, _, m, _ = solve_payload(payload(walls, openings=openings))
    a, b = m.rooms
    assert a.openings[0].connectsToRoomId == b.roomId
    assert b.openings[0].connectsToRoomId == a.roomId
    assert a.skirtingM == pytest.approx(12 - 0.8, abs=1e-3)


def test_plan_id_non_valido_rifiutato():
    with pytest.raises(ValidationError):
        PlanPayload.model_validate({"planId": "../../etc", "walls": []})


def test_posizione_tramezzo_non_misurata_genera_domanda():
    walls = [W("top", (0, 0), (600, 0), 600), W("right", (600, 0), (600, 300), 300),
             W("bottom", (600, 300), (0, 300), 600), W("left", (0, 300), (0, 0), 300),
             W("mid", (310, 0), (310, 300), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert {t["hostWallId"] for t in s.undetermined_tees} == {"top", "bottom"}
    assert all(r.quality.value == "ESTIMATED" for r in m.rooms)
    assert all(any("mid" in t for t in r.decisions) for r in m.rooms)


def test_posizione_tramezzo_misurata_e_determinata():
    walls = [W("top1", (0, 0), (310, 0), 250), W("top2", (310, 0), (600, 0), 350),
             W("right", (600, 0), (600, 300), 300), W("bottom", (600, 300), (0, 300), 600),
             W("left", (0, 300), (0, 0), 300), W("mid", (310, 0), (310, 300), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert s.undetermined_tees == []
    assert not s.needs_review, s.warnings
    assert sorted(round(r.floorAreaM2, 2) for r in m.rooms) == [7.5, 10.5]
    assert all(r.quality.value == "OK" for r in m.rooms)


@pytest.mark.parametrize("sketch_len", [150, 300, 520])
def test_lo_schizzo_non_influenza_le_pareti_calcolate(sketch_len):
    # la parete sinistra non misurata è disegnata lunga 150, 300 o 520: il risultato non cambia
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300),
             W("w3", (400, 300), (0, sketch_len), 400), W("w4", (0, sketch_len), (0, 0))]
    _, _, s, m, _ = solve_payload(payload(walls))
    w4 = next(w for w in m.walls if w.id == "w4")
    assert w4.lengthSource == "CALCULATED"
    assert w4.calculatedLengthMm == pytest.approx(3000, abs=1)
    assert m.rooms[0].floorAreaM2 == pytest.approx(12.0, abs=0.005)


def test_due_lati_mancanti_ricavabili():
    # rettangolo con due lati consecutivi non misurati: si chiudono con gli angoli retti
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300),
             W("w3", (400, 300), (0, 300)), W("w4", (0, 300), (0, 0))]
    _, _, s, m, _ = solve_payload(payload(walls))
    src = {w.id: (w.lengthSource, round(w.calculatedLengthMm)) for w in m.walls}
    assert src["w3"] == ("CALCULATED", 4000) and src["w4"] == ("CALCULATED", 3000)
    assert m.rooms[0].floorAreaM2 == pytest.approx(12.0, abs=0.005)


def test_lati_mancanti_non_ricavabili_vengono_segnalati():
    # a L: mancano i due lati orizzontali interni/superiori, se ne conosce solo la somma
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 200), 200),
             W("w3", (400, 200), (200, 200)), W("w4", (200, 200), (200, 400), 200),
             W("w5", (200, 400), (0, 400)), W("w6", (0, 400), (0, 0), 400)]
    _, _, s, m, _ = solve_payload(payload(walls))
    src = {w.id: w.lengthSource for w in m.walls}
    assert src["w3"] == "SKETCH" and src["w5"] == "SKETCH"
    r = m.rooms[0]
    assert r.quality.value == "ESTIMATED" and sorted(r.estimatedWallIds) == ["w3", "w5"]
    assert any("non ricavabile" in t and "w3" in t for t in r.decisions)
    # la somma è comunque rispettata dalle misure: w3 + w5 = 400
    lengths = {w.id: w.calculatedLengthMm for w in m.walls}
    assert lengths["w3"] + lengths["w5"] == pytest.approx(4000, abs=1)


def test_parete_obliqua_ricavabile_non_chiede_diagonale():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 250), 250),
             W("w3", (400, 250), (300, 300), 111.80), W("w4", (300, 300), (0, 300), 300),
             W("w5", (0, 300), (0, 0), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    assert s.sketch_shape_walls == []
    assert not any("diagonale" in q for q in m.rooms[0].questions)
