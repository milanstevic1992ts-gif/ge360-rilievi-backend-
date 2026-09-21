"""Incertezza dei m² con simulazione Monte Carlo.

Il rilievo viene ricalcolato N volte facendo variare, dentro i loro errori tipici:
- le misure (rumore di qualche mm),
- gli angoli (fuori squadra tipico),
- ciò che viene dallo schizzo (lati non misurabili, posizione dei tramezzi),
- le ipotesi alternative sugli errori, con la loro probabilità.

Per ogni stanza si ottiene un intervallo (10°-90° percentile) invece di un numero
finto-preciso. Il generatore è inizializzato dal contenuto del rilievo: stesso rilievo,
stesso risultato (niente numeri che cambiano a ogni calcolo).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

import numpy as np

from backend.geometry.solver import SolverResult, _solve_once


def _seed(plan) -> int:
    raw = json.dumps({"w": [(w.id, w.length_mm, w.sketch_a, w.sketch_b) for w in plan.walls],
                      "d": plan.diagonals, "t": plan.tees}, sort_keys=True, default=str)
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def _perturbed(plan, cfg, rng, sigma_mm, angle_sigma_deg):
    p = copy.copy(plan)
    p.walls = [copy.copy(w) for w in plan.walls]
    drop_len = cfg.get("drop_len_ids", frozenset())
    for w in p.walls:
        if w.measured:
            w.length_mm = max(10.0, w.length_mm + rng.normal(0.0, sigma_mm))
        elif w.id not in drop_len:
            w.length_mm = max(10.0, w.length_mm * math.exp(rng.normal(0.0, 0.15)))
    p.tees = [{**t, "t": float(min(0.97, max(0.03, t["t"] + rng.normal(0.0, 0.04))))} for t in plan.tees]
    p.diagonals = [{**d, "lengthMm": d["lengthMm"] + rng.normal(0.0, sigma_mm)}
                   for d in plan.diagonals if d["id"] not in cfg.get("ignored_diagonals", frozenset())]
    targets = dict(cfg["targets"])
    for wid, kind in cfg["kinds"].items():
        if kind != "free":
            targets[wid] = targets[wid] + math.radians(rng.normal(0.0, angle_sigma_deg))
    overrides = {k: v + rng.normal(0.0, sigma_mm) for k, v in (cfg.get("length_overrides") or {}).items()}
    return p, targets, overrides


def room_area_uncertainty(plan, solved: SolverResult, base_rooms, *, samples: int = 40) -> dict[str, Any]:
    from backend.geometry.rooms import detect_rooms  # evita import circolare

    cfg = solved.solve_config or {}
    if samples <= 0 or not base_rooms or not cfg.get("targets"):
        return {}
    sigma_mm = cfg.get("sigma_mm", 5.0)
    angle_sigma = cfg.get("angle_sigma_deg", 0.8)
    alts = [(p, c) for p, c in cfg.get("alternatives", []) if p > 0]
    p_map = max(0.0, 1.0 - sum(p for p, _ in alts))
    choices = [cfg] + [c for _, c in alts]
    weights = np.array([p_map] + [p for p, _ in alts], dtype=float)
    weights = weights / weights.sum() if weights.sum() > 0 else np.array([1.0] + [0.0] * len(alts))

    samples = min(200, samples)
    rng = np.random.default_rng(_seed(plan))
    areas: dict[str, list[float]] = {r.roomId: [] for r in base_rooms}
    totals: list[float] = []
    ok = 0
    for _ in range(samples):
        chosen = choices[int(rng.choice(len(choices), p=weights))]
        full = {**cfg, **chosen}
        p, targets, overrides = _perturbed(plan, full, rng, sigma_mm, angle_sigma)
        try:
            positions, opt = _solve_once(
                p, targets, full["kinds"], sigma_mm=sigma_mm,
                free_length_ids=full.get("free_length_ids", frozenset()),
                relaxed=full.get("relaxed", frozenset()),
                drop_len_ids=frozenset(full.get("drop_len_ids", frozenset())) | full.get("free_length_ids", frozenset()),
                drop_dir_ids=full.get("drop_dir_ids", frozenset()),
                length_overrides=overrides or None, angle_sigma_deg=angle_sigma,
            )
        except Exception:
            continue
        if not opt.success:
            continue
        sample = SolverResult(node_positions=positions, wall_meta={}, warnings=[], operations=[],
                              needs_review=False, closure_error_mm=0.0, max_length_error_mm=0.0)
        rooms = detect_rooms(p, sample)
        if not rooms:
            continue
        ok += 1
        totals.append(sum(r.floorAreaM2 for r in rooms))
        # Stable wall boundaries avoid mixing neighbouring rooms when centroids move.
        matched = set()
        for r in rooms:
            candidates = [base for base in base_rooms
                          if set(base.wallIds) == set(r.wallIds) and base.roomId not in matched]
            if len(candidates) == 1:
                rid = candidates[0].roomId
                matched.add(rid)
                areas[rid].append(r.floorAreaM2)

    def stats(values):
        if len(values) < max(5, samples // 4):
            return None
        arr = np.asarray(values)
        return {"p10": round(float(np.percentile(arr, 10)), 3), "p50": round(float(np.percentile(arr, 50)), 3),
                "p90": round(float(np.percentile(arr, 90)), 3), "std": round(float(arr.std()), 4)}

    return {"samples": ok, "rooms": {rid: stats(v) for rid, v in areas.items()}, "total": stats(totals)}
