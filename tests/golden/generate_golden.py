from __future__ import annotations
DATA = ROOT / "data"




def parse_dt(s: str) -> datetime:
return datetime.fromisoformat(s)




def main(overwrite: bool = False):
DATA.mkdir(parents=True, exist_ok=True)
cfg = yaml.safe_load((ROOT / "cases.yml").read_text())
tz = cfg.get("timezone", "Europe/Rome") # non usato qui, ma tienilo per coerenza


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
p = b["place"]
res = compute_tema(when, Place(**p), png_path)


elif ctype == "sinastria":
A = case["A"]; B = case["B"]
A = {"when": parse_dt(A["when"]), "place": A["place"], "name": A.get("name","A")}
B = {"when": parse_dt(B["when"]), "place": B["place"], "name": B.get("name","B")}
res = compute_sinastria(A, B, png_path)


elif ctype == "daily":
when = parse_dt(case["when"])
p = case["place"]
res = compute_oroscopo_daily(when, Place(**p), png_path)


elif ctype == "weekly":
start = parse_dt(case["start"])
N = int(case.get("sample_points", 7))
days = int(case.get("days", 7))
if "sampling" in case:
samples = [parse_dt(s) for s in case["sampling"]]
else:
step = max(1, days // max(1, N))
samples = [start + timedelta(days=i*step) for i in range(N)]
p = case["place"]
res = compute_oroscopo_period(samples, Place(**p), png_path)


elif ctype == "monthly":
month = case["month"] # YYYY-MM
year, m = map(int, month.split("-"))
N = int(case.get("sample_points", 10))
# campiona ogni ~3 giorni nel mese
samples = [datetime(year, m, 1) + timedelta(days=i*3) for i in range(N)]
p = case["place"]
res = compute_oroscopo_period(samples, Place(**p), png_path)


elif ctype == "annual":
year = int(case["year"])
N = int(case.get("sample_points", 120))
samples = [datetime(year, 1, 1) + timedelta(days=i*3) for i in range(N)]
p = case["place"]
res = compute_oroscopo_period(samples, Place(**p), png_path)


else:
raise ValueError(f"Tipo caso non supportato: {ctype}")


json_path.write_text(__import__('json').dumps(res, ensure_ascii=False, indent=2))
print(f"[OK] {cid} -> {json_path.name}, {png_path.name}")




if __name__ == "__main__":
ap = argparse.ArgumentParser()
ap.add_argument("--overwrite", action="store_true", help="Rigenera tutti i golden")
args = ap.parse_args()
main(overwrite=args.overwrite)
