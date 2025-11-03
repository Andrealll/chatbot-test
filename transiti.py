# transiti.py
from typing import Optional, Dict, List, Any
from astrobot_core.calcoli import (
    df_tutti,
    calcola_pianeti_da_df,   # firma: (df_tutti, giorno, mese, anno, ora, minuti)
    calcola_asc_mc_case      # nel tuo progetto: (citta, anno, mese, giorno, ora, minuti)
)

# =========================
# Helper: normalizzazione
# =========================
_NUMERIC_KEYS_PRIOR = (
    "lon", "long", "longitudine", "lambda", "ecl_lon",
    "gradi", "degree", "deg", "angle", "pos"
)

def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace("°", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None

def _extract_degree(val: Any) -> Optional[float]:
    """
    Estrae longitudine (0..360) da:
    - numero o stringa ("123.4°")
    - dict (chiavi tipiche: lon/long/longitudine/lambda/ecl_lon/gradi/degree/deg/angle/pos)
    - lista/tupla (primo valore numerico plausibile)
    """
    f = _to_float(val)
    if f is not None:
        return f % 360.0

    if isinstance(val, dict):
        # prova chiavi più comuni
        for k in _NUMERIC_KEYS_PRIOR:
            if k in val:
                f = _to_float(val[k])
                if f is not None:
                    return f % 360.0
        # altrimenti, primo valore numerico plausibile
        for v in val.values():
            f = _to_float(v)
            if f is not None:
                return f % 360.0
        return None

    if isinstance(val, (list, tuple)):
        for v in val:
            f = _to_float(v)
            if f is not None:
                return f % 360.0

    return None

# =========================
# Filtri sui nomi
# =========================
ALLOWED_BODIES = {
    # pianeti/luminari in italiano
    "sole", "luna", "mercurio", "venere", "marte",
    "giove", "saturno", "urano", "nettuno", "plutone",
    # punti opzionali
    "nodo", "lilith"
}
# chiavi da escludere sempre (rumore frequente)
EXCLUDE_KEYS = {
    "data", "date", "ora", "time", "citta", "city",
    "asc", "ascendente", "mc", "medium coeli",
    "lat", "lon", "long", "longitudine", "lambda", "ecl_lon"
}

def _is_planet_name(name: str) -> bool:
    n = name.strip().lower()
    if n in EXCLUDE_KEYS:
        return False
    return n in ALLOWED_BODIES

# =========================
# Spec aspetti
# =========================
_ASPECT_SPEC = {
    "congiunzione": {"angles": [0],         "orb": 6},
    "opposizione":  {"angles": [180],       "orb": 6},
    "trigono":      {"angles": [120, 240],  "orb": 4},
    "quadratura":   {"angles": [90, 270],   "orb": 4},
}

def _ang_delta(a: float, b: float) -> float:
    """Separazione direzionale (b - a) % 360 in [0, 360)."""
    return (b - a) % 360.0

def _circular_dist(x: float, target: float) -> float:
    """Distanza circolare minima tra x e target (0..180)."""
    diff = abs((x - target) % 360.0)
    return min(diff, 360.0 - diff)

def _match_aspect(delta: float):
    """Se delta ricade in una finestra d’aspetto, ritorna (tipo, orb); altrimenti None."""
    for tipo, spec in _ASPECT_SPEC.items():
        orb = spec["orb"]
        for ang in spec["angles"]:
            d = _circular_dist(delta, ang)
            if d <= orb:
                return tipo, d
    return None

# =========================
# Funzione pubblica
# =========================
def calcola_transiti_data_fissa(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    citta: Optional[str] = None,
) -> Dict:
    """
    Calcola:
      - posizioni planetarie (longitudini 0..360) per i soli corpi ammessi
      - ASC/MC/Case (se 'citta' è fornita)
      - aspetti tra tutte le coppie di pianeti (senza duplicati)
    """
    if df_tutti is None or getattr(df_tutti, "empty", False):
        raise RuntimeError("Effemeridi non caricate correttamente (df_tutti è vuoto o None).")

    # 1) Pianeti (firma tua) + filtro nomi + normalizzazione
    raw_pianeti = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora, minuti)

    long_pianeti: Dict[str, float] = {}
    scartati_valore: List[str] = []
    esclusi_nome: List[str] = []

    for nome, val in raw_pianeti.items():
        if not _is_planet_name(nome):
            esclusi_nome.append(str(nome))
            continue
        deg = _extract_degree(val)
        if deg is None:
            scartati_valore.append(str(nome))
        else:
            long_pianeti[str(nome)] = deg

    if not long_pianeti:
        raise ValueError("Nessuna longitudine planetaria valida ricavata (nomi filtrati o valori non numerici).")

    # 2) ASC/MC/Case (solo se ho la città, coerente con /tema)
    asc_mc_case = None
    if citta:
        try:
            asc_mc_case = calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti)
        except Exception as e:
            asc_mc_case = {"errore": f"calcola_asc_mc_case: {e}"}

    # 3) Aspetti (no duplicati p1-p2)
    pianeti = list(long_pianeti.keys())
    aspetti: List[Dict] = []
    for i in range(len(pianeti)):
        p1 = pianeti[i]
        for j in range(i + 1, len(pianeti)):
            p2 = pianeti[j]
            delta = _ang_delta(long_pianeti[p1], long_pianeti[p2])  # 0..360
            m = _match_aspect(delta)
            if m:
                tipo, orb = m
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

    # Meta diagnostica: cosa ho escluso e perché
    meta: Dict[str, Any] = {}
    if esclusi_nome:
        meta["esclusi_per_nome"] = esclusi_nome
    if scartati_valore:
        meta["scartati_per_valore"] = scartati_valore

    return {
        "data": f"{anno:04d}-{mese:02d}-{giorno:02d} {ora:02d}:{minuti:02d}",
        "asc_mc_case": asc_mc_case,
        "pianeti": long_pianeti,
        "aspetti": aspetti,
        "meta": meta
    }
