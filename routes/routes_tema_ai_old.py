# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import logging

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

logger = logging.getLogger(__name__)

router = APIRouter()

# ==========================
#  Costi in crediti (parametrici)
# ==========================
TEMA_AI_FEATURE_KEY = "tema_ai"
TEMA_AI_PREMIUM_COST = 2  # se domani vuoi 3/5 ecc, cambi solo qui


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
    free_credits_used_before: Optional[int] = None
    free_credits_used_after: Optional[int] = None

    if body.tier == "premium":
        # Stato crediti + free_tries (entitlements/guests/supabase + fallback RAM)
        state = load_user_credits_state(user)

        # snapshot prima del consumo (per logging)
        paid_credits_before = state.paid_credits
        free_credits_used_before = state.free_tries_used

        # Decidi: "paid" | "free_credit" (o 402 se niente)
        decision = decide_premium_mode(state)

        # Applica consumo effettivo
        apply_premium_consumption(
            state,
            decision,
            feature_cost=TEMA_AI_PREMIUM_COST,
        )

        # Salva stato aggiornato (Supabase + RAM)
        save_user_credits_state(state)

        # snapshot dopo consumo
        paid_credits_after = state.paid_credits
        free_credits_used_after = state.free_tries_used

        if decision.mode == "paid":
            billing_mode = "paid"
        elif decision.mode == "free_credit":
            billing_mode = "free_credit"
        else:
            billing_mode = "denied"
    else:
        # tier free: NON tocchiamo crediti, ma teniamo traccia del fatto che è free
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
        logger.exception("[TEMA_AI] Errore nel calcolo del tema natale")
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
            tier=body.tier,   # "free" o "premium" influenza il prompt
        )
    except Exception as e:
        logger.exception("[TEMA_AI] Errore nella costruzione del payload AI")
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
        or (ai_debug.get("ai_debug") or {}).get("raw_text")
        or ""
    )

    # ====================================================
    # 3b) LOGGING USAGE (usage_logs)
    # ====================================================
    usage: Dict[str, Any] = {}
    try:
        usage = (ai_debug.get("ai_debug") or {}).get("usage") or {}
    except Exception:
        usage = {}

    tokens_in = usage.get("input_tokens", 0) or 0
    tokens_out = usage.get("output_tokens", 0) or 0

    model = None
    latency_ms: Optional[float] = None
    try:
        inner = ai_debug.get("ai_debug") or {}
        model = inner.get("model")
        elapsed_sec = inner.get("elapsed_sec")
        if isinstance(elapsed_sec, (int, float)):
            latency_ms = float(elapsed_sec) * 1000.0
    except Exception:
        model = None
        latency_ms = None

    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    # Calcolo costi per logging (paid vs free_credit)
    cost_paid_credits = 0
    cost_free_credits = 0

    if body.tier == "premium" and decision is not None:
        if decision.mode == "paid":
            cost_paid_credits = TEMA_AI_PREMIUM_COST
        elif decision.mode == "free_credit":
            cost_free_credits = TEMA_AI_PREMIUM_COST

    # Logghiamo SEMPRE, anche guest
    try:
        log_usage_event(
            user_id=user.sub,
            feature=TEMA_AI_FEATURE_KEY,
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
            request_json=body.dict(),
        )
    except Exception as e:
        # Non blocchiamo la risposta se il logging fallisce
        logger.exception("[TEMA_AI] log_usage_event error: %r", e)

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
                "remaining_credits": (
                    state.paid_credits if state is not None else None
                ),
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
            "mode": billing_mode,                 # "free", "paid" o "free_credit"
            "remaining_credits": (
                state.paid_credits if state is not None else None
            ),
            "cost_credits": (
                TEMA_AI_PREMIUM_COST
                if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                else 0
            ),
        },
    }
