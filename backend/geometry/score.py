def geometry_score(validation: dict, room_count: int) -> float:
    """Punteggio 0-100. Gli scarti sono pesati rispetto alla tolleranza di rilievo,
    non in valore assoluto: 5 mm su 4 m non sono un difetto."""
    score = 100.0
    worst_ratio = 0.0
    for w in validation.get("walls", []):
        if w.get("measured", True) and w.get("toleranceMm"):
            worst_ratio = max(worst_ratio, float(w["errorMm"]) / float(w["toleranceMm"]))
    if validation.get("walls"):
        score -= min(50.0, max(0.0, worst_ratio - 0.5) * 20.0)
    else:
        score -= min(50.0, float(validation.get("maxLengthErrorMm", 0)) * 0.5)
    score -= min(25.0, abs(float(validation.get("closureErrorCm", 0))) * 0.5)
    score -= min(15.0, len(validation.get("warnings", [])) * 1.0)
    score -= min(40.0, len(validation.get("errors", [])) * 20.0)
    if room_count == 0:
        score -= 20.0
    return round(max(0.0, min(100.0, score)), 3)
