# ai_claude.py
import os
import json
from typing import Dict, Any

from anthropic import Anthropic, APIStatusError


# Modello di default se non impostato via env
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")


# Inizializza client globale (fallirà all'avvio se manca la key → meglio così)
client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"]
)


def call_claude_oroscopo_ai(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chiamata a Claude per l'oroscopo AI.

    `payload_ai` è esattamente quello che costruisci oggi nel backend
    (meta, periodi, kb, ecc.).

    Ritorna un dict Python (JSON parse dell’output del modello).
    """

    # ⚠️ QUI devi incollare il TUO prompt di sistema definitivo
    # (quello che abbiamo costruito per /oroscopo_ai, con regole su periodi, tier, sezioni, JSON, ecc.)
    system_prompt = """
SEI ASTROBOT, UN ASTRO-ENGINE AI CHE GENERA OROSCOPI PERSONALIZZATI.

[QUI INCOLLA IL TUO SYSTEM PROMPT DEFINITIVO PER /oroscopo_ai]
- Regole su: periodi (giornaliero/settimanale/mensile/annuale)
- Differenze free/premium
- Struttura JSON di output (sezioni, capitoli, titoli, ecc.)
- Divieti (niente percentuali, niente tecnicismi inventati, ecc.)
- Utilizzo di meta, periodi, kb, ecc.
    """.strip()

    # Input "utente": payload_ai serializzato + istruzioni chiare
    user_prompt = (
        "Di seguito trovi il payload AI JSON con tutte le informazioni astrologiche "
        "necessarie per generare l'oroscopo.\n\n"
        "PAYLOAD_AI:\n"
        f"{json.dumps(payload_ai, ensure_ascii=False)}\n\n"
        "IMPORTANTE:\n"
        "- Usa SOLO le informazioni presenti nel payload.\n"
        "- NON inventare dati astrologici.\n"
        "- Rispondi SOLO con un JSON valido, SENZA testo extra, "
        "che rispetti lo schema richiesto nel prompt di sistema.\n"
    )

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1800,  # alza se serve per annuale premium
            temperature=0.6,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt,
                        }
                    ],
                }
            ],
        )
    except APIStatusError as e:
        # Log utile in console (Render + locale)
        print("[CLAUDE ERROR]", e.status_code, e.response)
        raise

    # Claude v1 API: il testo è in response.content[0].text
    text = ""
    if response.content and len(response.content) > 0:
        text = response.content[0].text

    # Proviamo a fare il parse del JSON in maniera robusta
    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError:
        # fallback: prova a "ripulire" se il modello ha aggiunto ``` o "json"
        cleaned = text.strip()

        # Rimuovi blocchi di codice tipo ```json ... ```
        if cleaned.startswith("```"):
            # togli i backtick iniziali/finali
            cleaned = cleaned.strip("`").strip()
            # togli l'eventuale parola "json" all'inizio
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        # Ultimo tentativo di parse
        data = json.loads(cleaned)
        return data
import time  # se non è già importato in alto

def _estimate_cost(usage: Dict[str, int]) -> float:
    """
    Stima costo in USD per Claude 3.5 Sonnet (input/output per milione di token).
    """
    INPUT_PRICE = 3.0 / 1_000_000   # $3 / 1M token input (esempio)
    OUTPUT_PRICE = 15.0 / 1_000_000 # $15 / 1M token output (esempio)

    return round(
        usage.get("input_tokens", 0) * INPUT_PRICE
        + usage.get("output_tokens", 0) * OUTPUT_PRICE,
        6,
    )


def call_claude_tema_ai(payload_ai: Dict[str, Any], tier: str = "free") -> Dict[str, Any]:
    """
    Chiamata a Claude per TEMA_AI.

    Ritorna TUTTO quello che ti serve per ai_debug:
    - raw_text
    - usage (input/output tokens)
    - cost_usd
    - elapsed_sec
    - model
    """

    system_prompt = """
Sei ASTROBOT, un modello di interpretazione astrologica.

Compito:
- Ricevi un payload compatto del TEMA NATALE in formato JSON.
- Devi restituire SOLO un JSON valido con questa struttura:

{
  "personalita": "testo breve",
  "talenti": "testo breve",
  "sfide": "testo breve"
}

Linee guida:
- Usa SOLO le informazioni presenti nel payload.
- Non inventare posizioni o aspetti non presenti.
- Tono: chiaro, concreto, psicologico, senza termini tecnici strani.
- Niente percentuali, niente fuffa motivazionale.
""".strip()

    # Puoi usare il tier per modulare la lunghezza (più lungo per premium, più corto per free)
    if tier == "premium":
        max_tokens = 900
    else:
        max_tokens = 500

    user_prompt = (
        "Di seguito trovi il payload AI del TEMA NATALE (compatto):\n\n"
        f"{json.dumps(payload_ai, ensure_ascii=False)}\n\n"
        "IMPORTANTE:\n"
        "- Rispondi SOLO con un JSON valido che rispetta lo schema richiesto.\n"
        "- Nessun testo fuori dal JSON, nessun commento.\n"
    )

    t0 = time.time()

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=0.5,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt,
                        }
                    ],
                }
            ],
        )
    except APIStatusError as e:
        print("[CLAUDE TEMA_AI ERROR]", e.status_code, e.response)
        # Rilancio l'eccezione, ci penserà FastAPI a trasformarla in 500
        raise

    t1 = time.time()

    raw_text = ""
    if response.content and len(response.content) > 0:
        raw_text = response.content[0].text

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", None),
        "output_tokens": getattr(response.usage, "output_tokens", None),
    }

    cost_usd = _estimate_cost(usage)

    return {
        "raw_text": raw_text,
        "usage": usage,
        "cost_usd": cost_usd,
        "elapsed_sec": round(t1 - t0, 3),
        "model": ANTHROPIC_MODEL,
    }
