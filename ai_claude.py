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
ANTHROPIC_MODEL_TEMA = os.getenv("ANTHROPIC_MODEL_TEMA", "claude-3-5-haiku-20241022")

_ANTHROPIC_CLIENT: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is not None:
        return _ANTHROPIC_CLIENT

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non impostata nell'ambiente")

    _ANTHROPIC_CLIENT = Anthropic(api_key=api_key)
    return _ANTHROPIC_CLIENT


# =====================================================================
# PROMPT FREE / PREMIUM – VERSIONE ORIGINALE
# =====================================================================

def _build_system_prompt_tema_free() -> str:
    return (
        "SEI UN ASTROLOGO PROFESSIONISTA.\n"
        "Modalità FREE.\n"
        "Devi restituire SOLO un JSON con la chiave:\n"
        '{ "profilo_generale": "..." }\n\n'
        "Regole FREE:\n"
        "- Solo 3–5 frasi molto evocative.\n"
        "- Niente tecnicismi.\n"
        "- Nessuna citazione degli aspetti.\n"
        "- Aggiungi una CTA finale:\n"
        '"Per sbloccare Amore, Lavoro, Fortuna e altre sezioni complete, attiva la versione Premium."\n'
        "NON aggiungere testo fuori dal JSON."
    )


def _build_system_prompt_tema_premium() -> str:
    return (
        "SEI UN ASTROLOGO PROFESSIONISTA.\n"
        "Modalità PREMIUM.\n"
        "Devi restituire SOLO un JSON con le seguenti chiavi:\n"
        '{\n'
        '  "profilo_generale": "",\n'
        '  "psicologia_profonda": "",\n'
        '  "amore_relazioni": "",\n'
        '  "lavoro_carriera": "",\n'
        '  "fortuna_crescita": "",\n'
        '  "talenti": "",\n'
        '  "sfide": "",\n'
        '  "consigli": ""\n'
        "}\n\n"
        "Regole PREMIUM:\n"
        "- Ogni sezione = paragrafo ricco di 10–15 frasi.\n"
        "- Stile narrativo, psicologico, evocativo.\n"
        "- Nessun elenco, solo paragrafi.\n"
        "- Non inventare aspetti non presenti.\n"
        "- Nessun testo fuori dal JSON."
    )


def _build_user_prompt_tema_free(payload_ai: Dict[str, Any]) -> str:
    return json.dumps(payload_ai, ensure_ascii=False)


def _build_user_prompt_tema_premium(payload_ai: Dict[str, Any]) -> str:
    return json.dumps(payload_ai, ensure_ascii=False)


# =====================================================================
# Helpers
# =====================================================================

def _compute_cost_haiku(input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[float]:
    if input_tokens is None or output_tokens is None:
        return None

    PRICE_INPUT_PER_M = 0.25
    PRICE_OUTPUT_PER_M = 1.25

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
# PARSE del JSON prodotto da Claude
# =====================================================================

def _parse_claude_json(raw_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Claude a volte restituisce:
    - testo puro
    - JSON con rumore
    - JSON dentro triple backticks
    - JSON preceduto/seguito da testo
    """

    if not raw_text or raw_text.strip() == "":
        return None, "Risposta vuota."

    txt = raw_text.strip()

    # Caso perfetto: JSON nudo
    if txt.startswith("{") and txt.endswith("}"):
        try:
            return json.loads(txt), None
        except Exception as e:
            return None, f"Errore parse JSON diretto: {e}"

    # Cerco il primo '{' e ultimo '}'
    try:
        start = txt.index("{")
        end = txt.rindex("}") + 1
        snippet = txt[start:end]
        return json.loads(snippet), None
    except Exception as e:
        return None, f"Errore parse JSON da estrazione: {e}"


# =====================================================================
# TEMA NATALE - Claude
# =====================================================================

def call_claude_tema_ai(payload_ai: Dict[str, Any], tier: str = "free") -> Dict[str, Any]:

    client = _get_client()
    model = ANTHROPIC_MODEL_TEMA

    if tier == "premium":
        system_prompt = _build_system_prompt_tema_premium()
        user_prompt = _build_user_prompt_tema_premium(payload_ai)
    else:
        system_prompt = _build_system_prompt_tema_free()
        user_prompt = _build_user_prompt_tema_free(payload_ai)

    start = time.time()
    raw_text = ""
    usage = {"input_tokens": None, "output_tokens": None}
    cost_usd = None
    error_msg: Optional[str] = None

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.4,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)

        raw_text = "".join(parts).strip()

        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", None),
            "output_tokens": getattr(resp.usage, "output_tokens", None),
        }

        cost_usd = _compute_cost_haiku(
            usage["input_tokens"], usage["output_tokens"]
        )

    except APIStatusError as e:
        error_msg = f"APIStatusError: {e.status_code} - {e.message}"
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"

    elapsed_sec = time.time() - start

    debug = _build_debug_dict(
        model=model,
        raw_text=raw_text,
        elapsed=elapsed_sec,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost_usd=cost_usd,
        error=error_msg,
    )

    # ===============================================================
    # PARSING JSON → result
    # ===============================================================
    if error_msg:
        return {
            "result": {
                "error": "Errore API Claude",
                "detail": error_msg,
                "raw_preview": raw_text[:500],
            },
            "ai_debug": debug,
        }

    parsed, parse_err = _parse_claude_json(raw_text)

    if parse_err or parsed is None:
        return {
            "result": {
                "error": "JSON non valido",
                "parse_error": parse_err,
                "raw_preview": raw_text[:500],
            },
            "ai_debug": debug,
        }

    # ===============================================================
    # OK: ritorno il JSON interpretazione + debug
    # ===============================================================
    return {
        "result": parsed,
        "ai_debug": debug,
    }
