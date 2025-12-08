# routes/routes_sinastria_ai.py

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from astrobot_core.kb.tema_kb import build_aspetti_natali_con_kb

from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai

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

logger = logging.getLogger(__name__)

print(">>> DEBUG: routes_sinastria_ai COMPLETA LOADED <<<")

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])

# ==========================
#  Costi in crediti (parametrici)
# ==========================
SINASTRIA_FEATURE_KEY = "sinastria_ai"
SINASTRIA_PREMIUM_COST = 3  # quante volte "vale" una sinastria premium


# ==========================
#  Request models
# ==========================
class Persona(BaseModel):
    citta: str
    data: str        # YYYY-MM-DD
    ora: str         # HH:MM
    nome: Optional[str] = None


class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: str = "free"   # "free" | "premium"


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/")  # 👈 path relativo, quindi POST /sinastria_ai/
async def sinastria_ai_endpoint(
    body: SinastriaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo sinastria (numerico)
    2) Build payload_ai
    3) Chiamata Claude
    4) Logging usage
    5) Risposta finale con blocco billing
    """

    # ==============================
    # Metadati utente + request (usati in success + error)
    # ==============================
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

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
                feature_cost=SINASTRIA_PREMIUM_COST,
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
        # 1) Parsing datetime + calcolo sinastria
        # ====================================================
        try:
            dt_A = datetime.fromisoformat(f"{body.A.data} {body.A.ora}")
            dt_B = datetime.fromisoformat(f"{body.B.data} {body.B.ora}")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato data/ora non valido: {e}",
            )

        try:
            sinastria_data = calcola_sinastria(
                dt_A,
                body.A.citta,
                dt_B,
                body.B.citta,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nel calcolo della sinastria")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo della sinastria: {e}",
            )

        # ====================================================
        # 1b) KB ASPETTI per SINASTRIA (solo PREMIUM, via build_aspetti_natali_con_kb)
        # ====================================================
        kb_aspetti_sinastria = []
        if body.tier == "premium":
            try:
                top_stretti = (
                    sinastria_data
                    .get("sinastria", {})
                    .get("top_stretti", [])
                )

                # build_aspetti_natali_con_kb si aspetta un dict con "natal_aspects"
                kb_aspetti_sinastria = build_aspetti_natali_con_kb(
                    {"natal_aspects": top_stretti}
                )
            except Exception as e:
                logger.exception(
                    "[SINASTRIA_AI] Errore costruendo KB aspetti sinastria: %r",
                    e,
                )
                kb_aspetti_sinastria = []

        # ====================================================
        # 1c) Costruzione payload sinastria_vis per la UI
        #     (NON usato per l'AI, solo frontend)
        # ====================================================
        def _build_vis_tema(tema_dict: Dict[str, Any], nome_fallback: str) -> Dict[str, Any]:
            if not isinstance(tema_dict, dict):
                tema_dict = {}

            pianeti_decod = tema_dict.get("pianeti_decod") or {}
            pianeti_vis = []

            if isinstance(pianeti_decod, dict):
                for nome, info in pianeti_decod.items():
                    if not isinstance(info, dict):
                        continue
                    segno = info.get("segno") or info.get("segno_nome")
                    gradi_segno = (
                        info.get("gradi_segno")
                        or info.get("grado_segno")
                        or info.get("gradi")
                    )
                    casa = info.get("casa")

                    pianeti_vis.append(
                        {
                            "nome": nome,
                            "segno": segno,
                            "gradi_segno": gradi_segno,
                            "casa": casa,
                        }
                    )

            return {
                "nome": nome_fallback,
                "data": tema_dict.get("data"),
                "citta": None,  # opzionale, lato UI usi body.A.citta / body.B.citta
                "pianeti": pianeti_vis,
            }

        temaA_raw = sinastria_data.get("A") or {}
        temaB_raw = sinastria_data.get("B") or {}
        sinastria_inner = sinastria_data.get("sinastria", {}) or {}

        temaA_vis = _build_vis_tema(temaA_raw, body.A.nome or "Persona A")
        temaB_vis = _build_vis_tema(temaB_raw, body.B.nome or "Persona B")

        # Aspetti prevalenti (top stretti) in forma leggibile
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
                orb_str = f"{float(orb):.1f}°" if isinstance(orb, (int, float, float)) else None
            except Exception:
                orb_str = None

            label = None
            if p1 and p2 and tipo:
                if orb_str:
                    label = f"{p1} {tipo} {p2} (orb {orb_str})"
                else:
                    label = f"{p1} {tipo} {p2}"

            aspetti_vis.append(
                {
                    "pianetaA": p1,
                    "pianetaB": p2,
                    "tipo": tipo,
                    "orb": orb,
                    "label": label,
                }
            )

        sinastria_vis: Dict[str, Any] = {
            "A": {
                **temaA_vis,
                "citta": body.A.citta,
            },
            "B": {
                **temaB_vis,
                "citta": body.B.citta,
            },
            "aspetti_top": aspetti_vis,
        }




          # ====================================================
        # 2) Build payload AI (versione ULTRA COMPATTA)
        #    → passiamo a Claude solo:
        #      - A_compatto: per ogni pianeta {segno, casa}
        #      - B_compatto: idem
        #      - top_stretti_compatti: per ogni aspetto solo
        #        {pianetaA, pianetaB, tipo, orb}
        #    Inoltre, SOLO PER PREMIUM:
        #      - kb_aspetti_sinastria: ottenuto da build_aspetti_natali_con_kb
        #        applicato ai top_stretti raw.
        #    Tutto il resto resta in sinastria_data (per grafici/debug).
        # ====================================================
        try:
            sinastria_inner = sinastria_data.get("sinastria", {}) or {}
            temaA = sinastria_data.get("A") or {}
            temaB = sinastria_data.get("B") or {}

            def _compress_tema(tema: Dict[str, Any]) -> Dict[str, Any]:
                """Riduce il tema a: data + pianeti {nome: {segno, casa}}."""
                pianeti_decod = tema.get("pianeti_decod") or {}
                pianeti_compatti: Dict[str, Any] = {}

                if isinstance(pianeti_decod, dict):
                    for nome, info in pianeti_decod.items():
                        if not isinstance(info, dict):
                            continue
                        pianeti_compatti[nome] = {
                            "segno": info.get("segno"),
                            "casa": info.get("casa"),
                        }

                return {
                    "data": tema.get("data"),
                    "pianeti": pianeti_compatti,
                }

            # top_stretti raw (per grafici/KB) + compatti (per AI)
            top_stretti_raw = sinastria_inner.get("top_stretti", []) or []
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

            # Tema compattato per A e B
            sinastria_compatta: Dict[str, Any] = {
                "A": _compress_tema(temaA),
                "B": _compress_tema(temaB),
                "top_stretti": top_stretti_compatti,
            }

            # KB ASPETTI SINASTRIA (solo premium, e solo se riusciamo a costruirlo)
            kb_aspetti_sinastria = []
            if body.tier == "premium":
                try:
                    # build_aspetti_natali_con_kb si aspetta {"natal_aspects": [...]}
                    kb_aspetti_sinastria = build_aspetti_natali_con_kb(
                        {"natal_aspects": top_stretti_raw}
                    )
                except Exception as kb_err:
                    logger.exception(
                        "[SINASTRIA_AI] Errore costruendo kb_aspetti_sinastria: %r",
                        kb_err,
                    )
                    kb_aspetti_sinastria = []

            payload_ai: Dict[str, Any] = {
                "meta": {
                    "scope": "sinastria_ai",
                    "tier": body.tier,
                    "lingua": "it",
                    "nome_A": body.A.nome,
                    "nome_B": body.B.nome,
                },
                "sinastria": sinastria_compatta,
            }

            # Aggiungo il KB solo se c'è qualcosa (e solo premium a monte)
            if kb_aspetti_sinastria:
                payload_ai["kb_aspetti_sinastria"] = kb_aspetti_sinastria

        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nella costruzione del payload AI")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nella costruzione del payload AI: {e}",
            )



        # ====================================================
        # 3) Chiamata Claude
        # ====================================================
        sinastria_ai = call_claude_sinastria_ai(payload_ai)

        # ====================================================
        # 3b) Estrazione usage (usage_logs) – SOLO SUCCESSO
        # ====================================================
        tokens_in = 0
        tokens_out = 0
        model = None
        latency_ms: Optional[float] = None

        try:
            ai_debug_block = None

            if isinstance(sinastria_ai, dict):
                # 1) Caso semplice: debug ai livello top
                ai_debug_block = sinastria_ai.get("ai_debug") or sinastria_ai.get("debug")

                # 2) Caso: debug dentro meta (es. result["meta"]["ai_debug"])
                if ai_debug_block is None:
                    meta_block = sinastria_ai.get("meta")
                    if isinstance(meta_block, dict):
                        ai_debug_block = meta_block.get("ai_debug") or meta_block.get("debug")

                # 3) Caso wrapper tipo {"result": {...}, "ai_debug": {...}}
                if ai_debug_block is None:
                    wrapper_debug = sinastria_ai.get("ai_debug") or sinastria_ai.get("debug")
                    if isinstance(wrapper_debug, dict):
                        ai_debug_block = wrapper_debug

                # 4) Caso wrapper tipo {"result": {...}, ...} con debug dentro result
                if ai_debug_block is None:
                    inner = sinastria_ai.get("result")
                    if isinstance(inner, dict):
                        ai_debug_block = inner.get("ai_debug") or inner.get("debug")

            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
                # supporto sia a chiavi "input_tokens"/"output_tokens"
                # sia a eventuali forme alternative
                tokens_in = (
                    usage.get("input_tokens")
                    or usage.get("prompt_tokens")
                    or 0
                ) or 0
                tokens_out = (
                    usage.get("output_tokens")
                    or usage.get("completion_tokens")
                    or 0
                ) or 0

                model = ai_debug_block.get("model")
                elapsed_sec = (
                    ai_debug_block.get("elapsed_sec")
                    or ai_debug_block.get("latency_sec")
                )
                if isinstance(elapsed_sec, (int, float)):
                    latency_ms = float(elapsed_sec) * 1000.0
        except Exception:
            tokens_in = 0
            tokens_out = 0
            model = None
            latency_ms = None
        # ====================================================
        # 3b-bis) Logging usage SU SUCCESSO
        # ====================================================
        # Calcolo costi (paid vs free_credit) in base alla decisione
        cost_paid_credits = 0
        cost_free_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "paid":
                cost_paid_credits = SINASTRIA_PREMIUM_COST
            elif decision.mode == "free_credit":
                cost_free_credits = SINASTRIA_PREMIUM_COST

        # Payload di debug che salviamo in request_json su Supabase
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
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json=request_log_success,
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] log_usage_event error (success): %r", e)

        # ====================================================
        # 3c) Grafico sinastria (PNG base64) – opzionale
        # ====================================================
        chart_sinastria_base64 = None
        try:
            from astrobot_core.grafici import genera_carta_sinastria

            # 1) Pianeti decodificati per A e B
            pianeti_A_decod = sinastria_data["A"]["pianeti_decod"]
            pianeti_B_decod = sinastria_data["B"]["pianeti_decod"]

            # 2) Aspetti cross A–B dalla struttura:
            #    "sinastria": { "aspetti_AB": [...] }
            aspetti_raw = sinastria_data.get("sinastria", {}).get("aspetti_AB", [])

            # Adattamento chiavi: da pianeta1/pianeta2 -> pianetaA/pianetaB
            aspetti_AB = []
            for asp in aspetti_raw:
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
            "sinastria_vis": sinastria_vis,  # 👈 nuovo blocco solo per la UI
            "chart_sinastria_base64": chart_sinastria_base64,
            "billing": {
                "mode": billing_mode,                 # "free", "paid" o "free_credit"
                "remaining_credits": (
                    state.paid_credits if state is not None else None
                ),
                "cost_credits": (
                    SINASTRIA_PREMIUM_COST
                    if (body.tier == "premium" and billing_mode in ("paid", "free_credit"))
                    else 0
                ),
                "cost_paid_credits": cost_paid_credits,
                "cost_free_credits": cost_free_credits,
            },
        }


    # ====================================================
    # 5) LOG TENTATIVI FALLITI (HTTPException)
    # ====================================================
    except HTTPException as exc:
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
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

    # ====================================================
    # 6) LOG TENTATIVI FALLITI (unexpected Exception)
    # ====================================================
    except Exception as exc:
        logger.exception("[SINASTRIA_AI] Errore inatteso in sinastria_ai_endpoint")
        try:
            log_usage_event(
                user_id=user.sub,
                feature=SINASTRIA_FEATURE_KEY,
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
