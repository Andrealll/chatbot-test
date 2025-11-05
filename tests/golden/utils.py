from __future__ import annotations
from typing import Dict, Tuple, List
import numpy as np
from PIL import Image
from pathlib import Path


# ---- Angoli (differenza circolare) ----


def circular_diff_deg(a: float, b: float) -> float:
d = (a - b + 180.0) % 360.0 - 180.0
return abs(d)




def compare_angles(exp: Dict[str, float], act: Dict[str, float], tol_deg: float = 0.5) -> List[str]:
errors = []
keys = set(exp.keys()) & set(act.keys())
for k in sorted(keys):
d = circular_diff_deg(exp[k], act[k])
if d > tol_deg:
errors.append(f"{k}: Δ={d:.3f}° > {tol_deg}° (exp={exp[k]:.3f}, act={act[k]:.3f})")
missing = set(exp.keys()) - set(act.keys())
extra = set(act.keys()) - set(exp.keys())
for k in sorted(missing):
errors.append(f"missing angle key: {k}")
for k in sorted(extra):
errors.append(f"extra angle key: {k}")
return errors


# ---- Intensità (tolleranza relativa) ----


def compare_intensities(exp: Dict[str, float], act: Dict[str, float], rel_tol: float = 0.10) -> List[str]:
errors = []
keys = set(exp.keys()) & set(act.keys())
for k in sorted(keys):
e, a = float(exp[k]), float(act[k])
denom = max(abs(e), 1e-9)
rel_err = abs(a - e) / denom
if rel_err > rel_tol:
errors.append(f"{k}: rel_err={rel_err:.3%} > {rel_tol:.0%} (exp={e:.4f}, act={a:.4f})")
missing = set(exp.keys()) - set(act.keys())
extra = set(act.keys()) - set(exp.keys())
for k in sorted(missing):
errors.append(f"missing intensity key: {k}")
for k in sorted(extra):
errors.append(f"extra intensity key: {k}")
return errors


# ---- Immagini (RMSE normalizzato 0..1) ----


def image_rmse(p1: Path, p2: Path) -> float:
i1 = Image.open(p1).convert('RGB')
i2 = Image.open(p2).convert('RGB')
if i1.size != i2.size:
i2 = i2.resize(i1.size)
a1 = np.asarray(i1, dtype=np.float32)
a2 = np.asarray(i2, dtype=np.float32)
mse = np.mean((a1 - a2) ** 2)
rmse = float(np.sqrt(mse)) / 255.0
return rmse
