from __future__ import annotations
import math,re
from .schemas import CADOperation
_MEASURE=re.compile(r"(?P<v>\d+(?:[\.,]\d+)?)\s*(?P<u>mm|cm|m|metro|metri|millimetri|centimetri)\b",re.I)
_ANGLE=re.compile(r"(?P<v>\d+(?:[\.,]\d+)?)\s*(?:°|grado|gradi)\b",re.I)
_BARE=re.compile(r"(?<![A-Za-z0-9_])(\d+(?:[\.,]\d+)?)(?![A-Za-z0-9_])")
_NUM={"length_mm","thickness_mm","height_mm","delta_mm","distance_from_start_mm","width_mm","offset_mm","offset_delta_mm","sill_height_mm"}
_UNSAFE=("rm -rf","esegui shell","execute shell","esegui questo python","execute python","modifica direttamente il database","scrivi nel database","disabilita la validazione","bypass validator","bypass solver","ignora le regole","eval(","exec(")
def is_unsafe_execution_request(s): q=s.casefold(); return any(x in q for x in _UNSAFE)
def measurements(s):
    out=[]
    for m in _MEASURE.finditer(s):
        v=float(m.group("v").replace(",",".")); u=m.group("u").lower(); out.append(v*(1 if u.startswith("mm") or u.startswith("mill") else 10 if u.startswith("cm") or u.startswith("cent") else 1000))
    return out
def _match(v,vals,tol=1.1): return any(math.isclose(abs(v),abs(x),abs_tol=tol,rel_tol=.002) for x in vals)
def validate_measurement_provenance(op:CADOperation,instruction:str,trusted=()):
    obs=measurements(instruction)+[float(x) for x in trusted if x is not None]
    for k,raw in op.arguments.items():
        if raw is None: continue
        if k=="angle_deg":
            angles=[float(x.group("v").replace(",",".")) for x in _ANGLE.finditer(instruction)]
            if not _match(float(raw),angles,.11): raise ValueError("angle not traceable to user")
        elif k in _NUM and not _match(float(raw),obs):
            if k=="width_mm" and op.tool.value in {"create_door","create_window"}:
                bare=[float(x.group(1).replace(",",".")) for x in _BARE.finditer(instruction)]
                if any(20<=n<=400 and _match(float(raw),[n*10]) for n in bare): continue
            raise ValueError(f"{k} not traceable to user/trusted measurement")
