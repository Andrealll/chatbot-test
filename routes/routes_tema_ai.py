# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional, List, Literal

import json
import logging

from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.tema_vis_payload import build_tema_vis_payload
from astrobot_core.grafici import grafico_tema_natal
from astrobot_core.payload_tema_ai import build_payload_tema_ai, build_tema_vis

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

# Costi in crediti
TEMA_AI_FEATURE_KEY = "tema_ai"
TEMA_AI_PREMIUM_COST = 2


# ==========================
# Request model ALLINEATO AL FRONTEND
# ==========================
class TemaAIRequest(BaseModel):
    citta: str
    data: str                 # "YYYY-MM-DD"
    ora: Optional[str] = None # "HH:MM" oppure None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Literal["free", "premium"] = "free"
    ora_ignota: bool = False


# ==========================
# ROUTE /tema_ai
# ==========================
@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti (se premium)
    1) Calcolo tema natale (gestione ora_ignota)
    1b) Payload visivo (tema_vis)
    2) Payload AI
    3) Chiamata Claude
    4) Logging usage
    5) Risposta finale
    """

    # Metadati utente
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
        "body": body.dict(),
        "client_source": client_source,
        "client_session": client_session,
    }

    # Stato crediti
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
            # tier free: nessun consumo, ma salviamo comunque lo stato
            save_user_credits_state(state)
            billing_mode = "free"

        # ====================================================
        # 1) Calcolo tema natale (gestione ORA IGNOTA)
        # ====================================================
        ora_effettiva = (
            "12:00"
            if body.ora_ignota or not body.ora
            else body.ora
        )

        tema = costruisci_tema_natale(
            citta=body.citta,
            data_nascita=body.data,
            ora_nascita=ora_effettiva,
            sistema_case="equal",
        )

        if not isinstance(tema.get("input"), dict):
            tema["input"] = {}
        tema["input"]["ora_ignota"] = bool(body.ora_ignota)

        # ====================================================
        # 1b) Costruzione payload VISIVO (tema_vis) dal CORE
        # ====================================================
        try:
            tema_vis = build_tema_vis_payload(tema)

            ora_ignota_flag = bool((tema.get("input") or {}).get("ora_ignota", False))

            pianeti_decod = tema.get("pianeti_decod") or {}
            asc_mc_case = tema.get("asc_mc_case") or {}
            aspetti = tema.get("natal_aspects") or []

            # se ora ignota → niente case per grafico e testo
            asc_mc_case_for_draw = {} if ora_ignota_flag else asc_mc_case

            # --- grafico ---
            try:
                chart_png_base64 = grafico_tema_natal(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case_for_draw,
                    aspetti=aspetti,
                )
                tema_vis["chart_png_base64"] = chart_png_base64
            except Exception as ge:
                logger.exception(
                    "[TEMA_AI] Errore nella generazione del grafico tema con aspetti: %r",
                    ge,
                )

            # --- payload testuale pianeti + aspetti ---
            try:
                text_payload = build_tema_text_payload(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case_for_draw,
                    aspetti=aspetti,
                )
                pianeti_vis = text_payload.get("pianeti", [])
                aspetti_vis = text_payload.get("aspetti", [])

                if ora_ignota_flag:
                    # togliamo info di casa e la parte "Casa X" dalla label
                    import re

                    for p in pianeti_vis:
                        p["casa"] = None
                        label = p.get("label") or ""
                        # rimuove ", Casa 10" o " Casa 10"
                        label = re.sub(r",?\s*Casa\s+\d+\b", "", label)
                        p["label"] = label

                    # togliamo anche ASC/MC dai meta, se presenti
                    meta = tema_vis.get("meta") or {}
                    for k in [
                        "ascendente_segno",
                        "ascendente_gradi_segno",
                        "mc_segno",
                        "mc_gradi_segno",
                    ]:
                        if k in meta:
                            meta.pop(k, None)
                    tema_vis["meta"] = meta

                tema_vis["pianeti"] = pianeti_vis
                tema_vis["aspetti"] = aspetti_vis

            except Exception as te:
                logger.exception(
                    "[TEMA_AI] Errore nella costruzione del payload testuale tema_vis: %r",
                    te,
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
                tier=body.tier,   # "free" o "premium"
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
        from astrobot_core.ai_tema_claude import call_claude_tema_ai

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
