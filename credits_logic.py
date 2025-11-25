# credits_logic.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status

from auth import UserContext
from settings_credits import FREE_TRIES_PER_PERIOD, FREE_TRIES_PERIOD_DAYS


ModeType = Literal["paid", "free_try", "denied"]


@dataclass
class UserCreditsState:
    """
    Stato crediti + free tries per un utente.

    NOTA: qui non facciamo ancora query reali su Supabase.
    Le funzioni di load/save sono dei placeholder da collegare
    alle tabelle `entitlements` (utenti) e `guests` (anonimi).
    """
    sub: str
    role: str
    is_guest: bool

    paid_credits: int = 0
    free_tries_used: int = 0
    free_tries_period_start: Optional[datetime] = None


@dataclass
class PremiumDecision:
    allowed: bool
    mode: ModeType
    reason: Optional[str] = None


# =========================================================
#  FUNZIONI DI ACCESSO AI DATI (PLACEHOLDER)
# =========================================================

def load_user_credits_state(user: UserContext) -> UserCreditsState:
    """
    Carica lo stato crediti + free tries dal DB (Supabase).

    QUI al momento mettiamo solo un placeholder che inizializza tutto a zero.

    TODO (da implementare):
      - Se user.sub inizia con "anon-": leggere/aggiornare la tabella `guests`
      - Altrimenti: leggere/aggiornare la tabella `entitlements`
    """
    is_guest = user.sub.startswith("anon-")

    # Placeholder: nessun credito pagato, nessun free try usato
    # (serve solo per non bloccare gli endpoint mentre sviluppiamo la logica)
    return UserCreditsState(
        sub=user.sub,
        role=user.role,
        is_guest=is_guest,
        paid_credits=0,
        free_tries_used=0,
        free_tries_period_start=None,
    )


def save_user_credits_state(state: UserCreditsState) -> None:
    """
    Salva lo stato crediti + free tries nel DB (Supabase).

    TODO (da implementare):
      - Se state.is_guest: update su `guests`
      - Altrimenti: update su `entitlements`
    """
    # Placeholder: per ora non fa nulla.
    # Quando integrerai Supabase, qui andranno le query di update.
    return


# =========================================================
#  LOGICA DI GATING PREMIUM
# =========================================================

def decide_premium_mode(
    state: UserCreditsState,
    now: Optional[datetime] = None,
) -> PremiumDecision:
    """
    Decide se l'utente può eseguire una lettura premium e in che modalità.

    Regole:
      1) Se role == "premium" -> allow paid (bypass crediti, per account speciali)
      2) Se ha paid_credits > 0 -> mode = "paid"
      3) Se non ha crediti:
           - se ci sono free tries disponibili nel periodo -> mode = "free_try"
           - altrimenti -> mode = "denied"
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 1) Utenti "premium" (account speciali)
    if state.role == "premium":
        return PremiumDecision(allowed=True, mode="paid")

    # 2) Ha crediti pagati?
    if state.paid_credits > 0:
        return PremiumDecision(allowed=True, mode="paid")

    # 3) Nessun credito pagato: gestiamo i free tries

    # Se non abbiamo ancora un periodo, lo inizializziamo ora
    period_start = state.free_tries_period_start
    if period_start is None:
        state.free_tries_period_start = now
        state.free_tries_used = 0
    else:
        delta_days = (now - period_start).days
        if delta_days >= FREE_TRIES_PERIOD_DAYS:
            # Nuovo periodo: reset del contatore
            state.free_tries_period_start = now
            state.free_tries_used = 0

    # Ora controlliamo il numero di try usati nel periodo
    if state.free_tries_used < FREE_TRIES_PER_PERIOD:
        return PremiumDecision(allowed=True, mode="free_try")

    # Nessun credito e nessun free try residuo
    return PremiumDecision(
        allowed=False,
        mode="denied",
        reason="no_credits_and_no_free",
    )


def apply_premium_consumption(
    state: UserCreditsState,
    decision: PremiumDecision,
    feature_cost: int,
) -> None:
    """
    Applica il consumo effettivo in base alla decisione:
      - mode = "paid": scala 'feature_cost' da paid_credits
      - mode = "free_try": incrementa free_tries_used di 1
      - mode = "denied": solleva HTTPException
    """
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Non hai crediti sufficienti o tentativi gratuiti disponibili.",
        )

    if decision.mode == "paid":
        if state.paid_credits < feature_cost:
            # Non dovrebbe succedere se controlli prima, ma per sicurezza:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Crediti insufficienti per questa operazione.",
            )
        state.paid_credits -= feature_cost
        return

    if decision.mode == "free_try":
        # Un free try vale per UN calcolo premium (indipendente dal costo)
        state.free_tries_used += 1
        return

    # mode "denied" dovrebbe essere già gestito sopra
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Stato crediti non consistente.",
    )
