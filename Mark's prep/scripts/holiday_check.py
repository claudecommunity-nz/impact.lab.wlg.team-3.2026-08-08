#!/usr/bin/env python3
"""Show why total traffic volume alone cannot tell a holiday from an emergency.

Reproduces the daily table behind docs/findings.md. Needs the monthly count CSVs
in data/cache/, which scripts/build_replay.py downloads.

    python3 scripts/holiday_check.py
"""

from __future__ import annotations

import collections
import csv
import datetime
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import build_replay  # noqa: E402
import detect_disruption  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
RAINFALL = ROOT / "data" / "replay" / "april-2026" / "rainfall.json"

NAMED_DAYS = {
    "2026-04-03": "Good Friday",
    "2026-04-05": "Easter Sunday",
    "2026-04-06": "Easter Monday",
    "2026-04-20": "EMERGENCY DECLARED",
    "2026-04-21": "day after",
    "2026-04-27": "ANZAC Day observed",
}


def main() -> int:
    months = sorted(CACHE.glob("counts_2026_*.csv"))
    if not months:
        print("No cached counts. Run scripts/build_replay.py first.", file=sys.stderr)
        return 1

    daily: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for path in months:
        with path.open() as fh:
            for row in csv.DictReader(fh):
                daily[row["COUNTLINE_DATE"]][row["COUNTLINE_TRANSPORT_CLASS"]] += int(
                    row["DIRECTION_COUNT"]
                )

    def ratio(classes: collections.Counter) -> float | None:
        enclosed = sum(classes[m] for m in build_replay.ENCLOSED_MODES)
        exposed = sum(classes[m] for m in build_replay.EXPOSED_MODES)
        return 1000.0 * exposed / enclosed if enclosed else None

    # Baselines by weekday, from days that are neither holidays nor the event.
    vol_base: dict[int, list[int]] = collections.defaultdict(list)
    rat_base: dict[int, list[float]] = collections.defaultdict(list)
    for day, classes in daily.items():
        if day in build_replay.HOLIDAYS_2026 or day in build_replay.EVENT_DAYS:
            continue
        weekday = datetime.date.fromisoformat(day).weekday()
        vol_base[weekday].append(sum(classes.values()))
        r = ratio(classes)
        if r:
            rat_base[weekday].append(r)
    vol_med = {k: statistics.median(v) for k, v in vol_base.items()}
    rat_med = {k: statistics.median(v) for k, v in rat_base.items()}

    rain_daily: dict[str, float] = collections.defaultdict(float)
    if RAINFALL.exists():
        rain = json.loads(RAINFALL.read_text())
        for gauge in rain["reporting"].values():
            for stamp, mm in gauge["series"]:
                rain_daily[stamp[:10]] = max(rain_daily[stamp[:10]], 0)
        for name, gauge in rain["reporting"].items():
            per_day: dict[str, float] = collections.defaultdict(float)
            for stamp, mm in gauge["series"]:
                per_day[stamp[:10]] += mm
            for day, total in per_day.items():
                rain_daily[day] = max(rain_daily[day], total)

    print("April 2026, daily. Baseline is the same weekday across Feb-May,")
    print("excluding NZ public holidays and the event window.\n")
    print(f"{'date':12}{'dow':5}{'volume':>11}{'vs base':>9}{'mode mix':>10}"
          f"{'wettest':>9}   verdict")
    for day in sorted(d for d in daily if d.startswith("2026-04")):
        classes = daily[day]
        weekday = datetime.date.fromisoformat(day).weekday()
        total = sum(classes.values())
        vol_pct = 100 * (total - vol_med[weekday]) / vol_med[weekday]
        r = ratio(classes)
        rat_pct = 100 * (r - rat_med[weekday]) / rat_med[weekday] if r and rat_med.get(weekday) else 0.0
        mm = rain_daily.get(day)

        if vol_pct > detect_disruption.VOLUME_DROP:
            verdict = ""
        elif rat_pct <= detect_disruption.RATIO_DROP:
            verdict = "storm-like"
        else:
            verdict = "holiday-like"
        note = NAMED_DAYS.get(day, "")
        wet = f"{mm:.0f} mm" if mm else ("-" if mm == 0 else "")
        print(f"{day:12}{datetime.date.fromisoformat(day).strftime('%a'):5}"
              f"{total:11,}{vol_pct:+8.0f}%{rat_pct:+9.0f}%{wet:>9}   "
              f"{verdict}{'  <- ' + note if note else ''}")

    print("\nRainfall column is the wettest reporting gauge that day, and only")
    print("covers 16-22 April - the window the replay bundle fetched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
