from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time
from datetime import datetime
import logging

from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai

# === IMPORT PER AUTH + CREDITI (NUOVI) ===
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

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])

# ==========================
#  Costi / feature
# ==========================
SINASTRIA_FEATURE_KEY = "sinastria_ai"
SINASTRIA_FEATURE_COST = 3  # parametrico


class Persona(BaseModel):
    citta: str
    data: str
    ora: str
    nome: Optional[str] = None


class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: Optional[str] = "free"  # "free" | "premium"


def _normalize_tier(raw: Optional[str]) -> str:
    if not raw:
        return "free"
    s = raw.strip().lower()
    if s in {"premium", "pro", "paid"}:
        return "premium"
    return "free"


@router.post("/")
async def sinastria_ai_endpoint(
    payload: SinastriaAIRequest,
    user: UserContext = Depends(get_current_user),  # utente dal JWT
):
    start = time.time()
    tier = _normalize_tier(payload.tier)

    # ==========================================
    # 0) GATING CREDITI (solo per tier premium)
    # ==========================================
    state = None
    decision: Optional[PremiumDecision] = None

    if tier == "premium":
        # Carica stato crediti (paid + free credits guest/user)
        state = load_user_credits_state(user)

        # Decide: paid / free_credit / denied
        decision = decide_premium_mode(state)

        # Applica il consumo (paid o free_credit) o solleva 402
        apply_premium_consumption(
            state,
            decision,
            feature_cost=SINASTRIA_FEATURE_COST,
        )

        # Salva stato aggiornato
        save_user_credits_state(state)

    try:
        # ==========================================
        # 1) Parsing datetime
        # ==========================================
        try:
            dt_A = datetime.fromisoformat(f"{payload.A.data} {payload.A.ora}")
            dt_B = datetime.fromisoformat(f"{payload.B.data} {payload.B.ora}")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato data/ora non valido: {e}",
            )

        # ==========================================
        # 2) Calcolo numerico sinastria
        # ==========================================
        sinastria_data = calcola_sinastria(
            dt_A,
            payload.A.citta,
            dt_B,
            payload.B.citta,
        )

        # ==========================================
        # 3) Build payload_ai (Claude)
        # ==========================================
        payload_ai: Dict[str, Any] = {
            "meta": {
                "scope": "sinastria_ai",
                "tier": tier,
                "lingua": "it",
                "nome_A": payload.A.nome,
                "nome_B": payload.B.nome,
            },
            "sinastria": sinastria_data,
        }

        # ==========================================
        # 4) Chiamata Claude
        # ==========================================
        sinastria_ai = call_claude_sinastria_ai(payload_ai)

        elapsed = time.time() - start

        # ==========================================
        # 5) Estrazione usage (se presente)
        # ==========================================
        tokens_in = 0
        tokens_out = 0
        try:
            # se ai_sinastria_claude ritorna qualcosa tipo {"ai_debug": {"usage": {...}}}
            ai_debug_block = None
            if isinstance(sinastria_ai, dict):
                ai_debug_block = sinastria_ai.get("ai_debug") or sinastria_ai.get("debug")
            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
                tokens_in = usage.get("input_tokens", 0) or 0
                tokens_out = usage.get("output_tokens", 0) or 0
        except Exception:
            tokens_in = 0
            tokens_out = 0

        # ==========================================
        # 6) COSTI & BILLING (paid vs free_credit vs free)
        # ==========================================
        is_guest = user.sub.startswith("anon-")

        billing_mode = "free"
        remaining_credits = None
        cost_paid_credits = 0
        cost_free_credits = 0

        if tier == "premium" and state is not None and decision is not None:
            billing_mode = decision.mode  # "paid" | "free_credit"
            remaining_credits = state.paid_credits

            if decision.mode == "paid":
                cost_paid_credits = SINASTRIA_FEATURE_COST
            elif decision.mode == "free_credit":
                cost_free_credits = SINASTRIA_FEATURE_COST
        else:
            billing_mode = "free"
            remaining_credits = None

        billing = {
            "tier": tier,
            "mode": billing_mode,
            "remaining_credits": remaining_credits,
            "cost_paid_credits": cost_paid_credits,
            "cost_free_credits": cost_free_credits,
        }

        # ==========================================
        # 7) LOG USAGE (anche guest, con request_json)
        # ==========================================
        try:
            request_json = {
                "A": payload.A.dict(),
                "B": payload.B.dict(),
                "tier": tier,
            }

            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
                tier=tier,
                billing_mode=billing_mode,
                cost_paid_credits=cost_paid_credits,
                cost_free_credits=cost_free_credits,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                is_guest=is_guest,
                request_json=request_json,
            )
        except Exception:
            logger.exception("[SINASTRIA] Errore nel logging usage")

        # ==========================================
        # 8) Risposta finale
        # ==========================================
        return {
            "status": "ok",
            "elapsed": elapsed,
            "input": {
                "A": payload.A.dict(),
                "B": payload.B.dict(),
                "tier": tier,
            },
            "payload_ai": payload_ai,
            "sinastria_ai": sinastria_ai,
            "error": None,
            "billing": billing,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore interno /sinastria_ai: {e}")
