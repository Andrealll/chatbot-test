from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal, Optional
from datetime import date
from pydantic import BaseModel

from astrobot_core.config.loader import load_all_configs, get_config
from astrobot_core.config.schedule import resolve_snapshots

Scope = Literal["daily","weekly","monthly","yearly"]
Tier  = Literal["free","premium"]

app = FastAPI(title="AstroBot Config Service Demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SnapshotsResp(BaseModel):
    scope: Scope
    tier: Tier
    count: int
    snapshots: list[str]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/config/{scope}/{tier}/snapshots", response_model=SnapshotsResp)
def api_snapshots(scope: Scope, tier: Tier,
                  start: Optional[str] = Query(None, description="YYYY-MM-DD"),
                  horizon_days: Optional[int] = Query(None)):
    start_date = date.fromisoformat(start) if start else date.today()
    snaps = resolve_snapshots(scope, tier, start_date=start_date, horizon_days=horizon_days)
    return {
        "scope": scope,
        "tier": tier,
        "count": len(snaps),
        "snapshots": [dt.isoformat() for dt in snaps]
    }

@app.get("/config/{scope}/{tier}/all")
def api_all(scope: Scope, tier: Tier):
    cfg = load_all_configs(scope, tier)
    return cfg

@app.get("/config/{kind}/{scope}/{tier}")
def api_one(kind: Literal["snapshots","pesi","filtri","orb","grafica"], scope: Scope, tier: Tier):
    return get_config(kind, scope, tier)

@app.get("/")
def root():
    return {"status":"ok","message":"AstroBot Config Service Demo online"}
