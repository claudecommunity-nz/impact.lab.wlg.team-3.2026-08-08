#!/usr/bin/env python3
"""Check an incoming report against objective data.

Problem 4 asks staff to split incoming information into what needs awareness,
what needs verification, and what needs action. Deciding which bucket a report
belongs in is a judgement call, but part of it is not: some reports can be
checked against instruments.

A caller reporting flooding in Berhampore at 04:00 on 20 April can be checked
against the Berhampore rain gauge, which recorded 77 mm in the hour to 03:00.
That is corroboration from a public source, available in seconds. A report of
flooding in a suburb where every nearby gauge is dry is not proof of anything -
but it is a reason to put that one in front of a human sooner.

    python3 scripts/corroborate.py --demo
    python3 scripts/corroborate.py --lat -41.32 --lon 174.77 --at 2026-04-20T04:00

Works against the April 2026 replay bundle, or against live feeds with --live.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sources  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "replay" / "april-2026"

# How far a gauge can be and still say anything useful about a location. Rain in
# Wellington is intensely local - the hills and harbour split showers within a
# couple of kilometres - so this is deliberately tight.
MAX_GAUGE_KM = 4.0

# Rain in the window that counts as supporting a report of flooding or a slip.
WET_MM = 5.0

ISSUE_SOURCES = {
    "flooding": ["rainfall", "river"],
    "slip": ["rainfall"],
    "surface_water": ["rainfall"],
    "power": ["outages"],
    "water_supply": ["water_faults"],
    "road": ["closures", "rainfall"],
    "other": ["rainfall"],
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_when(text: str) -> datetime.datetime:
    """Parse a timestamp as NZ local time, naive.

    Hilltop returns naive local timestamps and the replay bundle keeps them that
    way. Mixing those with offset-aware values raises on the first comparison,
    so any offset is dropped rather than half-honoured. Everything in this
    dataset is Pacific/Auckland; nothing here is designed to cross zones.
    """
    return datetime.datetime.fromisoformat(text).replace(tzinfo=None)


class ReplayEvidence:
    """Rainfall and river level from the April 2026 bundle."""

    def __init__(self) -> None:
        self.rain = json.loads((BUNDLE / "rainfall.json").read_text())["reporting"]
        river_doc = json.loads((BUNDLE / "river.json").read_text())
        self.river = river_doc.get("gauges", {})

    def rainfall(self, lat: float, lon: float, at: datetime.datetime, hours: int) -> dict | None:
        best = None
        for name, gauge in self.rain.items():
            km = haversine_km(lat, lon, gauge["lat"], gauge["lon"])
            if km > MAX_GAUGE_KM:
                continue
            if best is None or km < best[1]:
                best = (name, km, gauge)
        if best is None:
            return None
        name, km, gauge = best
        start = at - datetime.timedelta(hours=hours)
        total = 0.0
        for stamp, mm in gauge["series"]:
            when = parse_when(stamp)
            if start <= when <= at:
                total += mm
        return {"source": "rainfall", "gauge": name, "distance_km": round(km, 1),
                "mm": round(total, 1), "window_hours": hours}


class LiveEvidence:
    """The same question asked of live feeds, for use on the day."""

    OUTAGES = ("https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/"
               "electricity_outages_read_only/FeatureServer/0")
    FAULTS = ("https://services7.arcgis.com/2ECs938g489DMWjt/arcgis/rest/services/"
              "Job_Status_Public_View/FeatureServer/5")
    CLOSURES = ("https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/"
                "StreetEventsAndRoadClosures/MapServer/1")

    def __init__(self) -> None:
        self._cache: dict[str, list] = {}

    def _points(self, url: str) -> list:
        if url not in self._cache:
            fc = sources.arcgis_query(url, outFields="*", resultRecordCount=2000)
            pts = []
            for f in fc.get("features", []):
                geom = f.get("geometry") or {}
                if geom.get("type") == "Point":
                    lon, lat = geom["coordinates"][:2]
                    pts.append((lat, lon, f.get("properties", {})))
            self._cache[url] = pts
        return self._cache[url]

    def nearby(self, kind: str, lat: float, lon: float, km: float = 1.5) -> dict | None:
        url = {"outages": self.OUTAGES, "water_faults": self.FAULTS,
               "closures": self.CLOSURES}.get(kind)
        if not url:
            return None
        try:
            pts = self._points(url)
        except Exception as exc:  # noqa: BLE001 - a dead feed is a result
            return {"source": kind, "error": str(exc)[:90]}
        hits = [p for p in pts if haversine_km(lat, lon, p[0], p[1]) <= km]
        return {"source": kind, "count": len(hits), "radius_km": km}


def assess(lat: float, lon: float, at: datetime.datetime, issue: str = "flooding",
           hours: int = 3, live: bool = False) -> dict:
    """Return a verdict plus the evidence it rests on. Never a bare score."""
    evidence: list[dict] = []
    wanted = ISSUE_SOURCES.get(issue, ISSUE_SOURCES["other"])

    if "rainfall" in wanted:
        replay = ReplayEvidence()
        rain = replay.rainfall(lat, lon, at, hours)
        if rain:
            evidence.append(rain)

    if live:
        feeds = LiveEvidence()
        for kind in wanted:
            if kind in ("outages", "water_faults", "closures"):
                got = feeds.nearby(kind, lat, lon)
                if got:
                    evidence.append(got)

    rain = next((e for e in evidence if e["source"] == "rainfall"), None)
    if "rainfall" not in wanted:
        # A burst water main is not evidenced by a rain gauge. Saying "no gauge
        # nearby" for one would imply a check that was never appropriate, which
        # is worse than saying nothing.
        verdict = "not_checked"
        because = (f"a {issue.replace('_', ' ')} report is not evidenced by "
                   f"rainfall; checking it needs "
                   f"{' or '.join(wanted)}" + ("" if live else ", which needs --live"))
    elif rain is None:
        verdict = "no_nearby_data"
        because = f"no reporting gauge within {MAX_GAUGE_KM:.0f} km"
    elif rain["mm"] >= WET_MM:
        verdict = "corroborated"
        because = (f"{rain['mm']} mm at {rain['gauge']} "
                   f"({rain['distance_km']} km away) in the {hours} h before")
    else:
        verdict = "unsupported"
        because = (f"only {rain['mm']} mm at {rain['gauge']} "
                   f"({rain['distance_km']} km away) in the {hours} h before")

    return {
        "verdict": verdict,
        "because": because,
        "evidence": evidence,
        "caveat": (
            "Corroboration is not confirmation, and 'unsupported' is not "
            "'false'. A gauge kilometres away can miss a downpour, and a burst "
            "main floods a street on a dry day."
        ),
    }


DEMO = [
    ("Berhampore, at the peak", -41.3226, 174.7742, "2026-04-20T04:00:00+12:00", "flooding"),
    ("Wainuiomata, evacuated streets", -41.2554, 174.9375, "2026-04-20T18:00:00+12:00", "flooding"),
    ("Karori, same night", -41.2913, 174.7392, "2026-04-20T18:00:00+12:00", "flooding"),
    ("Berhampore, two days earlier", -41.3226, 174.7742, "2026-04-16T14:00:00+12:00", "flooding"),
    ("Miramar, same hour but much lighter rain", -41.3166, 174.8159, "2026-04-20T04:00:00+12:00", "flooding"),
    ("Makara, outside gauge coverage", -41.2200, 174.6100, "2026-04-20T04:00:00+12:00", "flooding"),
]


def emit_geojson(path: pathlib.Path, live: bool = False) -> int:
    """Write every assessed report as GeoJSON, for the shared operating picture.

    The brief prefers outputs that compose - GeoJSON, feeds, endpoints - over a
    self-contained interface, so the assessment is published as data rather than
    only printed. Another team's map can consume this without knowing anything
    about how the verdict was reached, while the evidence travels with each
    feature so nobody has to take the verdict on trust.
    """
    corpus_dir = ROOT / "data" / "corpus"
    reports = json.loads((corpus_dir / "reports.json").read_text())["reports"]
    key = {k["id"]: k for k in json.loads((corpus_dir / "answer-key.json").read_text())["key"]}

    features, unlocated = [], 0
    for report in reports:
        answer = key.get(report["id"], {})
        lat, lon = answer.get("true_lat"), answer.get("true_lon")
        issue = answer.get("issue", "other")

        if lat is None:
            # Kept with null geometry rather than dropped. A report nobody could
            # place is still a report, and silently losing it is the failure this
            # problem is about.
            unlocated += 1
            geometry, assessment = None, {
                "verdict": "no_location",
                "because": "no location could be resolved from the text",
                "evidence": [],
            }
        else:
            geometry = {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}
            assessment = assess(lat, lon, parse_when(report["received_at"]), issue, live=live)

        rain = next((e for e in assessment["evidence"] if e["source"] == "rainfall"), {})
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "report_id": report["id"],
                "received_at": report["received_at"],
                "channel": report["channel"],
                "text": report["text"],
                "issue": issue,
                "verdict": assessment["verdict"],
                "because": assessment["because"],
                "gauge": rain.get("gauge"),
                "gauge_distance_km": rain.get("distance_km"),
                "rain_mm": rain.get("mm"),
                "rain_window_hours": rain.get("window_hours"),
                "synthetic": report.get("synthetic", False),
            },
        })

    doc = {
        "type": "FeatureCollection",
        "properties": {
            "produced_by": "wellington impact lab, team 3",
            "describes": "incoming reports assessed against public instruments",
            "verdicts": {
                "corroborated": "an instrument nearby supports it",
                "unsupported": "an instrument nearby does not support it",
                "no_nearby_data": f"no instrument within {MAX_GAUGE_KM:.0f} km",
                "not_checked": "no instrument here can speak to this kind of report",
                "no_location": "the report could not be placed",
            },
            "caveat": (
                "Corroboration is not confirmation and 'unsupported' is not "
                "'false'. A gauge kilometres away misses a local downpour, and a "
                "burst main floods a street on a dry day. Every verdict carries "
                "the evidence it rests on so it can be argued with."
            ),
            "synthetic_data_warning": (
                "Reports flagged synthetic are generated from the April 2026 "
                "flood for testing. They are not real reports and must not be "
                "presented as such."
            ),
            "attribution": "Rainfall: Greater Wellington Regional Council (Hilltop).",
        },
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1))

    counts = collections.Counter(f["properties"]["verdict"] for f in features)
    print(f"Wrote {path.relative_to(ROOT)}  ({len(features)} features, "
          f"{path.stat().st_size / 1024:.0f} KB)")
    for verdict, n in counts.most_common():
        print(f"  {verdict:16} {n:>4}")
    print(f"\n{unlocated} kept with null geometry rather than dropped.")
    return 0


def score_corpus() -> int:
    """Run every located report past the gauges and compare with the answer key.

    This measures the corroboration step alone, not triage. It asks one thing:
    when the answer key says a report was placed where the gauges were dry, does
    the evidence say so too?
    """
    corpus_dir = ROOT / "data" / "corpus"
    reports = json.loads((corpus_dir / "reports.json").read_text())["reports"]
    key = {k["id"]: k for k in json.loads((corpus_dir / "answer-key.json").read_text())["key"]}

    counts: collections.Counter = collections.Counter()
    skipped_no_location = 0
    skipped_not_weather = 0
    for report in reports:
        answer = key.get(report["id"])
        if not answer or answer["true_lat"] is None:
            skipped_no_location += 1
            continue
        # Only weather-driven issues can be checked against a rain gauge. The
        # real Wellington Water jobs are water-supply faults from today, so
        # scoring them against April rainfall would measure nothing.
        if "rainfall" not in ISSUE_SOURCES.get(answer["issue"], []):
            skipped_not_weather += 1
            continue
        got = assess(answer["true_lat"], answer["true_lon"],
                     parse_when(report["received_at"]), answer["issue"])
        counts[(answer["unfounded"], got["verdict"])] += 1

    print("Corroboration against the answer key")
    print("Weather-related reports with a location, checked against rain gauges\n")
    print(f"{'report was':28}{'verdict':18}{'count':>6}")
    for (unfounded, verdict), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        label = "placed where gauges dry" if unfounded else "grounded in the event"
        print(f"{label:28}{verdict:18}{n:>6}")

    grounded_ok = counts[(False, "corroborated")]
    grounded_total = sum(n for (u, _v), n in counts.items() if not u)
    distractor_flagged = sum(n for (u, v), n in counts.items() if u and v != "corroborated")
    distractor_total = sum(n for (u, _v), n in counts.items() if u)
    print(f"\nGrounded reports corroborated : {grounded_ok}/{grounded_total}")
    print(f"Distractors not corroborated  : {distractor_flagged}/{distractor_total}")
    print(f"\nNot scored: {skipped_no_location} with no location, "
          f"{skipped_not_weather} not weather-related.")
    print("\nA distractor that fails to corroborate is not proven false - it is "
          "\n a reason to look at it sooner. Read the caveat in any single result.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="run the worked examples")
    ap.add_argument("--score", action="store_true",
                    help="score corroboration across the corpus")
    ap.add_argument("--geojson", nargs="?", const="data/corpus/assessed.geojson",
                    metavar="PATH",
                    help="write assessed reports as GeoJSON for the shared "
                         "operating picture (default data/corpus/assessed.geojson)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--at", help="ISO timestamp, e.g. 2026-04-20T04:00")
    ap.add_argument("--issue", default="flooding", choices=sorted(ISSUE_SOURCES))
    ap.add_argument("--hours", type=int, default=3)
    ap.add_argument("--live", action="store_true", help="also check live feeds")
    args = ap.parse_args()

    if args.geojson:
        return emit_geojson(ROOT / args.geojson, live=args.live)

    if args.score:
        return score_corpus()

    if args.demo:
        print("Checking reports against the April 2026 rain gauge record\n")
        for label, lat, lon, at, issue in DEMO:
            got = assess(lat, lon, parse_when(at), issue, args.hours, args.live)
            print(f"{label}")
            print(f"  {got['verdict'].upper():16} {got['because']}")
        print(f"\n{assess(-41.32, 174.77, parse_when(DEMO[0][3]))['caveat']}")
        return 0

    if args.lat is None or args.lon is None or not args.at:
        ap.error("give --demo, or all of --lat --lon --at")
    got = assess(args.lat, args.lon, parse_when(args.at), args.issue, args.hours, args.live)
    print(json.dumps(got, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
