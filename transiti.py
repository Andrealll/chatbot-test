# transiti.py
from typing import Any

_NUMERIC_KEYS_PRIOR = ("lon", "long", "longitudine", "lambda", "ecl_lon", "gradi", "degree", "deg", "angle", "pos")

def _to_float(x: Any):
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

def _extract_degree(val: Any):
    """
    Estrae una longitudine (0..360) da:
    - numero o stringa ("123.4°")
    - dict (chiavi tipiche: lon/long/longitudine/lambda/ecl_lon/gradi/degree/deg/angle/pos)
    - lista/tupla (primo valore numerico)
    """
    f = _to_float(val)
    if f is not None:
        return f % 360.0
    if isinstance(val, dict):
        for k in _NUMERIC_KEYS_PRIOR:
            if k in val:
                f = _to_float(val[k])
                if f is not None:
                    return f % 360.0
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
from astrobot_core.calcoli import (
    df_tutti,
    calcola_pianeti_da_df,   # firma: (df_tutti, giorno, mese, anno, ora, minuti)
    calcola_asc_mc_case      # nel tuo progetto accetta: (citta, anno, mese, giorno, ora, minuti)
)

# ---- specifiche aspetti (come richiesto) ----
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
    """Distanza circolare minima tra x e target su circonferenza (0..180)."""
    diff = abs((x - target) % 360.0)
    return min(diff, 360.0 - diff)

def _match_aspect(delta: float):
    """
    Se delta cade in una finestra d'aspetto ritorna (tipo, orb) altrimenti None.
    orb = distanza dall'angolo esatto dell'aspetto.
    """
    for tipo, spec in _ASPECT_SPEC.items():
        orb = spec["orb"]
        for ang in spec["angles"]:
            d = _circular_dist(delta, ang)
            if d <= orb:
                return tipo, d
    return None

def calcola_transiti_data_fissa(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    citta: Optional[str] = None,
) -> Dict:
    """
    Calcola: posizioni planetarie (longitudini 0..360), ASC/MC/Case (se 'citta' è fornita),
    e aspetti (congiunzione/opposizione/trigono/quadratura) tra tutte le coppie di pianeti.
    Non modifica né rimpiazza i tuoi metodi esistenti.
    """
    if df_tutti is None or getattr(df_tutti, "empty", False):
        raise RuntimeError("Effemeridi non caricate correttamente (df_tutti è vuoto o None).")

    # 1) Pianeti (usa la tua firma con ora/minuti)
    long_pianeti = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora, minuti)
    long_pianeti = {
        k: float(v) for k, v in long_pianeti.items()
        if v is not None and v == v
    }

    # 2) ASC/MC/Case (solo se ho la città, coerente con /tema)
    asc_mc_case = None
    if citta:
        try:
            asc_mc_case = calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti)
        except Exception as e:
            asc_mc_case = {"errore": f"calcola_asc_mc_case: {e}"}

    # 3) Aspetti tra pianeti (niente duplicati p1-p2)
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

    # ordina per tipo e orb crescente
    ordine_tipo = {"congiunzione": 0, "opposizione": 1, "trigono": 2, "quadratura": 3}
    aspetti.sort(key=lambda x: (ordine_tipo.get(x["tipo"], 99), x["orb"]))

    return {
        "data": f"{anno:04d}-{mese:02d}-{giorno:02d} {ora:02d}:{minuti:02d}",
        "asc_mc_case": asc_mc_case,   # è il risultato integro della tua funzione
        "pianeti": long_pianeti,      # es. {"Sole": 123.4, ...}
        "aspetti": aspetti            # lista di aspetti trovati
    }
