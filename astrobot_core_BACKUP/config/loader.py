from __future__ import annotations
import os, re, yaml
from typing import Literal, Dict, Any

ConfigKind = Literal["snapshots", "pesi", "filtri", "orb", "grafica"]
Scope = Literal["daily", "weekly", "monthly", "yearly"]
Tier = Literal["free", "premium"]

CONFIG_FILENAMES: Dict[ConfigKind, str] = {
    "snapshots": "snapshots.yml",
    "pesi": "pesi.yml",
    "filtri": "filtri.yml",
    "orb": "orb.yml",
    "grafica": "grafica.yml",
}

DEFAULT_TIMEZONE = "Europe/Rome"
WEEKDAYS = {"MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"}
ALLOWED_ASPECTS = {"congiunzione","opposizione","trigono","quadratura","sestile","quinconce"}

class ConfigError(ValueError):
    pass

def _config_dir() -> str:
    env = os.getenv("ASTROBOT_CONFIG_DIR")
    if env:
        return env
    return os.path.dirname(__file__)

def _read_yaml(path: str) -> dict:
    if not os.path.exists(path):
        raise ConfigError(f"Config non trovato: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Formato YAML non valido: {path}")
    return data

def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def _require(cond: bool, msg: str):
    if not cond:
        raise ConfigError(msg)

def _is_time(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-2]\d:[0-5]\d", s or ""))

def _validate_snapshots(cfg: dict, scope: Scope, tier: Tier) -> dict:
    tz = cfg.get("timezone") or DEFAULT_TIMEZONE
    _require(isinstance(tz, str), "timezone deve essere stringa")
    prof = (cfg.get("profiles", {}).get(scope, {}) or {}).get(tier, {}) or {}
    defaults = cfg.get("defaults", {})
    strat = prof.get("strategy")
    _require(strat in {"fixed_times","weekdays_times","days_of_month","monthly_on_day","every_n_days"},
             f"strategy non valido: {strat}")

    if strat == "fixed_times":
        times = prof.get("times")
        _require(isinstance(times, list) and times and all(_is_time(t) for t in times),
                 "times (HH:MM) obbligatorio per fixed_times")
    elif strat == "weekdays_times":
        items = prof.get("items")
        _require(isinstance(items, list) and items, "items obbligatorio per weekdays_times")
        for it in items:
            _require(it.get("weekday") in WEEKDAYS, f"weekday non valido: {it}")
            _require(_is_time(it.get("time")), f"time HH:MM non valido: {it}")
    elif strat == "days_of_month":
        days = prof.get("days"); time = prof.get("time") or defaults.get("anchor_time","12:00")
        _require(isinstance(days, list) and all(isinstance(d,int) and 1<=d<=31 for d in days),
                 "days deve essere lista di interi 1..31")
        _require(_is_time(time), "time HH:MM non valido")
        prof["time"] = time
    elif strat == "monthly_on_day":
        day = prof.get("day"); time = prof.get("time") or defaults.get("anchor_time","12:00")
        _require(isinstance(day,int) and 1<=day<=31, "day deve essere 1..31")
        _require(_is_time(time), "time HH:MM non valido")
        prof["time"] = time
    elif strat == "every_n_days":
        n = prof.get("n"); time = prof.get("time") or defaults.get("anchor_time","12:00")
        _require(isinstance(n,int) and n>0, "n deve essere int>0")
        _require(_is_time(time), "time HH:MM non valido")
        if "max_events" in prof:
            _require(isinstance(prof["max_events"], int) and prof["max_events"]>0, "max_events int>0")
        prof["time"] = time

    return {"timezone": tz, "start_week_on": cfg.get("defaults",{}).get("start_week_on","MONDAY"), **prof}

def _validate_pesi(cfg: dict, scope: Scope, tier: Tier) -> dict:
    weights = cfg.get("weights", {})
    aspects = weights.get("aspects", {})
    _require(isinstance(aspects, dict) and aspects, "pesi.aspects mancanti")
    for k,v in aspects.items():
        _require(k in ALLOWED_ASPECTS, f"aspetto non consentito: {k}")
        _require(isinstance(v,(int,float)) and v>=0, f"peso aspetto non valido: {k}={v}")
    planets = weights.get("planets",{}).get("groups",{})
    _require(isinstance(planets, dict) and planets, "pesi.planets.groups mancanti")
    for k,v in planets.items():
        _require(isinstance(v,(int,float)) and v>=0, f"peso gruppo pianeti non valido: {k}={v}")
    houses = weights.get("houses",{})
    _require(isinstance(houses, dict) and houses, "pesi.houses mancanti")
    falloff = cfg.get("falloff",{})
    _require(falloff.get("mode") in {"linear","cosine","gaussian"}, "falloff.mode non valido")
    agg = cfg.get("aggregation",{})
    _require(agg.get("method") in {"mean","weighted_mean"}, "aggregation.method non valido")
    _require(agg.get("snapshot_weights") in {"uniform","recency_decay"}, "snapshot_weights non valido")
    ov = (cfg.get("overrides",{}).get(scope,{}) or {}).get(tier,{}) or {}
    return _deep_merge({"weights":weights, "falloff":falloff, "aggregation":agg}, ov)

def _validate_filtri(cfg: dict, scope: Scope, tier: Tier) -> dict:
    defaults = cfg.get("defaults",{}) or {}
    profiles = cfg.get("profiles",{}) or {}
    prof = (profiles.get(scope, {}) or {}).get(tier, {}) or {}
    out = _deep_merge(defaults, prof)
    aspects = out.get("aspects", [])
    _require(isinstance(aspects, list), "aspects non validi")
    include = out.get("include", {}) or {}
    _require(isinstance(include, dict), "include deve essere un dizionario")
    thr = out.get("thresholds", {}) or {}
    _require(0 <= thr.get("min_orb_ratio", 0.35) <= 1, "min_orb_ratio fuori range 0..1")
    _require(isinstance(thr.get("min_strength", 0.1), (int,float)), "min_strength deve essere numerico")
    opt = out.get("options", {}) or {}
    if "max_aspects_per_pair" in opt:
        _require(isinstance(opt["max_aspects_per_pair"], int) and opt["max_aspects_per_pair"]>0,
                 "max_aspects_per_pair deve essere int>0")
    return out

def _validate_orb(cfg: dict, scope: Scope, tier: Tier) -> dict:
    base = cfg.get("base",{}) or {}
    _require(isinstance(base, dict) and base, "orb.base mancante")
    for k,v in base.items():
        _require(isinstance(v,(int,float)) and v>0, f"orb.base {k} deve essere >0")
    return {
        "base": base,
        "multipliers": cfg.get("multipliers",{}),
        "modes": cfg.get("modes",{}),
        "limits": cfg.get("limits",{"min_orb_deg":0.5})
    }

def _validate_grafica(cfg: dict, scope: Scope, tier: Tier) -> dict:
    theme = cfg.get("theme","light")
    if theme not in {"light","dark"}:
        raise ConfigError("theme deve essere light|dark")
    out = {k: v for k,v in cfg.items() if k != "overrides"}
    ov = (cfg.get("overrides",{}).get(scope,{}) or {}).get(tier,{}) or {}
    def _deep(base, ov):
        for k,v in ov.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = _deep(base[k], v)
            else:
                base[k] = v
        return base
    return _deep(out, ov)

def get_config(kind: ConfigKind, scope: Scope, tier: Tier) -> dict:
    path = os.path.join(_config_dir(), CONFIG_FILENAMES[kind])
    data = _read_yaml(path)
    if kind == "snapshots":
        return _validate_snapshots(data, scope, tier)
    if kind == "pesi":
        return _validate_pesi(data, scope, tier)
    if kind == "filtri":
        return _validate_filtri(data, scope, tier)
    if kind == "orb":
        return _validate_orb(data, scope, tier)
    if kind == "grafica":
        return _validate_grafica(data, scope, tier)
    raise ConfigError(f"Tipo config sconosciuto: {kind}")

def load_all_configs(scope: Scope, tier: Tier) -> Dict[str, Any]:
    return { k: get_config(k, scope, tier) for k in CONFIG_FILENAMES.keys() }
