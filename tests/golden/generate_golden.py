from __future__ import annotations
import argparse
from pathlib import Path
import yaml
from datetime import datetime, timedelta
import json

from .adapters import (
    Place, Natal,
    compute_tema,
    compute_sinastria,
    compute_oroscopo_daily,
    compute_oroscopo_period,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)

def main(overwrite: bool = False):
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "cases.yml").read_text())

    default_natal = cfg.get("natal")

    for case in cfg["cases"]:
        cid = case["id"]
        ctype = case["type"]
        json_path = DATA / f"{cid}.json"
        png_path = DATA / f"{cid}.png"
        if json_path.exists() and not overwrite:
            print(f"[SKIP] {cid} (usa --overwrite per rigenerare)")
            continue

        if ctype == "tema":
            b = case["birth"]
            when = parse_dt(b["when"])
            p = Place(**b["place"])
            res = compute_tema(when, p, png_path)

        elif ctype == "sinastria":
            A = case["A"]; B = case["B"]
            res = compute_sinastria(
                {"when": parse_dt(A["when"]), "place": A["place"], "name": A.get("name","A")},
                {"when": parse_dt(B["when"]), "place": B["place"], "name": B.get("name","B")},
                png_path
            )

        elif ctype == "daily":
            when = parse_dt(case["when"])
            p = Place(**case["place"])
            natal_cfg = case.get("natal", default_natal)
            natal = Natal(when=parse_dt(natal_cfg["when"]), place=natal_cfg["place"])
            res = compute_oroscopo_daily(when, p, natal, png_path)

        elif ctype == "weekly":
            start = parse_dt(case["start"])
            days = int(case.get("days", 7))
            if "sampling" in case:
                samples = [parse_dt(s) for s in case["sampling"]]
            else:
                N = int(case.get("sample_points", 7))
                step = max(1, days // max(1, N))
                samples = [start + timedelta(days=i*step) for i in range(N)]
            p = Place(**case["place"])
            natal_cfg = case.get("natal", default_natal)
            natal = Natal(when=parse_dt(natal_cfg["when"]), place=natal_cfg["place"])
            res = compute_oroscopo_period(samples, p, natal, png_path)

        elif ctype == "monthly":
            year, m = map(int, case["month"].split("-"))
            N = int(case.get("sample_points", 10))
            samples = [datetime(year, m, 1) + timedelta(days=i*3) for i in range(N)]
            p = Place(**case["place"])
            natal_cfg = case.get("natal", default_natal)
            natal = Natal(when=parse_dt(natal_cfg["when"]), place=natal_cfg["place"])
            res = compute_oroscopo_period(samples, p, natal, png_path)

        elif ctype == "annual":
            year = int(case["year"])
            N = int(case.get("sample_points", 120))
            samples = [datetime(year, 1, 1) + timedelta(days=i*3) for i in range(N)]
            p = Place(**case["place"])
            natal_cfg = case.get("natal", default_natal)
            natal = Natal(when=parse_dt(natal_cfg["when"]), place=natal_cfg["place"])
            res = compute_oroscopo_period(samples, p, natal, png_path)

        else:
            raise ValueError(f"Tipo caso non supportato: {ctype}")

        json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(f"[OK] {cid} -> {json_path.name}, {png_path.name}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true", help="Rigenera tutti i golden")
    args = ap.parse_args()
    main(overwrite=args.overwrite)
