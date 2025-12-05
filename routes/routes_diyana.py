# routes_diyana.py

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException


from astrobot_core.ai_diyana_qa import (
    QaAnswerRequest,
    QaAnswerResponse,
    process_diyana_qa,
)

from diyana_wallet import (
    PurchaseExtraRequest,
    PurchaseExtraResponse,
    get_balance,
    consume_credit,
    WalletInfo,
    ErrorPayload,
)
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diyana", tags=["diyana"])
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def log_diyana_qa_event(req: QaAnswerRequest, resp: QaAnswerResponse) -> None:
    """
    Logga una domanda/risposta di DYANA nella tabella Supabase dyana_qas.

    Non deve MAI bloccare la risposta all'utente:
    - se mancano le env → warning e return
    - se Supabase risponde con errore → error log e return
    - qualsiasi altra eccezione → exception log e return
    """

    # 1) Env check
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning(
            "[DYANA-LOG] SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY mancanti, skip log dyana_qas"
        );
        return

    try:
        # 2) Estraiamo campi principali dalla request
        user_id = getattr(req, "user_id", None)
        session_id = getattr(req, "session_id", None)
        question_origin = getattr(req, "question_origin", None)  # es: "included" / "extra"

        reading = getattr(req, "reading", None)
        if reading is not None:
            reading_id = getattr(reading, "reading_id", None)
            reading_type = getattr(reading, "reading_type", None)
            reading_label = getattr(reading, "reading_label", None)
            reading_text = getattr(reading, "reading_text", None)
            kb_tags = getattr(reading, "kb_tags", None)
        else:
            reading_id = None
            reading_type = None
            reading_label = None
            reading_text = None
            kb_tags = None

        user_question = getattr(req, "user_question", None)

        # 3) Estraiamo meta dalla response (tok_in, tok_out, model, tags, ecc.)
        meta_obj = getattr(resp, "meta", None)

        tokens_in = getattr(meta_obj, "tokens_in", None) if meta_obj else None
        tokens_out = getattr(meta_obj, "tokens_out", None) if meta_obj else None
        model = getattr(meta_obj, "model", None) if meta_obj else None
        reading_tags = getattr(meta_obj, "reading_tags", None) if meta_obj else None
        question_tags = getattr(meta_obj, "question_tags", None) if meta_obj else None

        ai_answer = getattr(resp, "ai_answer", None)
        status = getattr(resp, "status", None)
        error = getattr(resp, "error", None)

        # 4) Costruiamo il payload per la tabella dyana_qas
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "reading_id": reading_id,
            "reading_type": reading_type,
            "reading_label": reading_label,
            "reading_text": reading_text,
            "kb_tags": kb_tags,
            "user_question": user_question,
            "ai_answer": ai_answer,
            "status": status,
            "question_origin": question_origin,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
            "reading_tags": reading_tags,
            "question_tags": question_tags,
        }

        # 5) Chiamata a Supabase
        url = SUPABASE_URL.rstrip("/") + "/rest/v1/dyana_qas"
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        r = httpx.post(url, json=payload, headers=headers, timeout=5.0)

        if r.status_code not in (200, 201):
            logger.error(
                "[DYANA-LOG] Insert dyana_qas FAILED status=%s body=%s payload=%s",
                r.status_code,
                r.text,
                payload,
            )
            return

        logger.info(
            "[DYANA-LOG] Insert dyana_qas OK user_id=%s reading_id=%s origin=%s",
            user_id,
            reading_id,
            question_origin,
        )

    except Exception as e:
        logger.exception("[DYANA-LOG] Errore inatteso in log_diyana_qa_event: %s", e)

@router.post("/qa_answer", response_model=QaAnswerResponse)
async def diyana_qa_answer(req: QaAnswerRequest):
    if not req.reading.reading_text:
        raise HTTPException(
            status_code=400,
            detail="reading.reading_text è obbligatorio (testo mostrato sul sito)",
        )

    if not req.reading.reading_type:
        raise HTTPException(
            status_code=400,
            detail="reading.reading_type è obbligatorio",
        )

    if not req.user_question:
        raise HTTPException(
            status_code=400,
            detail="user_question è obbligatoria",
        )

    # 1) chiamiamo l'engine AI
    resp = process_diyana_qa(req)

    # 2) tentiamo il log su Supabase (non blocca la risposta)
    try:
        log_diyana_qa_event(req, resp)
    except Exception as e:
        logger.exception("[DYANA-LOG] Errore in log_diyana_qa_event: %s", e)

    # 3) restituiamo comunque la risposta all'utente
    return resp



# =============== NUOVA ROUTE: domanda extra ===============

@router.post("/purchase_extra_question", response_model=PurchaseExtraResponse)
async def diyana_purchase_extra_question(req: PurchaseExtraRequest):
    """
    Endpoint chiamato da Typebot quando l'utente ha finito le domande incluse
    e accetta di usare i propri crediti per una domanda extra.

    Logica:
    - Legge il saldo dal wallet.
    - Se saldo <= 0 → allowed = false.
    - Se saldo > 0 → scala 1 credito, allowed = true, new_questions_left = 1.
    """
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id obbligatorio")

    current_balance = get_balance(req.user_id)

    # Nessun credito → non posso concedere domanda extra
    if current_balance <= 0:
        return PurchaseExtraResponse(
            status="ok",
            allowed=False,
            new_questions_left=0,
            wallet=WalletInfo(credits_balance=current_balance),
            error=ErrorPayload(
                code="INSUFFICIENT_CREDITS",
                message="Non hai abbastanza crediti per una domanda extra."
            ),
        )

    # Ho almeno 1 credito → tento di scalare
    try:
        new_balance = consume_credit(req.user_id, amount=1)
    except ValueError:
        # Qualcuno ha consumato nel frattempo, saldo insufficiente
        current_balance = get_balance(req.user_id)
        return PurchaseExtraResponse(
            status="ok",
            allowed=False,
            new_questions_left=0,
            wallet=WalletInfo(credits_balance=current_balance),
            error=ErrorPayload(
                code="INSUFFICIENT_CREDITS",
                message="Non hai abbastanza crediti per una domanda extra."
            ),
        )

    # TODO: qui puoi loggare in DB la domanda extra richiesta
    # (user_id, reading_id, reading_type, ecc.)

    return PurchaseExtraResponse(
        status="ok",
        allowed=True,
        new_questions_left=1,
        wallet=WalletInfo(credits_balance=new_balance),
        error=None,
    )
