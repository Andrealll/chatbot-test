"""
oroscopo_payload_ai.py

Costruisce il payload AI per l'oroscopo, integrando:

- meta (dati utente / contesto)
- periodi (giornaliero, settimanale, ... con intensità e driver)
- kb_hooks (ganci verso la Knowledge Base)
- kb (contenuto markdown estratto da Supabase, pronto per essere usato nel prompt AI)

L'oggetto è MULTILINGUA:
- parametro `lang` (es. "it", "en", ...) propagato in meta e in kb.

Gestione volume KB su 2 livelli:

1) NUMERO DI VOCI (entry KB):
   - dipende da tier (free/premium) e periodo principale (daily/weekly/monthly/yearly)
   - usiamo max_entries_per_section + max_total_entries verso fetch_kb_from_hooks

2) VOLUME DI TESTO (caratteri markdown):
   - limite standard per tier:
       free    → max_kb_chars_free
       premium → max_kb_chars_premium
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .fetch_kb_from_hooks import fetch_kb_from_hooks


# =========================================================
#  Policy limiti KB: tier + periodo
# =========================================================

# Mappiamo i nomi italiani dei periodi nel codice "standard"
PERIOD_KEY_TO_CODE: Dict[str, str] = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}

# Limiti per numero di voci KB, per tier e periodo.
# Qui puoi tarare i numeri come preferisci.
KB_LIMITS_POLICY: Dict[str, Dict[str, Dict[str, Any]]] = {
    "free": {
        "daily": {
            "max_total_entries": 10,
            "per_section": {
                "case": 2,
                "pianeti": 3,
                "segni": 3,
                "pianeti_case": 2,
                "transiti_pianeti": 2,
            },
        },
        "weekly": {
            "max_total_entries": 14,
            "per_section": {
                "case": 3,
                "pianeti": 4,
                "segni": 4,
                "pianeti_case": 3,
                "transiti_pianeti": 3,
            },
        },
        "monthly": {
            "max_total_entries": 18,
            "per_section": {
                "case": 4,
                "pianeti": 5,
                "segni": 5,
                "pianeti_case": 4,
                "transiti_pianeti": 4,
            },
        },
        "yearly": {
            "max_total_entries": 22,
            "per_section": {
                "case": 5,
                "pianeti": 6,
                "segni": 6,
                "pianeti_case": 5,
                "transiti_pianeti": 5,
            },
        },
    },
    "premium": {
        "daily": {
            "max_total_entries": 20,
            "per_section": {
                "case": 4,
                "pianeti": 5,
                "segni": 5,
                "pianeti_case": 4,
                "transiti_pianeti": 4,
            },
        },
        "weekly": {
            "max_total_entries": 24,
            "per_section": {
                "case": 5,
                "pianeti": 6,
                "segni": 6,
                "pianeti_case": 5,
                "transiti_pianeti": 5,
            },
        },
        "monthly": {
            "max_total_entries": 30,
            "per_section": {
                "case": 6,
                "pianeti": 7,
                "segni": 7,
                "pianeti_case": 6,
                "transiti_pianeti": 6,
            },
        },
        "yearly": {
            "max_total_entries": 36,
            "per_section": {
                "case": 7,
                "pianeti": 8,
                "segni": 8,
                "pianeti_case": 7,
                "transiti_pianeti": 7,
            },
        },
    },
}

# Limite di CARATTERI per tier (secondo livello)
KB_CHAR_LIMIT_BY_TIER: Dict[str, int] = {
    "free": 8000,      # ≈ 2000 token circa
    "premium": 16000,  # ≈ 4000 token circa
}

DEFAULT_TIER = "free"
DEFAULT_PERIOD_CODE = "daily"


# =========================================================
#  Builders di alto livello
# =========================================================

def build_oroscopo_payload_ai(
    oroscopo_struct: Dict[str, Any],
    lang: str = "it",
) -> Dict[str, Any]:
    """
    Costruisce il payload AI completo per l'oroscopo.

    Parametri
    ---------
    oroscopo_struct : dict
        Deve contenere almeno:
        {
          "meta": {...},
          "periodi": {...},
          "tema": {...},        # opzionale ma utile per i kb_hooks
          "transiti": [...],    # opzionale ma utile per i kb_hooks
          "kb_hooks": {...}     # opzionale: se presente, ha priorità
        }

    lang : str
        Codice lingua ("it", "en", ...).

    Ritorna
    -------
    dict
        Payload pronto da dare al modello AI.
    """
    raw_meta = oroscopo_struct.get("meta") or {}

    tier = _normalize_tier(raw_meta.get("tier"))
    period_code = _infer_primary_period_code(oroscopo_struct)

    # Limiti KB per questo contesto (tier + periodo)
    kb_limits = _get_kb_limits_for_context(tier, period_code)
    max_entries_per_section = kb_limits["max_entries_per_section"]
    max_total_entries = kb_limits["max_total_entries"]
    max_kb_chars = kb_limits["max_kb_chars"]

    # 1) Meta arricchita con lang + tier normalizzato
    meta = _build_meta(raw_meta, lang=lang, tier=tier)

    # 2) Periodi: passo diretto quello che hai
    periodi = oroscopo_struct.get("periodi") or {}

    # 3) kb_hooks: se esistono già, li uso; altrimenti li derivo
    kb_hooks = _build_kb_hooks(oroscopo_struct)

    # 4) Fetch KB da Supabase con limiti numerici (livello 1)
    if kb_hooks:
        kb_result = fetch_kb_from_hooks(
            kb_hooks,
            max_entries_per_section=max_entries_per_section,
            max_total_entries=max_total_entries,
            filter_chapters=True,  # tieni attivo il filtro "solo alcuni capitoli"
        )
    else:
        kb_result = {"by_section": {}, "combined_markdown": ""}

    combined_md_full = kb_result.get("combined_markdown", "") or ""

    # 5) Limite finale di caratteri in base al tier (livello 2)
    combined_md_clipped = _clip_markdown(combined_md_full, max_kb_chars)

    payload_ai: Dict[str, Any] = {
        "meta": meta,
        "periodi": periodi,
        "kb_hooks": kb_hooks,
        "kb": {
            "by_section": kb_result.get("by_section", {}),
            "combined_markdown": combined_md_clipped,
            "lang": lang,
        },
    }

    return payload_ai


# =========================================================
#  Meta + policy helper
# =========================================================

def _normalize_tier(raw_tier: Any) -> str:
    """
    Normalizza il tier in {free, premium}.
    Tutto ciò che non è "premium" diventa "free" (compresi None, "annual", ecc.).
    """
    if not raw_tier:
        return DEFAULT_TIER
    s = str(raw_tier).strip().lower()
    if s in {"premium", "paid", "pro"}:
        return "premium"
    return "free"


def _infer_primary_period_code(oroscopo_struct: Dict[str, Any]) -> str:
    """
    Cerca di capire qual è il "periodo principale" (daily/weekly/monthly/yearly)
    guardando i periodi presenti.

    Strategia:
    - se c'è un solo periodo in `periodi`, mappo quello
    - se ce ne sono più, assegno una priorità:
        giornaliero > settimanale > mensile > annuale
    - se non trovo nulla, uso DEFAULT_PERIOD_CODE.
    """
    periodi = oroscopo_struct.get("periodi") or {}
    if not isinstance(periodi, dict) or not periodi:
        return DEFAULT_PERIOD_CODE

    keys = list(periodi.keys())

    # se c'è un solo periodo, mappo direttamente
    if len(keys) == 1:
        k = keys[0]
        return PERIOD_KEY_TO_CODE.get(k, DEFAULT_PERIOD_CODE)

    # priorità se ci sono più periodi
    priority = ["giornaliero", "settimanale", "mensile", "annuale"]
    for p in priority:
        if p in periodi:
            return PERIOD_KEY_TO_CODE.get(p, DEFAULT_PERIOD_CODE)

    return DEFAULT_PERIOD_CODE


def _get_kb_limits_for_context(tier: str, period_code: str) -> Dict[str, Any]:
    """
    Restituisce i limiti KB per (tier, periodo) sotto forma di:

    {
      "max_entries_per_section": {...},
      "max_total_entries": int,
      "max_kb_chars": int,
    }
    """
    tier_cfg = KB_LIMITS_POLICY.get(tier) or KB_LIMITS_POLICY[DEFAULT_TIER]
    period_cfg = tier_cfg.get(period_code) or tier_cfg.get(DEFAULT_PERIOD_CODE)

    per_section = period_cfg.get("per_section", {})
    max_total_entries = period_cfg.get("max_total_entries")

    max_kb_chars = KB_CHAR_LIMIT_BY_TIER.get(tier, KB_CHAR_LIMIT_BY_TIER[DEFAULT_TIER])

    return {
        "max_entries_per_section": per_section,
        "max_total_entries": max_total_entries,
        "max_kb_chars": max_kb_chars,
    }


def _build_meta(raw_meta: Dict[str, Any], lang: str, tier: str) -> Dict[str, Any]:
    """
    Normalizza / arricchisce la sezione meta.

    - Mantiene tutti i campi originali
    - Forza:
      - meta["lang"] = lang
      - meta["tier"] = tier normalizzato (free/premium)
    """
    meta = dict(raw_meta) if raw_meta else {}
    meta["lang"] = lang
    meta["tier"] = tier
    return meta


# =========================================================
#  Gestione clipping KB (livello 2)
# =========================================================

def _clip_markdown(text: str, max_chars: Optional[int]) -> str:
    """
    Se max_chars è impostato e il testo è più lungo, lo tronca
    e aggiunge una nota esplicita di taglio.

    Questo serve a non riempire tutto il contesto del modello
    con la sola Knowledge Base.
    """
    if not text:
        return ""

    if not max_chars or max_chars <= 0:
        return text

    if len(text) <= max_chars:
        return text

    clipped = text[:max_chars]
    note = (
        "\n\n---\n\n"
        "[KB TRONCATA PER LIMITI DI CONTESTO: la Knowledge Base completa è disponibile "
        "ma questa è una selezione automatica delle parti più rilevanti in base ai kb_hooks.]\n"
    )
    return clipped + note


# =========================================================
#  Costruzione kb_hooks (come prima)
# =========================================================

def _build_kb_hooks(oroscopo_struct: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recupera o costruisce i kb_hooks a partire dalla struttura tecnica.

    PRIORITÀ:
    1) Se oroscopo_struct["kb_hooks"] esiste ed è un dict, lo uso così com'è.
    2) Altrimenti, derivo i kb_hooks da:
       - oroscopo_struct["tema"] (pianeti, segni, case)
       - oroscopo_struct["transiti"] (transit_planet, natal_planet, aspect, natal_house)
       - oroscopo_struct["periodi"][*]["ambiti"][*]["drivers"] (se contengono info astrologiche)
    """
    existing = oroscopo_struct.get("kb_hooks")
    if isinstance(existing, dict):
        return existing

    case: Set[int] = set()
    pianeti: Set[str] = set()
    segni: Set[str] = set()
    pianeti_case: Set[Tuple[str, int]] = set()
    transiti_pianeti: Set[Tuple[str, str, str]] = set()

    # --- TEMA ---
    tema = oroscopo_struct.get("tema") or {}

    pianeti_decod = tema.get("pianeti_decod") or {}
    for nome_pianeta, dati in pianeti_decod.items():
        if not isinstance(dati, dict):
            continue

        nome_lower = str(nome_pianeta).lower()
        if nome_lower in {"data", "asc", "ascendente", "mc", "medium_coeli", "discendente", "cuspidi"}:
            continue

        pianeti.add(str(nome_pianeta))

        segno = dati.get("segno") or dati.get("sign")
        if segno:
            segni.add(str(segno))

    case_decod = (
        tema.get("case_decod")
        or tema.get("case")
        or tema.get("case_natal")
        or {}
    )
    if isinstance(case_decod, dict):
        for k, dati_casa in case_decod.items():
            try:
                n_casa = int(k)
            except (TypeError, ValueError):
                continue
            case.add(n_casa)

            if isinstance(dati_casa, dict):
                segno_casa = dati_casa.get("segno") or dati_casa.get("sign")
                if segno_casa:
                    segni.add(str(segno_casa))

    # --- TRANSITI ---
    transits_list: List[Dict[str, Any]] = _extract_transits(oroscopo_struct)

    for tr in transits_list:
        if not isinstance(tr, dict):
            continue

        tplanet = (
            tr.get("transit_planet")
            or tr.get("pianeta_transito")
            or tr.get("pianeta_transiting")
        )
        nplanet = (
            tr.get("natal_planet")
            or tr.get("pianeta_natale")
            or tr.get("pianeta_nativo")
        )
        aspect = tr.get("aspect") or tr.get("aspetto")
        house = tr.get("natal_house") or tr.get("casa_nativa") or tr.get("casa")

        if tplanet:
            pianeti.add(str(tplanet))
        if nplanet:
            pianeti.add(str(nplanet))

        if house is not None:
            try:
                n_casa = int(house)
            except (TypeError, ValueError):
                n_casa = None
            if n_casa is not None:
                case.add(n_casa)
                if tplanet:
                    pianeti_case.add((str(tplanet), n_casa))

        if tplanet and nplanet and aspect:
            transiti_pianeti.add(
                (str(tplanet), str(nplanet), str(aspect))
            )

    # --- DRIVERS NEI PERIODI ---
    periodi = oroscopo_struct.get("periodi") or {}
    for _, periodo_data in periodi.items():
        if not isinstance(periodo_data, dict):
            continue
        ambiti = periodo_data.get("ambiti") or {}
        for _, ambito_data in ambiti.items():
            if not isinstance(ambito_data, dict):
                continue
            drivers = ambito_data.get("drivers") or []
            if not isinstance(drivers, list):
                continue

            for drv in drivers:
                if not isinstance(drv, dict):
                    continue

                tplanet = drv.get("transit_planet")
                nplanet = drv.get("natal_planet")
                aspect = drv.get("aspect")
                house = drv.get("natal_house") or drv.get("casa")
                segno_drv = drv.get("segno") or drv.get("sign")

                if segno_drv:
                    segni.add(str(segno_drv))
                if tplanet:
                    pianeti.add(str(tplanet))
                if nplanet:
                    pianeti.add(str(nplanet))
                if house is not None:
                    try:
                        n_casa = int(house)
                    except (TypeError, ValueError):
                        n_casa = None
                    if n_casa is not None:
                        case.add(n_casa)
                        if tplanet:
                            pianeti_case.add((str(tplanet), n_casa))
                if tplanet and nplanet and aspect:
                    transiti_pianeti.add(
                        (str(tplanet), str(nplanet), str(aspect))
                    )

    hooks: Dict[str, Any] = {}

    if case:
        hooks["case"] = sorted(case)
    if pianeti:
        hooks["pianeti"] = sorted(pianeti)
    if segni:
        hooks["segni"] = sorted(segni)
    if pianeti_case:
        hooks["pianeti_case"] = [
            {"transit_planet": tp, "natal_house": h}
            for (tp, h) in sorted(pianeti_case, key=lambda x: (x[0], x[1]))
        ]
    if transiti_pianeti:
        hooks["transiti_pianeti"] = [
            {
                "transit_planet": tp,
                "natal_planet": np,
                "aspect": asp,
            }
            for (tp, np, asp) in sorted(
                transiti_pianeti, key=lambda x: (x[0], x[1], x[2])
            )
        ]

    return hooks


def _extract_transits(oroscopo_struct: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Estrae una lista di transiti da oroscopo_struct in modo robusto.
    """
    raw = (
        oroscopo_struct.get("transiti")
        or oroscopo_struct.get("transits")
        or []
    )

    if isinstance(raw, list):
        return raw

    transits_list: List[Dict[str, Any]] = []

    if isinstance(raw, dict):
        if "lista" in raw and isinstance(raw["lista"], list):
            transits_list.extend(raw["lista"])

        for key in ("entries", "items"):
            if key in raw and isinstance(raw[key], list):
                transits_list.extend(raw[key])

        per_periodo = raw.get("per_periodo")
        if isinstance(per_periodo, dict):
            for _, lst in per_periodo.items():
                if isinstance(lst, list):
                    transits_list.extend(lst)

    return transits_list


# =========================================================
#  Demo / test manuale
# =========================================================

def _demo_oroscopo_struct() -> Dict[str, Any]:
    """
    Demo minimale di oroscopo_struct, per testare il modulo in autonomia.
    """
    return {
        "meta": {
            "nome": "Mario",
            "citta_nascita": "Napoli",
            "data_nascita": "1986-07-19",
            "ora_nascita": "08:50",
            "tier": "premium",
            "scope": "oroscopo_multi_snapshot",
        },
        "tema": {
            "pianeti_decod": {
                "Sole": {"segno": "Cancro"},
                "Luna": {"segno": "Sagittario"},
                "Data": {"segno": "Ariete"},
            },
            "case_decod": {
                "1": {"segno": "Leone"},
                "7": {"segno": "Acquario"},
            },
        },
        "transiti": [
            {
                "transit_planet": "Saturno",
                "natal_planet": "Sole",
                "aspect": "quadratura",
                "natal_house": 7,
            },
            {
                "transit_planet": "Venere",
                "natal_house": 5,
            },
        ],
        "periodi": {
            "giornaliero": {
                "label": "Oroscopo di oggi",
                "tier": "premium",
                "date_range": {"start": None, "end": None},
                "ambiti": {
                    "energy": {
                        "score": -0.9,
                        "drivers": [
                            {
                                "transit_planet": "Luna",
                                "natal_planet": "Sole",
                                "aspect": "opposizione",
                                "natal_house": 1,
                                "segno": "Cancro",
                            }
                        ],
                    }
                },
            }
        },
    }


if __name__ == "__main__":
    import json

    demo = _demo_oroscopo_struct()
    payload_ai = build_oroscopo_payload_ai(demo, lang="it")

    print("\n========== META ==========\n")
    print(json.dumps(payload_ai["meta"], ensure_ascii=False, indent=2))

    print("\n========== PERIODI ==========\n")
    print(json.dumps(payload_ai["periodi"], ensure_ascii=False, indent=2))

    print("\n========== KB_HOOKS (derivati) ==========\n")
    print(json.dumps(payload_ai["kb_hooks"], ensure_ascii=False, indent=2))

    kb_md = payload_ai["kb"]["combined_markdown"]
    print("\n========== KB (combined_markdown) ==========\n")
    print(kb_md)
    print(f"\n[LENGTH] KB chars (clipped): {len(kb_md)}")
