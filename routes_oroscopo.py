# routes_oroscopo.py

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal, Dict, Any
from datetime import date

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
    puoi estenderlo in base a T4/T6 (es. fuso, sistema_case, ecc.).
    """
    citta: str
    data: date              # data di riferimento (oggi per daily, lunedì per weekly, ecc.)
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"


class OroscopoResponse(BaseModel):
    status: str
    scope: ScopeType
    engine: Literal["legacy", "new"]
    input: Dict[str, Any]
    result: Dict[str, Any]   # payload specifico dell’oroscopo (lo decidi tu)


# ==========================
# MOTORI (STUB)
# ==========================

def calcola_oroscopo_legacy(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """
    QUI agganci il motore attuale (T4/T6).
    Per ora è uno stub che ti ricorda cosa sostituire.
    """
    # TODO: sostituire con chiamata reale al motore attuale.
    return {
        "engine_version": "legacy",
        "scope": scope,
        "note": "Motore legacy non ancora collegato (stub).",
    }


def calcola_oroscopo_new(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """
    QUI agganci il motore nuovo (nuova pipeline).
    """
    # TODO: sostituire con chiamata reale al motore nuovo.
    return {
        "engine_version": "new",
        "scope": scope,
        "note": "Motore NEW non ancora collegato (stub).",
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
    - altrimenti → usa il motore legacy (backward compat)
    """
    # Normalizza flag engine
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
