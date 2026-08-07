#!/usr/bin/env python3
"""Build a corpus of incoming reports for the April 2026 flood, plus an answer key.

Problem 4 is about sorting incoming information. The blocker is that Council's
actual intake - phone, email, social, partner agencies - is not public, so there
is nothing real to sort. Most prototypes will invent a handful of reports, and a
demo over invented reports cannot show whether the sorting was right.

This builds a corpus with two properties that make it useful instead:

1. It is grounded. Every synthetic report traces to something that actually
   happened on 20 April 2026 - a street that was evacuated, a suburb with
   uninhabitable houses, a gauge that recorded heavy rain at that hour - or is a
   deliberate distractor placed where the gauges were dry.

2. It comes with an answer key. Because each report is generated from a known
   fact, the true location, the true issue, which reports are duplicates of one
   another, and which are unfounded are all recorded separately. A triage
   prototype can be scored rather than admired.

Real reports are included too: open Wellington Water fault jobs carry genuine
operational free text, addresses and priorities. They are the real thing and are
labelled as such.

    python3 scripts/build_corpus.py

Writes data/corpus/reports.json (what a triage system sees) and
data/corpus/answer-key.json (what it should have concluded).
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sources  # noqa: E402
from build_gazetteer import suburb_polygons, which_suburb  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "replay" / "april-2026"
GAZETTEER = ROOT / "data" / "gazetteer.json"
OUT = ROOT / "data" / "corpus"

WATER_FAULTS = ("https://services7.arcgis.com/2ECs938g489DMWjt/arcgis/rest/services/"
                "Job_Status_Public_View/FeatureServer/5")

# Fixed so the corpus is identical for everyone on the team and across runs.
SEED = 20260420

CHANNELS = ["phone", "email", "social", "form", "partner", "news"]

# Phrasings for the same underlying incident, so duplicate detection has to work
# on meaning rather than on matching strings.
FLOOD_PHRASES = [
    "Water coming up over the road at {place}, getting deeper",
    "{place} is flooding badly, cars are stuck",
    "Surface flooding {place} - about knee deep near the corner",
    "Reports of water through properties on {place}",
    "Can't get through {place}, it's underwater",
    "Flooding at {place}. Been rising for the last hour",
]
SLIP_PHRASES = [
    "Slip has come down across {place}, road blocked",
    "Bank has given way above {place}",
    "Mud and debris across {place} after the rain",
    "Landslip at {place} - looks like it's still moving",
]
EVAC_PHRASES = [
    "Residents on {place} being told to leave, water rising fast",
    "We've evacuated our house on {place}, whole street is going",
    "Emergency services door knocking {place}, everyone out",
]
VAGUE_PHRASES = [
    "There's flooding at the bottom of the hill near the shops",
    "Road's closed somewhere past the roundabout, big slip",
    "Water everywhere down our street, been like it for hours",
    "Something's come down across the road up the valley",
]
RUMOUR_PHRASES = [
    "Hearing the whole of {place} is underwater, is that right?",
    "Someone posted that {place} has been evacuated - can anyone confirm?",
    "Word going round that the river's broken its banks at {place}",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def displace(rng: random.Random, lat: float, lon: float,
             min_km: float = 0.3, max_km: float = 1.2) -> tuple[float, float]:
    """Move a point a few hundred metres in a random direction.

    An incident is near a gauge, not on it. Real reports come from streets and
    houses, and the distance between the two is exactly what makes corroboration
    a judgement rather than a lookup.
    """
    km = rng.uniform(min_km, max_km)
    bearing = rng.uniform(0, 2 * math.pi)
    dlat = (km * math.cos(bearing)) / 110.574
    dlon = (km * math.sin(bearing)) / (111.320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def load(path: pathlib.Path):
    return json.loads(path.read_text())


STREET_TYPES = {
    "street", "st", "road", "rd", "avenue", "ave", "grove", "terrace", "tce",
    "crescent", "cres", "place", "pl", "drive", "dr", "lane", "way", "parade",
    "close", "track", "esplanade", "quay", "circuit", "rise", "view", "gardens",
}


def resolve(gaz: dict, name: str, near_lat: float | None = None):
    """Best candidate for a place name, optionally the one nearest a hint.

    Falls back to matching on the name body when the exact string misses.
    People get street types wrong constantly - the April 2026 reporting said
    "Wetherby Street", and the street in Wainuiomata is Wetherby Grove. An
    exact-match gazetteer silently loses that incident, which is the failure
    mode this whole problem is about.
    """
    place = gaz.get(name.lower())
    if not place:
        body = " ".join(w for w in name.lower().split()
                        if w not in STREET_TYPES)
        if body:
            matches = [
                p for k, p in gaz.items()
                if " ".join(w for w in k.split() if w not in STREET_TYPES) == body
            ]
            if matches:
                place = matches[0]
    if not place:
        return None
    cands = place["candidates"]
    if near_lat is not None and len(cands) > 1:
        cands = sorted(cands, key=lambda c: abs(c["lat"] - near_lat))
    return {"name": place["name"], "kind": place["kind"], **cands[0]}


def wettest_gauges(rain: dict, at: datetime.datetime, hours: int = 3, top: int = 6):
    """Gauges with the most rain in the window ending at `at`."""
    start = at - datetime.timedelta(hours=hours)
    totals = []
    for name, gauge in rain.items():
        mm = 0.0
        for stamp, val in gauge["series"]:
            when = datetime.datetime.fromisoformat(stamp)
            if start <= when <= at:
                mm += val
        if mm > 0:
            totals.append((name, mm, gauge["lat"], gauge["lon"]))
    totals.sort(key=lambda t: -t[1])
    return totals[:top]


def dry_gauges(rain: dict, at: datetime.datetime, hours: int = 3, top: int = 4):
    start = at - datetime.timedelta(hours=hours)
    totals = []
    for name, gauge in rain.items():
        mm = sum(v for s, v in gauge["series"]
                 if start <= datetime.datetime.fromisoformat(s) <= at)
        totals.append((name, mm, gauge["lat"], gauge["lon"]))
    totals.sort(key=lambda t: t[1])
    return totals[:top]


def fetch_real_faults(limit: int = 40) -> list[dict]:
    """Open Wellington Water jobs - genuine operational text, not synthetic."""
    try:
        fc = sources.arcgis_query(WATER_FAULTS, outFields="*", resultRecordCount=limit)
    except Exception as exc:  # noqa: BLE001
        log(f"  could not fetch Wellington Water faults: {exc}")
        return []
    out = []
    for f in fc.get("features", [])[:limit]:
        props = f.get("properties", {})
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        # Real field names, checked against the layer rather than guessed. The
        # descriptive ones are all lowercase; an uppercase guess yields a row of
        # work-order numbers and nothing readable.
        bits = [props.get(k) for k in
                ("comm_description", "description", "wsadd_formattedaddress",
                 "StatusDescription", "wtypedesc")]
        text = ". ".join(str(b).strip() for b in bits if b and str(b).strip())
        if not text:
            continue
        out.append({
            "text": text[:400], "lat": lat, "lon": lon,
            "priority": props.get("priority"),
            "address": props.get("wsadd_formattedaddress"),
        })
    log(f"  {len(out)} real Wellington Water fault jobs")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-live", action="store_true",
                    help="skip the real Wellington Water jobs (offline)")
    args = ap.parse_args()

    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    gaz = load(GAZETTEER)["places"]
    truth = load(BUNDLE / "ground-truth.json")
    rain = load(BUNDLE / "rainfall.json")["reporting"]

    declared = datetime.datetime.fromisoformat(truth["declaration"]["at"]).replace(tzinfo=None)
    reports: list[dict] = []
    key: list[dict] = []
    incident_no = 0

    def emit(text, when, channel, *, lat, lon, place, issue, incident,
             category, basis, synthetic=True, unfounded=False):
        rid = f"R{len(reports) + 1:04d}"
        reports.append({
            "id": rid,
            "received_at": when.isoformat(),
            "channel": channel,
            "text": text,
            "synthetic": synthetic,
        })
        key.append({
            "id": rid,
            "incident": incident,
            "true_place": place,
            "true_lat": lat,
            "true_lon": lon,
            "issue": issue,
            "category": category,
            "unfounded": unfounded,
            "basis": basis,
        })

    log("Building report corpus")

    # 1. Evacuated streets. These are the reports that must reach a human fast.
    for evac in truth["evacuations"]:
        incident_no += 1
        street = evac["street"].split("(")[0].strip()
        hint = -41.2554  # Wainuiomata, to pick the right one of several same-named streets
        found = resolve(gaz, street, near_lat=hint) or resolve(gaz, evac["suburb"])
        if not found:
            log(f"  could not place {street}")
            continue
        base = declared + datetime.timedelta(minutes=rng.randint(-90, 60))
        for i in range(rng.randint(2, 3)):
            when = base + datetime.timedelta(minutes=rng.randint(0, 75))
            emit(rng.choice(EVAC_PHRASES).format(place=f"{street}, {evac['suburb']}"),
                 when, rng.choice(["phone", "social", "partner"]),
                 lat=found["lat"], lon=found["lon"],
                 place=f"{street}, {evac['suburb']}", issue="flooding",
                 incident=f"I{incident_no:03d}", category="action",
                 basis="street recorded as evacuated in contemporaneous reporting")

    # 2. Suburbs with uninhabitable dwellings.
    for suburb in truth["uninhabitable_dwellings"]["suburbs"]:
        incident_no += 1
        found = resolve(gaz, suburb.replace("South ", ""))
        if not found:
            log(f"  could not place {suburb}")
            continue
        for i in range(rng.randint(2, 4)):
            when = declared + datetime.timedelta(minutes=rng.randint(-240, 180))
            phrases = FLOOD_PHRASES if i % 2 == 0 else SLIP_PHRASES
            emit(rng.choice(phrases).format(place=suburb),
                 when, rng.choice(CHANNELS),
                 lat=found["lat"], lon=found["lon"], place=suburb,
                 issue="flooding" if i % 2 == 0 else "slip",
                 incident=f"I{incident_no:03d}", category="action",
                 basis="suburb recorded as having uninhabitable dwellings")

    # People name suburbs and streets, not telemetry sites. "Slip at Karori
    # Stream at Ngaio Reservoir" is not a sentence anyone says, so gauges are
    # converted to the locality they sit in before being used in report text.
    polys = suburb_polygons()

    def locality(lat: float, lon: float, gauge_name: str) -> str:
        found = which_suburb(lat, lon, polys)
        if found:
            return found
        tail = gauge_name.split(" at ")[-1]
        return tail.replace(" - Niwa", "").strip()

    # 3. Heavy rain where a gauge proves it. These should corroborate.
    peak = datetime.datetime(2026, 4, 20, 4, 0)
    for name, mm, lat, lon in wettest_gauges(rain, peak):
        incident_no += 1
        label = locality(lat, lon, name)
        for i in range(rng.randint(1, 2)):
            when = peak + datetime.timedelta(minutes=rng.randint(-60, 120))
            # Offset from the gauge by a few hundred metres to a kilometre.
            # Generating these at the gauge's own coordinates would make
            # corroboration trivially true - the report would be standing on the
            # instrument - and would flatter the results.
            olat, olon = displace(rng, lat, lon)
            emit(rng.choice(FLOOD_PHRASES + SLIP_PHRASES).format(place=label),
                 when, rng.choice(CHANNELS),
                 lat=olat, lon=olon, place=label, issue="surface_water",
                 incident=f"I{incident_no:03d}", category="verify",
                 basis=f"{mm:.0f} mm recorded at {name} in the 3 h to {peak:%H:%M}")

    # 4. Distractors: reports placed where the gauges were dry. Not "false" - a
    #    burst main floods a dry street - but they should sort differently.
    for name, mm, lat, lon in dry_gauges(rain, peak):
        incident_no += 1
        label = locality(lat, lon, name)
        when = peak + datetime.timedelta(minutes=rng.randint(-30, 90))
        olat, olon = displace(rng, lat, lon)
        emit(rng.choice(RUMOUR_PHRASES).format(place=label),
             when, rng.choice(["social", "phone"]),
             lat=olat, lon=olon, place=label, issue="flooding",
             incident=f"I{incident_no:03d}", category="verify",
             basis=f"only {mm:.1f} mm at {name} in the same window",
             unfounded=True)

    # 5. Vague reports with no resolvable location. A real queue is full of these
    #    and they are the ones a naive extractor quietly drops.
    for phrase in VAGUE_PHRASES:
        incident_no += 1
        when = declared + datetime.timedelta(minutes=rng.randint(-180, 240))
        emit(phrase, when, rng.choice(["phone", "social"]),
             lat=None, lon=None, place=None, issue="unknown",
             incident=f"I{incident_no:03d}", category="verify",
             basis="no location stated; needs a human or a follow-up call")

    synthetic_count = len(reports)
    log(f"  {synthetic_count} synthetic reports across {incident_no} incidents")

    # 6. Real operational text.
    if not args.no_live:
        for fault in fetch_real_faults():
            incident_no += 1
            when = declared + datetime.timedelta(minutes=rng.randint(-300, 300))
            emit(fault["text"], when, "partner",
                 lat=fault["lat"], lon=fault["lon"], place=None,
                 issue="water_supply", incident=f"I{incident_no:03d}",
                 category="awareness",
                 basis="live Wellington Water job - real text, real location, "
                       "but from today rather than from the event",
                 synthetic=False)

    reports.sort(key=lambda r: r["received_at"])

    (OUT / "reports.json").write_text(json.dumps({
        "note": (
            "What a triage prototype sees. Synthetic reports are flagged. Do not "
            "read the answer key from here."
        ),
        "event": truth["event"],
        "reports": reports,
    }, indent=1))

    (OUT / "answer-key.json").write_text(json.dumps({
        "note": (
            "Ground truth for scoring. 'incident' groups reports that describe "
            "the same thing, so duplicate detection can be measured. 'category' "
            "is a defensible reading of the brief's three buckets, not an "
            "official Council triage - argue with it."
        ),
        "categories": {
            "action": "someone must do something now",
            "verify": "plausible but unconfirmed; check before acting",
            "awareness": "useful context, no immediate action",
        },
        "key": key,
    }, indent=1))

    dupes = len(reports) - len({k["incident"] for k in key})
    log(f"\nWrote {len(reports)} reports "
        f"({synthetic_count} synthetic, {len(reports) - synthetic_count} real)")
    log(f"  {len({k['incident'] for k in key})} distinct incidents, "
        f"{dupes} reports that duplicate another")
    log(f"  {sum(1 for k in key if k['unfounded'])} placed where gauges were dry")
    log(f"  {sum(1 for k in key if k['true_lat'] is None)} with no resolvable location")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
