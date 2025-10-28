import pandas as pd

# Carica i dati
df_tutti = pd.read_excel("effemeridi_1980_2000.xlsx")

def calcola_pianeti_da_df(
    df_tutti,
    giorno: int,
    mese: int,
    anno: int,
    colonne_extra=('Nodo', 'Lilith')
):
    """
    Ritorna (valori_raw, valori_norm)

    - valori_raw: {nome: valore} con negativi preservati (retrogrado)
    - valori_norm: {nome: valore} = abs(valori_raw)
    """
    r = df_tutti[
        (df_tutti['Giorno'] == giorno) &
        (df_tutti['Mese'] == mese) &
        (df_tutti['Anno'] == anno)
    ]
    if r.empty:
        raise ValueError("Nessun dato per la data richiesta nel df_tutti.")
    row = r.iloc[0]

    exclude = {'Giorno', 'Mese', 'Anno'}
    valori_raw = {}
    valori_norm = {}

    for col in df_tutti.columns:
        if col in exclude:
            continue
        try:
            v_raw = float(row[col])
        except Exception:
            continue

        valori_raw[col] = v_raw
        valori_norm[col] = abs(v_raw)

    ordine = ['Sole','Luna','Mercurio','Venere','Marte','Giove',
              'Saturno','Urano','Nettuno','Plutone']
    for extra in colonne_extra:
        if extra in valori_raw and extra not in ordine:
            ordine.append(extra)
    for c in valori_raw.keys():
        if c not in ordine:
            ordine.append(c)

    valori_raw = {k: valori_raw[k] for k in ordine if k in valori_raw}
    valori_norm = {k: valori_norm[k] for k in ordine if k in valori_norm}

    return valori_raw, valori_norm


# ============================================================
# 🔮 Calcolo completo Ascendente, MC e Case (Skyfield + Geo)
# ============================================================

import numpy as np
from math import radians, degrees, atan2, asin
from skyfield.api import load
from geopy.geocoders import Nominatim
from timezonefinderL import TimezoneFinder
from datetime import datetime
import pytz

# ================================
# Support functions
# ================================
def _deg_to_sign(deg):
    segni = [
        "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
        "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
    ]
    segno_index = int(deg // 30) % 12
    gradi_segno = round(deg % 30, 2)
    return segni[segno_index], gradi_segno


def _obliquita_laskar_rad(t):
    """Obliquità media dell'eclittica (Laskar) — in radianti"""
    T = (t.tt - 2451545.0) / 36525.0
    eps0 = (84381.406 -
            46.836769 * T -
            0.0001831 * T**2 +
            0.00200340 * T**3 -
            0.000000576 * T**4 -
            0.0000000434 * T**5)
    return np.deg2rad(eps0 / 3600.0)


# ================================
# Calcolo geografico automatico
# ================================
def geocodifica_citta_con_fuso(citta: str, anno:int, mese:int, giorno:int, ora:int, minuti:int):
    geolocator = Nominatim(user_agent="astrobot")
    location = geolocator.geocode(citta)
    if not location:
        raise ValueError(f"Città non trovata: {citta}")

    lat = location.latitude
    lon = location.longitude

    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lat=lat, lng=lon) or "UTC"
    tz = pytz.timezone(timezone_str)
    local_dt = tz.localize(datetime(anno, mese, giorno, ora, minuti), is_dst=None)
    offset_hours = local_dt.utcoffset().total_seconds() / 3600.0

    return {
        "lat": lat,
        "lon": lon,
        "fuso_orario": offset_hours,
        "timezone": timezone_str
    }


# ================================
# Calcolo Ascendente, MC e Case
# ================================
def calcola_asc_mc_case(citta:str, anno:int, mese:int, giorno:int, ora:int, minuti:int,
                        sistema_case:str='equal'):
    """
    Calcolo completo Ascendente, MC e 12 case astrologiche
    usando Skyfield + coordinate automatiche da città.
    """
    # --- Geo + Time ---
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat_deg, lon_deg, fuso_orario = info["lat"], info["lon"], info["fuso_orario"]

    ts = load.timescale()
    t  = ts.utc(anno, mese, giorno, ora - fuso_orario, minuti)

    eps = _obliquita_laskar_rad(t)
    phi = np.radians(lat_deg)
    lst_hours = t.gmst + (lon_deg / 15.0)
    LST = np.radians((lst_hours % 24.0) * 15.0)

    # --- Funzioni ausiliarie ---
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

    # --- Ricerca numerica Ascendente (alt≈0, az≈90°) ---
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
    segno, gradi_segno = _deg_to_sign(asc_deg)

    # --- Medio Cielo (formula astronomica) ---
    y_mc = np.sin(LST)
    x_mc = np.cos(LST) * np.cos(eps)
    mc_deg = float(np.degrees(np.arctan2(y_mc, x_mc)) % 360.0)
    segno_mc, gradi_mc = _deg_to_sign(mc_deg)

    # --- Case (Equal) ---
    case = [(asc_deg + i * 30) % 360 for i in range(12)]

    return {
        "citta": citta,
        "lat": round(lat_deg, 4),
        "lon": round(lon_deg, 4),
        "timezone": info["timezone"],
        "fuso_orario": round(fuso_orario, 2),
        "ASC": round(asc_deg, 2),
        "ASC_segno": segno,
        "ASC_gradi_segno": gradi_segno,
        "MC": round(mc_deg, 2),
        "MC_segno": segno_mc,
        "MC_gradi_segno": gradi_mc,
        "case": [round(c, 2) for c in case],
        "sistema_case": sistema_case,
        "precisione": "Skyfield"
    }

