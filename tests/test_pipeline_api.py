from __future__ import annotations

import importlib
import json
import sys
import time

import ezdxf
import trimesh
from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.db import Database
from backend.pipeline import Pipeline
from backend.storage import PlanStorage
from conftest import make_payload


def _settings(tmp_path, api_key="test-key"):
    return Settings(
        api_key=api_key,
        data_dir=tmp_path/"data",
        db_path=tmp_path/"data"/"db.sqlite3",
        host="127.0.0.1",port=8796,
        default_wall_thickness_mm=120,default_wall_height_mm=2700,
        snap_tolerance_mm=250,orthogonal_tolerance_deg=25,length_tolerance_mm=0.5,
        ai_enabled=False,ollama_url="http://127.0.0.1:11434",ollama_model="qwen2.5:7b",ollama_timeout=1,
        telegram_enabled=False,telegram_bot_token="",telegram_chat_id="",public_base_url="",
    )


def _rect(plan_id="artifact-plan"):
    walls=[
        {"id":"w1","a":{"x":0,"y":0},"b":{"x":200,"y":8},"lengthCm":200},
        {"id":"w2","a":{"x":200,"y":8},"b":{"x":207,"y":305},"lengthCm":300},
        {"id":"w3","a":{"x":207,"y":305},"b":{"x":0,"y":298},"lengthCm":200},
        {"id":"w4","a":{"x":0,"y":298},"b":{"x":0,"y":0},"lengthCm":300},
    ]
    return make_payload(walls,plan_id=plan_id,openings=[
        {"id":"d1","type":"door","wallId":"w2","widthCm":80,"offsetCm":120,"referenceEnd":"a"}
    ])


def test_pipeline_generates_real_artifacts_and_versions(tmp_path):
    settings=_settings(tmp_path)
    storage=PlanStorage(settings.data_dir); db=Database(settings.db_path); pipe=Pipeline(settings,storage,db)
    payload=_rect()
    raw=payload.model_dump(mode="json")
    pipe.save_raw(payload)
    result=pipe.process(payload.planId)
    assert result["status"]=="PROCESSED"
    assert result["version"]==1
    current=storage.plan_dir(payload.planId)/"current"
    required=["processed-plan.json","plan.svg","plan.dxf","preview.png","plan.pdf","plan3d.json","plan.glb"]
    assert all((current/x).exists() and (current/x).stat().st_size>20 for x in required)
    processed=json.loads((current/"processed-plan.json").read_text())
    assert processed["walls"][0]["sourceLengthCm"]==200
    assert abs(processed["rooms"][0]["floorAreaM2"]-6)<0.02
    assert "<svg" in (current/"plan.svg").read_text()[:200]
    ezdxf.readfile(current/"plan.dxf")
    with Image.open(current/"preview.png") as image:
        assert image.size==(1600,1100)
    assert (current/"plan.pdf").read_bytes().startswith(b"%PDF")
    plan3d=json.loads((current/"plan3d.json").read_text())
    assert plan3d["units"]=="mm" and abs(plan3d["rooms"][0]["floorAreaM2"]-6)<0.02
    glb=trimesh.load(current/"plan.glb")
    assert len(glb.geometry)>=5
    assert json.loads((storage.plan_dir(payload.planId)/"raw"/"original.json").read_text())==raw

    second=pipe.process(payload.planId)
    assert second["version"]==2
    assert (storage.plan_dir(payload.planId)/"versions"/"001").exists()
    assert (storage.plan_dir(payload.planId)/"versions"/"002").exists()


def test_fastapi_contract_and_security(tmp_path, monkeypatch):
    monkeypatch.setenv("GE360_API_KEY","secret-test")
    monkeypatch.setenv("GE360_DATA_DIR",str(tmp_path/"api-data"))
    monkeypatch.setenv("GE360_DB_PATH",str(tmp_path/"api-data"/"api.sqlite3"))
    monkeypatch.setenv("GE360_AI_ENABLED","false")
    monkeypatch.setenv("GE360_TELEGRAM_ENABLED","false")
    sys.modules.pop("backend.main",None)
    main=importlib.import_module("backend.main")
    client=TestClient(main.app)
    headers={"X-GE360-API-Key":"secret-test"}

    assert client.get("/api/v1/health").status_code==401
    assert client.get("/api/v1/health",headers=headers).status_code==200
    payload=_rect("api-plan").model_dump(mode="json")
    create=client.post("/api/v1/plans",headers=headers,json=payload)
    assert create.status_code==200 and create.json()["status"]=="RAW"
    process=client.post("/api/v1/plans/api-plan/process",headers=headers)
    assert process.status_code==200 and process.json()["status"]=="PROCESSING"
    job_id=process.json()["jobId"]
    state=None
    for _ in range(100):
        state=client.get(f"/api/v1/jobs/{job_id}",headers=headers).json()
        if state["status"]!="PROCESSING": break
        time.sleep(0.02)
    assert state["status"]=="DONE",state
    status=client.get("/api/v1/plans/api-plan",headers=headers).json()
    assert status["status"]=="PROCESSED" and status["currentVersion"]==1
    for endpoint in ("processed","preview","svg","dxf","pdf","3d"):
        response=client.get(f"/api/v1/plans/api-plan/{endpoint}",headers=headers)
        assert response.status_code==200,endpoint
    versions=client.get("/api/v1/plans/api-plan/versions",headers=headers).json()
    assert versions["versions"][0]["version"]==1

    compat=client.post("/api/v1/plans/refine",headers=headers,json={**payload,"planId":"api-refine"})
    assert compat.status_code==200 and compat.json()["status"]=="PROCESSING"
