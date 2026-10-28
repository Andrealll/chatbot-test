import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from astrobot_auth.credits_logic import (
    apply_premium_consumption,
    decide_premium_mode,
    load_user_credits_state,
    log_usage_event,
    save_user_credits_state,
)
from astrobot_auth.report_history import save_report_history_with_id
from astrobot_auth.tema_ai_v2_chart_storage import (
    create_tema_ai_v2_chart_signed_url,
    delete_tema_ai_v2_chart,
    upload_tema_ai_v2_chart_base64,
)
from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.tema_vis_v2 import build_tema_vis_v2
from astrobot_core.tema_v2_service import generate_tema_premium_v2
from auth import UserContext, get_current_user


logger = logging.getLogger(__name__)
router = APIRouter()

TEMA_AI_V2_FEATURE_KEY = "tema_ai_v2"
TEMA_AI_V2_PREMIUM_COST = 4
ALLOWED_REPORT_TYPES = {"base", "amore", "carriera", "psicologia", "karma"}
REPORT_TYPE_ALIASES = {
    "default": "base",
    "love": "amore",
    "career": "carriera",
    "psychology": "psicologia",
    "psych": "psicologia",
    "karmic": "karma",
}


class TemaAIV2Request(BaseModel):
    citta: str
    data: str
    ora: Optional[str] = None
    country_code: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    output_mode: Optional[Literal["standard", "dyana_chat"]] = "standard"
    lang: Literal["it", "en"] = "it"
    ora_ignota: bool = False
    report_type: Optional[str] = Field(
        default="base",
        description="base | amore | carriera | psicologia | karma",
    )


def normalize_report_type(report_type: Optional[str]) -> str:
    value = (report_type or "base").strip().lower()
    value = REPORT_TYPE_ALIASES.get(value, value)
    return value if value in ALLOWED_REPORT_TYPES else "base"


def _contains_analisi_key(value: Any) -> bool:
    if isinstance(value, dict):
        return "analisi" in value or any(_contains_analisi_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_analisi_key(item) for item in value)
    return False


def _tema_vis_preview(tema_vis: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Espone nel locked solo il grafico e i metadati gia' calcolati."""
    if not isinstance(tema_vis, dict):
        return None
    return {
        "meta": tema_vis.get("meta") or {},
        **({"chart_url": tema_vis["chart_url"]} if isinstance(tema_vis.get("chart_url"), str) else {}),
    }


def _persistable_tema_vis(tema_vis: Dict[str, Any], chart_storage: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Esclude Base64 dal DB; il riferimento Storage e' opzionale."""
    persisted = {key: value for key, value in tema_vis.items() if key != "chart_png_base64"}
    if chart_storage:
        persisted["chart_storage"] = chart_storage
    return persisted


def _tema_vis_with_signed_url(tema_vis: Dict[str, Any]) -> Dict[str, Any]:
    """Materializza un URL temporaneo senza persisterlo ne' bloccare il report."""
    response = {key: value for key, value in tema_vis.items() if key != "chart_storage"}
    chart_storage = tema_vis.get("chart_storage")
    if isinstance(chart_storage, dict):
        try:
            response["chart_url"] = create_tema_ai_v2_chart_signed_url(chart_storage)
        except Exception:
            logger.warning("[TEMA_AI_V2] grafico Storage non disponibile", exc_info=True)
    return response


@router.post("/tema-ai-v2/generate")
def generate_tema_ai_v2(
    body: TemaAIV2Request,
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> Dict[str, Any]:
    sub = str(getattr(user, "sub", "") or "")
    is_guest = sub.startswith("anon-")
    role = getattr(user, "role", None)
    report_type_norm = normalize_report_type(body.report_type)
    log_email = (
        (body.email or "")
        or (getattr(user, "email", "") or "")
        or (getattr(user, "user_email", "") or "")
        or ((getattr(user, "user_metadata", {}) or {}).get("email", ""))
    ).strip().lower() or None

    request_json: Dict[str, Any] = {
        "body": {
            "citta": body.citta,
            "data": body.data,
            "ora": body.ora,
            "country_code": body.country_code,
            "nome": body.nome,
            "domanda": body.domanda,
            "output_mode": body.output_mode,
            "lang": body.lang,
            "ora_ignota": body.ora_ignota,
            "report_type": report_type_norm,
        },
        "client_source": request.headers.get("x-client-source") or "unknown",
        "client_session": request.headers.get("x-client-session"),
        "feature": TEMA_AI_V2_FEATURE_KEY,
        "tier": "free",
    }
    if is_guest:
        request_json["owner_sub"] = sub

    state = None
    decision = None
    billing_mode = "v2_locked"
    paid_credits_before = None
    free_credits_before = None
    free_tries_used_before = None

    if not is_guest:
        state = load_user_credits_state(user)
        paid_credits_before = state.paid_credits
        free_credits_before = state.free_credits_balance
        free_tries_used_before = state.free_tries_used
        try:
            decision = decide_premium_mode(
                state,
                feature_cost=TEMA_AI_V2_PREMIUM_COST,
            )
            billing_mode = decision.mode
        except HTTPException as exc:
            if not (
                exc.status_code == 402
                and exc.detail == "INSUFFICIENT_CREDITS"
            ):
                raise

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
        tema_input["ora_ignota"] = bool(body.ora_ignota or tema_input.get("ora_ignota", False))
        tema["input"] = tema_input
    except Exception as exc:
        logger.exception("[TEMA_AI_V2] errore calcolo tema natale")
        raise HTTPException(status_code=500, detail=f"Errore nel calcolo del tema natale: {exc}")

    try:
        tema_vis = build_tema_vis_v2(
            tema,
            data=body.data,
            ora=body.ora,
            ora_ignota=body.ora_ignota,
            citta=body.citta,
            lang=body.lang,
        )
    except Exception as exc:
        logger.exception("[TEMA_AI_V2] errore costruzione tema_vis")
        raise HTTPException(status_code=500, detail=f"Errore costruzione visualizzazione Tema V2: {exc}")

    try:
        generated = generate_tema_premium_v2(
            tema,
            nome=body.nome,
            email=log_email,
            domanda=body.domanda,
            lang=body.lang,
            report_type=report_type_norm,
            output_mode=body.output_mode or "standard",
        )
    except Exception as exc:
        logger.exception("[TEMA_AI_V2] errore generazione")
        raise HTTPException(status_code=500, detail=f"Errore generazione Tema V2: {exc}")

    full_report = generated["full_report"]
    locked_report = generated["locked_report"]
    generation = generated["generation"]
    generation_for_storage = {key: value for key, value in generation.items() if key != "raw_text"}

    if decision is not None:
        try:
            apply_premium_consumption(
                state,
                decision,
                feature_cost=TEMA_AI_V2_PREMIUM_COST,
            )
            save_user_credits_state(state)
        except Exception as exc:
            logger.exception("[TEMA_AI_V2] errore consumo crediti")
            raise HTTPException(status_code=500, detail=f"Errore consumo crediti Tema V2: {exc}")

    report_tier = "premium" if decision is not None else "free"
    request_json["tier"] = report_tier
    paid_credits_after = state.paid_credits if state is not None else None
    free_credits_after = state.free_credits_balance if state is not None else None
    free_tries_used_after = state.free_tries_used if state is not None else None
    cost_paid_credits = (
        int(paid_credits_before or 0) - int(paid_credits_after or 0)
        if decision is not None
        else 0
    )
    cost_free_credits = (
        int(free_credits_before or 0) - int(free_credits_after or 0)
        if decision is not None
        else 0
    )

    generation_audit = {
        key: generation.get(key)
        for key in (
            "provider",
            "model",
            "success",
            "schema_valid",
            "retry_count",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cost_usd",
            "elapsed_sec",
            "status",
        )
    }
    usage_log_id = None
    try:
        usage_log_id = log_usage_event(
            user_id=sub,
            feature=TEMA_AI_V2_FEATURE_KEY,
            tier=report_tier,
            role=role,
            is_guest=is_guest,
            billing_mode=billing_mode,
            cost_paid_credits=cost_paid_credits,
            cost_free_credits=cost_free_credits,
            tokens_in=int(generation.get("input_tokens") or 0),
            tokens_out=int(generation.get("output_tokens") or 0),
            model=generation.get("model"),
            latency_ms=(
                float(generation["elapsed_sec"]) * 1000.0
                if isinstance(generation.get("elapsed_sec"), (int, float))
                else None
            ),
            paid_credits_before=paid_credits_before,
            paid_credits_after=paid_credits_after,
            free_credits_used_before=free_tries_used_before,
            free_credits_used_after=free_tries_used_after,
            request_json={**request_json, "generation": generation_audit},
        )
    except Exception as exc:
        logger.exception("[TEMA_AI_V2] log_usage_event error: %r", exc)

    chart_storage = None
    try:
        chart_storage = upload_tema_ai_v2_chart_base64(tema_vis.get("chart_png_base64"))
    except Exception:
        logger.warning("[TEMA_AI_V2] upload grafico Storage non disponibile", exc_info=True)
    persisted_tema_vis = _persistable_tema_vis(tema_vis, chart_storage)

    try:
        report_id = save_report_history_with_id(
            email=log_email or "unknown@guest.local",
            user_id=None if is_guest else sub,
            feature=TEMA_AI_V2_FEATURE_KEY,
            tier=report_tier,
            lang=body.lang,
            report_type=report_type_norm,
            request_json=request_json,
            report_json={
                "full_report": full_report,
                "tema_vis": persisted_tema_vis,
                "generation": generation_for_storage,
            },
            usage_log_id=usage_log_id,
        )
    except Exception as exc:
        logger.exception("[TEMA_AI_V2] save report_history error")
        if chart_storage:
            try:
                delete_tema_ai_v2_chart(chart_storage)
            except Exception:
                logger.warning("[TEMA_AI_V2] cleanup grafico Storage non riuscito", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore salvataggio Tema V2: {exc}")

    tema_vis_response = _tema_vis_with_signed_url(persisted_tema_vis)

    if decision is not None:
        return {
            "report_id": report_id,
            "full_report": full_report,
            "tema_vis": tema_vis_response,
        }

    response = {
        "report_id": report_id,
        "locked_report": locked_report,
        "tema_vis_preview": _tema_vis_preview(tema_vis_response),
    }
    if _contains_analisi_key(response):
        logger.error("[TEMA_AI_V2] locked response contiene analisi")
        raise HTTPException(status_code=500, detail="Locked report non valido")
    return response
