"""Modello degli errori che impara dai rilievi reali di chi usa il sistema.

Cosa impara (con "restringimento" verso valori prudenti finché i dati sono pochi):
- sigma delle misure (mm): dai residui dei rilievi che chiudono senza errori grossi;
- sigma del fuori squadra (gradi): dalle deviazioni angolari degli stessi rilievi;
- frequenza e tipo degli errori grossi: SOLO da conferme implicite dell'utente, cioè quando
  una misura che l'agente aveva corretto viene poi reinserita con il valore usato
  dall'agente (confermata) o con un altro valore (smentita).

Non impara dalle proprie decisioni (si auto-convincerebbe). Tutti i parametri sono
limitati in intervalli ragionevoli: un rilievo anomalo non può "rovinare" il modello.
"""
from __future__ import annotations

import json
import fcntl
import math
import os
import threading
from pathlib import Path
from typing import Any

from backend.geometry.hypotheses import DEFAULT_PRIORS

_LOCK = threading.RLock()
PRIOR_SIGMA_MM = 5.0
PRIOR_ANGLE_DEG = 0.8
PSEUDO_N_SIGMA = 200        # quante "misure virtuali" vale il valore prudente iniziale
PSEUDO_N_ANGLE = 100
PSEUDO_ERRORS = 3.0         # prior di Dirichlet/Beta sugli errori grossi
PSEUDO_WALLS = 100.0
TYPO_KINDS = ("transposition", "tens", "hundreds", "scale", "generic")


def _empty() -> dict[str, Any]:
    return {"version": 1, "residualSumSq": 0.0, "residualN": 0, "angleSumSq": 0.0, "angleN": 0,
            "measuredWallsSeen": 0, "confirmed": {k: 0 for k in TYPO_KINDS}, "rejected": 0, "plans": 0}


class ErrorModel:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = _empty()
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if loaded.get("version") == 1:
                    self.data.update(loaded)
            except (OSError, ValueError):
                pass

    # ------------------------------------------------------------------ parametri
    def sigma_mm(self) -> float:
        d = self.data
        v = (PSEUDO_N_SIGMA * PRIOR_SIGMA_MM ** 2 + d["residualSumSq"]) / (PSEUDO_N_SIGMA + d["residualN"])
        return round(min(15.0, max(2.0, math.sqrt(v))), 3)

    def angle_sigma_deg(self) -> float:
        d = self.data
        v = (PSEUDO_N_ANGLE * PRIOR_ANGLE_DEG ** 2 + d["angleSumSq"]) / (PSEUDO_N_ANGLE + d["angleN"])
        return round(min(2.5, max(0.3, math.sqrt(v))), 3)

    def priors(self) -> dict[str, float]:
        d = self.data
        confirmed = sum(d["confirmed"].values())
        rate = (PSEUDO_ERRORS + confirmed) / (PSEUDO_WALLS + d["measuredWallsSeen"])
        out = dict(DEFAULT_PRIORS)
        out["outlierRate"] = round(min(0.2, max(0.005, rate)), 4)
        base = {k: DEFAULT_PRIORS[k] for k in TYPO_KINDS}
        alpha = 10.0
        total = alpha + confirmed
        for k in TYPO_KINDS:
            out[k] = round((alpha * base[k] + d["confirmed"][k]) / total, 4)
        return out

    def summary(self) -> dict[str, Any]:
        return {"sigmaMm": self.sigma_mm(), "angleSigmaDeg": self.angle_sigma_deg(), "priors": self.priors(),
                "plans": self.data["plans"], "confirmedErrors": dict(self.data["confirmed"]),
                "rejected": self.data["rejected"]}

    # ------------------------------------------------------------------ apprendimento
    def observe(self, plan, solved, previous_decisions: list[dict] | None, accept_abs_mm: float) -> dict[str, Any]:
        d = self.data
        learned = {"residuals": 0, "angles": 0, "confirmed": [], "rejected": []}
        gross = any(x.get("kind") in {"typo", "outlier", "diagonal_outlier", "out_of_square"} for x in solved.decisions)
        measured = [w for w in plan.walls if w.measured]
        d["measuredWallsSeen"] += len(measured)
        d["plans"] += 1
        if not gross and not solved.needs_review:
            for w in measured:
                meta = solved.wall_meta.get(w.id, {})
                err = float(meta.get("lengthErrorMm", 0.0))
                err = min(err, 3 * accept_abs_mm)
                d["residualSumSq"] += err * err
                d["residualN"] += 1
                learned["residuals"] += 1
                if meta.get("orientation") in {"orthogonal", "diagonal45"}:
                    dev = min(3.0, float(meta.get("angleErrorDeg", 0.0)))
                    d["angleSumSq"] += dev * dev
                    d["angleN"] += 1
                    learned["angles"] += 1
        current = {w.id: w.length_mm for w in plan.walls if w.measured}
        for dec in previous_decisions or []:
            if dec.get("kind") not in {"typo", "outlier"} or dec.get("wallId") not in current:
                continue
            now = current[dec["wallId"]]
            if abs(now - float(dec.get("declaredMm", now))) < 0.5:
                continue  # misura invariata: nessuna informazione
            kind = dec.get("typoKind") if dec.get("kind") == "typo" else "generic"
            if abs(now - float(dec.get("usedMm", -1))) <= max(2.0, 0.002 * now):
                d["confirmed"][kind if kind in TYPO_KINDS else "generic"] += 1
                learned["confirmed"].append(dec["wallId"])
            else:
                d["rejected"] += 1
                learned["rejected"].append(dec["wallId"])
        return learned

    def observe_and_save(self, plan, solved, previous_decisions, accept_abs_mm, input_hash):
        # Reload under the lock: workers may have started from the same old model.
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.data = ErrorModel(self.path).data
                seen = self.data.setdefault("observedRevisions", {})
                key = f"{plan.plan_id}:{input_hash}"
                if key in seen:
                    return {"skipped": "already_observed"}
                learned = self.observe(plan, solved, previous_decisions, accept_abs_mm)
                seen[key] = True
                self.save()
                return learned

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
