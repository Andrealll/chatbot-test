# routes/routes_tema_ai.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from astrobot_core.calcoli import costruisci_tema_natale
from utils.payload_tema_ai import build_payload_tema_ai
from ai_claude import call_claude_tema_ai

import json


router = APIRouter()


class TemaAIRequest(BaseModel):
    citta: str
    data: str          # formato YYYY-MM-DD
    ora: str           # formato HH:MM
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: str = "free"  # "free" | "premium"


@router.post("/tema_ai")
def tema_ai_endpoint(body: TemaAIRequest):
    """
    Endpoint TEMA_AI:
    1) calcola il tema natale
    2) costruisce un payload_ai compatto
    3) chiama Claude
    4) restituisce:
       - result: JSON strutturato (interpretazione)
       - ai_debug: raw_text + usage + cost_usd + elapsed_sec
    """
    # 1) Calcolo tema natale (riuso la stessa logica di /tema)
    try:
        tema = costruisci_tema_natale(
            body.citta,
            body.data,
            body.ora,
            sistema_case="equal",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore calcolo tema: {e}")

    # 2) Costruzione payload_ai compatto (FREE vs PREMIUM)
    payload_ai = build_payload_tema_ai(tema, tier=body.tier)

    # 3) Chiamata a Claude (con token limit differenziato per tier)
    try:
        claude_debug = call_claude_tema_ai(payload_ai, tier=body.tier)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore Claude: {e}")

    # 4) Parsing del JSON generato da Claude
    raw_text = claude_debug.get("raw_text") or ""
    try:
        ai_json = json.loads(raw_text)
    except Exception as e:
        # se non è JSON, lo segnaliamo ma NON buttiamo via il testo
        ai_json = {
            "error": "JSON non valido",
            "parse_error": str(e),
            "raw_preview": raw_text[:4000],
        }

    return {
        "status": "ok",
        "scope": "tema_ai",
        "input": body.model_dump(),
        "payload_ai": payload_ai,
        "result": ai_json,
        "ai_debug": claude_debug,
    }
