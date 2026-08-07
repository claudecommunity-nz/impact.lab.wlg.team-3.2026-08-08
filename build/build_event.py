#!/usr/bin/env python3
"""Build the 20 April 2026 event bundle.

    python3 build/build_event.py            # rebuild from frozen sources
    python3 build/build_event.py --fetch     # refresh the network cache first
    python3 build/build_event.py --summary   # rebuild and print the breakdown

Deterministic. Same seed, same inputs, same bytes out - no network, no clock.
The only thing that touches the network is `--fetch`, and what it fetches is
frozen under `build/cache/` with the time it was fetched, which is what the
manifest quotes.

Output is `data/event/2026-04-20/`. The server knows nothing about it beyond its
shape; `push.py` reads it and plays it into the intake API.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cache  # noqa: E402
import feeds  # noqa: E402
import fetch  # noqa: E402
import incidents as incidents_mod  # noqa: E402
import observations  # noqa: E402
import stream  # noqa: E402

ROOT = HERE.parent
REPLAY = ROOT / "Mark's prep" / "data" / "replay" / "april-2026"
GAZETTEER = ROOT / "data" / "gazetteer.json"
OUT = ROOT / "data" / "event" / "2026-04-20"

# Fixed so the bundle is identical for everyone on the team and across runs.
SEED = 20260420

LAST_REPORT_AT = incidents_mod.at(22, 0)

GROUND_TRUTH_CAVEAT = (
    "Ground truth for this event comes from news reporting, not from a Council "
    "incident log. No such log is public. Times are approximate to the hour "
    "except the declaration, which was reported precisely."
)


def write(path: pathlib.Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return path.stat().st_size


def write_lines(path: pathlib.Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return path.stat().st_size


def manifest(files: dict[str, dict], truth: dict) -> dict:
    return {
        "event": truth["event"],
        "date": "2026-04-20",
        "built_by": "build/build_event.py",
        "seed": SEED,
        "note": (
            "A replayable bundle for the 20 April 2026 Wellington flooding. Real "
            "observations, generated reports and feeds, and an answer key held "
            "separately so triage can be scored rather than admired."
        ),
        "honesty": [
            "Every file below is marked real or generated. Every generated record "
            "carries a flag of its own as well.",
            "The report stream is generated in full. No Council intake data is "
            "public, so there was nothing real to use.",
            "Generated feed records are written into the real published schemas, "
            "read from the live services. The schemas are real; the records are not.",
            "No real people. No names, phone numbers, or house numbers on "
            "evacuated streets. Streets and suburbs only.",
            GROUND_TRUTH_CAVEAT,
            "This is not an operational emergency source. In an emergency, call 111.",
        ],
        "files": files,
        "attribution": {
            "rainfall and river level": {
                "publisher": "Greater Wellington Regional Council",
                "source": observations.HILLTOP,
                "licence": "GWRC Hilltop telemetry, public endpoint",
            },
            "transport counts": {
                "publisher": "Wellington City Council (Digital Innovation)",
                "source": "WCC open data, transport sensor countline CSVs on S3",
                "licence": "WCC open data",
            },
            "CAP alerts": {
                "publisher": "National Emergency Management Agency",
                "source": fetch.CAP_ALERTS,
                "licence": "CC BY 4.0 (NEMA open data)",
            },
            "schemas the generated feeds are written into": {
                "publisher": "Wellington Water, Wellington City Council, NEMA",
                "source": [fetch.WATER_FAULTS, fetch.ROAD_CLOSURES, fetch.OUTAGES],
                "licence": "see each publisher; field definitions only",
            },
            "place names": {
                "publisher": "Wellington City Council and OpenStreetMap contributors",
                "source": "data/gazetteer.json",
                "licence": "ODbL for the OpenStreetMap pass",
            },
        },
    }


def build(summary: bool) -> int:
    rng = random.Random(SEED)
    gaz = json.loads(GAZETTEER.read_text())["places"]
    truth = json.loads((REPLAY / "ground-truth.json").read_text())

    print("Building data/event/2026-04-20/\n")

    rainfall = observations.rainfall()
    river = observations.river()
    movement = observations.movement()
    alerts = observations.cap_alerts()

    catalogue = incidents_mod.Catalogue(rng, gaz, rainfall, truth)
    incident_list = catalogue.build()
    reports, key = stream.build(rng, incident_list, LAST_REPORT_AT)

    water = feeds.water_faults(rng, incident_list)
    closures = feeds.road_closures(rng, incident_list)
    power = feeds.outages(rng, incident_list)

    files = {}

    def record(name: str, path: pathlib.Path, origin: str, holds: str,
               source: str, publisher: str, licence: str,
               fetched_at: str | None = None, size: int = 0,
               frozen_at: str | None = None,
               provenance: str | None = None) -> None:
        files[name] = {
            "origin": origin, "holds": holds, "source": source,
            "publisher": publisher, "licence": licence,
            "fetched_at": fetched_at, "frozen_at": frozen_at,
            "provenance": provenance, "bytes": size,
        }

    size = write_lines(OUT / "reports.jsonl", reports)
    record("reports.jsonl", OUT, "generated",
           f"{len(reports)} incoming reports, 20 April 2026, sorted by arrival",
           "generated by build/build_event.py from ground truth and the gauge record",
           "this prototype", "none - generated content", size=size)

    size = write(OUT / "answer-key.json", {
        "note": (
            "Ground truth for scoring, held apart from the stream so a triage "
            "prototype is measured rather than admired. 'incident' groups reports "
            "that describe the same thing, so duplicate detection can be counted. "
            "'category' is a defensible reading of the brief's three buckets, not "
            "an official Council triage - argue with it."
        ),
        "categories": {
            "action": "someone must do something now",
            "verify": "plausible but unconfirmed; check before acting",
            "awareness": "useful context, no immediate action",
        },
        "fields": {
            "ambiguous": "the report named a place that exists in more than one "
                         "location. Refusing to place it is the right answer.",
            "unfounded": "placed where every nearby gauge was dry. Not proof it "
                         "is false - a burst main floods a street on a dry day.",
            "basis": "what in the ground truth or the gauge record justifies this.",
        },
        "caveat": GROUND_TRUTH_CAVEAT,
        "incidents": len({k["incident"] for k in key}),
        "key": key,
    })
    record("answer-key.json", OUT, "generated",
           f"truth for all {len(key)} reports across "
           f"{len({k['incident'] for k in key})} incidents",
           "derived from ground-truth.json and the gauge record",
           "this prototype", "none - generated content", size=size)

    for name, payload, holds in (
        ("rainfall.json", rainfall, f"hourly rainfall, {len(rainfall['reporting'])} "
                                    "reporting gauges"),
        ("river.json", river, f"river level, {len(river['gauges'])} gauges"),
        ("movement.json", movement, "hourly transport counts against baseline"),
        ("cap-alerts.json", alerts, f"{alerts['count']} CAP alerts broadcast "
                                    "18-23 April"),
    ):
        size = write(OUT / "observations" / name, payload)
        record(f"observations/{name}", OUT, "real", holds,
               payload.get("source", observations.HILLTOP),
               payload["publisher"],
               "CC BY 4.0 (NEMA open data)" if name == "cap-alerts.json"
               else "publisher's open data terms",
               payload.get("fetched_at"), size,
               payload.get("frozen_at"), payload.get("provenance"))

    for name, payload, holds in (
        ("water-faults.json", water, f"{len(water['features'])} generated "
                                     "Wellington Water job records"),
        ("road-closures.json", closures, f"{len(closures['features'])} generated "
                                         "road closures"),
        ("outages.json", power, f"{len(power['features'])} generated electricity "
                                "outages"),
    ):
        size = write(OUT / "feeds" / name, payload)
        record(f"feeds/{name}", OUT, "generated",
               holds + ", written into the real published schema",
               payload["schema_source"], payload["schema_publisher"],
               payload["schema_licence"] + " (schema only)",
               payload["schema_fetched_at"], size)

    write(OUT / "manifest.json", manifest(files, truth))

    print(f"  reports.jsonl      {len(reports)} reports")
    print(f"  answer-key.json    {len(key)} keyed, "
          f"{len({k['incident'] for k in key})} incidents")
    print(f"  observations/      {len(rainfall['reporting'])} rain gauges, "
          f"{len(river['gauges'])} river gauges, {alerts['count']} CAP alerts")
    print(f"  feeds/             {len(water['features'])} water, "
          f"{len(closures['features'])} closures, {len(power['features'])} outages")

    if summary:
        print_summary(reports, key, rainfall)
    return 0


def print_summary(reports: list[dict], key: list[dict], rainfall: dict) -> None:
    by_id = {k["id"]: k for k in key}
    print("\nBy channel")
    total = len(reports)
    for channel, count in collections.Counter(
            r["channel"] for r in reports).most_common():
        print(f"  {channel:9} {count:4}  {count / total:5.1%}")

    print("\nBy hour, against region-wide rainfall")
    hourly_mm = collections.Counter()
    for gauge in rainfall["reporting"].values():
        for hour, mm in gauge["hourly_mm"].items():
            hourly_mm[int(hour)] += mm
    per_hour = collections.Counter(
        datetime.datetime.fromisoformat(r["received_at"]).hour for r in reports)
    for hour in sorted(per_hour):
        bar = "#" * round(per_hour[hour] / 2)
        print(f"  {hour:02d}:00 {per_hour[hour]:4}  {hourly_mm[hour]:6.1f} mm  {bar}")

    sizes = collections.Counter(collections.Counter(
        k["incident"] for k in key).values())
    print("\nCluster sizes")
    for size in sorted(sizes):
        print(f"  {size} report(s)  {sizes[size]:3} incident(s)")

    print("\nAnswer key")
    print(f"  {sum(1 for k in key if k['unfounded'])} unfounded, placed where "
          "gauges were dry")
    print(f"  {sum(1 for k in key if k['ambiguous'])} named a place that exists "
          "in more than one location")
    print(f"  {sum(1 for k in key if k['true_lat'] is None)} with no resolvable "
          "location")
    for category, count in collections.Counter(
            k["category"] for k in key).most_common():
        print(f"  {category:9} {count:4}")
    assert len(by_id) == len(reports), "answer key does not cover every report once"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true",
                        help="refresh the network cache before building")
    parser.add_argument("--summary", action="store_true",
                        help="print counts by channel, hour, incident and category")
    args = parser.parse_args()

    if args.fetch:
        fetch.all_sources()
        print()
    try:
        return build(args.summary)
    except cache.MissingCache as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
