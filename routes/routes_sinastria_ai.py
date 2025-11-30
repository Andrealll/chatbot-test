# routes/routes_sinastria_ai.py

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai

# --- IMPORT PER AUTH + CREDITI (come tema_ai) ---
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

print(">>> DEBUG: routes_sinastria_ai COMPLETA LOADED <<<")

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])

# ==========================
#  Costi in crediti (parametrici)
# ==========================
SINASTRIA_FEATURE_KEY = "sinastria_ai"
SINASTRIA_PREMIUM_COST = 3  # quante volte "vale" una sinastria premium


# ==========================
#  Request models
# ==========================
class Persona(BaseModel):
    citta: str
    data: str        # YYYY-MM-DD
    ora: str         # HH:MM
    nome: Optional[str] = None


class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: str = "free"   # "free" | "premium"


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/")  # 👈 path relativo, quindi POST /sinastria_ai/
async def sinastria_ai_endpoint(
    body: SinastriaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo sinastria (numerico)
    2) Build payload_ai
    3) Chiamata Claude
    4) Logging usage
    5) Risposta finale con blocco billing
    """

    # ==============================
    # Metadati utente + request (usati in success + error)
    # ==============================
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
        "body": body.dict(),
        "client_source": client_source,
        "client_session": client_session,
    }

    # Variabili di stato usate sia in success path che in error path
    state = None
    decision: Optional[PremiumDecision] = None
    billing_mode = "free"

    paid_credits_before: Optional[int] = None
    paid_credits_after: Optional[int] = None
    free_credits_used_before: Optional[int] = None
    free_credits_used_after: Optional[int] = None

    try:
        # ====================================================
        # 0) STATO CREDITI + GATING (consumo solo PREMIUM)
        # ====================================================
        state = load_user_credits_state(user)

        paid_credits_before = state.paid_credits
        free_credits_used_before = state.free_tries_used
        paid_credits_after = state.paid_credits
        free_credits_used_after = state.free_tries_used

        if body.tier == "premium":
            decision = decide_premium_mode(state)

            apply_premium_consumption(
                state,
                decision,
                feature_cost=SINASTRIA_PREMIUM_COST,
            )

            save_user_credits_state(state)

            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

            if decision.mode == "paid":
                billing_mode = "paid"
            elif decision.mode == "free_credit":
                billing_mode = "free_credit"
            else:
                billing_mode = "denied"
        else:
            # tier free: nessun consumo, ma salviamo comunque lo stato (es. last_seen)
            save_user_credits_state(state)
            billing_mode = "free"

        # ====================================================
        # 1) Parsing datetime + calcolo sinastria
        # ====================================================
        try:
            dt_A = datetime.fromisoformat(f"{body.A.data} {body.A.ora}")
            dt_B = datetime.fromisoformat(f"{body.B.data} {body.B.ora}")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato data/ora non valido: {e}",
            )

        try:
            sinastria_data = calcola_sinastria(
                dt_A,
                body.A.citta,
                dt_B,
                body.B.citta,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nel calcolo della sinastria")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo della sinastria: {e}",
            )

        # ====================================================
        # 2) Build payload AI
        # ====================================================
        try:
            payload_ai: Dict[str, Any] = {
                "meta": {
                    "scope": "sinastria_ai",
                    "tier": body.tier,
                    "lingua": "it",
                    "nome_A": body.A.nome,
                    "nome_B": body.B.nome,
                },
                "sinastria": sinastria_data,
            }
        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nella costruzione del payload AI")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nella costruzione del payload AI: {e}",
            )

        # ====================================================
        # 3) Chiamata Claude
        # ====================================================
        sinastria_ai = call_claude_sinastria_ai(payload_ai)

        # ====================================================
        # 3b) Estrazione usage (usage_logs) – SOLO SUCCESSO
        # ====================================================
        tokens_in = 0
        tokens_out = 0
        model = None
        latency_ms: Optional[float] = None

        try:
            ai_debug_block = None
            if isinstance(sinastria_ai, dict):
                ai_debug_block = (
                    sinastria_ai.get("ai_debug")
                    or sinastria_ai.get("debug")
                )

            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
                tokens_in = usage.get("input_tokens", 0) or 0
                tokens_out = usage.get("output_tokens", 0) or 0

                model = ai_debug_block.get("model")
                elapsed_sec = ai_debug_block.get("elapsed_sec")
                if isinstance(elapsed_sec, (int, float)):
                    latency_ms = float(elapsed_sec) * 1000.0
        except Exception:
            tokens_in = 0
            tokens_out = 0
            model = None
            latency_ms = None

        # Calcolo costi per logging (paid vs free_credit)
        cost_paid_credits = 0
        cost_free_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "paid":
                cost_paid_credits = SINASTRIA_PREMIUM_COST
            elif decision.mode == "free_credit":
                cost_free_credits = SINASTRIA_PREMIUM_COST

        request_log_success = {
            **request_log_base,
            "ai_call": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        }

        # Logghiamo SEMPRE (successo)
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
                tier=body.tier,
                role=role,
                is_guest=is_guest,
                billing_mode=billing_mode,
                cost_paid_credits=cost_paid_credits,
                cost_free_credits=cost_free_credits,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                latency_ms=latency_ms,
                paid_credits_before=paid_credits_before,
                paid_credits_after=paid_credits_after,
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=free_credits_used_after,
                request_json=request_log_success,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] log_usage_event error (success): %r", e)

        # ====================================================
        # 4) Risposta finale
        # ====================================================
        return {
            "status": "ok",
            "scope": "sinastria_ai",
            "input": body.dict(),
            "payload_ai": payload_ai,
            "sinastria_ai": sinastria_ai,
            "billing": {
                "mode": billing_mode,                 # "free", "paid" o "free_credit"
                "remaining_credits": (
                    state.paid_credits if state is not None else None
                ),
                "cost_credits": (
                    SINASTRIA_PREMIUM_COST
                    if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                    else 0
                ),
                "cost_paid_credits": cost_paid_credits,
                "cost_free_credits": cost_free_credits,
            },
        }

    # ====================================================
    # 5) LOG TENTATIVI FALLITI (HTTPException)
    # ====================================================
    except HTTPException as exc:
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
                tier=getattr(body, "tier", "unknown"),
                role=role,
                is_guest=is_guest,
                billing_mode="error",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(state.paid_credits if state is not None else None),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json={
                    **request_log_base,
                    "error": {
                        "type": "http_exception",
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    },
                },
            )
        except Exception as log_err:
            logger.exception(
                "[SINASTRIA_AI] log_usage_event error (HTTPException): %r",
                log_err,
            )
        raise

    # ====================================================
    # 6) LOG TENTATIVI FALLITI (unexpected Exception)
    # ====================================================
    except Exception as exc:
        logger.exception("[SINASTRIA_AI] Errore inatteso in sinastria_ai_endpoint")
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
                tier=getattr(body, "tier", "unknown"),
                role=role,
                is_guest=is_guest,
                billing_mode="error",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(state.paid_credits if state is not None else None),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json={
                    **request_log_base,
                    "error": {
                        "type": "unexpected_exception",
                        "detail": str(exc),
                    },
                },
            )
        except Exception as log_err:
            logger.exception(
                "[SINASTRIA_AI] log_usage_event error (unexpected): %r",
                log_err,
            )
        raise
