import os
from typing import Any, Dict, Optional
from groq import Groq

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def build_prompt(asc, pianeti, meta, domanda_utente=None):
    """Crea prompt completo per l’interpretazione astrologica."""
    asc_info = (
        f"Ascendente in {asc.get('ASC_segno')} a {asc.get('ASC_gradi_segno')}°.\n"
        f"Medio Cielo in {asc.get('MC_segno')} a {asc.get('MC_gradi_segno')}°.\n"
    )

    pianeti_info = "\n".join([
        f"- {nome} in {d['segno']} a {d['gradi_segno']}°{' (R)' if d['retrogrado'] else ''}"
        for nome, d in pianeti.items()
        if nome not in ("Nodo", "Lilith")
    ])

    base_prompt = (
        "Sei un astrologo professionista. Fornisci un’interpretazione sintetica, empatica e chiara "
        "del seguente tema natale.\n\n"
        f"Città: {meta.get('citta')}\nData e ora: {meta.get('data')} {meta.get('ora')}\n\n"
        f"{asc_info}\nPianeti:\n{pianeti_info}\n\n"
    )

    if domanda_utente:
        base_prompt += f"Domanda specifica: {domanda_utente}\n"

    return [
        {"role": "system", "content": "Sei un astrologo esperto e scrivi in italiano fluente e preciso."},
        {"role": "user", "content": base_prompt}
    ]


def call_ai_model(messages, model=DEFAULT_MODEL, temperature=0.6, max_tokens=700):
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        chat = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        return f"[Errore AI] {e}"


def build_summary_prompt(text: str):
    """Prompt per sintesi breve."""
    return [
        {"role": "system", "content": "Sei un astrologo esperto di comunicazione sintetica."},
        {"role": "user", "content": f"Riassumi in 3 frasi:\n{text}"}
    ]


def interpreta_groq(asc, pianeti_decod, meta, domanda_utente=None):
    """Crea interpretazione e sintesi finale."""
    messages = build_prompt(asc, pianeti_decod, meta, domanda_utente)
    interpretazione = call_ai_model(messages)

    sintesi = ""
    if not interpretazione.startswith("[Errore AI]"):
        sintesi = call_ai_model(build_summary_prompt(interpretazione), temperature=0.5, max_tokens=150)

    return {"interpretazione": interpretazione, "sintesi": sintesi}
