# routes_oroscopo.py

from datetime import date, datetime, timedelta
from typing import Optional, Literal, Dict, Any, List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from astrobot_core.transiti import (
    calcola_transiti_data_fissa,
    transiti_vs_natal_in_data,
)
from astrobot_core.transiti_pesatura import (
    calcola_intensita_aspetto,
    calcola_intensita_posizione,
)

router = APIRouter(
    prefix="/oroscopo",
    tags=["oroscopo"],
)

# ==========================
# COSTANTI / HELPER
# ==========================

ScopeType = Literal["daily", "weekly", "monthly", "yearly"]

DOMAINS = ["energy", "emotions", "relationships", "work", "luck"]

# mapping molto semplice pianeta -> domini toccati
PLANET_TO_DOMAINS: Dict[str, List[str]] = {
    "Sole": ["energy", "work"],
    "Luna": ["emotions", "relationships"],
    "Mercurio": ["work", "energy"],
    "Venere": ["relationships", "emotions"],
    "Marte": ["energy", "relationships"],
    "Giove": ["luck", "energy"],
    "Saturno": ["work"],
    "Urano": ["work", "energy"],
    "Nettuno": ["emotions", "luck"],
    "Plutone": ["energy", "luck"],
    "Nodo": ["relationships", "luck"],
    "Nodo Nord": ["relationships", "luck"],
    "Nodo Sud": ["relationships", "luck"],
    "Lilith": ["emotions", "relationships"],
}


def _build_date_series(scope: ScopeType, base_date: date) -> List[date]:
    """Costruisce la serie di date in base allo scope richiesto."""
    if scope == "daily":
        return [base_date]
    if scope == "weekly":
        # 7 giorni a partire dalla data indicata (es. lunedì)
        return [base_date + timedelta(days=i) for i in range(7)]
    if scope == "monthly":
        # 30 giorni centrati sulla data indicata
        start = base_date - timedelta(days=14)
        return [start + timedelta(days=i) for i in range(30)]
    if scope == "yearly":
        # 12 punti (circa mensili) a partire dall'inizio dell'anno
        start = date(base_date.year, 1, 1)
        return [start + timedelta(days=30 * i) for i in range(12)]
    # fallback di sicurezza
    return [base_date]


def _use_case_for_scope(scope: ScopeType) -> str:
    """Mappa lo scope API sullo use_case atteso da transiti_pesatura."""
    if scope in ("daily", "weekly"):
        return "daily"
    if scope == "monthly":
        return "monthly"
    return "yearly"


def _norm_intensity_series(raw_series: List[Dict[str, float]]) -> Dict[str, List[float]]:
    """Normalizza le intensità 0..1 su tutti i domini e tutte le date."""
    if not raw_series:
        return {d: [] for d in DOMAINS}

    max_val = 0.0
    for day in raw_series:
        for d in DOMAINS:
            v = float(day.get(d, 0.0))
            if v > max_val:
                max_val = v

    if max_val <= 0.0:
        # fallback piattone 0.5 se non c'è contrasto
        n = len(raw_series)
        return {d: [0.5] * n for d in DOMAINS}

    out: Dict[str, List[float]] = {d: [] for d in DOMAINS}
    for day in raw_series:
        for d in DOMAINS:
            v = float(day.get(d, 0.0)) / max_val
            if v < 0.0:
                v = 0.0
            if v > 1.0:
                v = 1.0
            out[d].append(v)
    return out


def _intensita_da_transiti(
    scope: ScopeType,
    payload: "OroscopoRequest",
    quando: datetime,
) -> Dict[str, float]:
    """Calcola l'intensità grezza per ciascun dominio in una singola data.

    Se sono presenti data_nascita + ora_nascita nel payload, usa i transiti
    rispetto al tema natale personale (transiti_vs_natal_in_data).

    Altrimenti usa solo la configurazione generale dei pianeti in cielo
    (calcola_transiti_data_fissa).
    """
    use_case = _use_case_for_scope(scope)

    # 1) Otteniamo pianeti + aspetti per 'quando'
    aspetti: List[Dict[str, Any]]
    pianeti_transito: Dict[str, float]

    if payload.data_nascita and payload.ora_nascita:
        # transiti rispetto al tema natale
        res = transiti_vs_natal_in_data(
            citta=payload.citta,
            data_nascita=payload.data_nascita,
            ora_nascita=payload.ora_nascita,
            quando=quando,
            include_node=True,
            include_lilith=True,
            filtra_transito=None,
            filtra_natal=None,
        )
        aspetti = res.get("aspetti", []) or []
        pianeti_transito = (res.get("transito", {}) or {}).get("pianeti", {}) or {}
    else:
        # solo configurazione generale dei pianeti in cielo
        res = calcola_transiti_data_fissa(
            giorno=quando.day,
            mese=quando.month,
            anno=quando.year,
            ora=quando.hour,
            minuti=quando.minute,
            citta=payload.citta,
            include_node=True,
            include_lilith=True,
        )
        aspetti = res.get("aspetti", []) or []
        pianeti_transito = res.get("pianeti", {}) or {}

    # 2) accumuliamo intensità per dominio
    dom_vals: Dict[str, float] = {d: 0.0 for d in DOMAINS}

    # 2a) contributo aspetti
    for asp in aspetti:
        # transiti_vs_natal: chiave 'transito'
        # calcola_transiti_data_fissa: chiave 'pianeta1'/'pianeta2'
        pt = asp.get("transito") or asp.get("pianeta1")
        if not isinstance(pt, str):
            continue
        tipo = asp.get("tipo")
        if not isinstance(tipo, str):
            continue
        orb = float(asp.get("orb", asp.get("delta", 2.0)))
        polarita = asp.get("polarita")
        if isinstance(polarita, (int, float)):
            pol_val = float(polarita)
        else:
            pol_val = None

        try:
            base_int = calcola_intensita_aspetto(
                use_case=use_case,
                pianeta_transito=pt,
                aspetto_tipo=tipo,
                orb=orb,
                polarita=pol_val,
            )
        except Exception:
            continue

        if base_int <= 0:
            continue

        for dom in PLANET_TO_DOMAINS.get(pt, []):
            dom_vals[dom] += base_int

    # 2b) contributo "posizione generale" dei pianeti (anche senza aspetti)
    for pt, lon in pianeti_transito.items():
        if not isinstance(pt, str):
            continue
        if not isinstance(lon, (int, float)):
            continue

        try:
            base_int = calcola_intensita_posizione(
                use_case=use_case,
                pianeta_transito=pt,
                tipo_config="generale",
            )
        except Exception:
            continue

        if base_int <= 0:
            continue

        for dom in PLANET_TO_DOMAINS.get(pt, []):
            dom_vals[dom] += base_int

    return dom_vals


# ==========================
# MODELLI
# ==========================


class OroscopoRequest(BaseModel):
    """Richiesta oroscopo.

    Campi aggiuntivi opzionali:
    - data_nascita / ora_nascita: se presenti, l'oroscopo è personalizzato
      rispetto al tema natale; altrimenti è "generale" (solo cielo del giorno).
    """
    citta: str
    data: date              # data di riferimento (oggi per daily, inizio periodo per gli altri)
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"

    # opzionali per transiti personalizzati
    data_nascita: Optional[str] = None   # "YYYY-MM-DD"
    ora_nascita: Optional[str] = None    # "HH:MM"


class OroscopoResponse(BaseModel):
    status: str
    scope: ScopeType
    engine: Literal["legacy", "new"]
    input: Dict[str, Any]
    result: Dict[str, Any]


# ==========================
# MOTORI (LEGACY + NEW)
# ==========================


def calcola_oroscopo_legacy(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """Stub per motore legacy (backward compat)."""
    return {
        "engine_version": "legacy",
        "scope": scope,
        "note": "Motore legacy non ancora collegato (stub).",
    }


def calcola_oroscopo_new(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """Motore NEW basato su transiti + transiti_pesatura.

    - costruisce una serie di date in base a `scope` e `payload.data`
    - per ogni data calcola:
        * transiti (eventualmente vs tema natale personale)
        * intensità grezza per 5 domini
    - normalizza 0..1 e genera un grafico a linee via frontend
      (qui ritorniamo solo i dati, il grafico PNG lo genera /transiti/premium).
    """
    base_date = payload.data
    date_list = _build_date_series(scope, base_date)
    when_list = [
        datetime(d.year, d.month, d.day, 12, 0)
        for d in date_list
    ]

    raw_series: List[Dict[str, float]] = []
    for when in when_list:
        dom_vals = _intensita_da_transiti(scope, payload, when)
        raw_series.append(dom_vals)

    intensities_norm = _norm_intensity_series(raw_series)
    date_strings = [d.isoformat() for d in date_list]

    return {
        "engine_version": "new",
        "scope": scope,
        "personalizzato": bool(payload.data_nascita and payload.ora_nascita),
        "meta": {
            "citta": payload.citta,
            "nome": payload.nome,
            "email": payload.email,
            "domanda": payload.domanda,
            "data_riferimento": base_date.isoformat(),
        },
        "dates": date_strings,
        "intensities": intensities_norm,
    }


# ==========================
# ROUTE UNICA /oroscopo/{scope}
# ==========================


@router.post("/{scope}", response_model=OroscopoResponse)
async def oroscopo_endpoint(
    scope: ScopeType,
    payload: OroscopoRequest,
    x_engine: Optional[str] = Header(default=None, alias="X-Engine"),
):
    """Endpoint oroscopo:

    - scope: daily | weekly | monthly | yearly
    - X-Engine:
        * "new" -> usa il motore nuovo (transiti + pesatura)
        * assente -> motore legacy (stub)
    """
    engine_flag = (x_engine or "").lower().strip()
    if engine_flag not in ("", "new"):
        raise HTTPException(
            status_code=400,
            detail="Valore X-Engine non valido. Usa 'new' oppure ometti l'header.",
        )

    use_new_engine = engine_flag == "new"

    if use_new_engine:
        result = calcola_oroscopo_new(scope, payload)
        engine_name = "new"
    else:
        result = calcola_oroscopo_legacy(scope, payload)
        engine_name = "legacy"

    return OroscopoResponse(
        status="ok",
        scope=scope,
        engine=engine_name,
        input=payload.model_dump(),
        result=result,
    )
