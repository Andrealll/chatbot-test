# routes/routes_tema_ai.py

import json
import logging
from typing import Dict, Any, Optional, List, Literal

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from astrobot_core.ai_tema_claude import call_claude_tema_ai
from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.grafici import grafico_tema_natal, build_tema_text_payload
from astrobot_core.payload_tema_ai import build_payload_tema_ai

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
    # il frontend manda data_nascita / ora_nascita → usiamo alias
    citta: str
    data: str = Field(..., alias="data_nascita")          # "YYYY-MM-DD"
    ora: Optional[str] = Field(None, alias="ora_nascita") # "HH:MM" o vuota
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Literal["free", "premium"] = "free"
    ora_ignota: bool = False

    class Config:
        allow_population_by_field_name = True


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo tema natale (usa costruisci_tema_natale che gestisce ora_ignota)
    2) Build payload_vis (PNG + liste testuali) dal CORE
    3) Build payload_ai
    4) Chiamata Claude
    5) Logging usage
    6) Risposta finale con blocco billing
    """

    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
        # uso by_alias=True così nel log vedi data_nascita/ora_nascita
        "body": body.dict(by_alias=True),
        "client_source": client_source,
        "client_session": client_session,
    }

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
                feature_cost=TEMA_AI_PREMIUM_COST,
            )

            save_user_credits_state(state)

            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

            if decision.mode == "paid":
                billing_mode = "paid"
            elif decision.mode == "free_credit":
                billing_mode = "free_credit"
            elif decision.mode == "free_trial":
                billing_mode = "free_trial"
            else:
                billing_mode = "error"
        else:
            # tier free: nessun consumo, ma salviamo comunque lo stato (es. last_seen)
            save_user_credits_state(state)
            billing_mode = "free"

        # ====================================================
        # 1) Calcolo tema natale
        #    → costruisci_tema_natale gestisce internamente ora_ignota:
        #      - se ora_nascita None/"" → niente ASC / case / asc_ruler
        # ====================================================
        ora_raw = (body.ora or "").strip()
        ora_for_tema = None if body.ora_ignota or not ora_raw else ora_raw

        try:
            tema = costruisci_tema_natale(
                citta=body.citta,
                data_nascita=body.data,
                ora_nascita=ora_for_tema,
                sistema_case="equal",
            )
            # allineo comunque il flag, nel caso serva altrove
            tema_input = tema.get("input") or {}
            tema_input["ora_ignota"] = body.ora_ignota or tema_input.get(
                "ora_ignota", False
            )
            tema["input"] = tema_input

        except Exception as e:
            logger.exception("[TEMA_AI] Errore nel calcolo del tema natale")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo del tema natale: {e}",
            )

        # ====================================================
        # 1b) Costruzione payload VISIVO (tema_vis)
        # ====================================================
        try:
            # payload di base (meta, ecc.) → se hai una funzione dedicata, usala;
            # qui ricostruiamo il blocco con grafico + legenda pianeti/aspetti.
            pianeti_decod = tema.get("pianeti_decod") or {}
            asc_mc_case = tema.get("asc_mc_case") or {}
            aspetti = tema.get("natal_aspects") or []

            tema_vis: Dict[str, Any] = {}

            # PNG ruota-only (usa anche gli aspetti per disegno interno)
            try:
                chart_png_base64 = grafico_tema_natal(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case,
                    aspetti=aspetti,
                )
                tema_vis["chart_png_base64"] = chart_png_base64
            except Exception as ge:
                logger.exception(
                    "[TEMA_AI] Errore nella generazione del grafico tema con aspetti: %r",
                    ge,
                )

            # Payload testuale per frontend (Pianeti + Aspetti)
            try:
                text_payload = build_tema_text_payload(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case,
                    aspetti=aspetti,
                )
                tema_vis["pianeti"] = text_payload.get("pianeti", [])
                tema_vis["aspetti"] = text_payload.get("aspetti", [])
            except Exception as te:
                logger.exception(
                    "[TEMA_AI] Errore nella costruzione del payload testuale tema_vis: %r",
                    te,
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("[TEMA_AI] Errore nella costruzione del tema_vis")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nella costruzione del payload visivo del tema: {e}",
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
                tier=body.tier,  # "free" o "premium" influenza il prompt
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
        out = call_claude_tema_ai(payload_ai, tier=body.tier)

        raw = (out.get("ai_debug") or {}).get("raw_text") or ""
        parsed = out.get("content")
        parse_error = out.get("parse_error")

        ai_debug = {
            "result": parsed,
            "ai_debug": out.get("ai_debug"),
}

        # ====================================================
        # 3b) LOGGING USAGE (usage_logs) – SOLO SUCCESSO
        # ====================================================
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

        cost_paid_credits = 0
        cost_free_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "paid":
                cost_paid_credits = TEMA_AI_PREMIUM_COST
            elif decision.mode == "free_credit":
                cost_free_credits = TEMA_AI_PREMIUM_COST

        request_log_success = {
            **request_log_base,
            "ai_call": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        }

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
                request_json=request_log_success,
            )
        except Exception as e:
            logger.exception("[TEMA_AI] log_usage_event error (success): %r", e)

        # ====================================================
        # 4) Caso: Claude non ha risposto
        # ====================================================
        if not raw:
            return {
                "status": "error",
                "message": "Claude non ha restituito testo.",
                "input": body.dict(by_alias=True),
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
            "input": body.dict(by_alias=True),
            "tema_vis": tema_vis,        # PNG + pianeti/aspetti testuali
            "payload_ai": payload_ai,
            "result": {
                "error": "JSON non valido" if parsed is None else None,
                "parse_error": parse_error,
                "raw_preview": raw[:500],
                "content": parsed,
            },
            "ai_debug": ai_debug,
            "billing": {
                "mode": billing_mode,  # "free", "paid" o "free_credit"
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
    # 7) LOG TENTATIVI FALLITI
    # ====================================================
    except HTTPException as exc:
        try:
            log_usage_event(
                user_id=user.sub,
                feature=TEMA_AI_FEATURE_KEY,
                tier=body.tier,
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
                "[TEMA_AI] log_usage_event error (HTTPException): %r",
                log_err,
            )
        raise

    except Exception as exc:
        logger.exception("[TEMA_AI] Errore inatteso in tema_ai_endpoint")
        try:
            log_usage_event(
                user_id=user.sub,
                feature=TEMA_AI_FEATURE_KEY,
                tier=body.tier,
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
                "[TEMA_AI] log_usage_event error (unexpected): %r",
                log_err,
            )
        raise
