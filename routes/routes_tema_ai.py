# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import json

from astrobot_core.calcoli import costruisci_tema_natale
from utils.payload_tema_ai import build_payload_tema_ai
from ai_claude import call_claude_tema_ai

# --- IMPORT PER AUTH + CREDITI ---
from auth import get_current_user, UserContext
from astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)

router = APIRouter()

# ==========================
#  Costi in crediti (parametrici)
# ==========================
TEMA_AI_FEATURE_KEY = "tema_ai"
TEMA_AI_PREMIUM_COST = 2  # <-- se domani vuoi 3/5 ecc, cambi solo qui


# ==========================
#  Request model
# ==========================
class TemaAIRequest(BaseModel):
    citta: str
    data: str        # formato YYYY-MM-DD
    ora: str         # formato HH:MM
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: str = "free"   # "free" | "premium"


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo tema natale
    2) Build payload_ai
    3) Chiamata Claude
    4) Logging usage
    5) Risposta finale con blocco billing
    """

    # ====================================================
    # 0) GATING CREDITI (solo per PREMIUM)
    # ====================================================
    state = None
    decision: Optional[PremiumDecision] = None
    billing_mode = "free"  # default per tier free

    paid_credits_before: Optional[int] = None
    paid_credits_after: Optional[int] = None
    free_credits_before: Optional[int] = None
    free_credits_after: Optional[int] = None

    if body.tier == "premium":
        state = load_user_credits_state(user)

        paid_credits_before = state.paid_credits
        free_credits_before = state.free_credits

        decision = decide_premium_mode(state)

        apply_premium_consumption(
            state,
            decision,
            feature_cost=TEMA_AI_PREMIUM_COST,
        )

        save_user_credits_state(state)

        paid_credits_after = state.paid_credits
        free_credits_after = state.free_credits

        if decision.mode == "paid":
            billing_mode = "paid"
        elif decision.mode == "free_credit":
            billing_mode = "free_credit"
        else:
            billing_mode = "denied"
    else:
        billing_mode = "free"

    # ====================================================
    # 1) Calcolo tema natale
    # ====================================================
    try:
        tema = costruisci_tema_natale(
            body.citta,
            body.data,
            body.ora,
            sistema_case="equal",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore nel calcolo del tema natale: {e}",
        )

    # ====================================================
    # 2) Build payload AI
    # ====================================================
    try:
        payload_ai = build_payload_tema_ai(
            tema=tema,
            nome=body.nome,
            email=body.email,
            domanda=body.domanda,
            tier=body.tier,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore nella costruzione del payload AI: {e}",
        )

    # ====================================================
    # 3) Chiamata Claude
    # ====================================================
    ai_debug = call_claude_tema_ai(payload_ai, tier=body.tier)

    raw = (
        ai_debug.get("raw_text")
        or ai_debug.get("ai_debug", {}).get("raw_text")
        or ""
    )

    # ====================================================
    # 3b) LOGGING USAGE (usage_logs)
    # ====================================================
    usage = {}
    try:
        usage = (ai_debug.get("ai_debug") or {}).get("usage") or {}
    except Exception:
        usage = {}

    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)

    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    # Calcolo costi per logging
    cost_paid_credits = 0
    cost_free_credits = 0

    if body.tier == "premium" and decision is not None:
        if decision.mode == "paid":
            cost_paid_credits = TEMA_AI_PREMIUM_COST
        elif decision.mode == "free_credit":
            cost_free_credits = TEMA_AI_PREMIUM_COST

    # Compatibilità totale con credits_logic.log_usage_event
    cost_credits = cost_paid_credits or cost_free_credits

    try:
        log_usage_event(
            user_id=user.sub,
            feature=TEMA_AI_FEATURE_KEY,
            tier=body.tier,
            billing_mode=billing_mode,
            cost_paid_credits=cost_paid_credits,
            cost_free_credits=cost_free_credits,
            cost_credits=cost_credits,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            is_guest=is_guest,
            request_json=body.dict(),
        )
    except Exception as e:
        print("[TEMA_AI] log_usage_event error:", repr(e))

    # ====================================================
    # 4) Caso: Claude non ha risposto
    # ====================================================
    if not raw:
        return {
            "status": "error",
            "message": "Claude non ha restituito testo.",
            "input": body.dict(),
            "payload_ai": payload_ai,
            "result": None,
            "ai_debug": ai_debug,
            "billing": {
                "mode": billing_mode,
                "paid_credits_before": paid_credits_before,
                "paid_credits_after": paid_credits_after,
                "free_credits_before": free_credits_before,
                "free_credits_after": free_credits_after,
                "cost_credits": (
                    TEMA_AI_PREMIUM_COST
                    if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                    else 0
                ),
            },
        }

    # ====================================================
    # 5) Parse JSON dall'AI
    # ====================================================
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(raw)
    except Exception as e:
        parse_error = str(e)

    # ====================================================
    # 6) Risposta finale
    # ====================================================
    return {
        "status": "ok",
        "scope": "tema_ai",
        "input": body.dict(),
        "payload_ai": payload_ai,
        "result": {
            "error": "JSON non valido" if parsed is None else None,
            "parse_error": parse_error,
            "raw_preview": raw[:500],
            "content": parsed,
        },
        "ai_debug": ai_debug,
        "billing": {
            "mode": billing_mode,
            "paid_credits_before": paid_credits_before,
            "paid_credits_after": paid_credits_after,
            "free_credits_before": free_credits_before,
            "free_credits_after": free_credits_after,
            "cost_credits": (
                TEMA_AI_PREMIUM_COST
                if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                else 0
            ),
        },
    }
