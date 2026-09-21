"""Motore delle ipotesi: l'agente risolve da solo le incoerenze del rilievo.

Niente domande e niente regole rigide. Quando le misure non chiudono, il motore mette
in gara le spiegazioni possibili e sceglie la più probabile (massimo a posteriori):

- ``compromise``   : nessun errore grosso, piccoli errori distribuiti su tutte le misure;
- ``typo``         : una cifra sbagliata in una misura (cifre invertite, ±10 cm, ±1 m,
                     centimetri/millimetri scambiati);
- ``outlier``      : una misura sbagliata di un valore qualsiasi (la si ricava dalle altre);
- ``out_of_square``: una parete che non è davvero a 90°/45°;
- ``diagonal_outlier``: una quota di controllo sbagliata.

Ogni ipotesi viene risolta dal solver e valutata con:

    log posterior = log verosimiglianza (quanto spiega TUTTE le misure)
                  + log prior (quanto è frequente quel tipo di errore)

La verosimiglianza usa lo stesso modello di rumore del solver (misure: sigma in mm,
angoli: sigma in gradi) più un termine debolissimo sullo schizzo, che conta solo per
decidere tra ipotesi altrimenti equivalenti. I prior possono essere imparati dai
rilievi reali (vedi ``backend/geometry/error_model.py``).

Il motore NON inventa: le misure dichiarate restano scritte come tali, ogni decisione
ha la sua probabilità e il valore effettivamente usato.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from backend.geometry.text_it import it
from backend.geometry.solver import (
    _angle,
    _angle_distance,
    _solve_once,
    acceptance_mm,
)

DEFAULT_PRIORS: dict[str, float] = {
    "outlierRate": 0.03,        # probabilità che una misura contenga un errore grosso
    "transposition": 0.30,      # 3,30 al posto di 3,03
    "tens": 0.25,               # 10 cm in più o in meno
    "hundreds": 0.15,           # 1 m in più o in meno
    "scale": 0.10,              # cm/mm scambiati
    "generic": 0.20,            # errore di valore qualsiasi
    "nonSquareRate": 0.04,      # parete che non è davvero a squadra/45°
    "nonSquareSigmaDeg": 5.0,   # ...e di quanto: pochi gradi, quasi mai 20-30°
    "diagonalOutlierRate": 0.05,
}
SKETCH_LOG_SIGMA = 0.35         # lo schizzo sbaglia le proporzioni anche del 30-40%
SKETCH_ANGLE_SIGMA_DEG = 15.0   # ...e le direzioni di una decina di gradi
MAX_ROUNDS = 3
MAX_CANDIDATE_WALLS = 6


def _loglik(plan, positions, cfg, *, sigma_mm, angle_sigma_deg) -> float:
    ll = 0.0
    overrides = cfg.get("length_overrides", {})
    free = cfg.get("free_length_ids", frozenset())
    kinds = cfg["kinds"]
    targets = cfg["targets"]
    scale = plan.scale_mm_per_unit
    for w in plan.walls:
        if w.start_node == w.end_node:
            continue
        a, b = positions[w.start_node], positions[w.end_node]
        calc = math.dist(a, b)
        if w.measured and w.id not in free:
            ll -= 0.5 * ((calc - overrides.get(w.id, w.length_mm)) / sigma_mm) ** 2
        if kinds[w.id] != "free":
            dev = math.degrees(_angle_distance(_angle(b[0] - a[0], b[1] - a[1]), targets[w.id]))
            ll -= 0.5 * (dev / angle_sigma_deg) ** 2
        sketch = math.dist(w.sketch_a, w.sketch_b) * scale
        if sketch > 1 and calc > 1:
            # lo schizzo è una traccia debole: conta solo per scegliere tra ipotesi quasi equivalenti
            ll -= 0.5 * (math.log(calc / sketch) / SKETCH_LOG_SIGMA) ** 2 * 0.05
            sketch_dir = _angle(w.sketch_b[0] - w.sketch_a[0], w.sketch_b[1] - w.sketch_a[1])
            dev_s = math.degrees(_angle_distance(_angle(b[0] - a[0], b[1] - a[1]), sketch_dir))
            ll -= 0.5 * (dev_s / SKETCH_ANGLE_SIGMA_DEG) ** 2
    ignored = cfg.get("ignored_diagonals", frozenset())
    for d in plan.diagonals:
        if d["id"] in ignored:
            continue
        calc = math.dist(positions[d["nodeA"]], positions[d["nodeB"]])
        ll -= 0.5 * ((calc - d["lengthMm"]) / sigma_mm) ** 2
    return ll


def typo_candidates(length_mm: float) -> list[tuple[str, float]]:
    """Valori che l'utente potrebbe aver voluto digitare (in mm)."""
    cm = length_mm / 10.0
    out: list[tuple[str, float]] = []
    digits = str(int(round(cm)))
    for i in range(len(digits) - 1):
        if digits[i] != digits[i + 1]:
            swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2:]
            if not swapped.startswith("0"):
                out.append(("transposition", float(swapped) * 10.0 + (cm - round(cm)) * 10.0))
    for delta in (10, -10):
        out.append(("tens", (cm + delta) * 10.0))
    for delta in (100, -100):
        out.append(("hundreds", (cm + delta) * 10.0))
    out.append(("scale", cm * 100.0))
    out.append(("scale", cm))
    seen, clean = set(), []
    for kind, v in out:
        if v >= 50.0 and abs(v - length_mm) > 1.0 and round(v, 1) not in seen:
            seen.add(round(v, 1))
            clean.append((kind, v))
    return clean


def _solve(plan, cfg, *, sigma_mm, angle_sigma_deg):
    work = plan
    ignored = cfg.get("ignored_diagonals", frozenset())
    if ignored:
        work = copy.copy(plan)
        work.diagonals = [d for d in plan.diagonals if d["id"] not in ignored]
    free = cfg.get("free_length_ids", frozenset())
    return _solve_once(
        work, cfg["targets"], cfg["kinds"], sigma_mm=sigma_mm,
        free_length_ids=free, relaxed=cfg["relaxed"],
        drop_len_ids=frozenset(cfg.get("drop_len_ids", frozenset())) | free,
        drop_dir_ids=cfg.get("drop_dir_ids", frozenset()),
        length_overrides=cfg.get("length_overrides") or None,
        angle_sigma_deg=angle_sigma_deg,
    )


def _inconsistent(plan, positions, cfg, accept_abs_mm, accept_rel, angle_sigma_deg):
    """Misure/angoli ancora non spiegati dalla configurazione corrente."""
    overrides = cfg.get("length_overrides", {})
    free = cfg.get("free_length_ids", frozenset())
    bad_walls, bad_angles, bad_diags = [], [], []
    for w in plan.walls:
        if w.start_node == w.end_node:
            continue
        a, b = positions[w.start_node], positions[w.end_node]
        calc = math.dist(a, b)
        if w.measured and w.id not in free:
            target = overrides.get(w.id, w.length_mm)
            tol = acceptance_mm(target, accept_abs_mm, accept_rel)
            if abs(calc - target) > tol:
                bad_walls.append((abs(calc - target) / tol, w.id))
        if cfg["kinds"][w.id] != "free":
            dev = math.degrees(_angle_distance(_angle(b[0] - a[0], b[1] - a[1]), cfg["targets"][w.id]))
            if dev > 2.0 * angle_sigma_deg:
                bad_angles.append((dev, w.id))
    for d in plan.diagonals:
        if d["id"] in cfg.get("ignored_diagonals", frozenset()):
            continue
        calc = math.dist(positions[d["nodeA"]], positions[d["nodeB"]])
        tol = acceptance_mm(d["lengthMm"], accept_abs_mm, accept_rel)
        if abs(calc - d["lengthMm"]) > tol:
            bad_diags.append((abs(calc - d["lengthMm"]) / tol, d["id"]))
    return sorted(bad_walls, reverse=True), sorted(bad_angles, reverse=True), sorted(bad_diags, reverse=True)


def _with(cfg, **changes):
    out = dict(cfg)
    for k, v in changes.items():
        out[k] = v
    return out


def _wall_error_rank(plan, positions, cfg):
    overrides = cfg.get("length_overrides", {})
    free = cfg.get("free_length_ids", frozenset())
    rows = []
    for w in plan.walls:
        if not w.measured or w.id in free or w.id in overrides or w.start_node == w.end_node:
            continue
        calc = math.dist(positions[w.start_node], positions[w.end_node])
        rows.append((abs(calc - w.length_mm), w.id))
    return [wid for _, wid in sorted(rows, reverse=True)]


def resolve_inconsistencies(plan, targets, kinds, *, sigma_mm, relaxed, drops, accept_abs_mm, accept_rel,
                            angle_sigma_deg, priors=None) -> dict[str, Any]:
    pri = dict(DEFAULT_PRIORS)
    pri.update(priors or {})
    wall_by_id = {w.id: w for w in plan.walls}
    cfg: dict[str, Any] = {
        "targets": dict(targets), "kinds": dict(kinds), "relaxed": relaxed,
        "length_overrides": {}, "free_length_ids": frozenset(), "ignored_diagonals": frozenset(),
        **drops,
    }
    positions, opt = _solve(plan, cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
    decisions: list[dict[str, Any]] = []
    evaluated = 0
    alt_cfgs: list = []

    for round_no in range(MAX_ROUNDS):
        bad_walls, bad_angles, bad_diags = _inconsistent(plan, positions, cfg, accept_abs_mm, accept_rel, angle_sigma_deg)
        if not (bad_walls or bad_angles or bad_diags):
            break
        base_ll = _loglik(plan, positions, cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
        hyps: list[dict[str, Any]] = [{"kind": "compromise", "cfg": cfg, "positions": positions, "opt": opt,
                                       "logpost": base_ll, "label": "piccoli errori distribuiti su tutte le misure"}]
        log_out = math.log(pri["outlierRate"])

        # errori di misura sulle pareti con lo scarto più grande
        for wid in _wall_error_rank(plan, positions, cfg)[:MAX_CANDIDATE_WALLS]:
            w = wall_by_id[wid]
            free_cfg = _with(cfg, free_length_ids=cfg["free_length_ids"] | {wid})
            pos_f, opt_f = _solve(plan, free_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
            evaluated += 1
            implied = math.dist(pos_f[w.start_node], pos_f[w.end_node])
            occam = math.log(sigma_mm * math.sqrt(2 * math.pi) / max(w.length_mm, 1000.0))
            hyps.append({"kind": "outlier", "wallId": wid, "cfg": free_cfg, "positions": pos_f, "opt": opt_f,
                         "usedMm": implied,
                         "logpost": _loglik(plan, pos_f, free_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
                         + log_out + math.log(pri["generic"]) + occam,
                         "label": f"misura di {wid} sbagliata (dal resto: {implied / 10:.1f} cm)"})
            near = max(3 * acceptance_mm(implied, accept_abs_mm, accept_rel), 0.05 * implied)
            for typo_kind, value in typo_candidates(w.length_mm):
                if abs(value - implied) > near:
                    continue
                t_cfg = _with(cfg, length_overrides={**cfg["length_overrides"], wid: value})
                pos_t, opt_t = _solve(plan, t_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
                evaluated += 1
                hyps.append({"kind": "typo", "typoKind": typo_kind, "wallId": wid, "cfg": t_cfg,
                             "positions": pos_t, "opt": opt_t, "usedMm": value,
                             "logpost": _loglik(plan, pos_t, t_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
                             + log_out + math.log(pri[typo_kind]),
                             "label": f"{wid} digitata {w.length_mm / 10:.1f} invece di {value / 10:.1f} cm"})

        # pareti che forse non sono davvero a squadra
        angle_candidates = [wid for _, wid in bad_angles]
        for wid in _wall_error_rank(plan, positions, cfg)[:3]:
            for w2 in plan.walls:
                if w2.id not in angle_candidates and cfg["kinds"][w2.id] != "free" and \
                        ({w2.start_node, w2.end_node} & {wall_by_id[wid].start_node, wall_by_id[wid].end_node}):
                    angle_candidates.append(w2.id)
        for wid in angle_candidates[:MAX_CANDIDATE_WALLS + 2]:
            w = wall_by_id[wid]
            a, b = positions[w.start_node], positions[w.end_node]
            a_cfg = _with(cfg, kinds={**cfg["kinds"], wid: "free"},
                          targets={**cfg["targets"], wid: _angle(b[0] - a[0], b[1] - a[1])})
            pos_a, opt_a = _solve(plan, a_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
            evaluated += 1
            a2, b2 = pos_a[w.start_node], pos_a[w.end_node]
            dev = math.degrees(_angle_distance(_angle(b2[0] - a2[0], b2[1] - a2[1]), cfg["targets"][wid]))
            # prior sull'entità del fuori squadra: pochi gradi sono comuni, 20° quasi mai
            ns = pri["nonSquareSigmaDeg"]
            occam = math.log(angle_sigma_deg / ns) - 0.5 * (dev / ns) ** 2
            hyps.append({"kind": "out_of_square", "wallId": wid, "cfg": a_cfg, "positions": pos_a, "opt": opt_a,
                         "deviationDeg": dev,
                         "logpost": _loglik(plan, pos_a, a_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
                         + math.log(pri["nonSquareRate"]) + occam,
                         "label": f"{wid} fuori squadra di {dev:.1f}°"})

        # quote di controllo sbagliate
        for _, did in bad_diags[:3]:
            d_cfg = _with(cfg, ignored_diagonals=cfg["ignored_diagonals"] | {did})
            pos_d, opt_d = _solve(plan, d_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
            evaluated += 1
            occam = math.log(sigma_mm * math.sqrt(2 * math.pi) / 3000.0)
            hyps.append({"kind": "diagonal_outlier", "diagonalId": did, "cfg": d_cfg, "positions": pos_d, "opt": opt_d,
                         "logpost": _loglik(plan, pos_d, d_cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
                         + math.log(pri["diagonalOutlierRate"]) + occam,
                         "label": f"quota {did} sbagliata"})

        hyps = [h for h in hyps if h["opt"].success or h["kind"] == "compromise"]
        top = max(h["logpost"] for h in hyps)
        weights = [math.exp(h["logpost"] - top) for h in hyps]
        total = sum(weights)
        for h, wgt in zip(hyps, weights):
            h["probability"] = wgt / total
        # a parità di punteggio vince l'ipotesi più semplice (ordine stabile = risultato riproducibile)
        best = max(hyps, key=lambda h: (round(h["probability"], 6), h["kind"] == "compromise"))
        alternatives = [{"label": h["label"], "probability": round(h["probability"], 3)}
                        for h in sorted(hyps, key=lambda h: -h["probability"]) if h is not best][:3]

        decision = {"id": f"d{len(decisions) + 1}", "kind": best["kind"], "probability": round(best["probability"], 3),
                    "alternatives": alternatives, "round": round_no + 1}
        if best["kind"] in {"typo", "outlier"}:
            w = wall_by_id[best["wallId"]]
            decision.update(wallId=w.id, declaredMm=w.length_mm, usedMm=round(best["usedMm"], 1))
            if best["kind"] == "typo":
                decision["typoKind"] = best["typoKind"]
                decision["text"] = (f"Parete {w.id}: misurata {w.length_mm / 10:.1f} cm, trattata come "
                                    f"{best['usedMm'] / 10:.1f} cm ({_typo_label(best['typoKind'])})")
            else:
                decision["text"] = (f"Parete {w.id}: misura {w.length_mm / 10:.1f} cm incompatibile con il resto, "
                                    f"usato {best['usedMm'] / 10:.1f} cm ricavato dalle altre misure")
        elif best["kind"] == "out_of_square":
            decision.update(wallId=best["wallId"], deviationDeg=round(best["deviationDeg"], 2))
            decision["text"] = f"Parete {best['wallId']}: fuori squadra di {best['deviationDeg']:.1f}°, come indicano le misure"
        elif best["kind"] == "diagonal_outlier":
            decision.update(diagonalId=best["diagonalId"])
            decision["text"] = f"Quota {best['diagonalId']} incompatibile con le altre misure: non usata"
        else:
            bw = [wid for _, wid in bad_walls]
            decision.update(wallIds=bw)
            decision["text"] = ("Piccoli errori distribuiti su tutte le misure"
                                + (f" (pareti {', '.join(bw)} oltre la tolleranza)" if bw else ""))
        decision["text"] = it(decision["text"])
        decision["alternatives"] = [{**a, "label": it(a["label"])} for a in decision["alternatives"]]
        decisions.append(decision)
        # le alternative credibili restano disponibili per il Monte Carlo (incertezza onesta)
        alt_cfgs = [(round(h["probability"], 4), h["cfg"]) for h in hyps if h is not best and h["probability"] >= 0.05]
        cfg, positions, opt = best["cfg"], best["positions"], best["opt"]
        if best["kind"] == "compromise":
            break

    return {
        "positions": positions, "opt": opt, "decisions": decisions, "evaluated": evaluated,
        "alternatives": alt_cfgs,
        "config": {k: cfg[k] for k in ("targets", "kinds", "length_overrides", "free_length_ids",
                                      "ignored_diagonals", "drop_len_ids", "drop_dir_ids")},
    }


def _typo_label(kind: str) -> str:
    return {
        "transposition": "cifre invertite",
        "tens": "10 cm di differenza",
        "hundreds": "1 m di differenza",
        "scale": "centimetri e millimetri scambiati",
    }.get(kind, kind)


# ---------------------------------------------------------------------------------------
# Forma delle pareti: invece di una soglia fissa sull'angolo dello schizzo, per le pareti
# ambigue si mettono in gara "a squadra", "a 45°" e "obliqua" e decidono le misure.
# ---------------------------------------------------------------------------------------
SHAPE_PRIORS = {"orthogonal": 0.85, "diagonal45": 0.07, "free": 0.08}
AMBIGUOUS_FROM_DEG = 12.0   # sotto questa deviazione dallo schizzo la forma è ovvia
MAX_SHAPE_CANDIDATES = 8


def _shape_logprior(kind: str, sketch_dev_deg: float) -> float:
    if kind == "free":
        # obliqua: nessuna preferenza di direzione (densità uniforme su 180°, alla stessa risoluzione)
        return math.log(SHAPE_PRIORS["free"]) + math.log(SKETCH_ANGLE_SIGMA_DEG * math.sqrt(2 * math.pi) / 180.0)
    return math.log(SHAPE_PRIORS[kind]) - 0.5 * (sketch_dev_deg / SKETCH_ANGLE_SIGMA_DEG) ** 2


def classify_wall_shapes(plan, targets, kinds, base, *, sigma_mm, relaxed, angle_sigma_deg):
    """Ritorna (targets, kinds, decisions) con la forma più probabile per le pareti ambigue."""
    from backend.geometry.solver import _sketch_angle

    targets, kinds = dict(targets), dict(kinds)
    decisions: list[dict[str, Any]] = []
    ambiguous = []
    for w in plan.walls:
        a = _sketch_angle(w)
        c90 = min((base + k * math.pi / 2 for k in range(-4, 5)), key=lambda t: _angle_distance(t, a))
        d90 = math.degrees(_angle_distance(c90, a))
        c45 = min((base + math.pi / 4 + k * math.pi / 2 for k in range(-4, 5)), key=lambda t: _angle_distance(t, a))
        d45 = math.degrees(_angle_distance(c45, a))
        if min(d90, d45) >= AMBIGUOUS_FROM_DEG or kinds[w.id] == "free":
            ambiguous.append((min(d90, d45), w, a, c90, d90, c45, d45))
    ambiguous.sort(key=lambda r: -r[0])
    for _, w, a, c90, d90, c45, d45 in ambiguous[:MAX_SHAPE_CANDIDATES]:
        options = [("orthogonal", c90, d90), ("diagonal45", c45, d45), ("free", a, 0.0)]
        scored = []
        for kind, target, dev in options:
            cfg = {"targets": {**targets, w.id: target}, "kinds": {**kinds, w.id: kind}, "relaxed": relaxed,
                   "length_overrides": {}, "free_length_ids": frozenset(), "ignored_diagonals": frozenset()}
            pos, opt = _solve(plan, cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
            ll = _loglik(plan, pos, cfg, sigma_mm=sigma_mm, angle_sigma_deg=angle_sigma_deg)
            # l'angolo dello schizzo è già nel prior: si toglie dalla verosimiglianza per non contarlo due volte
            scored.append((ll + _shape_logprior(kind, dev), kind, target, dev))
        top = max(sc for sc, *_ in scored)
        weights = [math.exp(sc - top) for sc, *_ in scored]
        total = sum(weights)
        best_i = max(range(len(scored)), key=lambda i: weights[i])
        _, kind, target, dev = scored[best_i]
        prob = weights[best_i] / total
        if kind != kinds[w.id]:
            label = {"orthogonal": "a squadra", "diagonal45": "a 45°", "free": "obliqua"}[kind]
            decisions.append({
                "kind": "wall_shape", "wallId": w.id, "shape": kind, "probability": round(prob, 3),
                "sketchDeviationDeg": round(dev, 1),
                "text": f"Parete {w.id}: disegnata storta di {dev:.0f}°, considerata {label} (è la forma che spiega meglio le misure)"
                if kind != "free" else f"Parete {w.id}: considerata obliqua come nello schizzo",
            })
        targets[w.id], kinds[w.id] = target, kind
    for d in decisions:
        d["text"] = it(d["text"])
    return targets, kinds, decisions
