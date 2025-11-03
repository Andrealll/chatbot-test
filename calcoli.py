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
# =========================
# Transiti su data fissa
# =========================
from typing import Dict, List, Tuple, Optional
import math

# Se questo file è separato, importa ciò che hai già:
# from calcoli import df_tutti, calcola_pianeti_da_df, calcola_asc_mc_case

_ASPECT_SPEC = {
    "congiunzione": {"angles": [0],         "orb": 6},
    "opposizione":  {"angles": [180],       "orb": 6},
    "trigono":      {"angles": [120, 240],  "orb": 4},
    "quadratura":   {"angles": [90, 270],   "orb": 4},
}

def _ang_delta(a: float, b: float) -> float:
    """
    Ritorna la separazione direzionale (0..360) tra a e b (in gradi).
    delta = (b - a) mod 360.
    """
    d = (b - a) % 360.0
    return d

def _circular_dist(x: float, target: float) -> float:
    """
    Distanza circolare minima in gradi tra un angolo x e un angolo 'target'.
    """
    diff = abs((x - target) % 360.0)
    return min(diff, 360.0 - diff)

def _match_aspect(delta: float) -> Optional[Tuple[str, float]]:
    """
    Dato delta in [0, 360), ritorna (tipo_aspetto, orb) se cade in una
    delle finestre specificate; altrimenti None.
    L'orb è la distanza dall'angolo esatto dell'aspetto.
    """
    for tipo, spec in _ASPECT_SPEC.items():
        orb = spec["orb"]
        for ang in spec["angles"]:
            if _circular_dist(delta, ang) <= orb:
                return tipo, _circular_dist(delta, ang)
    return None

def calcola_transiti_data_fissa(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    fuso_orario: float = 0.0,
    sistema_case: str = "equal",
    include_extras: Tuple[str, ...] = ("Nodo", "Lilith"),
    usa_df: bool = True,
) -> Dict:
    """
    Calcola posizioni planetarie, ASC/MC/case per una data/ora e rileva i transiti
    planetari del giorno tra tutte le coppie di pianeti.

    Parametri
    ---------
    giorno, mese, anno : int
    ora, minuti        : int
    lat, lon           : float opzionali (necessari per ASC/MC/case)
    fuso_orario        : float (es. +1.0 per CET senza DST; gestisci come nel tuo progetto)
    sistema_case       : 'equal', 'placidus', ecc. (come implementato nel tuo calcolo case)
    include_extras     : tuple di corpi extra da includere se presenti nei tuoi dati
    usa_df             : se True usa calcola_pianeti_da_df/ephemeridi; in alternativa
                         puoi agganciare qui un calcolo Skyfield

    Ritorna
    -------
    dict con:
      - 'data'   : stringa ISO-like
      - 'ASC', 'MC', 'case'
      - 'pianeti': dict {nome: longitudine (0..360)}
      - 'aspetti': lista di dict con chiavi:
            'pianeta1', 'pianeta2', 'tipo', 'delta', 'orb'
        dove:
          - delta è (long2 - long1) mod 360 (0..360)
          - orb è la distanza dall’angolo esatto dell’aspetto
    """
    # 1) Posizioni planetarie
    if usa_df:
        long_pianeti = calcola_pianeti_da_df(
            df_tutti, giorno, mese, anno, colonne_extra=include_extras
        )
    else:
        # Se hai un tuo calcolo Skyfield, aggancialo qui:
        # long_pianeti = calcola_pianeti_skyfield(giorno, mese, anno, ora, minuti, include_extras=include_extras)
        raise NotImplementedError("Imposta usa_df=True o implementa il ramo Skyfield.")

    # Pulizia NaN e cast a float
    long_pianeti = {k: float(v) for k, v in long_pianeti.items() if v == v}

    # 2) ASC / MC / Case (se lat/lon sono forniti)
    asc = mc = case = None
    if lat is not None and lon is not None:
        # Tenta con keyword per compatibilità con la tua firma
        try:
            res = calcola_asc_mc_case(
                giorno=giorno, mese=mese, anno=anno,
                ora=ora, minuti=minuti,
                lat=lat, lon=lon,
                fuso_orario=fuso_orario,
                sistema_case=sistema_case
            )
        except TypeError:
            # Fallback ad una possibile firma alternativa (adatta se necessario)
            res = calcola_asc_mc_case(lat, lon, giorno, mese, anno, ora, minuti, fuso_orario, sistema_case)

        if isinstance(res, dict):
            asc, mc, case = res.get("ASC"), res.get("MC"), res.get("case")
        else:
            # supponiamo una tupla (asc, mc, case)
            asc, mc, case = res

    # 3) Aspetti (transiti del giorno tra pianeti)
    # Ordine chiavi per non duplicare (p1, p2) e (p2, p1)
    pianeti = list(long_pianeti.keys())
    aspetti: List[Dict] = []

    for i in range(len(pianeti)):
        p1 = pianeti[i]
        for j in range(i + 1, len(pianeti)):
            p2 = pianeti[j]
            delta = _ang_delta(long_pianeti[p1], long_pianeti[p2])  # 0..360
            match = _match_aspect(delta)
            if match:
                tipo, orb = match
                aspetti.append({
                    "pianeta1": p1,
                    "pianeta2": p2,
                    "tipo": tipo,
                    "delta": round(delta, 3),
                    "orb": round(orb, 3),
                })

    # Ordina per tipo e orb crescente
    ordine_tipo = {"congiunzione": 0, "opposizione": 1, "trigono": 2, "quadratura": 3}
    aspetti.sort(key=lambda x: (ordine_tipo.get(x["tipo"], 99), x["orb"]))

    return {
        "data": f"{anno:04d}-{mese:02d}-{giorno:02d} {ora:02d}:{minuti:02d}",
        "ASC": asc,
        "MC": mc,
        "case": case,
        "pianeti": long_pianeti,
        "aspetti": aspetti,
    }

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
