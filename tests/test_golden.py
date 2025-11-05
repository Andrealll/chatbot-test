from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timedelta
import yaml
import pytest

from tests.golden.adapters import (
    Place, Natal,
    compute_tema,
    compute_sinastria,
    compute_oroscopo_daily,
    compute_oroscopo_period,
)
from tests.golden.utils import compare_angles, compare_intensities, image_rmse

ROOT = Path(__file__).resolve().parent / "golden"
DATA = ROOT / "data"

# Tolleranze (override con env se vuoi)
TOL_DEG = float(os.getenv("GOLD_TOL_DEG", "0.5")) if "os" in globals() else 0.5
TOL_REL = float(os.getenv("GOLD_TOL_REL", "0.10")) if "os" in globals() else 0.10
TOL_RMSE = float(os.getenv("GOLD_TOL_RMSE", "0.03")) if "os" in globals() else 0.03

def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)

def _load_cfg():
    return yaml.safe_load((ROOT / "cases.yml").read_text())

def _load_case_ids():
    cfg = _load_cfg()
    return [c["id"] for c in cfg["cases"]]

@pytest.mark.parametrize("case_id", _load_case_ids())
def test_golden(case_id):
    cfg = _load_cfg()
    default_natal = cfg.get("natal")
    case = next(c for c in cfg["cases"] if c["id"] == case_id)

    gold_json = json.loads((DATA / f"{case_id}.json").read_text())
    gold_png = DATA / f"{case_id}.png"
    tmp_png = DATA / f"__actual_{case_id}.png"

    ctype = case["type"]

    if ctype == "tema":
        b = case["birth"]
        res = compute_tema(_parse_dt(b["when"]), Place(**b["place"]), tmp_png)
        assert not compare_angles(gold_json["angles"], res["angles"], TOL_DEG), "Angles differ beyond tolerance"

    elif ctype == "sinastria":
        A = case["A"]; B = case["B"]
        res = compute_sinastria(
            {"when": _parse_dt(A["when"]), "place": A["place"], "name": A.get("name","A")},
            {"when": _parse_dt(B["when"]), "place": B["place"], "name": B.get("name","B")},
            tmp_png,
        )
        assert not compare_angles(gold_json["angles_A"], res["angles_A"], TOL_DEG)
        assert not compare_angles(gold_json["angles_B"], res["angles_B"], TOL_DEG)

    elif ctype == "daily":
        natal_cfg = case.get("natal", default_natal)
        natal = Natal(when=_parse_dt(natal_cfg["when"]), place=natal_cfg["place"])
        res = compute_oroscopo_daily(_parse_dt(case["when"]), Place(**case["place"]), natal, tmp_png)
        assert not compare_intensities(gold_json["intensities"], res["intensities"], TOL_REL)

    elif ctype in ("weekly", "monthly", "annual"):
        natal_cfg = case.get("natal", default_natal)
        natal = Natal(when=_parse_dt(natal_cfg["when"]), place=natal_cfg["place"])

        if ctype == "weekly":
            start = _parse_dt(case["start"])
            days = int(case.get("days", 7))
            if "sampling" in case:
                samples = [_parse_dt(s) for s in case["sampling"]]
            else:
                N = int(case.get("sample_points", 7))
                step = max(1, days // max(1, N))
                samples = [start + timedelta(days=i*step) for i in range(N)]
        elif ctype == "monthly":
            year, m = map(int, case["month"].split("-"))
            N = int(case.get("sample_points", 10))
            samples = [datetime(year, m, 1) + timedelta(days=i*3) for i in range(N)]
        else:  # annual
            year = int(case["year"])
            N = int(case.get("sample_points", 120))
            samples = [datetime(year, 1, 1) + timedelta(days=i*3) for i in range(N)]

        res = compute_oroscopo_period(samples, Place(**case["place"]), natal, tmp_png)
        assert not compare_intensities(gold_json["intensities"], res["intensities"], TOL_REL)

    else:
        raise ValueError(ctype)

    # PNG RMSE
    assert gold_png.exists(), f"Golden PNG mancante: {gold_png}"
    rmse = image_rmse(gold_png, tmp_png)
    assert rmse <= TOL_RMSE, f"PNG RMSE {rmse:.4f} > {TOL_RMSE}"
