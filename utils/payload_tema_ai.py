# utils/payload_tema_ai.py
from typing import Dict, Any

# Pianeti “essenziali” per il FREE (per risparmiare token)
ESSENTIAL_PLANETS = ["Sole", "Luna", "Mercurio", "Venere", "Marte", "Giove", "Saturno"]


def build_payload_tema_ai(
    tema: Dict[str, Any],
    nome: str = None,
    email: str = None,
    domanda: str = None,
    tier: str = "free",
) -> Dict[str, Any]:
    """
    Costruisce il payload_ai da passare a Claude per il TEMA NATALE.
    Compatibile al 100% con la route /tema_ai e con ai_claude.py.
    """

    if not tema:
        raise ValueError("Tema natale non valido (vuoto o None).")

    # Pianeti decodificati (preferiti) o pianeti base
    pianeti = tema.get("pianeti_decod") or tema.get("pianeti") or {}

    # Case astrologiche
    case = tema.get("case") or tema.get("asc_mc_case") or {}

    payload = {
        "meta": {
            "scope": "tema_ai",
            "tier": tier,
            "version": "1.0",
            "nome": nome,
            "email": email,
            "domanda": domanda,
        },
        "pianeti": {},
        "case": case,
    }

    # Normalizzazione pianeti
    for pianeta, info in pianeti.items():
        if not isinstance(info, dict):
            continue

        payload["pianeti"][pianeta] = {
            "segno": info.get("segno"),
            "gradi_eclittici": info.get("gradi_eclittici") or info.get("g_long") or info.get("long"),
            "retrogrado": info.get("retrogrado", False),
        }

    return payload