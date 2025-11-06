
# service/main_scoring.py
from fastapi import FastAPI, Query, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Literal, List, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field

from astrobot_core.config.loader import load_all_configs, get_config
from astrobot_core.config.schedule import resolve_snapshots
from astrobot_core.scoring import score_snapshot
from astrobot_core.aggregate import aggregate_scores
from astrobot_core.plotting import trend_bar_png

Scope = Literal["daily","weekly","monthly","yearly"]
Tier  = Literal["free","premium"]

app = FastAPI(title="AstroBot Scoring Service", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

class Aspect(BaseModel):
    pianeta1: str
    pianeta2: str
    tipo: Literal["congiunzione","opposizione","trigono","quadratura","sestile","quinconce"]
    delta: float = Field(ge=0.0)
    house_class: Optional[Literal["angular","succedent","cadent"]] = None

class SnapshotInput(BaseModel):
    when: datetime
    aspetti: List[Aspect]

class ScoreResponse(BaseModel):
    scope: Scope
    tier: Tier
    count: int
    items: List[Dict[str, Any]]
    aggregate: float

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/schedule/{scope}/{tier}")
def schedule(scope: Scope, tier: Tier, start: Optional[str] = None, horizon_days: Optional[int] = None):
    d = date.fromisoformat(start) if start else date.today()
    snaps = resolve_snapshots(scope, tier, start_date=d, horizon_days=horizon_days)
    return {"scope": scope, "tier": tier, "snapshots": [dt.isoformat() for dt in snaps]}

@app.post("/oroscopo/{scope}/{tier}", response_model=ScoreResponse)
def oroscopo(scope: Scope, tier: Tier, body: Dict[str, Any] = Body(...)):
    snapshots = [SnapshotInput(**s) for s in body.get("snapshots", [])]
    context = body.get("context", "transit")

    cfg = load_all_configs(scope, tier)
    cfg_pesi, cfg_filtri, cfg_orb, cfg_gfx = cfg["pesi"], cfg["filtri"], cfg["orb"], cfg["grafica"]

    per_snap = []
    for s in snapshots:
        score = score_snapshot([a.dict() for a in s.aspetti], cfg_pesi, cfg_filtri, cfg_orb, context=context)
        per_snap.append({"when": s.when.isoformat(), "score": score})

    agg_cfg = cfg_pesi.get("aggregation", {})
    aggregate = aggregate_scores(
        [x["score"] for x in per_snap],
        method=agg_cfg.get("method", "weighted_mean"),
        snapshot_weights=agg_cfg.get("snapshot_weights", "uniform"),
        lam=float(agg_cfg.get("lambda", 0.05)),
    )
    return {"scope": scope, "tier": tier, "count": len(per_snap), "items": per_snap, "aggregate": aggregate}

@app.post("/plot/{scope}/{tier}")
def plot(scope: Scope, tier: Tier, body: Dict[str, Any] = Body(...)):
    """
    body come /oroscopo: { "context": "...", "snapshots": [ {when, aspetti:[...]}, ... ] }
    ritorna immagine PNG base64 del trend e i punteggi.
    """
    resp = oroscopo(scope, tier, body)  # riusa calcolo
    cfg_gfx = get_config("grafica", scope, tier)
    labels = [it["when"].split("T")[0] for it in resp["items"]]
    scores = [it["score"] for it in resp["items"]]
    data_url = trend_bar_png(scores, labels, cfg_gfx)
    return {"image_base64": data_url, **resp}

# --------- AUTO MODE (usa core transiti se disponibile) ---------
try:
    from astrobot_core.transiti import calcola_transiti_data_fissa as _core_transits
except Exception:
    _core_transits = None

def _normalize_aspetti(raw: Any) -> List[Dict[str, Any]]:
    # tenta vari formati: lista diretta o wrapper {"aspetti":[...]}
    if isinstance(raw, dict) and "aspetti" in raw:
        raw = raw["aspetti"]
    out = []
    if isinstance(raw, list):
        for a in raw:
            try:
                out.append({
                    "pianeta1": a.get("pianeta1") or a.get("p1") or a.get("A") or "NA",
                    "pianeta2": a.get("pianeta2") or a.get("p2") or a.get("B") or "NA",
                    "tipo": a.get("tipo") or a.get("aspect") or "congiunzione",
                    "delta": float(a.get("delta") or a.get("orb") or 0.0),
                    "house_class": a.get("house_class"),
                })
            except Exception:
                continue
    return out

@app.post("/oroscopo/auto/{scope}/{tier}", response_model=ScoreResponse)
def oroscopo_auto(scope: Scope, tier: Tier,
                  start: Optional[str] = Query(None, description="YYYY-MM-DD"),
                  horizon_days: Optional[int] = Query(None, description="giorni (default dipende dallo scope)"),
                  params: Dict[str, Any] = Body(default={})):
    """
    Chiama il core 'calcola_transiti_data_fissa' per ogni snapshot e calcola score/aggregate.
    Body 'params' viene passato tal-quale come **kwargs al core (per data natale, luogo, ecc.).
    """
    if _core_transits is None:
        return {"scope": scope, "tier": tier, "count": 0, "items": [], "aggregate": 0.0}

    d = date.fromisoformat(start) if start else date.today()
    snaps = resolve_snapshots(scope, tier, start_date=d, horizon_days=horizon_days)

    cfg = load_all_configs(scope, tier)
    cfg_pesi, cfg_filtri, cfg_orb = cfg["pesi"], cfg["filtri"], cfg["orb"]

    items = []
    for dt in snaps:
        try:
            raw = _core_transits(dt, **params)
            aspetti = _normalize_aspetti(raw)
            score = score_snapshot(aspetti, cfg_pesi, cfg_filtri, cfg_orb, context=params.get("context","transit"))
        except Exception:
            score = 0.0
        items.append({"when": dt.isoformat(), "score": score})

    agg_cfg = cfg_pesi.get("aggregation", {})
    aggregate = aggregate_scores([x["score"] for x in items],
                                 method=agg_cfg.get("method", "weighted_mean"),
                                 snapshot_weights=agg_cfg.get("snapshot_weights", "uniform"),
                                 lam=float(agg_cfg.get("lambda", 0.05)))
    return {"scope": scope, "tier": tier, "count": len(items), "items": items, "aggregate": aggregate}
