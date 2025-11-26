# ============================================================
#  AstroBot - Oroscopo Pipeline (VERBOSE VERSION)
# ============================================================
# Questo file gestisce:
# - Calcolo snapshot multi-periodo (giornaliero, settimanale, mensile, annuale)
# - Raccolta transiti rilevanti per sottoperiodo
# - Fallback automatico: pianeti nelle case → segni → pianeti → case
# - Sottoperiodi free/premium obbligatori (mai vuoti)
# - Driver per AI (payload_ai)
#
# Tutto il codice è stato ristrutturato per garantire:
# - Coerenza tra oroscopo ai vari livelli
# - Zero periodi vuoti
# - Output robusto per l'AI
# ============================================================

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

# Import dai moduli reali (non mock)
from .calcoli import costruisci_tema_natale
from .transiti import calcola_transiti_snapshot
from .transiti_pesatura import pesa_aspetti_per_periodo
from .scoring import normalizza_score
from .config.loader import load_yaml_config

# ============================================================
# CONFIGURAZIONE
# ============================================================

# Configurazioni YAML usate realmente nel progetto:
PESI_CONFIG = load_yaml_config("pesi.yml")             # pesi pianeti per periodo
SNAPSHOTS_CONFIG = load_yaml_config("snapshots.yml")   # definizione snapshot
FILTRI_CONFIG = load_yaml_config("filtri.yml")         # filtri di rilevanza
ORB_CONFIG = load_yaml_config("orb.yml")               # orbi aspetti
GRAFICA_CONFIG = load_yaml_config("grafica.yml")       # (per grafici, se necessario)

# ============================================================
# PERIODI SUPPORTATI
# ============================================================

SUPPORTED_PERIODI = ["giornaliero", "settimanale", "mensile", "annuale"]


# ============================================================
# STRUTTURE DATACLASS
# ============================================================

@dataclass
class SnapshotResult:
    """
    Contiene i risultati per un singolo snapshot temporale:
    - transiti
    - pianeti nelle case
    - segni rilevanti
    """
    quando: datetime
    transiti: List[dict]
    pianeti_case: List[dict]
    segni: List[dict]
    pianeti: List[dict]
    case: List[dict]


@dataclass
class SubPeriodo:
    """
    Ogni sottoperiodo (es: "inizio_mese", "weekend", "mattina", ecc.)
    deve sempre avere drivers e sintesi energetiche.
    """
    id: str
    label: str
    start: datetime
    end: datetime
    drivers: List[dict]
    intensita: Dict[str, float]
    pianeti_prevalenti: List[str]


# ============================================================
# UTILITY BASE
# ============================================================

def _range_date_periodo(periodo: str, anchor_date: date) -> (datetime, datetime):
    """
    Calcola il range temporale principale del periodo richiesto.
    """
    if periodo == "giornaliero":
        start = datetime(anchor_date.year, anchor_date.month, anchor_date.day, 0, 0)
        end = start + timedelta(days=1)

    elif periodo == "settimanale":
        weekday = anchor_date.weekday()
        start = datetime(anchor_date.year, anchor_date.month, anchor_date.day) - timedelta(days=weekday)
        end = start + timedelta(days=7)

    elif periodo == "mensile":
        start = datetime(anchor_date.year, anchor_date.month, 1)
        if anchor_date.month == 12:
            end = datetime(anchor_date.year + 1, 1, 1)
        else:
            end = datetime(anchor_date.year, anchor_date.month + 1, 1)

    elif periodo == "annuale":
        start = datetime(anchor_date.year, 1, 1)
        end = datetime(anchor_date.year + 1, 1, 1)

    else:
        raise ValueError(f"Periodo non supportato: {periodo}")

    return start, end


def _split_sottoperiodi(periodo: str, start: datetime, end: datetime, tier: str) -> List[SubPeriodo]:
    """
    Crea i sottoperiodi in base a:
    - periodo (giornaliero, settimanale...)
    - tier (free/premium)
    """

    sottoperiodi = []

    # Giornaliero --------------------------------------------------------
    if periodo == "giornaliero":
        if tier == "free":
            # solo 1 blocco
            sottoperiodi.append(SubPeriodo(
                id="giorno_intero",
                label="Sintesi del giorno",
                start=start,
                end=end,
                drivers=[],
                intensita={},
                pianeti_prevalenti=[]
            ))
        else:
            # premium → 3 blocchi
            durata = (end - start) / 3
            t1 = start
            t2 = start + durata
            t3 = start + durata * 2

            sottoperiodi.extend([
                SubPeriodo("mattina", "Mattina", t1, t2, [], {}, []),
                SubPeriodo("sera", "Pomeriggio/sera", t2, t3, [], {}, []),
                SubPeriodo("domani", "Prime ore del giorno seguente", t3, end, [], {}, []),
            ])

    # Settimanale --------------------------------------------------------
    elif periodo == "settimanale":
        if tier == "free":
            # settimana / weekend
            mid = start + timedelta(days=5)
            sottoperiodi.extend([
                SubPeriodo("settimana", "Settimana", start, mid, [], {}, []),
                SubPeriodo("weekend", "Weekend", mid, end, [], {}, []),
            ])
        else:
            # premium → inizio, metà, fine
            d = (end - start) / 3
            sottoperiodi.extend([
                SubPeriodo("inizio_settimana", "Inizio settimana", start, start + d, [], {}, []),
                SubPeriodo("meta_settimana", "Metà settimana", start + d, start + 2*d, [], {}, []),
                SubPeriodo("fine_settimana", "Fine settimana", start + 2*d, end, [], {}, []),
            ])

    # Mensile --------------------------------------------------------
    elif periodo == "mensile":
        if tier == "free":
            mid = start + (end - start) / 2
            sottoperiodi.extend([
                SubPeriodo("prima_meta", "Prima metà del mese", start, mid, [], {}, []),
                SubPeriodo("seconda_meta", "Seconda metà del mese", mid, end, [], {}, []),
            ])
        else:
            # premium → 3 decadi + inizio prossimo mese
            d = (end - start) / 3
            sottoperiodi.extend([
                SubPeriodo("decade_1", "Prima decade", start, start + d, [], {}, []),
                SubPeriodo("decade_2", "Seconda decade", start + d, start + 2*d, [], {}, []),
                SubPeriodo("decade_3", "Terza decade", start + 2*d, end, [], {}, []),
                SubPeriodo("inizio_mese_successivo", "Inizio mese successivo", end, end + timedelta(days=3), [], {}, []),
            ])

    # Annuale --------------------------------------------------------
    elif periodo == "annuale":
        # sempre 5 periodi
        dur = (end - start) / 4
        sottoperiodi.extend([
            SubPeriodo("Q1", "Gennaio - Marzo", start, start + dur, [], {}, []),
            SubPeriodo("Q2", "Aprile - Giugno", start + dur, start + dur*2, [], {}, []),
            SubPeriodo("Q3", "Luglio - Settembre", start + dur*2, start + dur*3, [], {}, []),
            SubPeriodo("Q4", "Ottobre - Dicembre", start + dur*3, end, [], {}, []),
            SubPeriodo("sintesi_iniziale", "Transizione nuova annualità", end, end + timedelta(days=15), [], {}, []),
        ])

    return sottoperiodi

# ============================================================
#  DRIVER ENGINE (core della pipeline)
# ============================================================

def _estrai_transiti_rilevanti(snapshot: SnapshotResult, periodo: str) -> List[dict]:
    """
    Prende i transiti dello snapshot e applica:
    - pesatura periodo-specifica
    - filtri di rilevanza (FILTRI_CONFIG)
    - normalizzazione final score
    """
    transiti = snapshot.transiti
    if not transiti:
        return []

    # 1) Pesa aspetti secondo periodo (giorno, settimana, mese, anno)
    trans_pesati = pesa_aspetti_per_periodo(
        transiti,
        periodo=periodo,
        pesi_config=PESI_CONFIG,
        orb_config=ORB_CONFIG
    )

    # 2) Filtra aspetti troppo deboli
    trans_filt = []
    for t in trans_pesati:
        if t.get("score", 0) >= FILTRI_CONFIG["transiti"]["min_score"]:
            trans_filt.append(t)

    # 3) Normalizza
    trans_norm = normalizza_score(trans_filt)

    return trans_norm


def _drivers_from_transiti(transiti: List[dict]) -> List[dict]:
    """
    Converte transiti pesati in driver AI.
    """
    out = []
    for t in transiti:
        out.append({
            "tipo": "transito",
            "pianeta": t.get("pianeta"),
            "aspetto": t.get("aspetto"),
            "bersaglio": t.get("bersaglio"),
            "orb": t.get("orb"),
            "score": t.get("score"),
            "descrizione": f"{t.get('pianeta')} {t.get('aspetto')} {t.get('bersaglio')}"
        })
    return out


def _drivers_from_pianeti_case(pianeti_case: List[dict]) -> List[dict]:
    """
    Driver da: pianeta nella casa.
    """
    out = []
    for p in pianeti_case:
        out.append({
            "tipo": "pianeta_nella_casa",
            "pianeta": p.get("pianeta"),
            "casa": p.get("casa"),
            "descrizione": f"{p.get('pianeta')} in casa {p.get('casa')}"
        })
    return out


def _drivers_from_segni(segni: List[dict]) -> List[dict]:
    """
    Driver da segni rilevanti.
    """
    out = []
    for s in segni:
        out.append({
            "tipo": "segno",
            "segno": s.get("segno"),
            "descrizione": f"Attivazione del segno {s.get('segno')}"
        })
    return out


def _drivers_from_pianeti(pianeti: List[dict]) -> List[dict]:
    """
    Driver da pianeti puri.
    """
    out = []
    for p in pianeti:
        out.append({
            "tipo": "pianeta",
            "pianeta": p.get("pianeta"),
            "descrizione": f"Influsso di {p.get('pianeta')}"
        })
    return out


def _drivers_from_case(case: List[dict]) -> List[dict]:
    """
    Case attivate come fallback finale.
    """
    out = []
    for c in case:
        out.append({
            "tipo": "casa",
            "casa": c.get("casa"),
            "descrizione": f"Attivazione della casa {c.get('casa')}"
        })
    return out


# ============================================================
#  FUNZIONE CENTRALE:
#  Costruisce i drivers PER OGNI SOTTOPERIODO
# ============================================================

def _build_drivers_for_subperiod(
    periodo: str,
    snapshot: SnapshotResult,
    min_drivers: int = 3
) -> List[dict]:
    """
    Genera SEMPRE una lista di driver significativi per l'AI.
    
    Ordine di priorità:
    1. Transiti rilevanti (sempre i più forti)
    2. Pianeti nelle case
    3. Segni rilevanti
    4. Pianeti rilevanti
    5. Case attivate
    """

    drivers: List[dict] = []

    # 1) Transiti rilevanti (top level)
    trans_ril = _estrai_transiti_rilevanti(snapshot, periodo)
    if trans_ril:
        drivers.extend(_drivers_from_transiti(trans_ril))

    # 2) Pianeti nelle case
    if len(drivers) < min_drivers:
        if snapshot.pianeti_case:
            drivers.extend(_drivers_from_pianeti_case(snapshot.pianeti_case))

    # 3) Segni rilevanti
    if len(drivers) < min_drivers:
        if snapshot.segni:
            drivers.extend(_drivers_from_segni(snapshot.segni))

    # 4) Pianeti rilevanti
    if len(drivers) < min_drivers:
        if snapshot.pianeti:
            drivers.extend(_drivers_from_pianeti(snapshot.pianeti))

    # 5) Case attivate
    if len(drivers) < min_drivers:
        if snapshot.case:
            drivers.extend(_drivers_from_case(snapshot.case))

    # 6) Fallback assoluto
    if not drivers:
        drivers.append({
            "tipo": "fallback",
            "descrizione": "Pattern astrologico armonico su base natale"
        })

    return drivers[: max(min_drivers, len(drivers))]


# ============================================================
#  GENERAZIONE SNAPSHOT (punti temporali dentro il periodo)
# ============================================================

def _genera_snapshot_temporali(periodo: str, start: datetime, end: datetime) -> List[datetime]:
    """
    Genera i punti temporali (datetime) dove calcolare i transiti.
    Questi snapshot definiscono il livello di dettaglio del periodo.
    """
    config = SNAPSHOTS_CONFIG.get(periodo, {})
    n_samples = config.get("n_samples", 3)

    if n_samples <= 1:
        return [start]

    delta = (end - start) / (n_samples - 1)
    out = []
    for i in range(n_samples):
        out.append(start + delta * i)

    return out


def _costruisci_snapshot(ctx: dict, quando: datetime) -> SnapshotResult:
    """
    Costruisce lo snapshot per un 'quando' specifico:
    - transiti tra pianeti transito e natali
    - pianeti nelle case
    - segni attivati
    - pianeti rilevanti
    - case rilevanti
    """

    trans = calcola_transiti_snapshot(
        tema_ctx=ctx["tema"],
        quando=quando,
        filtri=FILTRI_CONFIG,
        orb_config=ORB_CONFIG
    )

    # Pianeti nelle case
    pianeti_case = [{
        "pianeta": p["pianeta"],
        "casa": p["casa"]
    } for p in trans.get("pianeti_case", [])]

    # Segni attivi
    segni = [{
        "segno": s["segno"],
        "peso": s.get("peso", 1.0)
    } for s in trans.get("segni_attivi", [])]

    # Pianeti attivi
    pianeti = [{
        "pianeta": p["pianeta"],
        "peso": p.get("peso", 1.0)
    } for p in trans.get("pianeti_attivi", [])]

    # Case attive
    case = [{
        "casa": c["casa"],
        "peso": c.get("peso", 1.0)
    } for c in trans.get("case_attive", [])]

    return SnapshotResult(
        quando=quando,
        transiti=trans.get("aspetti_transito_natale", []),
        pianeti_case=pianeti_case,
        segni=segni,
        pianeti=pianeti,
        case=case
    )


# ============================================================
#  AGGREGAZIONE SNAPSHOT IN SOTTOPERIODO
# ============================================================

def _snapshot_in_range(snapshot: SnapshotResult, start: datetime, end: datetime) -> bool:
    """Verifica se snapshot appartiene al sottoperiodo."""
    return start <= snapshot.quando < end


def _aggregazione_sottoperiodo(periodo: str, sub: SubPeriodo, snapshots: List[SnapshotResult]) -> SubPeriodo:
    """
    Per ogni sottoperiodo:
    - raccoglie snapshot contenuti nel range
    - aggrega drivers
    - calcola intensità
    """

    # Snapshot rilevanti
    snap_rilevanti = [s for s in snapshots if _snapshot_in_range(s, sub.start, sub.end)]
    if not snap_rilevanti:
        # fallback estremo: snapshot centrale del periodo
        snap_rilevanti = [snapshots[len(snapshots) // 2]]

    # GENERAZIONE DRIVERS -----------------------------------
    drivers_finali = []
    for snap in snap_rilevanti:
        drivers_finali.extend(
            _build_drivers_for_subperiod(periodo, snap, min_drivers=3)
        )

    # --------------------------------------------------------
    #  CALCOLO INTENSITA'
    # --------------------------------------------------------

    def _estrai_scores(snapshot_list: List[SnapshotResult]):
        vals = []
        for s in snapshot_list:
            for tr in s.transiti:
                vals.append(tr.get("score", 0))
        return vals or [0]

    scores = _estrai_scores(snap_rilevanti)
    intensita_media = sum(scores) / len(scores) if scores else 0.0

    # intensità per dimensioni AI
    intensita_block = {
        "energy": round(intensita_media, 4),
        "emotions": round(intensita_media * 0.9, 4),
        "relationships": round(intensita_media * 0.85, 4),
        "work": round(intensita_media * 0.8, 4),
        "luck": round(intensita_media * 1.1, 4),
    }

    # --------------------------------------------------------
    #  CALCOLO PIANETI PREVALENTI
    # --------------------------------------------------------

    pianeti_counter = {}
    for snap in snap_rilevanti:
        for tr in snap.transiti:
            p = tr.get("pianeta")
            if p:
                pianeti_counter[p] = pianeti_counter.get(p, 0) + tr.get("score", 1)

    pianeti_prevalenti = sorted(
        pianeti_counter.keys(),
        key=lambda x: pianeti_counter[x],
        reverse=True
    )[:5]

    # Aggiorna sottoperiodo ---------------------------------
    sub.drivers = drivers_finali
    sub.intensita = intensita_block
    sub.pianeti_prevalenti = pianeti_prevalenti

    return sub


# ============================================================================
# ORCHESTRAZIONE COMPLETA DEL PERIODO
# ============================================================================
def _build_periodo_output(
    periodo: Periodo,
    tier: Tier,
    ctx: dict,
    anchor_start: datetime,
    anchor_end: datetime,
) -> Dict[str, Any]:
    """
    Orchestrazione completa:
    - genera snapshot reali del periodo (3–7 punti)
    - genera sottoperiodi (in base a periodo + tier)
    - popola ciascun sottoperiodo con:
        - drivers
        - pianeti prevalenti
        - intensità
    - aggrega aspetti per KB + AI
    """

    # --------------------------------------------------------
    # 1) SNAPSHOT
    # --------------------------------------------------------
    dt_list = get_sampling_datetimes(periodo, anchor_start, anchor_end)
    if not dt_list:
        # fallback estremo: un solo punto a metà
        mid = anchor_start + (anchor_end - anchor_start) / 2
        dt_list = [mid]

    # Prepara contesto tema natale
    tema_ctx = ctx["tema"]
    profilo_natale = ctx["profilo_natale"]
    use_case = _map_periodo_to_use_case(periodo)

    snapshots: List[SnapshotResult] = []

    for i, dt in enumerate(dt_list):
        trans = transiti_vs_tema_precalc(
            tema_ctx=tema_ctx,
            quando=dt,
            use_case=use_case,
        )

        # step 1: conversione aspetti -> AspettoSnapshot (con score_definitivo)
        aspetti_snap = _build_aspetti_snapshot(
            trans.get("aspetti", []),
            dt,
            use_case,
            profilo_natale,
        )

        # step 2: metriche snapshot (scores + intensità)
        metrics = _calcola_metriche_snapshot(
            trans.get("aspetti", []),
            periodo,
        )

        snapshots.append(
            SnapshotResult(
                label=f"{periodo}_{i+1}",
                datetime_iso=dt.isoformat(timespec="minutes"),
                metrics=metrics,
                aspetti=aspetti_snap,
            )
        )

    # Se anche qui non abbiamo snapshot → fallback
    if not snapshots:
        snapshots = [
            SnapshotResult(
                label="fallback",
                datetime_iso=anchor_start.isoformat(),
                metrics=SnapshotMetrics(
                    raw_scores={a: 0 for a in AMBITI},
                    intensities={a: 0.5 for a in AMBITI},
                    n_aspetti=0,
                ),
                aspetti=[],
            )
        ]

    # --------------------------------------------------------
    # 2) COSTRUISCI SOTTOPERIODI
    # --------------------------------------------------------
    sottoperiodi = build_sottoperiodi(periodo, tier, anchor_start, anchor_end)
    if not sottoperiodi:
        # fallback: un unico mega periodo
        sottoperiodi = [
            SubPeriodo(
                id="periodo_intero",
                label=str(periodo),
                start=anchor_start,
                end=anchor_end,
            )
        ]

    # --------------------------------------------------------
    # 3) AGGREGAZIONE — PER OGNI SOTTOPERIODO
    # --------------------------------------------------------
    for idx, sp in enumerate(sottoperiodi):
        sottoperiodi[idx] = _aggregazione_sottoperiodo(periodo, sp, snapshots)

    # --------------------------------------------------------
    # 4) ASPETTI RILEVANTI GLOBALI (per KB+AI)
    # --------------------------------------------------------
    aspetti_rilevanti = aggrega_aspetti_rilevanti(
        snapshots,
        max_aspetti=12 if tier == "premium" else 5,
    )

    # --------------------------------------------------------
    # 5) METRICHE GRAFICO MULTI-SNAPSHOT
    # --------------------------------------------------------
    metriche_grafico = aggrega_metriche_per_grafico(snapshots)

    # --------------------------------------------------------
    # 6) COSTRUZIONE OUTPUT FINALE DEL PERIODO
    # --------------------------------------------------------
    out = {
        "label": f"Oroscopo {periodo}",
        "date_range": {
            "start": anchor_start.date().isoformat(),
            "end": anchor_end.date().isoformat(),
        },
        "sottoperiodi": [sp.to_dict() for sp in sottoperiodi],
        "aspetti_rilevanti": aspetti_rilevanti,
        "metriche_grafico": metriche_grafico,
    }

    # Se non ci sono intensità → fallback
    for sp in out["sottoperiodi"]:
        if not sp.get("intensita"):
            sp["intensita"] = {a: 0.5 for a in AMBITI}

    return out
# ============================================================================
# RUN COMPLETO MULTI-SNAPSHOT PER TUTTI I PERIODI
# ============================================================================
def run_oroscopo_multi_snapshot(
    periodo: Periodo | str,
    tier: Tier | str,
    citta: str,
    data_nascita: str,
    ora_nascita: str,
    raw_date: date,
    include_node: bool = True,
    include_lilith: bool = True,
) -> Dict[str, Any]:
    """
    Runner completo usato dal backend (chatbot-test) e dai test Groq.

    OUTPUT CONTIENE:
    - meta
    - tema natale completo
    - profilo natale
    - periodi → con sottoperiodi, aspetti rilevanti, metriche grafiche
    - dati necessari per KB (non vuoto)
    - nessun periodo mai vuoto (fallback multilivello)
    """

    # Normalizzazione input
    periodo = Periodo(periodo) if isinstance(periodo, str) else periodo
    tier = Tier(tier) if isinstance(tier, str) else tier

    # ----------------------------------------------------------------------
    # 1) COSTRUZIONE TEMA NATALE + PROFILO
    # ----------------------------------------------------------------------
    tema_natale = costruisci_tema_natale(
        citta=citta,
        data_nascita=data_nascita,
        ora_nascita=ora_nascita,
        sistema_case="equal",
        include_node=include_node,
        include_lilith=include_lilith,
    )

    profilo_natale = calcola_profilo_natale(tema_natale)

    ctx = {
        "tema": tema_natale,
        "profilo_natale": profilo_natale,
        "kb_hooks": {},
    }

    # ----------------------------------------------------------------------
    # 2) INTEGRAZIONE KNOWLEDGE BASE (always non-empty)
    # ----------------------------------------------------------------------
    try:
        ctx["kb_hooks"] = fetch_kb_hooks(
            tema_natale=tema_natale,
            profilo_natale=profilo_natale,
            periodo=periodo,
            tier=tier,
        )
    except Exception as e:
        # fallback: KB vuota minima (mai None)
        ctx["kb_hooks"] = {
            "case": [],
            "segni": [],
            "pianeti": [],
            "pianeti_case": [],
            "transiti": [],
        }

    # ----------------------------------------------------------------------
    # 3) COSTRUZIONE RANGE TEMPORALE DEL PERIODO
    # ----------------------------------------------------------------------
    rango = get_periodo_range(periodo, raw_date)
    start = rango["start"]
    end = rango["end"]

    # ----------------------------------------------------------------------
    # 4) ORCHESTRAZIONE COMPLETA (snapshot → sottoperiodi → AI-ready)
    # ----------------------------------------------------------------------
    periodo_output = _build_periodo_output(
        periodo=periodo,
        tier=tier,
        ctx=ctx,
        anchor_start=start,
        anchor_end=end,
    )

    # ----------------------------------------------------------------------
    # 5) COSTRUZIONE RETURN-FINALE
    # ----------------------------------------------------------------------
    out = {
        "status": "ok",
        "periodo": str(periodo),
        "tier": str(tier),
        "meta": {
            "citta": citta,
            "data_nascita": data_nascita,
            "ora_nascita": ora_nascita,
            "range": {"start": start.isoformat(), "end": end.isoformat()},
        },
        "tema_natale": tema_natale,
        "profilo_natale": profilo_natale,
        "kb_hooks": ctx["kb_hooks"],
        "snapshots": [],   # se vuoi esportarli anche verso l'esterno
        "periodo_output": periodo_output,
    }

    return out



