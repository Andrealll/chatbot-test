import os
import pandas as pd
import numpy as np
from math import degrees, atan2, asin
from datetime import datetime
from timezonefinder import TimezoneFinder
import pytz
from skyfield.api import load


# ======================================================
# CARICAMENTO EFFEMERIDI (robusto)
# ======================================================
BASE_DIR = os.path.dirname(__file__)
EFF_PATH = os.path.join(BASE_DIR, "effemeridi_1975_2025.xlsx")

def _carica_effemeridi(path):
    try:
        df = pd.read_excel(path)
        # Converti tutte le colonne (tranne le prime 3) in numeriche forzate
        for col in df.columns:
            if col not in ("Anno", "Mese", "Giorno"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Anche la colonna "Giorno" deve essere numerica
        df["Giorno"] = pd.to_numeric(df["Giorno"], errors="coerce")
        return df
    except Exception as e:
        print(f"[ERRORE] Impossibile caricare effemeridi: {e}")
        return None

df_tutti = _carica_effemeridi(EFF_PATH)
if df_tutti is not None:
    print(f"[AstroBot] Effemeridi caricate correttamente ({len(df_tutti)} righe)")
else:
    print("[ERRORE] Nessun file di effemeridi valido trovato.")


# ======================================================
# CALCOLO POSIZIONI PLANETARIE (aggiornato)
# ======================================================
def calcola_pianeti_da_df(df, giorno, mese, anno, ora=0, minuti=0):
    """
    Calcola posizioni planetarie ignorando il segno (retrogrado) nei valori.
    Restituisce {pianeta: {gradi_eclittici, retrogrado}}.
    """
    if df is None or df.empty:
        raise ValueError("Effemeridi non caricate correttamente.")

    giorno_int = int(giorno)

    r0 = df[
        (df["Anno"] == anno)
        & (df["Mese"] == mese)
        & (df["Giorno"].astype(int) == giorno_int)
    ]
    r1 = df[
        (df["Anno"] == anno)
        & (df["Mese"] == mese)
        & (df["Giorno"].astype(int) == giorno_int + 1)
    ]

    if r0.empty:
        raise ValueError(f"Nessuna effemeride trovata per {giorno}/{mese}/{anno}")
    if r1.empty:
        r1 = r0.copy()

    f0, f1 = r0.iloc[0], r1.iloc[0]
    frac = (ora + minuti / 60.0) / 24.0

    skip_cols = {"Anno", "Mese", "Giorno"}
    planet_cols = [c for c in df.columns if c not in skip_cols]

    pianeti = {}
    for col in planet_cols:
        # Ignora colonne non numeriche
        if not np.issubdtype(type(f0[col]), np.number):
            continue

        raw0 = float(f0[col])
        raw1 = float(f1[col])
        retrogrado = raw0 < 0
        v0, v1 = abs(raw0) % 360.0, abs(raw1) % 360.0
        v_interp = (v0 + (v1 - v0) * frac) % 360.0
        pianeti[col] = {
            "gradi_eclittici": round(v_interp, 4),
            "retrogrado": retrogrado
        }

    return pianeti



# ======================================================
# CONVERSIONE GRADI → SEGNO + GRADI SEGNO
# ======================================================
def decodifica_segni(pianeti_dict: dict) -> dict:
    segni = [
        "Ariete","Toro","Gemelli","Cancro","Leone","Vergine",
        "Bilancia","Scorpione","Sagittario","Capricorno","Acquario","Pesci"
    ]
    out = {}
    for nome, data in pianeti_dict.items():
        g = data["gradi_eclittici"]
        retro = data["retrogrado"]
        idx = int(g // 30)
        segno = segni[idx]
        gradi_segno = round(g % 30, 2)
        out[nome] = {
            "segno": segno,
            "gradi_segno": gradi_segno,
            "gradi_eclittici": g,
            "retrogrado": retro
        }
    return out


# ======================================================
# GENERA IMMAGINE CARTA (placeholder)
# ======================================================
def genera_carta_base64(anno, mese, giorno, ora, minuti, citta):
    import io, base64
    import matplotlib.pyplot as plt
    plt.figure(figsize=(3, 3))
    plt.title(f"Tema di {citta}\n{giorno:02d}/{mese:02d}/{anno}")
    plt.plot([0, 1], [0, 1], "k--")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()
