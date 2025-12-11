# chatbot_test/routes/routes_oroscopo_ai.py

import logging
from typing import Any, Dict, Optional, List, Literal

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, validator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar

from astrobot_core.kb.tema_kb import build_kb_oroscopo_glossario
from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai
from astrobot_core.ai_oroscopo_claude import call_claude_oroscopo_ai

# === AUTH + CREDITI ===
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

router = APIRouter(prefix="/oroscopo_ai", tags=["oroscopo_ai"])

Periodo = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]
Engine = Literal["ai"]

OROSCOPO_FEATURE_KEY_PREFIX = "oroscopo_ai"
OROSCOPO_FEATURE_COSTS: Dict[Periodo, int] = {
    "daily": 1,
    "weekly": 2,
    "monthly": 3,
    "yearly": 5,
}

PERIODO_EN_TO_IT = {
    "daily": "giornaliero",
    "weekly": "settimanale",
    "monthly": "mensile",
    "yearly": "annuale",
}

PERIODO_IT_TO_CODE = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}

class OroscopoAIRequest(BaseModel):
    citta: str
    data: str
    ora: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"
    ora_ignota: Optional[bool] = False  # 👈 NUOVO

    @validator("data")
    def _validate_data(cls, v: str) -> str:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError("data deve essere in formato YYYY-MM-DD")
        return v

    @validator("ora")
    def _validate_ora(cls, v: Optional[str]) -> Optional[str]:
        # Accettiamo None / "" come "nessuna ora" (es. ora ignota)
        if v is None:
            return v
        v = v.strip()
        if v == "":
          return None
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("ora deve essere in formato HH:MM")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("ora deve contenere solo numeri (HH:MM)")
        return v

class OroscopoBaseInput(OroscopoAIRequest):
    """
    Alias retrocompatibile per i helper interni.
    Stesse fields di OroscopoAIRequest.
    """
    pass


class OroscopoResponse(BaseModel):
    status: Literal["ok", "error"]
    scope: Periodo
    engine: Engine
    input: Dict[str, Any]
    engine_result: Optional[Dict[str, Any]] = None
    payload_ai: Optional[Dict[str, Any]] = None
    oroscopo_ai: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    billing: Optional[Dict[str, Any]] = None

    # NUOVO: blocchi dedicati al front-end
    grafico: Optional[Dict[str, Any]] = None
    tabella_aspetti: Optional[List[Dict[str, Any]]] = None


def _normalize_period(periodo: str) -> Periodo:
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
            detail=f"Periodo non valido: '{periodo}'. Usa uno tra: daily, weekly, monthly, yearly.",
        )
    return mapping[p]  # type: ignore[return-value]


def _normalize_tier(raw: Optional[str]) -> Tier:
    if not raw:
        return "free"
    s = raw.strip().lower()
    if s in {"premium", "pro", "paid"}:
        return "premium"
    return "free"

@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str
    periodo: str
    tier: str
    ora_ignota: bool = False  # 👈 NUOVO



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
                {
                    "id": "mattina",
                    "label": "Mattina",
                    "datetime": start_dt.replace(hour=9).isoformat(),
                },
                {
                    "id": "pomeriggio",
                    "label": "Pomeriggio",
                    "datetime": start_dt.replace(hour=15).isoformat(),
                },
                {
                    "id": "domani",
                    "label": "Domani",
                    "datetime": domani.isoformat(),
                },
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
                {
                    "id": "inverno",
                    "label": "Inverno",
                    "range": {"start": f"{year}-01-01", "end": f"{year}-03-20"},
                },
                {
                    "id": "primavera",
                    "label": "Primavera",
                    "range": {"start": f"{year}-03-21", "end": f"{year}-06-20"},
                },
                {
                    "id": "estate",
                    "label": "Estate",
                    "range": {"start": f"{year}-06-21", "end": f"{year}-09-22"},
                },
                {
                    "id": "autunno",
                    "label": "Autunno",
                    "range": {"start": f"{year}-09-23", "end": f"{year}-12-31"},
                },
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
        dts.append(
            _safe_iso_to_dt(dt_raw if isinstance(dt_raw, str) else None, today=today)
        )

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
        return (
            datetime.combine(d, datetime.min.time())
            .replace(hour=12)
        )

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
    _ = calendar.monthrange(year, month)

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

    samples_sorted = sorted(
        samples, key=lambda s: _safe_iso_to_dt(s.get("datetime"))
    )
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


def _aggregate_metriche_for_period(
    metriche_grafico: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
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
    if isinstance(po, dict) and (
        "date_range" in po or "aspetti_rilevanti" in po
    ):
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
            if (
                "date_range" in keys
                or "aspetti_rilevanti" in keys
                or "metriche_grafico" in keys
            ):
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


def _cleanup_period_block_for_ai(
    period_block: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
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
def build_oroscopo_struct_from_pipe(
    pipe: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
    # --- DEBUG: cosa contiene la pipe? ---
    logger.info("[OROSCOPO][STRUCT] pipe keys: %s", list(pipe.keys()))

    tema = pipe.get("tema_natale") or {}
    profilo_natale = pipe.get("profilo_natale") or {}

    logger.info("[OROSCOPO][STRUCT] tema_natale keys: %s", list(tema.keys()))
    logger.info("[OROSCOPO][STRUCT] tipo tema['pianeti_decod']: %s", type(tema.get("pianeti_decod")))
    logger.info("[OROSCOPO][STRUCT] tipo tema['natal_aspects']: %s", type(tema.get("natal_aspects")))
    logger.info("[OROSCOPO][STRUCT] tipo tema['natal_houses']: %s", type(tema.get("natal_houses")))

    # --- CERCA ALTRI BLOCCHI CHE CONTENGONO UN TEMA COMPLETO ---
    tema_candidates = []
    for k, v in pipe.items():
        if isinstance(v, dict) and (
            "pianeti_decod" in v or "natal_aspects" in v or "natal_houses" in v
        ):
            tema_candidates.append(k)
    logger.info("[OROSCOPO][STRUCT] possibili blocchi tema completi: %s", tema_candidates)


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

    # ==============================
    # KB DEBUG (combined_markdown) – come prima
    # ==============================
    kb_hooks = build_debug_kb_hooks(
        period_block=period_block,
        tema=tema,
        profilo_natale=profilo_natale,
        persona=persona,
    )

    # ==============================
    # KB GLOSSARIO TEMA – NUOVO
    # ==============================
    kb_glossario_tema: Dict[str, Any] = {}
    try:
        kb_glossario_tema = build_kb_oroscopo_glossario(
        tema=tema,
        period_block=period_block,
        ) or {}
        if kb_glossario_tema:
            logger.info(
                "[OROSCOPO_AI] kb_glossario_tema costruito: "
                "pianeti=%d, segni=%d, case=%d, aspetti=%d, coppie=%d",
                len(kb_glossario_tema.get("pianeti") or {}),
                len(kb_glossario_tema.get("segni") or {}),
                len(kb_glossario_tema.get("case") or {}),
                len(kb_glossario_tema.get("aspetti") or {}),
                len(kb_glossario_tema.get("coppie_rilevanti") or []),
            )
    except Exception as e:
        logger.exception("[OROSCOPO_AI] Errore build_kb_tema_glossario: %r", e)
        kb_glossario_tema = {}

    oroscopo_struct = {
        "meta": {
            "nome": persona.nome,
            "citta": persona.citta,
            "data_nascita": persona.data,
            "ora_nascita": persona.ora,
            "ora_ignota": bool(getattr(persona, "ora_ignota", False)),  # 👈 NUOVO
            "tier": persona.tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema,
        "profilo_natale": profilo_natale,
        "kb_hooks": kb_hooks,
        "kb_glossario_tema": kb_glossario_tema,  # QUI il nuovo glossario natal vs oggi
        "periodi": {
            persona.periodo: period_block,
        },
    }


    return oroscopo_struct




# =========================================================
# NUOVI HELPER: BLOCCO GRAFICO + TABELLA ASPETTI PER HTTP
# =========================================================

def _build_grafico_http_from_period_block(
    period_block: Dict[str, Any],
    scope: Periodo,
) -> Dict[str, Any]:
    """
    Converte metriche_grafico del period_block in un formato minimal per il front-end:

    {
      "scope": "daily",
      "axes": ["emozioni", "relazioni", "lavoro"],
      "samples": [
        {
          "label": "...",
          "datetime": "...",
          "emozioni": 0.73,
          "relazioni": 0.40,
          "lavoro": 0.85
        },
        ...
      ]
    }
    """
    mg = period_block.get("metriche_grafico") or {}
    samples_in = mg.get("samples") or []
    if not isinstance(samples_in, list) or not samples_in:
        return {}

    out_samples: List[Dict[str, Any]] = []

    for s in samples_in:
        m = s.get("metrics") or {}
        intens = m.get("intensities") or {}
        out_samples.append(
            {
                "label": s.get("label"),
                "datetime": s.get("datetime"),
                "emozioni": intens.get("emozioni"),
                "relazioni": intens.get("relazioni"),
                "lavoro": intens.get("lavoro"),
            }
        )

    return {
        "scope": scope,
        "axes": ["emozioni", "relazioni", "lavoro"],
        "samples": out_samples,
    }


def _build_tabella_aspetti_http_from_period_block(
    period_block: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Tabella aspetti light per il front-end, senza ripetizioni inutili:

    [
      {
        "pianeta_transito": "...",
        "pianeta_natale": "...",
        "aspetto": "congiunzione/quadratura/...",
        "intensita_discreta": "forte/debole/...",
        "persistenza": { "data_inizio": "...", "durata_giorni": N },
        "score_rilevanza": ...
      },
      ...
    ]
    """
    aspetti = period_block.get("aspetti_rilevanti") or []
    if not isinstance(aspetti, list):
        return []

    out: List[Dict[str, Any]] = []
    seen = set()

    for a in aspetti:
        if not isinstance(a, dict):
            continue
        tp = a.get("pianeta_transito")
        np = a.get("pianeta_natale")
        asp = a.get("aspetto") or a.get("tipo")
        if not (tp and np and asp):
            continue

        key = (str(tp), str(asp), str(np))
        if key in seen:
            continue
        seen.add(key)

        out.append(
            {
                "pianeta_transito": tp,
                "pianeta_natale": np,
                "aspetto": asp,
                "intensita_discreta": a.get("intensita_discreta"),
                "persistenza": a.get("persistenza"),
                "score_rilevanza": a.get("score_rilevanza"),
            }
        )

    return out


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

    NUOVO:
    - salva oroscopo_struct dentro engine_result["oroscopo_struct"]
      così la route può riusarlo per costruire grafico/tabella HTTP.
    """
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] scope=%s tier=%s nome=%s",
        scope,
        tier,
        data_input.nome,
    )

    pipe = engine_result.get("pipe") or {}
    if not pipe:
        raise RuntimeError(
            "engine_result.pipe mancante: assicurati che "
            "_run_oroscopo_engine_new sia stato chiamato correttamente."
        )

    periodo_ita = PERIODO_EN_TO_IT[scope]
    ora_ignota_flag = bool(getattr(data_input, "ora_ignota", False))

    persona = Persona(
        nome=data_input.nome or "Anonimo",
        citta=data_input.citta,
        data=data_input.data,
        ora=data_input.ora or "00:00",
        periodo=periodo_ita,
        tier=tier,
        ora_ignota=ora_ignota_flag,  # 👈 NUOVO
    )


    # 1) oroscopo_struct dalla pipe
    oroscopo_struct = build_oroscopo_struct_from_pipe(pipe, persona)

    # NUOVO: lo agganciamo all'engine_result per uso HTTP
    engine_result["oroscopo_struct"] = oroscopo_struct

    # 2) period_code in stile "daily"/"weekly"/...
    period_code = PERIODO_IT_TO_CODE.get(periodo_ita, scope)

    # 3) payload AI usando il modulo ufficiale
    payload_ai = build_oroscopo_payload_ai(
        oroscopo_struct=oroscopo_struct,
        lang="it",
        period_code=period_code,
    )
    
    logger.info(
        "[OROSCOPO][PAYLOAD_AI] kb keys: %s",
        list((payload_ai.get("kb") or {}).keys())
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
    periodo_ita = PERIODO_EN_TO_IT[scope]

    logger.info(
        "[OROSCOPO][ENGINE_NEW] scope=%s (ita=%s) tier=%s citta=%s data=%s",
        scope,
        periodo_ita,
        tier,
        data_input.citta,
        data_input.data,
    )

    # 👇 NUOVO: normalizzazione ora con supporto ora_ignota
    ora_ignota_flag = bool(getattr(data_input, "ora_ignota", False))
    ora_effettiva = data_input.ora

    if ora_ignota_flag or not ora_effettiva:
        # Se l'ora è ignota o non fornita, usiamo le 12:00 solo per i calcoli numerici
        ora_effettiva = "12:00"

    pipe = run_oroscopo_multi_snapshot(
        periodo=periodo_ita,
        tier=tier,
        citta=data_input.citta,
        data_nascita=data_input.data,
        ora_nascita=ora_effettiva,  # 👈 usa l'ora normalizzata
        raw_date=date.today(),
    )

    return {
        "engine_version": "new",
        "scope": scope,
        "tier": tier,
        "periodo_ita": periodo_ita,
        "pipe": pipe,
    }



def _run_oroscopo_engine(
    scope: Periodo,
    tier: Tier,
    data_input: OroscopoAIRequest,
) -> Dict[str, Any]:
    """
    Wrapper compatibile usato dalla route oroscopo_ai_endpoint.
    Delega alla nuova implementazione _run_oroscopo_engine_new.
    """
    return _run_oroscopo_engine_new(
        scope=scope,
        tier=tier,
        data_input=data_input,
    )


# =============================
# ROUTE PRINCIPALE
# =============================

@router.post(
    "/{periodo}",
    response_model=OroscopoResponse,
    summary="Oroscopo AI (daily/weekly/monthly/yearly, free/premium, billing stile tema_ai)",
)
async def oroscopo_ai_endpoint(
    periodo: str,
    payload: OroscopoAIRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> OroscopoResponse:
    """
    Oroscopo AI con:
    - normalizzazione periodo (daily/weekly/monthly/yearly)
    - gating crediti stile tema_ai
    - logging in usage_logs (tokens, billing, request_json)
    - billing per periodo con costi diversi (OROSCOPO_FEATURE_COSTS)
    """

    # ==============================
    # Metadati utente + request
    # ==============================
    scope: Periodo = _normalize_period(periodo)
    tier: Tier = _normalize_tier(payload.tier)

    logger.info(
        "[OROSCOPO_AI] scope=%s tier=%s citta=%s data=%s nome=%s",
        scope,
        tier,
        payload.citta,
        payload.data,
        payload.nome,
    )

    engine: Engine = "ai"
    is_guest = user.sub.startswith("anon-")
    role = getattr(user, "role", None)

    client_source = request.headers.get("x-client-source") or "unknown"
    client_session = request.headers.get("x-client-session")

    request_log_base: Dict[str, Any] = {
        "body": payload.dict(),
        "client_source": client_source,
        "client_session": client_session,
        "scope": scope,
        "tier": tier,
    }

    # Variabili di stato per logging
    state = None
    decision: Optional[PremiumDecision] = None
    billing_mode = "free"

    paid_credits_before: Optional[int] = None
    paid_credits_after: Optional[int] = None
    free_credits_used_before: Optional[int] = None
    free_credits_used_after: Optional[int] = None
    feature_cost: int = 0

    try:
        # ==============================
        # 0) STATO CREDITI + GATING
        # ==============================
        state = load_user_credits_state(user)

        paid_credits_before = state.paid_credits
        free_credits_used_before = state.free_tries_used
        paid_credits_after = state.paid_credits
        free_credits_used_after = state.free_tries_used

        if tier == "premium":
            feature_cost = OROSCOPO_FEATURE_COSTS.get(scope, 0)
            if feature_cost <= 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Costo oroscopo premium non configurato "
                        f"per periodo '{scope}'."
                    ),
                )

            decision = decide_premium_mode(state)

            apply_premium_consumption(
                state,
                decision,
                feature_cost=feature_cost,
            )

            save_user_credits_state(state)

            paid_credits_after = state.paid_credits
            free_credits_used_after = state.free_tries_used

            if decision.mode == "paid":
                billing_mode = "paid"
            elif decision.mode == "free_credit":
                billing_mode = "free_credit"
            else:
                billing_mode = "denied"
        else:
            # tier free: nessun consumo, ma salviamo comunque lo stato
            save_user_credits_state(state)
            billing_mode = "free"

        # ==============================
        # 1) ENGINE OROSCOPO (pipeline)
        # ==============================
        engine_result = _run_oroscopo_engine(
            scope=scope,
            tier=tier,
            data_input=payload,
        )

        # ==============================
        # 2) Build payload AI
        # ==============================
        payload_ai = _build_payload_ai(
            scope=scope,
            tier=tier,
            engine_result=engine_result,
            data_input=payload,
        )

        # ==============================
        # 3) Chiamata Claude (oroscopo)
        # ==============================
        oroscopo_ai = _call_oroscopo_ai_claude(payload_ai)

        # ==============================
        # 3b) COSTRUZIONE grafico + tabella_aspetti per HTTP
        # ==============================
        grafico_http: Optional[Dict[str, Any]] = None
        tabella_aspetti_http: Optional[List[Dict[str, Any]]] = None

        try:
            oroscopo_struct = engine_result.get("oroscopo_struct") or {}
            periodi_struct = oroscopo_struct.get("periodi") or {}
            period_block_http: Optional[Dict[str, Any]] = None

            if isinstance(periodi_struct, dict) and periodi_struct:
                # single-period: ci aspettiamo UNA sola chiave (giornaliero/settimana/mensile/annuale in IT)
                if len(periodi_struct) == 1:
                    period_block_http = list(periodi_struct.values())[0]
                else:
                    # fallback difensivo: prendiamo il primo valore
                    period_block_http = list(periodi_struct.values())[0]

            if isinstance(period_block_http, dict):
                grafico_http = _build_grafico_http_from_period_block(
                    period_block_http,
                    scope=scope,
                )
                tabella_aspetti_http = _build_tabella_aspetti_http_from_period_block(
                    period_block_http
                )
        except Exception as e:
            logger.exception(
                "[OROSCOPO_AI] Errore costruzione grafico/tabella HTTP: %r", e
            )

        # ==============================
        # USAGE TOKENS / LATENCY da _ai_usage
        # ==============================
        tokens_in = 0
        tokens_out = 0
        model = None
        latency_ms: Optional[float] = None

        try:
            if isinstance(oroscopo_ai, dict):
                ai_usage = oroscopo_ai.pop("_ai_usage", None)
                if isinstance(ai_usage, dict):
                    in_tok = ai_usage.get("input_tokens")
                    out_tok = ai_usage.get("output_tokens")
                    dur = ai_usage.get("duration_ms")

                    if isinstance(in_tok, (int, float)):
                        tokens_in = int(in_tok)
                    if isinstance(out_tok, (int, float)):
                        tokens_out = int(out_tok)
                    if isinstance(dur, (int, float)):
                        latency_ms = float(dur)
        except Exception:
            logger.exception(
                "[OROSCOPO_AI] Errore lettura _ai_usage (input/output/duration_ms)"
            )

        # ==============================
        # 4) BILLING CALCOLATO
        # ==============================
        cost_paid_credits = 0
        cost_free_credits = 0

        if tier == "premium" and decision is not None:
            if decision.mode == "paid":
                cost_paid_credits = feature_cost
            elif decision.mode == "free_credit":
                cost_free_credits = feature_cost

        billing = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": billing_mode,
            "remaining_credits": (
                state.paid_credits if state is not None else None
            ),
            "cost_paid_credits": cost_paid_credits,
            "cost_free_credits": cost_free_credits,
        }

        # ==============================
        # 5) LOGGING USAGE (successo)
        # ==============================
        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"
        request_log_success = {
            **request_log_base,
            "ai_call": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        }

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
                role=role,
                is_guest=is_guest,
                billing_mode=billing_mode,
                cost_paid_credits=cost_paid_credits,
                cost_free_credits=cost_free_credits,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                latency_ms=latency_ms,
                paid_credits_before=paid_credits_before,
                paid_credits_after=paid_credits_after,
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=free_credits_used_after,
                request_json=request_log_success,
            )
        except Exception as e:
            logger.exception(
                "[OROSCOPO_AI] log_usage_event error (success): %r", e
            )

        # ==============================
        # 6) RISPOSTA FINALE
        # ==============================
        return OroscopoResponse(
            status="ok",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=engine_result,
            payload_ai=payload_ai,
            oroscopo_ai=oroscopo_ai,
            error=None,
            billing=billing,
            grafico=grafico_http,
            tabella_aspetti=tabella_aspetti_http,
        )

    # ==============================
    # 7) LOG ERRORI HTTP (gating, ecc.)
    # ==============================
    except HTTPException as exc:
        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
                role=role,
                is_guest=is_guest,
                billing_mode="error",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json={
                    **request_log_base,
                    "error": {
                        "type": "http_exception",
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    },
                },
            )
        except Exception as log_err:
            logger.exception(
                "[OROSCOPO_AI] log_usage_event error (HTTPException): %r",
                log_err,
            )

        raise

    # ==============================
    # 8) LOG ERRORI INATTESI
    # ==============================
    except Exception as exc:
        logger.exception("[OROSCOPO_AI] Errore non gestito")
        feature_name = f"{OROSCOPO_FEATURE_KEY_PREFIX}_{scope}"

        try:
            log_usage_event(
                user_id=user.sub,
                feature=feature_name,
                tier=tier,
                role=role,
                is_guest=is_guest,
                billing_mode="error",
                cost_paid_credits=0,
                cost_free_credits=0,
                tokens_in=0,
                tokens_out=0,
                model=None,
                latency_ms=None,
                paid_credits_before=paid_credits_before,
                paid_credits_after=(
                    state.paid_credits if state is not None else None
                ),
                free_credits_used_before=free_credits_used_before,
                free_credits_used_after=(
                    state.free_tries_used if state is not None else None
                ),
                request_json={
                    **request_log_base,
                    "error": {
                        "type": "unexpected_exception",
                        "detail": str(exc),
                    },
                },
            )
        except Exception as log_err:
            logger.exception(
                "[OROSCOPO_AI] log_usage_event error (unexpected): %r",
                log_err,
            )

        billing_error = {
            "tier": tier,
            "scope": scope,
            "engine": engine,
            "mode": "error",
            "remaining_credits": state.paid_credits if state else None,
        }

        return OroscopoResponse(
            status="error",
            scope=scope,
            engine=engine,
            input=payload.dict(),
            engine_result=None,
            payload_ai=None,
            oroscopo_ai=None,
            error=str(exc),
            billing=billing_error,
            grafico=None,
            tabella_aspetti=None,
        )
