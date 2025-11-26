# routes_diyana.py

from fastapi import APIRouter, HTTPException

from astrobot_core.ai_diyana_qa import (
    QaAnswerRequest,
    QaAnswerResponse,
    process_diyana_qa,
)

from astrobot_core.diyana_wallet import (
    PurchaseExtraRequest,
    PurchaseExtraResponse,
    get_balance,
    consume_credit,
    WalletInfo,
    ErrorPayload,
)

router = APIRouter(prefix="/diyana", tags=["diyana"])


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

    return process_diyana_qa(req)


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
