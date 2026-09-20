from __future__ import annotations


def geometry_score(validation: dict, room_count: int) -> float:
    score = 100.0
    score -= min(50.0, float(validation.get("maxLengthErrorMm", 0)) * 5.0)
    score -= min(25.0, abs(float(validation.get("closureErrorCm", 0))) * 2.0)
    score -= min(15.0, len(validation.get("warnings", [])) * 2.0)
    score -= min(40.0, len(validation.get("errors", [])) * 20.0)
    if room_count == 0:
        score -= 20.0
    return round(max(0.0, min(100.0, score)), 3)
