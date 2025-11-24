# routes/routes_tema_ai.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import json

from astrobot_core.calcoli import costruisci_tema_natale
from utils.payload_tema_ai import build_payload_tema_ai
from ai_claude import call_claude_tema_ai

router = APIRouter()

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
    tier: str = "free"   # free | premium


# ==========================
#  ROUTE PRINCIPALE
# ==========================
@router.post("/tema_ai")
def tema_ai_endpoint(body: TemaAIRequest):
    """
    1) Calcola il tema natale
    2) Costruisce payload_ai (pianeti, case, meta…)
    3) Chiama Claude (free/premium)
    4) Restituisce JSON finale
    """
    try:
        # ----------------------------------------
        # 1) Calcolo tema natale
        # ----------------------------------------
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

        # ----------------------------------------
        # 2) Build payload AI
        # ----------------------------------------
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

        # ----------------------------------------
        # 3) Chiamata Claude
        # ----------------------------------------
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
                "payload_ai": payload_ai,
                "ai_debug": ai_debug
            }

        # ----------------------------------------
        # 4) Parse JSON dall'AI
        # ----------------------------------------
        parsed = None
        parse_error = None
        try:
            parsed = json.loads(raw)
        except Exception as e:
            parse_error = str(e)

        # ----------------------------------------
        # 5) Risposta finale
        # ----------------------------------------
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
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore interno tema_ai: {e}"
        )
