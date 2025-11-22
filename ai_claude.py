import os
import json
import time
from typing import Any, Dict

from anthropic import Anthropic, APIStatusError  # type: ignore

# ============================================================
#  CONFIGURAZIONE CLIENT CLAUDE
# ============================================================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

if not ANTHROPIC_API_KEY:
    raise RuntimeError("Missing ANTHROPIC_API_KEY environment variable")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Prezzi stimati Haiku per i costi
PRICE_INPUT_PER_M = 0.25   # $ per 1M token input
PRICE_OUTPUT_PER_M = 1.25  # $ per 1M token output


# ============================================================
#  HELPER GENERICO
# ============================================================

def _call_claude_json(
    *,
    model: str,
    system_prompt: str,
    payload: Dict[str, Any],
    max_tokens: int = 1500,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """
    Chiama Claude e restituisce SEMPRE un dict con:
      - raw_text
      - usage: {input_tokens, output_tokens}
      - cost_usd
      - elapsed_sec
      - model
      - (eventuale) error
    """

    start_time = time.time()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False),
                        }
                    ],
                }
            ],
        )
        elapsed = time.time() - start_time
    except (APIStatusError, Exception) as e:
        elapsed = time.time() - start_time
        return {
            "raw_text": "",
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
            },
            "cost_usd": None,
            "elapsed_sec": elapsed,
            "model": model,
            "error": repr(e),
        }

    # Estrai testo
    raw_text = ""
    if response.content and len(response.content) > 0:
        # SDK Anthropic: ogni "content" è un oggetto con attributo .text
        first_chunk = response.content[0]
        raw_text = getattr(first_chunk, "text", "") or ""

    # Token / costi
    input_tokens = getattr(response.usage, "input_tokens", None)
    output_tokens = getattr(response.usage, "output_tokens", None)

    cost_usd = None
    if input_tokens is not None and output_tokens is not None:
        cost_usd = (
            (input_tokens / 1_000_000) * PRICE_INPUT_PER_M
            + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
        )

    ai_debug = {
        "raw_text": raw_text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "cost_usd": cost_usd,
        "elapsed_sec": time.time() - start_time,
        "model": model,
    }

    return ai_debug


# ============================================================
#  TEMA NATALE: call_claude_tema_ai
# ============================================================
from typing import Dict, Any, Tuple, Optional
import json
import time
from anthropic import APIStatusError

# qui assumo che tu abbia già creato il client in alto nel file:
# client = _create_astrobot_client()


def call_claude_tema_ai(
    payload_ai: Dict[str, Any],
    tier: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Chiama Claude Haiku per generare l'interpretazione del TEMA NATALE.

    Input: payload_ai = dict con:
      - meta: { nome, citta, data_nascita, ora_nascita, tier, lang, ... }
      - pianeti: posizione dei pianeti nei segni
      - case: info ascendente, MC, sistema di case, ecc.

    Può gestire anche il caso in cui venga chiamata per errore con un tuple:
    call_claude_tema_ai((payload_ai, tier))
    """

    MODEL_TEMA = "claude-3-5-haiku-20241022"

    # ---- NORMALIZZAZIONE INPUT (fix per 'tuple' object has no attribute 'get') ----
    # Se per qualche motivo arriva una tupla (payload_ai, tier) la spacchettiamo.
    if isinstance(payload_ai, tuple):
        if len(payload_ai) == 2 and isinstance(payload_ai[0], dict):
            real_payload, maybe_tier = payload_ai
            payload_ai = real_payload
            if tier is None and isinstance(maybe_tier, str):
                tier = maybe_tier
        else:
            raise TypeError(
                f"call_claude_tema_ai: payload_ai tuple non valida: {repr(payload_ai)}"
            )

    if not isinstance(payload_ai, dict):
        raise TypeError(
            f"call_claude_tema_ai: payload_ai deve essere un dict, trovato {type(payload_ai)}"
        )

    meta = payload_ai.get("meta") or {}
    # Se non mi hai passato tier esplicito, lo leggo dal payload
    if tier is None:
        tier = str(meta.get("tier", "free")).lower()
    else:
        tier = str(tier).lower()
        meta["tier"] = tier
        payload_ai["meta"] = meta

    # Prezzi Haiku (stimati) per il calcolo costi
    PRICE_INPUT_PER_M = 0.25   # $ per 1M token input
    PRICE_OUTPUT_PER_M = 1.25  # $ per 1M token output

    system_prompt = """
SEI ASTROBOT, UN ASTRO-ENGINE AI CHE INTERPRETA IL TEMA NATALE.

CONTESTO
- Ricevi un payload JSON che contiene:
  - meta: informazioni sulla persona (nome, città, data/ora di nascita, tier: "free" o "premium", lingua, ecc.).
  - pianeti: posizione dei pianeti nei segni (con eventuale indicazione di moto retrogrado).
  - case: informazioni sull'Ascendente, Medio Cielo, sistema di case, ecc.
- Devi generare un’interpretazione PSICOLOGICA e NARRATIVA del tema natale.

REGOLE GENERALI
- Usa SOLO le informazioni presenti nel payload.
- NON inventare posizioni, aspetti o configurazioni non fornite.
- Puoi citare pianeti, segni, case e aspetti IN MODO NARRATIVO, collegandoli tra loro.
- Linguaggio: italiano, seconda persona singolare ("tu").
- Nessuna percentuale, nessun tecnicismo inventato, nessun gergo pseudo-scientifico.
- Stile: chiaro, caldo, coinvolgente ma non fuffa new age.

STRUTTURA DI OUTPUT (OBBLIGATORIA)
Devi SEMPRE restituire ESATTAMENTE un JSON con questa struttura:

{
  "profilo_generale": {
    "titolo": "Profilo generale",
    "testo": "..."
  },
  "amore_relazioni": {
    "titolo": "Amore e relazioni",
    "testo": "..."
  },
  "lavoro_vocazione": {
    "titolo": "Lavoro e vocazione",
    "testo": "..."
  },
  "crescita_personale_spirituale": {
    "titolo": "Crescita personale e spirituale",
    "testo": "..."
  },
  "shadow_work": {
    "titolo": "Shadow work",
    "testo": "..."
  },
  "riassunto": {
    "personalita": "...",
    "talenti": "...",
    "sfide": "..."
  }
}

- NON aggiungere altre chiavi al primo livello.
- NON aggiungere commenti, spiegazioni o testo fuori dal JSON.
- TUTTI i valori "testo"/"personalita"/"talenti"/"sfide" devono essere stringhe.

CONTENUTO DELLE SEZIONI (LINEE GUIDA)

[1] profilo_generale
- Integra: Sole, segno solare, Luna, segno lunare, Ascendente, case rilevanti (1ª, 4ª, 7ª, 10ª se disponibili).
- Descrivi: temperamento di base, bisogni emotivi, modo in cui ti presenti al mondo.
- Collega in modo chiaro eventuali contrasti (es. Sole in segno d’acqua + Luna in segno di fuoco + Ascendente in segno di terra).

[2] amore_relazioni
- Focalizzati su: Luna, Venere, Marte, Plutone, case 5ª, 7ª, 8ª (se ricavabili dal contesto), aspetti di armonia e tensione tra questi pianeti.
- Descrivi: come vivi l’affettività, come ti innamori, cosa ti attrae, quali dinamiche ricorrenti puoi incontrare nelle relazioni.
- Evidenzia risorse (capacità di amare, passione, profondità) e possibili blocchi (paura di abbandono, gelosia, sfiducia).

[3] lavoro_vocazione
- Focalizzati su: Sole, Mercurio, Giove, Saturno, Marte, Medio Cielo / 10ª casa, eventuali segnature di terra/fuoco/aria/acqua.
- Descrivi: stile lavorativo, talenti mentali e pratici, che tipo di attività o ambienti ti valorizzano, rapporto con disciplina e responsabilità.
- Inserisci collegamenti tra vocazione profonda e modalità concrete di realizzarla.

[4] crescita_personale_spirituale
- Focalizzati su: Nodo Lunare, Nettuno, Plutone, eventuali configurazioni che parlano di trasformazione, ricerca di senso, intuizione.
- Descrivi: direzione evolutiva dell’anima, temi di crescita interiore, modalità con cui la vita ti invita a cambiare.

[5] shadow_work
- Metti a fuoco i PUNTI DI TENSIONE: quadrature, opposizioni, quincunx, Lilith, eventuali accumuli in segni/case “sensibili”.
- Descrivi: quali dinamiche tendono a creare blocchi, autosabotaggi, paure.
- Offri spunti di integrazione: come lavorare su questi temi in modo costruttivo, senza giudizio.

[6] riassunto
- "personalita": sintesi compatta del profilo generale (2–4 frasi).
- "talenti": elenco ragionato (in forma discorsiva) dei principali punti di forza.
- "sfide": principali lezioni di vita, difficoltà da integrare, punti di attenzione.

LOGICA FREE vs PREMIUM
- Leggi meta.tier nel payload ("free" o "premium").

- Se tier = "free":
  - Ogni campo "testo" delle sezioni principali
    deve essere BREVE: massimo 2–3 frasi per sezione.
  - Anche "personalita", "talenti", "sfide" devono essere compatti.
  - Obiettivo: dare un assaggio chiaro ma NON esaustivo.

- Se tier = "premium":
  - Ogni campo "testo" delle sezioni principali può essere articolato:
    2–4 paragrafi brevi per sezione (o testo equivalente ben strutturato).
  - "personalita", "talenti", "sfide" possono essere più ricchi e dettagliati.
  - Obiettivo: analisi approfondita e integrata, con riferimenti espliciti
    ma naturali a pianeti, segni e case.

IMPORTANTISSIMO
- NON cambiare i nomi delle chiavi.
- NON aggiungere testo fuori dal JSON.
- Se devi citare aspetti o posizioni, fallo dentro al testo narrativo,
  non come elenco tecnico sterile.
    """.strip()

    start_time = time.time()

    try:
        response = client.messages.create(
            model=MODEL_TEMA,
            max_tokens=1200,
            temperature=0.7,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload_ai, ensure_ascii=False)
                        }
                    ]
                }
            ]
        )
    except APIStatusError as e:
        elapsed = time.time() - start_time
        # In caso di errore API restituiamo un result "di errore" + debug
        result = {
            "error": "Claude call failed",
            "detail": str(e),
        }
        ai_debug = {
            "raw_text": "",
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
            },
            "cost_usd": None,
            "elapsed_sec": elapsed,
            "model": MODEL_TEMA,
            "error": repr(e),
        }
        return result, ai_debug

    elapsed = time.time() - start_time

    # Estrai testo grezzo
    raw_text = ""
    if response.content and len(response.content) > 0:
        raw_text = response.content[0].text

    # Prova a parsare il JSON
    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        # Se il modello ha sbagliato formato, incapsuliamo come errore
        result = {
            "error": "Invalid JSON from Claude",
            "raw": raw_text,
        }

    # Usage & costi
    input_tokens = getattr(response.usage, "input_tokens", None)
    output_tokens = getattr(response.usage, "output_tokens", None)

    cost_usd = None
    if input_tokens is not None and output_tokens is not None:
        cost_usd = (
            (input_tokens / 1_000_000) * PRICE_INPUT_PER_M
            + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
        )

    ai_debug = {
        "raw_text": raw_text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "cost_usd": cost_usd,
        "elapsed_sec": elapsed,
        "model": MODEL_TEMA,
    }

    return result, ai_debug



# ============================================================
#  PLACEHOLDER: oroscopo AI (non usato in questo momento)
#  (Tienilo così giusto per non rompere eventuali import)
# ============================================================

def call_claude_oroscopo_ai(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder per future estensioni /oroscopo_ai.
    Al momento restituisce solo un errore descrittivo.
    """
    return {
        "raw_text": "",
        "usage": {"input_tokens": None, "output_tokens": None},
        "cost_usd": None,
        "elapsed_sec": 0.0,
        "model": "claude-3-5-sonnet-20241022",
        "error": "call_claude_oroscopo_ai non è ancora implementato",
    }
