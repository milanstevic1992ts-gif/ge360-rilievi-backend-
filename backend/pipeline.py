from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime, timezone

from backend.cad import build_cad_model, export_dxf, export_pdf, export_png, export_svg
from backend.agent.prompt_loader import MAX_ERROR_TOLERANCE_RATIO
from backend.config import Settings
from backend.db import Database
from backend.geometry.normalizer import normalize_payload
from backend.geometry.score import geometry_score
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.geometry.validator import validate_geometry
from backend.models import PlanPayload, PlanStatus, QualityStatus
from backend.storage import PlanStorage
from backend.works import resolve_works
from backend.view3d import to_plan3d


class Pipeline:
    def __init__(self, settings: Settings, storage: PlanStorage, db: Database):
        self.settings = settings
        self.storage = storage
        self.db = db

    def save_raw(self, payload: PlanPayload) -> dict:
        if not payload.planId:
            payload = payload.model_copy(update={"planId": uuid.uuid4().hex})
        data = payload.model_dump(mode="json")
        path = self.storage.save_raw(payload.planId, data)
        self.db.upsert_raw(payload.planId, payload.name, self.storage.plan_dir(payload.planId))
        self.storage.append_log(
            payload.planId,
            {
                "event": "raw_saved",
                "inputHash": self.storage.sha256_json(data),
                "path": str(path),
            },
        )
        return {"success": True, "planId": payload.planId, "status": PlanStatus.RAW.value}

    def process(self, plan_id: str, raw_override: dict | None = None) -> dict:
        started = time.perf_counter()
        created_at = datetime.now(timezone.utc).isoformat()
        self.db.set_status(plan_id, PlanStatus.PROCESSING, error="")
        raw = raw_override if raw_override is not None else self.storage.raw_payload(plan_id)
        input_hash = self.storage.sha256_json(raw)
        version = self.storage.next_version(plan_id)
        out = self.storage.version_dir(plan_id, version)
        initial_manifest = {
            "planId": plan_id,
            "version": version,
            "status": PlanStatus.PROCESSING.value,
            "createdAt": created_at,
            "inputHash": input_hash,
            "files": [],
            "glb": None,
        }
        self.storage.write_json_atomic(out / "manifest.json", initial_manifest)
        self.storage.append_log(
            plan_id,
            {
                "event": "processing_started",
                "inputHash": input_hash,
                "version": version,
            },
        )

        try:
            payload = PlanPayload.model_validate(raw)
            if payload.planId and payload.planId != plan_id:
                raise ValueError(f"raw revision belongs to {payload.planId}, expected {plan_id}")
            if not payload.planId:
                payload = payload.model_copy(update={"planId": plan_id})
            normalized = normalize_payload(
                payload,
                default_thickness_mm=self.settings.default_wall_thickness_mm,
                default_height_mm=self.settings.default_wall_height_mm,
                snap_tolerance_mm=self.settings.snap_tolerance_mm,
                auto_close_mm=self.settings.auto_close_mm,
            )
            topology = build_topology(normalized)
            survey_kwargs = self._survey_kwargs()
            solved = solve_geometry(
                normalized,
                topology,
                orthogonal_tolerance_deg=self.settings.orthogonal_tolerance_deg,
                length_tolerance_mm=self.settings.length_tolerance_mm,
                **survey_kwargs,
            )
            tiling_h = self.settings.bath_tiling_height_mm

            agent_log = {
                "enabled": self.settings.ai_enabled,
                "aiAvailable": False,
                "iterations": 0,
                "proposals": [],
                "accepted": [],
                "rejected": [],
                "offline": False,
                "instructionVersion": None,
                "errorToleranceRatio": MAX_ERROR_TOLERANCE_RATIO,
                "estimatedErrorRatio": 0.0,
                "overErrorTolerance": False,
                "assessment": {},
                "missingCapabilities": [],
            }
            score_before = None
            agent_uncertainty = (
                solved.needs_review
                or bool(solved.undetermined_tees)
                or bool(solved.sketch_shape_walls)
                or any(meta.get("lengthSource") == "SKETCH" for meta in solved.wall_meta.values())
            )
            if self.settings.ai_enabled and agent_uncertainty:
                try:
                    from backend.agent import GeometryAgent, OllamaClient

                    pre_model = build_cad_model(normalized, solved, bath_tiling_height_mm=tiling_h)
                    pre_val = validate_geometry(
                        normalized,
                        solved,
                        pre_model.rooms,
                        length_tolerance_mm=self.settings.length_tolerance_mm,
                    )
                    score_before = geometry_score(pre_val, len(pre_model.rooms))
                    run = GeometryAgent(
                        OllamaClient(
                            self.settings.ollama_url,
                            self.settings.ollama_model,
                            self.settings.ollama_timeout,
                        ),
                        5,
                        self.settings.length_tolerance_mm,
                        self.settings.orthogonal_tolerance_deg,
                        solver_kwargs=survey_kwargs,
                    ).improve(normalized, topology, solved)
                    normalized = run.plan
                    topology = run.topology
                    solved = run.solved
                    agent_log = {
                        "enabled": True,
                        "aiAvailable": not run.offline,
                        "iterations": run.iterations,
                        "proposals": run.proposals,
                        "accepted": run.accepted,
                        "rejected": run.rejected,
                        "offline": run.offline,
                        "instructionVersion": run.instruction_version,
                        "errorToleranceRatio": run.error_tolerance_ratio,
                        "estimatedErrorRatio": run.estimated_error_ratio,
                        "overErrorTolerance": run.estimated_error_ratio > run.error_tolerance_ratio,
                        "assessment": run.assessment,
                        "missingCapabilities": run.missing_capabilities,
                    }
                    if agent_log["overErrorTolerance"]:
                        solved.needs_review = True
                        solved.warnings.append(
                            f"IA: errore/incertezza residua {run.estimated_error_ratio:.0%} oltre "
                            f"la tolleranza consentita {run.error_tolerance_ratio:.0%}; "
                            "risultato prodotto comunque ma da revisionare"
                        )
                except Exception as exc:
                    agent_log.update(
                        {
                            "aiAvailable": False,
                            "offline": True,
                            "error": str(exc),
                        }
                    )

            model = build_cad_model(normalized, solved, bath_tiling_height_mm=tiling_h)
            interpretation = None
            if self.settings.ai_enabled:
                from backend.agent import OllamaClient
                from backend.agent.interpreter import interpret

                interpretation = interpret(
                    OllamaClient(self.settings.ollama_url, self.settings.ollama_model, self.settings.ollama_timeout),
                    model,
                )
                if interpretation["roomHints"]:
                    model = build_cad_model(
                        normalized, solved, bath_tiling_height_mm=tiling_h, room_hints=interpretation["roomHints"]
                    )
                model.metadata["ai"] = {
                    "available": interpretation["available"],
                    "version": interpretation["version"],
                    "questions": interpretation["questions"],
                    "summary": interpretation["summary"],
                    "roomHints": interpretation["roomHints"],
                }
            agent_log["interpreter"] = interpretation
            validation = validate_geometry(
                normalized,
                solved,
                model.rooms,
                length_tolerance_mm=self.settings.length_tolerance_mm,
            )
            model.needsReview = bool(model.needsReview or validation["needsReview"])
            score = geometry_score(validation, len(model.rooms))
            max_gap = float(model.metadata.get("mergedEndpointMaxGapMm", 0))
            estimated = any(r.quality == QualityStatus.ESTIMATED for r in model.rooms)
            quality_status = (
                QualityStatus.NEEDS_REVIEW
                if model.needsReview
                else (QualityStatus.ESTIMATED if estimated else QualityStatus.OK)
            )
            quality = {
                "status": quality_status.value,
                "closureErrorCm": validation["closureErrorCm"],
                "maxLengthErrorMm": validation["maxLengthErrorMm"],
                "geometryScore": score,
                "warnings": validation["warnings"],
                "errors": validation["errors"],
                "suspects": validation["suspects"],
                "diagonals": validation["diagonals"],
                "acceptance": {
                    "absMm": self.settings.accept_abs_mm,
                    "rel": self.settings.accept_rel,
                    "rule": "scarto per lato <= max(absMm, rel * lunghezza)",
                },
            }
            model.quality = quality
            resolved_works = resolve_works(model, payload.works)
            model.metadata["works"] = resolved_works
            totals = self.plan_totals(model)
            totals["works"] = len(resolved_works)
            totals["workItemsNeedingReview"] = sum(1 for row in resolved_works if row.get("needsReview"))
            model.metadata["totals"] = totals

            self.storage.write_json_atomic(out / "processed-plan.json", model.model_dump(mode="json"))
            dxf_validation = export_dxf(model, out / "plan.dxf")
            export_svg(model, out / "plan.svg")
            export_png(model, out / "preview.png")
            export_pdf(model, out / "plan.pdf")
            self.storage.write_json_atomic(out / "plan3d.json", to_plan3d(model))

            total_area = round(sum(room.floorAreaM2 for room in model.rooms), 6)
            summary = {"rooms": len(model.rooms), "floorAreaM2": total_area}
            status = PlanStatus.NEEDS_REVIEW if model.needsReview else PlanStatus.PROCESSED
            completed_at = datetime.now(timezone.utc).isoformat()
            manifest = {
                "planId": plan_id,
                "version": version,
                "status": status.value,
                "createdAt": created_at,
                "completedAt": completed_at,
                "inputHash": input_hash,
                "quality": quality,
                "summary": summary,
                "totals": totals,
                "dxfValidation": dxf_validation,
                "files": sorted(p.name for p in out.iterdir() if p.is_file() and p.name != "manifest.json"),
                "glb": None,
                "agent": agent_log,
            }
            self.storage.write_json_atomic(out / "manifest.json", manifest)
            self.storage.publish_current(plan_id, out)
            self.db.set_status(
                plan_id,
                status,
                version=version,
                quality=quality,
                needs_review=model.needsReview,
                error="",
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            self.storage.append_log(
                plan_id,
                {
                    "event": "processing_completed",
                    "inputHash": input_hash,
                    "solverOperations": solved.operations,
                    "aiAvailable": agent_log["aiAvailable"],
                    "aiInstructionVersion": agent_log.get("instructionVersion"),
                    "aiErrorToleranceRatio": agent_log.get("errorToleranceRatio"),
                    "aiEstimatedErrorRatio": agent_log.get("estimatedErrorRatio"),
                    "aiOverErrorTolerance": agent_log.get("overErrorTolerance"),
                    "aiAssessment": agent_log.get("assessment"),
                    "aiMissingCapabilities": agent_log.get("missingCapabilities"),
                    "aiProposals": agent_log["proposals"],
                    "acceptedOperations": agent_log["accepted"],
                    "rejectedOperations": agent_log["rejected"],
                    "geometryScoreBefore": score_before,
                    "geometryScoreAfter": score,
                    "processingTimeMs": elapsed_ms,
                    "warnings": quality["warnings"],
                    "errors": quality["errors"],
                    "version": version,
                },
            )
            return self.process_response(plan_id, model, version, status, agent_log)
        except Exception as exc:
            completed_at = datetime.now(timezone.utc).isoformat()
            error_manifest = {
                **initial_manifest,
                "status": PlanStatus.ERROR.value,
                "completedAt": completed_at,
                "error": str(exc),
                "files": sorted(p.name for p in out.iterdir() if p.is_file() and p.name != "manifest.json"),
            }
            self.storage.write_json_atomic(out / "manifest.json", error_manifest)
            self.db.set_status(plan_id, PlanStatus.ERROR, error=str(exc))
            self.storage.append_log(
                plan_id,
                {
                    "event": "processing_error",
                    "inputHash": input_hash,
                    "version": version,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=12),
                    "processingTimeMs": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise

    def _survey_kwargs(self) -> dict:
        return {
            "accept_abs_mm": self.settings.accept_abs_mm,
            "accept_rel": self.settings.accept_rel,
            "sigma_mm": self.settings.measure_sigma_mm,
            "diagonal_snap_deg": self.settings.diagonal_snap_deg,
        }

    @staticmethod
    def plan_totals(model) -> dict:
        rooms = model.rooms

        def total(attr):
            return round(sum(float(getattr(r, attr) or 0) for r in rooms), 4)

        questions = []
        for r in rooms:
            questions += [f"{r.name}: {q}" for q in r.questions]
        questions += list((model.metadata.get("ai") or {}).get("questions") or [])
        return {
            "rooms": len(rooms),
            "floorAreaM2": total("floorAreaM2"),
            "grossFloorAreaM2": total("grossFloorAreaM2"),
            "ceilingAreaM2": total("ceilingAreaM2"),
            "grossWallAreaM2": total("grossWallAreaM2"),
            "netWallAreaM2": total("netWallAreaM2"),
            "openingsAreaM2": total("openingsAreaM2"),
            "revealsAreaM2": total("revealsAreaM2"),
            "tilingAreaM2": total("tilingAreaM2"),
            "paintAreaM2": total("paintAreaM2"),
            "skirtingM": total("skirtingM"),
            "volumeM3": total("volumeM3"),
            "doors": sum(1 for o in model.openings if o.type == "door"),
            "windows": sum(1 for o in model.openings if o.type == "window"),
            "estimatedWalls": sorted(w.id for w in model.walls if w.lengthSource == "SKETCH"),
            "calculatedWalls": sorted(w.id for w in model.walls if w.lengthSource == "CALCULATED"),
            "suspectWalls": sorted(w.id for w in model.walls if w.suspect),
            "questions": list(dict.fromkeys(questions)),
            "aiSummary": (model.metadata.get("ai") or {}).get("summary"),
        }

    @staticmethod
    def process_response(plan_id, model, version, status, agent_log) -> dict:
        total = round(sum(r.floorAreaM2 for r in model.rooms), 6)
        return {
            "success": status != PlanStatus.ERROR,
            "planId": plan_id,
            "status": status.value,
            "version": version,
            "needsReview": model.needsReview,
            "quality": model.quality,
            "summary": {"rooms": len(model.rooms), "floorAreaM2": total},
            "totals": model.metadata.get("totals"),
            "aiAvailable": agent_log.get("aiAvailable", False),
            "geometry": {
                "walls": [w.model_dump(mode="json") for w in model.walls],
                "openings": [o.model_dump(mode="json") for o in model.openings],
                "rooms": [r.model_dump(mode="json") for r in model.rooms],
            },
            "files": {
                "preview": f"/api/v1/plans/{plan_id}/preview",
                "png": f"/api/v1/plans/{plan_id}/png",
                "svg": f"/api/v1/plans/{plan_id}/svg",
                "pdf": f"/api/v1/plans/{plan_id}/pdf",
                "dxf": f"/api/v1/plans/{plan_id}/dxf",
                "json": f"/api/v1/plans/{plan_id}/processed",
                "plan3d": f"/api/v1/plans/{plan_id}/3d",
                "glb": None,
            },
        }
