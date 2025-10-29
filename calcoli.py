# calcoli.py — AstroBot v9
from skyfield.api import load, Topos
import numpy as np
import pandas as pd
import io, base64, math
import matplotlib.pyplot as plt
from datetime import datetime

# ======================================================
# COSTANTI
# ======================================================
PLANETI_BASE = [
    "Sole", "Luna", "Mercurio", "Venere", "Marte",
    "Giove", "Saturno", "Urano", "Nettuno", "Plutone"
]
# Nodo e Lilith opzionali
PLANETI_EXTRA = ["Nodo", "Lilith"]

# ======================================================
# DATI EPHEMERIDI
# ======================================================
ts = load.timescale()
planets = load('de421.bsp')   # puoi sostituire con DE440s per maggiore precisione

# ======================================================
# FUNZIONI PRINCIPALI
# ======================================================

def calcola_pianeti_da_df(df_tutti=None, giorno=None, mese=None, anno=None,
                           colonne_extra=('Nodo','Lilith')) -> tuple[dict, pd.DataFrame]:
    """
    Calcola le longitudini eclittiche planetarie (0–360°) per una data.
    df_tutti è mantenuto per compatibilità (può essere None).
    """
    if not all([giorno, mese, anno]):
        raise ValueError("Data incompleta.")

    t = ts.utc(anno, mese, giorno)
    e = load('de421.bsp')
    earth = e['earth']

    # Pianeti
    pianeti = {
        "Sole": e["sun"],
        "Luna": e["moon"],
        "Mercurio": e["mercury"],
        "Venere": e["venus"],
        "Marte": e["mars"],
        "Giove": e["jupiter barycenter"],
        "Saturno": e["saturn barycenter"],
        "Urano": e["uranus barycenter"],
        "Nettuno": e["neptune barycenter"],
        "Plutone": e["pluto barycenter"]
    }

    longitudes = {}
    for nome, corpo in pianeti.items():
        pos = (earth.at(t).observe(corpo).ecliptic_latlon())[1].degrees
        longitudes[nome] = pos % 360

    # Nodo e Lilith (approssimativi / opzionali)
    if 'Nodo' in colonne_extra:
        longitudes['Nodo'] = (longitudes['Luna'] + 180) % 360
    if 'Lilith' in colonne_extra:
        longitudes['Lilith'] = (longitudes['Luna'] - 180) % 360

    df = pd.DataFrame(list(longitudes.items()), columns=["Pianeta", "Longitudine"])
    return longitudes, df


# ======================================================
# ASCENDENTE / CASE
# ======================================================

def calcola_asc_mc_case(citta: str, anno: int, mese: int, giorno: int,
                        ora: int, minuti: int, fuso: float = 1.0,
                        sistema_case: str = "equal") -> dict:
    """
    Calcola Ascendente, MC, DC, IC e case (Equal House).
    """
    # --- Coordinate città (placeholder, puoi sostituire con geocoder reale) ---
    city_coords = {
        "Roma": (41.9028, 12.4964),
        "Milano": (45.4642, 9.19),
        "Napoli": (40.8518, 14.2681),
        "Torino": (45.0703, 7.6869),
        "Firenze": (43.7699, 11.2556)
    }
    lat, lon = city_coords.get(citta, (41.9, 12.5))

    # --- Tempo locale → UTC ---
    ora_utc = ora - fuso + (minuti / 60)
    t = ts.utc(anno, mese, giorno, ora_utc)

    # --- Calcolo ascendente e MC (semplificato) ---
    e = load('de421.bsp')
    observer = e['earth'] + Topos(latitude_degrees=lat, longitude_degrees=lon)
    astrometric = observer.at(t).observe(e['sun'])
    _, lon_sun, _ = astrometric.ecliptic_latlon()

    asc_long = (lon_sun.degrees + 90) % 360  # placeholder semplice
    mc_long = (lon_sun.degrees + 180) % 360
    dc_long = (asc_long + 180) % 360
    ic_long = (mc_long + 180) % 360

    # --- Case astrologiche Equal House ---
    case = {}
    for i in range(1, 13):
        case[i] = (asc_long + (i - 1) * 30) % 360

    asc = {
        "segno": segno_zodiacale(asc_long),
        "grado": int(asc_long % 30),
        "min": int(((asc_long % 30) - int(asc_long % 30)) * 60),
        "ASC": asc_long,
        "MC": mc_long,
        "DC": dc_long,
        "IC": ic_long,
        "case": case
    }
    return asc


def segno_zodiacale(longitudine: float) -> str:
    segni = [
        "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
        "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
    ]
    idx = int((longitudine % 360) // 30)
    return segni[idx]


# ======================================================
# GRAFICO POLARE DEL TEMA
# ======================================================

def genera_carta_base64(anno, mese, giorno, ora, minuti, citta):
    """
    Crea la carta natale in formato base64 (diagramma polare).
    """
    pianeti_raw, _ = calcola_pianeti_da_df(None, giorno, mese, anno)
    labels = list(pianeti_raw.keys())
    angoli = [np.deg2rad(pianeti_raw[k]) for k in labels]
    radii = np.ones(len(labels))

    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.linspace(0, 2*np.pi, 12, endpoint=False))
    ax.set_xticklabels([
        "♈︎","♉︎","♊︎","♋︎","♌︎","♍︎",
        "♎︎","♏︎","♐︎","♑︎","♒︎","♓︎"
    ])
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
