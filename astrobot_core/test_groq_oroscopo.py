######test_groq_oroscopo.py
"""
test_groq_oroscopo.py
-----------------------------------------
Test end-to-end: invia un payload AI ad Groq (LLaMA 3.1 70B)
per generare l'oroscopo mensile premium in formato JSON.
-----------------------------------------
Requisiti:
- Variabile d’ambiente GROQ_API_KEY impostata.
- Libreria requests installata.
"""

import os
import json
import requests
from textwrap import dedent

# ==========================================================
# CONFIGURAZIONE BASE
# ==========================================================

MODEL = "llama-3.1-70b-versatile"
API_URL = "https://api.groq.com/openai/v1/chat/completions"
API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    raise EnvironmentError("❌ Devi impostare la variabile d’ambiente GROQ_API_KEY")

# ==========================================================
# PAYLOAD DI TEST (direttamente incorporato)
# ==========================================================

payload_ai = {
    "meta": {
        "nome": "Andrea",
        "tier": "premium",
        "lang": "it",
        "scope": "oroscopo",
        "segno_sol": "Cancro",
        "ascendente": "Leone",
        "periodo_principale": "mensile",
        "range_date": "2025-11-01 / 2025-11-30",
    },
    "periodo": {
        "codice": "monthly",
        "label": "mensile",
        "anchor_date": "2025-11-01",
        "ambiti": {
            "generale": {
                "drivers": [
                    {"type": "transito_pianeta", "transit_planet": "Marte", "natal_planet": "Urano", "aspect": "congiunzione"},
                    {"type": "transito_pianeta", "transit_planet": "Marte", "natal_planet": "Venere", "aspect": "quadratura"},
                    {"type": "transito_pianeta", "transit_planet": "Sole", "natal_planet": "Mercurio", "aspect": "trigono"},
                    {"type": "transito_pianeta", "transit_planet": "Sole", "natal_planet": "Saturno", "aspect": "congiunzione"},
                    {"type": "transito_pianeta", "transit_planet": "Venere", "natal_planet": "Plutone", "aspect": "congiunzione"},
                ]
            }
        },
    },
    "kb": {
        "combined_markdown": dedent("""
            # Energia e direzione
            Il mese di novembre porta un’intensa spinta all’azione, grazie ai transiti di Marte
            che attivano Urano e Venere. Potresti sentire il desiderio di cambiare routine e
            rompere schemi ormai obsoleti. Tuttavia, è importante gestire l’impulsività e non
            forzare i tempi: Saturno ti ricorda che la disciplina è la vera libertà.

            # Comunicazione e relazioni
            Il trigono Sole–Mercurio stimola la chiarezza mentale e la capacità di esprimerti.
            Venere e Plutone accentuano la profondità emotiva: in amore potresti desiderare
            più autenticità o sentire la necessità di rinnovare un legame.
        """).strip(),
        "lang": "it",
    },
}

# ==========================================================
# PROMPT (system + user)
# ==========================================================

SYSTEM_PROMPT = dedent("""
Sei AstroBot, un'intelligenza artificiale che scrive oroscopi
basati su transiti astrologici già calcolati e una base di conoscenza markdown.

Non inventare transiti, non parlare di salute fisica, e adatta il livello
di dettaglio al tier:
- tier=free  → testo breve, massimo 2 sezioni
- tier=premium → testo più ricco, con consigli pratici

Rispondi sempre in italiano e restituisci SOLO un oggetto JSON valido con
questa struttura:

{
  "meta": { "tier": "...", "periodo": "...", "lang": "it" },
  "summary": { "title": "...", "subtitle": "...", "tone": "..." },
  "highlights": [
    { "label": "...", "description": "...", "related_drivers": [...] }
  ],
  "sections": [
    { "id": "...", "title": "...", "summary": "...", "details": [...], "advice": [...] }
  ]
}
""").strip()

USER_PROMPT = f"""
Genera l'oroscopo mensile per l'utente, utilizzando i dati seguenti:

PAYLOAD_INIZIO
{json.dumps(payload_ai, ensure_ascii=False, indent=2)}
PAYLOAD_FINE
"""

# ==========================================================
# CHIAMATA HTTP A GROQ
# ==========================================================

def call_groq(system_prompt: str, user_prompt: str) -> dict:
    body = {
        "model": MODEL,
        "temperature": 0.7,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    print("[Groq] Invio richiesta...")
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body),
        timeout=60,
    )

    print(f"[Groq] HTTP status: {response.status_code}")
    if response.status_code != 200:
        print(response.text)
        return {}

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        print("⚠️ Errore nel parsing JSON, testo grezzo:")
        print(content)
        return {}
    return parsed


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":
    result = call_groq(SYSTEM_PROMPT, USER_PROMPT)
    print("\n[Groq] Output JSON:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
