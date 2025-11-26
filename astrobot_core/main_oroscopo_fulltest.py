"""
main_oroscopo_fulltest.py

Test end-to-end completo:

- tema natale reale (19/07/1986, 08:50, Napoli)
- oroscopo multi-snapshot per tutti i periodi (giornaliero / settimanale / mensile / annuale)
  tramite oroscopo_pipeline.run_oroscopo_multi_snapshot
  -> transiti_vs_tema_precalc + transiti_pesatura + pesi per periodo
- costruzione di un oroscopo_struct multi-periodo in memoria
- build_oroscopo_payload_ai(...) con aggancio KB su Supabase
- stampa, per ogni (tier, periodo):
    * riga sintetica CSV-like
    * blocco [TRANSITI USATI] con i transiti effettivamente inclusi in kb.transiti_pianeti
    * blocco [DETAIL] con entità KB per sezione
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Dict, List, Tuple

from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import (
    build_oroscopo_payload_ai,
    PERIOD_KEY_TO_CODE,
)
from astrobot_core.fetch_kb_from_hooks import KB_TABLES


# Periodi che vogliamo generare dalla pipeline
PERIOD_KEYS = ["giornaliero", "settimanale", "mensile", "annuale"]

# Periodi effettivamente usati per tier
FREE_PERIODS = ["giornaliero", "settimanale"]
PREMIUM_PERIODS = ["giornaliero", "settimanale", "mensile", "annuale"]

PERIOD_LABELS: Dict[str, str] = {
    "giornaliero": "Oroscopo di oggi",
    "settimanale": "Oroscopo della settimana",
    "mensile": "Oroscopo del mese",
    "annuale": "Oroscopo dell'anno",
}


def estimate_tokens_from_chars(n_chars: int) -> int:
    """Stima grezza: 1 token ≈ 4 caratteri."""
    if n_chars <= 0:
        return 0
    return max(1, n_chars // 4)


# ============================================================================
#  COSTRUZIONE OROSCOPO_STRUCT COMPLETO DALLA PIPELINE
# ============================================================================

def build_oroscopo_struct_from_pipeline() -> Dict[str, Any]:
    """
    Costruisce un oroscopo_struct multi-periodo "reale" usando TUTTA la pipeline:

    - tema natale: costruisci_tema_natale
    - multi-snapshot per ogni periodo: run_oroscopo_multi_snapshot
      (che usa transiti_vs_tema_precalc + transiti_pesatura)
    - raccolta degli aspetti rilevanti per tutti i periodi come transiti globali
    - costruzione blocco 'periodi' con ambiti + drivers
    """

    # ----- Dati utente hard-coded per il test -----
    citta = "Napoli"
    data_nascita_str = "1986-07-19"  # STRINGA "YYYY-MM-DD"
    ora_nascita_str = "08:50"        # STRINGA "HH:MM"

    # Data di riferimento per il test (ancora "oggi")
    raw_date = date.today()

    # 1) Tema natale completo (serve per 'tema' in oroscopo_struct)
    #    NB: costruisci_tema_natale vuole data_nascita come STRINGA.
    tema_natale = costruisci_tema_natale(
        citta=citta,
        data_nascita=data_nascita_str,
        ora_nascita=ora_nascita_str,
        sistema_case="equal",
    )

    # 2) Per ogni periodo, eseguo la pipeline multi-snapshot (tier premium)
    periodi_results: Dict[str, Dict[str, Any]] = {}
    for period_key in PERIOD_KEYS:
        print(f"[PIPELINE] Calcolo periodo={period_key}, tier=premium")
        res = run_oroscopo_multi_snapshot(
            periodo=period_key,          # Periodo (Literal["giornaliero", ...])
            tier="premium",              # Tier
            citta=citta,
            data_nascita=data_nascita_str,
            ora_nascita=ora_nascita_str,
            raw_date=raw_date,           # <--- parametro corretto, NO data_riferimento
            # include_node / include_lilith / filtri usano i default
        )
        periodi_results[period_key] = res

    # 3) Costruisco oroscopo_struct base
    oroscopo_struct: Dict[str, Any] = {
        "meta": {
            "nome": "Demo User",
            "citta_nascita": citta,
            "data_nascita": data_nascita_str,
            "ora_nascita": ora_nascita_str,
            "tier": "premium",  # verrà sovrascritto nei test per 'free'
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema_natale,
        "transiti": [],  # lo riempiamo subito sotto
        "periodi": {},   # idem
    }

    # 4) TRANSITI GLOBALI: unisco gli aspetti rilevanti di TUTTI i periodi
    transiti_global: List[Dict[str, Any]] = []
    seen_keys: set[Tuple[str, str, str, str]] = set()

    for period_key, res in periodi_results.items():
        aspetti_ril = res.get("aspetti_rilevanti", []) or []
        period_code = PERIOD_KEY_TO_CODE.get(period_key, "daily")

        for a in aspetti_ril:
            tp = a.get("pianeta_transito")
            np = a.get("pianeta_natale")
            asp = a.get("aspetto")
            if not (tp and np and asp):
                continue

            key = (str(tp), str(np), str(asp), period_code)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            transiti_global.append(
                {
                    "transit_planet": str(tp),
                    "natal_planet": str(np),
                    "aspect": str(asp),
                    "period_code": period_code,
                    "score_rilevanza": float(a.get("score_rilevanza", 0.0)),
                    "orb_min": float(a.get("orb_min", 0.0)),
                    "n_snapshot": int(a.get("n_snapshot", 0)),
                }
            )

    oroscopo_struct["transiti"] = transiti_global

    # 5) BLOCCO PERIODI: ambiti + drivers derivati dalla pipeline
    periodi_struct: Dict[str, Any] = {}
    for period_key, res in periodi_results.items():
        metriche = res.get("metriche_grafico", {}) or {}
        per_ambito = metriche.get("per_ambito", {}) or {}

        # score per ogni ambito (energy, emotions, relationships, work, luck...)
        ambiti: Dict[str, Any] = {}
        for ambito_key, data_ambito in per_ambito.items():
            if not isinstance(data_ambito, dict):
                continue
            score = data_ambito.get("score_norm")
            if score is None:
                score = data_ambito.get("score", 0.0)

            # drivers = primi 3 aspetti rilevanti di questo periodo
            drivers: List[Dict[str, Any]] = []
            for a in (res.get("aspetti_rilevanti") or [])[:3]:
                tp = a.get("pianeta_transito")
                np = a.get("pianeta_natale")
                asp = a.get("aspetto")
                if not (tp and np and asp):
                    continue
                drivers.append(
                    {
                        "transit_planet": str(tp),
                        "natal_planet": str(np),
                        "aspect": str(asp),
                        "score_rilevanza": float(a.get("score_rilevanza", 0.0)),
                        "orb_min": float(a.get("orb_min", 0.0)),
                    }
                )

            ambiti[ambito_key] = {
                "score": float(score or 0.0),
                "drivers": drivers,
            }

        periodi_struct[period_key] = {
            "label": PERIOD_LABELS.get(period_key, period_key),
            "tier": "premium",
            "date_range": {
                "start": res.get("anchor_date"),
                "end": None,
            },
            "ambiti": ambiti,
        }

    oroscopo_struct["periodi"] = periodi_struct

    return oroscopo_struct


# ============================================================================
#  TEST KB VOLUME SU oroscopo_struct COSTRUITO DALLA PIPELINE
# ============================================================================

def run_kb_volume_test(oroscopo_struct_base: Dict[str, Any]) -> None:
    base_periodi = oroscopo_struct_base.get("periodi") or {}
    if not isinstance(base_periodi, dict) or not base_periodi:
        raise SystemExit("L'oroscopo_struct generato non contiene una chiave 'periodi' valida.")

    available_periods = [k for k in PERIOD_KEYS if k in base_periodi]
    if not available_periods:
        raise SystemExit(
            f"Nessuno dei periodi attesi {PERIOD_KEYS} è presente oroscopo_struct['periodi'].\n"
            f"Chiavi trovate: {list(base_periodi.keys())}"
        )

    print("\n[TEST KB VOLUME FULL PIPELINE - SINTETICO + ENTITIES]")
    print("Periodi disponibili:", ", ".join(available_periods))
    print("N.B.: per 'free' consideriamo solo giornaliero/settimanale se presenti.")
    print("     per 'premium' consideriamo tutti i periodi disponibili.\n")

    header = [
        "TIER",
        "PERIODO",
        "KB_CHARS",
        "TOK_EST",
        "CASE",
        "PIANETI",
        "SEGNI",
        "PIANETI_CASE",
        "TRANSITI_PIANETI",
        "TOTAL_ENTRIES",
    ]
    print(";".join(header))

    # FREE
    _run_for_tier(
        base_struct=oroscopo_struct_base,
        base_periodi=base_periodi,
        tier="free",
        periods_to_test=FREE_PERIODS,
        available_periods=available_periods,
    )

    # PREMIUM
    _run_for_tier(
        base_struct=oroscopo_struct_base,
        base_periodi=base_periodi,
        tier="premium",
        periods_to_test=PREMIUM_PERIODS,
        available_periods=available_periods,
    )


def _run_for_tier(
    base_struct: Dict[str, Any],
    base_periodi: Dict[str, Any],
    tier: str,
    periods_to_test: List[str],
    available_periods: List[str],
) -> None:
    """
    Per un singolo tier stampa:

    1) riga CSV-like sintetica
    2) blocco [TRANSITI USATI] (transiti effettivamente presenti in kb.transiti_pianeti)
    3) blocco [DETAIL] con la matrice delle entità per sezione.
    """
    sections_of_interest = ["case", "pianeti", "segni", "pianeti_case", "transiti_pianeti"]

    for period_key in periods_to_test:
        if period_key not in available_periods:
            continue

        period_code = PERIOD_KEY_TO_CODE.get(period_key, "daily")

        test_struct = deepcopy(base_struct)
        meta = test_struct.get("meta") or {}
        meta["tier"] = tier
        test_struct["meta"] = meta

        # tengo solo il periodo da testare
        test_struct["periodi"] = {period_key: base_periodi[period_key]}

        print(f"\n[DEBUG] Costruisco payload periodo={period_key} ({period_code}), tier={tier}")
        payload_ai = build_oroscopo_payload_ai(
            oroscopo_struct=test_struct,
            lang="it",
            period_code=period_code,
        )

        kb = payload_ai.get("kb", {}) or {}
        kb_md = kb.get("combined_markdown", "") or ""
        by_section = kb.get("by_section", {}) or {}

        n_chars = len(kb_md)
        n_tokens_est = estimate_tokens_from_chars(n_chars)

        counts = {sec: len(by_section.get(sec, [])) for sec in sections_of_interest}
        total_entries = sum(counts.values())

        # RIGA SINTETICA
        row = [
            tier,
            period_key,
            str(n_chars),
            str(n_tokens_est),
            str(counts["case"]),
            str(counts["pianeti"]),
            str(counts["segni"]),
            str(counts["pianeti_case"]),
            str(counts["transiti_pianeti"]),
            str(total_entries),
        ]
        print(";".join(row))

        # --------- TRANSITI USATI (section transiti_pianeti) ---------
        trans_rows = by_section.get("transiti_pianeti", []) or []
        seen_tr: set[Tuple[str, str, str]] = set()
        unique_trans: List[Tuple[str, str, str]] = []

        for r in trans_rows:
            if not isinstance(r, dict):
                continue
            tp = str(r.get("transit_planet") or "")
            np = str(r.get("natal_planet") or "")
            asp = str(r.get("aspect") or r.get("aspetto") or "")
            if not (tp and np and asp):
                continue
            key = (tp, np, asp)
            if key in seen_tr:
                continue
            seen_tr.add(key)
            unique_trans.append(key)

        print(f"\n[TRANSITI USATI] tier={tier}, periodo={period_key} (n={len(unique_trans)}):")
        for tp, np, asp in unique_trans:
            print(f"   - {tp} {asp} {np}")

        # --------- DETAIL ENTITIES PER SEZIONE ---------
        print(f"\n[DETAIL] tier={tier}, periodo={period_key}")

        for section in sections_of_interest:
            rows = by_section.get(section, []) or []
            if not rows:
                continue

            cfg = KB_TABLES.get(section)
            if cfg:
                id_columns = cfg.id_columns
            else:
                sample = rows[0]
                id_columns = tuple(
                    k for k in sample.keys()
                    if k != "content_md"
                )

            seen = set()
            entities: List[Dict[str, Any]] = []

            for r in rows:
                key = tuple(r.get(col) for col in id_columns)
                if key in seen:
                    continue
                seen.add(key)
                ent = {col: r.get(col) for col in id_columns}
                entities.append(ent)

            print(f"- {section}:")
            for ent in entities:
                parts = [f"{k}={v}" for k, v in ent.items()]
                print("    - " + ", ".join(parts))

        print("")


# ============================================================================
#  MAIN
# ============================================================================

def main() -> None:
    oroscopo_struct = build_oroscopo_struct_from_pipeline()
    run_kb_volume_test(oroscopo_struct)


if __name__ == "__main__":
    main()
