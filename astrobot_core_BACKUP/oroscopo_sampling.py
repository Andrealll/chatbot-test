from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Dict, List, Literal

# Tipi logici per periodo e tier
Periodo = Literal["giornaliero", "settimanale", "mensile", "annuale"]
Tier = Literal["free", "premium"]


def compute_anchor_date(periodo: Periodo, raw_date: date) -> date:
    """
    Calcola una 'data ancora' in base al periodo.

    - giornaliero: usa direttamente raw_date
    - settimanale: ancora = mercoledì di quella settimana
    - mensile: ancora = primo giorno del mese
    - annuale: ancora = 1 gennaio di quell'anno
    """
    p = str(periodo)

    if p == "giornaliero":
        return raw_date

    if p == "settimanale":
        # weekday(): lun=0,...,dom=6 ; vogliamo mercoledì=2
        weekday = raw_date.weekday()
        delta = 2 - weekday  # 2 = mercoledì
        return raw_date + timedelta(days=delta)

    if p == "mensile":
        return raw_date.replace(day=1)

    if p == "annuale":
        return date(2026, 1, 1)

    # fallback di sicurezza
    return raw_date


def get_sampling_datetimes(
    periodo: Periodo,
    tier: Tier,
    data_riferimento: date,
) -> List[Dict[str, str]]:
    """
    Restituisce una lista di:
      { "label": str, "datetime": "YYYY-MM-DDTHH:MM" }
    in base a periodo e tier.

    Regole:

      - giornaliero free:
          1 snapshot: oggi 15:00
      - giornaliero premium:
          3 snapshot: oggi 12:00, oggi 19:00, domani 09:00

      - settimanale free:
          2 snapshot: mercoledì 12:00 (settimana), sabato 12:00 (weekend)
      - settimanale premium:
          4 snapshot: martedì 12, giovedì 12, sabato 12, lunedì successivo 12

      - mensile premium:
          12 snapshot: uno ogni 3 giorni, a partire dal 1° del mese, tutti alle 12:00,
          includendo i primi giorni del mese successivo.

      - annuale (free/premium uguale):
          52 snapshot: uno a settimana, dalle 12:00 del 1 gennaio.
    """
    p = str(periodo)
    t = str(tier)

    out: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # GIORNALIERO
    # ------------------------------------------------------------------
    if p == "giornaliero":
        giorno = data_riferimento

        if t == "free":
            # 1 solo snapshot alle 15:00
            dt = datetime(giorno.year, giorno.month, giorno.day, 15, 0)
            out.append(
                {"label": "oggi", "datetime": dt.isoformat(timespec="minutes")}
            )

        else:  # premium
            # oggi 12:00, oggi 19:00, domani 9:00
            dt_oggi = datetime(giorno.year, giorno.month, giorno.day, 12, 0)
            dt_ssera = datetime(giorno.year, giorno.month, giorno.day, 19, 0)
            domani = giorno + timedelta(days=1)
            dt_domani = datetime(domani.year, domani.month, domani.day, 9, 0)

            out.extend(
                [
                    {
                        "label": "oggi",
                        "datetime": dt_oggi.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "stasera",
                        "datetime": dt_ssera.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "domani",
                        "datetime": dt_domani.isoformat(timespec="minutes"),
                    },
                ]
            )

        return out

    # ------------------------------------------------------------------
    # SETTIMANALE
    # ------------------------------------------------------------------
    if p == "settimanale":
        # data_riferimento è già l'anchor (mercoledì)
        base = datetime(
            data_riferimento.year,
            data_riferimento.month,
            data_riferimento.day,
            12,
            0,
        )

        if t == "free":
            # mercoledì 12:00 (settimana) e sabato 12:00 (weekend)
            dt_sett = base
            dt_weekend = base + timedelta(days=3)

            out.extend(
                [
                    {
                        "label": "settimana",
                        "datetime": dt_sett.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "weekend",
                        "datetime": dt_weekend.isoformat(timespec="minutes"),
                    },
                ]
            )

        else:  # premium
            # martedì 12, giovedì 12, sabato 12, lunedì successivo 12
            martedi = base - timedelta(days=1)
            giovedi = base + timedelta(days=1)
            sabato = base + timedelta(days=3)
            lun_next = base + timedelta(days=5)

            out.extend(
                [
                    {
                        "label": "inizio_settimana",
                        "datetime": martedi.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "centro_settimana",
                        "datetime": giovedi.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "weekend",
                        "datetime": sabato.isoformat(timespec="minutes"),
                    },
                    {
                        "label": "inizio_prossima",
                        "datetime": lun_next.isoformat(timespec="minutes"),
                    },
                ]
            )

        return out

    # ------------------------------------------------------------------
    # MENSILE (solo premium)
    # ------------------------------------------------------------------
    if p == "mensile":
        # ancora = primo giorno del mese
        base = datetime(
            data_riferimento.year, data_riferimento.month, data_riferimento.day, 12, 0
        )

        # 12 slot ogni 3 giorni
        for i in range(12):
            dt = base + timedelta(days=i * 3)
            label = f"mese_slot_{i + 1}"
            out.append({"label": label, "datetime": dt.isoformat(timespec="minutes")})

        return out

    # ------------------------------------------------------------------
    # ANNUALE: 52 snapshot, uno a settimana
    # ------------------------------------------------------------------
    if p == "annuale":
        year = 2026
        base_dt = datetime(year, 1, 1, 12, 0)
        n_weeks = 52

        for i in range(n_weeks):
            dt = base_dt + timedelta(weeks=i)
            label = f"anno_settimana_{i + 1}"
            out.append({"label": label, "datetime": dt.isoformat(timespec="minutes")})

        return out

    # ------------------------------------------------------------------
    # fallback
    # ------------------------------------------------------------------
    dt = datetime(
        data_riferimento.year, data_riferimento.month, data_riferimento.day, 12, 0
    )
    out.append({"label": "unico", "datetime": dt.isoformat(timespec="minutes")})
    return out
