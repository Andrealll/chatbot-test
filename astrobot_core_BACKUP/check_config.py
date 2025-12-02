
# check_config.py — script di verifica rapida
from astrobot_core.config.schedule import resolve_snapshots
from datetime import date

def show(scope, tier, horizon=None):
    snaps = resolve_snapshots(scope, tier, start_date=date.today(), horizon_days=horizon)
    print(f"{scope}/{tier}: {len(snaps)}")
    for dt in snaps[:10]:
        print(" -", dt.isoformat())

if __name__ == "__main__":
    show("daily", "free")
    show("daily", "premium")
    show("weekly", "free")
    show("weekly", "premium")
    show("monthly", "free")
    show("monthly", "premium", horizon=31)
    show("yearly", "free")
    show("yearly", "premium", horizon=365)
