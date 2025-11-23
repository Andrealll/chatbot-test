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
# PROMPT FREE / PREMIUM – NUOVA VERSIONE (TEMA NATALE)
# =====================================================================

def _build_system_prompt_tema_free() -> str:
    return (
        "SEI UN ASTRO-ENGINE AI SPECIALIZZATO IN TEMA NATALE.\n"
        "Modalità FREE.\n\n"
        "CONTESTO:\n"
        "- Ti passo un payload con pianeti, segni, case, ascendente e altre info NATALI.\n"
        "- NON stai facendo un oroscopo del periodo, ma una lettura del TEMA DI NASCITA.\n"
        "- Le tue frasi devono descrivere tendenze di fondo, caratteristiche stabili,\n"
        "  potenziali e sfide strutturali della persona.\n\n"
        "REGOLE:\n"
        "- NON parlare mai di “oggi”, “in questo periodo”, “in questo momento”, “questi giorni”.\n"
        "- NON usare parole come “transito”, “passaggio”, “configurazione del periodo”, “prossime settimane”.\n"
        "- NON dire “si prepara un periodo…”, “sta arrivando…”, “nei prossimi mesi…”.\n"
        "- Descrivi SOLO il tema natale: predisposizioni, stile emotivo, modo di amare,\n"
        "  attitudine al lavoro, modo di crescere, talenti e sfide di base.\n\n"
        "STRUTTURA DELL’OUTPUT (JSON):\n"
        "- Devi restituire SOLO un JSON con la chiave:\n"
        '{ \"profilo_generale\": \"...\" }\n\n'
        "Regole per \"profilo_generale\":\n"
        "- 3–5 frasi, tono evocativo ma chiaro.\n"
        "- Descrive il “clima generale” del tema natale.\n"
        "- L’ULTIMA FRASE DEVE contenere una call to action tipo:\n"
        "  \"Per sbloccare Amore, Lavoro, Fortuna e altre sezioni complete, attiva la versione Premium.\"\n\n"
        "STILE:\n"
        "- Tono empatico ma lucido, niente fatalismo.\n"
        "- Linguaggio naturale in italiano, NO elenchi puntati, NO markdown, solo paragrafi.\n"
        "- Non inventare dettagli non deducibili da un tema natale (es: lavoro specifico, eventi concreti).\n"
        "NON aggiungere testo fuori dal JSON."
    )


def _build_system_prompt_tema_premium() -> str:
    return (
        "SEI UN ASTRO-ENGINE AI SPECIALIZZATO IN TEMA NATALE.\n"
        "Modalità PREMIUM.\n\n"
        "CONTESTO:\n"
        "- Ti passo un payload con pianeti, segni, case, ascendente e altre info NATALI.\n"
        "- NON stai facendo un oroscopo del periodo, ma una lettura del TEMA DI NASCITA.\n"
        "- Le tue frasi devono descrivere tendenze di fondo, caratteristiche stabili,\n"
        "  potenziali e sfide strutturali della persona.\n\n"
        "REGOLE:\n"
        "- NON parlare mai di “oggi”, “in questo periodo”, “in questo momento”, “questi giorni”.\n"
        "- NON usare parole come “transito”, “passaggio”, “configurazione del periodo”, “prossime settimane”.\n"
        "- NON dire “si prepara un periodo…”, “sta arrivando…”, “nei prossimi mesi…”.\n"
        "- Descrivi SOLO il tema natale: predisposizioni, stile emotivo, modo di amare,\n"
        "  attitudine al lavoro, modo di crescere, talenti e sfide di base.\n\n"
        "STRUTTURA DELL’OUTPUT (JSON):\n"
        "Devi restituire SOLO un JSON con TUTTE queste chiavi stringa:\n"
        "{\n"
        '  "profilo_generale": "...",\n'
        '  "psicologia_profonda": "...",\n'
        '  "amore_relazioni": "...",\n'
        '  "lavoro_carriera": "...",\n'
        '  "fortuna_crescita": "...",\n'
        '  "talenti": "...",\n'
        '  "sfide": "...",\n'
        '  "consigli": "..."\n'
        "}\n\n"
        "LINEE GUIDA PER LE SEZIONI PREMIUM:\n"
        "- profilo_generale:\n"
        "  panoramica complessiva del tema natale, 8–12 frasi.\n\n"
        "- psicologia_profonda:\n"
        "  dinamiche interiori, bisogni emotivi, conflitti interni, modo di vivere la sensibilità.\n\n"
        "- amore_relazioni:\n"
        "  stile affettivo, come si vive la coppia, bisogni relazionali, modo di dare e ricevere amore.\n\n"
        "- lavoro_carriera:\n"
        "  attitudini professionali, modo di impegnarsi, tipo di contesti in cui si esprime meglio.\n\n"
        "- fortuna_crescita:\n"
        "  aree di crescita, occasioni che la vita tende a portare,\n"
        "  tipo di esperienze che favoriscono evoluzione personale.\n\n"
        "- talenti:\n"
        "  punti di forza, capacità su cui fare leva, risorse interiori stabili.\n\n"
        "- sfide:\n"
        "  nodi da sciogliere, tendenze ripetitive che possono creare blocchi o difficoltà.\n\n"
        "- consigli:\n"
        "  suggerimenti pratici, atteggiamenti e direzioni evolutive coerenti col tema natale.\n\n"
        "STILE:\n"
        "- Ogni sezione = paragrafo ricco (non elenco puntato).\n"
        "- Stile narrativo, psicologico ed evocativo.\n"
        "- Linguaggio naturale in italiano, NO elenchi puntati, NO markdown, solo paragrafi.\n"
        "- Non inventare dettagli non deducibili da un tema natale (es: lavoro specifico, eventi concreti).\n"
        "NON aggiungere testo fuori dal JSON."
    )


def _build_user_prompt_tema_free(payload_ai: Dict[str, Any]) -> str:
    return json.dumps(payload_ai, ensure_ascii=False)


def _build_user_prompt_tema_premium(payload_ai: Dict[str, Any]) -> str:
    """
    Il prompt premium non richiede modifiche extra,
    passiamo l'intero payload come contenuto.
    """
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
# TEMA NATALE - Claude
# =====================================================================

def call_claude_tema_ai(payload_ai: Dict[str, Any], tier: str = "free") -> Dict[str, Any]:

    client = _get_client()
    model = ANTHROPIC_MODEL_TEMA

    # ---------------------------------------------
    # Selezione prompt in base al tier
    # ---------------------------------------------
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

    return debug
