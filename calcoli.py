import os
import pandas as pd
import numpy as np
from math import degrees, atan2, asin
from datetime import datetime
from timezonefinder import TimezoneFinder
import pytz
from skyfield.api import load


# ======================================================
# CARICAMENTO EFFEMERIDI ROBUSTO
# ======================================================
BASE_DIR = os.path.dirname(__file__)
EFF_PATH = os.path.join(BASE_DIR, "effemeridi_1950_2025.xlsx")

def _carica_effemeridi(path):
    try:
        df = pd.read_excel(path)
        # Conversione universale a numerico
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
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
# GEOLOCALIZZAZIONE E FUSO
# ======================================================
def geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti):
    """
    Geocodifica ibrida:
    1️⃣ Prova con Nominatim (geopy)
    2️⃣ Se non riesce (timeout o errore di rete), fallback su coordinate approssimative offline
    """
    citta = citta.lower().strip()
    from datetime import datetime
    import pytz

    # 🔹 Mappatura base per fallback offline
    fallback_coords = {
        "napoli": (40.8518, 14.2681, "Europe/Rome"),
        "roma": (41.9028, 12.4964, "Europe/Rome"),
        "milano": (45.4642, 9.19, "Europe/Rome"),
        "torino": (45.0703, 7.6869, "Europe/Rome"),
        "firenze": (43.7696, 11.2558, "Europe/Rome"),
        "bologna": (44.4949, 11.3426, "Europe/Rome"),
        "palermo": (38.1157, 13.3615, "Europe/Rome"),
        "genova": (44.4056, 8.9463, "Europe/Rome"),
        "bari": (41.1253, 16.8660, "Europe/Rome"),
        "cagliari": (39.2238, 9.1217, "Europe/Rome"),
    }

    try:
        # 1️⃣ Tentativo online con geopy / Nominatim
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="astrobot")
        loc = geolocator.geocode(citta, timeout=10)
        if not loc:
            raise ValueError("Città non trovata online.")

        # 2️⃣ Ricava timezone con timezonefinder
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        timezone_str = tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
        if not timezone_str:
            timezone_str = "UTC"

        tz = pytz.timezone(timezone_str)
        dt_local = tz.localize(datetime(anno, mese, giorno, ora, minuti))
        fuso_orario = dt_local.utcoffset().total_seconds() / 3600.0

        return {
            "lat": loc.latitude,
            "lon": loc.longitude,
            "timezone": timezone_str,
            "fuso_orario": fuso_orario
        }

    except Exception as e:
        # 🔸 Fallback offline
        if citta in fallback_coords:
            lat, lon, tz_name = fallback_coords[citta]
            tz = pytz.timezone(tz_name)
            dt_local = tz.localize(datetime(anno, mese, giorno, ora, minuti))
            fuso_orario = dt_local.utcoffset().total_seconds() / 3600.0
            return {
                "lat": lat,
                "lon": lon,
                "timezone": tz_name,
                "fuso_orario": fuso_orario,
                "note": f"Fallback offline ({e})"
            }
        else:
            # come ultima spiaggia, coord generiche (Roma)
            return {
                "lat": 41.9,
                "lon": 12.5,
                "timezone": "Europe/Rome",
                "fuso_orario": 1.0,
                "note": f"Fallback generico: {e}"
            }



# ======================================================
# CALCOLO ASCENDENTE E CASE
# ======================================================
def calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti, sistema_case='equal'):
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat, lon, fuso = info["lat"], info["lon"], info["fuso_orario"]

    ts = load.timescale()
    t = ts.utc(anno, mese, giorno, ora - fuso, minuti)
    eps = np.radians(23.4393)
    phi = np.radians(lat)
    lst_hours = (t.gmst + lon / 15.0) % 24
    LST = np.radians(lst_hours * 15)

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
        return np.arctan2(num, den) % (2*np.pi), h

    lambdas = np.linspace(0, 2*np.pi, 721)
    best_lambda, best_score = None, 1e9
    for lam in lambdas:
        A, h = azimuth(lam)
        score = abs(h) + 0.5*abs((A - np.pi/2 + np.pi) % (2*np.pi) - np.pi)
        if score < best_score:
            best_score, best_lambda = score, lam

    asc_deg = (degrees(best_lambda) % 360.0)

    segni = [
        "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
        "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
    ]
    segno_idx = int(asc_deg // 30)
    segno_nome = segni[segno_idx]
    gradi_segno = round(asc_deg % 30, 2)

    y_mc = np.sin(LST)
    x_mc = np.cos(LST) * np.cos(eps)
    mc_deg = np.degrees(np.arctan2(y_mc, x_mc)) % 360
    segno_idx_mc = int(mc_deg // 30)
    segno_mc = segni[segno_idx_mc]
    gradi_mc = round(mc_deg % 30, 2)

    case = [(asc_deg + i * 30) % 360 for i in range(12)]

    return {
        "citta": citta,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "timezone": info["timezone"],
        "fuso_orario": round(fuso, 2),
        "ASC": round(asc_deg, 2),
        "ASC_segno": segno_nome,
        "ASC_gradi_segno": gradi_segno,
        "MC": round(mc_deg, 2),
        "MC_segno": segno_mc,
        "MC_gradi_segno": gradi_mc,
        "case": [round(c, 2) for c in case],
        "sistema_case": sistema_case
    }


# ======================================================
# CALCOLO POSIZIONI PLANETARIE
# ======================================================
def calcola_pianeti_da_df(df, giorno, mese, anno, ora=0, minuti=0):
    """
    Calcola posizioni planetarie ignorando il segno (retrogrado) nei valori.
    Restituisce {pianeta: {gradi_eclittici, retrogrado}}.
    """
    if df is None or df.empty:
        raise ValueError("Effemeridi non caricate correttamente.")

    giorno_int = int(giorno)
    r0 = df[(df["Anno"] == anno) & (df["Mese"] == mese) & (df["Giorno"].astype(int) == giorno_int)]
    r1 = df[(df["Anno"] == anno) & (df["Mese"] == mese) & (df["Giorno"].astype(int) == giorno_int + 1)]

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
        if not np.issubdtype(type(f0[col]), np.number):
            continue
        raw0 = float(f0[col])
        raw1 = float(f1[col])
        retrogrado = raw0 < 0
        v0, v1 = abs(raw0) % 360.0, abs(raw1) % 360.0
        v_interp = (v0 + (v1 - v0) * frac) % 360.0
        pianeti[col] = {"gradi_eclittici": round(v_interp, 4), "retrogrado": retrogrado}

    return pianeti


# ======================================================
# CONVERSIONE GRADI → SEGNO
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
# GENERAZIONE IMMAGINE
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
