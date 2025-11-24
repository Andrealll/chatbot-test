# chatbot_test/routes_oroscopo.py

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Costanti / tipi
# ============================================================

Periodo = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]
Engine = Literal["ai", "new", "legacy"]  # ai = pipeline completa (Claude), new = numerico


# ============================================================
# MODELLI INPUT / OUTPUT
# ============================================================

class OroscopoBaseInput(BaseModel):
    """
    Input comune a tutti i periodi.
    Questa struttura è quella che userai sia da DYANA che da Typebot.
    """
    citta: str = Field(..., description="Città di nascita (es. 'Napoli')")
    data: str = Field(..., description="Data di nascita in formato YYYY-MM-DD")
    ora: Optional[str] = Field(
        None,
        description="Ora di nascita in formato HH:MM (24h). Obbligatoria se vuoi l'ascendente preciso."
    )
    nome: Optional[str] = Field(None, description="Nome della persona (opzionale, usato solo nel testo)")
    email: Optional[str] = None
    domanda: Optional[str] = Field(
        None,
        description="Eventuale domanda specifica da passare all'AI."
    )
    tier: Optional[Tier] = Field(
        None,
        description="free / premium. Se non passato, verrà determinato dal token/JWT."
    )

    @validator("data")
    def _validate_data(cls, v: str) -> str:
        # Controllo minimale sul formato, senza usare dateutil
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError("data deve essere in formato YYYY-MM-DD")
        return v

    @validator("ora")
    def _validate_ora(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("ora deve essere in formato HH:MM")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("ora deve contenere solo numeri (HH:MM)")
        return v


class OroscopoResponse(BaseModel):
    """
    Response 'macro' /oroscopo.
    - engine: "ai" quando usi la pipeline completa con Claude
    - engine: "new" quando usi solo il motore numerico (multi-snapshot) senza AI
    """
    status: Literal["ok", "error"]
    scope: Periodo
    engine: Engine
    input: Dict[str, Any]

    # Risultato del motore numerico (multi-snapshot, intensità, grafico, ecc.)
    engine_result: Optional[Dict[str, Any]] = None

    # Payload per la AI (quello che passa a Claude)
    payload_ai: Optional[Dict[str, Any]] = None

    # Output di Claude (oroscopo strutturato / testo)
    oroscopo_ai: Optional[Dict[str, Any]] = None

    # In caso di errore
    error: Optional[str] = None


# ============================================================
# Helpers interni
# ============================================================

def _normalize_period(periodo: str) -> Periodo:
    """
    Normalizza alias tipo "giornaliero" -> "daily", ecc.
    Se non riconosciuto, tira 400.
    """
    p = periodo.lower().strip()

    mapping = {
        "daily": "daily",
        "giornaliero": "daily",
        "giornaliera": "daily",
        "day": "daily",

        "weekly": "weekly",
        "settimanale": "weekly",
        "week": "weekly",

        "monthly": "monthly",
        "mensile": "monthly",
        "month": "monthly",

        "yearly": "yearly",
        "annuale": "yearly",
        "anno": "yearly",
    }

    if p not in mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Periodo non valido: '{periodo}'. Usa uno tra: daily, weekly, monthly, yearly."
        )

    return mapping[p]  # type: ignore[return-value]


def _resolve_tier(request: Request, body_tier: Optional[Tier]) -> Tier:
    """
    Regola unica per stabilire il tier:
    1) Se da JWT / cookie / whatever (da implementare)
    2) altrimenti fallback su body.tier
    3) altrimenti 'free'
    """
    # TODO: collega qui la tua logica reale di risoluzione tier dal JWT
    #       es: from .auth import get_tier_from_request
    #       tier_from_token = get_tier_from_request(request)
    tier_from_token: Optional[Tier] = None  # placeholder

    if tier_from_token is not None:
        return tier_from_token
    if body_tier is not None:
        return body_tier
    return "free"


def _resolve_engine(x_engine: Optional[str]) -> Engine:
    """
    Interpreta l'header X-Engine:
    - "ai"      → usa pipeline completa (motore numerico + payload_ai + Claude)
    - "new"     → solo motore numerico (multi-snapshot), senza AI
    - "legacy"  → eventuale vecchio motore (se vorrai reintrodurlo)
    - None      → default: "ai" (scelta A)
    """
    if x_engine is None or x_engine.strip() == "":
        return "ai"

    value = x_engine.lower().strip()
    if value not in ("ai", "new", "legacy"):
        raise HTTPException(
            status_code=400,
            detail="X-Engine deve essere uno tra: ai, new, legacy"
        )
    return value  # type: ignore[return-value]


# ============================================================
# TODO: collegamento al core AstroBot
# ============================================================

def _run_oroscopo_engine_new(
    scope: Periodo,
    tier: Tier,
    data_input: OroscopoBaseInput,
) -> Dict[str, Any]:
    """
    Wrapper unico per il motore numerico (multi-snapshot).
    Qui dovresti richiamare il tuo codice in astrobot-core, ad esempio:
        from astrobot_core.oroscopo_engine_new import run_oroscopo_multi_snapshot

        result = run_oroscopo_multi_snapshot(
            periodo=scope,
            tier=tier,
            citta=data_input.citta,
            data=data_input.data,
            ora=data_input.ora,
            nome=data_input.nome,
            email=data_input.email,
        )

    Per ora metto un placeholder così il file è auto-consistente.
    """
    # TODO: sostituisci questo blocco con l'import reale + chiamata al motore new
    logger.info(
        "[OROSCOPO][ENGINE_NEW] scope=%s tier=%s citta=%s data=%s",
        scope, tier, data_input.citta, data_input.data
    )
    return {
        "engine_version": "new",
        "scope": scope,
        "tier": tier,
        "note": "TODO: collega qui run_oroscopo_multi_snapshot dal core AstroBot.",
    }


def _build_payload_ai(
    scope: Periodo,
    tier: Tier,
    engine_result: Dict[str, Any],
    data_input: OroscopoBaseInput,
) -> Dict[str, Any]:
    """
    Costruisce il payload_ai da passare a Claude.

    Qui dovresti usare il tuo:
        from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai

    che a sua volta userà:
      - tema natale
      - transiti filtrati / aggregati
      - snapshot del periodo
      - ecc.
    """
    # TODO: sostituisci questo blocco con l'import reale + chiamata build_oroscopo_payload_ai
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] scope=%s tier=%s nome=%s",
        scope, tier, data_input.nome
    )
    return {
        "meta": {
            "scope": "oroscopo_ai",
            "periodo": scope,
            "tier": tier,
            "nome": data_input.nome,
            "email": data_input.email,
            "domanda": data_input.domanda,
        },
        "debug": {
            "note": "TODO: collega build_oroscopo_payload_ai dal core AstroBot.",
            "engine_result_sample": engine_result.get("scope"),
        },
    }


def _call_oroscopo_ai_claude(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chiama Claude con il super-prompt oroscopo.

    Qui dovresti usare il client che hai già preparato per il TEMA, adattato all'oroscopo, per esempio:
        from .ai_oroscopo_client import call_claude_oroscopo

        return call_claude_oroscopo(payload_ai)

    Per ora restituisco un placeholder.
    """
    # TODO: sostituisci con la vera chiamata ad Anthropic (Claude)
    logger.info("[OROSCOPO][CLAUDE] Chiamata placeholder oroscopo_ai")
    return {
        "model": "claude-3-5-haiku-20241022",
        "note": "TODO: collega il client reale Anthropic per l'oroscopo.",
        "sintesi": "Questo è un placeholder: collega il vero output di Claude qui.",
        "capitoli": [],
    }

# ============================================================
# ROUTE MACRO /oroscopo_ai/{periodo} (via prefix nel main)
# ============================================================

@router.post(
    "/{periodo}",
    response_model=OroscopoResponse,
    tags=["oroscopo"],
    summary="Oroscopo macro (daily/weekly/monthly/yearly, free/premium, motore AI completo)",
)
async def oroscopo_macro(
    periodo: str,
    data_input: OroscopoBaseInput,
    request: Request,
    x_engine: Optional[str] = Header(None, alias="X-Engine"),
) -> OroscopoResponse:
    """
    Route unica per tutti gli oroscopi.

    Path effettivo (dal main):
    - /oroscopo_ai/daily
    - /oroscopo_ai/weekly
    - /oroscopo_ai/monthly
    - /oroscopo_ai/yearly

    Corpo JSON (OroscopoBaseInput):
    {
      "citta": "...",
      "data": "YYYY-MM-DD",
      "ora": "HH:MM",
      "nome": "...",
      "email": "...",
      "domanda": "...",
      "tier": "free" | "premium"  # opzionale, altrimenti da JWT
    }

    Header:
    - X-Engine: "ai" | "new" | "legacy"
      * default: "ai" (scelta A → pipeline completa con Claude)
    """
    # --- qui sotto resta tutto come ti avevo già scritto ---
    scope: Periodo = _normalize_period(periodo)
    tier: Tier = _resolve_tier(request, data_input.tier)
    engine: Engine = _resolve_engine(x_engine)

    logger.info(
        "[OROSCOPO] scope=%s tier=%s engine=%s citta=%s data=%s nome=%s",
        scope, tier, engine, data_input.citta, data_input.data, data_input.nome
    )

    try:
        engine_result = _run_oroscopo_engine_new(scope=scope, tier=tier, data_input=data_input)

        payload_ai: Optional[Dict[str, Any]] = None
        oroscopo_ai: Optional[Dict[str, Any]] = None

        if engine == "ai":
            payload_ai = _build_payload_ai(
                scope=scope,
                tier=tier,
                engine_result=engine_result,
                data_input=data_input,
            )
            oroscopo_ai = _call_oroscopo_ai_claude(payload_ai)

        elif engine == "legacy":
            raise HTTPException(
                status_code=501,
                detail="Motore legacy non più supportato. Usa X-Engine: ai oppure new."
            )

        return OroscopoResponse(
            status="ok",
            scope=scope,
            engine=engine,
            input=data_input.dict(),
            engine_result=engine_result,
            payload_ai=payload_ai,
            oroscopo_ai=oroscopo_ai,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OROSCOPO] Errore non gestito")
        return OroscopoResponse(
            status="error",
            scope=scope,
            engine=engine,
            input=data_input.dict(),
            engine_result=None,
            payload_ai=None,
            oroscopo_ai=None,
            error=str(e),
        )
        
@router.post(
    "/oroscopo_ai/{periodo}",
    response_model=OroscopoResponse,
    tags=["oroscopo"],
    summary="Alias /oroscopo_ai per oroscopo macro (daily/weekly/monthly/yearly)",
)
async def oroscopo_ai_macro(
    periodo: str,
    data_input: OroscopoBaseInput,
    request: Request,
    x_engine: Optional[str] = Header(None, alias="X-Engine"),
) -> OroscopoResponse:
    """
    Alias di /{periodo} esposto come /oroscopo_ai/{periodo}.

    Esempi:
    - /oroscopo_ai/daily
    - /oroscopo_ai/weekly
    - /oroscopo_ai/monthly
    - /oroscopo_ai/yearly
    """
    # Riusa esattamente la stessa logica della route principale
    return await oroscopo_macro(
        periodo=periodo,
        data_input=data_input,
        request=request,
        x_engine=x_engine,
    )
