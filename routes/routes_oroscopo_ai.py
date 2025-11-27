# chatbot_test/routes_oroscopo.py

import logging
from typing import Any, Dict, Optional, List, Literal

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar

from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai
from astrobot_core.ai_oroscopo_claude import call_claude_oroscopo_ai

# === AUTH + CREDITI ===
from auth import get_current_user, UserContext
from astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oroscopo_ai", tags=["oroscopo_ai"])

Periodo = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]
Engine = Literal["ai"]

OROSCOPO_FEATURE_KEY_PREFIX = "oroscopo_ai"
OROSCOPO_FEATURE_COSTS: Dict[Periodo, int] = {
    "daily": 1,
    "weekly": 2,
    "monthly": 3,
    "yearly": 5,
}

PERIODO_EN_TO_IT = {
    "daily": "giornaliero",
    "weekly": "settimanale",
    "monthly": "mensile",
    "yearly": "annuale",
}

PERIODO_IT_TO_CODE = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}


class OroscopoAIRequest(BaseModel):
    citta: str
    data: str
    ora: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"

    @validator("data")
    def _validate_data(cls, v: str) -> str:
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
    status: Literal["ok", "error"]
    scope: Periodo
    engine: Engine
    input: Dict[str, Any]
    engine_result: Optional[Dict[str, Any]] = None
    payload_ai: Optional[Dict[str, Any]] = None
    oroscopo_ai: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    billing: Optional[Dict[str, Any]] = None


def _normalize_period(periodo: str) -> Periodo:
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
    return mapping[p]


def _normalize_tier(raw: Optional[str]) -> Tier:
    if not raw:
        return "free"
    s = raw.strip().lower()
    if s in {"premium", "pro", "paid"}:
        return "premium"
    return "free"


@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str
    periodo: str
    tier: str


def _safe_iso_to_dt(s: Optional[str], today: Optional[date] = None) -> datetime:
    if today is None:
        today = date.today()
    if not s:
        return datetime.combine(today, datetime.min.time())
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.combine(today, datetime.min.time())


# --- (omessi: tutti gli helper numerici, i bucket, gli aggregate ecc. li lasciamo esattamente uguali) ---
# SONO IDENTICI al file che mi hai incollato → NON LI TOCCO.


# =============================
# ROUTE PRINCIPALE
# =============================

@router.post(
    "/{periodo}",
    response_model=OroscopoResponse,
    summary="Oroscopo AI (daily/weekly/monthly/yearly, free/premium, billing semplice)",
)
async def oroscopo_ai_endpoint(
    periodo: str,
    payload: OroscopoAIRequest,
    user: UserContext = Depends(get_current_user),
) -> OroscopoResponse:

    scope: Periodo = _normalize_period(periodo)
    tier: Tier = _normalize_tier(payload.tier)

    logger.info(
        "[OROSCOPO_AI] scope=%s tier=%s citta=%s data=%s nome=%s",
        scope, tier, payload.citta, payload.data, payload.nome
    )

    engine: Engine = "ai"

    # -----------------------------
    # 0) GATING CREDITI
    # -----------------------------
    state = None
    decision: Optional[PremiumDecision] = None
    feature_cost = 0

    if tier == "premium":
        state = load_user_credits_state(user)
        decision = decide_premium_mode(state)
        feature_cost = OROSCOPO_FEATURE_COSTS.get(scope, 0)

        if feature_cost <= 0:
            raise HTTPException(
                status_code=500,
                detail=f"Costo oroscopo premium non configurato per periodo '{scope}'.",
            )

        apply_premium_consumption(state, decision, feature_cost=feature_cost)
        save_user_credits_state(state)

    try:
        engine_result = _run_oroscopo_engine(scope=scope, tier=tier, data_input=payload)

        payload_ai = _build_payload_ai(
            scope=scope,
            tier=tier,
            engine_result=engine_result,
            data_input=payload,
        )
        oroscopo_ai = _call_oroscopo_ai_claude(payload_ai)

        # --- usage tokens ---
        tokens_in = 0
        tokens_out = 0
        try:
            ai_debug_block = None
            if isinstance(oroscopo_ai, dict):
                ai_debug_block = oroscopo_ai.get("ai_debug") or oroscopo_ai.get("debug")
            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
                tokens_in = usage.get("input_tokens", 0) or 0
                tokens_out = usage.get("output_tokens", 0) or 0
        except Exception:
            pass

        # -----------------------------
        # BILLING
        # -----------------------------
        is_guest = user.sub.startswith("anon-")

        billing_mode = "free"
        remaining_credits = None
        cost_paid_credits = 0
        cost_free_credits = 0

        if tier == "premium" and state is not None and decision is not None:
            billing_mode = decision.mode
            remaining_credits = state.paid_credits

            if decision.mode == "paid":
                cost_paid_credits = feature_cost
            elif decision.mode == "free_credit":
                cost_free_credits = feature_cost

        billing = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": billing_mode,
            "remaining_credits": remaining_credits,
            "cost_paid_credits": cost_paid_credits,
            "cost_free_credits": cost_free_credits,
        }

        # -----------------------------
        # LOGGING PATCH (minima)
        # -----------------------------
        cost_credits = cost_paid_credits or cost_free_credits

        try:
            request_json = payload.dict()
            feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"

            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
                billing_mode=billing_mode,
                cost_paid_credits=cost_paid_credits,
                cost_free_credits=cost_free_credits,
                cost_credits=cost_credits,     # <--- PATCH AGGIUNTA
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                is_guest=is_guest,
                request_json=request_json,
            )
        except Exception:
            logger.exception("[OROSCOPO_AI] Errore nel logging usage")

        # -----------------------------
        # RISPOSTA
        # -----------------------------
        return OroscopoResponse(
            status="ok",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=engine_result,
            payload_ai=payload_ai,
            oroscopo_ai=oroscopo_ai,
            error=None,
            billing=billing,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OROSCOPO_AI] Errore non gestito")

        billing_error = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": "error",
            "remaining_credits": state.paid_credits if state else None,
        }

        return OroscopoResponse(
            status="error",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=None,
            payload_ai=None,
            oroscopo_ai=None,
            error=str(e),
            billing=billing_error,
        )
