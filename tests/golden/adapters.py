from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import base64, io, math

# === Prova a importare i metodi reali da astrobot_core ===
try:
    from astrobot_core.calcoli import (
        df_tutti,
        calcola_pianeti_da_df,
        calcola_asc_mc_case,
        genera_carta_base64,
    )
except Exception:
    df_tutti = None
    calcola_pianeti_da_df = None
    calcola_asc_mc_case = None
    genera_carta_base64 = None

try:
    from astrobot_core.sinastria import sinastria as calcola_sinastria  # opzionale
except Exception:
    calcola_sinastria = None

try:
    from astrobot_core.transiti import calcola_transiti_data_fissa, transiti_su_due_date  # opzionale
except Exception:
    calcola_transiti_data_fissa = None
    transiti_su_due_date = None

from PIL import Image
import numpy as np

# === Strutture dati ===

@dataclass
class Place:
    lat: float
    lon: float
    name: str = ""

@dataclass
class Natal:
    when: datetime
    place: Dict[str, Any]  # {lat, lon, name}

# === Util ===

def save_base64_png(b64: str, png_path: Path) -> None:
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(png_path)

def _angles_at(when: datetime) -> Dict[str, float]:
    if calcola_pianeti_da_df is None or df_tutti is None:
        raise RuntimeError("astrobot_core.calcoli non disponibile: adatta gli import in adapters.py")
    # Prova con la firma nuova (con 'colonne_extra'), altrimenti fallback alla firma vecchia
    try:
        return calcola_pianeti_da_df(
            df_tutti, when.day, when.month, when.year, colonne_extra=("Nodo", "Lilith")
        )
    except TypeError:
        # Versione del core senza 'colonne_extra'
        return calcola_pianeti_da_df(df_tutti, when.day, when.month, when.year)

# === Mock intensities (fallback deterministico, sostituisci con i tuoi transiti) ===

CATEGORIES: List[str] = ["energy", "emotions", "relationships", "work", "luck"]

def _mock_intensities_from_angles(angles: Dict[str, float]) -> Dict[str, float]:
    vals = list(angles.values())
    if not vals:
        return {k: 0.0 for k in CATEGORIES}
    v = np.array(vals, dtype=np.float64)
    f1 = (np.mean(v % 30.0) / 30.0)
    f2 = np.clip(np.std(v) / 180.0, 0, 1)
    f3 = (np.mean(np.cos(np.radians(v))) + 1) / 2
    f4 = (np.mean(np.sin(np.radians(v))) + 1) / 2
    f5 = np.clip((np.max(v) - np.min(v)) / 360.0, 0, 1)
    raw = np.array([f1, f2, f3, f4, f5])
    return {k: float(x) for k, x in zip(CATEGORIES, raw)}

# === TEMA ===

def compute_tema(when: datetime, place: Place, png_path: Path) -> Dict[str, Any]:
    angles = _angles_at(when)

    # Se disponibile, genera carta polare dal core; altrimenti fallback
    if genera_carta_base64 is not None and calcola_asc_mc_case is not None:
        try:
            asc_mc = calcola_asc_mc_case(
                citta=place.name or "",
                anno=when.year, mese=when.month, giorno=when.day,
                ora=when.hour, minuti=when.minute,
                lat=place.lat, lon=place.lon, fuso_orario=0.0,
            )
            b64 = genera_carta_base64(angles, asc_mc)
            save_base64_png(b64, png_path)
        except Exception:
            _fallback_polar_plot(angles, png_path, title=f"Tema {when.isoformat()}")
    else:
        _fallback_polar_plot(angles, png_path, title=f"Tema {when.isoformat()}")

    return {"angles": angles}

# === SINASTRIA ===

def compute_sinastria(A: Dict[str, Any], B: Dict[str, Any], png_path: Path) -> Dict[str, Any]:
    whenA = A["when"]; whenB = B["when"]
    angles_A = _angles_at(whenA)
    angles_B = _angles_at(whenB)

    # Plot overlay polare
    _overlay_polar_plot(angles_A, angles_B, png_path, title="Sinastria A vs B")

    out = {"angles_A": angles_A, "angles_B": angles_B}

    # (Opzionale) se hai una funzione reale per gli aspetti, puoi inserirla qui.
    # try:
    #     if calcola_sinastria is not None:
    #         out["aspetti"] = calcola_sinastria(...)
    # except Exception:
    #     pass

    return out

# === OROSCOPO ===

def compute_oroscopo_daily(when: datetime, place: Place, natal: Natal, png_path: Path) -> Dict[str, Any]:
    angles_transit = _angles_at(when)
    angles_natal = _angles_at(natal.when)

    intensities = None

    # Se disponi di una funzione reale di transiti rispetto al natal, agganciala qui
    try:
        if transiti_su_due_date is not None:
            # TODO: adatta a firma reale se diversa
            # intensities = extract_intensities(transiti_su_due_date(...))
            pass
        elif calcola_transiti_data_fissa is not None:
            # TODO: adatta a firma reale se diversa (transiti su una data rispetto a natal)
            # intensities = extract_intensities(calcola_transiti_data_fissa(...))
            pass
    except Exception:
        intensities = None

    if intensities is None:
        # Fallback deterministico
        intensities = _mock_intensities_from_angles(angles_transit)

    _bar_chart(intensities, png_path, title=f"{when.isoformat()} — natal @ {natal.when.date()}")

    return {
        "angles_transit": angles_transit,
        "angles_natal": angles_natal,
        "intensities": intensities,
    }

def compute_oroscopo_period(samples: List[datetime], place: Place, natal: Natal, png_path: Path) -> Dict[str, Any]:
    # Aggrega il daily
    tmp = png_path.with_name("__tmp.png")
    chunks: List[Dict[str, float]] = []
    for dt in samples:
        r = compute_oroscopo_daily(dt, place, natal, tmp)
        chunks.append(r["intensities"])
    agg = {k: float(np.mean([d[k] for d in chunks])) for k in CATEGORIES}
    _bar_chart(agg, png_path, title=f"Aggregazione su {len(samples)} campioni — natal @ {natal.when.date()}")
    return {"intensities": agg, "n_samples": len(samples)}

# === Plotting helpers (fallback) ===

def _fallback_polar_plot(angles: Dict[str, float], png_path: Path, title: str = "") -> None:
    import matplotlib.pyplot as plt
    thetas = [math.radians(v) for v in angles.values()]
    rs = [1.0] * len(thetas)
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="polar")
    ax.scatter(thetas, rs)
    ax.set_title(title)
    ax.set_yticklabels([])
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

def _overlay_polar_plot(a1: Dict[str, float], a2: Dict[str, float], png_path: Path, title: str = "") -> None:
    import matplotlib.pyplot as plt
    t1 = [math.radians(v) for v in a1.values()]
    t2 = [math.radians(v) for v in a2.values()]
    r1 = [1.0] * len(t1); r2 = [0.8] * len(t2)
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="polar")
    ax.scatter(t1, r1, label="A", marker="o")
    ax.scatter(t2, r2, label="B", marker="x")
    ax.legend(loc="upper right")
    ax.set_title(title)
    ax.set_yticklabels([])
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

def _bar_chart(intensities: Dict[str, float], png_path: Path, title: str = "") -> None:
    import matplotlib.pyplot as plt
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.bar(list(intensities.keys()), list(intensities.values()))
    ax.set_ylim(0, 1)
    ax.set_title(title)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)
