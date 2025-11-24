from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time
from datetime import datetime
from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.ai_sinastria_claude import call_claude_sinastria_ai

router = APIRouter(prefix="/sinastria_ai", tags=["sinastria_ai"])


class Persona(BaseModel):
    citta: str
    data: str
    ora: str
    nome: Optional[str] = None


class SinastriaAIRequest(BaseModel):
    A: Persona
    B: Persona
    tier: Optional[str] = "free"  # "free" | "premium"


def _normalize_tier(raw: Optional[str]) -> str:
    if not raw:
        return "free"
    s = raw.strip().lower()
    if s in {"premium", "pro", "paid"}:
        return "premium"
    return "free"

@router.post("/")
async def sinastria_ai_endpoint(payload: SinastriaAIRequest):
    start = time.time()
    tier = _normalize_tier(payload.tier)

    try:
        # 1) Costruzione dei datetime per A e B (formati: YYYY-MM-DD, HH:MM)
        try:
            dt_A = datetime.fromisoformat(f"{payload.A.data} {payload.A.ora}")
            dt_B = datetime.fromisoformat(f"{payload.B.data} {payload.B.ora}")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato data/ora non valido: {e}"
            )

        # 2) Calcolo sinastria numerica con AstroBot (firma: sinastria(dt_A, citta_A, dt_B, citta_B))
        sinastria_data = calcola_sinastria(
            dt_A,
            payload.A.citta,
            dt_B,
            payload.B.citta,
        )

        # 3) Costruzione payload_ai da passare a Claude
        payload_ai: Dict[str, Any] = {
            "meta": {
                "scope": "sinastria_ai",
                "tier": tier,
                "lingua": "it",
                "nome_A": payload.A.nome,
                "nome_B": payload.B.nome,
            },
            "sinastria": sinastria_data,
        }

        # 4) Chiamata a Claude
        sinastria_ai = call_claude_sinastria_ai(payload_ai)

        elapsed = time.time() - start

        return {
            "status": "ok",
            "elapsed": elapsed,
            "input": {
                "A": payload.A.dict(),
                "B": payload.B.dict(),
                "tier": tier,
            },
            "payload_ai": payload_ai,
            "sinastria_ai": sinastria_ai,
            "error": None,
        }

    except HTTPException:
        # le rilanciamo così come sono (es. errore formato data/ora)
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore interno /sinastria_ai: {e}")
