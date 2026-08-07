#!/usr/bin/env python3
"""Detect city-scale movement disruption from WCC transport sensor counts.

Problem 5 asks for sudden movement changes that indicate disruption or
evacuation, with the limitations kept visible. The hard part is not spotting a
drop - it is telling a drop caused by an emergency apart from a drop caused by
a public holiday, which looks almost identical in total volume.

The discriminator used here is mode composition. On a public holiday people
simply make fewer trips, and the mix of how they travel barely moves. In heavy
rain they also switch out of the exposed modes - bike, scooter, motorbike -
into cars and buses. So volume alone is ambiguous; volume plus a collapse in
the exposed-to-enclosed ratio is not.

    python3 scripts/detect_disruption.py

Runs against the committed April 2026 replay bundle and scores itself against
what actually happened.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "replay" / "april-2026"

# Thresholds, fitted to one event's worth of evidence. See "Known limits".
#
# The ratio threshold is set from the daily separation in scripts/holiday_check.py:
# across April 2026 every day with real rain sat at -51% or worse, and all three
# public holidays sat at -27% or better. -45% is the midpoint of that gap. An
# earlier -12% was fitted against a thinner baseline and flagged all three
# holidays as storms.
VOLUME_DROP = -15.0   # percent below the weekday/hour baseline
RATIO_DROP = -45.0    # percent below baseline exposed:enclosed ratio


def load(name: str):
    return json.loads((BUNDLE / name).read_text())


def mode_ratio(by_class: dict, exposed: list[str], enclosed: list[str]) -> float | None:
    """Exposed modes per 1000 enclosed. None when the sample is too thin."""
    e = sum(by_class.get(m, 0) for m in exposed)
    n = sum(by_class.get(m, 0) for m in enclosed)
    if n < 500:
        return None
    return 1000.0 * e / n


def classify(volume_pct: float, ratio_pct: float | None) -> str:
    """Label an hour. Order matters: the holiday test must run before disruption."""
    if volume_pct > VOLUME_DROP:
        return "normal"
    if ratio_pct is None:
        return "quiet (too few trips to judge mode mix)"
    if ratio_pct <= RATIO_DROP:
        return "DISRUPTION"
    return "low volume, normal mode mix (holiday-like)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument(
        "--write-json",
        action="store_true",
        help="also write assessment.json into the bundle, for the map to read",
    )
    args = ap.parse_args()

    movement = load("movement.json")
    truth = load("ground-truth.json")
    rainfall = load("rainfall.json")

    declared = datetime.datetime.fromisoformat(truth["declaration"]["at"])

    rows = []
    for stamp in sorted(movement["window"]):
        day, hour_s = stamp.split("T")
        hour = int(hour_s)
        rec = movement["window"][stamp]
        weekday = datetime.date.fromisoformat(day).weekday()
        base = movement["baseline"].get(f"{weekday}:{hour}")
        if not base or not base["median"]:
            continue
        vol_pct = 100.0 * (rec["total"] - base["median"]) / base["median"]
        ratio = mode_ratio(rec["by_class"], movement["exposed_modes"], movement["enclosed_modes"])
        rb = base.get("ratio_median")
        ratio_pct = None if (ratio is None or not rb) else 100.0 * (ratio - rb) / rb
        rows.append(
            {
                "at": datetime.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+12:00"),
                "total": rec["total"],
                "vol_pct": vol_pct,
                "ratio_pct": ratio_pct,
                "label": classify(vol_pct, ratio_pct),
                "baseline_n": base["n"],
            }
        )

    if not args.quiet:
        print(f"{truth['event']}\n")
        print(f"{'time':17}{'movements':>11}{'vs normal':>11}{'mode mix':>10}   assessment")
        for r in rows:
            rp = "     -" if r["ratio_pct"] is None else f"{r['ratio_pct']:+6.0f}%"
            mark = "  <-- state of emergency declared" if (
                r["at"] <= declared < r["at"] + datetime.timedelta(hours=1)
            ) else ""
            print(
                f"{r['at']:%Y-%m-%d %H:%M}  {r['total']:>9,}{r['vol_pct']:>10.0f}%{rp:>10}   "
                f"{r['label']}{mark}"
            )

    # Group flagged hours into episodes. The window deliberately starts before
    # the emergency and contains an earlier storm on 18 April, which the detector
    # also flags - correctly, since 30 mm fell that day. Quoting the very first
    # flag as the lead time on the declaration would credit the detector with
    # predicting an event two days out, which it did not do.
    episodes = []
    for row in rows:
        if row["label"] != "DISRUPTION":
            continue
        if episodes and row["at"] - episodes[-1][-1]["at"] <= datetime.timedelta(hours=3):
            episodes[-1].append(row)
        else:
            episodes.append([row])

    print("\n--- Episodes detected ---")
    for ep in episodes:
        containing = ep[0]["at"] <= declared <= ep[-1]["at"] + datetime.timedelta(hours=1)
        tag = "  <-- contains the declaration" if containing else ""
        print(
            f"{ep[0]['at']:%d %b %H:%M} to {ep[-1]['at']:%d %b %H:%M}  "
            f"({len(ep)} h, worst {min(r['vol_pct'] for r in ep):.0f}% volume){tag}"
        )

    print("\n--- Assessment ---")
    main_ep = next(
        (e for e in episodes if e[0]["at"] <= declared <= e[-1]["at"] + datetime.timedelta(hours=1)),
        None,
    )
    if main_ep:
        lead = (declared - main_ep[0]["at"]).total_seconds() / 3600.0
        print(f"Episode containing declaration starts : {main_ep[0]['at']:%Y-%m-%d %H:%M}")
        print(f"State of emergency declared           : {declared:%Y-%m-%d %H:%M}")
        print(f"Lead time                             : {lead:.0f} hours")
        print("  Read this as 'the signal was already visible', not 'the signal")
        print("  predicted it'. An operator watching would still have needed to")
        print("  decide the drop mattered.")
    flagged = sum(1 for r in rows if r["label"] == "DISRUPTION")
    print(f"Hours flagged                         : {flagged} of {len(rows)}")

    peak = max(rainfall["reporting"].items(), key=lambda kv: kv[1]["total_mm"])
    print(f"Wettest gauge         : {peak[0]}, {peak[1]['total_mm']} mm over the window")
    print(f"Gauges reporting      : {len(rainfall['reporting'])} "
          f"({len(rainfall['listed_but_silent'])} listed but silent)")

    thin = [r for r in rows if r["baseline_n"] < 8]
    print("\n--- Known limits ---")
    print("* Thresholds were tuned by eye against this single event. One event is")
    print("  not a validation set, and nothing here has been tested against a")
    print("  disruption that is not weather (a quake, a cordon, a major outage).")
    print("* Run scripts/holiday_check.py for the daily test behind the mode-mix")
    print("  threshold. It clears all four April public holidays, but misses")
    print("  19 April - 34 mm of rain that it reads as holiday-like. The test")
    print("  buys separation from holidays at the cost of missing lighter rain.")
    if thin:
        print(f"* {len(thin)} of {len(rows)} hours rest on fewer than 8 baseline samples.")
    print("* Counts are hourly, so the earliest possible detection is the end of")
    print("  the hour in which the change happens.")
    print("* Sensors cover instrumented streets only, not the whole network, and")
    print("  a sensor that fails in a storm looks exactly like a road nobody used.")

    if args.write_json:
        out = {
            "thresholds": {"volume_drop_pct": VOLUME_DROP, "ratio_drop_pct": RATIO_DROP},
            "hours": [
                {
                    "at": r["at"].isoformat(),
                    "total": r["total"],
                    "vol_pct": round(r["vol_pct"], 1),
                    "ratio_pct": None if r["ratio_pct"] is None else round(r["ratio_pct"], 1),
                    "label": r["label"],
                    "baseline_n": r["baseline_n"],
                }
                for r in rows
            ],
        }
        path = BUNDLE / "assessment.json"
        path.write_text(json.dumps(out))
        print(f"\nWrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
