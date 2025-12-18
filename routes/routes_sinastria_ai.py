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

import os
import json

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
    ora: str         # "HH:MM" oppure "" se ora ignota
    nome: Optional[str] = None
    ora_ignota: bool = False   # 👈 nuovo campo


class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: str = "free"   # "free" | "premium"


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/")
async def sinastria_ai_endpoint(
    body: SinastriaAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    0) Gating crediti SOLO se tier == "premium"
    1) Calcolo sinastria (numerico)
    2) Build payload_ai (compatto + KB aspetti solo premium)
    3) Chiamata Claude
    4) Logging usage
    5) Risposta finale con blocco billing + payload_vis per la UI
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
        # 1) Parsing datetime (solo validazione formato) + supporto ora ignota
        # ====================================================
        def _build_dt(data_str: str, ora_str: str, ora_ignota: bool) -> datetime:
            """
            Se ora_ignota=True o ora_str è vuota:
              - usiamo internamente le 12:00 SOLO per i calcoli numerici
              - ma il flag di ora ignota verrà propagato nel payload AI.
            """
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
        # 1b) Calcolo sinastria (numerico) → sinastria_data
        # ====================================================
        try:
            # firma reale del core: sinastria(dt_A, citta_A, dt_B, citta_B)
            sinastria_data = calcola_sinastria(
                dt_A,          # 👈 datetime A
                body.A.citta,  # 👈 città A
                dt_B,          # 👈 datetime B
                body.B.citta,  # 👈 città B
            )
        except Exception as e:
            logger.exception("[SINASTRIA_AI] Errore nel calcolo della sinastria")
            raise HTTPException(
                status_code=500,
                detail=f"Errore nel calcolo della sinastria: {e}",
            )

        # ====================================================
        # 1c) Costruzione payload sinastria_vis per la UI
        #     (NON usato per l'AI, solo frontend)
        # ====================================================
        def _build_vis_tema(
            tema_dict: Dict[str, Any],
            nome_fallback: str,
            ora_ignota: bool,  # 👈 NUOVO: serve per nascondere Ascendente/case SOLO se ora ignota
        ) -> Dict[str, Any]:
            if not isinstance(tema_dict, dict):
                tema_dict = {}

            pianeti_decod = tema_dict.get("pianeti_decod") or {}
            pianeti_vis = []

            if isinstance(pianeti_decod, dict):
                for nome, info in pianeti_decod.items():
                    if not isinstance(info, dict):
                        continue

                    # SOLO se ora ignota: togliamo Ascendente dalla UI
                    if ora_ignota and nome == "Ascendente":
                        continue

                    segno = info.get("segno") or info.get("segno_nome")
                    gradi_segno = (
                        info.get("gradi_segno")
                        or info.get("grado_segno")
                        or info.get("gradi")
                    )

                    item = {
                        "nome": nome,
                        "segno": segno,
                        "gradi_segno": gradi_segno,
                    }

                    # SOLO se ora NON ignota: includiamo la casa (come prima)
                    if not ora_ignota:
                        item["casa"] = info.get("casa")

                    pianeti_vis.append(item)

            return {
                "nome": nome_fallback,
                "data": tema_dict.get("data"),
                "citta": None,  # lato UI usi body.A.citta / body.B.citta
                "pianeti": pianeti_vis,
            }

        temaA_raw = sinastria_data.get("A") or {}
        temaB_raw = sinastria_data.get("B") or {}
        sinastria_inner = sinastria_data.get("sinastria", {}) or {}

        temaA_vis = _build_vis_tema(temaA_raw, body.A.nome or "Persona A", body.A.ora_ignota)
        temaB_vis = _build_vis_tema(temaB_raw, body.B.nome or "Persona B", body.B.ora_ignota)

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
                orb_str = f"{float(orb):.1f}°" if isinstance(orb, (int, float)) else None
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
        # 2) Build payload AI (versione ULTRA COMPATTA + KB ASPETTI PREMIUM)
        # ====================================================
        try:
            sinastria_inner = sinastria_data.get("sinastria", {}) or {}
            temaA = sinastria_data.get("A") or {}
            temaB = sinastria_data.get("B") or {}

            def _compress_tema(tema: Dict[str, Any], ora_ignota: bool) -> Dict[str, Any]:
                """
                Riduce il tema a:
                - data
                - pianeti { nome: { segno, casa } } (case SOLO se ora NON ignota)

                Se ora_ignota=True:
                - rimuove Ascendente
                - NON include le case (case/ascendenti non affidabili)
                """
                pianeti_decod = tema.get("pianeti_decod") or {}
                natal_houses = tema.get("natal_houses") or {}

                pianeti_compatti: Dict[str, Any] = {}

                if isinstance(pianeti_decod, dict):
                    for nome, info in pianeti_decod.items():
                        if not isinstance(info, dict):
                            continue

                        # SOLO se ora ignota: rimuovi Ascendente dal payload AI
                        if ora_ignota and nome == "Ascendente":
                            continue

                        segno = info.get("segno")

                        item: Dict[str, Any] = {"segno": segno}

                        # SOLO se ora NON ignota: includi casa come prima
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

            # top_stretti raw (per KB) + filtro Ascendente se ora ignota
            top_stretti_raw = sinastria_inner.get("top_stretti", []) or []

            if body.A.ora_ignota or body.B.ora_ignota:
                filtered = []
                for asp in top_stretti_raw:
                    if not isinstance(asp, dict):
                        continue
                    p1 = asp.get("pianeta1")
                    p2 = asp.get("pianeta2")
                    # se una delle due parti è Ascendente, lo togliamo
                    if p1 == "Ascendente" or p2 == "Ascendente":
                        continue
                    filtered.append(asp)
                top_stretti_raw = filtered

            # compatti (per AI)
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
                "A": _compress_tema(temaA, body.A.ora_ignota),
                "B": _compress_tema(temaB, body.B.ora_ignota),
                "top_stretti": top_stretti_compatti,
            }

            # KB ASPETTI SINASTRIA (solo premium, struttura tipo glossario senza ripetizioni)
            kb_glossario_aspetti: Optional[Dict[str, Any]] = None
            if body.tier == "premium":
                try:
                    # build_aspetti_natali_con_kb si aspetta {"natal_aspects": [...]}
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

                        # Glossario pianeti → ogni pianeta una sola volta
                        if p1 and desc_p1 and p1 not in pianeti_map:
                            pianeti_map[p1] = desc_p1
                        if p2 and desc_p2 and p2 not in pianeti_map:
                            pianeti_map[p2] = desc_p2

                        # Glossario aspetti → ogni tipo ("congiunzione", "quadratura", ...) una sola volta
                        if tipo and desc_asp and tipo not in aspetti_map:
                            aspetti_map[tipo] = desc_asp

                        # Lista coppie rilevanti (senza testi lunghi)
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
                            "pianeti": pianeti_map,                # es. "Sole" → descrizione sintetica
                            "aspetti": aspetti_map,                # es. "quadratura" → descrizione sintetica
                            "coppie_rilevanti": coppie_rilevanti,  # solo struttura, niente testi ripetuti
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
                    "lingua": "it",
                    "nome_A": body.A.nome,
                    "nome_B": body.B.nome,
                    "ora_ignota_A": body.A.ora_ignota,
                    "ora_ignota_B": body.B.ora_ignota,
                },
                "sinastria": sinastria_compatta,
            }

            # Aggiungo il KB glossario solo se esiste (solo premium a monte)
            if kb_glossario_aspetti:
                payload_ai["kb_aspetti_sinastria"] = kb_glossario_aspetti

            # ====================================================
            # 2b) DEBUG: DIMENSIONE PAYLOAD + SALVATAGGIO SU FILE
            # ====================================================
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
                # 1) Caso semplice: debug a livello top
                ai_debug_block = sinastria_ai.get("ai_debug") or sinastria_ai.get("debug")

                # 2) Caso: debug dentro meta (es. result["meta"]["ai_debug"])
                if ai_debug_block is None:
                    meta_block = sinastria_ai.get("meta")
                    if isinstance(meta_block, dict):
                        ai_debug_block = meta_block.get("ai_debug") or meta_block.get("debug")

                # 3) Caso wrapper tipo {"result": {...}, "ai_debug": {...}}
                if ai_debug_block is None:
                    inner = sinastria_ai.get("result")
                    if isinstance(inner, dict):
                        ai_debug_block = inner.get("ai_debug") or inner.get("debug")

            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
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
        cost_paid_credits = 0
        cost_free_credits = 0

        if body.tier == "premium" and decision is not None:
            if decision.mode == "paid":
                cost_paid_credits = SINASTRIA_PREMIUM_COST
            elif decision.mode == "free_credit":
                cost_free_credits = SINASTRIA_PREMIUM_COST

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

            pianeti_A_decod = sinastria_data["A"]["pianeti_decod"]
            pianeti_B_decod = sinastria_data["B"]["pianeti_decod"]

            aspetti_raw = sinastria_data.get("sinastria", {}).get("aspetti_AB", []) or []

            # se ora ignota per almeno uno, togliamo gli aspetti con Ascendente
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
