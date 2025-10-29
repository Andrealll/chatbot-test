# calcoli.py — AstroBot v11
# Accurate Ascendant + Planets interpolation

import numpy as np
import pandas as pd
import math, os
from math import radians, degrees, atan2, asin
from datetime import datetime, timedelta
from skyfield.api import load
from timezonefinder import TimezoneFinder
import pytz

# ======================================================
# CONFIG
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EFF_PATH = os.path.join(BASE_DIR, "effemeridi_1950_2025.xlsx")

try:
    df_tutti = pd.read_excel(EFF_PATH)
except Exception as e:
    print(f"[ATTENZIONE] Errore nel caricamento effemeridi: {e}")
    df_tutti = None

ts = load.timescale()

# ======================================================
# SUPPORT FUNCTIONS
# ======================================================

def _obliquita_laskar_rad(t):
    """Calcola l'obliquità dell'eclittica in radianti."""
    T = (t.tt - 2451545.0) / 36525.0
    eps = np.radians(23 + 26/60 + (21.448 - 46.8150*T - 0.00059*T**2 + 0.001813*T**3)/3600)
    return eps

def _deg_to_sign(deg):
    segni = [
        "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
        "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
    ]
    idx = int((deg % 360) // 30)
    return segni[idx], round(deg % 30, 2)

def geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti):
    """Ottiene latitudine, longitudine, timezone e fuso locale usando timezonefinder."""
    # Dizionario rapido di fallback (se non si vuole usare API)
    lookup = {
        "Roma": (41.9028, 12.4964),
        "Milano": (45.4642, 9.19),
        "Napoli": (40.8518, 14.2681),
        "Torino": (45.0703, 7.6869),
        "Firenze": (43.7699, 11.2556)
    }
    lat, lon = lookup.get(citta, (41.9, 12.5))
    tz_name = TimezoneFinder().timezone_at(lng=lon, lat=lat)
    tz = pytz.timezone(tz_name)
    dt_local = tz.localize(datetime(anno, mese, giorno, ora, minuti))
    fuso = dt_local.utcoffset().total_seconds() / 3600.0
    return {"lat": lat, "lon": lon, "timezone": tz_name, "fuso_orario": fuso}


# ======================================================
# CALCOLO ASCENDENTE E CASE
# ======================================================

def calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti, sistema_case='equal'):
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat_deg, lon_deg, fuso = info["lat"], info["lon"], info["fuso_orario"]

    ts = load.timescale()
    t = ts.utc(anno, mese, giorno, ora - fuso, minuti)
    eps = _obliquita_laskar_rad(t)
    phi = np.radians(lat_deg)

    # Tempo siderale locale (in radianti)
    lst_hours = t.gmst + (lon_deg / 15.0)
    LST = np.radians((lst_hours % 24.0) * 15.0)

    def ra_dec_from_lambda(lmbda):
        sL, cL = np.sin(lmbda), np.cos(lmbda)
        sin_eps, cos_eps = np.sin(eps), np.cos(eps)
        alpha = atan2(sL * cos_eps, cL)
        delta = asin(sL * sin_eps)
        return alpha % (2*np.pi), delta

    def altitude(lambda_rad):
        alpha, delta = ra_dec_from_lambda(lambda_rad)
        H = (LST - alpha + 2*np.pi) % (2*np.pi)
        return np.arcsin(np.sin(phi)*np.sin(delta) + np.cos(phi)*np.cos(delta)*np.cos(H))

    def azimuth(lambda_rad):
        alpha, delta = ra_dec_from_lambda(lambda_rad)
        H = (LST - alpha + 2*np.pi) % (2*np.pi)
        h = altitude(lambda_rad)
        num = -np.sin(H)
        den = (np.tan(delta)*np.cos(phi) - np.sin(phi)*np.cos(H))
        A = np.arctan2(num, den) % (2*np.pi)
        return A, h

    # ricerca dell'ascendente (punto all'orizzonte est)
    lambdas = np.linspace(0, 2*np.pi, 721)
    best_lambda, best_score = None, 1e9
    for lam in lambdas:
        A, h = azimuth(lam)
        score = abs(h) + 0.5*abs((A - np.pi/2 + np.pi) % (2*np.pi) - np.pi)
        if score < best_score:
            best_score, best_lambda = score, lam

    fine = np.linspace(best_lambda - np.deg2rad(2), best_lambda + np.deg2rad(2), 401)
    for lam in fine:
        A, h = azimuth(lam)
        score = abs(h) + 0.5*abs((A - np.pi/2 + np.pi) % (2*np.pi) - np.pi)
        if score < best_score:
            best_score, best_lambda = score, lam

    asc_deg = float((degrees(best_lambda)) % 360.0)
    segno_asc, gradi_asc = _deg_to_sign(asc_deg)

    # Medio Cielo
    y_mc = np.sin(LST)
    x_mc = np.cos(LST) * np.cos(eps)
    mc_deg = float(np.degrees(np.arctan2(y_mc, x_mc)) % 360.0)
    segno_mc, gradi_mc = _deg_to_sign(mc_deg)

    # Case equal
    case = [(asc_deg + i*30) % 360 for i in range(12)]

    return {
        "citta": citta,
        "lat": round(lat_deg, 4),
        "lon": round(lon_deg, 4),
        "timezone": info["timezone"],
        "fuso_orario": round(fuso, 2),
        "ASC": round(asc_deg, 2),
        "ASC_segno": segno_asc,
        "ASC_gradi_segno": gradi_asc,
        "MC": round(mc_deg, 2),
        "MC_segno": segno_mc,
        "MC_gradi_segno": gradi_mc,
        "case": [round(c, 2) for c in case],
        "sistema_case": sistema_case
    }


# ======================================================
# CALCOLO PIANETI INTERPOLATO DALLE EFFEMERIDI
# ======================================================

def calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora=0, minuti=0, colonne_extra=('Nodo','Lilith')):
    """
    Restituisce le longitudini planetarie (in gradi) per data e ora specifica.
    Usa le effemeridi giornaliere e interpola linearmente l'ora.
    """
    if df_tutti is None:
        raise ValueError("Effemeridi non caricate correttamente.")
    
    # colonna data nel formato datetime
    if 'Data' in df_tutti.columns:
        df_tutti['Data'] = pd.to_datetime(df_tutti['Data'])
    else:
        raise ValueError("Il file effemeridi deve contenere una colonna 'Data'.")

    target_date = datetime(anno, mese, giorno)
    next_date = target_date + timedelta(days=1)

    # trova righe corrispondenti
    row_today = df_tutti[df_tutti['Data'] == target_date]
    row_next = df_tutti[df_tutti['Data'] == next_date]

    if row_today.empty or row_next.empty:
        raise ValueError("Data fuori intervallo effemeridi.")

    # frazione oraria del giorno (0.0–1.0)
    frac = (ora + minuti/60) / 24.0

    pianeti = {}
    planet_cols = [c for c in df_tutti.columns if c not in ['Data']]

    for col in planet_cols:
        val_today = float(row_today[col].values[0])
        val_next = float(row_next[col].values[0])
        diff = (val_next - val_today) % 360
        interpolated = (val_today + diff * frac) % 360
        pianeti[col] = interpolated

    # Nodo e Lilith opzionali
    if 'Nodo' in colonne_extra:
        pianeti['Nodo'] = (pianeti['Luna'] + 180) % 360
    if 'Lilith' in colonne_extra:
        pianeti['Lilith'] = (pianeti['Luna'] - 180) % 360

    return pianeti


# ======================================================
# GRAFICO POLARE DEL TEMA
# ======================================================

import io, base64
import matplotlib.pyplot as plt

def genera_carta_base64(anno, mese, giorno, ora, minuti, citta):
    """
    Disegna il tema natale in formato base64 (diagramma polare).
    """
    pianeti_raw = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora, minuti)
    labels = list(pianeti_raw.keys())
    angoli = [np.deg2rad(pianeti_raw[k]) for k in labels]
    radii = np.ones(len(labels))

    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.linspace(0, 2*np.pi, 12, endpoint=False))
    ax.set_xticklabels(["♈︎","♉︎","♊︎","♋︎","♌︎","♍︎","♎︎","♏︎","♐︎","♑︎","♒︎","♓︎"])
    ax.set_yticklabels([])
    ax.scatter(angoli, radii, s=80, c="black")
    for i, label in enumerate(labels):
        ax.text(angoli[i], 1.05, label, ha='center', va='center', fontsize=8)
    ax.set_title(f"{citta} – {giorno:02d}/{mese:02d}/{anno}", va='bottom')

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_b64}"
