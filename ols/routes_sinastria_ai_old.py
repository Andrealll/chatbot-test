from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time
from datetime import datetime
import logging

from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai

# === NUOVI IMPORT PER AUTH + CREDITI ===
from auth import get_current_user, UserContext
from credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])

# ==========================
#  Costi / feature
# ==========================
SINASTRIA_FEATURE_KEY = "sinastria_ai"
# Parametrico: quante volte "vale" una sinastria premium
SINASTRIA_FEATURE_COST = 3  # puoi cambiare facilmente questo valore


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
    user: UserContext = Depends(get_current_user),  # <-- utente dal JWT
):
    start = time.time()
    tier = _normalize_tier(payload.tier)

    # ==========================================
    # 0) GATING CREDITI (solo per tier premium)
    # ==========================================
    state = None
    decision = None

    if tier == "premium":
        # Carica stato crediti + free tries da Supabase (guest vs user)
        state = load_user_credits_state(user)

        # Decide se può fare una sinastria premium: paid / free_try / denied
        decision = decide_premium_mode(state)

        # Applica il consumo effettivo (crediti o free_try) oppure tira 402
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
                detail=f"Formato data/ora non valido: {e}"
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
        # 5) LOG USAGE (solo utenti registrati)
        # ==========================================
        try:
            is_guest = user.sub.startswith("anon-")
            if not is_guest:
                cost_credits = 0
                if tier == "premium" and state is not None and decision is not None:
                    mode = getattr(decision, "mode", None)
                    if mode == "paid":
                        cost_credits = SINASTRIA_FEATURE_COST

                tokens_in = 0
                tokens_out = 0

                log_usage_event(
                    user_id=user.sub,
                    feature=SINASTRIA_FEATURE_KEY,
                    cost_credits=cost_credits,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
        except Exception:
            logger.exception("[SINASTRIA] Errore nel logging usage")

        # ==========================================
        # 6) Risposta finale
        # ==========================================
        billing = {"tier": tier}

        if state is not None and decision is not None:
            billing.update(
                {
                    "mode": decision.mode,            # "paid" | "free_try"
                    "remaining_credits": state.paid_credits,
                }
            )
        else:
            billing.update(
                {
                    "mode": "free",
                    "remaining_credits": None,
                }
            )

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
