from __future__ import annotations

import time
import traceback

from backend.agent.agent import GeometryAgent
from backend.agent.ollama import OllamaClient
from backend.cad import build_cad_model, export_dxf, export_pdf, export_png, export_svg
from backend.config import Settings
from backend.db import Database
from backend.geometry.normalizer import normalize_payload
from backend.geometry.score import geometry_score
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.geometry.validator import validate_geometry
from backend.models import PlanPayload, PlanStatus, QualityStatus
from backend.storage import PlanStorage
from backend.telegram.notifier import TelegramNotifier
from backend.view3d import export_glb, to_plan3d


class Pipeline:
    def __init__(self, settings: Settings, storage: PlanStorage, db: Database):
        self.settings = settings
        self.storage = storage
        self.db = db

    def save_raw(self, payload: PlanPayload) -> dict:
        data = payload.model_dump(mode="json")
        path = self.storage.save_raw(payload.planId, data)
        self.db.upsert_raw(payload.planId, payload.name, self.storage.plan_dir(payload.planId))
        self.storage.append_log(payload.planId, {
            "event": "raw_saved",
            "inputHash": self.storage.sha256_json(data),
            "path": str(path),
        })
        return {"planId": payload.planId, "status": PlanStatus.RAW.value}

    def process(self, plan_id: str) -> dict:
        started = time.perf_counter()
        self.db.set_status(plan_id, PlanStatus.PROCESSING)
        raw = self.storage.raw_payload(plan_id)
        input_hash = self.storage.sha256_json(raw)
        self.storage.append_log(plan_id, {"event":"processing_started", "inputHash":input_hash})
        try:
            payload = PlanPayload.model_validate(raw)
            normalized = normalize_payload(
                payload,
                default_thickness_mm=self.settings.default_wall_thickness_mm,
                default_height_mm=self.settings.default_wall_height_mm,
                snap_tolerance_mm=self.settings.snap_tolerance_mm,
            )
            topology = build_topology(normalized)
            solved = solve_geometry(
                normalized,
                topology,
                orthogonal_tolerance_deg=self.settings.orthogonal_tolerance_deg,
                length_tolerance_mm=self.settings.length_tolerance_mm,
            )

            agent_log = {"enabled": self.settings.ai_enabled, "proposals": [], "accepted": [], "rejected": [], "offline": False}
            if self.settings.ai_enabled and solved.needs_review:
                agent = GeometryAgent(
                    OllamaClient(self.settings.ollama_url, self.settings.ollama_model, self.settings.ollama_timeout),
                    max_iterations=5,
                    length_tolerance_mm=self.settings.length_tolerance_mm,
                    orthogonal_tolerance_deg=self.settings.orthogonal_tolerance_deg,
                )
                agent_run = agent.improve(normalized, topology, solved)
                solved = agent_run.solved
                agent_log = {
                    "enabled": True,
                    "iterations": agent_run.iterations,
                    "proposals": agent_run.proposals,
                    "accepted": agent_run.accepted,
                    "rejected": agent_run.rejected,
                    "offline": agent_run.offline,
                }

            model = build_cad_model(normalized, solved)
            validation = validate_geometry(normalized, solved, model.rooms, length_tolerance_mm=self.settings.length_tolerance_mm)
            model.needsReview = bool(model.needsReview or validation["needsReview"])
            score = geometry_score(validation, len(model.rooms))
            max_gap = float(model.metadata.get("mergedEndpointMaxGapMm", 0.0))
            if model.needsReview:
                quality_status = QualityStatus.NEEDS_REVIEW
            elif max_gap > 10.0:
                quality_status = QualityStatus.ESTIMATED
            else:
                quality_status = QualityStatus.OK
            quality = {
                "status": quality_status.value,
                "closureErrorCm": validation["closureErrorCm"],
                "maxLengthErrorMm": validation["maxLengthErrorMm"],
                "geometryScore": score,
                "warnings": validation["warnings"],
                "errors": validation["errors"],
            }
            model.quality = quality

            version = self.storage.next_version(plan_id)
            out = self.storage.version_dir(plan_id, version)
            processed = model.model_dump(mode="json")
            self.storage.write_json_atomic(out / "processed-plan.json", processed)
            export_svg(model, out / "plan.svg")
            export_dxf(model, out / "plan.dxf")
            export_png(model, out / "preview.png")
            export_pdf(model, out / "plan.pdf")
            plan3d = to_plan3d(model)
            self.storage.write_json_atomic(out / "plan3d.json", plan3d)
            glb_ok, glb_error = export_glb(model, out / "plan.glb")
            if not glb_ok:
                try:
                    (out / "plan.glb").unlink()
                except FileNotFoundError:
                    pass

            manifest = {
                "planId": plan_id,
                "version": version,
                "inputHash": input_hash,
                "quality": quality,
                "files": sorted(p.name for p in out.iterdir() if p.is_file()),
                "glb": {"generated": glb_ok, "error": glb_error},
                "agent": agent_log,
            }
            self.storage.write_json_atomic(out / "manifest.json", manifest)
            self.storage.publish_current(plan_id, out)

            status = PlanStatus.NEEDS_REVIEW if model.needsReview else PlanStatus.PROCESSED
            self.db.set_status(plan_id, status, version=version, quality=quality, needs_review=model.needsReview, error="")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            self.storage.append_log(plan_id, {
                "event": "processing_completed",
                "inputHash": input_hash,
                "solverOperations": solved.operations,
                "aiProposals": agent_log["proposals"],
                "acceptedOperations": agent_log["accepted"],
                "rejectedOperations": agent_log["rejected"],
                "geometryScoreAfter": score,
                "processingTimeMs": elapsed_ms,
                "warnings": quality["warnings"],
                "errors": quality["errors"],
                "version": version,
            })

            notifier = TelegramNotifier(
                self.settings.telegram_enabled,
                self.settings.telegram_bot_token,
                self.settings.telegram_chat_id,
                self.settings.public_base_url,
            )
            total_area = sum(r.floorAreaM2 for r in model.rooms)
            telegram_result = notifier.send_processed(
                plan_id=plan_id,
                name=model.name,
                room_count=len(model.rooms),
                area_m2=total_area,
                status=quality_status.value,
                files_dir=self.storage.plan_dir(plan_id) / "current",
            )
            self.storage.append_log(plan_id, {"event":"telegram", **telegram_result})
            return self.process_response(plan_id, model, version, status)
        except Exception as exc:
            self.db.set_status(plan_id, PlanStatus.ERROR, error=str(exc))
            self.storage.append_log(plan_id, {
                "event":"processing_error",
                "inputHash":input_hash,
                "error":str(exc),
                "traceback":traceback.format_exc(limit=12),
                "processingTimeMs":round((time.perf_counter()-started)*1000,2),
            })
            raise

    def process_response(self, plan_id, model, version: int, status: PlanStatus) -> dict:
        files = {
            "preview": f"/api/v1/plans/{plan_id}/preview",
            "pdf": f"/api/v1/plans/{plan_id}/pdf",
            "dxf": f"/api/v1/plans/{plan_id}/dxf",
            "svg": f"/api/v1/plans/{plan_id}/svg",
            "3d": f"/api/v1/plans/{plan_id}/3d",
        }
        if self.storage.plan_dir(plan_id).joinpath("current/plan.glb").exists():
            files["glb"] = f"/api/v1/plans/{plan_id}/glb"
        return {
            "success": status != PlanStatus.ERROR,
            "planId": plan_id,
            "status": status.value,
            "version": version,
            "quality": model.quality,
            "geometry": {
                "walls": [w.model_dump(mode="json") for w in model.walls],
                "openings": [o.model_dump(mode="json") for o in model.openings],
                "rooms": [r.model_dump(mode="json") for r in model.rooms],
            },
            "files": files,
        }
