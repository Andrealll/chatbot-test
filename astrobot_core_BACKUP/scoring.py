
# astrobot_core/scoring.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import math

PLANET_GROUP = {
    "Sole": "luminaries", "Luna": "luminaries",
    "Mercurio": "personal", "Venere": "personal", "Marte": "personal",
    "Giove": "social", "Saturno": "social",
    "Urano": "generational", "Nettuno": "generational", "Plutone": "generational",
    "ASC": "angles", "MC": "angles",
    "Nodo": "points", "Lilith": "points",
}

def group_of(planet: str) -> str:
    return PLANET_GROUP.get(planet, "personal")

def falloff_value(delta: float, orb: float, mode: str = "cosine", power: float = 1.0, sigma: Optional[float] = None) -> float:
    if orb <= 0:
        return 0.0
    x = max(0.0, min(1.0, delta / orb))
    if mode == "linear":
        v = 1.0 - x
    elif mode == "gaussian":
        s = sigma if sigma and sigma > 0 else (orb / 2.0)
        v = math.exp(-0.5 * (delta / s) ** 2)
    else:
        v = math.cos((math.pi / 2.0) * x)
        v = max(0.0, v)
    if power and power != 1.0:
        v = v ** power
    return v

def effective_orb(aspect_type: str, p1: str, p2: str, cfg_orb: Dict[str, Any], context: str = "transit") -> float:
    base = float(cfg_orb["base"].get(aspect_type, 0.0))
    if base <= 0:
        return 0.0
    by_group = cfg_orb.get("multipliers", {}).get("by_group", {}) or {}
    angles_mul = float(cfg_orb.get("multipliers", {}).get("angles", 1.0) or 1.0)
    g1 = group_of(p1); g2 = group_of(p2)
    m1 = float(by_group.get(g1, 1.0) or 1.0)
    m2 = float(by_group.get(g2, 1.0) or 1.0)
    ctx_mul = float(cfg_orb.get("modes", {}).get("context", {}).get(context, 1.0) or 1.0)
    angle_boost = angles_mul if ("angles" in (g1, g2)) else 1.0
    return max(cfg_orb.get("limits", {}).get("min_orb_deg", 0.5), base * m1 * m2 * ctx_mul * angle_boost)

def aspect_strength(
    aspect_type: str, p1: str, p2: str, delta: float,
    cfg_pesi: Dict[str, Any], cfg_filtri: Dict[str, Any], cfg_orb: Dict[str, Any],
    context: str = "transit", house_class: Optional[str] = None,
) -> float:
    allowed_aspects = set(cfg_filtri.get("aspects", []))
    if allowed_aspects and aspect_type not in allowed_aspects:
        return 0.0
    orb_eff = effective_orb(aspect_type, p1, p2, cfg_orb, context=context)
    if orb_eff <= 0:
        return 0.0
    thr = cfg_filtri.get("thresholds", {})
    if (delta / orb_eff) > float(thr.get("min_orb_ratio", 0.35)):
        return 0.0
    w_aspect = float(cfg_pesi["weights"]["aspects"].get(aspect_type, 0.0))
    if w_aspect <= 0:
        return 0.0
    wg = cfg_pesi["weights"]["planets"]["groups"]
    w_g1 = float(wg.get(group_of(p1), 1.0))
    w_g2 = float(wg.get(group_of(p2), 1.0))
    w_house = 1.0
    if house_class:
        w_house = float(cfg_pesi["weights"]["houses"].get(house_class, 1.0))
    fcfg = cfg_pesi.get("falloff", {})
    f = falloff_value(delta, orb_eff, mode=fcfg.get("mode","cosine"), power=float(fcfg.get("power",1.0)))
    score = w_aspect * ((w_g1 + w_g2)/2.0) * w_house * f
    if score < float(thr.get("min_strength", 0.1)):
        return 0.0
    return score

def score_snapshot(aspects: List[Dict[str, Any]], cfg_pesi: Dict[str, Any], cfg_filtri: Dict[str, Any], cfg_orb: Dict[str, Any], context: str = "transit") -> float:
    total = 0.0; kept = 0
    for a in aspects:
        s = aspect_strength(a["tipo"], a["pianeta1"], a["pianeta2"], float(a["delta"]), cfg_pesi, cfg_filtri, cfg_orb, context=context, house_class=a.get("house_class"))
        if s > 0: total += s; kept += 1
    return (total/kept) if kept else 0.0
