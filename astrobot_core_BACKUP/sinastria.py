from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

from .calcoli import (
    df_tutti,
    calcola_pianeti_da_df,
    calcola_asc_mc_case,
    decodifica_segni,
)

ASPECTS_DEG = {
    "congiunzione": 0, "sestile": 60, "quadratura": 90,
    "trigono": 120, "quincunce": 150, "opposizione": 180,
}
ORB_MAX = {
    "congiunzione": 8.0, "sestile": 4.0, "quadratura": 6.0,
    "trigono": 6.0, "quincunce": 3.0, "opposizione": 8.0,
}
PIANETI_BASE = ["Sole","Luna","Mercurio","Venere","Marte","Giove","Saturno","Urano","Nettuno","Plutone"]

SEGNI_IDX = {
    "Ariete":0,"Toro":1,"Gemelli":2,"Cancro":3,"Leone":4,"Vergine":5,
    "Bilancia":6,"Scorpione":7,"Sagittario":8,"Capricorno":9,"Acquario":10,"Pesci":11
}

def _min_delta(a: float, b: float) -> float:
    x = abs((a - b) % 360.0)
    return x if x <= 180 else 360.0 - x

def _match_aspect(delta: float) -> Optional[Tuple[str, float]]:
    best = None; best_orb = None
    for nome, deg in ASPECTS_DEG.items():
        orb = abs(delta - deg)
        if orb <= ORB_MAX.get(nome, 0):
            if best_orb is None or orb < best_orb:
                best, best_orb = nome, orb
    return (best, round(best_orb, 3)) if best is not None else None

# ---------- coercion/normalize ----------
def _coerce_deg(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value) % 360.0
    if isinstance(value, dict):
        # includo anche 'gradi_eclittici' (shape usata dal tuo core)
        for k in ("gradi_eclittici","gradi_assoluti","assoluti","long_abs",
                  "longitudine_assoluta","lambda","long","longitudine","deg",
                  "degrees","value","val"):
            v = value.get(k)
            if isinstance(v, (int, float)):
                return float(v) % 360.0
        # (segno_idx, gradi_segno)
        seg_idx = value.get("segno_idx")
        gs = value.get("gradi_segno") or value.get("grado_segno") or value.get("gradi")
        if isinstance(seg_idx, int) and isinstance(gs, (int, float)):
            return (seg_idx * 30.0 + float(gs)) % 360.0
        # (segno, gradi_segno)
        seg = value.get("segno") or value.get("segno_nome")
        if isinstance(seg, str) and isinstance(gs, (int, float)):
            idx = SEGNI_IDX.get(seg.strip().capitalize())
            if idx is not None:
                return (idx * 30.0 + float(gs)) % 360.0
    return None

def _normalize_pianeti_from_raw(raw: Any) -> Dict[str, float]:
    """Estrae {nome: gradi_assoluti} da molte forme comuni; fallback su decodifica_segni."""
    data = raw

    # lista di record?
    if isinstance(data, (list, tuple)) and data:
        if isinstance(data[0], dict):
            if all(isinstance(x, dict) and "nome" in x for x in data):
                tmp = {}
                for x in data:
                    deg = _coerce_deg(
                        x.get("val") or x.get("value") or x.get("deg") or
                        x.get("long") or x.get("longitudine") or x.get("gradi_eclittici")
                    )
                    if deg is None:
                        deg = _coerce_deg(x.get("gradi") or x.get("gradi_segno"))
                    nome = x.get("nome") or x.get("planet") or x.get("pianeta")
                    if nome and isinstance(deg, (int, float)):
                        tmp[str(nome)] = float(deg)
                return tmp
            data = data[0]

    # dict con chiave 'pianeti'?
    if isinstance(data, dict) and "pianeti" in data and isinstance(data["pianeti"], dict):
        data = data["pianeti"]

    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == "data":
                continue
            deg = _coerce_deg(v)
            if isinstance(deg, (int, float)):
                out[k] = float(deg)

    if out:
        return out

    # fallback: prova a usare decodifica_segni(raw) per ricavare i gradi assoluti
    try:
        decoded = decodifica_segni(raw)
        if isinstance(decoded, dict):
            for k, v in decoded.items():
                if isinstance(k, str) and k.lower() == "data":
                    continue
                if isinstance(v, dict) and "gradi_eclittici" in v:
                    out[k] = float(v["gradi_eclittici"]) % 360.0
    except Exception:
        pass

    return out

def _estrai_ascendente(asc_res: Any) -> Optional[float]:
    if asc_res is None:
        return None
    if isinstance(asc_res, dict):
        val = asc_res.get("ASC", asc_res.get("Ascendente"))
        if isinstance(val, (int, float)):
            return float(val) % 360.0
    elif isinstance(asc_res, (int, float)):
        return float(asc_res) % 360.0
    return None

def _safe_calcola_pianeti(g: int, m: int, a: int, h: int, mi: int) -> Dict[str, float]:
    raw = None
    tries = [
        lambda: calcola_pianeti_da_df(df_tutti, g, m, a, h, mi),
        lambda: calcola_pianeti_da_df(df_tutti, g, m, a),  # senza ora/minuti
        lambda: calcola_pianeti_da_df(df_tutti, g, m, a, h, mi, ("Nodo","Lilith")),
        lambda: calcola_pianeti_da_df(df_tutti, g, m, a, colonne_extra=("Nodo","Lilith")),
    ]
    for t in tries:
        try:
            raw = t()
            if raw is not None:
                break
        except TypeError:
            continue
        except Exception:
            continue
    return _normalize_pianeti_from_raw(raw)

def _tema_statico(dt: datetime, citta: str) -> Dict:
    # pianeti (float -> gradi assoluti)
    pianeti = _safe_calcola_pianeti(dt.day, dt.month, dt.year, dt.hour, dt.minute)

    # ASC/MC/case (può essere dict o float)
    try:
        asc_raw = calcola_asc_mc_case(citta, dt.year, dt.month, dt.day, dt.hour, dt.minute)
    except Exception:
        asc_raw = None

    asc_deg = _estrai_ascendente(asc_raw)
    if isinstance(asc_deg, (int, float)):
        pianeti["Ascendente"] = float(asc_deg)

    # adattamento per decodifica_segni: shape atteso
    pianeti_for_decoding = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in pianeti.items()
        if isinstance(v, (int, float))
    }

    return {
        "data": dt.strftime("%Y-%m-%d %H:%M"),
        "pianeti": pianeti,
        "pianeti_decod": decodifica_segni(pianeti_for_decoding),
        "asc_mc_case": asc_raw,
    }

def _aspetti_cross(A: Dict[str, float], B: Dict[str, float]) -> List[Dict]:
    out: List[Dict] = []
    for p1, v1 in A.items():
        if not isinstance(v1, (int, float)): continue
        for p2, v2 in B.items():
            if not isinstance(v2, (int, float)): continue
            delta = _min_delta(v1, v2)
            match = _match_aspect(delta)
            if match:
                tipo, orb = match
                out.append({
                    "chart1": "A", "pianeta1": p1,
                    "chart2": "B", "pianeta2": p2,
                    "tipo": tipo, "delta": orb, "orb": orb
                })
    out.sort(key=lambda x: (ASPECTS_DEG[x["tipo"]], x["orb"]))
    return out

def _count_by_type(aspetti: List[Dict]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for a in aspetti:
        d[a["tipo"]] = d.get(a["tipo"], 0) + 1
    return d

def sinastria(dt_A: datetime, citta_A: str, dt_B: datetime, citta_B: str) -> Dict:
    temaA = _tema_statico(dt_A, citta_A)
    temaB = _tema_statico(dt_B, citta_B)
    aspetti_AB = _aspetti_cross(temaA["pianeti"], temaB["pianeti"])
    return {
        "A": temaA,
        "B": temaB,
        "sinastria": {
            "aspetti_AB": aspetti_AB,
            "conteggio_per_tipo": _count_by_type(aspetti_AB),
            "top_stretti": [a for a in aspetti_AB if a["orb"] <= 2.0]
        }
    }
