# === Mock intensities (fallback deterministico, sostituisci con i tuoi transiti) ===

CATEGORIES: List[str] = ["energy", "emotions", "relationships", "work", "luck"]

def _mock_intensities_from_angles(angles: Dict[str, float]) -> Dict[str, float]:
    vals = list(angles.values())
    if not vals:
        return {k: 0.0 for k in CATEGORIES}

    v = np.array(vals, dtype=np.float64)

    # 5 feature in [0,1] derivate in modo deterministico dagli angoli
    f1 = np.mean(v % 30.0) / 30.0
    f2 = float(np.clip(np.std(v) / 180.0, 0.0, 1.0))
    f3 = (np.mean(np.cos(np.radians(v))) + 1.0) / 2.0
    f4 = (np.mean(np.sin(np.radians(v))) + 1.0) / 2.0
    f5 = float(np.clip((np.max(v) - np.min(v)) / 360.0, 0.0, 1.0))

    raw = np.array([f1, f2, f3, f4, f5], dtype=np.float64)
    return {k: float(x) for k, x in zip(CATEGORIES, raw)}
