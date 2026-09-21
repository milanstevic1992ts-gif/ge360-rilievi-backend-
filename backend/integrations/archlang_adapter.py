from __future__ import annotations
from backend.models import PlanModel

# V1 deliberately does not make ArchLang a runtime dependency. This adapter
# emits a small declarative representation suitable for a future Node worker.
def to_archlang(plan:PlanModel)->str:
    lines=[f'plan "{plan.name.replace(chr(34), chr(39))}" {{']
    for w in plan.walls:
        lines.append(f'  # wall {w.id} solved_length_mm={int(round(w.calculatedLengthMm))} declared_length_mm={int(round(w.declaredLengthMm))} source={w.lengthSource}')
    for r in plan.rooms:
        lines.append(f'  # room {r.roomId} "{r.name}" area_m2={r.floorAreaM2:.3f}')
    lines.append('}')
    return "\n".join(lines)

def integration_status()->dict:
    return {"runtime":"NOT_USED_V1","reason":"JSON tool-calling is simpler and keeps Python backend independent; adapter retained for future Node worker."}
