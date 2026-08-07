# Wellington Impact Lab — Team 3

Prep for the Wellington City Council emergency management Impact Lab,
Saturday 8 August 2026.

**Read [START-HERE.md](START-HERE.md) first.** Two minutes, written for arriving
cold on the day.

## What is here

Team 3's problem is **sorting incoming information** — awareness, needs
verification, needs action.

| For problem 4 | |
|---|---|
| `data/corpus/` | 74 incoming reports plus a separate answer key, so triage can be scored. |
| `scripts/corroborate.py` | Checks a located report against rain gauges and live feeds. `--demo`, `--score`, `--geojson`, `--live`. |
| `data/corpus/assessed.geojson` | Assessed reports as GeoJSON, for the shared common operating picture. |
| `scripts/build_corpus.py` | Rebuilds the corpus from ground truth and live Wellington Water jobs. |
| `scripts/build_gazetteer.py` | 3,694 place names to coordinates, collisions kept apart. |

| Everything else | |
|---|---|
| `scripts/check_feeds.py` | Which of 19 live emergency feeds are up right now, and which are quiet by design. ~7 seconds. |
| `scripts/detect_disruption.py` | Movement disruption detector, scored against the April 2026 flood. |
| `scripts/holiday_check.py` | The daily test showing why a public holiday looks like an emergency, and what separates them. |
| `scripts/build_replay.py` | Rebuilds the replay bundle from public sources. |
| `scripts/serve.py` | Threaded dev server for the map. |
| `scripts/sources.py` | Verified endpoints and stdlib-only helpers. |
| `site/` | Replay map: scrub through the emergency hour by hour. |
| `data/replay/april-2026/` | The April 2026 Wellington flood, rebuilt from public data. |
| `.claude/skills/wellington-emergency-data/` | Everything above, taught to Claude Code. |
| `docs/findings.md` | What was found and how far it can be trusted. |

## Requirements

Python 3.9+ and a browser. No pip install, no virtualenv, no API keys.

## Quick start

```bash
python3 scripts/check_feeds.py         # what is live
python3 scripts/detect_disruption.py   # the detector, with its own limits
python3 scripts/serve.py               # then http://localhost:8777/site/
```

Use `scripts/serve.py` rather than `python3 -m http.server`. That one is
single-threaded and the map silently fails to load behind it.

## The data

Public sources only, as the brief requires. Hazard layers come from the
organisers' catalogue at
[claudecommunity-nz/wcc-emergency-gis-data](https://github.com/claudecommunity-nz/wcc-emergency-gis-data),
which is thorough and worth reading before hunting for anything new.

Attribution: transport sensor counts and suburb boundaries from Wellington City
Council; rainfall and river level from Greater Wellington Regional Council
(Hilltop telemetry). Licences vary by publisher — check before republishing
anything. WCC emergency routes carry "consult WCC prior to use".

The `data/cache/` directory holds ~180 MB of downloaded monthly CSVs and is
gitignored. `build_replay.py` refills it on demand.
