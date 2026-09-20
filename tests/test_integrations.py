from backend.integrations.archit_adapter import available
from backend.integrations.archlang_adapter import integration_status
from backend.integrations.openplan3d_adapter import to_openplan3d
from tests.test_geometry import process,wall

def test_archit_is_optional():
    assert isinstance(available(),bool)

def test_archlang_not_runtime_v1():
    assert integration_status()['runtime']=='NOT_USED_V1'

def test_openplan_adapter_preserves_metric_values_after_unit_conversion():
    walls=[wall('w1',(0,0),(200,0),200),wall('w2',(200,0),(200,300),300),wall('w3',(200,300),(0,300),200),wall('w4',(0,300),(0,0),300)]
    _,_,_,m=process({'planId':'op3d','wallHeightM':2.7,'walls':walls})
    op=to_openplan3d(m)
    assert op['units']=='cm'
    assert sorted(round(((x['end']['x']-x['start']['x'])**2+(x['end']['y']-x['start']['y'])**2)**.5) for x in op['walls'])==[200,200,300,300]
    assert all(x['height']==270 for x in op['walls'])
    assert all(x['thickness']==12 for x in op['walls'])

def test_viewer_contains_required_controls_and_opening_renderer():
    from pathlib import Path
    html=(Path(__file__).parents[1]/'viewer3d/index.html').read_text(encoding='utf-8')
    assert 'OrbitControls' in html
    assert 'id="top"' in html and 'id="perspective"' in html and 'id="reset"' in html
    assert 'openingRanges' in html and 'centerFromStart' in html
