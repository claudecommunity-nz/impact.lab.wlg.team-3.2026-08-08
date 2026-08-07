---
name: wellington-emergency-data
description: Use when building anything against Wellington emergency, hazard, weather, transport or lifeline data - warnings, river and rainfall gauges, quakes, outages, road closures, movement counts, community hubs. Covers which endpoints are live, the traps that silently return wrong data, and the April 2026 flood replay bundle for demoing when live feeds are quiet.
---

# Wellington emergency data

Public data for Wellington emergency management, and the traps in it. Everything
here was confirmed against the live services, not read off a datasheet.

## Where these files live in this repo

This skill was written in a separate prep repo, so the paths below are relative
to that. In this repo, on the `mark` branch, everything it refers to sits under
`Mark's prep/`:

| The skill says | Here it is |
|---|---|
| `scripts/…` | `Mark's prep/scripts/…` |
| `data/replay/april-2026/…` | `Mark's prep/data/replay/april-2026/…` |
| `data/corpus/…` | `Mark's prep/data/corpus/…` |
| `data/gazetteer.json` | `data/gazetteer.json` **and** `Mark's prep/data/gazetteer.json` |

`data/gazetteer.json` at the repo root is the copy the running prototype uses.

## Before anything else

**Live emergency feeds are empty most of the time, and that is correct.** GWRC's
incident layer, WCC's Emergency Assistance Centres layer and the Civil Defence
alert RSS all publish nothing between activations. If you build against them
live on a calm day you will have nothing to show. Do not "fix" this - either
handle empty as a first-class state, or drive your prototype from the replay
bundle described below.

Check what is actually up before building:

```bash
python3 scripts/check_feeds.py
```

19 feeds, about 7 seconds, tells you up / quiet / down and how many records each
holds right now.

## The traps

These cost an hour each if you meet them cold. Every one is real and reproduced.

| Trap | What you see | What to do |
|---|---|---|
| ArcGIS native projection is NZTM2000 (EPSG:2193) | Coordinates in the millions; map centres off Africa | Always pass `outSR=4326` |
| Layers cap silently at `maxRecordCount` (1000-2000) | A round number of records and no error | Check `exceededTransferLimit`, then page |
| Hilltop gzips some responses unasked | `not well-formed (invalid token): line 1, column 0` | Decompress when the body starts `\x1f\x8b` - `sources.get` does this |
| Hilltop root element varies | `GetData` returns `<Hilltop>`, `SiteList` returns `<HilltopServer>`, and so does the error | Detect errors by the `<Error>` child, never the root tag |
| A gauge listed for a measurement may hold no data | Empty series, no error | Treat "listed" and "reporting" as different things |
| Spaces in Hilltop site names | `No data for site` | Percent-encode as `%20`; a `+` is not decoded server-side |
| Wellington Water live layer | Layers 0 and similar names look right but are dead since 2018 | The live one is index **5** |
| NZTA traffic counts region filter | Silently returns nothing | The string is `'09 - Wellington'`, not `'Wellington'` |
| NZTA cameras | A dead camera still appears in the feed | Check `Offline` and `UnderMaintenance` |
| GeoNet quake feed | Retracted quakes appear inline | Filter out `quality == "deleted"` |
| Overpass named-area queries | Zero results | Use the bbox `-41.36,174.70,-41.14,174.90` |
| Some sites 403 a bare request | Ferries, airport, some council pages | Send a User-Agent - `sources.get` does |

## Using the helpers

`scripts/sources.py` is standard library only. No install, no virtualenv.

```python
import sys; sys.path.insert(0, "scripts")
import sources

# Rainfall gauges in Wellington that exist, then one that reports
gauges = [s for s in sources.hilltop_sites("Rainfall") if sources.in_wellington(s)]
series = sources.hilltop_series("Berhampore at Nursery", "Rainfall",
                                "2026-04-19", "2026-04-22")   # [(timestamp, mm)]

# Any ArcGIS layer, already WGS84 GeoJSON
hubs = sources.arcgis_query(
    "https://mapping.gw.govt.nz/arcgis/rest/services/GW/Emergencies_P/MapServer/2")
```

`sources.HilltopError` means the server answered but had no data - distinct from
a network failure, so you can tell "no gauge" from "no rain".

## The replay bundle

`data/replay/april-2026/` holds a real Wellington emergency, rebuilt from public
data: the flooding that led to a **state of emergency declared at 17:25 on
Monday 20 April 2026**.

| File | Holds |
|---|---|
| `movement.json` | Hourly transport counts for 18-22 April, by class and countline, plus a weekday/hour baseline from Feb-May excluding holidays |
| `rainfall.json` | Hourly rainfall for the 19 gauges that were actually reporting, and the 31 that were listed but silent |
| `river.json` | River level per gauge |
| `countlines.geojson` | Sensor positions |
| `ground-truth.json` | What actually happened - declaration time, evacuated streets, uninhabitable suburbs, sources |

Peak rainfall was **134 mm at Berhampore** on 20 April, 84 mm at Te Papa,
matching reports of 70 mm in under an hour in southern Wellington.

Rebuild it with `python3 scripts/build_replay.py` (downloads ~180 MB, cached).
Rebuild one part with `--only movement`.

Use it to drive a prototype so the demo shows something real, and score against
`ground-truth.json` rather than against your own impression.

## Sorting incoming reports (the assigned problem)

Team 3's problem is helping emergency staff sort incoming information into
awareness, needs-verification, and needs-action. Two pieces are built; the
extraction, grouping and queue are deliberately left to build on the day.

### The corpus

`data/corpus/reports.json` is 74 incoming reports. `answer-key.json` is what
each one actually was, held separately so a prototype can be **scored** rather
than admired.

- **34 synthetic**, each traceable to something real on 20 April 2026: a street
  that was evacuated, a suburb with uninhabitable houses, a gauge that recorded
  heavy rain at that hour. Includes duplicates of the same incident in different
  words and channels, four reports with no resolvable location, and four
  distractors placed where every nearby gauge was dry.
- **40 real**, from open Wellington Water fault jobs - genuine operational text,
  addresses and statuses. Real, but from today rather than from the event, and
  labelled as such.

The answer key records the true location, the issue, which reports describe the
same incident, and which are unfounded. Its `category` field is a defensible
reading of the brief's three buckets, not official Council triage - argue with it.

Rebuild with `python3 scripts/build_corpus.py`.

### Corroboration

`scripts/corroborate.py` checks a located report against instruments. A caller
reporting flooding in Berhampore at 04:00 on 20 April is checked against the
Berhampore gauge, which recorded 82.4 mm in the preceding three hours.

```bash
python3 scripts/corroborate.py --demo     # worked examples
python3 scripts/corroborate.py --score    # measured across the corpus
python3 scripts/corroborate.py --geojson  # publish as data, for the shared picture
```

The brief prefers outputs that compose - GeoJSON, feeds, endpoints - over a
self-contained interface, so `--geojson` writes
`data/corpus/assessed.geojson`: one feature per report, carrying the verdict,
the gauge that produced it, the distance and the millimetres. Another team's map
can consume it without knowing how the verdict was reached, and the evidence
travels with each feature so nobody takes it on trust. Reports that could not be
placed are kept with `"geometry": null` rather than dropped.

Across the corpus it corroborates 20 of 26 grounded weather reports and
corroborates none of the 4 distractors.

Verdicts are `corroborated`, `unsupported`, `no_nearby_data` (nothing within 4
km), `not_checked` (no instrument speaks to that kind of report - a burst main
is not evidenced by a rain gauge) and `no_location`. Every result carries its
evidence and this caveat: **corroboration is not confirmation, and "unsupported"
is not "false"** - a gauge kilometres away misses a local downpour, and a burst
main floods a street on a dry day.

Use `--live` to check outages, water faults and road closures instead of replay.

### Place names

`data/gazetteer.json` maps 3,694 suburb and street names to coordinates, built
from WCC boundaries and roads plus OpenStreetMap for the Hutt Valley.

Two things it handles that matter:

- **Name collisions are kept apart, not averaged.** Wellington has several Rata
  Streets; averaging their midpoints lands in Naenae, kilometres from the
  Wainuiomata one that was evacuated. 46 names have more than one location.
- **Street types are unreliable.** The April reporting said "Wetherby Street";
  the street in Wainuiomata is Wetherby Grove. Exact matching silently loses
  that incident, so `build_corpus.resolve()` falls back to the name body.

A street midpoint is not where the incident is. On a long road it can be a
kilometre out.

## Movement disruption detection

`scripts/detect_disruption.py` finds city-scale disruption in the transport
counts, and separates it from a public holiday - which looks nearly identical if
you only watch total volume.

The discriminator is **mode composition**. On a holiday people make fewer trips
and the travel mix barely moves. In a storm they also abandon the exposed modes -
bike, scooter, motorbike - for cars and buses. So a volume drop with a normal
mode mix is a holiday; a volume drop with a collapsed exposed-to-enclosed ratio
is disruption.

Tested daily across April 2026 by `scripts/holiday_check.py`, it classifies all
four public holidays as holiday-like and the three heaviest rain days as
storm-like, and puts the start of the declaration-day episode 10 hours before
the declaration itself. It misses 19 April, which had 34 mm - the threshold that
separates holidays from storms also loses lighter rain.

Read `--- Known limits ---` in the detector's output before quoting any of this.
The thresholds are fitted to one event.

## What is not in the public data

Worth saying out loud in any pitch, because it bounds what a prototype can
honestly claim:

- No public marae dataset.
- No aged-care or retirement-village dataset. The most vulnerable populations
  have the worst data.
- No public telco coverage or fault data beyond 2degrees' outage list.
- No Council incident log. Ground truth for past events comes from news
  reporting, which is approximate and incomplete.
- Deprivation (NZDep2023) and the EHINZ social vulnerability indicators are the
  available proxies for who cannot self-evacuate.

## Reference

- `references/sources.md` - the full verified endpoint list by theme
- `references/problems.md` - the five WCC problem statements mapped to sources

The organisers' catalogue of 74 hazard layers, with per-dataset docs, is at
<https://github.com/claudecommunity-nz/wcc-emergency-gis-data>. It is thorough;
read `docs/additional-sources.md` there before hunting for anything new.
