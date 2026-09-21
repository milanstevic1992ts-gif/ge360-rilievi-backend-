"""Agente autonomo: decide la spiegazione più probabile, non fa domande, non inventa."""
from __future__ import annotations

import pytest

from conftest import solve_payload
from backend.cad.model import build_cad_model
from backend.geometry.hypotheses import typo_candidates
from backend.geometry.normalizer import normalize_payload
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.models import PlanPayload


def W(i, a, b, length=None):
    w = {"id": i, "a": {"x": a[0], "y": a[1]}, "b": {"x": b[0], "y": b[1]}}
    if length is not None:
        w["lengthCm"] = length
    return w


def payload(walls):
    return PlanPayload.model_validate({"planId": "auto", "walls": walls, "wallHeightM": 2.7})


def with_uncertainty(walls, samples=40):
    n = normalize_payload(payload(walls))
    s = solve_geometry(n, build_topology(n))
    return s, build_cad_model(n, s, uncertainty_samples=samples)


TRE_STANZE = [W("top", (0, 0), (900, 0), 900), W("right", (900, 0), (900, 305), 305),
              W("bottom", (900, 305), (0, 305), 900), W("left", (0, 305), (0, 0), 305),
              W("s2", (600, 0), (600, 305), 305)]


def test_candidati_di_battitura():
    kinds = dict((round(v), k) for k, v in typo_candidates(3300.0))
    assert kinds[3030] == "transposition" and kinds[3200] == "tens" and kinds[2300] == "hundreds"
    assert kinds[330] == "scale" and kinds[33000] == "scale"


def test_cifre_invertite_riconosciute_e_corrette():
    walls = TRE_STANZE + [W("s1", (300, 0), (300, 305), 350)]  # 305 digitato 350
    _, _, s, m, v = solve_payload(payload(walls))
    d = next(d for d in s.decisions if d.get("wallId") == "s1")
    assert d["kind"] == "typo" and d["typoKind"] == "transposition"
    assert d["usedMm"] == pytest.approx(3050, abs=1) and d["probability"] > 0.8
    assert not s.needs_review and not v["needsReview"]
    assert all(r.floorAreaM2 == pytest.approx(9.15, abs=0.01) for r in m.rooms)


def test_centimetri_e_millimetri_scambiati():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 3000),
             W("w3", (400, 300), (0, 300), 400), W("w4", (0, 300), (0, 0), 300)]
    _, _, s, m, _ = solve_payload(payload(walls))
    d = s.decisions[0]
    assert d["kind"] == "typo" and d["typoKind"] == "scale" and d["usedMm"] == pytest.approx(3000)
    assert m.rooms[0].floorAreaM2 == pytest.approx(12.0, abs=0.01)


def test_tramezzo_storto_di_25_gradi_non_e_una_spiegazione_plausibile():
    walls = [W("top", (0, 0), (900, 0), 900), W("right", (900, 0), (900, 300), 300),
             W("bottom", (900, 300), (0, 300), 900), W("left", (0, 300), (0, 0), 300),
             W("s1", (300, 0), (300, 300), 330), W("s2", (600, 0), (600, 300), 300)]
    _, _, s, _, _ = solve_payload(payload(walls))
    assert s.decisions[0]["kind"] == "outlier" and s.decisions[0]["wallId"] == "s1"


def test_mai_inventare_misure_dichiarate_e_origine_di_ogni_valore():
    cases = [
        TRE_STANZE + [W("s1", (300, 0), (300, 305), 350)],
        [W("w1", (0, 0), (200, 0), 200), W("w2", (200, 0), (200, 300), 300),
         W("w3", (200, 300), (0, 300), 200), W("w4", (0, 300), (0, 0), 280)],
        [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300),
         W("w3", (400, 300), (0, 300)), W("w4", (0, 300), (0, 0))],
    ]
    for walls in cases:
        _, _, s, m, _ = solve_payload(payload(walls))
        declared = {w["id"]: w.get("lengthCm") for w in walls}
        for wm in m.walls:
            if declared[wm.id] is not None:
                assert wm.declaredLengthMm == pytest.approx(declared[wm.id] * 10)  # mai toccata
                # misura conservata così com'è; se l'agente l'ha corretta resta marcata come sospetta
                assert wm.lengthSource in {"MEASURED", "SUSPECT_MEASURED"}
                assert (wm.lengthSource == "SUSPECT_MEASURED") == wm.suspect
            else:
                assert wm.lengthSource in {"CALCULATED", "SKETCH"}
        for d in s.decisions:
            assert d["text"] and d["kind"]
            assert d["probability"] is None or 0 < d["probability"] <= 1
        assert all(r.questions == [] for r in m.rooms)


def test_intervalli_monte_carlo_deterministici():
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 300), 300),
             W("w3", (400, 300), (0, 300), 400), W("w4", (0, 300), (0, 0), 300)]
    _, m1 = with_uncertainty(walls)
    _, m2 = with_uncertainty(walls)
    r = m1.rooms[0]
    lo, hi = r.floorAreaRangeM2
    assert lo < r.floorAreaM2 < hi and hi - lo < 0.2  # tutto misurato: intervallo stretto
    assert m2.rooms[0].floorAreaRangeM2 == r.floorAreaRangeM2  # stesso rilievo, stesso risultato


def test_parita_tra_ipotesi_allarga_l_intervallo():
    # 3,03 digitato 3,30 su un lato o sull'altro: non si può sapere quale -> intervallo onesto
    walls = [W("w1", (0, 0), (400, 0), 400), W("w2", (400, 0), (400, 303), 330),
             W("w3", (400, 303), (0, 303), 400), W("w4", (0, 303), (0, 0), 303)]
    s, m = with_uncertainty(walls, samples=60)
    assert s.decisions[0]["probability"] < 0.6
    lo, hi = m.rooms[0].floorAreaRangeM2
    assert hi - lo > 0.5  # l'intervallo copre entrambe le spiegazioni (12,12 e 13,20 m²)
    assert m.rooms[0].confidence < 0.6


def test_posizione_tramezzo_stimata_ha_intervallo_largo():
    walls = [W("top", (0, 0), (600, 0), 600), W("right", (600, 0), (600, 300), 300),
             W("bottom", (600, 300), (0, 300), 600), W("left", (0, 300), (0, 0), 300),
             W("mid", (310, 0), (310, 300), 300)]
    _, m = with_uncertainty(walls)
    for r in m.rooms:
        lo, hi = r.floorAreaRangeM2
        assert hi - lo > 0.2


def _pipeline(tmp_path):
    from backend.config import Settings
    from backend.db import Database
    from backend.pipeline import Pipeline
    from backend.storage import PlanStorage
    s = Settings("", tmp_path / "data", tmp_path / "data/db.sqlite3", "127.0.0.1", 9888,
                 120, 2700, 250, 25, .5, False, "http://127.0.0.1:9", "x", .05)
    return Pipeline(s, PlanStorage(s.data_dir), Database(s.db_path)), s


def test_impara_solo_dalle_conferme_dell_utente(tmp_path):
    import json
    from backend.geometry.error_model import ErrorModel
    pipe, s = _pipeline(tmp_path)
    walls = TRE_STANZE + [W("s1", (300, 0), (300, 305), 350)]
    pipe.save_raw(PlanPayload.model_validate({"planId": "impara", "walls": walls}))
    pipe.process("impara")
    model = ErrorModel(s.data_dir / "error-model.json")
    assert sum(model.data["confirmed"].values()) == 0  # la propria decisione NON è una conferma
    before = model.priors()["transposition"]
    # l'utente ricontrolla e corregge proprio come aveva deciso l'agente
    fixed = TRE_STANZE + [W("s1", (300, 0), (300, 305), 305)]
    pipe.save_raw(PlanPayload.model_validate({"planId": "impara", "walls": fixed}))
    pipe.process("impara")
    model = ErrorModel(s.data_dir / "error-model.json")
    assert model.data["confirmed"]["transposition"] == 1
    assert model.priors()["transposition"] > before
    log = (pipe.storage.plan_dir("impara") / "logs/processing.jsonl").read_text()
    assert '"confirmed":["s1"]' in log.replace(" ", "")


def test_modello_errori_limitato_anche_con_dati_assurdi(tmp_path):
    from backend.geometry.error_model import ErrorModel
    m = ErrorModel(tmp_path / "em.json")
    m.data.update(residualSumSq=1e12, residualN=10, angleSumSq=1e9, angleN=10)
    assert m.sigma_mm() <= 15.0 and m.angle_sigma_deg() <= 2.5
    m.data.update(residualSumSq=0.0, residualN=10**6, angleSumSq=0.0, angleN=10**6)
    assert m.sigma_mm() >= 2.0 and m.angle_sigma_deg() >= 0.3
