# utils/payload_tema_ai.py
from typing import Dict, Any

# Pianeti “essenziali” per il FREE (per risparmiare token)
ESSENTIAL_PLANETS = ["Sole", "Luna", "Mercurio", "Venere", "Marte", "Giove", "Saturno"]


def build_payload_tema_ai(tema: Dict[str, Any], tier: str = "free") -> Dict[str, Any]:
    """
    Costruisce un payload_ai COMPATTO per il tema natale.
    - Riduce i campi inutili.
    - Riduce il numero di pianeti per il tier FREE.
    """

    pianeti_decod = tema.get("pianeti_decod", {})
    asc_mc_case = tema.get("asc_mc_case", {})

    if tier == "free":
        # FREE → solo pianeti principali
        pianeti_filtrati = {
            nome: info
            for nome, info in pianeti_decod.items()
            if nome in ESSENTIAL_PLANETS
        }
    else:
        # PREMIUM → tutti i pianeti disponibili
        pianeti_filtrati = pianeti_decod

    pianeti_compatti = {}
    for nome, info in pianeti_filtrati.items():
        pianeti_compatti[nome] = {
            "segno": info.get("segno"),
            "gradi_eclittici": round(info.get("gradi_eclittici", 0.0), 2),
            "retrogrado": info.get("retrogrado", False),
        }

    payload = {
        "meta": {
            "scope": "tema_ai",
            "tier": tier,
            "version": "1.0",
        },
        "pianeti": pianeti_compatti,
        # Case: puoi mantenerle così come sono, di solito sono poche → costo minimo
        "case": asc_mc_case,
    }

    return payload
