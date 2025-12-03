# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import logging

from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.tema_vis_payload import build_tema_vis_payload
from astrobot_core.grafici import grafico_tema_natal, build_tema_text_payload
from astrobot_core.payload_tema_ai import build_payload_tema_ai
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
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo tema natale
    2) Build payload_vis (PNG + liste testuali) dal CORE
    3) Build payload_ai
    4) Chiamata Claude
    5) Logging usage
    6) Risposta finale con blocco billing
    """

    # ==============================
    # Metadati utente + request (usati in success + error)
    # ==============================
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    # base request_json comune (successo e errore)
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
                feature_cost=TEMA_AI_PREMIUM_COST,
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
        # 1b) Costruzione payload VISIVO (tema_vis) dal CORE
        # ====================================================
        try:
            # payload di base (meta, ecc.)
            tema_vis = build_tema_vis_payload(tema)

            # 🔹 PIANETI / CASE / ASPETTI natali
            pianeti_decod = tema.get("pianeti_decod") or {}
            asc_mc_case = tema.get("asc_mc_case") or {}
            aspetti = tema.get("natal_aspects") or []

            # 🔹 PNG ruota-only (usa anche gli aspetti per disegno interno)
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

            # 🔹 Payload testuale per frontend (Pianeti + Aspetti)
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
        # 3b) LOGGING USAGE (usage_logs) – SOLO SUCCESSO
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

        # Calcolo costi per logging (paid vs free_credit)
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
            "tema_vis": tema_vis,        # 👈 PNG + pianeti/aspetti testuali
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
