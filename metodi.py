from typing import Dict, Any, Optional, List, Tuple
import math
from ai_utils import call_ai_model

SEGNI = [
    "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
    "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
]


# -------------------------
# Normalizzazione
# -------------------------

def normalize_longitude(deg: float) -> float:
    if deg is None:
        return None
    x = deg % 360.0
    if x < 0:
        x += 360.0
    return x


def deg_to_sign_dms(longitude: float) -> Tuple[str, int, int]:
    L = normalize_longitude(longitude)
    segno_idx = int(L // 30)
    segno = SEGNI[segno_idx]
    gradi = int(L % 30)
    primi = int(round((L - math.floor(L)) * 60))
    if primi == 60:
        primi = 0
        gradi = (gradi + 1) % 30
        if gradi == 0:
            segno_idx = (segno_idx + 1) % 12
            segno = SEGNI[segno_idx]
    return segno, gradi, primi


# -------------------------
# Pianeti + Case
# -------------------------

def pianeti_struct(pianeti_raw: Dict[str, Any], case: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    results = []
    for name, val in pianeti_raw.items():
        if val is None:
            continue
        L = normalize_longitude(float(val))
        sign, d, m = deg_to_sign_dms(L)
        casa = case.get(name) if case else None
        readable = f"{name} in {sign} {d}°{m:02d}'"
        if casa:
            readable += f" in {casa}ª casa"
        results.append({
            "name": name,
            "longitude_deg": round(L, 6),
            "sign": sign,
            "deg_in_sign": d,
            "min_in_sign": m,
            "house": casa,
            "readable": readable
        })
    return sorted(results, key=lambda x: x["name"])


# -------------------------
# Prompt per Groq / GPT
# -------------------------

def build_prompt(asc: Dict[str, Any],
                 planets: List[Dict[str, Any]],
                 meta: Dict[str, Any],
                 domanda_utente: Optional[str]) -> List[Dict[str, str]]:
    asc_str = f"Ascendente: {asc.get('segno', 'N/D')} {asc.get('grado', 0)}°{asc.get('min', 0):02d}'"
    planets_text = "\n".join([f"- {p['name']}: {p['readable']}" for p in planets])

    system = (
        "Sei un astrologo esperto e preciso.\n"
        "Non modificare i dati astronomici, non inventare posizioni.\n"
        "Rispondi in tono empatico, ma accurato."
    )

    base = (
        f"DATI:\n{asc_str}\n\nPIANETI:\n{planets_text}\n\n"
        f"Città: {meta.get('citta')} | Data: {meta.get('data')} | Ora: {meta.get('ora')}\n"
    )

    if domanda_utente:
        user = f"{base}\nDOMANDA: {domanda_utente}"
    else:
        user = f"{base}\nRICHIESTA: Fornisci un'interpretazione sintetica del tema natale."

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]


# -------------------------
# Funzione principale
# -------------------------

from typing import Dict, Any, Optional
from ai_utils import call_ai_model, DEFAULT_MODEL

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
    Genera l'interpretazione astrologica usando Groq e il modello configurato.
    """
    try:
        # Conversione pianeti in struttura leggibile
        planets = pianeti_struct(pianeti_raw)
        # Costruzione del prompt con contesto
        messages = build_prompt(asc, planets, meta, domanda_utente)
        # Chiamata al modello AI
        risposta = call_ai_model(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider
        )
        return risposta
    except Exception as e:
        return f"[Errore AI] {e}"
