# metodi.py
from typing import Dict, Any, Optional, List, Tuple
import math

# =========================
# Utilità di formattazione
# =========================

SEGNI = [
    "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
    "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"
]

def normalize_longitude(deg: float) -> float:
    """
    Porta la longitudine in gradi nell'intervallo [0, 360).
    Gestisce negativi o >360.
    """
    if deg is None:
        return None
    x = deg % 360.0
    if x < 0:
        x += 360.0
    return x

def deg_to_sign_dms(longitude: float) -> Tuple[str, int, int]:
    """
    Converte una longitudine eclittica (0..360) in:
    - segno zodiacale (nome)
    - gradi nel segno (0..29)
    - primi nel segno (0..59)
    """
    L = normalize_longitude(longitude)
    segno_idx = int(L // 30)
    segno = SEGNI[segno_idx]
    gradi = int(L % 30)
    primi = int(round((L - math.floor(L)) * 60))
    if primi == 60:  # normalizza eventuale round-up
        primi = 0
        gradi = (gradi + 1) % 30
        if gradi == 0:
            segno_idx = (segno_idx + 1) % 12
            segno = SEGNI[segno_idx]
    return segno, gradi, primi

def pianeti_struct(pianeti_raw: Dict[str, float]) -> List[Dict[str, Any]]:
    """
    Converte il dict {nome: longitudine_float} in una lista di oggetti
    con campi disambiguati:
      - name: "Sole"
      - longitude_deg: 123.456 (0..360)
      - sign: "Leone"
      - deg_in_sign: 3
      - min_in_sign: 27
      - readable: "Sole in Leone 3°27'"
    """
    results = []
    for name, val in pianeti_raw.items():
        if val is None:
            continue
        L = normalize_longitude(float(val))
        sign, d, m = deg_to_sign_dms(L)
        readable = f"{name} in {sign} {d}°{m:02d}'"
        results.append({
            "name": name,
            "longitude_deg": round(L, 6),
            "sign": sign,
            "deg_in_sign": d,
            "min_in_sign": m,
            "readable": readable
        })
    # Ordina per ordine tradizionale o per longitudine (qui per nome)
    results.sort(key=lambda x: x["name"])
    return results

def asc_readable(asc: Dict[str, Any]) -> str:
    """
    Atteso qualcosa tipo {"segno": "Leone", "grado": 12, "min": 34, ...}
    Adatta se il tuo ascendente ha struttura diversa.
    """
    # Fallback generico:
    segno = asc.get("segno") or asc.get("sign") or "N/D"
    grado = asc.get("grado") or asc.get("deg") or asc.get("degree") or 0
    minuti = asc.get("min") or asc.get("minutes") or 0
    return f"Ascendente {segno} {int(grado)}°{int(minuti):02d}'"

# =========================
# Prompting per Groq
# =========================

def build_prompt(asc: Dict[str, Any],
                 planets: List[Dict[str, Any]],
                 meta: Dict[str, Any],
                 domanda_utente: Optional[str]) -> Dict[str, Any]:
    """
    Costruisce messaggi per chat-completions (role-based).
    Usa un system forte per impedire al modello di alterare i dati astronomici.
    """
    asc_str = asc_readable(asc)
    # Impacchetta un JSON dei pianeti molto esplicito
    planets_json_lines = []
    for p in planets:
        planets_json_lines.append(
            f'- {p["name"]}: {p["longitude_deg"]}° ({p["readable"]})'
        )
    planets_block = "\n".join(planets_json_lines)

    meta_lines = [
        f"Data: {meta.get('data', 'N/D')}",
        f"Ora: {meta.get('ora', 'N/D')}",
        f"Città: {meta.get('citta', 'N/D')}",
        f"Sistema case: {meta.get('sistema_case', 'equal')}",
        f"Fuso: {meta.get('fuso', 0.0)}"
    ]
    meta_block = "\n".join(meta_lines)

    system_content = (
        "Sei un astrologo professionista. Ti vengono forniti dati astronomici già calcolati.\n"
        "REGOLE VINCOLANTI:\n"
        "1) NON modificare, inferire o indovinare posizioni. Usa SOLO i dati forniti.\n"
        "2) NON convertire i gradi: considera 'longitude_deg' come longitudine eclittica 0–360 già normalizzata.\n"
        "3) Quando citi una posizione, riporta il NOME del pianeta e la forma leggibile (es. 'Sole in Leone 3°27'').\n"
        "4) Se la domanda chiede posizioni non fornite, rispondi che non sono disponibili.\n"
        "5) Stile: chiaro, sintetico, benevolo, ma tecnico quando serve.\n"
    )

    user_base = (
        f"DATI TEMA:\n"
        f"- {asc_str}\n"
        f"- Pianeti:\n{planets_block}\n\n"
        f"METADATI:\n{meta_block}\n"
    )

    if domanda_utente and str(domanda_utente).strip():
        user_content = (
            user_base
            + "DOMANDA UTENTE:\n"
            + str(domanda_utente).strip()
        )
    else:
        user_content = (
            user_base
            + "RICHIESTA:\n"
            + "Fornisci un'interpretazione sintetica e coerente del tema, "
              "citando i pianeti con il loro NOME e la loro posizione leggibile."
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content}
    ]
    return {"messages": messages}

# =========================
# Chiamata al modello (adatta al tuo client)
# =========================

def call_groq_chat(messages: List[Dict[str, str]],
                   model: str = "mixtral-8x7b",
                   temperature: float = 0.3,
                   max_tokens: int = 800) -> str:
    """
    Sostituisci questo stub con la tua integrazione Groq reale.
    Esempio se usi SDK ufficiale:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    """
    # Placeholder per evitare rotture in fase di test
    # In produzione, implementa la chiamata reale come nel commento sopra.
    return "(Stub) Integra qui la chiamata a Groq e restituisci il contenuto."

# =========================
# API pubblica per main.py
# =========================

def interpreta_groq(asc: Dict[str, Any],
                    pianeti_raw: Dict[str, float],
                    meta: Dict[str, Any],
                    domanda_utente: Optional[str] = None,
                    model: str = "mixtral-8x7b",
                    temperature: float = 0.3,
                    max_tokens: int = 800) -> str:
    """
    - Normalizza i dati planetari
    - Costruisce prompt robusto e disambiguato (nome pianeta + posizione leggibile)
    - Chiama Groq (sostituisci lo stub con la tua integrazione)
    """
    planets = pianeti_struct(pianeti_raw)
    payload = build_prompt(asc=asc, planets=planets, meta=meta, domanda_utente=domanda_utente)
    messages = payload["messages"]

    # CHIAMATA REALE: sostituisci lo stub qui sotto con il tuo client Groq
    text = call_groq_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    return text
