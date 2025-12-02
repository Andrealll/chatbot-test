from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from .calcoli import (
    df_tutti,
    calcola_pianeti_da_df,
    calcola_asc_mc_case,
    decodifica_segni,
)
from .transiti_pesatura import calcola_score_definitivo_aspetto  # NEW: scoring transiti+natal

ASPECTS_DEG = {
    "congiunzione": 0,
    "sestile": 60,
    "quadratura": 90,
    "trigono": 120,
    "quincunce": 150,
    "opposizione": 180,
}
ORB_MAX = {
    "congiunzione": 8.0,
    "sestile": 4.0,
    "quadratura": 6.0,
    "trigono": 6.0,
    "quincunce": 3.0,
    "opposizione": 8.0,
}
PIANETI_BASE = [
    "Sole",
    "Luna",
    "Mercurio",
    "Venere",
    "Marte",
    "Giove",
    "Saturno",
    "Urano",
    "Nettuno",
    "Plutone",
]

SEGNI_IDX = {
    "Ariete": 0,
    "Toro": 1,
    "Gemelli": 2,
    "Cancro": 3,
    "Leone": 4,
    "Vergine": 5,
    "Bilancia": 6,
    "Scorpione": 7,
    "Sagittario": 8,
    "Capricorno": 9,
    "Acquario": 10,
    "Pesci": 11,
}

# --- polarità aspetti / pianeti ----------------------------------------------

ASPECT_POLARITY: Dict[str, float] = {
    "congiunzione": 0.6,
    "trigono": 0.9,
    "sestile": 0.7,
    "quadratura": -0.9,
    "opposizione": -0.8,
    "quincunce": -0.4,
}

PLANET_POLARITY_BASE: Dict[str, float] = {
    "Giove": 1.0,
    "Venere": 1.0,
    "Sole": 0.6,
    "Luna": 0.5,
    "Mercurio": 0.2,
    "Marte": -0.3,
    "Saturno": -0.7,
    "Urano": 0.0,
    "Nettuno": 0.0,
    "Plutone": -0.6,
    # opzionale: Nodo/Lilith/Asc a 0.0 se serve
}


def _calcola_polarita_aspetto(transit_planet: str, aspect_type: str) -> float:
    """
    Restituisce una polarità tra -1.0 e +1.0 in base al tipo di aspetto e
    alla natura del pianeta di transito.
    """
    base_asp = ASPECT_POLARITY.get(aspect_type, 0.0)
    base_pl = PLANET_POLARITY_BASE.get(transit_planet, 0.0)
    raw = base_asp + base_pl
    if raw > 1.0:
        return 1.0
    if raw < -1.0:
        return -1.0
    return raw


# ---------- util gradi/aspetti ------------------------------------------------

def _min_delta(a: float, b: float) -> float:
    x = abs((a - b) % 360.0)
    return x if x <= 180 else 360.0 - x


def _match_aspect(delta: float) -> Optional[Tuple[str, float]]:
    best = None
    best_orb = None
    for nome, deg in ASPECTS_DEG.items():
        orb = abs(delta - deg)
        if orb <= ORB_MAX.get(nome, 0):
            if best_orb is None or orb < best_orb:
                best, best_orb = nome, orb
    return (best, round(best_orb, 3)) if best is not None else None


# ---------- coercion/normalize ------------------------------------------------

def _coerce_deg(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value) % 360.0
    if isinstance(value, dict):
        # gradi assoluti diretti
        for k in (
            "gradi_eclittici",
            "gradi_assoluti",
            "assoluti",
            "long_abs",
            "longitudine_assoluta",
            "lambda",
            "long",
            "longitudine",
            "deg",
            "degrees",
            "value",
            "val",
        ):
            v = value.get(k)
            if isinstance(v, (int, float)):
                return float(v) % 360.0
        # (segno_idx, gradi_segno)
        seg_idx = value.get("segno_idx")
        gs = (
            value.get("gradi_segno")
            or value.get("grado_segno")
            or value.get("gradi")
        )
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
    """Estrae {nome: gradi_assoluti} da molte forme comuni."""
    data = raw
    # lista di record?
    if isinstance(data, (list, tuple)) and data:
        if isinstance(data[0], dict):
            if all(isinstance(x, dict) and "nome" in x for x in data):
                tmp: Dict[str, float] = {}
                for x in data:
                    deg = _coerce_deg(
                        x.get("val")
                        or x.get("value")
                        or x.get("deg")
                        or x.get("long")
                        or x.get("longitudine")
                        or x.get("gradi_eclittici")
                    )
                    if deg is None:
                        deg = _coerce_deg(
                            x.get("gradi") or x.get("gradi_segno")
                        )
                    nome = x.get("nome") or x.get("planet") or x.get("pianeta")
                    if nome and isinstance(deg, (int, float)):
                        tmp[str(nome)] = float(deg)
                return tmp
            data = data[0]

    # dict con chiave 'pianeti'?
    if isinstance(data, dict) and "pianeti" in data and isinstance(
        data["pianeti"], dict
    ):
        data = data["pianeti"]

    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == "data":
                continue
            deg = _coerce_deg(v)
            if isinstance(deg, (int, float)):
                out[k] = float(deg)
    return out


def _estrai_ascendente(asc_res: Any) -> Optional[float]:
    if asc_res is None:
        return None
    if isinstance(asc_res, dict):
        v = asc_res.get("ASC", asc_res.get("Ascendente"))
        if isinstance(v, (int, float)):
            return float(v) % 360.0
    elif isinstance(asc_res, (int, float)):
        return float(asc_res) % 360.0
    return None


# ---------- pianeti robusti: DF -----------------------------------------------

def _safe_calcola_pianeti(
    giorno: int,
    mese: int,
    anno: int,
    ora: int,
    minuti: int,
    include_node: bool,
    include_lilith: bool,
) -> Dict[str, float]:
    """
    Calcola le posizioni planetarie usando df_tutti / calcola_pianeti_da_df
    in modo robusto. Questo è la base per TUTTI i casi non giornalieri
    (settimana/mese/anno) e come fallback quando l'API non è disponibile.
    """
    raw = None

    # 1) tentativi classici
    tries = [
        lambda: calcola_pianeti_da_df(
            df_tutti, giorno, mese, anno, ora, minuti
        ),
        lambda: calcola_pianeti_da_df(df_tutti, giorno, mese, anno),
        lambda: calcola_pianeti_da_df(
            df_tutti,
            giorno,
            mese,
            anno,
            ora,
            minuti,
            (
                "Nodo" if include_node else None,
                "Lilith" if include_lilith else None,
            ),
        ),
        lambda: calcola_pianeti_da_df(
            df_tutti,
            giorno,
            mese,
            anno,
            colonne_extra=tuple(
                [
                    x
                    for x in ("Nodo", "Lilith")
                    if (x == "Nodo" and include_node)
                    or (x == "Lilith" and include_lilith)
                ]
            ),
        ),
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

    # 2) normalizzazione diretta
    m = _normalize_pianeti_from_raw(raw)
    if m:
        return m

    # 3) fallback: prova a decodificare e re-estrarre i gradi assoluti
    try:
        decoded = decodifica_segni(raw)
        if isinstance(decoded, dict):
            out: Dict[str, float] = {}
            for k, v in decoded.items():
                if isinstance(k, str) and k.lower() == "data":
                    continue
                if isinstance(v, dict) and "gradi_eclittici" in v:
                    out[k] = float(v["gradi_eclittici"]) % 360.0
            if out:
                return out
    except Exception:
        pass

    return {}


# ---------- pianeti via API (per uso giornaliero) -----------------------------

def _calcola_pianeti_api(
    giorno: int,
    mese: int,
    anno: int,
    ora: int,
    minuti: int,
    include_node: bool,
    include_lilith: bool,
) -> Dict[str, float]:
    """
    Tenta di usare una funzione 'calcola_pianeti_api' definita in .calcoli
    (o altrove) per ottenere posizioni planetarie ad alta risoluzione
    (data+ora). Se non disponibile o se qualcosa va storto, fallback su DF.

    Nota: questo è pensato per gli use case GIORNALIERI (oggi / stasera / domani).
    """
    try:
        # Se non esiste, scatena ImportError e facciamo fallback
        from .calcoli import calcola_pianeti_api  # type: ignore
    except Exception:
        # fallback sul DF
        return _safe_calcola_pianeti(
            giorno, mese, anno, ora, minuti, include_node, include_lilith
        )

    raw = None
    # cerchiamo di essere tolleranti sulla firma
    try:
        # firma ipotetica più esplicita
        raw = calcola_pianeti_api(
            anno=anno,
            mese=mese,
            giorno=giorno,
            ora=ora,
            minuti=minuti,
            include_node=include_node,
            include_lilith=include_lilith,
        )
    except TypeError:
        try:
            # firma alternativa: (giorno, mese, anno, ora, minuti, ...)
            raw = calcola_pianeti_api(
                giorno, mese, anno, ora, minuti, include_node, include_lilith
            )
        except Exception:
            raw = None
    except Exception:
        raw = None

    m = _normalize_pianeti_from_raw(raw)
    if m:
        return m

    # se l'API non torna niente di sensato, usiamo comunque il DF
    return _safe_calcola_pianeti(
        giorno, mese, anno, ora, minuti, include_node, include_lilith
    )


# ---------- aspetti -----------------------------------------------------------

def _calcola_aspetti(
    long_pianeti: Dict[str, float],
    include_node: bool = True,
    include_lilith: bool = True,
) -> List[Dict]:
    labels: List[str] = []
    for p in PIANETI_BASE:
        if p in long_pianeti:
            labels.append(p)
    if include_node and "Nodo" in long_pianeti:
        labels.append("Nodo")
    if include_lilith and "Lilith" in long_pianeti:
        labels.append("Lilith")
    if "Ascendente" in long_pianeti:
        labels.append("Ascendente")

    out: List[Dict] = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            p1, p2 = labels[i], labels[j]
            v1, v2 = long_pianeti.get(p1), long_pianeti.get(p2)
            if not isinstance(v1, (int, float)) or not isinstance(
                v2, (int, float)
            ):
                continue
            delta = _min_delta(v1, v2)
            match = _match_aspect(delta)
            if match:
                tipo, orb = match
                out.append(
                    {
                        "pianeta1": p1,
                        "pianeta2": p2,
                        "tipo": tipo,
                        "delta": orb,
                        "orb": orb,
                    }
                )
    out.sort(key=lambda x: (ASPECTS_DEG[x["tipo"]], x["orb"]))
    return out


# ---------- API base: transiti in data fissa (DF) -----------------------------

def calcola_transiti_data_fissa(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    citta: Optional[str] = None,
    include_node: bool = True,
    include_lilith: bool = True,
) -> Dict:
    dt = datetime(anno, mese, giorno, ora, minuti)

    # pianeti robusti (DF)
    long_pianeti = _safe_calcola_pianeti(
        giorno, mese, anno, ora, minuti, include_node, include_lilith
    )

    # ascendente opzionale
    asc_res = None
    if citta:
        try:
            asc_res = calcola_asc_mc_case(
                citta, anno, mese, giorno, ora, minuti
            )
            asc_deg = _estrai_ascendente(asc_res)
            if isinstance(asc_deg, (int, float)):
                long_pianeti["Ascendente"] = float(asc_deg)
        except Exception:
            asc_res = None

    # aspetti
    aspetti = _calcola_aspetti(
        long_pianeti, include_node=include_node, include_lilith=include_lilith
    )

    # adattamento per decodifica_segni: shape atteso
    pianeti_for_decoding = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in long_pianeti.items()
        if isinstance(v, (int, float))
    }

    return {
        "data": dt.strftime("%Y-%m-%d %H:%M"),
        "asc_mc_case": asc_res,
        "pianeti": long_pianeti,
        "pianeti_decod": decodifica_segni(pianeti_for_decoding),
        "aspetti": aspetti,
    }


def _aspect_key(a: Dict) -> Tuple[str, str, str]:
    p1, p2 = a["pianeta1"], a["pianeta2"]
    return (p1, p2, a["tipo"]) if p1 < p2 else (p2, p1, a["tipo"])


def transiti_su_due_date(
    dt_start: datetime,
    dt_end: datetime,
    include_node: bool = True,
    include_lilith: bool = True,
) -> Dict:
    if dt_end < dt_start:
        dt_start, dt_end = dt_end, dt_start

    t1 = calcola_transiti_data_fissa(
        dt_start.day,
        dt_start.month,
        dt_start.year,
        dt_start.hour,
        dt_start.minute,
        include_node=include_node,
        include_lilith=include_lilith,
    )
    t2 = calcola_transiti_data_fissa(
        dt_end.day,
        dt_end.month,
        dt_end.year,
        dt_end.hour,
        dt_end.minute,
        include_node=include_node,
        include_lilith=include_lilith,
    )

    a1, a2 = t1["aspetti"], t2["aspetti"]
    m1 = {_aspect_key(a): a for a in a1}
    m2 = {_aspect_key(a): a for a in a2}

    k1, k2 = set(m1.keys()), set(m2.keys())
    persistono_keys = k1 & k2
    entrano_keys = k2 - k1
    escono_keys = k1 - k2

    persistono = []
    for k in sorted(persistono_keys):
        a_start, a_end = m1[k], m2[k]
        persistono.append(
            {
                "pianeta1": min(a_end["pianeta1"], a_end["pianeta2"]),
                "pianeta2": max(a_end["pianeta1"], a_end["pianeta2"]),
                "tipo": a_end["tipo"],
                "orb_inizio": a_start["orb"],
                "orb_fine": a_end["orb"],
                "variazione_orb": round(a_end["orb"] - a_start["orb"], 3),
            }
        )

    def _fmt(keys, src):
        out = []
        for k in sorted(keys):
            a = src[k]
            out.append(
                {
                    "pianeta1": a["pianeta1"],
                    "pianeta2": a["pianeta2"],
                    "tipo": a["tipo"],
                    "orb": a["orb"],
                }
            )
        return out

    entrano = _fmt(entrano_keys, m2)
    escono = _fmt(escono_keys, m1)

    return {
        "intervallo": {"inizio": t1["data"], "fine": t2["data"]},
        "inizio": t1,
        "fine": t2,
        "differenze": {
            "persistono": sorted(
                persistono,
                key=lambda x: (ASPECTS_DEG[x["tipo"]], abs(x["variazione_orb"])),
            ),
            "entrano": sorted(
                entrano, key=lambda x: (ASPECTS_DEG[x["tipo"]], x["orb"])
            ),
            "escono": sorted(
                escono, key=lambda x: (ASPECTS_DEG[x["tipo"]], x["orb"])
            ),
        },
    }


# ====== TRANSITI VS NATALE ====================================================

def _labels_for(
    m: Dict[str, float],
    include_node: bool,
    include_lilith: bool,
) -> List[str]:
    labels: List[str] = [p for p in PIANETI_BASE if p in m]
    if include_node and "Nodo" in m:
        labels.append("Nodo")
    if include_lilith and "Lilith" in m:
        labels.append("Lilith")
    if "Ascendente" in m:
        labels.append("Ascendente")
    return labels


def _trova_aspetti_transito(
    natal: Dict[str, float],
    transito: Dict[str, float],
    include_node: bool = True,
    include_lilith: bool = True,
    filtra_transito: Optional[List[str]] = None,
    filtra_natal: Optional[List[str]] = None,
    use_case: str = "daily",
    profilo_natale: Optional[Dict[str, float]] = None,
) -> List[Dict]:
    """
    Assegna aspetti tra ogni pianeta di transito e ogni pianeta del tema natale,
    calcolando anche score di rilevanza (intensità transito * fattore natale).
    """
    lab_tr = _labels_for(transito, include_node, include_lilith)
    lab_na = _labels_for(natal, include_node, include_lilith)

    if filtra_transito:
        lab_tr = [x for x in lab_tr if x in filtra_transito]
    if filtra_natal:
        lab_na = [x for x in lab_na if x in filtra_natal]

    out: List[Dict] = []
    for pt in lab_tr:
        vtr = transito.get(pt)
        if not isinstance(vtr, (int, float)):
            continue
        for pn in lab_na:
            vna = natal.get(pn)
            if not isinstance(vna, (int, float)):
                continue
            delta = _min_delta(vtr, vna)
            m = _match_aspect(delta)
            if not m:
                continue
            tipo, orb = m

            pol = _calcola_polarita_aspetto(pt, tipo)

            # nuovo: score definitivo (transito + fattore natale)
            score_info = calcola_score_definitivo_aspetto(
                use_case=use_case,
                pianeta_transito=pt,
                pianeta_natale=pn,
                aspetto_tipo=tipo,
                orb=orb,
                polarita=pol,
                profilo_natale=profilo_natale,
            )

            out.append(
                {
                    "transito": pt,
                    "natal": pn,
                    "tipo": tipo,
                    "delta": round(delta, 3),  # separazione angolare
                    "orb": round(orb, 3),  # scostamento dall'aspetto perfetto
                    "long_transito": round(vtr, 4),
                    "long_natal": round(vna, 4),
                    "polarita": pol,
                    "intensita_base": round(score_info["intensita_base"], 6),
                    "fattore_natale": round(score_info["fattore_natale"], 6),
                    "score": round(score_info["score_definitivo"], 6),
                }
            )
    # ordina per score decrescente, poi geometria
    out.sort(
        key=lambda a: (
            -a["score"],
            ASPECTS_DEG[a["tipo"]],
            a["orb"],
            a["transito"],
            a["natal"],
        )
    )
    return out


# ---------- Tema natale riutilizzabile (per pipeline oroscopo) ----------------

def prepara_tema_natale(
    citta: str,
    data_nascita: str,  # "YYYY-MM-DD"
    ora_nascita: str,  # "HH:MM"
    include_node: bool = True,
    include_lilith: bool = True,
) -> Dict:
    """
    Calcola UNA VOLTA il tema natale completo (pianeti, asc_mc_case, decodifica)
    e restituisce un contesto riutilizzabile per molte chiamate di transiti.

    Questo evita di ricalcolare il tema per ogni snapshot (giornaliero premium,
    settimanale, mensile, annuale, ecc.).
    """
    dn = datetime.strptime(f"{data_nascita} {ora_nascita}", "%Y-%m-%d %H:%M")

    # pianeti natali (DF: per il tema va benissimo)
    natal_long = _safe_calcola_pianeti(
        dn.day, dn.month, dn.year, dn.hour, dn.minute, include_node, include_lilith
    )

    # ascendente natale
    asc_res = None
    try:
        asc_res = calcola_asc_mc_case(
            citta, dn.year, dn.month, dn.day, dn.hour, dn.minute
        )
        asc_deg = _estrai_ascendente(asc_res)
        if isinstance(asc_deg, (int, float)):
            natal_long["Ascendente"] = float(asc_deg)
    except Exception:
        asc_res = None

    # per decodifica
    natal_for_dec = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in natal_long.items()
        if isinstance(v, (int, float))
    }
    natal_decod = decodifica_segni(natal_for_dec)

    return {
        "input": {
            "citta": citta,
            "data_nascita": data_nascita,
            "ora_nascita": ora_nascita,
            "include_node": include_node,
            "include_lilith": include_lilith,
        },
        "natal": {
            "pianeti": natal_long,
            "pianeti_decod": natal_decod,
            "asc_mc_case": asc_res,
            "data": dn.strftime("%Y-%m-%d %H:%M"),
        },
    }


def transiti_vs_tema_precalc(
    tema_ctx: Dict,
    quando: datetime,
    include_node: bool = True,
    include_lilith: bool = True,
    filtra_transito: Optional[List[str]] = None,
    filtra_natal: Optional[List[str]] = None,
    usa_api_transiti: bool = False,
    use_case: str = "daily",
    profilo_natale: Optional[Dict[str, float]] = None,
) -> Dict:
    """
    Variante di transiti_vs_natal_in_data che RIUSA un tema già calcolato
    tramite prepara_tema_natale, invece di ricalcolarlo ogni volta.

    Se usa_api_transiti=True, prova a usare l'API per i pianeti di transito
    (altrimenti usa il DF come sempre).

    use_case: "daily" | "weekly" | "monthly" | "yearly"
    profilo_natale: dict {pianeta_natale: fattore_natale}, opzionale.
    """
    natal_block = tema_ctx["natal"]
    natal_long = dict(natal_block.get("pianeti", {}))
    asc_res = natal_block.get("asc_mc_case")
    birth_info = tema_ctx.get("input", {})

    # transiti in 'quando'
    if usa_api_transiti:
        tr = _calcola_pianeti_api(
            quando.day,
            quando.month,
            quando.year,
            quando.hour,
            quando.minute,
            include_node,
            include_lilith,
        )
    else:
        tr = _safe_calcola_pianeti(
            quando.day,
            quando.month,
            quando.year,
            quando.hour,
            quando.minute,
            include_node,
            include_lilith,
        )

    # aspetti transito -> natale (con score)
    aspetti = _trova_aspetti_transito(
        natal=natal_long,
        transito=tr,
        include_node=include_node,
        include_lilith=include_lilith,
        filtra_transito=filtra_transito,
        filtra_natal=filtra_natal,
        use_case=use_case,
        profilo_natale=profilo_natale,
    )

    # formati per decodifica transiti
    tr_for_dec = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in tr.items()
        if isinstance(v, (int, float))
    }
    tr_decod = decodifica_segni(tr_for_dec)

    # piccolo riassunto
    cnt: Dict[str, int] = {}
    for a in aspetti:
        cnt[a["tipo"]] = cnt.get(a["tipo"], 0) + 1

    return {
        "input": {
            "natal": {
                "citta": birth_info.get("citta"),
                "data": birth_info.get("data_nascita"),
                "ora": birth_info.get("ora_nascita"),
            },
            "quando": quando.strftime("%Y-%m-%d %H:%M"),
            "include_node": include_node,
            "include_lilith": include_lilith,
            "filtra_transito": filtra_transito,
            "filtra_natal": filtra_natal,
            "use_case": use_case,
        },
        "natal": natal_block,
        "transito": {
            "pianeti": tr,
            "pianeti_decod": tr_decod,
            "data": quando.strftime("%Y-%m-%d %H:%M"),
        },
        "aspetti": aspetti,
        "riassunto": {"conteggio_aspetti": cnt},
    }


def transiti_vs_natal_in_data(
    citta: str,
    data_nascita: str,  # "YYYY-MM-DD"
    ora_nascita: str,  # "HH:MM"
    quando: datetime,  # data/ora dei transiti
    include_node: bool = True,
    include_lilith: bool = True,
    filtra_transito: Optional[List[str]] = None,
    filtra_natal: Optional[List[str]] = None,
    use_case: str = "daily",
    profilo_natale: Optional[Dict[str, float]] = None,
) -> Dict:
    """
    Confronta i pianeti di transito in 'quando' con il tema natale fornito.

    Usa il DF sia per il tema natale sia per i transiti. Per gli use case
    che richiedono MOLTI snapshot (settimanale/mensile/annuale) puoi
    usare invece prepara_tema_natale + transiti_vs_tema_precalc().

    use_case: "daily" | "weekly" | "monthly" | "yearly"
    profilo_natale: dict {pianeta_natale: fattore_natale}, opzionale.
    """
    # parse nascita
    dn = datetime.strptime(f"{data_nascita} {ora_nascita}", "%Y-%m-%d %H:%M")

    # tema natale (DF)
    natal_long = _safe_calcola_pianeti(
        dn.day, dn.month, dn.year, dn.hour, dn.minute, include_node, include_lilith
    )

    # ascendente natale
    asc_res = None
    try:
        asc_res = calcola_asc_mc_case(
            citta, dn.year, dn.month, dn.day, dn.hour, dn.minute
        )
        asc_deg = _estrai_ascendente(asc_res)
        if isinstance(asc_deg, (int, float)):
            natal_long["Ascendente"] = float(asc_deg)
    except Exception:
        asc_res = None

    # transiti in 'quando' (DF)
    tr = _safe_calcola_pianeti(
        quando.day,
        quando.month,
        quando.year,
        quando.hour,
        quando.minute,
        include_node,
        include_lilith,
    )

    # aspetti transito -> natale (con score)
    aspetti = _trova_aspetti_transito(
        natal=natal_long,
        transito=tr,
        include_node=include_node,
        include_lilith=include_lilith,
        filtra_transito=filtra_transito,
        filtra_natal=filtra_natal,
        use_case=use_case,
        profilo_natale=profilo_natale,
    )

    # formati "decodifica"
    natal_for_dec = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in natal_long.items()
        if isinstance(v, (int, float))
    }
    tr_for_dec = {
        k: {"gradi_eclittici": float(v), "retrogrado": False}
        for k, v in tr.items()
        if isinstance(v, (int, float))
    }

    # piccolo riassunto
    cnt: Dict[str, int] = {}
    for a in aspetti:
        cnt[a["tipo"]] = cnt.get(a["tipo"], 0) + 1

    return {
        "input": {
            "natal": {
                "citta": citta,
                "data": data_nascita,
                "ora": ora_nascita,
            },
            "quando": quando.strftime("%Y-%m-%d %H:%M"),
            "include_node": include_node,
            "include_lilith": include_lilith,
            "filtra_transito": filtra_transito,
            "filtra_natal": filtra_natal,
            "use_case": use_case,
        },
        "natal": {
            "pianeti": natal_long,
            "pianeti_decod": decodifica_segni(natal_for_dec),
            "asc_mc_case": asc_res,
            "data": dn.strftime("%Y-%m-%d %H:%M"),
        },
        "transito": {
            "pianeti": tr,
            "pianeti_decod": decodifica_segni(tr_for_dec),
            "data": quando.strftime("%Y-%m-%d %H:%M"),
        },
        "aspetti": aspetti,
        "riassunto": {"conteggio_aspetti": cnt},
    }


# ---------- GIORNALIERO: nuovo transiti_oggi con API per transiti -------------

def transiti_oggi(
    citta: str,
    data_nascita: str,  # "YYYY-MM-DD"
    ora_nascita: str,  # "HH:MM"
    include_node: bool = True,
    include_lilith: bool = True,
    filtra_transito: Optional[List[str]] = None,
    filtra_natal: Optional[List[str]] = None,
) -> Dict:
    """
    Comodità: transiti 'di oggi' a mezzogiorno ora locale (come prima),
    MA usando l'API per i pianeti di transito se disponibile.

    - Tema natale: calcolato UNA volta (DF) tramite prepara_tema_natale.
    - Transiti: calcolati via _calcola_pianeti_api() se la funzione
      calcola_pianeti_api è definita in .calcoli, altrimenti fallback DF.

    Questo è lo strumento ideale per gli use case giornalieri; per gli
    altri periodi (settimanale/mensile/annuale) conviene usare DF + pipeline.
    """
    # Europe/Rome = UTC+1 in inverno, +2 in estate; qui rimaniamo coerenti
    # con la logica precedente assumendo che datetime.now() sia già locale.
    now_local = datetime.now().replace(
        hour=12, minute=0, second=0, microsecond=0
    )

    # calcola tema natale una volta
    tema_ctx = prepara_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        include_node=include_node,
        include_lilith=include_lilith,
    )

    # usa l'API per i transiti (se disponibile), altrimenti DF
    return transiti_vs_tema_precalc(
        tema_ctx=tema_ctx,
        quando=now_local,
        include_node=include_node,
        include_lilith=include_lilith,
        filtra_transito=filtra_transito,
        filtra_natal=filtra_natal,
        usa_api_transiti=True,
        use_case="daily",
        profilo_natale=None,  # se vuoi usare il profilo natale, passalo da fuori
    )
# ==============================================================================
