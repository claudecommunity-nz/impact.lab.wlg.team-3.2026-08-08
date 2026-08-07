#!/usr/bin/env python3
"""Build the April 2026 Wellington flood replay bundle from public sources.

Why this exists: on a calm Saturday every live emergency feed is empty by
design. GWRC's incident layer, WCC's Emergency Assistance Centres layer and the
Civil Defence alert RSS all publish nothing between events. A prototype that
reads them live has nothing to show at demo time.

This rebuilds a real Wellington emergency from data that is still retrievable,
so a prototype can be driven against something that actually happened.

    python3 scripts/build_replay.py

Writes data/replay/april-2026/. Downloads about 180 MB of monthly count CSVs on
first run and caches them in data/cache/ (gitignored).
"""

from __future__ import annotations

import argparse
import csv
import collections
import datetime
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sources  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "replay" / "april-2026"
CACHE = ROOT / "data" / "cache"

# The event window, and the months either side used to build a baseline of
# normal movement. One month is not enough: it gives only four samples per
# weekday, so a single public holiday drags the median badly.
EVENT_MONTHS = [(2026, 2), (2026, 3), (2026, 4), (2026, 5)]
EVENT_START = datetime.date(2026, 4, 18)
EVENT_END = datetime.date(2026, 4, 22)

# Days excluded when computing "normal", because they are known not to be.
# NZ public holidays in the window plus the event itself.
HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-02", "2026-01-19", "2026-02-06",
    "2026-04-03", "2026-04-06", "2026-04-27", "2026-06-01",
}
EVENT_DAYS = {"2026-04-18", "2026-04-19", "2026-04-20", "2026-04-21", "2026-04-22"}

EXPOSED_MODES = ("Cyclist", "E-scooter", "Motorbike")
ENCLOSED_MODES = ("Car", "Bus", "LGV", "OGV1", "OGV2")


def log(msg: str) -> None:
    print(msg, flush=True)


def cached_download(url: str, name: str) -> pathlib.Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists() and path.stat().st_size > 0:
        return path
    log(f"  downloading {name} ...")
    path.write_bytes(sources.get(url, timeout=600))
    return path


def build_movement() -> dict:
    """Hourly movement for the event window, plus a weekday/hour baseline."""
    hourly: dict[tuple[str, int], collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    per_countline: dict[tuple[str, int], collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for year, month in EVENT_MONTHS:
        path = cached_download(
            sources.countline_counts_url(year, month), f"counts_{year}_{month:02d}.csv"
        )
        log(f"  reading {path.name}")
        with path.open() as fh:
            for row in csv.DictReader(fh):
                day = row["COUNTLINE_DATE"]
                hour = int(row["COUNTLINE_HOUR"])
                count = int(row["DIRECTION_COUNT"])
                hourly[(day, hour)][row["COUNTLINE_TRANSPORT_CLASS"]] += count
                if EVENT_START.isoformat() <= day <= EVENT_END.isoformat():
                    per_countline[(day, hour)][row["COUNTLINE_ID"]] += count

    # Baseline: median across the same weekday and hour, over all four months,
    # excluding public holidays and the event itself.
    #
    # The mode-ratio baseline has to be built here, from the same clean days.
    # Deriving it later from the window's own shoulder days does not work: 18
    # April already had 30 mm of rain, so a baseline drawn from it is a storm
    # measured against a storm.
    buckets: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    ratio_buckets: dict[tuple[int, int], list[float]] = collections.defaultdict(list)
    for (day, hour), classes in hourly.items():
        if day in HOLIDAYS_2026 or day in EVENT_DAYS:
            continue
        weekday = datetime.date.fromisoformat(day).weekday()
        buckets[(weekday, hour)].append(sum(classes.values()))
        enclosed = sum(classes.get(m, 0) for m in ENCLOSED_MODES)
        exposed = sum(classes.get(m, 0) for m in EXPOSED_MODES)
        if enclosed >= 500:
            ratio_buckets[(weekday, hour)].append(1000.0 * exposed / enclosed)
    baseline = {
        f"{wd}:{hr}": {
            "median": statistics.median(vals),
            "n": len(vals),
            "ratio_median": (
                statistics.median(ratio_buckets[(wd, hr)])
                if ratio_buckets.get((wd, hr))
                else None
            ),
            "ratio_n": len(ratio_buckets.get((wd, hr), [])),
        }
        for (wd, hr), vals in buckets.items()
    }

    # Per-countline baseline by hour of day, from clean weekdays only. Weekends
    # have a different enough shape that mixing them in flattens the peaks and
    # makes every weekday morning look like an anomaly.
    #
    # Rows are per class and direction, so sum each countline's day-hour first
    # and take the median across days - a median of raw rows would be the median
    # of one class, not of the traffic.
    per_countline_day: collections.Counter = collections.Counter()
    for year, month in EVENT_MONTHS:
        path = CACHE / f"counts_{year}_{month:02d}.csv"
        with path.open() as fh:
            for row in csv.DictReader(fh):
                day = row["COUNTLINE_DATE"]
                if day in HOLIDAYS_2026 or day in EVENT_DAYS:
                    continue
                if datetime.date.fromisoformat(day).weekday() >= 5:
                    continue
                per_countline_day[
                    (row["COUNTLINE_ID"], day, int(row["COUNTLINE_HOUR"]))
                ] += int(row["DIRECTION_COUNT"])
    grouped: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for (cid, _day, hour), total in per_countline_day.items():
        grouped[(cid, hour)].append(total)
    countline_baseline: dict[str, dict[str, float]] = collections.defaultdict(dict)
    for (cid, hour), vals in grouped.items():
        if len(vals) >= 5:
            countline_baseline[cid][str(hour)] = round(statistics.median(vals), 1)

    window = {}
    day = EVENT_START
    while day <= EVENT_END:
        key = day.isoformat()
        for hour in range(24):
            classes = hourly.get((key, hour))
            if not classes:
                continue
            window[f"{key}T{hour:02d}"] = {
                "total": sum(classes.values()),
                "by_class": dict(classes),
                "by_countline": dict(per_countline.get((key, hour), {})),
            }
        day += datetime.timedelta(days=1)

    return {
        "baseline": baseline,
        "countline_baseline": countline_baseline,
        "countline_baseline_note": (
            "median count for that countline at that hour of day, across clean "
            "weekdays only; omitted where fewer than 5 samples"
        ),
        "baseline_note": (
            "median total movements for the same weekday and hour across Feb-May "
            "2026, excluding NZ public holidays and the event window"
        ),
        "window": window,
        "exposed_modes": list(EXPOSED_MODES),
        "enclosed_modes": list(ENCLOSED_MODES),
    }


def build_rainfall() -> dict:
    """Hourly rainfall for every Wellington gauge that was actually reporting."""
    log("  listing rainfall gauges")
    sites = [s for s in sources.hilltop_sites("Rainfall") if sources.in_wellington(s)]
    log(f"  {len(sites)} gauges listed in the Wellington bbox; probing each")
    start = (EVENT_START - datetime.timedelta(days=2)).isoformat()
    end = (EVENT_END + datetime.timedelta(days=1)).isoformat()

    reporting, silent = {}, []
    for site in sites:
        if site["name"].startswith("__"):
            continue
        try:
            series = sources.hilltop_series(site["name"], "Rainfall", start, end)
        except sources.HilltopError:
            silent.append(site["name"])
            sources.polite()
            continue
        except Exception as exc:  # noqa: BLE001 - network flakiness, keep going
            log(f"    {site['name']}: {exc}")
            silent.append(site["name"])
            sources.polite()
            continue
        if series:
            reporting[site["name"]] = {
                "lat": site["lat"],
                "lon": site["lon"],
                "series": [[t, v] for t, v in series],
                "total_mm": round(sum(v for _, v in series), 1),
            }
        else:
            silent.append(site["name"])
        sources.polite()

    log(f"  {len(reporting)} gauges reporting, {len(silent)} listed but silent")
    return {
        "reporting": reporting,
        "listed_but_silent": silent,
        "note": (
            "Gauges appear in Hilltop's SiteList for a measurement even when they "
            "hold no data for the window. Being listed is not being live."
        ),
    }


def build_river() -> dict:
    """River level for gauges around the city, where available."""
    candidates = [
        "Hutt River at Taita Gorge",
        "Hutt River at Kaitoke",
        "Karori Stream at Duthie Street",
        "Kaiwharawhara Stream at Ngaio Gorge",
        "Porirua Stream at Town Centre",
        "Wainuiomata River at Manuka Track",
    ]
    start = (EVENT_START - datetime.timedelta(days=2)).isoformat()
    end = (EVENT_END + datetime.timedelta(days=1)).isoformat()
    out, missing = {}, []
    for name in candidates:
        try:
            series = sources.hilltop_series(name, "Stage", start, end)
        except Exception:  # noqa: BLE001
            missing.append(name)
            sources.polite()
            continue
        if series:
            out[name] = {"units": "mm", "series": [[t, v] for t, v in series]}
        else:
            missing.append(name)
        sources.polite()
    log(f"  {len(out)} river gauges with data, {len(missing)} without")
    return {"gauges": out, "no_data": missing}


def build_countlines() -> dict:
    """Countline positions, from the published metadata CSV."""
    path = cached_download(sources.COUNTLINE_META_URL, "countline_meta_info.csv")
    features = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            try:
                lat = float(row["LATITUDE_START_LINE"])
                lon = float(row["LONGITUDE_START_LINE"])
            except (TypeError, ValueError):
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "countline_id": row["COUNTLINE_ID"],
                        "name": row["NAME"],
                        "earliest": row["EARLIEST"],
                        "latest": row["LATEST"],
                    },
                }
            )
    log(f"  {len(features)} countlines with coordinates")
    return {"type": "FeatureCollection", "features": features}


# What actually happened, from contemporaneous public reporting. Held separately
# from the measurements so a prototype can be scored against ground truth.
GROUND_TRUTH = {
    "event": "Wellington region flooding, April 2026",
    "declaration": {
        "at": "2026-04-20T17:25:00+12:00",
        "what": "State of emergency declared for the Wellington region",
        "by": "Wellington CDEM Group joint committee",
    },
    "timeline": [
        {"at": "2026-04-20T02:00:00+12:00", "what": "Fire crews begin responding to weather callouts"},
        {"at": "2026-04-20T16:30:00+12:00", "what": "Close to 200 weather-related callouts attended since 02:00"},
        {"at": "2026-04-20T17:25:00+12:00", "what": "State of emergency declared"},
        {"at": "2026-04-20T18:00:00+12:00", "what": "Emergency Assistance Centre opened, Wellington City Mission, Oxford Terrace"},
    ],
    "evacuations": [
        {"street": "Konini Street (northern end)", "suburb": "Wainuiomata"},
        {"street": "Wetherby Street", "suburb": "Wainuiomata"},
        {"street": "Rata Street", "suburb": "Wainuiomata"},
    ],
    "uninhabitable_dwellings": {
        "count_approx": 10,
        "suburbs": ["Berhampore", "Mornington", "South Karori"],
    },
    "reported_rainfall": "More than 70 mm in under an hour across parts of southern Wellington",
    "sources": [
        "https://www.rnz.co.nz/news/top/592870/weather-state-of-emergency-declared-for-wellington",
        "https://www.rnz.co.nz/news/weather/592805/weather-state-of-emergency-in-wellington-as-more-rain-arrives-after-floods-slips",
        "https://thespinoff.co.nz/society/20-04-2026/wellington-region-state-of-emergency-what-you-need-to-know",
    ],
    "caveat": (
        "Timeline entries come from news reporting, not from a Council incident "
        "log. Treat times as approximate to the hour except the declaration, "
        "which is reported precisely."
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=["movement", "countlines", "rainfall", "river"],
        action="append",
        help="rebuild only these parts (repeatable). Rainfall probes 51 gauges "
        "over the network and takes several minutes.",
    )
    args = parser.parse_args()
    wanted = set(args.only or ["movement", "countlines", "rainfall", "river"])

    OUT.mkdir(parents=True, exist_ok=True)
    log("Building April 2026 replay bundle")

    if "movement" in wanted:
        log("movement:")
        (OUT / "movement.json").write_text(json.dumps(build_movement()))
    if "countlines" in wanted:
        log("countlines:")
        (OUT / "countlines.geojson").write_text(json.dumps(build_countlines()))
    if "rainfall" in wanted:
        log("rainfall:")
        (OUT / "rainfall.json").write_text(json.dumps(build_rainfall()))
    if "river" in wanted:
        log("river:")
        (OUT / "river.json").write_text(json.dumps(build_river()))
    (OUT / "ground-truth.json").write_text(json.dumps(GROUND_TRUTH, indent=2))

    manifest = {
        "event": GROUND_TRUTH["event"],
        "window": {"start": EVENT_START.isoformat(), "end": EVENT_END.isoformat()},
        "files": {
            "movement.json": "hourly counts in the window, plus weekday/hour baseline",
            "countlines.geojson": "sensor countline positions",
            "rainfall.json": "hourly rainfall per reporting gauge",
            "river.json": "river level per gauge",
            "ground-truth.json": "what actually happened, for scoring",
        },
        "licences": {
            "transport counts": "WCC open data",
            "rainfall and river": "Greater Wellington Regional Council, Hilltop telemetry",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"\nWrote {OUT}")
    for path in sorted(OUT.iterdir()):
        log(f"  {path.name}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
