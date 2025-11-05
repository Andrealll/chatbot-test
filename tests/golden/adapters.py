from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional


# === IMPORTA QUI I TUOI METODI REALI ===
# Esempio (adatta ai tuoi pacchetti/nome funzioni):
try:
from astrobot_core.calcoli import (
df_tutti,
calcola_pianeti_da_df,
calcola_asc_mc_case,
genera_carta_base64,
)
from astrobot_core.sinastria import sinastria as calcola_sinastria
try:
from astrobot_core.transiti import calcola_transiti_data_fissa, transiti_su_due_date # type: ignore
except Exception:
calcola_transiti_data_fissa, transiti_su_due_date = None, None
except Exception:
df_tutti = None
calcola_pianeti_da_df = None
calcola_asc_mc_case = None
genera_carta_base64 = None
calcola_sinastria = None
calcola_transiti_data_fissa = None
transiti_su_due_date = None


import base64
from pathlib import Path
import io
from PIL import Image
import numpy as np
import math


@dataclass
class Place:
lat: float
lon: float
name: str = ""


# ---------- UTIL ----------


def save_base64_png(b64: str, png_path: Path) -> None:
raw = base64.b64decode(b64)
img = Image.open(io.BytesIO(raw)).convert("RGBA")
png_path.parent.mkdir(parents=True, exist_ok=True)
img.save(png_path)


# ---------- ADAPTER: TEMA ----------


def compute_tema(when: datetime, place: Place, png_path: Path) -> Dict[str, Any]:
"""Ritorna angles + (eventuali) intensities e salva PNG del grafico polare."""
if calcola_pianeti_da_df is None:
raise RuntimeError("astrobot_core non disponibile: adatta gli import in adapters.py")


# Pianeti (longitudini eclittiche)
angles = calcola_pianeti_da_df(
df_tutti,
when.day,
when.month,
when.year,
colonne_extra=("Nodo", "Lilith"),
return {"intensities": agg, "n_samples": len(samples)}
