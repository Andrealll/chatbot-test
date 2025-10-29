# =============================================================
# 🔮 CALCOLI ASTROLOGICI COMPLETI — Skyfield + Effemeridi + Groq
# =============================================================

import numpy as np
import pandas as pd
from math import radians, degrees, atan2, asin
from skyfield.api import load
from geopy.geocoders import Nominatim
from timezonefinderL import TimezoneFinder
from datetime import datetime
import pytz
import matplotlib.pyplot as plt
import io, base64, os
from groq import Groq

# =============================================================
# ♈ Costanti segni
# =============================================================
SEGNI = [
    "♈ Ariete", "♉ Toro", "♊ Gemelli", "♋ Cancro",
    "♌ Leone", "♍ Vergine", "♎ Bilancia", "♏ Scorpione",
    "♐ Sagittario", "♑ Capricorno", "♒ Acquario", "♓ Pesci"
]

def _deg_to_sign(deg):
    segno_index = int(deg // 30) % 12
    segno = SEGNI[segno_index]
    gradi_segno = round(deg % 30, 2)
    return segno, gradi_segno

def _obliquita_laskar_rad(t):
    T = (t.tt - 2451545.0) / 36525.0
    eps0 = (84381.406 -
            46.836769 * T -
            0.0001831 * T**2 +
            0.00200340 * T**3 -
            0.000000576 * T**4 -
            0.0000000434 * T**5)
    return np.deg2rad(eps0 / 3600.0)

# =============================================================
# 🌍 GEOLOCALIZZAZIONE
# =============================================================
def geocodifica_citta_con_fuso(citta: str, anno:int, mese:int, giorno:int, ora:int, minuti:int):
    geolocator = Nominatim(user_agent="astrobot")
    location = geolocator.geocode(citta)
    if not location:
        raise ValueError(f"Città non trovata: {citta}")
    lat, lon = location.latitude, location.longitude
    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lat=lat, lng=lon) or "UTC"
    tz = pytz.timezone(timezone_str)
    local_dt = tz.localize(datetime(anno, mese, giorno, ora, minuti), is_dst=None)
    offset_hours = local_dt.utcoffset().total_seconds() / 3600.0
    return {"lat": lat, "lon": lon, "fuso_orario": offset_hours, "timezone": timezone_str}

# =============================================================
# 🌞 ASCENDENTE + MC + CASE
# =============================================================
def calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti, sistema_case='equal'):
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat_deg, lon_deg, fuso = info["lat"], info["lon"], info["fuso_orario"]
    ts = load.timescale()
    t = ts.utc(anno, mese, giorno, ora - fuso, minuti)
    eps = _obliquita_laskar_rad(t)
    phi = np.radians(lat_deg)
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
    y_mc = np.sin(LST)
    x_mc = np.cos(LST) * np.cos(eps)
    mc_deg = float(np.degrees(np.arctan2(y_mc, x_mc)) % 360.0)
    segno_mc, gradi_mc = _deg_to_sign(mc_deg)
    case = [(asc_deg + i*30) % 360 for i in range(12)]

    return {
        "citta": citta,
        "lat": round(lat_deg, 4),
        "lon": round(lon_deg, 4),
        "timezone": info["timezone"],
        "fuso_orario": round(fuso, 2),
        "ASC": round(asc_deg, 2), "ASC_segno": segno_asc, "ASC_gradi_segno": gradi_asc,
        "MC": round(mc_deg, 2), "MC_segno": segno_mc, "MC_gradi_segno": gradi_mc,
        "case": [round(c,2) for c in case],
        "sistema_case": sistema_case
    }

# =============================================================
# 🪐 PIANETI DA FILE EXCEL
# =============================================================
df_tutti = pd.read_excel("effemeridi_1950_2025.xlsx")

def calcola_pianeti_da_df(df_tutti, giorno, mese, anno, colonne_extra=('Nodo','Lilith')):
    r = df_tutti[(df_tutti['Giorno']==giorno)&(df_tutti['Mese']==mese)&(df_tutti['Anno']==anno)]
    if r.empty:
        raise ValueError("Data non presente in effemeridi.")
    row = r.iloc[0]
    exclude = {'Giorno','Mese','Anno'}
    valori_raw = {}; valori_norm = {}
    for col in df_tutti.columns:
        if col in exclude: continue
        try:
            v_raw = float(row[col])
        except: continue
        valori_raw[col] = v_raw
        valori_norm[col] = abs(v_raw)
    ordine = ['Sole','Luna','Mercurio','Venere','Marte','Giove','Saturno','Urano','Nettuno','Plutone']
    for extra in colonne_extra:
        if extra in valori_raw and extra not in ordine:
            ordine.append(extra)
    for c in valori_raw.keys():
        if c not in ordine:
            ordine.append(c)
    valori_raw = {k: valori_raw[k] for k in ordine if k in valori_raw}
    valori_norm = {k: valori_norm[k] for k in ordine if k in valori_norm}
    return valori_raw, valori_norm

# =============================================================
# 🎨 CARTA POLARE
# =============================================================
def genera_carta_base64(anno, mese, giorno, ora, minuti, citta):
    info = geocodifica_citta_con_fuso(citta, anno, mese, giorno, ora, minuti)
    lat, lon, fuso = info["lat"], info["lon"], info["fuso_orario"]
    res = calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti)
    valori_raw, valori_norm = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)

    plt.figure(figsize=(10,10))
    ax = plt.subplot(111, polar=True)
    for deg in range(0, 360, 30):
        th = np.deg2rad(deg)
        ax.plot([th, th], [0, 1.15], linestyle='--', linewidth=1)
        ax.text(th, 1.17, SEGNI[deg//30].split()[1], ha='center', va='center')

    # Pianeti
    for nome, gradi in valori_norm.items():
        th = np.deg2rad(gradi)
        ax.scatter(th, 1, s=220, edgecolors='k', zorder=3)
        ax.text(th, 1.07, nome, ha='center', va='center', fontsize=10, fontweight='bold')

    # ASC / MC
    asc = res["ASC"]; mc = res["MC"]
    ax.plot([np.deg2rad(asc), np.deg2rad(asc)], [0, 1.25], color='red', linewidth=3)
    ax.text(np.deg2rad(asc), 1.27, f"Asc {res['ASC_segno']}", color='red', fontweight='bold')
    ax.plot([np.deg2rad(mc), np.deg2rad(mc)], [0, 1.25], color='blue', linewidth=3)
    ax.text(np.deg2rad(mc), 1.27, f"MC {res['MC_segno']}", color='blue', fontweight='bold')

    ax.set_theta_zero_location('N'); ax.set_theta_direction(-1)
    ax.set_yticks([]); ax.set_xticks([]); ax.spines['polar'].set_visible(False)
    plt.title(f"Carta natale — {citta} {giorno:02d}/{mese:02d}/{anno}\nAsc: {res['ASC_segno']}  MC: {res['MC_segno']}")
    buf = io.BytesIO(); plt.savefig(buf, format="png", dpi=150); plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")

# =============================================================
# 🤖 INTERPRETAZIONE GROQ
# =============================================================
def interpreta_groq(dati, pianeti):
    descr = "\n".join([f"{k}: {v}°" for k,v in pianeti.items()])
    prompt = f"""
Sei un astrologo esperto. Interpreta in italiano questo tema natale.

Ascendente: {dati['ASC_segno']} ({dati['ASC_gradi_segno']}°)
Medio Cielo: {dati['MC_segno']} ({dati['MC_gradi_segno']}°)
Pianeti:
{descr}

Fornisci una sintesi di 6-8 righe, chiara e professionale.
"""
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6, max_tokens=600
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        return f"Errore Groq: {e}"
