# routes/routes_tema_ai.py

import json
import logging
from typing import Dict, Any, Optional, Literal

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from astrobot_core.ai_tema_claude import call_claude_tema_ai
from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.grafici import grafico_tema_natal, build_tema_text_payload
from astrobot_core.payload_tema_ai import build_payload_tema_ai

# --- AUTH + CREDITI ---
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
# Costi
# ==========================
TEMA_AI_FEATURE_KEY = "tema_ai"
TEMA_AI_PREMIUM_COST = 2


# ==========================
# Request model
# ==========================
class TemaAIRequest(BaseModel):
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


@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    is_guest = bool(getattr(user, "sub", "")).startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
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
        # 0) Crediti + gating (consumo solo premium)
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
            save_user_credits_state(state)
            billing_mode = "free"

        # ====================================================
        # 1) Calcolo tema natale (ora ignota)
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
            tema_input = tema.get("input") or {}
            tema_input["ora_ignota"] = bool(body.ora_ignota or tema_input.get("ora_ignota", False))
            tema["input"] = tema_input
        except Exception as e:
            logger.exception("[TEMA_AI] Errore nel calcolo del tema natale")
            raise HTTPException(status_code=500, detail=f"Errore nel calcolo del tema natale: {e}")

        # ====================================================
        # 1b) Payload visivo (tema_vis)
        # ====================================================
        try:
            pianeti_decod = tema.get("pianeti_decod") or {}
            asc_mc_case = tema.get("asc_mc_case") or {}
            aspetti = tema.get("natal_aspects") or []

            tema_vis: Dict[str, Any] = {}

            try:
                chart_png_base64 = grafico_tema_natal(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case,
                    aspetti=aspetti,
                )
                tema_vis["chart_png_base64"] = chart_png_base64
            except Exception as ge:
                logger.exception("[TEMA_AI] Errore grafico tema: %r", ge)

            try:
                text_payload = build_tema_text_payload(
                    pianeti_decod=pianeti_decod,
                    asc_mc_case=asc_mc_case,
                    aspetti=aspetti,
                )
                tema_vis["pianeti"] = text_payload.get("pianeti", [])
                tema_vis["aspetti"] = text_payload.get("aspetti", [])
            except Exception as te:
                logger.exception("[TEMA_AI] Errore payload testuale tema_vis: %r", te)

        except Exception as e:
            logger.exception("[TEMA_AI] Errore nella costruzione del tema_vis")
            raise HTTPException(status_code=500, detail=f"Errore nella costruzione del tema_vis: {e}")

        # ====================================================
        # 2) Payload AI
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
            logger.exception("[TEMA_AI] Errore build payload AI")
            raise HTTPException(status_code=500, detail=f"Errore build payload AI: {e}")

        # ====================================================
        # 3) Chiamata Claude
        # ====================================================
        out = call_claude_tema_ai(payload_ai, tier=body.tier)

        # ====================================================
        # 3a) Parse/shape robusto
        # ====================================================
        ai_dbg = out.get("ai_debug") or {}
        raw_text = ai_dbg.get("raw_text") or ""

        r = out.get("result")

        parsed: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None

        if isinstance(r, dict) and "result" in r and ("ai_debug" in r or "error" in r or "parse_error" in r):
            r = r.get("result")

        if isinstance(r, dict) and r.get("error"):
            parsed = None
            parse_error = r.get("parse_error") or r.get("detail") or r.get("error")
        else:
            if isinstance(r, dict):
                parsed = r
            elif isinstance(r, str) and r.strip():
                try:
                    tmp = json.loads(r)
                    if isinstance(tmp, dict) and not tmp.get("error"):
                        parsed = tmp
                    else:
                        parsed = None
                        if isinstance(tmp, dict):
                            parse_error = tmp.get("parse_error") or tmp.get("detail") or tmp.get("error") or "JSON non valido"
                        else:
                            parse_error = "Risposta non in formato JSON (dict)."
                except Exception as e:
                    parsed = None
                    parse_error = f"result string non parseabile: {e}"
            else:
                parsed = None
                parse_error = f"Risposta non in formato JSON (dict). type={type(r).__name__}"

        ai_debug = {"result": parsed, "ai_debug": ai_dbg}

        # ====================================================
        # 3b) Usage extract
        # ====================================================
        usage = {}
        try:
            usage = (ai_dbg.get("usage") or {}) if isinstance(ai_dbg, dict) else {}
        except Exception:
            usage = {}

        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)

        model = None
        latency_ms: Optional[float] = None
        try:
            model = ai_dbg.get("model") if isinstance(ai_dbg, dict) else None
            elapsed_sec = ai_dbg.get("elapsed_sec") if isinstance(ai_dbg, dict) else None
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

        # ====================================================
        # 3c) Log usage SUCCESS
        # ====================================================
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
                paid_credits_after=(state.paid_credits if state is not None else None),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(state.free_tries_used if state is not None else None),
                request_json={**request_log_base, "ai_call": {"tokens_in": tokens_in, "tokens_out": tokens_out}},
            )
        except Exception as e:
            logger.exception("[TEMA_AI] log_usage_event error (success): %r", e)

        # ====================================================
        # 4) JSON non valido / vuoto
        # ====================================================
        if parsed is None:
            return {
                "status": "error",
                "scope": "tema_ai",
                "message": "JSON non valido" if raw_text else "Claude non ha restituito testo.",
                "input": body.dict(by_alias=True),
                "tema_vis": tema_vis,
                "payload_ai": payload_ai,
                "result": {
                    "error": "JSON non valido" if raw_text else "Risposta vuota",
                    "parse_error": parse_error,
                    "raw_preview": raw_text[:500],
                    "content": None,
                },
                "ai_debug": ai_debug,
                "billing": {
                    "mode": billing_mode,
                    "remaining_credits": (state.paid_credits if state is not None else None),
                    "cost_credits": (
                        TEMA_AI_PREMIUM_COST
                        if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                        else 0
                    ),
                    "cost_paid_credits": cost_paid_credits,
                    "cost_free_credits": cost_free_credits,
                },
            }

        # ====================================================
        # 5) OK
        # ====================================================
        return {
            "status": "ok",
            "scope": "tema_ai",
            "input": body.dict(by_alias=True),
            "tema_vis": tema_vis,
            "payload_ai": payload_ai,
            "result": {
                "error": None,
                "parse_error": None,
                "raw_preview": raw_text[:500],
                "content": parsed,
            },
            "ai_debug": ai_debug,
            "billing": {
                "mode": billing_mode,
                "remaining_credits": (state.paid_credits if state is not None else None),
                "cost_credits": (
                    TEMA_AI_PREMIUM_COST
                    if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                    else 0
                ),
                "cost_paid_credits": cost_paid_credits,
                "cost_free_credits": cost_free_credits,
            },
        }

    except HTTPException as exc:
        # log fallimento HTTPException
        try:
            log_usage_event(
                user_id=user.sub,
                feature=TEMA_AI_FEATURE_KEY,
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
                free_credits_used_after=(state.free_tries_used if state is not None else None),
                request_json={
                    **request_log_base,
                    "error": {"type": "http_exception", "status_code": exc.status_code, "detail": exc.detail},
                },
            )
        except Exception as log_err:
            logger.exception("[TEMA_AI] log_usage_event error (HTTPException): %r", log_err)
        raise

    except Exception as exc:
        logger.exception("[TEMA_AI] Errore inatteso in tema_ai_endpoint")
        try:
            log_usage_event(
                user_id=user.sub,
                feature=TEMA_AI_FEATURE_KEY,
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
                free_credits_used_after=(state.free_tries_used if state is not None else None),
                request_json={
                    **request_log_base,
                    "error": {"type": "unexpected_exception", "detail": str(exc)},
                },
            )
        except Exception as log_err:
            logger.exception("[TEMA_AI] log_usage_event error (unexpected): %r", log_err)
        raise