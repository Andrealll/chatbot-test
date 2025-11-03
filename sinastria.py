from datetime import datetime
from typing import Dict, List, Tuple, Optional

# importa i tuoi metodi
# from calcoli import df_tutti, calcola_pianeti_da_df, calcola_asc_mc_case

# --------- Config aspetti & orbi (puoi adattare a tua prassi) ----------
ASPECTS_DEG = {
    "congiunzione": 0,
    "sestile": 60,
    "quadratura": 90,
    "trigono": 120,
    "quincunce": 150,
    "opposizione": 180
}

ORB_MAX = {
    "congiunzione": 8.0,
    "sestile": 4.0,
    "quadratura": 6.0,
    "trigono": 6.0,
    "quincunce": 3.0,
    "opposizione": 8.0
}

PIANETI_BASE = ["Sole","Luna","Mercurio","Venere","Marte","Giove","Saturno","Urano","Nettuno","Plutone"]


# -------------------- helper geometrici --------------------
def _min_delta(a: float, b: float) -> float:
    """Distanza angolare minima in gradi [0, 180]."""
    x = abs((a - b) % 360.0)
    return x if x <= 180 else 360.0 - x

def _match_aspect(delta: float) -> Optional[Tuple[str, float]]:
    """
    Se delta è entro l'orb di un aspetto, ritorna (nome_aspetto, orb),
    dove 'orb' è |delta - aspetto_esatto| in gradi.
    """
    best = None
    best_orb = None
    for nome, deg in ASPECTS_DEG.items():
        orb = abs(delta - deg)
        if orb <= ORB_MAX.get(nome, 0):
            if best_orb is None or orb < best_orb:
                best, best_orb = nome, orb
    return (best, round(best_orb, 3)) if best is not None else None


# -------------------- calcolo tema singolo --------------------
def _tema_statico(dt: datetime,
                  lat: float,
                  lon: float,
                  fuso_orario: float = 0.0,
                  include_node: bool = True,
                  include_lilith: bool = True,
                  sistema_case: str = "equal") -> Dict:
    """
    Restituisce il tema natale/“statico”:
    {
      "data": "YYYY-MM-DD HH:MM",
      "pianeti": { ... , "Ascendente": <°> },
      "asc_mc_case": {... opzionale ...}
    }
    """
    # Pianeti (giornalieri nel tuo metodo; va benissimo per sinastria)
    extra = []
    if include_node:
        extra.append("Nodo")
    if include_lilith:
        extra.append("Lilith")

    pianeti = calcola_pianeti_da_df(
        df_tutti, dt.day, dt.month, dt.year,
        colonne_extra=tuple(extra)
    )

    # Ascendente (usiamo il tuo calcolo; estraiamo ASC in gradi)
    try:
        asc_res = calcola_asc_mc_case(
            dt.year, dt.month, dt.day, dt.hour, dt.minute,
            lat, lon, fuso_orario, sistema_case=sistema_case
        )
        # attesi campi: "ASC" o "Ascendente" e "MC" ecc.
        asc_deg = None
        if isinstance(asc_res, dict):
            asc_deg = asc_res.get("ASC") or asc_res.get("Ascendente")
        if asc_deg is not None:
            pianeti["Ascendente"] = float(asc_deg) % 360.0
        asc_mc_case = asc_res
    except Exception:
        # fallback: niente ascendente se fallisce
        asc_mc_case = None

    return {
        "data": dt.strftime("%Y-%m-%d %H:%M"),
        "pianeti": pianeti,
        "asc_mc_case": asc_mc_case
    }


# -------------------- aspetti incrociati (sinastria) --------------------
def _aspetti_cross(piani_A: Dict[str, float],
                   piani_B: Dict[str, float]) -> List[Dict]:
    """
    Calcola tutti gli aspetti A vs B (no aspetti interni ad A o B).
    Includi Ascendente se presente nei dizionari.
    Output: lista di dict ordinata per orb crescente.
    """
    labels_A = list(piani_A.keys())
    labels_B = list(piani_B.keys())

    out = []
    for p1 in labels_A:
        # filtra eventuali item non numerici
        if not isinstance(piani_A[p1], (int, float)):
            continue
        for p2 in labels_B:
            if not isinstance(piani_B[p2], (int, float)):
                continue
            delta = _min_delta(piani_A[p1], piani_B[p2])
            match = _match_aspect(delta)
            if match:
                tipo, orb = match
                out.append({
                    "chart1": "A",
                    "pianeta1": p1,
                    "chart2": "B",
                    "pianeta2": p2,
                    "tipo": tipo,
                    # mantengo compatibilità con il tuo schema dove delta==orb
                    "delta": orb,
                    "orb": orb
                })

    # ordina per tipo (ordine geometrico) e orb
    out.sort(key=lambda x: (ASPECTS_DEG[x["tipo"]], x["orb"]))
    return out


def sinastria(
    dt_A: datetime, lat_A: float, lon_A: float, fuso_A: float = 0.0,
    dt_B: datetime, lat_B: float, lon_B: float, fuso_B: float = 0.0,
    include_node: bool = True,
    include_lilith: bool = True,
    sistema_case: str = "equal"
) -> Dict:
    """
    Ritorna entrambi i temi (con Ascendente) + aspetti incrociati.
    """
    temaA = _tema_statico(dt_A, lat_A, lon_A, fuso_A, include_node, include_lilith, sistema_case)
    temaB = _tema_statico(dt_B, lat_B, lon_B, fuso_B, include_node, include_lilith, sistema_case)

    aspetti_AB = _aspetti_cross(temaA["pianeti"], temaB["pianeti"])

    return {
        "A": temaA,
        "B": temaB,
        "sinastria": {
            "aspetti_AB": aspetti_AB,
            "conteggio_per_tipo": _count_by_type(aspetti_AB),
            "top_stretti": [a for a in aspetti_AB if a["orb"] <= 2.0]  # utili per highlight
        }
    }


def _count_by_type(aspetti: List[Dict]) -> Dict[str, int]:
    out = {}
    for a in aspetti:
        out[a["tipo"]] = out.get(a["tipo"], 0) + 1
    return out
