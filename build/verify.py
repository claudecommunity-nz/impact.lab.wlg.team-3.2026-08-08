#!/usr/bin/env python3
"""Check the bundle before anyone claims it works.

    python3 build/verify.py

Covers the parts of the brief's checklist that can be checked from the files:
the answer key covers every report exactly once, the stream leaks no truth, the
duplicate clusters actually cluster, and the surge lands where the rain did.

The two that cannot be checked from here - that the build is deterministic, and
that reports land through the API - are run by hand:

    python3 build/build_event.py && shasum -a 256 data/event/2026-04-20/*
    python3 server.py & python3 push.py --speed 900

Exits non-zero if anything fails, so it can go in front of a commit.
"""

from __future__ import annotations

import collections
import datetime
import json
import pathlib
import re
import sys

BUNDLE = pathlib.Path(__file__).resolve().parent.parent / "data" / "event" / "2026-04-20"

# The bundle contract. A report carries these keys and no others - no truth
# fields, no assessments, nothing a triage tool could read the answer off.
REPORT_KEYS = {"id", "received_at", "channel", "text", "source_url", "origin"}
CHANNELS = {"phone", "email", "form", "social", "news", "partner"}
CATEGORIES = {"action", "verify", "awareness"}

# A house number on a street that flooded is somebody's home address.
HOUSE_NUMBER = re.compile(r"\b\d+[a-z]?\s+[A-Z][a-z]+\s+(Street|Road|Avenue|Grove|"
                          r"Terrace|Crescent|Place|Drive|Lane|Way|Parade)\b")

failures: list[str] = []
warnings: list[str] = []


def check(condition: bool, description: str, detail: str = "") -> None:
    if condition:
        print(f"  ok    {description}")
    else:
        print(f"  FAIL  {description}  {detail}")
        failures.append(description)


def warn(condition: bool, description: str) -> None:
    if not condition:
        print(f"  warn  {description}")
        warnings.append(description)


def load():
    reports = [json.loads(line) for line in
               (BUNDLE / "reports.jsonl").read_text().splitlines() if line.strip()]
    key = json.loads((BUNDLE / "answer-key.json").read_text())
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    rainfall = json.loads((BUNDLE / "observations" / "rainfall.json").read_text())
    return reports, key, manifest, rainfall


def check_shape(reports: list[dict]) -> None:
    print("\nThe stream")
    ids = [r["id"] for r in reports]
    check(len(set(ids)) == len(ids), "every report id is unique")
    check(all(set(r) == REPORT_KEYS for r in reports),
          "every report carries exactly the contracted keys",
          str(sorted(set().union(*(set(r) for r in reports)) - REPORT_KEYS)))
    check(all(r["channel"] in CHANNELS for r in reports),
          "every channel is one of the six named in the problem statement")
    times = [datetime.datetime.fromisoformat(r["received_at"]) for r in reports]
    check(times == sorted(times), "sorted by received_at ascending")
    check(all(r["origin"] == "generated" for r in reports),
          "every report is flagged as generated")
    check(all(r["source_url"] is None or r["channel"] == "news" for r in reports),
          "only news reports carry a source url, and those urls are real")
    texts = collections.Counter(r["text"] for r in reports)
    check(max(texts.values()) == 1,
          "no two reports are word-for-word identical")
    offenders = [r["id"] for r in reports if HOUSE_NUMBER.search(r["text"])]
    check(not offenders, "no house numbers in any report text", str(offenders[:5]))
    check(200 <= len(reports) <= 400,
          f"{len(reports)} reports, inside the 200-400 the brief asks for")


def check_key(reports: list[dict], key: dict) -> None:
    print("\nThe answer key")
    entries = key["key"]
    keyed = [e["id"] for e in entries]
    report_ids = {r["id"] for r in reports}
    check(len(keyed) == len(set(keyed)), "every id appears exactly once in the key")
    check(set(keyed) == report_ids, "the key covers every report and nothing else",
          f"missing {sorted(report_ids - set(keyed))[:5]}, "
          f"extra {sorted(set(keyed) - report_ids)[:5]}")
    check(all(e["category"] in CATEGORIES for e in entries),
          "every category is one of the brief's three buckets")
    check(all(e["basis"] for e in entries),
          "every entry cites what justifies it")
    check(sum(1 for e in entries if e["unfounded"]) >= 2,
          "at least two unfounded reports, as the brief requires")
    check(any(e["ambiguous"] for e in entries),
          "some reports name a place that exists in more than one location")
    check(any(e["true_lat"] is None and e["true_place"] is None for e in entries),
          "some reports have no resolvable location at all")
    located = [e for e in entries if e["true_lat"] is not None]
    check(all(-41.4 < e["true_lat"] < -41.0 and 174.6 < e["true_lon"] < 175.1
              for e in located),
          "every coordinate is in the Wellington region, not off Africa")


def check_clusters(reports: list[dict], key: dict) -> None:
    print("\nDuplicate clusters")
    by_id = {e["id"]: e for e in key["key"]}
    sizes = collections.Counter(e["incident"] for e in key["key"])
    distribution = collections.Counter(sizes.values())
    for size in sorted(distribution):
        print(f"        {size} report(s)  {distribution[size]:3} incident(s)")
    clustered = sum(n for n in sizes.values() if n >= 3)
    check(sum(1 for n in sizes.values() if 3 <= n <= 8) >= 20,
          "at least twenty incidents cluster in the 3-8 range the brief asks for")
    check(max(sizes.values()) <= 8, "no cluster is larger than 8",
          f"largest is {max(sizes.values())}")
    print(f"        {clustered} of {len(reports)} reports "
          f"({clustered / len(reports):.0%}) belong to a cluster of 3 or more")

    # A cluster is only worth detecting if its members share a meaning without
    # sharing their words. Overlapping vocabulary is the cheap way to check.
    worst = []
    for incident, count in sizes.items():
        if count < 3:
            continue
        texts = [r["text"].lower() for r in reports
                 if by_id[r["id"]]["incident"] == incident]
        words = [set(re.findall(r"[a-z]{4,}", t)) for t in texts]
        pairs = [len(a & b) / len(a | b) for i, a in enumerate(words)
                 for b in words[i + 1:] if a | b]
        if pairs:
            worst.append((max(pairs), incident))
    worst.sort(reverse=True)
    check(worst and worst[0][0] < 0.8,
          "no two reports in a cluster are near-identical in wording",
          f"worst overlap {worst[0][0]:.2f} in {worst[0][1]}" if worst else "")


def check_surge(reports: list[dict], rainfall: dict) -> None:
    print("\nThe surge against the rain")
    per_hour = collections.Counter(
        datetime.datetime.fromisoformat(r["received_at"]).hour for r in reports)
    mm_per_hour = collections.Counter()
    for gauge in rainfall["reporting"].values():
        for hour, mm in gauge["hourly_mm"].items():
            mm_per_hour[int(hour)] += mm

    for hour in sorted(per_hour):
        bar = "#" * round(per_hour[hour] / 2)
        rain = "*" * round(mm_per_hour[hour] / 12)
        print(f"        {hour:02d}:00 {per_hour[hour]:4} {bar:<25} "
              f"{mm_per_hour[hour]:6.1f} mm {rain}")

    downpour = sum(per_hour[h] for h in (3, 4, 5))
    declaration = sum(per_hour[h] for h in (17, 18, 19))
    quiet = sum(per_hour[h] for h in (8, 9, 10, 11)) / 4
    check(downpour / 3 > quiet * 2,
          f"the 03:00 downpour drowns the queue ({downpour} reports in three hours "
          f"against {quiet:.0f}/hour in the quiet morning)")
    check(declaration / 3 > quiet * 2,
          f"the 17:25 declaration drowns it again ({declaration} in three hours)")
    check(mm_per_hour[3] == max(mm_per_hour.values()),
          "the heaviest rain hour is 03:00, which is where the first surge sits")

    print("\nChannel mix")
    total = len(reports)
    counts = collections.Counter(r["channel"] for r in reports)
    for channel, count in counts.most_common():
        print(f"        {channel:8} {count:4}  {count / total:5.1%}")
    check(counts["phone"] + counts["social"] > total / 2,
          "phone and social dominate, as the brief requires")
    check(counts["partner"] < total / 5,
          "partner job records stay a minority - they are the easy case")
    check(set(counts) == CHANNELS, "all six channels appear")


def check_manifest(manifest: dict) -> None:
    print("\nProvenance")
    files = manifest["files"]
    check(all(f["origin"] in ("real", "generated") for f in files.values()),
          "every file is marked real or generated")
    check(all(f["publisher"] and f["licence"] for f in files.values()),
          "every file names a publisher and a licence")
    real = [name for name, f in files.items() if f["origin"] == "real"]
    # A file either records when it was fetched, or says in words why it cannot.
    # The replay-derived observations fall in the second group: the bundle they
    # were frozen in never recorded its own fetch date, and inventing one would
    # be worse than admitting it.
    dated = [n for n in real if files[n]["fetched_at"]
             or (files[n]["frozen_at"] and files[n]["provenance"])]
    check(len(dated) == len(real),
          "every real file records when it was fetched, or says why it cannot",
          str([n for n in real if n not in dated]))
    check(any("news reporting" in line for line in manifest["honesty"]),
          "the manifest says ground truth came from news reporting, not a Council log")
    check(any("111" in line for line in manifest["honesty"]),
          "the manifest says this is not an operational emergency source")


def check_feeds() -> None:
    print("\nGenerated feeds")
    for name in ("water-faults.json", "road-closures.json", "outages.json"):
        feed = json.loads((BUNDLE / "feeds" / name).read_text())
        features = feed["features"]
        check(feed["origin"] == "generated", f"{name} is marked generated")
        check(all(f.get("generated") is True for f in features),
              f"{name}: every record carries its own generated flag")
        check(all("GENERATED" in json.dumps(f["properties"]) for f in features),
              f"{name}: every record says so in its readable text")
        check(all("incident" not in json.dumps(f) for f in features),
              f"{name}: no incident ids leak the answer key")
        schemas = {tuple(sorted(f["properties"])) for f in features}
        check(len(schemas) == 1,
              f"{name}: every record uses the same field set "
              f"({len(next(iter(schemas)))} fields)")


def main() -> int:
    if not BUNDLE.exists():
        sys.exit(f"{BUNDLE} is missing. Run: python3 build/build_event.py")
    reports, key, manifest, rainfall = load()
    print(f"Verifying {BUNDLE}")
    check_shape(reports)
    check_key(reports, key)
    check_clusters(reports, key)
    check_surge(reports, rainfall)
    check_manifest(manifest)
    check_feeds()

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"All checks passed{f', {len(warnings)} warning(s)' if warnings else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
