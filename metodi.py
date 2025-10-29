import os
from typing import Any, Dict, Optional
from groq import Groq

# ======================================================
# CONFIGURAZIONE BASE
# ======================================================
DEFAULT_MODEL = "llama-3.3-70b-versatile"


# ======================================================
# COSTRUZIONE PROMPT
# ======================================================
def build_prompt(asc: Dict[str, Any], pianeti: Dict[str, Any], meta: Dict[str, Any], domanda_utente: Optional[str] = None):
    """
    Crea un prompt chiaro e completo per l'interpretazione astrologica.
    Invia a Groq i dati più significativi del tema natale in forma testuale leggibile.
    """

    # --- Ascendente e Medio Cielo ---
    asc_info = (
        f"Ascendente in {asc.get('ASC_segno', 'N/A')} "
        f"a {asc.get('ASC_gradi_segno', 0)}°.\n"
        f"Medio Cielo in {asc.get('MC_segno', 'N/A')} "
        f"a {asc.get('MC_gradi_segno', 0)}°.\n"
    )

    # --- Pianeti principali nei segni ---
    pianeti_info = []
    for nome, valore in pianeti.items():
        if isinstance(valore, dict) and "segno" in valore:
            pianeti_info.append(f"- {nome} in {valore['segno']} a {valore['gradi_segno']}°")
        else:
            # fallback numerico se non è presente la struttura estesa
            pianeti_info.append(f"- {nome}: {valore:.2f}°")

    pianeti_text = "\n".join(pianeti_info)

    # --- Metadati per contesto ---
    meta_info = (
        f"Città: {meta.get('citta', 'sconosciuta')}\n"
        f"Data e ora di nascita: {meta.get('data', 'N/A')} {meta.get('ora', 'N/A')}\n"
        f"Sistema delle case: {meta.get('sistema_case', 'equal')}\n"
        f"Fuso orario: {meta.get('fuso', 0)}\n"
    )

    # --- Costruzione prompt finale ---
    base_prompt = (
        "Sei un esperto di astrologia moderna e psicologica. "
        "Offri un'interpretazione sintetica, empatica e professionale del tema natale seguente, "
        "spiegando il significato dell'Ascendente, del Sole, della Luna e dei principali pianeti personali.\n\n"
        f"{meta_info}\n"
        f"{asc_info}\n"
        f"Pianeti principali:\n{pianeti_text}\n\n"
    )

    if domanda_utente:
        base_prompt += f"Domanda specifica dell'utente: {domanda_utente}\n"

    return [
        {"role": "system", "content": "Sei un astrologo esperto e professionale, scrivi in italiano chiaro e accurato."},
        {"role": "user", "content": base_prompt}
    ]


# ======================================================
# CHIAMATA AL MODELLO AI (Groq)
# ======================================================
def call_ai_model(messages, model=DEFAULT_MODEL, temperature=0.6, max_tokens=700, provider="groq"):
    """
    Effettua la chiamata al modello Groq e restituisce la risposta testuale.
    """
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
        print(f"[ERRORE AI] {e}")
        return f"[Errore AI] {e}"


# ======================================================
# COSTRUZIONE STRUTTURA PIANETI
# ======================================================
def pianeti_struct(pianeti_raw: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """
    Converte i gradi eclittici in segni zodiacali e gradi all'interno del segno.
    Esempio: 116.2° → Cancro 26.2°
    """
    segni = [
        "Ariete", "Toro", "Gemelli", "Cancro",
        "Leone", "Vergine", "Bilancia", "Scorpione",
        "Sagittario", "Capricorno", "Acquario", "Pesci"
    ]

    pianeti_conv = {}
    for nome, valore in pianeti_raw.items():
        segno_idx = int(valore // 30)
        gradi_segno = round(valore % 30, 2)
        segno_nome = segni[segno_idx]
        pianeti_conv[nome] = {
            "gradi_eclittici": round(valore, 2),
            "segno": segno_nome,
            "gradi_segno": gradi_segno
        }

    return pianeti_conv


# ======================================================
# FUNZIONE PRINCIPALE DI INTERPRETAZIONE
# ======================================================
def interpreta_groq(
    asc: Dict[str, Any],
    pianeti_raw: Dict[str, float],
    meta: Dict[str, Any],
    domanda_utente: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    provider: str = "groq",
    temperature: float = 0.6,
    max_tokens: int = 800
) -> str:
    """
    Genera l'interpretazione del tema natale combinando dati astrologici e AI.
    """
    try:
        # Prepara struttura leggibile dei pianeti
        pianeti = pianeti_struct(pianeti_raw)
        messages = build_prompt(asc, pianeti, meta, domanda_utente)
        risposta = call_ai_model(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider
        )
        return risposta
    except Exception as e:
        print(f"[Errore interprete] {e}")
        return f"[Errore AI] {e}"
