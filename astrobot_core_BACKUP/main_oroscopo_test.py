from __future__ import annotations
from datetime import date, datetime
from typing import Any, Dict

# IMPORT ASSOLUTO (niente import relativo con il punto)
from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot


def _print_result(periodo: str, tier: str, result: Dict[str, Any]) -> None:
    """
    Stampa compatta per ispezionare il risultato della pipeline
    per un dato periodo/tier.
    """
    title = f"{periodo.upper()} {tier.upper()}"
    print("=" * 80)
    print(title)
    print("=" * 80)

    # Anchor date
    print(f"Anchor date: {result.get('anchor_date')}")

    # --- snapshots info ---
    print("\nSnapshots:")
    for s in result.get("snapshots_info", []):
        print(f" - {s['label']:<24} {s['datetime']}")

    # --- metriche per snapshot (intensities) ---
    print("\nMetriche (intensities) per snapshot:")
    for s in result.get("snapshots_raw", []):
        label = s["label"]
        dt = s["datetime"]
        intensities = s["metrics"]["intensities"]
        print(f" * {label:<24} {dt}")
        print(f"   intensities: {intensities}")

    # --- aspetti rilevanti aggregati ---
    print("\nAspetti rilevanti (aggregati):")
    for a in result.get("aspetti_rilevanti", []):
        pt = a["pianeta_transito"]
        pn = a["pianeta_natale"]
        asp = a["aspetto"]
        score = a["score_rilevanza"]
        orb_min = a["orb_min"]
        n_snap = a["n_snapshot"]
        occ = a.get("occorrenze", [])
        first_occ = occ[0] if occ else None

        print(
            f" - {pt} {asp} {pn} | score={score:.3f} | "
            f"orb_min={orb_min:.2f} | n_snapshot={n_snap}"
        )
        if first_occ:
            print(
                f"   prima occorrenza: {first_occ['datetime']} "
                f"(orb={first_occ['orb']:.3f})"
            )

    # --- pianeti prevalenti + casa natale di transito ---
    pianeti_prev = result.get("pianeti_prevalenti") or []
    if pianeti_prev:
        print("\nPianeti prevalenti per AI (pianeta + casa natale di transito):")
        for p in pianeti_prev:
            nome = p["pianeta"]
            sp = p["score_periodo"]
            fn = p["fattore_natale"]
            casa = p.get("casa_natale_transito")
            dt_first = p.get("prima_occorrenza")

            if isinstance(casa, int) and casa > 0:
                casa_str = f"casa natale {casa}"
            else:
                casa_str = "[non determinata]"

            extra_dt = f" (prima occorrenza a {dt_first})" if dt_first else ""

            print(
                f"  - {nome:<10} (score_periodo={sp:.3f}, fatt_natale={fn:.3f})"
                f" => transito in {casa_str}{extra_dt}"
            )

    print()  # riga vuota finale


def main() -> None:
    print("\n[DEBUG] main_oroscopo_test: avvio test oroscopo multi-snapshot\n")

    # Dati di test: il tuo solito esempio
    citta = "Napoli"
    data_nascita = "1986-07-19"
    ora_nascita = "08:50"

    # Data di riferimento (puoi cambiarla se vuoi)
    data_rif = date(2025, 11, 8)

    # Periodo/tier da testare (incluso ANNUALE)
    test_cases = [
        ("giornaliero", "free"),
        ("giornaliero", "premium"),
        ("settimanale", "free"),
        ("settimanale", "premium"),
        ("mensile", "premium"),
        ("annuale", "premium"),
    ]

    for periodo, tier in test_cases:
        print(f"\n[DEBUG] Eseguo periodo={periodo}, tier={tier}\n")
        res = run_oroscopo_multi_snapshot(
            periodo=periodo,
            tier=tier,
            citta=citta,
            data_nascita=data_nascita,
            ora_nascita=ora_nascita,
            raw_date=data_rif,
            include_node=True,
            include_lilith=True,
            filtra_transito=None,
            filtra_natal=None,
        )
        _print_result(periodo, tier, res)


if __name__ == "__main__":
    main()
