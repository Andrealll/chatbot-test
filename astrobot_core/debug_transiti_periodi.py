# ------------------------------------------------------------
# DEBUG TRANSITI PER ASTROBOT (pipeline nuova)
# ------------------------------------------------------------

from typing import Any, Dict
from datetime import date

from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai


def debug_print_transiti_payload_ai(payload_ai: dict) -> None:
    """
    Debug che mostra SOLO gli aspetti rilevanti,
    filtrati per score > 0, senza elencare tutti gli aspetti grezzi.
    """
    print("\n==============================")
    print("DEBUG TRANSITI - PAYLOAD_AI (SOLO RILEVANTI)")
    print("==============================")

    meta = payload_ai.get("meta", {})
    print(f"- Nome: {meta.get('nome')}")
    print(f"- Città: {meta.get('citta')}")
    print(f"- Data di nascita: {meta.get('data_nascita')}")
    print(f"- Periodo richiesto: {meta.get('periodo_it')}")
    print(f"- Tier: {meta.get('tier')}")
    print("------------------------------")

    periodi = payload_ai.get("periodi", {})
    if not periodi:
        print("⚠ Nessun periodo trovato.")
        return

    for periodo_key, periodo_data in periodi.items():
        print(f"\n=== PERIODO: {periodo_key} ===")

        # Lista aspetti rilevanti aggregati
        aspetti_ril = periodo_data.get("aspetti_rilevanti") or []

        # Filtriamo SOLO quelli con score > 0 (in qualunque campo venga messo)
        aspetti_ril_filtrati = []
        for a in aspetti_ril:
            score = (
                a.get("score_rilevanza")
                or a.get("score")
                or (a.get("extra") or {}).get("score_definitivo")
                or 0.0
            )
            if score and score > 0:
                aspetti_ril_filtrati.append((a, score))

        print(f"- N. aspetti rilevanti totali: {len(aspetti_ril)}")
        print(f"- N. aspetti rilevanti con score > 0: {len(aspetti_ril_filtrati)}")

        if not aspetti_ril_filtrati:
            print("  (nessun aspetto con score > 0)")
        else:
            print("  Dettaglio aspetti rilevanti (score > 0):")
            for a, score in aspetti_ril_filtrati[:20]:
                pt = a.get("pianeta_transito")
                pn = a.get("pianeta_natale")
                asp = a.get("aspetto")
                orb_min = a.get("orb_min")
                print(f"  • {pt} {asp} {pn} | orb_min={orb_min} | score={score}")

        # Solo info di contesto sugli snapshot, senza elencare gli aspetti grezzi
        snapshots = periodo_data.get("snapshots_raw") or []
        print(f"- N. snapshots (grezzi): {len(snapshots)}")

        print("\n------------------------------")



def main() -> None:
    """
    Esegue la pipeline oroscopo_multi_snapshot per tutti i periodi,
    costruisce il payload_ai e stampa i transiti reali usati.
    """
    # Input di test
    citta = "Napoli"
    data_nascita = "1986-07-19"
    ora_nascita = "08:50"
    tier = "premium"  # cambia in "free" se vuoi
    raw_date = date.today()

    periodi_da_testare = ["giornaliero", "settimanale", "mensile", "annuale"]

    period_code_map = {
        "giornaliero": "daily",
        "settimanale": "weekly",
        "mensile": "monthly",
        "annuale": "yearly",
    }

    for periodo in periodi_da_testare:
        print("\n====================================================")
        print(f"TEST TRANSITI - PERIODO: {periodo} - TIER: {tier}")
        print("====================================================")

        # 1) Pipeline: oroscopo_struct per il singolo periodo
        oroscopo_struct: Dict[str, Any] = run_oroscopo_multi_snapshot(
            periodo=periodo,
            tier=tier,
            citta=citta,
            data_nascita=data_nascita,
            ora_nascita=ora_nascita,
            raw_date=raw_date,
            include_node=True,
            include_lilith=True,
            filtra_transito=None,
            filtra_natal=None,
        )

        # 2) Costruzione payload_ai per questo periodo
        period_code = period_code_map.get(periodo, "daily")
        payload_ai: Dict[str, Any] = build_oroscopo_payload_ai(
            oroscopo_struct=oroscopo_struct,
            lang="it",
            period_code=period_code,
        )

        # 3) Debug transiti: stampa aspetti e snapshot reali
        debug_print_transiti_payload_ai(payload_ai)


if __name__ == "__main__":
    main()
