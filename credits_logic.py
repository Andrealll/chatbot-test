# credits_logic.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import os
import requests
from fastapi import HTTPException, status
from datetime import datetime, timezone, date

from auth import UserContext
from settings_credits import FREE_TRIES_PER_PERIOD, FREE_TRIES_PERIOD_DAYS


ModeType = Literal["paid", "free_try", "denied"]


@dataclass
class UserCreditsState:
    """
    Stato crediti + free tries per un utente.
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
#  CONFIG SUPABASE
# =========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


# =========================================================
#  FUNZIONI DI ACCESSO AI DATI
# =========================================================

def load_user_credits_state(user: UserContext) -> UserCreditsState:
    """
    Carica lo stato crediti + free tries dal DB (Supabase).

    - Se USE_SUPABASE = False: ritorna uno stato di default (stub).
    - Se sub inizia con "anon-": usa tabella `guests`.
    - Altrimenti: usa tabella `entitlements`.
    """
    is_guest = user.sub.startswith("anon-")

    # Fallback stub: nessun DB configurato → utente con 0 crediti e 0 tries
    if not USE_SUPABASE:
        return UserCreditsState(
            sub=user.sub,
            role=user.role,
            is_guest=is_guest,
            paid_credits=0,
            free_tries_used=0,
            free_tries_period_start=None,
        )

    if is_guest:
        return _load_guest_state(user.sub)
    else:
        return _load_entitlement_state(user.sub, user.role)


def save_user_credits_state(state: UserCreditsState) -> None:
    """
    Salva lo stato crediti + free tries nel DB (Supabase).

    Se USE_SUPABASE = False: non fa nulla (stub).
    """
    if not USE_SUPABASE:
        return

    if state.is_guest:
        _save_guest_state(state)
    else:
        _save_entitlement_state(state)


# -------------------------
#  HELPERS ENTITLEMENTS
# -------------------------

def _load_entitlement_state(user_id: str, role: str) -> UserCreditsState:
    url = f"{SUPABASE_URL}/rest/v1/entitlements"
    headers = _supabase_headers()
    params = {
        "user_id": f"eq.{user_id}",
        "select": "credits,free_tries_used,free_tries_period_start",
    }

    resp = requests.get(url, headers=headers, params=params, timeout=5)
    if resp.status_code != 200:
        # In caso di errore DB, fallback su stato "vuoto" per non spaccare tutto
        return UserCreditsState(
            sub=user_id,
            role=role,
            is_guest=False,
            paid_credits=0,
            free_tries_used=0,
            free_tries_period_start=None,
        )

    rows = resp.json()
    if not rows:
        # Nessuna riga: creiamo un entitlement base (0 crediti, 0 tries)
        data = {
            "user_id": user_id,
            "credits": 0,
            "free_tries_used": 0,
            "free_tries_period_start": None,
        }
        resp_ins = requests.post(
            url,
            headers={**headers, "Prefer": "return=representation"},
            json=data,
            timeout=5,
        )
        if resp_ins.status_code not in (200, 201):
            # Anche qui, fallback "vuoto"
            return UserCreditsState(
                sub=user_id,
                role=role,
                is_guest=False,
                paid_credits=0,
                free_tries_used=0,
                free_tries_period_start=None,
            )
        row = resp_ins.json()[0]
    else:
        row = rows[0]

    credits = row.get("credits", 0) or 0
    free_tries_used = row.get("free_tries_used", 0) or 0
    period_start_str = row.get("free_tries_period_start")

    if period_start_str:
        try:
            free_tries_period_start = datetime.fromisoformat(period_start_str)
            if free_tries_period_start.tzinfo is None:
                free_tries_period_start = free_tries_period_start.replace(tzinfo=timezone.utc)
        except Exception:
            free_tries_period_start = None
    else:
        free_tries_period_start = None

    return UserCreditsState(
        sub=user_id,
        role=role,
        is_guest=False,
        paid_credits=credits,
        free_tries_used=free_tries_used,
        free_tries_period_start=free_tries_period_start,
    )


def _save_entitlement_state(state: UserCreditsState) -> None:
    url = f"{SUPABASE_URL}/rest/v1/entitlements"
    headers = _supabase_headers()

    period_start = (
        state.free_tries_period_start.isoformat()
        if state.free_tries_period_start is not None
        else None
    )

    data = {
        "credits": state.paid_credits,
        "free_tries_used": state.free_tries_used,
        "free_tries_period_start": period_start,
    }

    params = {
        "user_id": f"eq.{state.sub}",
    }

    resp = requests.patch(
        url,
        headers=headers,
        params=params,
        json=data,
        timeout=5,
    )
    # Se fallisce, per ora non tiriamo giù tutto: possiamo loggare in futuro


# -------------------------
#  HELPERS GUESTS
# -------------------------
def _extract_guest_uuid(sub: str) -> Optional[str]:
    """
    sub è del tipo "anon-<uuid>".
    Estraggo la parte uuid dopo "anon-".
    """
    prefix = "anon-"
    if not sub.startswith(prefix):
        return None
    return sub[len(prefix):]


def _load_guest_state(sub: str) -> UserCreditsState:
    """
    Mappa la tabella `guests` (schema reale):

        guest_id uuid primary key,
        day date,
        free_uses int not null default 0,
        last_seen timestamptz,
        ip_hash text,
        ua text

    sui campi logici:

        free_tries_used         <-> free_uses
        free_tries_period_start <-> day (come datetime UTC a mezzanotte)
    """
    guest_uuid = _extract_guest_uuid(sub)
    if not guest_uuid:
        # Se qualcosa non torna, trattiamo l'utente come "vuoto"
        return UserCreditsState(
            sub=sub,
            role="free",
            is_guest=True,
            paid_credits=0,
            free_tries_used=0,
            free_tries_period_start=None,
        )

    if not USE_SUPABASE:
        # Caso teorico, ma per coerenza:
        return UserCreditsState(
            sub=sub,
            role="free",
            is_guest=True,
            paid_credits=0,
            free_tries_used=0,
            free_tries_period_start=None,
        )

    url = f"{SUPABASE_URL}/rest/v1/guests"
    headers = _supabase_headers()
    params = {
        "guest_id": f"eq.{guest_uuid}",
        "select": "guest_id,day,free_uses",
    }

    resp = requests.get(url, headers=headers, params=params, timeout=5)
    if resp.status_code != 200:
        # In caso di errore DB, fallback su stato "vuoto"
        return UserCreditsState(
            sub=sub,
            role="free",
            is_guest=True,
            paid_credits=0,
            free_tries_used=0,
            free_tries_period_start=None,
        )

    rows = resp.json()
    if not rows:
        # Nessuna riga: creiamo un guest "nuovo"
        data = {
            "guest_id": guest_uuid,
            "free_uses": 0,
            "day": None,
        }
        resp_ins = requests.post(
            url,
            headers={**headers, "Prefer": "return=representation"},
            json=data,
            timeout=5,
        )
        print("[CREDITS] GET /guests", resp.status_code, resp.text)
        if resp_ins.status_code not in (200, 201):
            # Fallback se anche l'insert fallisce
            return UserCreditsState(
                sub=sub,
                role="free",
                is_guest=True,
                paid_credits=0,
                free_tries_used=0,
                free_tries_period_start=None,
            )
        row = resp_ins.json()[0]
    else:
        row = rows[0]

    free_uses = row.get("free_uses", 0) or 0
    day_str = row.get("day")

    if day_str:
        try:
            # day è una DATE ("YYYY-MM-DD"), la mappiamo a datetime a mezzanotte UTC
            d = date.fromisoformat(day_str)
            free_tries_period_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except Exception:
            free_tries_period_start = None
    else:
        free_tries_period_start = None

    return UserCreditsState(
        sub=sub,
        role="free",
        is_guest=True,
        paid_credits=0,  # i guest non hanno crediti pagati
        free_tries_used=free_uses,
        free_tries_period_start=free_tries_period_start,
    )


def _save_guest_state(state: UserCreditsState) -> None:
    """
    Salva lo stato del guest mappando:

        free_tries_used         -> free_uses
        free_tries_period_start -> day (DATE)
    """
    guest_uuid = _extract_guest_uuid(state.sub)
    if not guest_uuid or not USE_SUPABASE:
        return

    url = f"{SUPABASE_URL}/rest/v1/guests"
    headers = _supabase_headers()

    if state.free_tries_period_start is not None:
        d = state.free_tries_period_start.date()
        day_value = d.isoformat()
    else:
        day_value = None

    data = {
        "free_uses": state.free_tries_used,
        "day": day_value,
    }

    params = {
        "guest_id": f"eq.{guest_uuid}",
    }

    resp = requests.patch(
        url,
        headers=headers,
        params=params,
        json=data,
        timeout=5,
    )
    
    print("[CREDITS] PATCH /guests", resp.status_code, resp.text)
# Anche qui, se fallisce, per ora non solleviamo: da loggare in futuro
    # Se fallisce, per ora niente eccezione: in futuro si può loggare resp.status_code / resp.text


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

    if state.free_tries_used < FREE_TRIES_PER_PERIOD:
        return PremiumDecision(allowed=True, mode="free_try")

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

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Stato crediti non consistente.",
    )
