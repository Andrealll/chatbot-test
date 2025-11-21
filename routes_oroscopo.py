# routes_oroscopo.py

from datetime import date, timedelta
from typing import Optional, Literal, Dict, Any, List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(
    prefix="/oroscopo",
    tags=["oroscopo"],
)

# ==========================
# MODELLI
# ==========================

ScopeType = Literal["daily", "weekly", "monthly", "yearly"]


class OroscopoRequest(BaseModel):
    """
    Input minimale e compatibile con /tema:
    - citta: metadata
    - data: riferimento per lo scope
    """
    citta: str
    data: date
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"


class OroscopoResponse(BaseModel):
    status: str
    scope: ScopeType
    engine: Literal["legacy", "new"]
    input: Dict[str, Any]
    result: Dict[str, Any]   # payload specifico dell’oroscopo


# ==========================
# UTILS
# ==========================

def _blank_png_no_prefix() -> str:
    # 1x1 pixel trasparente (senza prefisso data:image)
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="


# ==========================
# MOTORI (LEGACY + NEW)
# ==========================

def calcola_oroscopo_legacy(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    return {
        "engine_version": "legacy",
        "scope": scope,
        "note": "Motore legacy non collegato: usa X-Engine: new per la pipeline nuova.",
    }


def _build_date_series(scope: ScopeType, base_date: date) -> List[date]:
    if scope == "daily":
        return [base_date]
    if scope == "weekly":
        return [base_date + timedelta(days=i) for i in range(7)]
    if scope == "monthly":
        start = base_date - timedelta(days=14)
        return [start + timedelta(days=i) for i in range(30)]
    if scope == "yearly":
        start = date(base_date.year, 1, 1)
        return [start + timedelta(days=30 * i) for i in range(12)]
    return [base_date]


def _build_intensities_for_dates(dates: List[date]) -> Dict[str, List[float]]:
    import math
    n = len(dates)
    if n == 0:
        return {k: [] for k in ["energy","emotions","relationships","work","luck"]}
    base_ord = dates[0].toordinal()

    def norm_sin(idx: int, freq: float, phase: float = 0.0, amp: float = 0.40, bias: float = 0.5) -> float:
        x = idx / max(n - 1, 1)
        val = math.sin(2 * math.pi * (freq * x + phase + base_ord * 0.01))
        out = bias + amp * val
        return 0.0 if out < 0.0 else 1.0 if out > 1.0 else out

    energy        = [norm_sin(i, freq=0.9, phase=0.1) for i in range(n)]
    emotions      = [norm_sin(i, freq=0.7, phase=0.35) for i in range(n)]
    relationships = [norm_sin(i, freq=0.8, phase=0.55) for i in range(n)]
    work          = [norm_sin(i, freq=1.1, phase=0.2, amp=0.45) for i in range(n)]
    luck          = [norm_sin(i, freq=0.5, phase=0.8, amp=0.35, bias=0.55) for i in range(n)]

    return {
        "energy": energy,
        "emotions": emotions,
        "relationships": relationships,
        "work": work,
        "luck": luck,
    }


def _build_label_map_it() -> Dict[str, str]:
    return {
        "energy": "Energia",
        "emotions": "Emozioni",
        "relationships": "Relazioni",
        "work": "Lavoro",
        "luck": "Fortuna",
    }


def calcola_oroscopo_new(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """
    Motore NEW:
    - genera date + intensità 0–1 (5 domini)
    - prova a renderizzare il grafico a linee premium dal core
      con fallback a PNG trasparente se il modulo non è disponibile.
    """
    # 1) serie di date
    date_list = _build_date_series(scope, payload.data)
    date_strings = [d.isoformat() for d in date_list]

    # 2) intensità sintetiche
    intensities = _build_intensities_for_dates(date_list)

    # 3) grafico (import lazy + fallback)
    label_map = _build_label_map_it()
    png_base64 = None
    try:
        from astrobot_core.grafici import grafico_linee_premium  # <-- import lazy
        png_base64 = grafico_linee_premium(
            date_strings=date_strings,
            intensities_series=intensities,
            scope=scope,
            label_map=label_map,
        )
    except Exception:
        png_base64 = _blank_png_no_prefix()

    if png_base64 and not png_base64.startswith("data:image/png;base64,"):
        png_base64_with_prefix = "data:image/png;base64," + png_base64
    else:
        png_base64_with_prefix = png_base64

    return {
        "engine_version": "new",
        "scope": scope,
        "meta": {
            "citta": payload.citta,
            "nome": payload.nome,
            "email": payload.email,
            "domanda": payload.domanda,
        },
        "dates": date_strings,
        "intensities": intensities,
        "grafico_linee_png": png_base64_with_prefix,
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
    """
    POST /oroscopo/{daily|weekly|monthly|yearly}
    - se X-Engine: new → usa il motore nuovo
    - altrimenti → motore legacy (backward compatibility)
    """
    engine_flag = (x_engine or "").lower().strip()
    if engine_flag not in ("", "new"):
        raise HTTPException(status_code=400, detail="Valore X-Engine non valido. Usa 'new' oppure ometti l'header.")

    use_new_engine = engine_flag == "new"
    result = calcola_oroscopo_new(scope, payload) if use_new_engine else calcola_oroscopo_legacy(scope, payload)
    engine_name = "new" if use_new_engine else "legacy"

    return OroscopoResponse(
        status="ok",
        scope=scope,
        engine=engine_name,
        input=payload.model_dump(),
        result=result,
    )
