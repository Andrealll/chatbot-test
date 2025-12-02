"""
test_kb_volume_real.py (NUOVA VERSIONE - full pipeline)

Testa il volume della KB usando un oroscopo_struct costruito
DINAMICAMENTE dalla pipeline run_oroscopo_multi_snapshot,
per un tema natale fisso, per tutte le combinazioni:

- tier: free / premium
- periodo: giornaliero / settimanale / mensile / annuale

Per ogni combinazione costruiamo:

1) oroscopo_struct "minimal" ma compatibile con oroscopo_payload_ai:
   - meta: tier, info anagrafiche fittizie, periodo principale
   - tema: tema natale completo (costruisci_tema_natale)
   - transiti: lista di aspetti rilevanti sul periodo
   - periodi[periodo].ambiti["generale"].drivers: lista driver
     che rimappano gli stessi aspetti rilevanti, utile per case/segni

2) Chiamiamo build_oroscopo_payload_ai(oroscopo_struct, lang="it")
   e misuriamo:

   TIER;PERIODO;KB_CHARS;TOK_EST;CASE;PIANETI;SEGNI;PIANETI_CASE;TRANSITI_PIANETI;TOTAL_ENTRIES

3) Stampiamo anche il dettaglio delle entità usate, inclusi i
   transiti effettivamente presenti nella KB.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai
from astrobot_core.calcoli import costruisci_tema_natale
from astrobot_core.fetch_kb_from_hooks import KB_TABLES


# Tema natale di test (quello che abbiamo usato nei test pipeline)
TEST_CITTA = "Napoli"
TEST_DATA_NASCITA = "1986-07-19"
TEST_ORA_NASCITA = "08:50"

# Data di riferimento "ancora" per tutti i periodi.
# La logica di compute_anchor_date nel sampling farà:
# - giornaliero: ancora = stessa data
# - settimanale: ancora = mercoledì di quella settimana
# - mensile: ancora = primo giorno del mese
# - annuale: 1 gennaio dell'anno successivo (2026 fisso)
TEST_RAW_DATE = date(2025, 11, 8)

PERIOD_KEYS = ["giornaliero", "settimanale", "mensile", "annuale"]

FREE_PERIODS = ["giornaliero", "settimanale"]
PREMIUM_PERIODS = ["giornaliero", "settimanale", "mensile", "annuale"]


def estimate_tokens_from_chars(n_chars: int) -> int:
    """Stima grezza: 1 token ≈ 4 caratteri."""
    if n_chars <= 0:
        return 0
    return max(1, n_chars // 4)


def _build_oroscopo_struct_for(
    periodo_key: str,
    tier: str,
) -> Dict[str, Any]:
    """
    Costruisce un oroscopo_struct "minimal" compatibile con
    build_oroscopo_payload_ai, usando la pipeline multi-snapshot.

    NB: qui richiamiamo sia la pipeline (per transiti/ambiti) sia
    costruisci_tema_natale (per avere un blocco 'tema' completo,
    come si aspetta la funzione di payload AI).
    """
    if periodo_key not in PERIOD_KEYS:
        raise ValueError(f"Periodo non valido: {periodo_key!r}")

    # 1) Eseguiamo la pipeline multi-snapshot
    res = run_oroscopo_multi_snapshot(
        periodo=periodo_key,
        tier=tier,
        citta=TEST_CITTA,
        data_nascita=TEST_DATA_NASCITA,
        ora_nascita=TEST_ORA_NASCITA,
        raw_date=TEST_RAW_DATE,
        include_node=True,
        include_lilith=True,
    )

    # 2) Tema natale "completo" per la sezione 'tema' dello struct
    tema = costruisci_tema_natale(
        citta=TEST_CITTA,
        data_nascita=TEST_DATA_NASCITA,
        ora_nascita=TEST_ORA_NASCITA,
        sistema_case="equal",
    )

    # 3) Aspetti rilevanti aggregati sul periodo
    aspetti_agg = res.get("aspetti_rilevanti", []) or []
    pianeti_prevalenti = res.get("pianeti_prevalenti", []) or []

    # Trasformiamo aspetti_agg nel formato che _build_kb_hooks capisce
    # per i transiti:
    #   - chiavi: transit_planet, natal_planet, aspect
    transiti_list: List[Dict[str, Any]] = []
    for a in aspetti_agg:
        transiti_list.append(
            {
                "transit_planet": a.get("pianeta_transito"),
                "natal_planet": a.get("pianeta_natale"),
                "aspect": a.get("aspetto"),
                # info extra utili per debug / futuro
                "orb_min": a.get("orb_min"),
                "orb_media": a.get("orb_media"),
                "score_rilevanza": a.get("score_rilevanza"),
                "n_snapshot": a.get("n_snapshot"),
            }
        )

    # 4) Costruiamo una struttura 'periodi' minimale con un solo ambito "generale"
    #    che contiene come drivers sia gli aspetti rilevanti sia i pianeti prevalenti.
    drivers: List[Dict[str, Any]] = []

    # driver per transiti pianeta -> pianeta natale
    for tr in transiti_list:
        drivers.append(
            {
                "type": "transito_pianeta",
                "transit_planet": tr.get("transit_planet"),
                "natal_planet": tr.get("natal_planet"),
                "aspect": tr.get("aspect"),
            }
        )

    # driver per pianeti prevalenti (pianeta + casa natale di transito)
    for p in pianeti_prevalenti:
        drivers.append(
            {
                "type": "pianeta_prevalente",
                "transit_planet": p.get("pianeta"),
                "natal_house": p.get("casa_natale_transito"),
            }
        )

    period_block = {
        "anchor_date": res.get("anchor_date"),
        "ambiti": {
            # ambito fittizio ma sufficiente per far comparire i driver
            "generale": {
                "intensita": res.get("metriche_grafico", {}),
                "drivers": drivers,
            }
        },
    }

    # 5) oroscopo_struct finale per QUESTA coppia (periodo, tier)
    oroscopo_struct: Dict[str, Any] = {
        "meta": {
            "nome": "Test User",
            "tier": tier,
            "lang": "it",
            "scope": "test_kb_volume_pipeline",
            "citta_nascita": TEST_CITTA,
            "data_nascita": TEST_DATA_NASCITA,
            "ora_nascita": TEST_ORA_NASCITA,
            "periodo_principale": periodo_key,
        },
        "tema": tema,
        # questi transiti sono già "compattati" sugli aspetti più rilevanti
        "transiti": transiti_list,
        "periodi": {
            periodo_key: period_block,
        },
        # opzionale ma utile se un giorno volessimo arricchire l'oroscopo_struct
        "extra_pipeline": {
            "pianeti_prevalenti": pianeti_prevalenti,
            "profilo_natale": res.get("profilo_natale"),
        },
    }

    return oroscopo_struct


def _run_for_tier(
    tier: str,
    periods_to_test: List[str],
) -> None:
    """
    Esegue il test per un singolo tier, stampando:

    1) una riga CSV-like sintetica
    2) un blocco "TRANSITI USATI" con i transiti pescati dalla KB
    3) un blocco "DETAIL" con la matrice delle entità per sezione.
    """
    sections_of_interest = ["case", "pianeti", "segni", "pianeti_case", "transiti_pianeti"]

    for period_key in periods_to_test:
        if period_key not in PERIOD_KEYS:
            continue

        print(f"\n[DEBUG] Costruisco payload periodo={period_key} ({period_key}), tier={tier}")

        # Costruisce oroscopo_struct dinamico da pipeline
        oroscopo_struct = _build_oroscopo_struct_for(
            periodo_key=period_key,
            tier=tier,
        )

        payload_ai = build_oroscopo_payload_ai(oroscopo_struct, lang="it")

        kb = payload_ai.get("kb", {}) or {}
        kb_md = kb.get("combined_markdown", "") or ""
        by_section = kb.get("by_section", {}) or {}

        n_chars = len(kb_md)
        n_tokens_est = estimate_tokens_from_chars(n_chars)

        counts = {sec: len(by_section.get(sec, [])) for sec in sections_of_interest}
        total_entries = sum(counts.values())

        # ---------- Riga sintetica ----------
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

        # ---------- Transiti effettivamente usati ----------
        trans_rows = by_section.get("transiti_pianeti", []) or []
        if trans_rows:
            seen = set()
            trans_list = []
            for r in trans_rows:
                key = (r.get("transit_planet"), r.get("natal_planet"), r.get("aspect"))
                if key in seen:
                    continue
                seen.add(key)
                trans_list.append(key)

            print(f"\n[TRANSITI USATI] tier={tier}, periodo={period_key} (n={len(trans_list)}):")
            for tp, np, asp in trans_list:
                print(f"   - {tp} {asp} {np}")

        # ---------- Dettaglio entità ----------
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
                id_columns = tuple(k for k in sample.keys() if k != "content_md")

            seen_ent = set()
            entities: List[Dict[str, Any]] = []

            for r in rows:
                key = tuple(r.get(col) for col in id_columns)
                if key in seen_ent:
                    continue
                seen_ent.add(key)
                ent = {col: r.get(col) for col in id_columns}
                entities.append(ent)

            print(f"- {section}:")
            for ent in entities:
                parts = [f"{k}={v}" for k, v in ent.items()]
                print("    - " + ", ".join(parts))

        print("")  # riga vuota di separazione


def main() -> None:
    print("\n[TEST KB VOLUME REAL - SINTETICO + ENTITIES]")
    print("Periodi testati:", ", ".join(PERIOD_KEYS))
    print("N.B.: per 'free' consideriamo solo giornaliero/settimanale.")
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

    # TIER: FREE
    _run_for_tier(
        tier="free",
        periods_to_test=FREE_PERIODS,
    )

    # TIER: PREMIUM
    _run_for_tier(
        tier="premium",
        periods_to_test=PREMIUM_PERIODS,
    )


if __name__ == "__main__":
    main()
