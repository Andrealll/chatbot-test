
# chatbot_test/routes/routes_oroscopo_ai.py

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, validator

from astrobot_core.ai_oroscopo_claude import call_claude_oroscopo_ai
from astrobot_core.kb.tema_kb import build_kb_oroscopo_glossario
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai
from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_auth.report_history import save_report_history
from auth import UserContext, get_current_user
from astrobot_auth.credits_logic import (
    PremiumDecision,
    apply_premium_consumption,
    decide_premium_mode,
    load_user_credits_state,
    log_usage_event,
    save_user_credits_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oroscopo_ai", tags=["oroscopo_ai"])

Periodo = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]
Engine = Literal["ai"]

OROSCOPO_FEATURE_KEY_PREFIX = "oroscopo_ai"

OROSCOPO_FEATURE_COSTS: Dict[Periodo, int] = {
    "daily": 1,
    "weekly": 2,
    "monthly": 4,
    "yearly": 5,
}

PERIODO_EN_TO_IT = {
    "daily": "giornaliero",
    "weekly": "settimanale",
    "monthly": "mensile",
    "yearly": "annuale",
}

PERIODO_IT_TO_CODE = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}


class OroscopoAIRequest(BaseModel):
    citta: str
    data: str
    ora: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"
    lang: Optional[str] = "it"
    ora_ignota: Optional[bool] = False
    country_code: Optional[str] = None
    window_mode: Optional[Literal["rolling", "fixed"]] = "rolling"
    target_year: Optional[int] = None
    output_mode: Optional[Literal["standard", "dyana_chat"]] = "standard"
    
    
    @validator("data")
    def _validate_data(cls, v: str) -> str:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError("data deve essere in formato YYYY-MM-DD")
        return v

    @validator("ora")
    def _validate_ora(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v

        v = v.strip()
        if v == "":
            return None

        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("ora deve essere in formato HH:MM")

        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("ora deve contenere solo numeri (HH:MM)")

        return v


class OroscopoBaseInput(OroscopoAIRequest):
    pass


class OroscopoResponse(BaseModel):
    status: Literal["ok", "error"]
    scope: Periodo
    engine: Engine
    input: Dict[str, Any]
    engine_result: Optional[Dict[str, Any]] = None
    payload_ai: Optional[Dict[str, Any]] = None
    oroscopo_ai: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    billing: Optional[Dict[str, Any]] = None
    grafico: Optional[Dict[str, Any]] = None
    tabella_aspetti: Optional[List[Dict[str, Any]]] = None


@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str
    periodo: str
    tier: str
    ora_ignota: bool = False
    country_code: Optional[str] = None
    domanda: Optional[str] = None


def _normalize_period(periodo: str) -> Periodo:
    p = periodo.lower().strip()
    mapping = {
        "daily": "daily",
        "giornaliero": "daily",
        "giornaliera": "daily",
        "day": "daily",
        "weekly": "weekly",
        "settimanale": "weekly",
        "week": "weekly",
        "monthly": "monthly",
        "mensile": "monthly",
        "month": "monthly",
        "yearly": "yearly",
        "annuale": "yearly",
        "anno": "yearly",
    }

    if p not in mapping:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Periodo non valido: '{periodo}'. "
                "Usa uno tra: daily, weekly, monthly, yearly."
            ),
        )

    return mapping[p]  # type: ignore[return-value]


def _normalize_tier(raw: Optional[str]) -> Tier:
    if not raw:
        return "free"

    s = raw.strip().lower()
    if s in {"premium", "pro", "paid"}:
        return "premium"

    return "free"


def _normalize_lang(raw: Optional[str]) -> str:
    return "en" if str(raw).lower().strip() == "en" else "it"

def _normalize_output_mode(raw: Optional[str]) -> Literal["standard", "dyana_chat"]:
    return "dyana_chat" if str(raw).strip() == "dyana_chat" else "standard"

def _cleanup_period_block_for_ai(
    period_block: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
    periodo = persona.periodo.lower()
    cleaned = dict(period_block)

    aspetti = list(cleaned.get("aspetti_rilevanti") or [])
    new_aspetti = []
    for a in aspetti:
        tipo = (a.get("aspetto") or a.get("tipo") or "").lower()
        if "quincun" in tipo:
            continue
        new_aspetti.append(a)
    cleaned["aspetti_rilevanti"] = new_aspetti

    pianeti_prevalenti = list(cleaned.get("pianeti_prevalenti") or [])
    if periodo.startswith("ann"):
        new_pianeti = []
        for p in pianeti_prevalenti:
            nome = p.get("pianeta") or p.get("nome") or ""
            if nome == "Luna":
                continue
            new_pianeti.append(p)
        cleaned["pianeti_prevalenti"] = new_pianeti

    return cleaned


def build_debug_kb_hooks(
    period_block: Dict[str, Any],
    profilo_natale: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
    pianeti_prev = period_block.get("pianeti_prevalenti") or []
    aspetti = period_block.get("aspetti_rilevanti") or []

    lines: List[str] = []

    lines.append(f"# Contesto astrologico per {persona.nome}")
    lines.append(f"Periodo: {persona.periodo} — Tier: {persona.tier}")

    if persona.domanda:
        lines.append(f"Domanda utente: {persona.domanda}")

    lines.append("")

    if pianeti_prev:
        lines.append("## Pianeti prevalenti nel periodo")
        for p in pianeti_prev:
            nome = p.get("pianeta") or p.get("nome") or "?"
            score = p.get("score_periodo")
            casa = p.get("casa_natale_transito")
            prima = p.get("prima_occorrenza")

            parts = [f"- {nome}"]
            if casa is not None:
                parts.append(f"in casa {casa}")
            if score is not None:
                parts.append(f"(peso periodo: {round(score, 3)})")
            if prima:
                parts.append(f"prima attivazione: {prima}")

            lines.append(" ".join(parts))

        lines.append("")

    if aspetti:
        lines.append("## Aspetti chiave del periodo")
        for a in aspetti:
            tr = a.get("pianeta_transito") or "?"
            nat = a.get("pianeta_natale") or "?"
            asp = a.get("aspetto") or a.get("tipo") or "?"
            score_rel = a.get("score_rilevanza")
            riga = f"- {tr} {asp} {nat}"

            if score_rel is not None:
                riga += f", rilevanza: {round(score_rel, 3)}"

            lines.append(riga)

        lines.append("")

    if profilo_natale:
        lines.append("## Profilo natale sintetico (pesi pianeti)")
        for nome, peso in sorted(profilo_natale.items(), key=lambda x: -x[1]):
            lines.append(f"- {nome}: peso {peso}")

    combined_md = "\n".join(lines) if lines else ""

    return {
        "pianeti_prevalenti": pianeti_prev,
        "aspetti_rilevanti": aspetti,
        "combined_markdown": combined_md,
    }


def build_oroscopo_struct_from_pipe(
    pipe: Dict[str, Any],
    persona: Persona,
    lang: str,
) -> Dict[str, Any]:
    logger.info("[OROSCOPO][STRUCT] pipe keys: %s", list(pipe.keys()))

    tema = pipe.get("tema_natale") or {}
    profilo_natale = pipe.get("profilo_natale") or {}
    period_plan = pipe.get("period_plan") or {}

    date_range = period_plan.get("date_range") or pipe.get("date_range") or {}
    sottoperiodi = period_plan.get("sottoperiodi") or pipe.get("sottoperiodi") or []

    period_block_raw = {
        "label": period_plan.get("periodo") or persona.periodo,
        "date_range": date_range,
        "sottoperiodi": sottoperiodi,
        "cta": period_plan.get("cta"),
        "window_mode": period_plan.get("window_mode"),
        "target_year": period_plan.get("target_year"),
        "aspetti_rilevanti": pipe.get("aspetti_rilevanti", []),
        "metriche_grafico": pipe.get("metriche_grafico", {}) or {},
        "pianeti_prevalenti": pipe.get("pianeti_prevalenti", []),
    }

    period_block = _cleanup_period_block_for_ai(period_block_raw, persona)

    kb_hooks = build_debug_kb_hooks(
        period_block=period_block,
        profilo_natale=profilo_natale,
        persona=persona,
    )

    kb_glossario_tema: Dict[str, Any] = {}
    try:
        kb_glossario_tema = build_kb_oroscopo_glossario(
            tema=tema,
            period_block=period_block,
        ) or {}

        if kb_glossario_tema:
            logger.info(
                "[OROSCOPO_AI] kb_glossario_tema costruito: "
                "pianeti=%d, segni=%d, case=%d, aspetti=%d, coppie=%d",
                len(kb_glossario_tema.get("pianeti") or {}),
                len(kb_glossario_tema.get("segni") or {}),
                len(kb_glossario_tema.get("case") or {}),
                len(kb_glossario_tema.get("aspetti") or {}),
                len(kb_glossario_tema.get("coppie_rilevanti") or []),
            )
    except Exception as e:
        logger.exception("[OROSCOPO_AI] Errore build_kb_tema_glossario: %r", e)
        kb_glossario_tema = {}

    return {
        "meta": {
            "nome": persona.nome,
            "domanda": persona.domanda,
            "citta": persona.citta,
            "data_nascita": persona.data,
            "ora_nascita": persona.ora,
            "ora_ignota": bool(persona.ora_ignota),
            "tier": persona.tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": lang,
        },
        "tema": tema,
        "profilo_natale": profilo_natale,
        "kb_hooks": kb_hooks,
        "kb_glossario_tema": kb_glossario_tema,
        "periodi": {
            persona.periodo: period_block,
        },
    }


def _call_oroscopo_ai_claude(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    return call_claude_oroscopo_ai(payload_ai)


def _call_oroscopo_ai_claude_with_retry(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = _call_oroscopo_ai_claude(payload_ai)
        if isinstance(result, dict):
            result.setdefault(
                "_ai_retry",
                {
                    "ai_attempts": 1,
                    "ai_retry_used": False,
                    "ai_error_first": None,
                },
            )
        return result
    except Exception as first_exc:
        logger.warning("[OROSCOPO_AI] Prima chiamata AI fallita, retry: %r", first_exc)
        result = _call_oroscopo_ai_claude(payload_ai)
        if isinstance(result, dict):
            result.setdefault(
                "_ai_retry",
                {
                    "ai_attempts": 2,
                    "ai_retry_used": True,
                    "ai_error_first": str(first_exc),
                },
            )
        return result


def _build_grafico_http_from_period_block(
    period_block: Dict[str, Any],
    scope: Periodo,
    payload: OroscopoAIRequest,
    lang: str,
) -> Dict[str, Any]:
    mg = period_block.get("metriche_grafico") or {}
    samples_in = mg.get("samples") or []
    if not isinstance(samples_in, list) or not samples_in:
        return {}

    axis_labels = {
        "it": {
            "emozioni": "Emozioni",
            "relazioni": "Relazioni",
            "lavoro": "Lavoro",
        },
        "en": {
            "emozioni": "Emotions",
            "relazioni": "Relationships",
            "lavoro": "Work",
        },
    }[lang]

    out_samples: List[Dict[str, Any]] = []

    for s in samples_in:
        m = s.get("metrics") or {}
        intens = m.get("intensities") or {}

        out_samples.append(
            {
                "label": s.get("label"),
                "datetime": s.get("datetime"),
                "emozioni": intens.get("emozioni"),
                "relazioni": intens.get("relazioni"),
                "lavoro": intens.get("lavoro"),
            }
        )

    return {
        "scope": scope,
        "meta": {
            "nome": payload.nome,
            "data": payload.data,
            "ora": None if payload.ora_ignota else payload.ora,
            "ora_ignota": bool(payload.ora_ignota),
            "citta": payload.citta,
            "country_code": payload.country_code,
        },
        "axes": ["emozioni", "relazioni", "lavoro"],
        "axis_labels": axis_labels,
        "samples": out_samples,
    }


def _build_tabella_aspetti_http_from_period_block(
    period_block: Dict[str, Any],
    lang: str,
) -> List[Dict[str, Any]]:
    planet_map = {
        "Sole": "Sun",
        "Luna": "Moon",
        "Mercurio": "Mercury",
        "Venere": "Venus",
        "Marte": "Mars",
        "Giove": "Jupiter",
        "Saturno": "Saturn",
        "Urano": "Uranus",
        "Nettuno": "Neptune",
        "Plutone": "Pluto",
    } if lang == "en" else {}

    aspect_map = {
        "congiunzione": "conjunction",
        "trigono": "trine",
        "sestile": "sextile",
        "quadratura": "square",
        "opposizione": "opposition",
    } if lang == "en" else {}

    intensity_map = {
        "debole": "weak",
        "media": "medium",
        "forte": "strong",
    } if lang == "en" else {}

    aspetti = period_block.get("aspetti_rilevanti") or []
    out: List[Dict[str, Any]] = []
    seen = set()

    for a in aspetti:
        parts = str(a.get("chiave") or a.get("key") or "").split("_")
        tp = a.get("pianeta_transito") or (parts[0] if len(parts) >= 3 else None)
        np = a.get("pianeta_natale") or ("_".join(parts[2:]) if len(parts) >= 3 else None)
        asp = a.get("aspetto") or a.get("tipo") or (parts[1] if len(parts) >= 3 else None)

        if not (tp and np and asp):
            continue

        key = (str(tp), str(asp), str(np))
        if key in seen:
            continue
        seen.add(key)

        tp_label = planet_map.get(str(tp), tp)
        np_label = planet_map.get(str(np), np)
        asp_label = aspect_map.get(str(asp).lower(), asp)
        intensita = a.get("intensita_discreta")
        intensita_label = intensity_map.get(str(intensita).lower(), intensita)

        out.append(
            {
                "pianeta_transito": tp_label,
                "pianeta_natale": np_label,
                "aspetto": asp_label,
                "intensita_discreta": intensita_label,
                "persistenza": a.get("persistenza"),
                "score_rilevanza": a.get("score_rilevanza"),
                "label": f"{tp_label} {asp_label} {np_label}",
            }
        )

    return out


def _build_payload_ai(
    scope: Periodo,
    tier: Tier,
    engine_result: Dict[str, Any],
    data_input: OroscopoBaseInput,
    lang: str,
) -> Dict[str, Any]:
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] scope=%s tier=%s nome=%s",
        scope,
        tier,
        data_input.nome,
    )

    pipe = engine_result.get("pipe") or {}
    if not pipe:
        raise RuntimeError(
            "engine_result.pipe mancante: assicurati che "
            "_run_oroscopo_engine_new sia stato chiamato correttamente."
        )

    periodo_ita = PERIODO_EN_TO_IT[scope]

    persona = Persona(
        nome=data_input.nome or "Anonimo",
        citta=data_input.citta,
        data=data_input.data,
        ora=data_input.ora or "00:00",
        periodo=periodo_ita,
        tier=tier,
        ora_ignota=bool(data_input.ora_ignota),
        country_code=data_input.country_code,
        domanda=data_input.domanda,
    )

    oroscopo_struct = build_oroscopo_struct_from_pipe(
        pipe=pipe,
        persona=persona,
        lang=lang,
    )

    engine_result["oroscopo_struct"] = oroscopo_struct

    period_code = PERIODO_IT_TO_CODE.get(periodo_ita, scope)

    payload_ai = build_oroscopo_payload_ai(
        oroscopo_struct=oroscopo_struct,
        lang=lang,
        period_code=period_code,
    )
    payload_ai.setdefault("meta", {})
    payload_ai["meta"]["output_mode"] = _normalize_output_mode(getattr(data_input, "output_mode", None))
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] kb keys: %s",
        list((payload_ai.get("kb") or {}).keys()),
    )

    return payload_ai


def _run_oroscopo_engine_new(
    scope: Periodo,
    tier: Tier,
    data_input: OroscopoBaseInput,
) -> Dict[str, Any]:
    periodo_ita = PERIODO_EN_TO_IT[scope]

    logger.info(
        "[OROSCOPO][ENGINE_NEW] scope=%s ita=%s tier=%s citta=%s data=%s",
        scope,
        periodo_ita,
        tier,
        data_input.citta,
        data_input.data,
    )

    ora_effettiva = data_input.ora
    if bool(data_input.ora_ignota) or not ora_effettiva:
        ora_effettiva = "12:00"

    pipe = run_oroscopo_multi_snapshot(
        periodo=periodo_ita,
        tier=tier,
        citta=data_input.citta,
        data_nascita=data_input.data,
        ora_nascita=ora_effettiva,
        raw_date=date.today(),
        include_node=True,
        include_lilith=True,
        filtra_transito=None,
        filtra_natal=None,
        country_code=data_input.country_code,
        window_mode=getattr(data_input, "window_mode", "rolling"),
        target_year=getattr(data_input, "target_year", None),
    )

    return {
        "engine_version": "new",
        "scope": scope,
        "tier": tier,
        "periodo_ita": periodo_ita,
        "pipe": pipe,
    }


def _run_oroscopo_engine(
    scope: Periodo,
    tier: Tier,
    data_input: OroscopoAIRequest,
) -> Dict[str, Any]:
    return _run_oroscopo_engine_new(
        scope=scope,
        tier=tier,
        data_input=data_input,
    )


def _build_http_blocks(
    engine_result: Dict[str, Any],
    scope: Periodo,
    payload: OroscopoAIRequest,
    lang: str,
) -> tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    grafico_http: Optional[Dict[str, Any]] = None
    tabella_aspetti_http: Optional[List[Dict[str, Any]]] = None

    try:
        oroscopo_struct = engine_result.get("oroscopo_struct") or {}
        periodi_struct = oroscopo_struct.get("periodi") or {}
        period_block_http = (
            list(periodi_struct.values())[0]
            if isinstance(periodi_struct, dict) and periodi_struct
            else None
        )

        if isinstance(period_block_http, dict):
            grafico_http = _build_grafico_http_from_period_block(
                period_block=period_block_http,
                scope=scope,
                payload=payload,
                lang=lang,
            )
            tabella_aspetti_http = _build_tabella_aspetti_http_from_period_block(
                period_block=period_block_http,
                lang=lang,
            )
    except Exception as e:
        logger.exception("[OROSCOPO_AI] Errore costruzione grafico/tabella HTTP: %r", e)

    return grafico_http, tabella_aspetti_http


@router.post(
    "/{periodo}",
    response_model=OroscopoResponse,
    summary="Oroscopo AI (daily/weekly/monthly/yearly, free/premium)",
)
async def oroscopo_ai_endpoint(
    periodo: str,
    payload: OroscopoAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> OroscopoResponse:
    scope: Periodo = _normalize_period(periodo)
    tier: Tier = _normalize_tier(payload.tier)
    lang = _normalize_lang(payload.lang)
    output_mode = _normalize_output_mode(payload.output_mode)

    logger.info(
        "[OROSCOPO_AI] scope=%s tier=%s citta=%s data=%s nome=%s",
        scope,
        tier,
        payload.citta,
        payload.data,
        payload.nome,
    )

    engine: Engine = "ai"
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
        "body": payload.dict(),
        "email": payload.email,
        "client_source": client_source,
        "client_session": client_session,
        "scope": scope,
        "tier": tier,
        "window_mode": payload.window_mode,
        "target_year": payload.target_year,
    }

    state = None
    decision: Optional[PremiumDecision] = None
    billing_mode = "free"

    paid_credits_before: Optional[int] = None
    paid_credits_after: Optional[int] = None
    free_credits_used_before: Optional[int] = None
    free_credits_used_after: Optional[int] = None
    feature_cost: int = 0

    try:
        state = load_user_credits_state(user)

        paid_credits_before = state.paid_credits
        paid_credits_after = state.paid_credits
        free_credits_used_before = state.free_tries_used
        free_credits_used_after = state.free_tries_used

        if tier == "premium":
            feature_cost = OROSCOPO_FEATURE_COSTS.get(scope, 0)
            if feature_cost <= 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Costo oroscopo premium non configurato per periodo '{scope}'.",
                )

            decision = decide_premium_mode(state, feature_cost=feature_cost)

            if decision.mode in {"premium_plan", "combined_wallet", "free_trial"}:
                billing_mode = decision.mode
            else:
                raise HTTPException(status_code=402, detail="INSUFFICIENT_CREDITS")
        else:
            billing_mode = "free"
            decision = None

        engine_result = _run_oroscopo_engine(
            scope=scope,
            tier=tier,
            data_input=payload,
        )

        payload_ai = _build_payload_ai(
            scope=scope,
            tier=tier,
            engine_result=engine_result,
            data_input=payload,
            lang=lang,
        )

        oroscopo_ai = _call_oroscopo_ai_claude_with_retry(payload_ai)

        if tier == "premium" and decision is not None:
            apply_premium_consumption(
                state,
                decision,
                feature_cost=feature_cost,
            )
            save_user_credits_state(state)
            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

        grafico_http, tabella_aspetti_http = _build_http_blocks(
            engine_result=engine_result,
            scope=scope,
            payload=payload,
            lang=lang,
        )

        tokens_in = 0
        tokens_out = 0
        model = None
        latency_ms: Optional[int] = None
        ai_retry = {}

        try:
            if isinstance(oroscopo_ai, dict):
                ai_debug = oroscopo_ai.get("_ai_debug") or oroscopo_ai.get("_ai_usage") or {}
                ai_retry = oroscopo_ai.get("_ai_retry") or {}

                if isinstance(ai_debug, dict):
                    tokens_in = int(ai_debug.get("input_tokens") or 0)
                    tokens_out = int(ai_debug.get("output_tokens") or 0)
                    model = ai_debug.get("model")
                    latency_ms = int((ai_debug.get("elapsed_sec") or 0) * 1000)

                    if not latency_ms and ai_debug.get("duration_ms") is not None:
                        latency_ms = int(ai_debug.get("duration_ms") or 0)
        except Exception:
            logger.exception("[OROSCOPO_AI] Errore lettura _ai_debug/_ai_usage")

        cost_paid_credits = 0
        cost_free_credits = 0
        cost_credits = 0

        if tier == "premium" and decision is not None:
            if decision.mode == "combined_wallet":
                cost_paid_credits = feature_cost
                cost_credits = feature_cost
            elif decision.mode in {"free_trial", "premium_plan"}:
                cost_paid_credits = 0
                cost_free_credits = 0
                cost_credits = 0

        billing = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": billing_mode,
            "remaining_credits": state.paid_credits if state is not None else None,
            "cost_credits": cost_credits,
            "cost_paid_credits": cost_paid_credits,
            "cost_free_credits": cost_free_credits,
        }

        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"
        request_log_success = {
            **request_log_base,
            "feature_cost": feature_cost,
            "billing": billing,
            "ai_call": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "ai_attempts": ai_retry.get("ai_attempts", 1),
                "ai_retry_used": ai_retry.get("ai_retry_used", False),
                "ai_error_first": ai_retry.get("ai_error_first"),
            },
        }

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
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
            logger.exception("[OROSCOPO_AI] log_usage_event error (success): %r", e)
        
        try:
            save_report_history(
                email=payload.email,
                user_id=None if is_guest else user.sub,
                feature=feature_name,
                tier=tier,
                lang=lang,
                report_type=scope,
                request_json=request_log_success,
                report_json=oroscopo_ai,
                usage_log_id=None,
            )
        except Exception as e:
            logger.exception(
                "[OROSCOPO_AI] save_report_history error: %r",
                e,
            )
        
        return OroscopoResponse(
            status="ok",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=engine_result,
            payload_ai=payload_ai,
            oroscopo_ai=oroscopo_ai,
            error=None,
            billing=billing,
            grafico=grafico_http,
            tabella_aspetti=tabella_aspetti_http,
        )

    except HTTPException as exc:
        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
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
                paid_credits_after=state.paid_credits if state is not None else None,
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=state.free_tries_used if state is not None else None,
                request_json={
                    **request_log_base,
                    "feature_cost": feature_cost,
                    "error": {
                        "type": "http_exception",
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    },
                },
            )
        except Exception as log_err:
            logger.exception("[OROSCOPO_AI] log_usage_event error (HTTPException): %r", log_err)

        raise

    except Exception as exc:
        logger.exception("[OROSCOPO_AI] Errore non gestito")
        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
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
                paid_credits_after=state.paid_credits if state is not None else None,
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=state.free_tries_used if state is not None else None,
                request_json={
                    **request_log_base,
                    "feature_cost": feature_cost,
                    "error": {
                        "type": "unexpected_exception",
                        "detail": str(exc),
                    },
                },
            )
        except Exception as log_err:
            logger.exception("[OROSCOPO_AI] log_usage_event error (unexpected): %r", log_err)

        billing_error = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": "error",
            "remaining_credits": state.paid_credits if state else None,
        }

        return OroscopoResponse(
            status="error",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=None,
            payload_ai=None,
            oroscopo_ai=None,
            error=str(exc),
            billing=billing_error,
            grafico=None,
            tabella_aspetti=None,
        )


class InternalGuestOroscopoRequest(BaseModel):
    order_id: str
    email: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.post("/internal/guest/{periodo}")
async def internal_guest_oroscopo_premium(
    periodo: str,
    body: InternalGuestOroscopoRequest,
    request: Request,
) -> Dict[str, Any]:
    internal_secret = os.getenv("DYANA_INTERNAL_API_SECRET")
    received_secret = request.headers.get("x-internal-secret")

    if not internal_secret or received_secret != internal_secret:
        raise HTTPException(status_code=403, detail="Internal secret non valido.")

    scope: Periodo = _normalize_period(periodo)

    payload_dict = dict(body.payload or {})
    payload_dict["tier"] = "premium"
    payload_dict["email"] = body.email or payload_dict.get("email")
    payload_dict["lang"] = _normalize_lang(payload_dict.get("lang"))

    data_input = OroscopoBaseInput(**payload_dict)
    lang = _normalize_lang(data_input.lang)
    tier: Tier = "premium"

    engine_result = _run_oroscopo_engine(
        scope=scope,
        tier=tier,
        data_input=data_input,
    )

    payload_ai = _build_payload_ai(
        scope=scope,
        tier=tier,
        engine_result=engine_result,
        data_input=data_input,
        lang=lang,
    )

    oroscopo_ai = _call_oroscopo_ai_claude_with_retry(payload_ai)

    grafico_http, tabella_aspetti_http = _build_http_blocks(
        engine_result=engine_result,
        scope=scope,
        payload=data_input,
        lang=lang,
    )

    try:
        save_report_history(
            email=body.email,
            user_id=None,
            feature=f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}",
            tier="premium",
            lang=lang,
            report_type=scope,
            request_json={
                "order_id": body.order_id,
                "payload": payload_dict,
            },
            report_json=oroscopo_ai,
            usage_log_id=None,
        )
    except Exception as e:
        logger.exception(
            "[INTERNAL_GUEST_OROSCOPO] save_report_history error: %r",
            e,
        )
    
    return {
        "status": "ok",
        "order_id": body.order_id,
        "scope": scope,
        "engine": "ai",
        "input": data_input.dict(),
        "engine_result": engine_result,
        "payload_ai": payload_ai,
        "oroscopo_ai": oroscopo_ai,
        "billing": {
            "tier": "premium",
            "scope": scope,
            "mode": "guest_paid",
            "cost_credits": 0,
        },
        "grafico": grafico_http,
        "tabella_aspetti": tabella_aspetti_http,
    }
