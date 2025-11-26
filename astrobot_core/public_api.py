# public_api.py — Facciata ufficiale di astrobot_core

from datetime import date
from typing import Any, Dict

from .calcoli import costruisci_tema_natale
from .sinastria import calcola_sinastria  # se hai già una funzione del genere
from .oroscopo_sampling import Periodo, Tier
from .oroscopo_pipeline import run_oroscopo_multi_snapshot
from .oroscopo_payload_ai import build_oroscopo_payload_ai


# ==========================
#  1) Tema natale
# ==========================

def build_tema_natale(
    citta: str,
    data_nascita: str,   # "YYYY-MM-DD"
    ora_nascita: str,    # "HH:MM"
    sistema_case: str = "equal",
) -> Dict[str, Any]:
    """
    Facciata unica per costruire il tema natale completo.
    """
    return costruisci_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        sistema_case=sistema_case,
    )


# ==========================
#  2) Sinastria
# ==========================

def build_sinastria(
    personaA: Dict[str, str],
    personaB: Dict[str, str],
) -> Dict[str, Any]:
    """
    Facciata unica per sinastria.
    Si appoggia alla funzione già presente in sinastria.py.
    """
    # Adatta a come è definita nel tuo sinastria.py
    return calcola_sinastria(
        cittaA=personaA["citta"],
        dataA=personaA["data"],
        oraA=personaA["ora"],
        cittaB=personaB["citta"],
        dataB=personaB["data"],
        oraB=personaB["ora"],
    )


# ==========================
#  3) Oroscopo_struct (multi-periodo)
# ==========================

def build_oroscopo_struct(
    periodo: str,          # "giornaliero" | "settimanale" | "mensile" | "annuale"
    tier: str,             # "free" | "premium"
    citta: str,
    data_nascita: str,
    ora_nascita: str,
    ref_date: date,
) -> Dict[str, Any]:
    """
    Facciata unica per costruire un oroscopo_struct compatibile
    con oroscopo_payload_ai + KB.
    """

    periodo_it: Periodo = periodo  # Literal in oroscopo_sampling.py
    tier_val: Tier = tier

    # 1) Tema natale base (per tema in oroscopo_struct)
    tema = costruisci_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        sistema_case="equal",
    )

    # 2) Pipeline transiti multi-snapshot
    pipe = run_oroscopo_multi_snapshot(
        periodo=periodo_it,
        tier=tier_val,
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        raw_date=ref_date,
        include_node=True,
        include_lilith=True,
    )

    # 3) Costruzione blocco periodi (1 periodo alla volta)
    periodi: Dict[str, Any] = {}

    if periodo_it == "mensile":
        periodi["mensile"] = {
            "label": "Oroscopo del mese",
            "tier": tier,
            "date_range": {
                "start": ref_date.replace(day=1).isoformat(),
                "end": ref_date.isoformat(),
            },
            "intensita_mensile": pipe.get("intensita_mensile", {}),
            "sottoperiodi": pipe.get("mensile_sottoperiodi", []),
            "pianeti_prevalenti": pipe.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipe.get("aspetti_rilevanti", []),
            "metriche_grafico": pipe.get("metriche_grafico", {}),
        }
    elif periodo_it == "settimanale":
        periodi["settimanale"] = {
            "label": "Oroscopo della settimana",
            "tier": tier,
            "date_range": {
                "start": ref_date.isoformat(),
                "end": ref_date.isoformat(),
            },
            "intensita_settimanale": pipe.get("intensita_mensile", {}),  # se hai una chiave dedicata, usala qui
            "sottoperiodi": pipe.get("sottoperiodi", []),
            "pianeti_prevalenti": pipe.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipe.get("aspetti_rilevanti", []),
            "metriche_grafico": pipe.get("metriche_grafico", {}),
        }
    elif periodo_it == "annuale":
        periodi["annuale"] = {
            "label": "Oroscopo annuale",
            "tier": tier,
            "date_range": {
                "start": f"{ref_date.year}-01-01",
                "end": f"{ref_date.year}-12-31",
            },
            "intensita_annuale": pipe.get("intensita_mensile", {}),
            "sottoperiodi": pipe.get("sottoperiodi", []),
            "pianeti_prevalenti": pipe.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipe.get("aspetti_rilevanti", []),
            "metriche_grafico": pipe.get("metriche_grafico", {}),
        }
    else:  # giornaliero
        periodi["giornaliero"] = {
            "label": "Oroscopo di oggi",
            "tier": tier,
            "date_range": {
                "start": ref_date.isoformat(),
                "end": ref_date.isoformat(),
            },
            "intensita_giornaliera": pipe.get("intensita_mensile", {}),
            "sottoperiodi": pipe.get("sottoperiodi", []),
            "pianeti_prevalenti": pipe.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": pipe.get("aspetti_rilevanti", []),
            "metriche_grafico": pipe.get("metriche_grafico", {}),
        }

    # 4) oroscopo_struct minimale ma compatibile con oroscopo_payload_ai + KB
    oroscopo_struct: Dict[str, Any] = {
        "meta": {
            "nome": None,
            "citta": citta,
            "data_nascita": data_nascita,
            "ora_nascita": ora_nascita,
            "tier": tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema,
        "periodi": periodi,
        # Campo "transiti" opzionale: se in futuro vuoi popolarlo a partire da
        # pipe["aspetti_rilevanti"], puoi aggiungere una lista compatibile qui.
        "transiti": [],
    }

    return oroscopo_struct


# ==========================
#  4) Payload AI + KB
# ==========================

def build_oroscopo_payload_for_ai(
    oroscopo_struct: Dict[str, Any],
    periodo: str,      # "giornaliero" | "settimanale" | ...
    lang: str = "it",
) -> Dict[str, Any]:
    """
    Wrapper per costruire il payload AI per un singolo periodo.
    Mappa periodo IT → period_code EN ("daily"/"weekly"/...).
    """
    p = periodo.lower()
    if p.startswith("giorn"):
        period_code = "daily"
    elif p.startswith("settim"):
        period_code = "weekly"
    elif p.startswith("mens"):
        period_code = "monthly"
    elif p.startswith("ann"):
        period_code = "yearly"
    else:
        period_code = "monthly"

    return build_oroscopo_payload_ai(
        oroscopo_struct=oroscopo_struct,
        lang=lang,
        period_code=period_code,
    )
