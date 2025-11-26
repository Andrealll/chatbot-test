
# astrobot_core/aggregate.py
from __future__ import annotations
from typing import List
import math

def compute_weights(n: int, mode: str = "uniform", lam: float = 0.05) -> List[float]:
    if n <= 0: return []
    if mode == "recency_decay":
        ws = [math.exp(-lam * (n - 1 - i)) for i in range(n)]
    else:
        ws = [1.0] * n
    s = sum(ws)
    return [w/s for w in ws] if s>0 else ws

def aggregate_scores(per_snapshot_scores: List[float], method: str = "weighted_mean", snapshot_weights: str = "uniform", lam: float = 0.05) -> float:
    n = len(per_snapshot_scores)
    if n == 0: return 0.0
    if method == "mean": return sum(per_snapshot_scores)/n
    ws = compute_weights(n, mode=snapshot_weights, lam=lam)
    return sum(s*w for s,w in zip(per_snapshot_scores, ws))
