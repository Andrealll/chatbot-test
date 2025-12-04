# chatbot_test/routes_oroscopo.py

import logging
from typing import Any, Dict, Optional, Tuple, List, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Depends
from pydantic import BaseModel, Field, validator

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar
import time

from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai
from astrobot_core.ai_oroscopo_claude import call_claude_oroscopo_ai

# === IMPORT PER AUTH + CREDITI (COME SINASTRIA) ===
from auth import get_current_user, UserContext
from astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    # senza prefix qui: verrà montato dal main con prefix="/oroscopo_ai"
    tags=["oroscopo_ai"],
)

# ============================================================
# Costanti / tipi
# ============================================================

Periodo = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]
Engine = Literal["ai", "new", "legacy"]  # ai = pipeline completa (Claude), new = numerico

OROSCOPO_FEATURE_KEY = "oroscopo_ai"

# Costi per oroscopo premium AI (parametrici, per periodo)
OROSCOPO_FEATURE_COSTS: Dict[Periodo, int] = {
    "daily": 1,
    "weekly": 2,
    "monthly": 3,
    "yearly": 5,
}

# Mappa periodi inglesi (API) → italiani (core AstroBot)
PERIODO_EN_TO_IT = {
    "daily": "giornaliero",
    "weekly": "settimanale",
    "monthly": "mensile",
    "yearly": "annuale",
}

# Mappa periodi italiani → codici usati dal payload AI
PERIODO_IT_TO_CODE = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}


# ============================================================
# MODELLI INPUT / OUTPUT
# ============================================================

class OroscopoBaseInput(BaseModel):
    """
    Input comune a tutti i periodi.
    Questa struttura è quella che userai sia da DYANA che da Typebot.
    """
    citta: str = Field(..., description="Città di nascita (es. 'Napoli')")
    data: str = Field(..., description="Data di nascita in formato YYYY-MM-DD")
    ora: Optional[str] = Field(
        None,
        description="Ora di nascita in formato HH:MM (24h). Obbligatoria se vuoi l'ascendente preciso."
    )
    nome: Optional[str] = Field(None, description="Nome della persona (opzionale, usato solo nel testo)")
    email: Optional[str] = None
    domanda: Optional[str] = Field(
        None,
        description="Eventuale domanda specifica da passare all'AI."
    )
    tier: Optional[Tier] = Field(
        None,
        description="free / premium. Se non passato, verrà determinato dal token/JWT."
    )

    @validator("data")
    def _validate_data(cls, v: str) -> str:
        # Controllo minimale sul formato, senza usare dateutil
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError("data deve essere in formato YYYY-MM-DD")
        return v

    @validator("ora")
    def _validate_ora(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("ora deve essere in formato HH:MM")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("ora deve contenere solo numeri (HH:MM)")
        return v


class OroscopoResponse(BaseModel):
    """
    Response 'macro' /oroscopo.
    - engine: "ai" quando usi la pipeline completa con Claude
    - engine: "new" quando usi solo il motore numerico (multi-snapshot) senza AI
    """
    status: Literal["ok", "error"]
    scope: Periodo
    engine: Engine
    input: Dict[str, Any]

    # Risultato del motore numerico (multi-snapshot, intensità, grafico, ecc.)
    engine_result: Optional[Dict[str, Any]] = None

    # Payload per la AI (quello che passa a Claude)
    payload_ai: Optional[Dict[str, Any]] = None

    # Output di Claude (oroscopo strutturato / testo)
    oroscopo_ai: Optional[Dict[str, Any]] = None

    # In caso di errore
    error: Optional[str] = None

    # Blocco billing allineato a sinastria: tier, mode, cost_paid_credits, cost_free_credits, remaining_credits
    billing: Optional[Dict[str, Any]] = None


# ============================================================
# Helpers interni
# ============================================================

def _normalize_period(periodo: str) -> Periodo:
    """
    Normalizza alias tipo "giornaliero" -> "daily", ecc.
    Se non riconosciuto, tira 400.
    """
    p = periodo.lower().strip()

    mapping = {
        "daily": "daily",
        "giornaliero": "daily",
        "giornaliera": "daily",
        "day": "daily",

        "weekly": "weekly",
        "settimanale": "weekly",
        "week": "weekly",

        "monthly": "monthly",
        "mensile": "monthly",
        "month": "monthly",

        "yearly": "yearly",
        "annuale": "yearly",
        "anno": "yearly",
    }

    if p not in mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Periodo non valido: '{periodo}'. Usa uno tra: daily, weekly, monthly, yearly."
        )

    return mapping[p]  # type: ignore[return-value]


def _resolve_tier(request: Request, body_tier: Optional[Tier]) -> Tier:
    """
    Regola unica per stabilire il tier:
    1) Se da JWT / cookie / whatever (da implementare)
    2) altrimenti fallback su body.tier
    3) altrimenti 'free'
    """
    # TODO: collega qui la tua logica reale di risoluzione tier dal JWT
    tier_from_token: Optional[Tier] = None  # placeholder

    if tier_from_token is not None:
        return tier_from_token
    if body_tier is not None:
        return body_tier
    return "free"


def _resolve_engine(x_engine: Optional[str]) -> Engine:
    """
    Interpreta l'header X-Engine:
    - "ai"      → usa pipeline completa (motore numerico + payload_ai + Claude)
    - "new"     → solo motore numerico (multi-snapshot), senza AI
    - "legacy"  → eventuale vecchio motore (se vorrai reintrodurlo)
    - None      → default: "ai"
    """
    if x_engine is None or x_engine.strip() == "":
        return "ai"

    value = x_engine.lower().strip()
    if value not in ("ai", "new", "legacy"):
        raise HTTPException(
            status_code=400,
            detail="X-Engine deve essere uno tra: ai, new, legacy"
        )
    return value  # type: ignore[return-value]


# ============================================================
# STRUTTURA PERSONA (per riusare la logica del test)
# ============================================================

@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str
    periodo: str   # "giornaliero" | "settimanale" | "mensile" | "annuale"
    tier: str      # "free" | "premium"


# ============================================================
# HELPER ORB/DATE UTILIZZATI NELLA PIPE OROSCOPO
# ============================================================

def _safe_iso_to_dt(s: Optional[str], today: Optional[date] = None) -> datetime:
    if today is None:
        today = date.today()
    if not s:
        return datetime.combine(today, datetime.min.time())
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.combine(today, datetime.min.time())


def generate_subperiods(periodo: str, tier: str, date_range: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Copia della logica del test:
    - giornaliero free: nessun sottoperiodo
    - giornaliero premium: mattina, pomeriggio, domani
    - settimanale free: settimana, weekend
    - settimanale premium: inizio settimana, metà settimana, weekend
    - mensile free: nessun sottoperiodo
    - mensile premium: 3 decadi
    - annuale free: nessun sottoperiodo
    - annuale premium: 4 stagioni
    """
    today = date.today()
    periodo = (periodo or "").lower()
    tier = (tier or "").lower()
    out: List[Dict[str, Any]] = []

    start_dt = _safe_iso_to_dt(date_range.get("start"), today=today)
    end_dt = _safe_iso_to_dt(date_range.get("end"), today=today)

    # --- GIORNALIERO ---
    if periodo.startswith("giorn"):
        if tier == "premium":
            domani = start_dt + timedelta(days=1)
            out = [
                {"id": "mattina", "label": "Mattina", "datetime": start_dt.replace(hour=9).isoformat()},
                {"id": "pomeriggio", "label": "Pomeriggio", "datetime": start_dt.replace(hour=15).isoformat()},
                {"id": "domani", "label": "Domani", "datetime": domani.isoformat()},
            ]
        return out

    # --- SETTIMANALE ---
    if periodo.startswith("settim"):
        weekend_start = start_dt + timedelta(days=5)

        if tier == "premium":
            out = [
                {
                    "id": "inizio_settimana",
                    "label": "Inizio settimana",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": (start_dt + timedelta(days=2)).isoformat(),
                    },
                },
                {
                    "id": "meta_settimana",
                    "label": "Metà settimana",
                    "range": {
                        "start": (start_dt + timedelta(days=3)).isoformat(),
                        "end": (start_dt + timedelta(days=4)).isoformat(),
                    },
                },
                {
                    "id": "weekend",
                    "label": "Weekend",
                    "range": {
                        "start": weekend_start.isoformat(),
                        "end": (weekend_start + timedelta(days=1)).isoformat(),
                    },
                },
            ]
        else:
            out = [
                {
                    "id": "settimana",
                    "label": "Settimana intera",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": weekend_start.isoformat(),
                    },
                },
                {
                    "id": "weekend",
                    "label": "Weekend",
                    "range": {
                        "start": weekend_start.isoformat(),
                        "end": (weekend_start + timedelta(days=1)).isoformat(),
                    },
                },
            ]
        return out

    # --- MENSILE ---
    if periodo.startswith("mens"):
        if tier == "premium":
            out = [
                {
                    "id": "prima_decade",
                    "label": "1–10 del mese",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": (start_dt + timedelta(days=9)).isoformat(),
                    },
                },
                {
                    "id": "seconda_decade",
                    "label": "11–20 del mese",
                    "range": {
                        "start": (start_dt + timedelta(days=10)).isoformat(),
                        "end": (start_dt + timedelta(days=19)).isoformat(),
                    },
                },
                {
                    "id": "terza_decade",
                    "label": "21–fine mese",
                    "range": {
                        "start": (start_dt + timedelta(days=20)).isoformat(),
                        "end": end_dt.isoformat(),
                    },
                },
            ]
        return out

    # --- ANNUALE ---
    if periodo.startswith("ann"):
        if tier == "premium":
            year = start_dt.year
            out = [
                {"id": "inverno",   "label": "Inverno",   "range": {"start": f"{year}-01-01", "end": f"{year}-03-20"}},
                {"id": "primavera", "label": "Primavera", "range": {"start": f"{year}-03-21", "end": f"{year}-06-20"}},
                {"id": "estate",    "label": "Estate",    "range": {"start": f"{year}-06-21", "end": f"{year}-09-22"}},
                {"id": "autunno",   "label": "Autunno",   "range": {"start": f"{year}-09-23", "end": f"{year}-12-31"}},
            ]
        return out

    return out


def _aggregate_bucket(label: str, samples: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not samples:
        return None

    today = date.today()
    dts: List[datetime] = []
    for s in samples:
        dt_raw = s.get("datetime")
        dts.append(_safe_iso_to_dt(dt_raw if isinstance(dt_raw, str) else None, today=today))

    ts_avg = sum(dt.timestamp() for dt in dts) / len(dts)
    dt_mid = datetime.fromtimestamp(ts_avg)

    first_metrics = (samples[0].get("metrics") or {})
    raw_scores0 = first_metrics.get("raw_scores") or {}
    ambiti = list(raw_scores0.keys())

    agg_raw: Dict[str, float] = {}
    agg_int: Dict[str, float] = {}

    for amb in ambiti:
        vals_raw = []
        vals_int = []
        for s in samples:
            m = s.get("metrics") or {}
            rs = (m.get("raw_scores") or {}).get(amb)
            it = (m.get("intensities") or {}).get(amb)
            if rs is not None:
                vals_raw.append(rs)
            if it is not None:
                vals_int.append(it)
        if vals_raw:
            agg_raw[amb] = sum(vals_raw) / len(vals_raw)
        if vals_int:
            agg_int[amb] = sum(vals_int) / len(vals_int)

    n_vals = []
    for s in samples:
        m = s.get("metrics") or {}
        n = m.get("n_aspetti")
        if n is not None:
            n_vals.append(n)
    n_aspetti = int(round(sum(n_vals) / len(n_vals))) if n_vals else None

    metrics_out: Dict[str, Any] = {
        "raw_scores": agg_raw,
        "intensities": agg_int,
    }
    if n_aspetti is not None:
        metrics_out["n_aspetti"] = n_aspetti

    return {
        "label": label,
        "datetime": dt_mid.isoformat(timespec="seconds"),
        "metrics": metrics_out,
    }


def _aggregate_annual_samples(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {"samples": []}

    today = date.today()
    year = _safe_iso_to_dt(samples[0].get("datetime"), today=today).year

    def _dt(d: date) -> datetime:
        return datetime.combine(d, datetime.min.time()).replace(hour=12)

    spring = _dt(date(year, 3, 21))
    summer = _dt(date(year, 6, 21))
    autumn = _dt(date(year, 9, 23))

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "inverno": [],
        "primavera": [],
        "estate": [],
        "autunno": [],
    }

    for s in samples:
        t = _safe_iso_to_dt(s.get("datetime"), today=today)
        if t < spring:
            buckets["inverno"].append(s)
        elif t < summer:
            buckets["primavera"].append(s)
        elif t < autumn:
            buckets["estate"].append(s)
        else:
            buckets["autunno"].append(s)

    labels = {
        "inverno": "Inverno",
        "primavera": "Primavera",
        "estate": "Estate",
        "autunno": "Autunno",
    }

    out_samples: List[Dict[str, Any]] = []
    for key in ["inverno", "primavera", "estate", "autunno"]:
        bucket_sample = _aggregate_bucket(labels[key], buckets[key])
        if bucket_sample is not None:
            out_samples.append(bucket_sample)

    return {"samples": out_samples}


def _aggregate_monthly_samples(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {"samples": []}

    today = date.today()
    dt0 = _safe_iso_to_dt(samples[0].get("datetime"), today=today)
    year, month = dt0.year, dt0.month
    _, last_day = calendar.monthrange(year, month)  # non usato direttamente, ma coerente

    buckets = {
        "prima_decade": [],
        "seconda_decade": [],
        "terza_decade": [],
    }

    for s in samples:
        t = _safe_iso_to_dt(s.get("datetime"), today=today)
        day = t.day
        if day <= 10:
            buckets["prima_decade"].append(s)
        elif day <= 20:
            buckets["seconda_decade"].append(s)
        else:
            buckets["terza_decade"].append(s)

    labels = {
        "prima_decade": "1–10 del mese",
        "seconda_decade": "11–20 del mese",
        "terza_decade": "21–fine mese",
    }

    out_samples: List[Dict[str, Any]] = []
    for key in ["prima_decade", "seconda_decade", "terza_decade"]:
        bucket_sample = _aggregate_bucket(labels[key], buckets[key])
        if bucket_sample is not None:
            out_samples.append(bucket_sample)

    return {"samples": out_samples}


def _aggregate_weekly_samples(samples: List[Dict[str, Any]], tier: str) -> Dict[str, Any]:
    if not samples:
        return {"samples": []}

    samples_sorted = sorted(samples, key=lambda s: _safe_iso_to_dt(s.get("datetime")))
    n = len(samples_sorted)

    tier_norm = (tier or "").lower()
    if tier_norm == "premium":
        n_buckets = 3
        label_map = {0: "Inizio settimana", 1: "Metà settimana", 2: "Weekend"}
    else:
        n_buckets = 2
        label_map = {0: "Settimana", 1: "Weekend"}

    buckets: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(n_buckets)}

    for idx, s in enumerate(samples_sorted):
        b_idx = min(n_buckets - 1, int(idx * n_buckets / n))
        buckets[b_idx].append(s)

    out_samples: List[Dict[str, Any]] = []
    for i in range(n_buckets):
        bucket_sample = _aggregate_bucket(label_map[i], buckets[i])
        if bucket_sample is not None:
            out_samples.append(bucket_sample)

    return {"samples": out_samples}


def _aggregate_metriche_for_period(metriche_grafico: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    if not metriche_grafico:
        return metriche_grafico

    samples = metriche_grafico.get("samples") or []
    if not samples:
        return metriche_grafico

    periodo = persona.periodo.lower()
    tier = persona.tier.lower()

    if periodo.startswith("ann"):
        return _aggregate_annual_samples(samples)
    if periodo.startswith("mens"):
        return _aggregate_monthly_samples(samples)
    if periodo.startswith("settim"):
        return _aggregate_weekly_samples(samples, tier)

    return metriche_grafico


def _pick_period_block(pipe: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    # 1) Vecchio stile
    po = pipe.get("periodo_output")
    if isinstance(po, dict) and ("date_range" in po or "aspetti_rilevanti" in po):
        return po

    # 2) Strutture periodi / periodi_multi
    periodi = pipe.get("periodi") or pipe.get("periodi_multi")
    if isinstance(periodi, dict) and periodi:
        key_ita = persona.periodo
        key_code = PERIODO_IT_TO_CODE.get(persona.periodo, persona.periodo)

        for k in (key_ita, key_code):
            if k in periodi and isinstance(periodi[k], dict):
                return periodi[k]

    # 3) Ricerca ricorsiva generica
    def _search(d: Any) -> Optional[Dict[str, Any]]:
        if isinstance(d, dict):
            keys = set(d.keys())
            if "date_range" in keys or "aspetti_rilevanti" in keys or "metriche_grafico" in keys:
                return d
            for v in d.values():
                found = _search(v)
                if found:
                    return found
        elif isinstance(d, list):
            for item in d:
                found = _search(item)
                if found:
                    return found
        return None

    found = _search(pipe)
    return found or {}


def _cleanup_period_block_for_ai(period_block: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    periodo = persona.periodo.lower()
    cleaned = dict(period_block)

    # togliamo quincunx ovunque
    aspetti = list(cleaned.get("aspetti_rilevanti") or [])
    new_aspetti = []
    for a in aspetti:
        tipo = (a.get("aspetto") or a.get("tipo") or "").lower()
        if "quincun" in tipo:
            continue
        new_aspetti.append(a)
    cleaned["aspetti_rilevanti"] = new_aspetti

    # annuale: togliamo la Luna dai pianeti_prevalenti
    pian_prev = list(cleaned.get("pianeti_prevalenti") or [])
    if periodo.startswith("ann"):
        new_p = []
        for p in pian_prev:
            nome = (p.get("pianeta") or p.get("nome") or "")
            if nome == "Luna":
                continue
            new_p.append(p)
        cleaned["pianeti_prevalenti"] = new_p

    return cleaned


def build_debug_kb_hooks(
    period_block: Dict[str, Any],
    tema: Dict[str, Any],
    profilo_natale: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
    pianeti_prev = period_block.get("pianeti_prevalenti") or []
    aspetti = period_block.get("aspetti_rilevanti") or []

    lines: List[str] = []

    lines.append(f"# Contesto astrologico per {persona.nome}")
    lines.append(f"Periodo: {persona.periodo} — Tier: {persona.tier}")
    lines.append("")

    if pianeti_prev:
        lines.append("## Pianeti prevalenti nel periodo")
        for p in pianeti_prev:
            nome = p.get("pianeta") or p.get("nome") or "?"
            score = p.get("score_periodo")
            casa = p.get("casa_natale_transito")
            prima = p.get("prima_occorrenza")
            parts = [f"- {nome}"]
            if casa is not None:
                parts.append(f"in casa {casa}")
            if score is not None:
                parts.append(f"(peso periodo: {round(score, 3)})")
            if prima:
                parts.append(f"prima attivazione: {prima}")
            lines.append(" ".join(parts))
        lines.append("")

    if aspetti:
        lines.append("## Aspetti chiave del periodo")
        for a in aspetti:
            tr = a.get("pianeta_transito") or "?"
            nat = a.get("pianeta_natale") or "?"
            asp = a.get("aspetto") or a.get("tipo") or "?"
            n_snap = a.get("n_snapshot")
            score_rel = a.get("score_rilevanza")
            riga = f"- {tr} {asp} {nat}"
            if n_snap is not None:
                riga += f" (presente in {n_snap} snapshot)"
            if score_rel is not None:
                riga += f", rilevanza: {round(score_rel, 3)}"
            lines.append(riga)

        lines.append("")
        lines.append("### Dettagli delle occorrenze principali")
        for a in aspetti:
            tr = a.get("pianeta_transito") or "?"
            nat = a.get("pianeta_natale") or "?"
            asp = a.get("aspetto") or a.get("tipo") or "?"
            occs = a.get("occorrenze") or []
            for occ in occs:
                dt = occ.get("datetime")
                orb = occ.get("orb")
                score_def = occ.get("score_definitivo")
                lines.append(
                    f"- {dt}: {tr} {asp} {nat} "
                    f"(orb≈{round(orb, 3) if orb is not None else '?'}; "
                    f"score={round(score_def, 3) if score_def is not None else '?'})"
                )
        lines.append("")

    if profilo_natale:
        lines.append("## Profilo natale sintetico (pesi pianeti)")
        for nome, peso in sorted(profilo_natale.items(), key=lambda x: -x[1]):
            lines.append(f"- {nome}: peso {peso}")
        lines.append("")

    combined_md = "\n".join(lines) if lines else ""

    return {
        "pianeti_prevalenti": pianeti_prev,
        "aspetti_rilevanti": aspetti,
        "combined_markdown": combined_md,
    }


def build_oroscopo_struct_from_pipe(pipe: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    tema = pipe.get("tema_natale") or {}
    profilo_natale = pipe.get("profilo_natale") or {}

    periodo_output = _pick_period_block(pipe, persona) or {}
    date_range = periodo_output.get("date_range") or {}
    sottoperiodi = generate_subperiods(persona.periodo, persona.tier, date_range)

    metriche_orig = periodo_output.get("metriche_grafico", {}) or {}
    metriche_agg = _aggregate_metriche_for_period(metriche_orig, persona)

    period_block_raw = {
        "label": periodo_output.get("label"),
        "date_range": date_range,
        "sottoperiodi": sottoperiodi,
        "aspetti_rilevanti": periodo_output.get("aspetti_rilevanti", []),
        "metriche_grafico": metriche_agg,
        "pianeti_prevalenti": periodo_output.get("pianeti_prevalenti", []),
    }

    period_block = _cleanup_period_block_for_ai(period_block_raw, persona)

    kb_hooks = build_debug_kb_hooks(
        period_block=period_block,
        tema=tema,
        profilo_natale=profilo_natale,
        persona=persona,
    )

    oroscopo_struct = {
        "meta": {
            "nome": persona.nome,
            "citta": persona.citta,
            "data_nascita": persona.data,
            "ora_nascita": persona.ora,
            "tier": persona.tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema,
        "profilo_natale": profilo_natale,
        "kb_hooks": kb_hooks,
        "periodi": {
            persona.periodo: period_block
        },
    }

    return oroscopo_struct


def _build_payload_ai(
    scope: Periodo,
    tier: Tier,
    engine_result: Dict[str, Any],
    data_input: OroscopoBaseInput,
) -> Dict[str, Any]:
    """
    Costruisce il payload_ai da passare a Claude usando:
    - pipe = output di run_oroscopo_multi_snapshot
    - oroscopo_struct = stessa logica del test end-to-end
    - build_oroscopo_payload_ai di astrobot_core
    """
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] scope=%s tier=%s nome=%s",
        scope, tier, data_input.nome
    )

    pipe = engine_result.get("pipe") or {}
    if not pipe:
        raise RuntimeError("engine_result.pipe mancante: assicurati che _run_oroscopo_engine_new sia stato chiamato correttamente.")

    periodo_ita = PERIODO_EN_TO_IT[scope]
    persona = Persona(
        nome=data_input.nome or "Anonimo",
        citta=data_input.citta,
        data=data_input.data,
        ora=data_input.ora or "00:00",
        periodo=periodo_ita,
        tier=tier,
    )

    # 1) oroscopo_struct dalla pipe (stessa logica del test)
    oroscopo_struct = build_oroscopo_struct_from_pipe(pipe, persona)

    # 2) period_code in stile "daily"/"weekly"/...
    period_code = PERIODO_IT_TO_CODE.get(periodo_ita, scope)

    # 3) payload AI usando il modulo ufficiale (prompt incluso lì)
    payload_ai = build_oroscopo_payload_ai(
        oroscopo_struct=oroscopo_struct,
        lang="it",
        period_code=period_code,
    )

    return payload_ai


def _call_oroscopo_ai_claude(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    """
    Delego tutto al client in astrobot-core.
    """
    return call_claude_oroscopo_ai(payload_ai)


def _run_oroscopo_engine_new(
    scope: Periodo,
    tier: Tier,
    data_input: OroscopoBaseInput,
) -> Dict[str, Any]:
    """
    Wrapper per il motore numerico multi-snapshot di AstroBot.
    Usa run_oroscopo_multi_snapshot da astrobot_core.
    """
    periodo_ita = PERIODO_EN_TO_IT[scope]  # es. "daily" -> "giornaliero"

    logger.info(
        "[OROSCOPO][ENGINE_NEW] scope=%s (ita=%s) tier=%s citta=%s data=%s",
        scope, periodo_ita, tier, data_input.citta, data_input.data
    )

    pipe = run_oroscopo_multi_snapshot(
        periodo=periodo_ita,
        tier=tier,
        citta=data_input.citta,
        data_nascita=data_input.data,
        ora_nascita=data_input.ora,
        raw_date=date.today(),
    )

    return {
        "engine_version": "new",
        "scope": scope,
        "tier": tier,
        "periodo_ita": periodo_ita,
        "pipe": pipe,
    }


# ============================================================
# ROUTE MACRO /oroscopo_ai/{periodo} (via prefix nel main)
# ============================================================

@router.post(
    "/{periodo}",
    response_model=OroscopoResponse,
    summary="Oroscopo macro (daily/weekly/monthly/yearly, free/premium, motore AI completo)",
)
async def oroscopo_macro(
    periodo: str,
    data_input: OroscopoBaseInput,
    request: Request,
    x_engine: Optional[str] = Header(None, alias="X-Engine"),
    user: UserContext = Depends(get_current_user),  # utente dal JWT
) -> OroscopoResponse:
    """
    Route unica per tutti gli oroscopi.

    Con prefix nel main="/oroscopo_ai", i path effettivi sono:
    - /oroscopo_ai/daily
    - /oroscopo_ai/weekly
    - /oroscopo_ai/monthly
    - /oroscopo_ai/yearly
    """
    start = time.time()

    scope: Periodo = _normalize_period(periodo)
    tier: Tier = _resolve_tier(request, data_input.tier)
    engine: Engine = _resolve_engine(x_engine)

    # ==========================================
    # 0) GATING CREDITI (solo premium + engine=ai)
    # ==========================================
    state = None
    decision: Optional[PremiumDecision] = None
    feature_cost = 0

    if tier == "premium" and engine == "ai":
        state = load_user_credits_state(user)
        decision = decide_premium_mode(state)
        feature_cost = OROSCOPO_FEATURE_COSTS.get(scope, 0)
        if feature_cost <= 0:
            raise HTTPException(
                status_code=500,
                detail=f"Costo oroscopo premium non configurato per periodo '{scope}'.",
            )

        apply_premium_consumption(
            state,
            decision,
            feature_cost=feature_cost,
        )

        save_user_credits_state(state)

    logger.info(
        "[OROSCOPO] scope=%s tier=%s engine=%s citta=%s data=%s nome=%s",
        scope, tier, engine, data_input.citta, data_input.data, data_input.nome
    )

    try:
        # ==========================================
        # 1) Motore numerico
        # ==========================================
        engine_result = _run_oroscopo_engine_new(scope=scope, tier=tier, data_input=data_input)

        payload_ai: Optional[Dict[str, Any]] = None
        oroscopo_ai: Optional[Dict[str, Any]] = None

        # ==========================================
        # 2) AI (Claude) se richiesto
        # ==========================================
        if engine == "ai":
            payload_ai = _build_payload_ai(
                scope=scope,
                tier=tier,
                engine_result=engine_result,
                data_input=data_input,
            )
            oroscopo_ai = _call_oroscopo_ai_claude(payload_ai)
        elif engine == "legacy":
            raise HTTPException(
                status_code=501,
                detail="Motore legacy non più supportato. Usa X-Engine: ai oppure new."
            )

        elapsed = time.time() - start

        # ==========================================
        # 3) Estrazione usage (se presente, come sinastria)
        # ==========================================
        tokens_in = 0
        tokens_out = 0
        try:
            ai_debug_block = None
            if isinstance(oroscopo_ai, dict):
                ai_debug_block = oroscopo_ai.get("ai_debug") or oroscopo_ai.get("debug")
            if isinstance(ai_debug_block, dict):
                usage = ai_debug_block.get("usage") or {}
                tokens_in = usage.get("input_tokens", 0) or 0
                tokens_out = usage.get("output_tokens", 0) or 0
        except Exception:
            tokens_in = 0
            tokens_out = 0

        # ==========================================
        # 4) COSTI & BILLING (paid vs free_credit vs free)
        # ==========================================
        is_guest = user.sub.startswith("anon-")

        billing_mode = "free"
        remaining_credits = None
        cost_paid_credits = 0
        cost_free_credits = 0

        if tier == "premium" and state is not None and decision is not None:
            billing_mode = decision.mode  # "paid" | "free_credit"
            remaining_credits = state.paid_credits

            if decision.mode == "paid":
                cost_paid_credits = feature_cost
            elif decision.mode == "free_credit":
                cost_free_credits = feature_cost
        else:
            billing_mode = "free"
            remaining_credits = None

        billing = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": billing_mode,
            "remaining_credits": remaining_credits,
            "cost_paid_credits": cost_paid_credits,
            "cost_free_credits": cost_free_credits,
        }

        # ==========================================
        # 5) LOG USAGE (anche guest, con request_json)
        # ==========================================
        try:
            request_json = {
                "scope": scope,
                "engine": engine,
                "tier": tier,
                "input": data_input.dict(),
            }

            log_usage_event(
                user_id=user.sub,
                feature=f"{OROSCOPO_FEATURE_KEY}_{scope}",
                tier=tier,
                billing_mode=billing_mode,
                cost_paid_credits=cost_paid_credits,
                cost_free_credits=cost_free_credits,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                is_guest=is_guest,
                request_json=request_json,
            )
        except Exception:
            logger.exception("[OROSCOPO] Errore nel logging usage")

        # ==========================================
        # 6) Risposta finale
        # ==========================================
        return OroscopoResponse(
            status="ok",
            scope=scope,
            engine=engine,
            input=data_input.dict(),
            engine_result=engine_result,
            payload_ai=payload_ai,
            oroscopo_ai=oroscopo_ai,
            error=None,
            billing=billing,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OROSCOPO] Errore non gestito")
        billing_error = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": "error",
            "remaining_credits": state.paid_credits if state is not None else None,
            "cost_paid_credits": 0,
            "cost_free_credits": 0,
        }
        return OroscopoResponse(
            status="error",
            scope=scope,
            engine=engine,
            input=data_input.dict(),
            engine_result=None,
            payload_ai=None,
            oroscopo_ai=None,
            error=str(e),
            billing=billing_error,
        )
