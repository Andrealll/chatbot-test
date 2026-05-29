import json
import logging
from typing import Dict, Any, Optional, Literal
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from pydantic import BaseModel, Field
import os

from astrobot_core.ai_tema_claude import call_claude_tema_ai
from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.grafici import grafico_tema_natal, build_tema_text_payload
from astrobot_core.payload_tema_ai import build_payload_tema_ai
from astrobot_auth.report_history import save_report_history

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
TEMA_AI_PREMIUM_COST = 4


# ==========================
# Request model
# ==========================
class TemaAIRequest(BaseModel):
    citta: str
    data: str
    ora: Optional[str] = None
    country_code: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    output_mode: Optional[Literal["standard", "dyana_chat"]] = "standard"
    lang: Literal["it", "en"] = "it"
    tier: Literal["free", "premium"] = "free"
    ora_ignota: bool = False
    report_type: Optional[str] = Field(
        default="base",
        description="base | amore | carriera | psicologia | karma",
    )
    
class InternalGuestTemaPremiumRequest(BaseModel):
    order_id: str
    email: str
    payload: TemaAIRequest
    
    class Config:
        allow_population_by_field_name = True

ALLOWED_REPORT_TYPES = {"base", "amore", "carriera", "psicologia", "karma"}

REPORT_TYPE_ALIASES = {
    "default": "base",
    "love": "amore",
    "career": "carriera",
    "psychology": "psicologia",
    "psych": "psicologia",
    "karmic": "karma",
}

def normalize_report_type(report_type: Optional[str]) -> str:
    value = (report_type or "base").strip().lower()
    value = REPORT_TYPE_ALIASES.get(value, value)
    if value not in ALLOWED_REPORT_TYPES:
        return "base"
    return value
    
@router.post("/internal/guest/tema-premium")
def internal_guest_tema_premium(
    body: InternalGuestTemaPremiumRequest,
    x_internal_secret: str | None = Header(default=None),
):
    expected = os.getenv("DYANA_INTERNAL_API_SECRET")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    req = body.payload
    req.tier = "premium"
    req.email = body.email

    report_type_norm = normalize_report_type(req.report_type)
    log_email = (body.email or req.email or "").strip().lower() or None

    guest_request_log_base: Dict[str, Any] = {
        "body": {
            **req.dict(by_alias=True),
            "email": log_email,
            "tier": "premium",
            "report_type_normalized": report_type_norm,
        },
        "client_source": "internal_guest_order",
        "client_session": None,
        "email": log_email,
        "tier": "premium",
        "feature": TEMA_AI_FEATURE_KEY,
        "guest_order": {
            "order_id": body.order_id,
            "product_type": "tema",
            "pack_id": "tema_single",
            "mode": "guest_paid",
            "email": log_email,
            "lang": req.lang,
        },
    }

    try:
        ora_raw = (req.ora or "").strip()
        ora_for_tema = None if req.ora_ignota or not ora_raw else ora_raw

        tema = costruisci_tema_natale(
            citta=req.citta,
            data_nascita=req.data,
            ora_nascita=ora_for_tema,
            country_code=req.country_code,
            sistema_case="equal",
        )

        tema_input = tema.get("input") or {}
        tema_input["ora_ignota"] = bool(req.ora_ignota or tema_input.get("ora_ignota", False))
        tema["input"] = tema_input

        pianeti_decod = tema.get("pianeti_decod") or {}
        asc_mc_case = tema.get("asc_mc_case") or {}
        aspetti = tema.get("natal_aspects") or []

        tema_vis: Dict[str, Any] = {
            "meta": {
                "data": req.data,
                "ora": None if req.ora_ignota else req.ora,
                "ora_ignota": bool(req.ora_ignota),
                "citta": req.citta,
            }
        }

        try:
            tema_vis["chart_png_base64"] = grafico_tema_natal(
                pianeti_decod=pianeti_decod,
                asc_mc_case=asc_mc_case,
                aspetti=aspetti,
            )
        except Exception as ge:
            logger.exception("[INTERNAL_GUEST_TEMA] Errore grafico order_id=%r err=%r", body.order_id, ge)

        try:
            text_payload = build_tema_text_payload(
                pianeti_decod=pianeti_decod,
                asc_mc_case=asc_mc_case,
                aspetti=aspetti,
                lang=req.lang,
            )
            tema_vis["pianeti"] = text_payload.get("pianeti", [])
            tema_vis["aspetti"] = text_payload.get("aspetti", [])
        except Exception as te:
            logger.exception("[INTERNAL_GUEST_TEMA] Errore tema_vis testuale order_id=%r err=%r", body.order_id, te)

        payload_ai = build_payload_tema_ai(
            tema=tema,
            nome=req.nome,
            email=log_email,
            domanda=req.domanda,
            lang=req.lang,
            tier="premium",
            report_type=report_type_norm,
            output_mode=req.output_mode,
        )

        out = call_claude_tema_ai(
            payload_ai,
            tier="premium",
            lang=req.lang,
            report_type=report_type_norm,
        )

        ai_dbg = out.get("ai_debug") or {}
        raw_text = ai_dbg.get("raw_text") or ""
        r = out.get("result")

        usage = (ai_dbg.get("usage") or {}) if isinstance(ai_dbg, dict) else {}
        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        elapsed_sec = ai_dbg.get("elapsed_sec") if isinstance(ai_dbg, dict) else None
        model = ai_dbg.get("model") if isinstance(ai_dbg, dict) else None
        latency_ms = (float(elapsed_sec) * 1000.0) if isinstance(elapsed_sec, (int, float)) else None

        parsed = None
        parse_error = None

        if isinstance(r, dict) and "result" in r and ("ai_debug" in r or "error" in r or "parse_error" in r):
            r = r.get("result")

        if isinstance(r, dict) and not r.get("error"):
            parsed = r
        elif isinstance(r, str) and r.strip():
            try:
                tmp = json.loads(r)
                if isinstance(tmp, dict) and not tmp.get("error"):
                    parsed = tmp
                else:
                    parse_error = "Risposta JSON non valida"
            except Exception as e:
                parse_error = f"result string non parseabile: {e}"
        else:
            parse_error = f"Risposta non valida type={type(r).__name__}"

        if parsed is None:
            try:
                log_usage_event(
                    user_id=f"anon-guest-order-{body.order_id}",
                    feature=TEMA_AI_FEATURE_KEY,
                    tier="premium",
                    role="guest",
                    is_guest=True,
                    billing_mode="guest_paid",
                    cost_paid_credits=0,
                    cost_free_credits=0,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model,
                    latency_ms=latency_ms,
                    paid_credits_before=None,
                    paid_credits_after=None,
                    free_credits_used_before=None,
                    free_credits_used_after=None,
                    request_json={
                        **guest_request_log_base,
                        "ai_call": {
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                        },
                        "error": {
                            "type": "parse_error",
                            "detail": parse_error,
                            "raw_preview": raw_text[:500],
                        },
                    },
                )
            except Exception as e:
                logger.exception("[INTERNAL_GUEST_TEMA] log_usage_event error parse order_id=%r err=%r", body.order_id, e)

            return {
                "status": "error",
                "order_id": body.order_id,
                "email": log_email,
                "parse_error": parse_error,
                "raw_preview": raw_text[:500],
                "tema_vis": tema_vis,
            }

        usage_log_id = None
        try:
            usage_log_id = log_usage_event(
                user_id=f"anon-guest-order-{body.order_id}",
                feature=TEMA_AI_FEATURE_KEY,
                tier="premium",
                role="guest",
                is_guest=True,
                billing_mode="guest_paid",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                latency_ms=latency_ms,
                paid_credits_before=None,
                paid_credits_after=None,
                free_credits_used_before=None,
                free_credits_used_after=None,
                request_json={
                    **guest_request_log_base,
                    "ai_call": {
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                    },
                },
            )
        except Exception as e:
            logger.exception("[INTERNAL_GUEST_TEMA] log_usage_event error success order_id=%r err=%r", body.order_id, e)

        logger.warning(
            "[INTERNAL_GUEST_TEMA REPORT_HISTORY TRY] email=%s report_keys=%s",
            log_email,
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
        )

        try:
            save_report_history(
                email=log_email,
                user_id=None,
                feature=TEMA_AI_FEATURE_KEY,
                tier="premium",
                lang=req.lang,
                report_type=report_type_norm,
                request_json=guest_request_log_base,
                report_json=parsed,
                usage_log_id=usage_log_id,
            )
        except Exception as e:
            logger.exception(
                "[INTERNAL_GUEST_TEMA] save_report_history error: %r",
                e,
            )
        return {
            "status": "ok",
            "order_id": body.order_id,
            "email": log_email,
            "input": {
                **req.dict(by_alias=True),
                "email": log_email,
                "tier": "premium",
                "report_type_normalized": report_type_norm,
            },
            "tema_vis": tema_vis,
            "payload_ai": payload_ai,
            "content": parsed,
            "ai_debug": {
                "usage": usage,
                "model": model,
                "elapsed_sec": elapsed_sec,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[INTERNAL_GUEST_TEMA] Errore generazione order_id=%r", body.order_id)

        usage_log_id = None
        try:
            usage_log_id = log_usage_event(
                user_id=f"anon-guest-order-{body.order_id}",
                feature=TEMA_AI_FEATURE_KEY,
                tier="premium",
                role="guest",
                is_guest=True,
                billing_mode="guest_paid",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=None,
                paid_credits_after=None,
                free_credits_used_before=None,
                free_credits_used_after=None,
                request_json={
                    **guest_request_log_base,
                    "error": {
                        "type": "unexpected_exception",
                        "detail": str(e),
                    },
                },
            )
        except Exception as log_err:
            logger.exception("[INTERNAL_GUEST_TEMA] log_usage_event error exception order_id=%r err=%r", body.order_id, log_err)

        raise HTTPException(status_code=500, detail=f"Errore generazione Tema guest: {e}")
        
        
@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    
    print("[TEMA_AI_ROUTE_HIT]", body.output_mode, flush=True)
    sub = str(getattr(user, "sub", "") or "")
    is_guest = sub.startswith("anon-")
    role = getattr(user, "role", None)
    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")
    report_type_norm = normalize_report_type(body.report_type)

    log_email = (
        (body.email or "")
        or (getattr(user, "email", "") or "")
        or (getattr(user, "user_email", "") or "")
        or ((getattr(user, "user_metadata", {}) or {}).get("email", ""))
    ).strip().lower() or None

    request_log_base: Dict[str, Any] = {
        "body": {
            **body.dict(by_alias=True),
            "email": log_email,
            "tier": body.tier,
            "report_type_normalized": report_type_norm,
        },
        "client_source": client_source,
        "client_session": client_session,
        "email": log_email,
        "tier": body.tier,
        "feature": TEMA_AI_FEATURE_KEY,
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
            decision = decide_premium_mode(
                state,
                feature_cost=TEMA_AI_PREMIUM_COST,
            )

            if decision.mode == "premium_plan":
                billing_mode = "premium_plan"
            elif decision.mode == "combined_wallet":
                billing_mode = "combined_wallet"
            elif decision.mode == "free_trial":
                billing_mode = "free_trial"
            else:
                billing_mode = getattr(decision, "mode", None) or "insufficient_credits"
                raise HTTPException(status_code=402, detail="INSUFFICIENT_CREDITS")
                
        else:
            billing_mode = "free"
            decision = None

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
                country_code=body.country_code,
                sistema_case="equal",
            )
            tema_input = tema.get("input") or {}
            tema_input["ora_ignota"] = bool(
                body.ora_ignota or tema_input.get("ora_ignota", False)
            )
            tema["input"] = tema_input
        except Exception as e:
            logger.exception("[TEMA_AI] Errore nel calcolo del tema natale")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo del tema natale: {e}",
            )

        # ====================================================
        # 1b) Payload visivo (tema_vis)
        # ====================================================
        try:
            pianeti_decod = tema.get("pianeti_decod") or {}
            asc_mc_case = tema.get("asc_mc_case") or {}
            aspetti = tema.get("natal_aspects") or []

            tema_vis: Dict[str, Any] = {}
            tema_vis["meta"] = {
                "data": body.data,
                "ora": None if body.ora_ignota else body.ora,
                "ora_ignota": bool(body.ora_ignota),
                "citta": body.citta,
            }
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
                    lang=body.lang,
                )
                tema_vis["pianeti"] = text_payload.get("pianeti", [])
                tema_vis["aspetti"] = text_payload.get("aspetti", [])
                logger.warning("[TEMA_VIS_DEBUG] lang=%r pianeti=%s aspetti=%s keys=%s", body.lang, len(tema_vis.get("pianeti", [])), len(tema_vis.get("aspetti", [])), list(tema_vis.keys()))
            except Exception as te:
                logger.exception("[TEMA_AI] Errore payload testuale tema_vis: %r", te)

        except Exception as e:
            logger.exception("[TEMA_AI] Errore nella costruzione del tema_vis")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nella costruzione del tema_vis: {e}",
            )
        logger.warning("[TEMA_AI][OUTPUT_MODE_DEBUG] body.output_mode=%s", body.output_mode)
        # ====================================================
        # 2) Payload AI
        # ====================================================
        try:
            payload_ai = build_payload_tema_ai(
                tema=tema,
                nome=body.nome,
                email=log_email,
                domanda=body.domanda,
                lang=body.lang,
                tier=body.tier,
                report_type=report_type_norm,
                output_mode=body.output_mode,
            )
        except Exception as e:
            logger.exception("[TEMA_AI] Errore build payload AI")
            raise HTTPException(status_code=500, detail=f"Errore build payload AI: {e}")

        # ====================================================
        # 3) Chiamata Claude
        # ====================================================
        out = call_claude_tema_ai(
            payload_ai,
            tier=body.tier,
            lang=body.lang,
            report_type=report_type_norm,
        )
        
        logger.warning(
            "[TEMA_AI DEBUG OUT] tier=%s report_type=%s out_type=%s out_keys=%s",
            body.tier,
            report_type_norm,
            type(out).__name__,
            list(out.keys()) if isinstance(out, dict) else None,
        )
        logger.warning(
            "[TEMA_AI DEBUG OUT RESULT] %s",
            repr(out.get("result"))[:2000] if isinstance(out, dict) else repr(out)[:2000],
        )
        logger.warning(
            "[TEMA_AI DEBUG OUT AI_DEBUG] %s",
            repr(out.get("ai_debug"))[:2000] if isinstance(out, dict) else None,
)
        # ====================================================
        # 3a) Parse/shape robusto
        # ====================================================
        ai_dbg = out.get("ai_debug") or {}
        raw_text = ai_dbg.get("raw_text") or ""

        r = out.get("result")

        parsed: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None

        if isinstance(r, dict) and "result" in r and (
            "ai_debug" in r or "error" in r or "parse_error" in r
        ):
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
                            parse_error = (
                                tmp.get("parse_error")
                                or tmp.get("detail")
                                or tmp.get("error")
                                or "JSON non valido"
                            )
                        else:
                            parse_error = "Risposta non in formato JSON (dict)."
                except Exception as e:
                    parsed = None
                    parse_error = f"result string non parseabile: {e}"
            else:
                parsed = None
                parse_error = (
                    f"Risposta non in formato JSON (dict). type={type(r).__name__}"
                )

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

        # ====================================================
        # 4) JSON non valido / vuoto
        # ====================================================
        if parsed is None:
            logger.error(
                "[TEMA_AI PARSE FAILED] tier=%s report_type=%s parse_error=%s raw_preview=%s",
                body.tier,
                report_type_norm,
                parse_error,
                raw_text[:1000] if raw_text else None,
            )
            try:
                log_usage_event(
                    user_id=user.sub,
                    feature=TEMA_AI_FEATURE_KEY,
                    tier=body.tier,
                    role=role,
                    is_guest=is_guest,
                    billing_mode=billing_mode,
                    cost_paid_credits=0,
                    cost_free_credits=0,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model,
                    latency_ms=latency_ms,
                    paid_credits_before=paid_credits_before,
                    paid_credits_after=(state.paid_credits if state is not None else None),
                    free_credits_used_before=free_credits_used_before,
                    free_credits_used_after=(state.free_tries_used if state is not None else None),
                    request_json={
                        **request_log_base,
                        "ai_call": {
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                        },
                        "error": {
                            "type": "parse_error",
                            "detail": parse_error,
                            "raw_preview": raw_text[:500],
                        },
                    },
                )
            except Exception as e:
                logger.exception("[TEMA_AI] log_usage_event error (parse_error): %r", e)            
            
            return {
                "status": "error",
                "scope": "tema_ai",
                "message": "JSON non valido" if raw_text else "Claude non ha restituito testo.",
                "input": {
                    **body.dict(by_alias=True),
                    "email": log_email,
                    "tier": body.tier,
                    "report_type_normalized": report_type_norm,
                },
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
                    "remaining_credits": (
                        state.paid_credits if state is not None else None
                    ),
                    "cost_credits": 0,
                    "cost_paid_credits": 0,
                    "cost_free_credits": 0,
                },
            }

        # ====================================================
        # 4b) Consumo premium
        # ====================================================
        if body.tier == "premium" and decision is not None:
            apply_premium_consumption(
                state,
                decision,
                feature_cost=TEMA_AI_PREMIUM_COST,
            )
            save_user_credits_state(state)

            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

        # ====================================================
        # 4c) Billing calcolato
        # ====================================================
        cost_paid_credits = 0
        cost_free_credits = 0
        cost_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "combined_wallet":
                cost_paid_credits = TEMA_AI_PREMIUM_COST
                cost_credits = TEMA_AI_PREMIUM_COST
            elif decision.mode == "free_trial":
                cost_paid_credits = 0
                cost_free_credits = 0
                cost_credits = 0
            elif decision.mode == "premium_plan":
                cost_paid_credits = 0
                cost_free_credits = 0
                cost_credits = 0

        # ====================================================
        # 4d) Log usage SUCCESS
        # ====================================================
        logger.warning(
            "[TEMA_AI BEFORE_USAGE_LOG] tier=%s report_type=%s billing_mode=%s tokens_in=%s tokens_out=%s",
            body.tier,
            report_type_norm,
            billing_mode,
            tokens_in,
            tokens_out,
        )
        
        usage_log_id = None
        try:
            usage_log_id = log_usage_event(
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
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json={
                    **request_log_base,
                    "ai_call": {
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                    },
                },
            )
        except Exception as e:
            logger.exception("[TEMA_AI] log_usage_event error (success): %r", e)

        try:
            save_report_history(
                email=log_email or "unknown@guest.local",
                user_id=None if is_guest else user.sub,
                feature=TEMA_AI_FEATURE_KEY,
                tier=body.tier,
                lang=body.lang,
                report_type=report_type_norm,
                request_json=request_log_base,
                report_json=parsed,
                usage_log_id=usage_log_id,
            )
        except Exception as e:
            logger.exception("[TEMA_AI] save_report_history error: %r", e)
            
        logger.warning(
            "[TEMA_AI REPORT_HISTORY TRY] tier=%s email=%s report_keys=%s",
            body.tier,
            log_email,
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
        )
        # ====================================================
        # 5) OK
        # ====================================================
        return {
            "status": "ok",
            "scope": "tema_ai",
            "input": {
                **body.dict(by_alias=True),
                "report_type_normalized": report_type_norm,
            },
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
                "remaining_credits": (
                    state.paid_credits if state is not None else None
                ),
                "cost_credits": cost_credits,
                "cost_paid_credits": cost_paid_credits,
                "cost_free_credits": cost_free_credits,
            },
        }

    except HTTPException as exc:
        try:
            log_usage_event(
                user_id=user.sub,
                feature=TEMA_AI_FEATURE_KEY,
                tier=getattr(body, "tier", "unknown"),
                role=role,
                is_guest=is_guest,
                billing_mode=f"error:{billing_mode}",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
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
                billing_mode=f"error:{billing_mode}",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
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
            logger.exception("[TEMA_AI] log_usage_event error (unexpected): %r", log_err)
        raise