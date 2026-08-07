# Start here

Two minutes of reading, written for 8am Saturday when you have not seen any of
this before.

## What this is

Prep for the Wellington Impact Lab. Team 3 has **problem 4**: helping emergency
staff sort incoming reports into information for awareness, information needing
verification, and information needing action.

Two pieces are built for it, both deliberately narrow:

- **A grounded corpus** - 74 incoming reports with a separate answer key, so
  triage can be measured rather than admired. `data/corpus/`.
- **A corroboration engine** - checks a located report against rain gauges and
  live feeds. `scripts/corroborate.py`.

Extraction, grouping and the queue interface are **not** built. That is the part
worth doing together on the day, and five people who have just met need
something to build.

Some of the earlier work - the movement detector, the holiday discriminator -
was aimed at problem 5 and does not serve this one. It is still in the repo but
do not feel obliged to use it.

## The three things that matter

**1. Every live emergency feed is empty on a calm Saturday, and that is correct.**

GWRC's incident layer, WCC's Emergency Assistance Centres layer and the Civil
Defence alert RSS all publish nothing between activations. Any team that builds
against them live will have an empty screen at 4:30 and will waste an hour
debugging something that is not broken. Say this out loud in the room early - it
is worth knowing whoever you are working with.

**2. There is a real Wellington emergency in this repo to build against.**

`data/replay/april-2026/` is the flooding that led to a state of emergency
**declared at 17:25 on Monday 20 April 2026** - four months ago, worked by the
same WCC people who will be in the room. Rebuilt from public data: hourly
transport counts, rainfall and river gauges, and a ground-truth timeline.

The gauge record shows **77 mm of rain in the single hour to 03:00** at
Berhampore, and 134 mm across that day. That independently confirms the reported
"more than 70 mm in under an hour in southern Wellington" from the raw data.

**3. The transport sensor data is not in the organisers' catalogue.**

408 countlines, hourly counts by mode, back to November 2023, published as
monthly CSVs on S3. It is the load-bearing source for problem 5 and the
organisers' repo does not mention it. Details in
`.claude/skills/wellington-emergency-data/references/sources.md`.

## Run these first

```bash
python3 scripts/check_feeds.py            # which feeds are up right now (~7s)
python3 scripts/corroborate.py --demo     # checking reports against gauges
python3 scripts/corroborate.py --score    # measured across the corpus
python3 scripts/corroborate.py --geojson  # publish it as data
```

`--score` is the number to quote: **20 of 26** grounded weather reports
corroborated, **0 of 4** distractors corroborated. Reports placed where every
nearby gauge was dry do not corroborate — which is a reason to look at them
sooner, not proof they are false.

`--geojson` matters because the brief asks for outputs that compose into a
shared common operating picture, preferring GeoJSON and feeds over isolated
interfaces. It writes one feature per report with the verdict and the evidence
attached, so another team's map can consume it directly.

Also available: `scripts/detect_disruption.py` and `scripts/serve.py` (then
open `http://localhost:8777/site/`), both from the problem 5 work.

`check_feeds.py` is the one to run first thing. All 19 feeds were up when last
checked, but that was Thursday night.

Use `scripts/serve.py`, not `python3 -m http.server` - the latter is
single-threaded and the map silently fails to load behind it.

## Tell your team about the skill

`.claude/skills/wellington-emergency-data/` teaches any Claude Code instance the
catalogue, the verified endpoints, and the dozen traps that each cost an hour.
Anyone who clones this repo gets it automatically. That is the fastest thing you
can do for four people you have not met.

## The finding worth demoing

A public holiday and an emergency look almost identical in total traffic volume:
Good Friday was -43%, the flood day -44%. What separates them is **mode
composition** - in a storm people abandon bikes and scooters for cars and buses,
and on a holiday they simply travel less in the same proportions.

Tested across April 2026, that discriminator classifies **all four public
holidays** correctly and catches the three heaviest rain days. It misses 19
April, which had 34 mm - the separation from holidays costs you lighter rain.

Run `scripts/holiday_check.py` to see the test, and
`scripts/detect_disruption.py` for the hourly version. Both print their own
limits; read them before quoting any number.

Full reasoning in [docs/findings.md](docs/findings.md).

## What I would not claim

- The thresholds were tuned against one event. That is not a validation set.
- The ten-hour gap between the first flagged hour and the declaration is "the
  signal was visible", not "the signal predicted it".
- The ground-truth timeline comes from news reporting, not a Council incident
  log.
- Nothing here has been tested on a non-weather disruption.

Being straight about all four is worth more than hiding them - "honesty about
limits" is an explicit judging criterion.
