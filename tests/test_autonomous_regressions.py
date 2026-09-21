from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import solve_payload
from test_agente_autonomo import TRE_STANZE, W, payload, _pipeline
from backend.geometry.error_model import ErrorModel


def test_corrected_wall_fields_survive_json_export():
    _, _, solved, model, _ = solve_payload(payload(TRE_STANZE + [W('s1', (300, 0), (300, 305), 350)]))
    wall = next(w for w in model.model_dump(mode='json')['walls'] if w['id'] == 's1')
    assert wall['declaredLengthMm'] == 3500
    assert wall['usedLengthMm'] == pytest.approx(3050)
    assert wall['resolvedBy'] in {d['id'] for d in solved.decisions}


def test_compromise_cannot_hide_unresolved_measurements(monkeypatch):
    from backend.geometry import hypotheses
    original = hypotheses.resolve_inconsistencies

    def compromise(*args, **kwargs):
        result = original(*args, **kwargs)
        result['decisions'] = [{'id': 'd1', 'kind': 'compromise', 'wallIds': ['s1'],
                                'probability': 1.0, 'text': 'Residual remains'}]
        return result

    monkeypatch.setattr(hypotheses, 'resolve_inconsistencies', compromise)
    _, _, solved, _, validation = solve_payload(payload(TRE_STANZE + [W('s1', (300, 0), (300, 305), 350)]))
    assert solved.needs_review and validation['needsReview']
    assert solved.wall_meta['s1']['resolvedBy'] is None


def test_learning_reloads_and_deduplicates_between_workers(tmp_path):
    plan, _, solved, _, _ = solve_payload(payload(TRE_STANZE))
    path = tmp_path / 'errors.json'
    models = [ErrorModel(path) for _ in range(4)]
    def record(i):
        return models[i].observe_and_save(plan, solved, [], 10, str(i % 2))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(record, range(4)))
    assert ErrorModel(path).data['plans'] == 2


def test_learning_disk_failure_does_not_block_exports(tmp_path, monkeypatch):
    pipe, _ = _pipeline(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('learning file read-only')
    monkeypatch.setattr(ErrorModel, 'observe_and_save', fail)
    p = payload(TRE_STANZE)
    pipe.save_raw(p)
    result = pipe.process(p.planId)
    assert result['status'] == 'PROCESSED'
    assert (pipe.storage.plan_dir(p.planId) / 'current/plan.dxf').exists()
