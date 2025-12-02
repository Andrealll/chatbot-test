from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo
import calendar

from .loader import get_config, ConfigError

Scope = Literal["daily","weekly","monthly","yearly"]
Tier  = Literal["free","premium"]

WEEKDAY_TO_INT = {
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6
}

def _parse_hhmm(hhmm: str) -> time:
    hh, mm = map(int, hhmm.split(":"))
    return time(hh, mm)

def _add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)

def resolve_snapshots(scope: Scope, tier: Tier,
                      start_date: Optional[date] = None,
                      horizon_days: Optional[int] = None) -> List[datetime]:
    cfg = get_config("snapshots", scope, tier)
    tz = ZoneInfo(cfg.get("timezone", "Europe/Rome"))
    today = datetime.now(tz).date() if start_date is None else start_date
    out: List[datetime] = []
    strat = cfg["strategy"]

    def add_dt(d: date, hhmm: str):
        out.append(datetime.combine(d, _parse_hhmm(hhmm), tz))

    if scope == "daily":
        if strat == "fixed_times":
            for hhmm in cfg["times"]:
                add_dt(today, hhmm)
        else:
            raise ConfigError(f"strategy {strat} non supportata per daily")
        return sorted(out)

    if scope == "weekly":
        days = horizon_days or 7
        end_date = _add_days(today, days-1)
        if strat == "weekdays_times":
            items = cfg["items"]
            d = today
            while d <= end_date:
                wd = d.weekday()
                for it in items:
                    if WEEKDAY_TO_INT[it["weekday"]] == wd:
                        add_dt(d, it["time"])
                d = _add_days(d, 1)
        elif strat == "fixed_times":
            d = today
            while d <= end_date:
                for hhmm in cfg["times"]:
                    add_dt(d, hhmm)
                d = _add_days(d, 1)
        else:
            raise ConfigError(f"strategy {strat} non supportata per weekly")
        return sorted(out)

    if scope == "monthly":
        if strat == "days_of_month":
            y, m = today.year, today.month
            last_day = calendar.monthrange(y, m)[1]
            target_time = cfg["time"]
            for day in cfg["days"]:
                if 1 <= day <= last_day:
                    add_dt(date(y, m, day), target_time)
        elif strat == "every_n_days":
            n = int(cfg["n"])
            max_events = int(cfg.get("max_events", 10))
            target_time = cfg["time"]
            d = today
            count = 0
            horizon = horizon_days or 31
            end_date = _add_days(today, horizon-1)
            while d <= end_date and count < max_events:
                add_dt(d, target_time)
                d = _add_days(d, n)
                count += 1
        else:
            raise ConfigError(f"strategy {strat} non supportata per monthly")
        return sorted(out)

    if scope == "yearly":
        if strat == "monthly_on_day":
            target_day = int(cfg["day"])
            target_time = cfg["time"]
            for i in range(12):
                y = today.year + (today.month - 1 + i) // 12
                m = ((today.month - 1 + i) % 12) + 1
                last_day = calendar.monthrange(y, m)[1]
                day = min(target_day, last_day)
                add_dt(date(y, m, day), target_time)
        elif strat == "every_n_days":
            n = int(cfg["n"])
            max_events = int(cfg.get("max_events", 120))
            target_time = cfg["time"]
            d = today
            count = 0
            horizon = horizon_days or 365
            end_date = _add_days(today, horizon-1)
            while d <= end_date and count < max_events:
                add_dt(d, target_time)
                d = _add_days(d, n)
                count += 1
        else:
            raise ConfigError(f"strategy {strat} non supportata per yearly")
        return sorted(out)

    raise ConfigError(f"scope non supportato: {scope}")
