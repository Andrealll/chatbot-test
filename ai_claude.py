import os
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple

from anthropic import Anthropic, APIStatusError

logger = logging.getLogger(__name__)

# =====================================================================
# Client Anthropic unico
# =====================================================================
# Modello per il TEMA: di default Claude 3.5 Haiku
ANTHROPIC_MODEL_TEMA = os.getenv("ANTHROPIC_MODEL_TEMA", "claude-3-5-haiku-20241022")

# Client Anthropic lazy (per evitare casini a import)
_ANTHROPIC_CLIENT: Optional[Anthropic] = None

def _get_client() -> Anthropic:
    """
    Restituisce un client Anthropic inizializzato.
    Usa la variabile d'ambiente ANTHROPIC_API_KEY (senza underscore davanti).
    """
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is not None:
        return _ANTHROPIC_CLIENT

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non impostata nell'ambiente (.env / variabili di sistema)")

    _ANTHROPIC_CLIENT = Anthropic(api_key=api_key)
    return _ANTHROPIC_CLIENT

def _build_system_prompt_tema(tier: str = "free") -> str:
    """
    System prompt di base per interpretare il TEMA NATALE.
    Lo teniamo semplice: il JSON strutturato lo farà il livello successivo se serve.
    Qui l'obiettivo è avere un testo narrativo compatto, ma noi per ora
    ci limitiamo a chiedere un JSON ben formato.
    """
    return (
        "SEI UN ASTROLOGO ESPERTO.\n"
        "Riceverai un oggetto JSON con:\n"
        "- meta (scope, tier, version)\n"
        "- pianeti: pianeti con segno, gradi_eclittici, retrogrado\n"
        "- case: informazioni su Ascendente, MC e case.\n\n"
        "DEVI RESTITUIRE ESCLUSIVAMENTE UN OGGETTO JSON BEN FORMATO (NESSUN TESTO FUORI DAL JSON),\n"
        "con questa struttura indicativa:\n"
        "{\n"
        '  "profilo_generale": "testo...",\n'
        '  "talenti": ["...", "..."],\n'
        '  "sfide": ["...", "..."],\n'
        '  "consigli": ["...", "..."]\n'
        "}\n"
        "Non aggiungere spiegazioni prima o dopo il JSON."
    )

# =====================================================================
# Helpers comuni
# =====================================================================
def _compute_cost_haiku(input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[float]:
    """
    Calcola il costo stimato per Haiku 3.5.
    Prezzi (indicativi):
      - input: 0.25 $ / 1M token
      - output: 1.25 $ / 1M token
    """
    if input_tokens is None or output_tokens is None:
        return None

    PRICE_INPUT_PER_M = 0.25   # $ per 1M token input
    PRICE_OUTPUT_PER_M = 1.25  # $ per 1M token output

    return (
        (input_tokens / 1_000_000) * PRICE_INPUT_PER_M
        + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
    )


def _build_debug_dict(
    *,
    model: str,
    raw_text: str,
    elapsed: float,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cost_usd: Optional[float],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Costruisce il dict di debug che le route si aspettano.
    """
    debug: Dict[str, Any] = {
        "raw_text": raw_text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "cost_usd": cost_usd,
        "elapsed_sec": elapsed,
        "model": model,
    }
    if error is not None:
        debug["error"] = error
    return debug


# =====================================================================
# TEMA NATALE - Claude
# =====================================================================
def call_claude_tema_ai(payload_ai: Dict[str, Any], tier: str = "free") -> Dict[str, Any]:
    """
    Chiama Claude (Claude 3.5 Haiku) per il TEMA NATALE.
    - payload_ai: dict compatto generato da build_payload_tema_ai
    - tier: 'free' | 'premium' (per futura modulazione, per ora solo nel prompt)

    Ritorna SEMPRE un dict del tipo:

    {
        "raw_text": "<testo restituito da Claude>",
        "usage": {"input_tokens": int | None, "output_tokens": int | None},
        "cost_usd": float | None,
        "elapsed_sec": float | None,
        "model": "<nome-modello>",
        "error": "..."  # solo se c'è stato un errore
    }
    """
    client = _get_client()
    model = ANTHROPIC_MODEL_TEMA

    system_prompt = _build_system_prompt_tema(tier=tier)

    user_content = json.dumps(payload_ai, ensure_ascii=False)

    start = time.time()
    raw_text = ""
    usage = {"input_tokens": None, "output_tokens": None}
    cost_usd = None
    error_msg: Optional[str] = None

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0.4,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
        )

        # Anthropic v1: resp.content è una lista di blocchi, di solito 1 text block
        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        raw_text = "".join(parts).strip()

        # usage
        try:
            usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", None),
                "output_tokens": getattr(resp.usage, "output_tokens", None),
            }
        except Exception:
            usage = {"input_tokens": None, "output_tokens": None}

        # Se vuoi calcolare il costo, puoi aggiungerlo qui in base al listino Anthropic
        cost_usd = None

    except APIStatusError as e:
        error_msg = f"APIStatusError: {e.status_code} - {e.message}"
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"

    elapsed_sec = time.time() - start

    debug: Dict[str, Any] = {
        "raw_text": raw_text,
        "usage": usage,
        "cost_usd": cost_usd,
        "elapsed_sec": elapsed_sec,
        "model": model,
    }

    if error_msg:
        debug["error"] = error_msg

    return debug