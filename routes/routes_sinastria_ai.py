import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request, Header
from pydantic import BaseModel

from astrobot_core.kb.tema_kb import build_aspetti_natali_con_kb
from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai
from astrobot_core.grafici import TEMA_VIS_I18N

# --- IMPORT PER AUTH + CREDITI (come tema_ai) ---
from auth import get_current_user, UserContext
from astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)

import os
import json

logger = logging.getLogger(__name__)

print(">>> DEBUG: routes_sinastria_ai COMPLETA LOADED <<<")

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])

# ==========================
#  Costi in crediti (parametrici)
# ==========================
SINASTRIA_FEATURE_KEY = "sinastria_ai"
SINASTRIA_PREMIUM_COST = 5


# ==========================
#  Request models
# ==========================
class Persona(BaseModel):
    citta: str
    data: str
    ora: str
    country_code: Optional[str] = None
    nome: Optional[str] = None
    ora_ignota: bool = False

class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: str = "free"
    lang: str = "it"
    domanda:  Optional[str] = None
    report_type: Optional[str] = None
    email: Optional[str] = None
    output_mode: Optional[str] = None

def _extract_log_email(body: Any = None, user: Any = None) -> Optional[str]:
    meta = getattr(user, "user_metadata", None) or {}
    values = [
        getattr(body, "email", None),
        getattr(user, "email", None),
        getattr(user, "user_email", None),
        meta.get("email") if isinstance(meta, dict) else None,
    ]
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _extract_ai_debug(out: Any) -> Dict[str, Any]:
    if not isinstance(out, dict):
        return {}
    dbg = out.get("ai_debug") or out.get("debug")
    if isinstance(dbg, dict):
        return dbg
    meta = out.get("meta")
    if isinstance(meta, dict):
        dbg = meta.get("ai_debug") or meta.get("debug")
        if isinstance(dbg, dict):
            return dbg
    inner = out.get("result")
    if isinstance(inner, dict):
        dbg = inner.get("ai_debug") or inner.get("debug")
        if isinstance(dbg, dict):
            return dbg
    return {}


def _extract_usage(out: Any) -> tuple[int, int, Optional[str], Optional[float], str]:
    dbg = _extract_ai_debug(out)
    usage = dbg.get("usage") or {}
    tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    tokens_out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    model = dbg.get("model")
    elapsed_sec = dbg.get("elapsed_sec") or dbg.get("latency_sec")
    latency_ms = float(elapsed_sec) * 1000.0 if isinstance(elapsed_sec, (int, float)) else None
    raw_text = dbg.get("raw_text") or ""
    return int(tokens_in or 0), int(tokens_out or 0), model, latency_ms, raw_text


def _parse_sinastria_ai(out: Any) -> tuple[Optional[Dict[str, Any]], Optional[str], str]:
    raw_text = _extract_ai_debug(out).get("raw_text") or ""
    r = out.get("result") if isinstance(out, dict) else out

    if isinstance(r, dict) and "result" in r and ("ai_debug" in r or "error" in r or "parse_error" in r):
        r = r.get("result")

    if isinstance(r, dict) and not r.get("error"):
        return r, None, raw_text

    if isinstance(r, str) and r.strip():
        try:
            tmp = json.loads(r)
            if isinstance(tmp, dict) and not tmp.get("error"):
                return tmp, None, raw_text
            return None, "Risposta JSON non valida", raw_text
        except Exception as e:
            return None, f"result string non parseabile: {e}", raw_text

    return None, f"Risposta non valida type={type(r).__name__}", raw_text

def _call_sinastria_ai_with_retry(payload_ai: Dict[str, Any], report_type: str, max_attempts: int = 2):
    last = {"out": None, "parsed": None, "parse_error": None, "raw_text": "", "tokens_in": 0, "tokens_out": 0, "model": None, "latency_ms": None}
    attempts = []

    for attempt in range(1, max_attempts + 1):
        try:
            out = call_claude_sinastria_ai(payload_ai, report_type=report_type)
            tokens_in, tokens_out, model, latency_ms, raw_text = _extract_usage(out)
            parsed, parse_error, raw_text = _parse_sinastria_ai(out)
            attempts.append({"attempt": attempt, "ok": parsed is not None, "parse_error": parse_error})
            last = {"out": out, "parsed": parsed, "parse_error": parse_error, "raw_text": raw_text, "tokens_in": tokens_in, "tokens_out": tokens_out, "model": model, "latency_ms": latency_ms}
            if parsed is not None:
                return last, attempts
        except Exception as e:
            attempts.append({"attempt": attempt, "ok": False, "exception": str(e)})
            if attempt == max_attempts:
                raise

    return last, attempts
# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/")
async def sinastria_ai_endpoint(
    body: SinastriaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    log_email = _extract_log_email(body, user)

    request_log_base: Dict[str, Any] = {
        "body": body.dict(),
        "client_source": client_source,
        "client_session": client_session,
        "email": log_email,
    }

    lang = (body.lang or "it").strip().lower()
    if lang not in ("it", "en"):
        lang = "it"

    report_type = (body.report_type or "").strip().lower()

    if report_type not in {"amore", "amicizia", "famiglia", "lavoro"}:
        report_type = "amore"
    
    output_mode = "dyana_chat" if str(body.output_mode or "").strip().lower() == "dyana_chat" else "standard"

    state = None
    decision: Optional[PremiumDecision] = None
    billing_mode = "free"

    paid_credits_before: Optional[int] = None
    paid_credits_after: Optional[int] = None
    free_credits_used_before: Optional[int] = None
    free_credits_used_after: Optional[int] = None

    try:
        # ====================================================
        # 0) STATO CREDITI + GATING
        # ====================================================
        state = load_user_credits_state(user)

        paid_credits_before = state.paid_credits
        free_credits_used_before = state.free_tries_used
        paid_credits_after = state.paid_credits
        free_credits_used_after = state.free_tries_used

        if body.tier == "premium":
            decision = decide_premium_mode(
                state,
                feature_cost=SINASTRIA_PREMIUM_COST,
            )

            if decision.mode == "premium_plan":
                billing_mode = "premium_plan"
            elif decision.mode == "combined_wallet":
                billing_mode = "combined_wallet"
            elif decision.mode == "free_trial":
                billing_mode = "free_trial"
            else:
                raise HTTPException(
                    status_code=402,
                    detail="INSUFFICIENT_CREDITS",
                )
        else:
            billing_mode = "free"
            decision = None

        # ====================================================
        # 1) Parsing datetime
        # ====================================================
        def _build_dt(data_str: str, ora_str: str, ora_ignota: bool) -> datetime:
            if ora_ignota or not ora_str:
                return datetime.fromisoformat(f"{data_str} 12:00")
            return datetime.fromisoformat(f"{data_str} {ora_str}")

        try:
            dt_A = _build_dt(body.A.data, body.A.ora, body.A.ora_ignota)
            dt_B = _build_dt(body.B.data, body.B.ora, body.B.ora_ignota)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato data/ora non valido: {e}",
            )

        # ====================================================
        # 1b) Calcolo sinastria
        # ====================================================
        try:
            sinastria_data = calcola_sinastria(
                dt_A,
                body.A.citta,
                dt_B,
                body.B.citta,
                country_code_A=body.A.country_code,
                country_code_B=body.B.country_code,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nel calcolo della sinastria")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo della sinastria: {e}",
            )

        # ====================================================
        # 1c) Payload visivo per UI
        # ====================================================
        lang = "en" if str(body.lang or "").strip().lower() == "en" else "it"
        copy = TEMA_VIS_I18N[lang]
        zodiac_it = TEMA_VIS_I18N["it"]["zodiac"]
        zodiac_en = TEMA_VIS_I18N["en"]["zodiac"]
        zodiac_map = dict(zip(zodiac_it, zodiac_en)) if lang == "en" else dict(zip(zodiac_it, zodiac_it))
        def _build_vis_tema(
            tema_dict: Dict[str, Any],
            nome_fallback: str,
            ora_ignota: bool,
        ) -> Dict[str, Any]:
            if not isinstance(tema_dict, dict):
                tema_dict = {}

            pianeti_decod = tema_dict.get("pianeti_decod") or {}
            pianeti_vis = []

            if isinstance(pianeti_decod, dict):
                for nome, info in pianeti_decod.items():
                    if not isinstance(info, dict):
                        continue

                    if ora_ignota and nome == "Ascendente":
                        continue

                    segno = info.get("segno") or info.get("segno_nome")
                    nome_label = copy["planets"].get(nome, nome)
                    segno_label = zodiac_map.get(segno, segno)
                    gradi_segno = (
                        info.get("gradi_segno")
                        or info.get("grado_segno")
                        or info.get("gradi")
                    )

                    item = {
                        "nome": nome,
                        "nome_label": nome_label,
                        "segno": segno,
                        "segno_label": segno_label,
                        "gradi_segno": gradi_segno,
                    }

                    if not ora_ignota:
                        item["casa"] = info.get("casa")

                    pianeti_vis.append(item)

            return {
                "nome": nome_fallback,
                "data": tema_dict.get("data"),
                "citta": None,
                "pianeti": pianeti_vis,
            }

        temaA_raw = sinastria_data.get("A") or {}
        temaB_raw = sinastria_data.get("B") or {}
        sinastria_inner = sinastria_data.get("sinastria", {}) or {}

        temaA_vis = _build_vis_tema(
            temaA_raw,
            body.A.nome or "Persona A",
            body.A.ora_ignota,
        )
        temaB_vis = _build_vis_tema(
            temaB_raw,
            body.B.nome or "Persona B",
            body.B.ora_ignota,
        )

        aspetti_top_raw = sinastria_inner.get("top_stretti", []) or []
        aspetti_vis = []
        for asp in aspetti_top_raw:
            if not isinstance(asp, dict):
                continue
            p1 = asp.get("pianeta1")
            p2 = asp.get("pianeta2")
            tipo = asp.get("tipo")
            orb = asp.get("orb", asp.get("delta"))
            try:
                orb_str = f"{float(orb):.1f}°" if isinstance(orb, (int, float)) else None
            except Exception:
                orb_str = None
                
            p1_label = copy["planets"].get(p1, p1)
            p2_label = copy["planets"].get(p2, p2)
            tipo_key = str(tipo or "").lower()
            tipo_label = copy["aspects"].get(tipo_key, tipo)
            
            label = None
            if p1 and p2 and tipo:
                if orb_str:
                    label = f"{p1_label} {tipo_label} {p2_label} (orb {orb_str})"
                else:
                    label = f"{p1_label} {tipo_label} {p2_label}"

            aspetti_vis.append(
                {
                    "pianetaA": p1,
                    "pianetaB": p2,
                    "tipo": tipo,
                    "orb": orb,
                    "label": label,
                    "tipo_label": tipo_label,
                }
            )

        sinastria_vis: Dict[str, Any] = {
            "A": {**temaA_vis, "citta": body.A.citta},
            "B": {**temaB_vis, "citta": body.B.citta},
            "aspetti_top": aspetti_vis,
        }

        # ====================================================
        # 2) Build payload AI
        # ====================================================
        try:
            sinastria_inner = sinastria_data.get("sinastria", {}) or {}
            temaA = sinastria_data.get("A") or {}
            temaB = sinastria_data.get("B") or {}

            def _compress_tema(tema: Dict[str, Any], ora_ignota: bool) -> Dict[str, Any]:
                pianeti_decod = tema.get("pianeti_decod") or {}
                natal_houses = tema.get("natal_houses") or {}

                pianeti_compatti: Dict[str, Any] = {}

                if isinstance(pianeti_decod, dict):
                    for nome, info in pianeti_decod.items():
                        if not isinstance(info, dict):
                            continue

                        if ora_ignota and nome == "Ascendente":
                            continue

                        segno = info.get("segno")
                        item: Dict[str, Any] = {"segno": segno}

                        if not ora_ignota:
                            casa_val = info.get("casa")
                            if casa_val is None and isinstance(natal_houses, dict):
                                casa_val = natal_houses.get(nome)
                            item["casa"] = casa_val

                        pianeti_compatti[nome] = item

                return {
                    "data": tema.get("data"),
                    "pianeti": pianeti_compatti,
                }

            top_stretti_raw = sinastria_inner.get("top_stretti", []) or []

            if body.A.ora_ignota or body.B.ora_ignota:
                filtered = []
                for asp in top_stretti_raw:
                    if not isinstance(asp, dict):
                        continue
                    p1 = asp.get("pianeta1")
                    p2 = asp.get("pianeta2")
                    if p1 == "Ascendente" or p2 == "Ascendente":
                        continue
                    filtered.append(asp)
                top_stretti_raw = filtered

            top_stretti_compatti = []
            for asp in top_stretti_raw:
                if not isinstance(asp, dict):
                    continue
                top_stretti_compatti.append(
                    {
                        "pianetaA": asp.get("pianeta1"),
                        "pianetaB": asp.get("pianeta2"),
                        "tipo": asp.get("tipo"),
                        "orb": asp.get("orb", asp.get("delta")),
                    }
                )

            sinastria_compatta: Dict[str, Any] = {
                "A": _compress_tema(temaA, body.A.ora_ignota),
                "B": _compress_tema(temaB, body.B.ora_ignota),
                "top_stretti": top_stretti_compatti,
            }

            kb_glossario_aspetti: Optional[Dict[str, Any]] = None
            if body.tier == "premium":
                try:
                    kb_rows = build_aspetti_natali_con_kb(
                        {"natal_aspects": top_stretti_raw}
                    )

                    pianeti_map: Dict[str, str] = {}
                    aspetti_map: Dict[str, str] = {}
                    coppie_rilevanti = []

                    for row in kb_rows:
                        if not isinstance(row, dict):
                            continue

                        p1 = row.get("pianeta1")
                        p2 = row.get("pianeta2")
                        tipo = row.get("tipo")
                        orb = row.get("orb")

                        desc_p1 = row.get("descrizione_pianeta1")
                        desc_p2 = row.get("descrizione_pianeta2")
                        desc_asp = row.get("descrizione_aspetto")

                        if p1 and desc_p1 and p1 not in pianeti_map:
                            pianeti_map[p1] = desc_p1
                        if p2 and desc_p2 and p2 not in pianeti_map:
                            pianeti_map[p2] = desc_p2
                        if tipo and desc_asp and tipo not in aspetti_map:
                            aspetti_map[tipo] = desc_asp

                        if p1 and p2 and tipo:
                            coppie_rilevanti.append(
                                {
                                    "pianeta1": p1,
                                    "pianeta2": p2,
                                    "tipo": tipo,
                                    "orb": orb,
                                }
                            )

                    if pianeti_map or aspetti_map or coppie_rilevanti:
                        kb_glossario_aspetti = {
                            "pianeti": pianeti_map,
                            "aspetti": aspetti_map,
                            "coppie_rilevanti": coppie_rilevanti,
                        }

                except Exception as kb_err:
                    logger.exception(
                        "[SINASTRIA_AI] Errore costruendo kb_aspetti_sinastria (glossario): %r",
                        kb_err,
                    )
                    kb_glossario_aspetti = None

            payload_ai: Dict[str, Any] = {
                "meta": {
                    "scope": "sinastria_ai",
                    "tier": body.tier,
                    "lingua": lang,
                    "report_type": report_type,
                    "output_mode": output_mode,
                    "domanda": body.domanda,
                    "nome_A": body.A.nome,
                    "nome_B": body.B.nome,
                    "ora_ignota_A": body.A.ora_ignota,
                    "ora_ignota_B": body.B.ora_ignota,
                },
                "sinastria": sinastria_compatta,
            }

            if kb_glossario_aspetti:
                payload_ai["kb_aspetti_sinastria"] = kb_glossario_aspetti

            try:
                payload_str = json.dumps(payload_ai, ensure_ascii=False)
                payload_size = len(payload_str)

                meta_len = len(json.dumps(payload_ai.get("meta", {}), ensure_ascii=False))
                sinastria_len = len(json.dumps(payload_ai.get("sinastria", {}), ensure_ascii=False))
                kb_len = len(
                    json.dumps(payload_ai.get("kb_aspetti_sinastria", {}), ensure_ascii=False)
                ) if payload_ai.get("kb_aspetti_sinastria") else 0

                print("\n[DEBUG SINASTRIA PAYLOAD] CHAR COUNTS:")
                print(f"  - payload_total: {payload_size} char")
                print(f"  - meta: {meta_len} char")
                print(f"  - sinastria: {sinastria_len} char")
                print(f"  - kb_aspetti_sinastria: {kb_len} char")

                debug_dir = os.path.join("debug_payloads", "sinastria_ai")
                os.makedirs(debug_dir, exist_ok=True)

                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"payload_sinastria_{body.tier}_{ts}.json"
                filepath = os.path.join(debug_dir, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(payload_str)

                print(f"[DEBUG SINASTRIA PAYLOAD] payload salvato su: {filepath}")
            except Exception as dbg_err:
                print(f"[DEBUG SINASTRIA PAYLOAD] ERRORE debug payload: {dbg_err}")

        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nella costruzione del payload AI")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nella costruzione del payload AI: {e}",
            )

        # ====================================================
        # 3) Chiamata Claude
        # ====================================================
        ai_result, ai_attempts = _call_sinastria_ai_with_retry(payload_ai, report_type=report_type)

        sinastria_ai = ai_result["out"]
        parsed_ai = ai_result["parsed"]
        parse_error = ai_result["parse_error"]
        raw_text = ai_result["raw_text"]
        tokens_in = ai_result["tokens_in"]
        tokens_out = ai_result["tokens_out"]
        model = ai_result["model"]
        latency_ms = ai_result["latency_ms"]

        if parsed_ai is None:
            try:
                log_usage_event(
                    user_id=user.sub,
                    feature=SINASTRIA_FEATURE_KEY,
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
                    paid_credits_after=paid_credits_before,
                    free_credits_used_before=free_credits_used_before,
                    free_credits_used_after=free_credits_used_before,
                    request_json={
                        **request_log_base,
                        "ai_call": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        "ai_attempts": ai_attempts,
                        "error": {
                            "type": "parse_error",
                            "detail": parse_error,
                            "raw_preview": raw_text[:500],
                        },
                    },
                )
            except Exception as e:
                logger.exception("[SINASTRIA_AI] log_usage_event error (parse_error): %r", e)

            return {
                "status": "error",
                "scope": "sinastria_ai",
                "input": body.dict(),
                "payload_ai": payload_ai,
                "sinastria_ai": {
                    "result": {"content": None},
                    "error": "parse_error",
                    "parse_error": parse_error,
                    "raw_preview": raw_text[:500],
                },
                "sinastria_vis": sinastria_vis,
                "chart_sinastria_base64": None,
                "billing": {
                    "mode": billing_mode,
                    "remaining_credits": state.paid_credits if state is not None else None,
                    "cost_credits": 0,
                    "cost_paid_credits": 0,
                    "cost_free_credits": 0,
                },
            }

        cost_paid_credits = 0
        cost_free_credits = 0
        cost_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "combined_wallet":
                cost_paid_credits = SINASTRIA_PREMIUM_COST
                cost_credits = SINASTRIA_PREMIUM_COST
            elif decision.mode == "free_trial":
                cost_free_credits = SINASTRIA_PREMIUM_COST
                cost_credits = SINASTRIA_PREMIUM_COST

            apply_premium_consumption(
                state,
                decision,
                feature_cost=SINASTRIA_PREMIUM_COST,
            )
            save_user_credits_state(state)

            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

        sinastria_ai["result"] = parsed_ai

        request_log_success = {
            **request_log_base,
            "ai_call": {"tokens_in": tokens_in, "tokens_out": tokens_out},
            "ai_attempts": ai_attempts,
        }

        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
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
                paid_credits_after=state.paid_credits if state is not None else None,
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=state.free_tries_used if state is not None else None,
                request_json=request_log_success,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] log_usage_event error (success): %r", e)
            
        # ====================================================
        # 3a) Grafico sinastria
        # ====================================================
        chart_sinastria_base64 = None
        try:
            from astrobot_core.grafici import genera_carta_sinastria

            pianeti_A_decod = sinastria_data["A"]["pianeti_decod"]
            pianeti_B_decod = sinastria_data["B"]["pianeti_decod"]

            aspetti_raw = sinastria_data.get("sinastria", {}).get("aspetti_AB", []) or []

            if body.A.ora_ignota or body.B.ora_ignota:
                tmp = []
                for asp in aspetti_raw:
                    if not isinstance(asp, dict):
                        continue
                    p1 = asp.get("pianeta1")
                    p2 = asp.get("pianeta2")
                    if p1 == "Ascendente" or p2 == "Ascendente":
                        continue
                    tmp.append(asp)
                aspetti_raw = tmp

            aspetti_AB = []
            for asp in aspetti_raw:
                if not isinstance(asp, dict):
                    continue
                aspetti_AB.append(
                    {
                        "pianetaA": asp.get("pianeta1"),
                        "pianetaB": asp.get("pianeta2"),
                        "tipo": asp.get("tipo"),
                        "orb": asp.get("orb", asp.get("delta")),
                        "delta": asp.get("delta"),
                    }
                )

            chart_sinastria_base64 = genera_carta_sinastria(
                pianeti_A_decod=pianeti_A_decod,
                pianeti_B_decod=pianeti_B_decod,
                aspetti_AB=aspetti_AB,
                nome_A=body.A.nome or "A",
                nome_B=body.B.nome or "B",
            )

        except KeyError as e:
            logger.warning(
                "[SINASTRIA_AI] Chiavi mancanti per il grafico di sinastria: %r",
                e,
            )
            chart_sinastria_base64 = None
        except Exception:
            logger.exception(
                "[SINASTRIA_AI] Errore nella generazione del grafico di sinastria"
            )
            chart_sinastria_base64 = None

        # ====================================================
        # 4) Risposta finale
        # ====================================================
        return {
            "status": "ok",
            "scope": "sinastria_ai",
            "input": body.dict(),
            "payload_ai": payload_ai,
            "sinastria_ai": sinastria_ai,
            "sinastria_vis": sinastria_vis,
            "chart_sinastria_base64": chart_sinastria_base64,
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
                feature=SINASTRIA_FEATURE_KEY,
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
                "[SINASTRIA_AI] log_usage_event error (HTTPException): %r",
                log_err,
            )
        raise

    except Exception as exc:
        logger.exception("[SINASTRIA_AI] Errore inatteso in sinastria_ai_endpoint")
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
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
                "[SINASTRIA_AI] log_usage_event error (unexpected): %r",
                log_err,
            )
        raise
        
        
class InternalGuestSinastriaRequest(BaseModel):
    order_id: str
    email: str
    payload: SinastriaAIRequest


@router.post("/internal/guest/sinastria-premium")
def internal_guest_sinastria(
    body: InternalGuestSinastriaRequest,
    x_internal_secret: str | None = Header(default=None),
):
    expected = os.getenv("DYANA_INTERNAL_API_SECRET")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    req = body.payload
    req.tier = "premium"

    lang = (req.lang or "it").strip().lower()
    if lang not in ("it", "en"):
        lang = "it"

    report_type = (req.report_type or "").strip().lower()
    if report_type not in {"amore", "amicizia", "famiglia", "lavoro"}:
        report_type = "amore"
    output_mode = "dyana_chat" if str(req.output_mode or "").strip().lower() == "dyana_chat" else "standard"
    try:
        def _build_dt(data_str: str, ora_str: str, ora_ignota: bool) -> datetime:
            if ora_ignota or not ora_str:
                return datetime.fromisoformat(f"{data_str} 12:00")
            return datetime.fromisoformat(f"{data_str} {ora_str}")

        dt_A = _build_dt(req.A.data, req.A.ora, req.A.ora_ignota)
        dt_B = _build_dt(req.B.data, req.B.ora, req.B.ora_ignota)

        sinastria_data = calcola_sinastria(
            dt_A,
            req.A.citta,
            dt_B,
            req.B.citta,
            country_code_A=req.A.country_code,
            country_code_B=req.B.country_code,
        )

        sinastria_inner = sinastria_data.get("sinastria", {}) or {}
        temaA = sinastria_data.get("A") or {}
        temaB = sinastria_data.get("B") or {}

        def _compress_tema(tema: Dict[str, Any], ora_ignota: bool) -> Dict[str, Any]:
            pianeti_decod = tema.get("pianeti_decod") or {}
            natal_houses = tema.get("natal_houses") or {}
            pianeti_compatti: Dict[str, Any] = {}

            if isinstance(pianeti_decod, dict):
                for nome, info in pianeti_decod.items():
                    if not isinstance(info, dict):
                        continue
                    if ora_ignota and nome == "Ascendente":
                        continue

                    item: Dict[str, Any] = {"segno": info.get("segno")}

                    if not ora_ignota:
                        casa_val = info.get("casa")
                        if casa_val is None and isinstance(natal_houses, dict):
                            casa_val = natal_houses.get(nome)
                        item["casa"] = casa_val

                    pianeti_compatti[nome] = item

            return {
                "data": tema.get("data"),
                "pianeti": pianeti_compatti,
            }

        top_stretti_raw = sinastria_inner.get("top_stretti", []) or []

        if req.A.ora_ignota or req.B.ora_ignota:
            top_stretti_raw = [
                asp for asp in top_stretti_raw
                if isinstance(asp, dict)
                and asp.get("pianeta1") != "Ascendente"
                and asp.get("pianeta2") != "Ascendente"
            ]

        top_stretti_compatti = []
        for asp in top_stretti_raw:
            if isinstance(asp, dict):
                top_stretti_compatti.append({
                    "pianetaA": asp.get("pianeta1"),
                    "pianetaB": asp.get("pianeta2"),
                    "tipo": asp.get("tipo"),
                    "orb": asp.get("orb", asp.get("delta")),
                })

        payload_ai: Dict[str, Any] = {
            "meta": {
                "scope": "sinastria_ai",
                "tier": "premium",
                "lingua": lang,
                "report_type": report_type,
                "output_mode": output_mode,
                "domanda": req.domanda,
                "nome_A": req.A.nome,
                "nome_B": req.B.nome,
                "ora_ignota_A": req.A.ora_ignota,
                "ora_ignota_B": req.B.ora_ignota,
            },
            "sinastria": {
                "A": _compress_tema(temaA, req.A.ora_ignota),
                "B": _compress_tema(temaB, req.B.ora_ignota),
                "top_stretti": top_stretti_compatti,
            },
        }

        ai_result, ai_attempts = _call_sinastria_ai_with_retry(payload_ai, report_type=report_type)

        sinastria_ai = ai_result["out"]
        parsed_ai = ai_result["parsed"]
        parse_error = ai_result["parse_error"]
        raw_text = ai_result["raw_text"]
        tokens_in = ai_result["tokens_in"]
        tokens_out = ai_result["tokens_out"]
        model = ai_result["model"]
        latency_ms = ai_result["latency_ms"]
        request_log_base = {
            "body": req.dict(),
            "email": body.email.strip().lower(),
            "order_id": body.order_id,
            "client_source": "internal_guest_order",
        }

        if parsed_ai is None:
            try:
                log_usage_event(
                    user_id=f"guest-order-{body.order_id}",
                    feature=SINASTRIA_FEATURE_KEY,
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
                    request_json={
                        **request_log_base,
                        "ai_call": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        "ai_attempts": ai_attempts,
                        "error": {
                            "type": "parse_error",
                            "detail": parse_error,
                            "raw_preview": raw_text[:500],
                        },
                    },
                )
            except Exception as log_err:
                logger.exception("[INTERNAL_GUEST_SINASTRIA] log_usage_event parse_error: %r", log_err)

            return {
                "status": "error",
                "order_id": body.order_id,
                "email": body.email,
                "parse_error": parse_error,
                "raw_preview": raw_text[:500],
                "payload_ai": payload_ai,
                "sinastria_ai": {"result": {"content": None}},
            }

        sinastria_ai["result"] = parsed_ai

        try:
            log_usage_event(
                user_id=f"guest-order-{body.order_id}",
                feature=SINASTRIA_FEATURE_KEY,
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
                request_json={
                    **request_log_base,
                    "ai_call": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                    "ai_attempts": ai_attempts,
                },
            )
        except Exception as log_err:
            logger.exception("[INTERNAL_GUEST_SINASTRIA] log_usage_event success: %r", log_err)

        return {
            "status": "ok",
            "order_id": body.order_id,
            "email": body.email,
            "input": {
                **req.dict(),
                "tier": "premium",
                "report_type_normalized": report_type,
            },
            "payload_ai": payload_ai,
            "sinastria_ai": sinastria_ai,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[INTERNAL_GUEST_SINASTRIA] Errore generazione order_id=%r", body.order_id)
        raise HTTPException(status_code=500, detail=f"Errore generazione Sinastria guest: {e}")