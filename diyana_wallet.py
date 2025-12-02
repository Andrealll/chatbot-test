# astrobot_core/diyana_wallet.py

from typing import Optional
from pydantic import BaseModel, Field

# ==========================
# FAKE WALLET IN MEMORY
# ==========================

# Per i test:
# - user_1 ha 3 crediti
# - user_2 ha 0 crediti
WALLET = {
    "user_1": 3,
    "user_2": 0,
}

def get_balance(user_id: str) -> int:
    return WALLET.get(user_id, 0)

def consume_credit(user_id: str, amount: int = 1) -> int:
    current = get_balance(user_id)
    if current < amount:
        raise ValueError("INSUFFICIENT_CREDITS")
    new_balance = current - amount
    WALLET[user_id] = new_balance
    return new_balance


# ==========================
# MODELLI PER L'ENDPOINT
# ==========================

class PurchaseExtraRequest(BaseModel):
    user_id: str = Field(..., description="ID utente loggato")
    reading_id: Optional[str] = Field(
        None,
        description="ID della lettura per cui si chiede la domanda extra"
    )
    reading_type: Optional[str] = Field(
        None,
        description="Tipo lettura (oroscopo_weekly, tema_natale, sinastria...)"
    )


class WalletInfo(BaseModel):
    credits_balance: int


class ErrorPayload(BaseModel):
    code: str
    message: str


class PurchaseExtraResponse(BaseModel):
    status: str
    allowed: bool
    new_questions_left: int
    wallet: WalletInfo
    error: Optional[ErrorPayload]
