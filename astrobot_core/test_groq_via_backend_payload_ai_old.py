"""
Test end-to-end della pipeline AI AstroBot.

- calcola tema natale
- calcola transiti multi-snapshot
- costruisce oroscopo_struct
- genera payload_ai
- chiama backend /oroscopo_ai
- confronta FREE vs PREMIUM in tutti i periodi
"""

import time
import re
import json
import requests
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai


# ============================================
# CONFIG
# ============================================

BASE_URL = "http://127.0.0.1:8000"
OROSCOPO_AI_ENDPOINT = f"{BASE_URL}/oroscopo_ai"
TODAY = date.today()


# ============================================
# DATACLASS PERSONA
# ============================================

@dataclass
class PersonaTest:
    nome: str
    citta: str
    data_nascita: str
    ora_nascita: str
    tier: str
    periodo: str


# ============================================
# LISTA TEST CASES (SOLO MARIO)
# ============================================

PERSONE_TEST: List[PersonaTest] = [
    # Giornaliero
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "free", "giornaliero"),
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "premium", "giornaliero"),

    # Settimanale
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "free", "settimanale"),
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "premium", "settimanale"),

    # Mensile
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "free", "mensile"),
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "premium", "mensile"),

    # Annuale
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "free", "annuale"),
    PersonaTest("Mario", "Napoli", "1986-07-19", "08:50", "premium", "annuale"),
]


# ============================================
# HELPERS
# ============================================

def _map_periodo_for_core(p: str) -> str:
    p = (p or "").lower().strip()
    if p.startswith("giorn"): return "daily"
    if p.startswith("settim"): return "weekly"
    if p.startswith("mens"): return "monthly"
    if p.startswith("ann"): return "yearly"
    return "daily"


def _month_date_range(anchor_date: date) -> Dict[str, str]:
    from calendar import monthrange
    y = anchor_date.year
    m = anchor_date.month
    last = monthrange(y, m)[1]
    return {"start": f"{y}-{m:02d}-01", "end": f"{y}-{m:02d}-{last:02d}"}


def build_oroscopo_struct_for_case(persona: PersonaTest) -> Dict[str, Any]:
    """Costruisce oroscopo_struct corretto per la pipeline AI."""
    core_period = _map_periodo_for_core(persona.periodo)

    tema = costruisci_tema_natale(
        citta=persona.citta,
        data_nascita=persona.data_nascita,
        ora_nascita=persona.ora_nascita,
        sistema_case="equal",
    )

    pipeline_res = run_oroscopo_multi_snapshot(
        periodo=core_period,
        tier=persona.tier,
        citta=persona.citta,
        data_nascita=persona.data_nascita,
        ora_nascita=persona.ora_nascita,
        raw_date=TODAY,
        include_node=True,
        include_lilith=True,
    )

    periodi = {}

    if core_period == "monthly":
        periodi["monthly"] = {
            "label": "Oroscopo del mese",
            "date_range": _month_date_range(TODAY),
            "intensita_mensile": pipeline_res.get("intensita_mensile", {}),
            "sottoperiodi": pipeline_res.get("mensile_sottoperiodi", []),
            "pianeti_prevalenti": pipeline_res.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipeline_res.get("aspetti_rilevanti", []),
            "metriche_grafico": pipeline_res.get("metriche_grafico", {}),
        }
    else:
        periodi[core_period] = {
            "label": f"Oroscopo {core_period}",
            "date_range": {"start": TODAY.isoformat(), "end": TODAY.isoformat()},
            "intensita": pipeline_res.get("intensita", {}),
            "sottoperiodi": pipeline_res.get("sottoperiodi", []),
            "pianeti_prevalenti": pipeline_res.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipeline_res.get("aspetti_rilevanti", []),
            "metriche_grafico": pipeline_res.get("metriche_grafico", {}),
        }

    return {
        "meta": {
            "nome": persona.nome,
            "citta": persona.citta,
            "data_nascita": persona.data_nascita,
            "ora_nascita": persona.ora_nascita,
            "tier": persona.tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema,
        "periodi": periodi,
    }


def call_backend(persona: PersonaTest, payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    body = {
        "scope": "oroscopo_ai",
        "tier": persona.tier,
        "periodo": persona.periodo,
        "payload_ai": payload_ai,
    }
    print(f"\n=== POST {persona.periodo} / {persona.tier} ===")
    r = requests.post(OROSCOPO_AI_ENDPOINT, json=body, timeout=90)
    print("HTTP:", r.status_code)
    if r.status_code != 200:
        print("Errore:", r.text[:800])
        return {}
    return r.json()


# ============================================
# MAIN TEST
# ============================================

def main():
    print("=== Test AstroBot ===")
    print("Backend:", OROSCOPO_AI_ENDPOINT)

    for idx, persona in enumerate(PERSONE_TEST):
        print("\n========================================")
        print(f"{persona.nome} — {persona.periodo} — {persona.tier}")
        print("========================================")

        oro = build_oroscopo_struct_for_case(persona)

        core_period = _map_periodo_for_core(persona.periodo)
        payload_ai = build_oroscopo_payload_ai(oro, lang="it", period_code=core_period)

        resp = call_backend(persona, payload_ai)

        print("\nInterpretazione (raw):")
        print(str(resp.get("interpretazione_ai"))[:700])

        # Delay tra le chiamate
        if idx < len(PERSONE_TEST) - 1:
            print("\n[DEBUG] Attendo 10 secondi...\n")
            time.sleep(10)

    print("\n=== FINE TEST ===")


if __name__ == "__main__":
    main()
