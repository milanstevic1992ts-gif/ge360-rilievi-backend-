from __future__ import annotations
import json
from pathlib import Path
import ezdxf
from PIL import Image
from backend.models import PlanPayload
from backend.geometry.normalizer import normalize_payload
from backend.geometry.topology import build_topology
from backend.geometry.solver import solve_geometry
from backend.cad import build_cad_model, export_dxf, validate_dxf, export_svg, export_png, export_pdf
from backend.view3d import to_plan3d


def wall(id,a,b,length): return {"id":id,"a":{"x":a[0],"y":a[1]},"b":{"x":b[0],"y":b[1]},"lengthCm":length}

def model():
    p=PlanPayload.model_validate({"planId":"exports","name":"Stanza 2x3","wallHeightM":2.7,"walls":[
      wall("w1",(0,0),(205,8),200),wall("w2",(205,8),(214,310),300),wall("w3",(214,310),(4,301),200),wall("w4",(4,301),(0,0),300),
    ],"works":[{"id":"wk1","catalogId":"paint.walls_ceiling","targetType":"plan"}],"openings":[{"id":"d1","type":"door","wallId":"w2","widthCm":80,"offsetCm":60,"referenceEnd":"a"},{"id":"f1","type":"window","wallId":"w4","widthCm":100,"offsetCm":80,"referenceEnd":"a","heightCm":120,"sillHeightCm":90}]})
    n=normalize_payload(p); t=build_topology(n); s=solve_geometry(n,t); m=build_cad_model(n,s)
    from backend.works import resolve_works
    m.metadata["works"]=resolve_works(m,p.works)
    return m


def test_dxf_real_validation(tmp_path:Path):
    m=model(); path=tmp_path/'plan.dxf'; result=export_dxf(m,path)
    assert path.exists() and path.stat().st_size>1000
    assert result['units']==4
    assert result['entities']>0
    assert result['layers']==['GE360_WALLS','GE360_DOORS','GE360_WINDOWS','GE360_ROOMS','GE360_DIMENSIONS','GE360_TEXT']
    # independent second reopen/audit
    doc=ezdxf.readfile(path); audit=doc.audit(); assert not audit.has_errors
    layers={e.dxf.layer for e in doc.modelspace()}
    assert {'GE360_WALLS','GE360_DOORS','GE360_WINDOWS','GE360_ROOMS','GE360_DIMENSIONS','GE360_TEXT'} <= layers
    # XDATA makes authoritative geometry machine-readable
    wall_entities=[e for e in doc.modelspace() if e.dxf.layer=='GE360_WALLS' and e.dxftype()=='LWPOLYLINE']
    assert wall_entities and wall_entities[0].has_xdata('GE360')


def test_svg_png_pdf_and_plan3d(tmp_path:Path):
    m=model(); svg=tmp_path/'plan.svg'; png=tmp_path/'preview.png'; pdf=tmp_path/'plan.pdf'; p3=tmp_path/'plan3d.json'
    export_svg(m,svg); export_png(m,png); export_pdf(m,pdf); p3.write_text(json.dumps(to_plan3d(m)),encoding='utf-8')
    assert svg.read_text(encoding='utf-8').startswith('<svg')
    assert svg.stat().st_size>500
    with Image.open(png) as im: assert im.size==(1600,1100) and im.format=='PNG'
    pdf_bytes=pdf.read_bytes()
    assert pdf_bytes.startswith(b'%PDF') and pdf.stat().st_size>1000
    assert b'EDIL MILAN STEVIC' in pdf_bytes
    assert b'RIEPILOGO STANZE' in pdf_bytes
    assert b"NOTE E CONDIZIONI D'USO DEL PRESENTE ELABORATO" in pdf_bytes
    assert b'Natura del documento.' in pdf_bytes
    assert b'Limitazione di responsabilit' in pdf_bytes
    assert b'Riservatezza e divieto di diffusione.' in pdf_bytes
    assert b'Validit' in pdf_bytes
    assert b'LAVORAZIONI RILEVATE' in pdf_bytes
    assert b'Pitturazione pareti + soffitto' in pdf_bytes
    data=json.loads(p3.read_text())
    assert data['units']=='mm'
    assert sorted(round(w['length']) for w in data['walls'])==[2000,2000,3000,3000]
    assert all(round(w['height'])==2700 for w in data['walls'])
    assert all(round(w['thickness'])==120 for w in data['walls'])
    d=data['doors'][0]; assert d['width']==800 and d['offset']==600
