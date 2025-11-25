# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import json

from astrobot_core.calcoli import costruisci_tema_natale
from utils.payload_tema_ai import build_payload_tema_ai
from ai_claude import call_claude_tema_ai

# --- NUOVI IMPORT PER AUTH + CREDITI ---
from auth import get_current_user, UserContext
from credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
)

router = APIRouter()

# ==========================
#  Costi in crediti
# ==========================
# Tema natale AI: costo fisso in crediti (parametrico in futuro se vuoi)
TEMA_AI_FEATURE_KEY = "tema_ai"
TEMA_AI_FEATURE_COST = 2  # 2 crediti per tema_ai


# ==========================
#  Request model
# ==========================
class TemaAIRequest(BaseModel):
    citta: str
    data: str        # formato YYYY-MM-DD
    ora: str         # formato HH:MM
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: str = "free"   # free | premium (usato ancora per il prompt di Claude)


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/tema_ai")
def tema_ai_endpoint(
    body: TemaAIRequest,
    user: UserContext = Depends(get_current_user),  # <-- NUOVO: utente dal JWT
):
    """
    1) Verifica crediti / free tries (gating)
    2) Calcola il tema natale
    3) Costruisce payload_ai (pianeti, case, meta…)
    4) Chiama Claude (free/premium)
    5) Restituisce JSON finale
    """
    # ====================================================
    # 0) GATING CREDITI / FREE TRIES
    # ====================================================
    # Carichiamo lo stato crediti + free tries per questo utente
    state = load_user_credits_state(user)

    # Decidiamo se può eseguire una lettura premium di tipo "tema_ai"
    decision = decide_premium_mode(state)

    # Applichiamo il consumo (crediti pagati o free_try) oppure solleviamo errore
    # NB: TEMA_AI_FEATURE_COST è il costo in crediti del tema natale AI
    apply_premium_consumption(state, decision, feature_cost=TEMA_AI_FEATURE_COST)

    # Salviamo lo stato aggiornato (per ora è uno stub, verrà collegato a Supabase)
    save_user_credits_state(state)

    # (Opzionale) Potresti anche decidere di forzare tier="premium" se vuoi che
    # tema_ai sia sempre trattato come prodotto premium a pagamento, ma per ora
    # lascio body.tier così com'è, in modo da non rompere la logica esistente.
    #
    # Esempio se un domani vuoi forzare:
    # body.tier = "premium"

    # ====================================================
    # 1) Calcolo tema natale
    # ====================================================
    try:
        tema = costruisci_tema_natale(
            body.citta,
            body.data,
            body.ora,
            sistema_case="equal"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore nel calcolo del tema natale: {e}"
        )

    # ====================================================
    # 2) Build payload AI
    # ====================================================
    try:
        payload_ai = build_payload_tema_ai(
            tema=tema,
            nome=body.nome,
            email=body.email,
            domanda=body.domanda,
            tier=body.tier,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore nella costruzione del payload AI: {e}"
        )

    # ====================================================
    # 3) Chiamata Claude
    # ====================================================
    ai_debug = call_claude_tema_ai(payload_ai, tier=body.tier)

    # Claude può restituire raw_text in diversi punti
    raw = (
        ai_debug.get("raw_text")
        or ai_debug.get("ai_debug", {}).get("raw_text")
        or ""
    )

    if not raw:
        return {
            "status": "error",
            "message": "Claude non ha restituito testo.",
            "input": body.dict(),
            "payload_ai": payload_ai,
            "result": None,
            "ai_debug": ai_debug,
            "billing": {
                "mode": decision.mode,
                "remaining_credits": state.paid_credits,
            },
        }

    # ====================================================
    # 4) Parse JSON dall'AI
    # ====================================================
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(raw)
    except Exception as e:
        parse_error = str(e)

    # ====================================================
    # 5) Risposta finale
    # ====================================================
    return {
        "status": "ok",
        "scope": "tema_ai",
        "input": body.dict(),
        "payload_ai": payload_ai,
        "result": {
            "error": "JSON non valido" if parsed is None else None,
            "parse_error": parse_error,
            "raw_preview": raw[:500],
            "content": parsed,
        },
        "ai_debug": ai_debug,
        # Info di billing utili per DYANA / UI
        "billing": {
            "mode": decision.mode,          # "paid" | "free_try"
            "remaining_credits": state.paid_credits,
        },
    }
