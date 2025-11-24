# =========================================================
#  routes_oroscopo.py — AstroBot (oroscopo + oroscopo_ai)
#  Versione pulita e funzionante
# =========================================================

import os
import time
import json
from typing import Any, Dict, List, Optional, Literal
import requests
from anthropic import Anthropic, APIStatusError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from astrobot_core.oroscopo_payload_ai import (
    AI_ENTITY_LIMITS,
    DEFAULT_PERIOD_KEY,
    DEFAULT_TIER,
    PERIOD_KEY_TO_CODE,
    build_oroscopo_payload_ai,
)

router = APIRouter(prefix="/oroscopo", tags=["Oroscopo"])

# ==========================
# MODELLI
# ==========================

class OroscopoAIRequest(BaseModel):
    scope: Literal["oroscopo_ai"] = "oroscopo_ai"
    tier: Literal["free", "premium"]
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    payload_ai: Dict[str, Any]

class OroscopoSiteRequest(BaseModel):
    nome: Optional[str] = None
    citta: str
    data_nascita: str
    ora_nascita: str
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    tier: Literal["free", "premium", "auto"] = "auto"

# ==========================
# UTILS
# ==========================

def _resolve_tier_from_site(req_tier: str) -> str:
    if req_tier in ("free", "premium"):
        return req_tier
    return "free"

def _summary_intensities(period_block: Dict[str, Any]) -> Dict[str, float]:
    metriche = period_block.get("metriche_grafico", {})
    samples = metriche.get("samples", [])
    if not samples:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}

    acc = {}
    n = 0
    for s in samples:
        intens = s.get("metrics", {}).get("intensities", {})
        for k, v in intens.items():
            acc[k] = acc.get(k, 0.0) + float(v)
        n += 1

    return {k: acc[k] / n for k in acc}


def _summary_pianeti(period_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    return period_block.get("pianeti_prevalenti", [])


def _summary_aspetti(period_block: Dict[str, Any], max_n: int = 10):
    arr = period_block.get("aspetti_rilevanti", [])
    out = []
    for a in arr[:max_n]:
        out.append({
            "chiave": a.get("chiave"),
            "pianeta_transito": a.get("pianeta_transito"),
            "pianeta_natale": a.get("pianeta_natale"),
            "aspetto": a.get("aspetto"),
            "score_rilevanza": a.get("score_rilevanza"),
            "orb_min": a.get("orb_min"),
            "n_snapshot": a.get("n_snapshot"),
        })
    return out


def _extract_period_block(payload_ai: Dict[str, Any], periodo: str):
    blocco = payload_ai.get("periodi", {}).get(periodo)
    if not blocco:
        return {}
    return blocco


# =========================================================
#  SUPER-PROMPT (Claude)
# =========================================================

SUPER_PROMPT = """
SEI ASTROBOT AI.
Generi SEMPRE e SOLO JSON valido.
(…omesso per brevità: usa quello lungo che hai già) 
""".strip()


# =========================================================
#  CHIAMATA CLAUDE
# =========================================================

def _call_claude_json(messages, model, max_tokens, temperature):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY non configurata")

    client = Anthropic(api_key=api_key)

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=messages["system"],
            messages=[{"role": "user", "content": messages["user"]}],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore Claude: {e}")

    text = resp.content[0].text if resp.content else ""

    try:
        return json.loads(text)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=f"Claude ha restituito JSON non valido: {text[:300]}",
        )


# =========================================================
#  BUILD MESSAGES
# =========================================================

def _build_messages(payload_ai, periodo, tier):
    period_block = _extract_period_block(payload_ai, periodo)
    meta = payload_ai.get("meta", {})

    user_payload = {
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "tier": tier,
        },
        "periodo": periodo,
        "intensities": _summary_intensities(period_block),
        "pianeti_prevalenti": _summary_pianeti(period_block),
        "aspetti_chiave": _summary_aspetti(period_block, max_n=20),
    }

    return {
        "system": SUPER_PROMPT,
        "user": json.dumps(user_payload, ensure_ascii=False),
    }


# =========================================================
#  /oroscopo_ai
# =========================================================

@router.post("/ai")
def oroscopo_ai(req: OroscopoAIRequest):
    start = time.time()

    payload_ai = req.payload_ai
    periodo = req.periodo
    tie
