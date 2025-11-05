from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import base64, io, math, inspect

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

# Rileva dinamicamente se 'calcola_pianeti_da_df' accetta 'colonne_extra'
_HAS_COLONNE_EXTRA = False
try:
    if calcola_pianeti_da_df is not None:
        _HAS_COLONNE_EXTRA = "colonne_extra" in inspect.signature(calcola_pianeti_da_df).parameters
except Exception:
    _HAS_COLONNE_EXTRA = False

def _angles_at(when: datetime) -> Dict[str, float]:
    if calcola_pianeti_da_df is None or df_tutti is None:
        raise RuntimeError("astrobot_core.calcoli non disponibile: adatta gli import in adapters.py")
    if _HAS_COLONNE_EXTRA:
        # firma nuova
        return calcola_pianeti_da_df(
            df_tutti, when.day, when.month, when.year, colonne_extra=("Nodo","Lilith")
        )
    else:
        # firma vecchia
        return calcola_pianeti_da_df(df_tutti, when.day, when.month, when.year)

# === Mock intensities (fallback deterministico, sostituisci con i tuoi transiti) ===

CATEGORIES: List[str] = ["energy", "emotions", "relationships", "work", "luck"]

def _mock_intensities_from_angles(angles: Dict[str, float]) -> Dict[str, float]:
    vals = list(angles.values())
    if not vals:
        return {k: 0.0 for k in CATEGORIES}
    v = np.array(vals, dtype=np.float64)
    f1 = (np.mean(v % 30.0)
