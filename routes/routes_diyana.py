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
    Inserisce un record in dyana_qas su Supabase con:
    - dati utente/reading
    - domanda
    - risposta AI
    - meta (token, modello, tags)
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("[DYANA-LOG] SUPABASE_URL o SERVICE_ROLE_KEY mancanti, salto il log.")
        return

    url = SUPABASE_URL.rstrip("/") + "/rest/v1/dyana_qas"

    # resp.meta è un oggetto Pydantic (QaAnswerMeta), NON un dict
    meta_obj = getattr(resp, "meta", None)

    tokens_in = getattr(meta_obj, "tokens_in", None) if meta_obj else None
    tokens_out = getattr(meta_obj, "tokens_out", None) if meta_obj else None
    model = getattr(meta_obj, "model", None) if meta_obj else None
    kb_docs_used = getattr(meta_obj, "kb_docs_used", None) if meta_obj else None
    reading_tags = getattr(meta_obj, "reading_tags", None) if meta_obj else None
    question_tags = getattr(meta_obj, "question_tags", None) if meta_obj else None

    payload = {
        "user_id": req.user_id,
        "session_id": req.session_id,
        "reading_id": req.reading.reading_id,
        "reading_type": req.reading.reading_type,
        "reading_label": req.reading.reading_label,
        "question": req.user_question,
        "ai_answer": resp.ai_answer,
        "origin": req.question_origin,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model,
        "kb_docs_used": kb_docs_used,
        "reading_tags": reading_tags,
        "question_tags": question_tags,
    }

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=5.0)
        if r.status_code not in (200, 201, 204):
            logger.warning(
                "[DYANA-LOG] Insert dyana_qas KO status=%s body=%s",
                r.status_code,
                r.text,
            )
        else:
            logger.info(
                "[DYANA-LOG] Insert dyana_qas OK user_id=%s reading_id=%s origin=%s",
                req.user_id,
                req.reading.reading_id,
                req.question_origin,
            )
    except Exception as e:
        logger.exception("[DYANA-LOG] Errore inserendo log dyana_qas: %s", e)

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
