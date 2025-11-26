from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from .oroscopo_sampling import (
    Periodo,
    Tier,
    compute_anchor_date,
    get_sampling_datetimes,
)
from .transiti import (
    prepara_tema_natale,
    transiti_vs_tema_precalc,
    ORB_MAX,
)
from .calcoli import costruisci_tema_natale
from .transiti_pesatura import (
    USE_CASE_DAILY,
    USE_CASE_WEEKLY,
    USE_CASE_MONTHLY,
    USE_CASE_YEARLY,
    costruisci_profilo_natale,
    calcola_score_definitivo_aspetto,
)

# Usiamo gli stessi ambiti che avevamo ipotizzato per i grafici
AMBITI = ["energy", "emotions", "relationships", "work", "luck"]

# Mapping semplice pianeta -> ambiti (peso relativo) per i grafici
PIANETA_AMBITI: Dict[str, Dict[str, float]] = {
    "Sole": {
        "energy": 1.0,
        "work": 0.6,
        "luck": 0.3,
    },
    "Luna": {
        "emotions": 1.0,
        "relationships": 0.4,
    },
    "Mercurio": {
        "work": 0.7,
        "energy": 0.3,
    },
    "Venere": {
        "relationships": 1.0,
        "emotions": 0.6,
        "luck": 0.4,
    },
    "Marte": {
        "energy": 1.0,
        "work": 0.7,
    },
    "Giove": {
        "luck": 1.0,
        "work": 0.4,
        "relationships": 0.3,
    },
    "Saturno": {
        "work": 1.0,
        "energy": -0.3,
    },
    "Urano": {
        "energy": 0.7,
        "work": 0.3,
    },
    "Nettuno": {
        "emotions": 0.7,
        "relationships": 0.3,
    },
    "Plutone": {
        "energy": 0.8,
        "work": 0.4,
    },
    # Nodo/Lilith/Asc li possiamo mappare dopo, se necessario
}


# ============================================================================
# HELPER: mappa Periodo -> use_case (daily/weekly/monthly/yearly)
# ============================================================================

def _map_periodo_to_use_case(periodo: Periodo) -> str:
    p = str(periodo)
    if p == "giornaliero":
        return USE_CASE_DAILY
    if p == "settimanale":
        return USE_CASE_WEEKLY
    if p == "mensile":
        return USE_CASE_MONTHLY
    if p == "annuale":
        return USE_CASE_YEARLY
    # fallback: trattiamo come daily
    return USE_CASE_DAILY


# ============================================================================
# DATA CLASS — SNAPSHOT & ASPETTI
# ============================================================================

@dataclass
class AspettoSnapshot:
    """
    Un singolo aspetto in UN dato snapshot (data/ora specifica).

    Viene dalla lista 'aspetti' ritornata da transiti_vs_tema_precalc:
    {
      "transito": "Giove",
      "natal": "Sole",
      "tipo": "trigono",
      "orb": 0.3,
      "delta": ...,
      "long_transito": ...,
      "long_natal": ...,
      "polarita": ...,
      + extra score_definitivo/fattore_natale che aggiungiamo noi
    }
    """
    pianeta_transito: str
    pianeta_natale: str
    aspetto: str
    orb: float
    polarita: float
    datetime_iso: str
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def chiave_base(self) -> str:
        """
        Chiave logica per aggregare lo stesso aspetto su più snapshot.
        """
        return f"{self.pianeta_transito}_{self.aspetto}_{self.pianeta_natale}"


@dataclass
class SnapshotMetrics:
    """
    Metriche per un singolo snapshot (per grafici).
    """
    raw_scores: Dict[str, float]
    intensities: Dict[str, float]
    n_aspetti: int


@dataclass
class SnapshotResult:
    label: str
    datetime_iso: str
    metrics: SnapshotMetrics
    aspetti: List[AspettoSnapshot]


@dataclass
class AspettoAggregato:
    """
    Aspetto raggruppato su più snapshot (es. Giove trigono Sole che dura 3 slot).
    """
    chiave: str
    pianeta_transito: str
    pianeta_natale: str
    aspetto: str
    occorrenze: List[AspettoSnapshot] = field(default_factory=list)

    orb_media: float = 0.0
    orb_min: float = 0.0
    n_snapshot: int = 0
    score_rilevanza: float = 0.0

    def calcola_metriche(self) -> None:
        if not self.occorrenze:
            return

        orbs = [o.orb for o in self.occorrenze]
        self.orb_media = sum(orbs) / len(orbs)
        self.orb_min = min(orbs)
        self.n_snapshot = len(self.occorrenze)

        # --- nuovo: usiamo lo score_definitivo per aspetto (transito * natale)
        score_list = [
            float(o.extra.get("score_definitivo", 0.0)) for o in self.occorrenze
        ]
        if not score_list:
            self.score_rilevanza = 0.0
            return

        score_max = max(score_list)
        score_med = sum(score_list) / len(score_list)

        # peso orb: orb più stretto => leggero boost
        peso_orb = 1.0 / (1.0 + self.orb_min)  # 1 / (1 + orb_min)

        # peso ripetizione: più snapshot tocca, più pesa (fino a +45%)
        fattore_ripetizione = 1.0 + min(self.n_snapshot - 1, 3) * 0.15

        # score di base: privilegiamo il massimo (picchi) ma teniamo conto della media
        score_base = 0.7 * score_max + 0.3 * score_med

        self.score_rilevanza = score_base * peso_orb * fattore_ripetizione


# ============================================================================
# METRICHE (Step 4) — per un singolo snapshot (grafici)
# ============================================================================

def _calcola_metriche_snapshot(
    aspetti: List[Dict[str, Any]],
    periodo: Periodo,
) -> SnapshotMetrics:
    """
    Calcola le metriche per un singolo snapshot a partire dalla lista 'aspetti'
    di transiti_vs_tema_precalc.

    Logica per grafici:
      - ogni aspetto contribuisce a vari 'ambiti' (energy, emotions, ecc.)
        in base al pianeta di transito e alla polarità.
      - orb strette pesano di più.
      - il risultato viene passato attraverso una funzione logistica per
        ottenere intensità 0..1 ASSOLUTE (non più normalizzate per snapshot).
    """
    # inizializza punteggi grezzi
    scores: Dict[str, float] = {a: 0.0 for a in AMBITI}

    for a in aspetti:
        pt = a.get("transito")
        tipo = a.get("tipo")
        orb = float(a.get("orb", 999.0))
        polarita = float(a.get("polarita", 0.0))

        if not isinstance(pt, str) or not isinstance(tipo, str):
            continue

        mappa = PIANETA_AMBITI.get(pt)
        if not mappa:
            continue

        max_orb = ORB_MAX.get(tipo, 8.0)
        if max_orb <= 0:
            continue

        # peso orb: 1.0 quando orb=0, decresce linearmente fino a 0
        peso_orb = max(0.0, 1.0 - (orb / max_orb))

        for ambito, coeff in mappa.items():
            if ambito not in scores:
                continue
            contrib = coeff * polarita * peso_orb
            scores[ambito] += contrib

    # trasformazione assoluta 0..1 con funzione logistica
    intensities: Dict[str, float] = {}
    alpha = 0.8    # fattore di scala: più grande = curva più ripida
    max_abs = 3.0  # clamp per evitare valori estremi

    for ambito, x in scores.items():
        if x > max_abs:
            x = max_abs
        elif x < -max_abs:
            x = -max_abs
        intensities[ambito] = 1.0 / (1.0 + math.exp(-alpha * x))

    return SnapshotMetrics(
        raw_scores=scores,
        intensities=intensities,
        n_aspetti=len(aspetti),
    )


# ============================================================================
# TRASFORMAZIONE ASPETTI → AspettoSnapshot (con score_definitivo)
# ============================================================================

def _build_aspetti_snapshot(
    aspetti: List[Dict[str, Any]],
    dt: datetime,
    use_case: str,
    profilo_natale: Dict[str, float],
) -> List[AspettoSnapshot]:
    """
    Trasforma gli aspetti grezzi di transiti_vs_tema_precalc in AspettoSnapshot
    e calcola per ciascuno:
      - intensita_base (solo transito)
      - fattore_natale (casa angolare, ruler, aspetti stretti)
      - score_definitivo = intensita_base * fattore_natale
    """
    out: List[AspettoSnapshot] = []
    dt_iso = dt.isoformat(timespec="minutes")

    for a in aspetti:
        pt = a.get("transito")
        pn = a.get("natal")
        tipo = a.get("tipo")
        orb = float(a.get("orb", 999.0))
        polarita = float(a.get("polarita", 0.0))

        if not (isinstance(pt, str) and isinstance(pn, str) and isinstance(tipo, str)):
            continue

        # calcolo score definitivo transito * natale
        score_info = calcola_score_definitivo_aspetto(
            use_case=use_case,
            pianeta_transito=pt,
            pianeta_natale=pn,
            aspetto_tipo=tipo,
            orb=orb,
            polarita=polarita,
            profilo_natale=profilo_natale,
        )

        extra = {
            k: v
            for k, v in a.items()
            if k not in {"transito", "natal", "tipo", "orb", "polarita"}
        }
        extra.update(
            {
                "use_case": use_case,
                "intensita_base": score_info["intensita_base"],
                "fattore_natale": score_info["fattore_natale"],
                "score_definitivo": score_info["score_definitivo"],
            }
        )

        out.append(
            AspettoSnapshot(
                pianeta_transito=pt,
                pianeta_natale=pn,
                aspetto=tipo,
                orb=orb,
                polarita=polarita,
                datetime_iso=dt_iso,
                extra=extra,
            )
        )

    return out


# ============================================================================
# AGGREGAZIONE METRICHE MULTI-SNAPSHOT (per grafici)
# ============================================================================

def aggrega_metriche_per_grafico(samples: List[SnapshotResult]) -> Dict[str, Any]:
    """
    Wrapper semplice: restituisce tutti i punti pronti per essere plottati
    (es. grafico a linee su asse temporale, o barre per label).
    """
    punti: List[Dict[str, Any]] = []
    for s in samples:
        punti.append(
            {
                "label": s.label,
                "datetime": s.datetime_iso,
                "metrics": {
                    "raw_scores": s.metrics.raw_scores,
                    "intensities": s.metrics.intensities,
                    "n_aspetti": s.metrics.n_aspetti,
                },
            }
        )
    return {"samples": punti}


# ============================================================================
# AGGREGAZIONE ASPETTI RILEVANTI (per KB + AI)
# ============================================================================

def aggrega_aspetti_rilevanti(
    samples: List[SnapshotResult],
    max_aspetti: int = 5,
    orb_max: float = 3.0,
) -> List[AspettoAggregato]:
    """
    Raggruppa gli aspetti su più snapshot e seleziona i più rilevanti
    in base a:
      - score_definitivo (transito * natale)
      - durata sul periodo (n_snapshot)
      - orb_min (più stretto = meglio)
    """
    aggregati: Dict[str, AspettoAggregato] = {}

    for sample in samples:
        for asp in sample.aspetti:
            if asp.orb > orb_max:
                continue
            key = asp.chiave_base
            if key not in aggregati:
                aggregati[key] = AspettoAggregato(
                    chiave=key,
                    pianeta_transito=asp.pianeta_transito,
                    pianeta_natale=asp.pianeta_natale,
                    aspetto=asp.aspetto,
                )
            aggregati[key].occorrenze.append(asp)

    for agg in aggregati.values():
        agg.calcola_metriche()

    ordinati = sorted(
        aggregati.values(),
        key=lambda a: a.score_rilevanza,
        reverse=True,
    )
    return ordinati[:max_aspetti]


def _serialize_aspetti_aggregati_light(
    aspetti: List[AspettoAggregato],
) -> List[Dict[str, Any]]:
    """
    Serializza gli AspettoAggregato in forma leggera per AI/KB:

    - mantiene:
        * chiave logica
        * pianeta_transito / pianeta_natale
        * tipo di aspetto
        * orb_media / orb_min
        * n_snapshot (quante volte appare nel periodo)
        * score_rilevanza
        * prima_occorrenza (prima data in cui l'aspetto compare)
    - NON include più la lista completa delle occorrenze
      per ridurre la dimensione del JSON.
    """
    out: List[Dict[str, Any]] = []

    for a in aspetti:
        if a.occorrenze:
            prima = min(o.datetime_iso for o in a.occorrenze)
        else:
            prima = None

        out.append(
            {
                "chiave": a.chiave,
                "pianeta_transito": a.pianeta_transito,
                "pianeta_natale": a.pianeta_natale,
                "aspetto": a.aspetto,
                "orb_media": a.orb_media,
                "orb_min": a.orb_min,
                "n_snapshot": a.n_snapshot,
                "score_rilevanza": a.score_rilevanza,
                "prima_occorrenza": prima,
            }
        )

    return out


# ============================================================================
# HELPER: casa natale da longitudine di transito
# ============================================================================

def _trova_casa_da_longitudine(long_deg: float, cuspidi: List[float]) -> int:
    """
    Dato un grado eclittico di un pianeta di transito e la lista delle cuspidi
    delle 12 case natali (case[0] = cuspide I, ecc.), restituisce il numero
    di casa (1..12).
    """
    if not cuspidi or len(cuspidi) != 12:
        return 0

    long_deg = float(long_deg) % 360.0

    for i in range(12):
        start = float(cuspidi[i]) % 360.0
        end = float(cuspidi[(i + 1) % 12]) % 360.0

        if start <= end:
            # intervallo "normale"
            if start <= long_deg < end:
                return i + 1
        else:
            # intervallo che passa da 360 a 0 (es. 350° -> 20°)
            if long_deg >= start or long_deg < end:
                return i + 1

    # fallback: se non rientra in nessun intervallo, mettiamo casa 0 (non determinata)
    return 0


def _calcola_pianeti_prevalenti(
    samples: List[SnapshotResult],
    tema_ctx: Dict[str, Any],
    max_pianeti: int = 3,
) -> List[Dict[str, Any]]:
    """
    Calcola i pianeti di TRANSITO "principali" sul periodo, sommando gli
    score_definitivo sugli aspetti che li coinvolgono.

    Per ciascun pianeta di transito ritorna:
      - nome pianeta
      - score_periodo (somma score_definitivo)
      - fattore_natale (max dei fattori_natale degli aspetti in cui è coinvolto)
      - casa_natale_transito: casa natale in cui cade il transito alla
        PRIMA occorrenza utile
      - prima_occorrenza: datetime_iso della prima occorrenza
    """
    # recuperiamo cuspidi case dal tema natale "leggero"
    natal_block = tema_ctx.get("natal", {})
    asc_mc_case = natal_block.get("asc_mc_case") or {}
    cuspidi = asc_mc_case.get("case") or []

    agg: Dict[str, Dict[str, Any]] = {}

    for sample in samples:
        for asp in sample.aspetti:
            pt = asp.pianeta_transito
            score_def = float(asp.extra.get("score_definitivo", 0.0))
            fatt_nat = float(asp.extra.get("fattore_natale", 1.0))
            long_tr = asp.extra.get("long_transito")

            info = agg.get(pt)
            if info is None:
                info = {
                    "pianeta": pt,
                    "score_periodo": 0.0,
                    "fattore_natale": 0.0,
                    "prima_occorrenza": asp.datetime_iso,
                    "long_transito_prima": long_tr,
                }
                agg[pt] = info

            info["score_periodo"] += score_def
            if fatt_nat > info["fattore_natale"]:
                info["fattore_natale"] = fatt_nat

            # prima occorrenza: teniamo la più vecchia (samples sono già in ordine)
            # quindi non aggiorniamo mai prima_occorrenza, solo eventualmente il long se era None
            if info.get("long_transito_prima") is None and long_tr is not None:
                info["long_transito_prima"] = long_tr

    # trasformiamo in lista e calcoliamo casa natale del transito
    out: List[Dict[str, Any]] = []
    for pt, info in agg.items():
        casa_transito = None
        long_tr = info.get("long_transito_prima")
        if cuspidi and isinstance(long_tr, (int, float, float)):
            casa = _trova_casa_da_longitudine(float(long_tr), cuspidi)
            if casa > 0:
                casa_transito = casa

        out.append(
            {
                "pianeta": info["pianeta"],
                "score_periodo": info["score_periodo"],
                "fattore_natale": info["fattore_natale"] or 1.0,
                "casa_natale_transito": casa_transito,
                "prima_occorrenza": info["prima_occorrenza"],
            }
        )

    # ordiniamo per score_periodo decrescente
    out.sort(key=lambda x: x["score_periodo"], reverse=True)

    return out[:max_pianeti]


# ============================================================================
# NUOVO: split mensile in 4 sottoperiodi usando gli snapshot
# ============================================================================

def _split_mensile_in_sottoperiodi(
    samples: List[SnapshotResult],
    anchor_date: date,
    tema_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Divide gli snapshot mensili in 4 sottoperiodi:
      1. inizio mese (1–10)
      2. metà mese (11–20)
      3. fine mese (21–fine mese)
      4. inizio mese successivo (1–7 next month)

    Per ogni sottoperiodo:
      - aggrega intensità (media delle intensità negli snapshot)
      - aggrega aspetti rilevanti
      - calcola pianeti prevalenti
    """
    import calendar
    from datetime import datetime as _dt

    year = anchor_date.year
    month = anchor_date.month
    end_day = calendar.monthrange(year, month)[1]

    ranges = {
        "inizio_mese": (date(year, month, 1), date(year, month, 10)),
        "meta_mese": (date(year, month, 11), date(year, month, 20)),
        "fine_mese": (date(year, month, 21), date(year, month, end_day)),
    }

    # mese successivo
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
    ranges["inizio_mese_successivo"] = (
        date(next_year, next_month, 1),
        date(next_year, next_month, 7),
    )

    buckets: Dict[str, List[SnapshotResult]] = {k: [] for k in ranges.keys()}

    # assegna snapshot al sottoperiodo
    for s in samples:
        d = _dt.fromisoformat(s.datetime_iso).date()
        for key, (d1, d2) in ranges.items():
            if d1 <= d <= d2:
                buckets[key].append(s)
                break

    def _media_intensita(bucket: List[SnapshotResult]) -> Dict[str, float]:
        if not bucket:
            return {a: 0.5 for a in AMBITI}
        acc = {a: 0.0 for a in AMBITI}
        for s in bucket:
            for amb, v in s.metrics.intensities.items():
                acc[amb] += v
        n = len(bucket)
        return {a: acc[a] / n for a in AMBITI}

    out: List[Dict[str, Any]] = []

    for key, bucket in buckets.items():
        d1, d2 = ranges[key]

        if bucket:
            # aspetti rilevanti per sottoperiodo (forma light, con prima_occorrenza)
            aspetti = aggrega_aspetti_rilevanti(bucket)
            aspetti_serial = _serialize_aspetti_aggregati_light(aspetti)

            pianeti_prev = _calcola_pianeti_prevalenti(
                samples=bucket,
                tema_ctx=tema_ctx,
                max_pianeti=3,
            )

        else:
            aspetti_serial = []
            pianeti_prev = []

        out.append(
            {
                "id": key,
                "label": key.replace("_", " ").title(),
                "date_range": {
                    "start": d1.isoformat(),
                    "end": d2.isoformat(),
                },
                "intensita": _media_intensita(bucket),
                "aspetti_rilevanti": aspetti_serial,
                "pianeti_prevalenti": pianeti_prev,
            }
        )

    intensita_mensile = _media_intensita(samples)

    return {
        "intensita_mensile": intensita_mensile,
        "sottoperiodi": out,
    }


# ============================================================================
# FUNZIONE ALTO LIVELLO — pipeline multi-snapshot
# ============================================================================

def run_oroscopo_multi_snapshot(
    periodo: Periodo,
    tier: Tier,
    citta: str,
    data_nascita: str,   # "YYYY-MM-DD"
    ora_nascita: str,    # "HH:MM"
    raw_date: date | datetime,
    include_node: bool = True,
    include_lilith: bool = True,
    filtra_transito: Optional[List[str]] = None,
    filtra_natal: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Funzione orchestratrice:

    - calcola data ancora (anchor) in base al periodo
    - costruisce gli snapshot con oroscopo_sampling
    - calcola il tema natale UNA volta (prepara_tema_natale)
    - costruisce profilo_natale (case angolari, ruler, aspetti stretti)
    - per ogni snapshot:
        * calcola transiti vs tema (API per giornaliero, DF per altri)
        * calcola metriche snapshot (grafici)
        * calcola score_definitivo per ogni aspetto
    - aggrega metriche per grafico
    - aggrega aspetti rilevanti per KB + AI
    - calcola i pianeti di transito prevalenti sul periodo + casa natale
    """
    # 1) data ancora "furba"
    if isinstance(raw_date, datetime):
        raw_d = raw_date.date()
    else:
        raw_d = raw_date
    anchor_date = compute_anchor_date(periodo, raw_d)

    # 2) snapshot (label + datetime)
    snapshots_info = get_sampling_datetimes(
        periodo=periodo,
        tier=tier,
        data_riferimento=anchor_date,
    )

    # 3) tema natale UNA volta (per transiti: ctx "leggero")
    tema_ctx = prepara_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        include_node=include_node,
        include_lilith=include_lilith,
    )

    # 3b) tema natale "completo" per profilo_natale (case, ruler, aspetti stretti)
    tema_completo = costruisci_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        sistema_case="equal",
    )
    profilo_natale = costruisci_profilo_natale(
        natal_houses=tema_completo.get("natal_houses", {}),
        asc_ruler=tema_completo.get("asc_ruler"),
        natal_aspects=tema_completo.get("natal_aspects", []),
    )

    # 4) mapping Periodo -> use_case (daily/weekly/monthly/yearly)
    use_case = _map_periodo_to_use_case(periodo)

    # 5) loop sugli snapshot
    samples: List[SnapshotResult] = []
    for snap in snapshots_info:
        label = snap["label"]
        dt_iso = snap["datetime"]
        dt = datetime.fromisoformat(dt_iso)

        usa_api_transiti = str(periodo) == "giornaliero"

        transiti_data = transiti_vs_tema_precalc(
            tema_ctx=tema_ctx,
            quando=dt,
            include_node=include_node,
            include_lilith=include_lilith,
            filtra_transito=filtra_transito,
            filtra_natal=filtra_natal,
            usa_api_transiti=usa_api_transiti,
        )

        aspetti_list = transiti_data.get("aspetti", [])

        # DEBUG ANNUALE: transiti grezzi su alcuni snapshot chiave
        if str(periodo) == "annuale" and label in ("anno_settimana_1", "anno_settimana_26", "anno_settimana_52"):
            print(f"[DEBUG ANNUALE transiti] label={label}")
            print("  dt =", dt_iso)
            print("  n_aspetti_grezzi =", len(aspetti_list))
            print("  primi 3 aspetti:", aspetti_list[:3])

        # metriche per grafico (ambiti)
        metriche = _calcola_metriche_snapshot(aspetti_list, periodo)

        # aspetti snapshot con score_definitivo (transito * natale)
        aspetti_snap = _build_aspetti_snapshot(
            aspetti=aspetti_list,
            dt=dt,
            use_case=use_case,
            profilo_natale=profilo_natale,
        )

        samples.append(
            SnapshotResult(
                label=label,
                datetime_iso=dt_iso,
                metrics=metriche,
                aspetti=aspetti_snap,
            )
        )

    # 6) aggregazioni
    metriche_grafico = aggrega_metriche_per_grafico(samples)
    aspetti_aggregati = aggrega_aspetti_rilevanti(samples)

    # 7) pianeti di transito prevalenti + casa natale di transito
    pianeti_prevalenti = _calcola_pianeti_prevalenti(
        samples=samples,
        tema_ctx=tema_ctx,
        max_pianeti=3,
    )

    # risultato base (come prima)
    result: Dict[str, Any] = {
        "anchor_date": anchor_date.isoformat(),
        "snapshots_info": snapshots_info,
        "metriche_grafico": metriche_grafico,
        "aspetti_rilevanti": _serialize_aspetti_aggregati_light(aspetti_aggregati),
        "snapshots_raw": [
            {
                "label": s.label,
                "datetime": s.datetime_iso,
                "metrics": {
                    "raw_scores": s.metrics.raw_scores,
                    "intensities": s.metrics.intensities,
                    "n_aspetti": s.metrics.n_aspetti,
                },
                "aspetti": [asdict(a) for a in s.aspetti],
            }
            for s in samples
        ],
        "profilo_natale": profilo_natale,
        "tema_natale": {
            "asc_ruler": tema_completo.get("asc_ruler"),
            "natal_houses": tema_completo.get("natal_houses", {}),
        },
        "pianeti_prevalenti": pianeti_prevalenti,
    }


    # --- NUOVO: se periodo == mensile aggiungiamo 4 sottoperiodi
    if str(periodo) == "mensile":
        mensile_extra = _split_mensile_in_sottoperiodi(
            samples=samples,
            anchor_date=anchor_date,
            tema_ctx=tema_ctx,
        )
        result["mensile_sottoperiodi"] = mensile_extra["sottoperiodi"]
        result["intensita_mensile"] = mensile_extra["intensita_mensile"]

    return result
