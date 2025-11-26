import os
import pandas as pd
import numpy as np
from math import degrees, atan2, asin
from datetime import datetime
from timezonefinderL import TimezoneFinder
import pytz
from skyfield.api import load
from typing import Dict, List, Optional

# ======================================================
# COSTANTI ZODIACO / RULER / CASE
# ======================================================

SEGNI_ZODIACALI: List[str] = [
    "Ariete",
    "Toro",
    "Gemelli",
    "Cancro",
    "Leone",
    "Vergine",
    "Bilancia",
    "Scorpione",
    "Sagittario",
    "Capricorno",
    "Acquario",
    "Pesci",
]

# Ruler principali per segno (per signore dell'Ascendente)
RULER_PER_SEGNO: Dict[str, str] = {
    "Ariete": "Marte",
    "Toro": "Venere",
    "Gemelli": "Mercurio",
    "Cancro": "Luna",
    "Leone": "Sole",
    "Vergine": "Mercurio",
    "Bilancia": "Venere",
    "Scorpione": "Plutone",   # potresti scegliere Marte se preferisci
    "Sagittario": "Giove",
    "Capricorno": "Saturno",
    "Acquario": "Urano",
    "Pesci": "Nettuno",
}

CASE_ANGOLARI = {1, 4, 7, 10}

# aspetti "standard" e orb per il NATALE (allineati a transiti.py)
ASPECTS_DEG_NATAL: Dict[str, float] = {
    "congiunzione": 0.0,
    "sestile": 60.0,
    "quadratura": 90.0,
    "trigono": 120.0,
    "quincunce": 150.0,
    "opposizione": 180.0,
}
ORB_MAX_NATAL: Dict[str, float] = {
    "congiunzione": 8.0,
    "sestile": 4.0,
    "quadratura": 6.0,
    "trigono": 6.0,
    "quincunce": 3.0,
    "opposizione": 8.0,
}

# ======================================================
# CARICAMENTO EFFEMERIDI ROBUSTO
# ======================================================
BASE_DIR = os.path.dirname(__file__)
EFF_PATH = os.path.join(BASE_DIR, "effemeridi_1950_2025.xlsx")


def _carica_effemeridi(path: str) -> pd.DataFrame | None:
    """
    Carica il file di effemeridi da Excel e forza tutte le colonne a numerico
    (valori non numerici -> NaN), per evitare errori strani nei calcoli.

    Ritorna un DataFrame oppure None in caso di errore.
    """
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
def geocodifica_citta_con_fuso(
    citta: str,
    anno: int,
    mese: int,
    giorno: int,
    ora: int,
    minuti: int,
) -> dict:
    """
    Geocodifica ibrida:

    1) Prova con Nominatim (geopy) per ottenere lat/lon
    2) Se fallisce, usa un fallback offline con alcune città italiane
    3) Come ultima spiaggia, usa Roma

    Ritorna:
    {
        "lat": float,
        "lon": float,
        "timezone": str,
        "fuso_orario": float,
        "note": str (opzionale)
    }
    """
    citta_norm = citta.lower().strip()

    # Fallback offline minimale
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
        # 1) Tentativo online con Nominatim
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="astrobot")
        loc = geolocator.geocode(citta, timeout=10)
        if not loc:
            raise ValueError("Città non trovata online.")

        # 2) Ricava timezone con TimezoneFinder
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
            "fuso_orario": fuso_orario,
        }

    except Exception as e:
        # 3) Fallback offline
        if citta_norm in fallback_coords:
            lat, lon, tz_name = fallback_coords[citta_norm]
            tz = pytz.timezone(tz_name)
            dt_local = tz.localize(datetime(anno, mese, giorno, ora, minuti))
            fuso_orario = dt_local.utcoffset().total_seconds() / 3600.0
            return {
                "lat": lat,
                "lon": lon,
                "timezone": tz_name,
                "fuso_orario": fuso_orario,
                "note": f"Fallback offline ({e})",
            }
        else:
            # Ultima spiaggia: Roma
            tz_name = "Europe/Rome"
            tz = pytz.timezone(tz_name)
            dt_local = tz.localize(datetime(anno, mese, giorno, ora, minuti))
            fuso_orario = dt_local.utcoffset().total_seconds() / 3600.0
            return {
                "lat": 41.9,
                "lon": 12.5,
                "timezone": tz_name,
                "fuso_orario": fuso_orario,
                "note": f"Fallback generico: {e}",
            }


# ======================================================
# CALCOLO ASCENDENTE E CASE
# ======================================================
def calcola_asc_mc_case(
    citta: str,
    anno: int,
    mese: int,
    giorno: int,
    ora: int,
    minuti: int,
    sistema_case: str = "equal",
) -> dict:
    """
    Calcola ASC, MC e cuspidi delle 12 case.

    Parametri
    ---------
    citta : str
        Nome della città (utilizzata per lat/lon e timezone).
    sistema_case : str
        - 'equal'      -> Case uguali: ogni 30° dall'ASC (comportamento storico).
        - 'whole_sign' -> Whole Sign: Casa I = 0° del segno dell'ASC.

    Ritorna un dizionario con:
      - ASC, ASC_segno, ASC_gradi_segno
      - MC, MC_segno, MC_gradi_segno
      - case: lista di 12 cuspidi in gradi
      - info su lat/lon/timezone/fuso_orario
    """
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat, lon, fuso = info["lat"], info["lon"], info["fuso_orario"]

    # Skyfield – tempo in UTC
    ts = load.timescale()
    t = ts.utc(anno, mese, giorno, ora - fuso, minuti)

    # Obliquità media
    eps = np.radians(23.4393)
    phi = np.radians(lat)
    lst_hours = (t.gmst + lon / 15.0) % 24
    LST = np.radians(lst_hours * 15)

    def ra_dec_from_lambda(lmbda: float) -> tuple[float, float]:
        sL, cL = np.sin(lmbda), np.cos(lmbda)
        sin_eps, cos_eps = np.sin(eps), np.cos(eps)
        alpha = atan2(sL * cos_eps, cL)
        delta = asin(sL * sin_eps)
        return alpha % (2 * np.pi), delta

    def altitude(lambda_rad: float) -> float:
        alpha, delta = ra_dec_from_lambda(lambda_rad)
        H = (LST - alpha + 2 * np.pi) % (2 * np.pi)
        return np.arcsin(
            np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.cos(H)
        )

    def azimuth(lambda_rad: float) -> tuple[float, float]:
        alpha, delta = ra_dec_from_lambda(lambda_rad)
        H = (LST - alpha + 2 * np.pi) % (2 * np.pi)
        h = altitude(lambda_rad)
        num = -np.sin(H)
        den = (np.tan(delta) * np.cos(phi) - np.sin(phi) * np.cos(H))
        return np.arctan2(num, den) % (2 * np.pi), h

    # Ricerca numerica dell'Ascendente: alt ~ 0, az ~ 90°
    lambdas = np.linspace(0, 2 * np.pi, 721)
    best_lambda, best_score = None, 1e9
    for lam in lambdas:
        A, h = azimuth(lam)
        score = abs(h) + 0.5 * abs((A - np.pi / 2 + np.pi) % (2 * np.pi) - np.pi)
        if score < best_score:
            best_score, best_lambda = score, lam

    asc_deg = (degrees(best_lambda) % 360.0)

    def _indice_segno(nome_segno: str) -> int:
        try:
            return SEGNI_ZODIACALI.index(nome_segno)
        except ValueError:
            raise ValueError(f"Segno non riconosciuto: {nome_segno}")

    segno_idx = int(asc_deg // 30)
    segno_nome = SEGNI_ZODIACALI[segno_idx]
    gradi_segno = round(asc_deg % 30, 2)

    # MC approssimato
    y_mc = np.sin(LST)
    x_mc = np.cos(LST) * np.cos(eps)
    mc_deg = np.degrees(np.arctan2(y_mc, x_mc)) % 360
    segno_idx_mc = int(mc_deg // 30)
    segno_mc = SEGNI_ZODIACALI[segno_idx_mc]
    gradi_mc = round(mc_deg % 30, 2)

    # ---------------- CASE ----------------
    sistema_case_out = sistema_case
    case: list[float] = []

    if sistema_case == "equal":
        # Case uguali: ogni 30° a partire dall'ASC
        case = [(asc_deg + i * 30.0) % 360.0 for i in range(12)]
        sistema_case_out = "equal"

    elif sistema_case == "whole_sign":
        # Whole Sign: casa I = 0° del segno dell'ASC
        idx_segno_asc = _indice_segno(segno_nome)
        for i in range(12):
            deg = ((idx_segno_asc + i) % 12) * 30.0
            case.append(deg)
        sistema_case_out = "whole_sign"

    else:
        # Fallback robusto: calcolo equal ma lo segnalo
        case = [(asc_deg + i * 30.0) % 360.0 for i in range(12)]
        sistema_case_out = f"fallback_equal_{sistema_case}"

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
        "sistema_case": sistema_case_out,
    }


# ======================================================
# CALCOLO POSIZIONI PLANETARIE
# ======================================================
def calcola_pianeti_da_df(
    df: pd.DataFrame,
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 0,
    minuti: int = 0,
) -> dict:
    """
    Calcola posizioni planetarie dalle effemeridi giornaliere interpolando
    tra giorno e giorno+1 in base all'ora.

    Ritorna:
      { nome_pianeta: {"gradi_eclittici": float, "retrogrado": bool}, ... }
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
        # ultimo giorno disponibile: niente interpolazione sul giorno dopo
        r1 = r0.copy()

    f0, f1 = r0.iloc[0], r1.iloc[0]
    frac = (ora + minuti / 60.0) / 24.0

    skip_cols = {"Anno", "Mese", "Giorno"}
    planet_cols = [c for c in df.columns if c not in skip_cols]

    pianeti: dict = {}
    for col in planet_cols:
        v0_raw = f0[col]
        v1_raw = f1[col]

        # se non sono numerici, salto
        if not np.issubdtype(type(v0_raw), np.number):
            continue

        raw0 = float(v0_raw)
        raw1 = float(v1_raw)

        retrogrado = raw0 < 0
        v0, v1 = abs(raw0) % 360.0, abs(raw1) % 360.0
        v_interp = (v0 + (v1 - v0) * frac) % 360.0

        pianeti[col] = {
            "gradi_eclittici": round(v_interp, 4),
            "retrogrado": retrogrado,
        }

    return pianeti


# ======================================================
# CONVERSIONE GRADI → SEGNO
# ======================================================
def decodifica_segni(pianeti_dict: dict) -> dict:
    """
    A partire da {pianeta: {"gradi_eclittici": float, "retrogrado": bool}} o simili,
    aggiunge info di segno e gradi nel segno:

      {
        pianeta: {
          "segno": str,
          "gradi_segno": float,
          "gradi_eclittici": float,
          "retrogrado": bool
        },
        ...
      }

    Ignora sempre eventuali chiavi 'Data' / 'data' / 'DATE' ecc.
    """
    segni = [
        "Ariete",
        "Toro",
        "Gemelli",
        "Cancro",
        "Leone",
        "Vergine",
        "Bilancia",
        "Scorpione",
        "Sagittario",
        "Capricorno",
        "Acquario",
        "Pesci",
    ]

    out: dict = {}
    for nome, data in pianeti_dict.items():
        # 👇 filtro definitivo: niente chiavi 'data'
        if isinstance(nome, str) and nome.lower() == "data":
            continue

        if not isinstance(data, dict):
            continue

        g = data.get("gradi_eclittici")
        if g is None:
            continue

        retro = data.get("retrogrado", False)

        try:
            g_val = float(g)
        except (TypeError, ValueError):
            continue

        idx = int(g_val // 30) % 12
        segno = segni[idx]
        gradi_segno = round(g_val % 30, 2)

        out[nome] = {
            "segno": segno,
            "gradi_segno": gradi_segno,
            "gradi_eclittici": g_val,
            "retrogrado": bool(retro),
        }

    return out


# ======================================================
# LOGICA NATALE: CASE, ASPETTI, TEMA COMPLETO
# ======================================================

def _min_delta_gradi(a: float, b: float) -> float:
    """Distanza minima tra due gradi (0-360)."""
    x = abs((a - b) % 360.0)
    return x if x <= 180.0 else 360.0 - x


def _match_aspect_natal(delta: float) -> Optional[tuple[str, float]]:
    """
    Trova se 'delta' (separazione angolare) corrisponde a un aspetto
    entro l'orb massimo. Ritorna (tipo_aspetto, orb) oppure None.
    """
    best = None
    best_orb = None
    for nome, deg in ASPECTS_DEG_NATAL.items():
        orb = abs(delta - deg)
        if orb <= ORB_MAX_NATAL.get(nome, 0.0):
            if best_orb is None or orb < best_orb:
                best, best_orb = nome, orb
    return (best, round(best_orb, 3)) if best is not None else None


def trova_casa_per_grado(grado: float, cuspidi_case: List[float]) -> int:
    """
    Dato un grado eclittico assoluto (0-360) e una lista di 12 cuspidi case
    (anch'esse in gradi assoluti), restituisce il numero di casa (1-12)
    in cui cade il grado.
    """
    if not cuspidi_case or len(cuspidi_case) != 12:
        return 0  # valore di fallback: nessuna casa valida

    g = grado % 360.0
    for i in range(12):
        start = cuspidi_case[i] % 360.0
        end = cuspidi_case[(i + 1) % 12] % 360.0

        if start <= end:
            # intervallo "normale"
            if start <= g < end:
                return i + 1
        else:
            # intervallo che attraversa 360 -> 0
            if g >= start or g < end:
                return i + 1

    # fallback: se non trovato per qualche motivo, assegna alla 12ª
    return 12


def assegna_case_ai_pianeti(
    pianeti_decod: Dict[str, Dict],
    asc_mc_case: Dict,
) -> Dict[str, int]:
    """
    Assegna una casa natale a ciascun pianeta, a partire da:

    - pianeti_decod: output di decodifica_segni (contiene gradi_eclittici)
    - asc_mc_case: output di calcola_asc_mc_case (contiene 'case')

    Ritorna:
      { nome_pianeta: numero_casa (1-12), ... }
    """
    cuspidi = asc_mc_case.get("case") or []
    if not cuspidi or len(cuspidi) != 12:
        return {}

    natal_houses: Dict[str, int] = {}
    for nome, info in pianeti_decod.items():
        g = info.get("gradi_eclittici")
        if g is None:
            continue
        try:
            casa = trova_casa_per_grado(float(g), cuspidi)
            natal_houses[nome] = casa
        except Exception:
            continue

    return natal_houses


def calcola_aspetti_natal(
    pianeti: Dict[str, Dict],
) -> List[Dict]:
    """
    Calcola gli aspetti all'interno del tema natale.

    Parametro:
      pianeti: {nome: {"gradi_eclittici": float, ...}, ...}

    Ritorna una lista di dizionari:
      {
        "pianeta1": str,
        "pianeta2": str,
        "tipo": "congiunzione"/"sestile"/...,
        "delta": float,   # separazione angolare
        "orb": float,     # scostamento dall'aspetto esatto
      }
    """
    labels = []
    for nome, data in pianeti.items():
        if not isinstance(data, dict):
            continue
        if "gradi_eclittici" in data:
            labels.append(nome)

    out: List[Dict] = []
    n = len(labels)
    for i in range(n):
        p1 = labels[i]
        g1 = pianeti[p1]["gradi_eclittici"]
        for j in range(i + 1, n):
            p2 = labels[j]
            g2 = pianeti[p2]["gradi_eclittici"]
            delta = _min_delta_gradi(g1, g2)
            m = _match_aspect_natal(delta)
            if not m:
                continue
            tipo, orb = m
            out.append(
                {
                    "pianeta1": p1,
                    "pianeta2": p2,
                    "tipo": tipo,
                    "delta": round(delta, 3),
                    "orb": round(orb, 3),
                }
            )

    out.sort(key=lambda a: (ASPECTS_DEG_NATAL[a["tipo"]], a["orb"], a["pianeta1"], a["pianeta2"]))
    return out


def costruisci_tema_natale(
    citta: str,
    data_nascita: str,  # "YYYY-MM-DD"
    ora_nascita: str,   # "HH:MM"
    sistema_case: str = "equal",
) -> Dict:
    """
    Costruisce il TEMA NATALE completo a partire da citta / data / ora.

    Ritorna un dict con:
      {
        "input": {...},
        "pianeti": {p: {"gradi_eclittici", "retrogrado"}, "Ascendente": {...}},
        "pianeti_decod": {...},
        "asc_mc_case": {...},
        "natal_houses": {pianeta: casa},
        "natal_aspects": [...],
        "asc_ruler": "Marte"/...,
      }

    Questo oggetto è pensato per essere riusato da:
      - transiti.py (prepara_tema_natale o analoghi)
      - transiti_pesatura (costruzione profilo_natale)
    """
    dn = datetime.strptime(f"{data_nascita} {ora_nascita}", "%Y-%m-%d %H:%M")

    # pianeti natali dalle effemeridi (interpolazione su ora/minuti)
    pianeti = calcola_pianeti_da_df(
        df_tutti,
        giorno=dn.day,
        mese=dn.month,
        anno=dn.year,
        ora=dn.hour,
        minuti=dn.minute,
    )

    # ASC / MC / case
    asc_mc_case = calcola_asc_mc_case(
        citta=citta,
        anno=dn.year,
        mese=dn.month,
        giorno=dn.day,
        ora=dn.hour,
        minuti=dn.minute,
        sistema_case=sistema_case,
    )

    # includiamo l'Ascendente come "pianeta" per case e aspetti se serve
    pianeti_con_asc = dict(pianeti)
    asc_deg = asc_mc_case.get("ASC")
    if isinstance(asc_deg, (int, float, np.floating)):
        pianeti_con_asc["Ascendente"] = {
            "gradi_eclittici": float(asc_deg),
            "retrogrado": False,
        }

    # decodifica in segni
    pianeti_decod = decodifica_segni(pianeti_con_asc)

    # assegnazione case
    natal_houses = assegna_case_ai_pianeti(pianeti_decod, asc_mc_case)

    # aspetti natali (tra tutti i pianeti, incluso eventualmente Ascendente)
    natal_aspects = calcola_aspetti_natal(pianeti_con_asc)

    # signore dell'Ascendente
    asc_segno = asc_mc_case.get("ASC_segno")
    asc_ruler = None
    if isinstance(asc_segno, str):
        asc_ruler = RULER_PER_SEGNO.get(asc_segno)

    return {
        "input": {
            "citta": citta,
            "data_nascita": data_nascita,
            "ora_nascita": ora_nascita,
            "sistema_case": sistema_case,
        },
        "pianeti": pianeti_con_asc,
        "pianeti_decod": pianeti_decod,
        "asc_mc_case": asc_mc_case,
        "natal_houses": natal_houses,
        "natal_aspects": natal_aspects,
        "asc_ruler": asc_ruler,
    }
