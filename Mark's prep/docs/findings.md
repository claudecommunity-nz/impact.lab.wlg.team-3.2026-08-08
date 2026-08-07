# What I found, and how far it can be trusted

Work done overnight on 6-7 August 2026, before team assignments were published.
Every number here is reproducible from the scripts in this repo.

## 1. The organisers' catalogue is already excellent. Do not redo it.

`claudecommunity-nz/wcc-emergency-gis-data` is not "some endpoints". It is 74
datasets with per-dataset docs, a hand-verified sweep dated 2026-08-04, a
licensing table, and a *"Dead ends - verified, so nobody re-burns the time"*
section. It records the traps that actually cost hours: Wellington Water's live
layer is index 5 not 0; NZTA traffic counts need the region string
`'09 - Wellington'`; only one of six similarly-named Baring Head buoys is live.

The original plan here was to re-probe everything. That would have produced a
worse copy of a fresher document, so it was dropped. What follows is only what
that catalogue does not have.

## 2. Two sources named in the problem statements are missing from it

**WCC transport sensors.** 408 countlines, hourly directional counts by mode,
back to November 2023, as monthly CSVs on S3 (~45 MB, 1.4M rows each). This is
the public data underneath Pōneke Travel Insights, which is a Council dashboard
rather than an API. It is the load-bearing source for problem 5 and it appears
nowhere in the catalogue.

**RNZ news RSS.** Live, ~45 items. The catalogue notes that WCC's and GWRC's own
news RSS both 404 but does not record a working news feed.

Endpoints in `.claude/skills/wellington-emergency-data/references/sources.md`.

## 3. Live feeds are empty by design, and that will bite people on the day

The catalogue says this in several places without connecting it: GWRC's incident
layer is *"near-empty in peacetime, by design"*, WCC's Emergency Assistance
Centres layer is *"intentionally empty"*, the Civil Defence alert RSS is *"empty
between events"*, FENZ fire-danger payloads are empty in winter.

Saturday 8 August is a winter day with, presumably, no emergency. Any team
demoing a live emergency view will demo an empty map at 4:30.

`scripts/check_feeds.py` distinguishes "down" from "quiet, as expected" so nobody
debugs correct behaviour. All 19 feeds were up when last run.

## 4. A real Wellington emergency is still retrievable

A state of emergency was declared for the Wellington region at **17:25 on Monday
20 April 2026** after flooding. Four months ago; the WCC staff in the room will
have worked it.

Enough of it survives in public data to rebuild:

- Hilltop serves rainfall and river level at full cadence back to at least 2016.
- WCC's transport counts cover the month.
- News reporting gives a ground-truth timeline.

`scripts/build_replay.py` assembles `data/replay/april-2026/`.

**The gauge record confirms the news reporting.** Contemporaneous accounts said
"more than 70 mm in under an hour across parts of southern Wellington". The
Berhampore gauge recorded **77.0 mm in the single hour to 03:00** on 20 April,
and 134.0 mm across the day. That was not taken from an article - it came out of
the raw series.

Only **19 of 51** listed Wellington rainfall gauges held data for the window. In
Hilltop, being listed for a measurement and reporting are different things.

## 5. Movement: a public holiday looks like an emergency

This is the finding worth demoing, and it is the trap in problem 5.

Total traffic volume cannot separate the two:

| Day | Volume vs same-weekday baseline |
|---|---|
| Good Friday, 3 April | **-43%** |
| Day after the emergency, 21 April | **-44%** |

A detector watching volume alone cries wolf every long weekend.

**Mode composition separates them.** On a public holiday people make fewer trips
in roughly the same mix. In heavy rain they also abandon the exposed modes. On
the morning of 20 April, against other Mondays:

| Mode | Change, 05:00-09:00 |
|---|---|
| LGV | +73% |
| Bus | +59% |
| Car | +55% |
| Pedestrian | +29% |
| **Cyclist** | **-13%** |
| **E-scooter** | **-2%** |

Enclosed modes up, exposed modes down, across 229 of 329 usable countlines. That
is people moving earlier and switching out of the rain, not a sensor artefact.

So the rule is: a volume drop with a normal mode mix is a holiday; a volume drop
with a collapsed exposed-to-enclosed ratio is disruption.

### How well it actually works

`scripts/holiday_check.py`, daily across April 2026:

| Day | Volume | Mode mix | Wettest gauge | Verdict |
|---|---|---|---|---|
| Good Friday, 3 Apr | -43% | -13% | — | holiday-like ✓ |
| Easter Sunday, 5 Apr | -24% | +7% | — | holiday-like ✓ |
| Easter Monday, 6 Apr | -23% | -27% | — | holiday-like ✓ |
| ANZAC observed, 27 Apr | -23% | -26% | — | holiday-like ✓ |
| 18 Apr | -24% | -65% | 86 mm | storm-like ✓ |
| **19 Apr** | **-17%** | **-32%** | **34 mm** | **holiday-like — missed** |
| **20 Apr, declaration** | **-29%** | **-60%** | **134 mm** | **storm-like ✓** |
| 21 Apr | -44% | -77% | 43 mm | storm-like ✓ |
| 12 Apr | -26% | -57% | outside window | storm-like, unverified |

Four of four public holidays correct. Three of four verified rain days correct.
One miss: 19 April, 34 mm, read as a holiday. The threshold that buys separation
from holidays costs you lighter rain, and that trade is visible rather than
hidden.

### A correction worth recording

An earlier version of this used a -12% mode-mix threshold and claimed it cleared
the holidays. It did not - that threshold was fitted against a thinner
April-only baseline, and against a proper four-month baseline it flags Good
Friday, Easter Monday and ANZAC Day as storms. The claim had also never been
tested, because the hourly detector only ever sees 18-22 April and so never looks
at a holiday. The threshold is now -45%, set from the midpoint of the observed
gap, and `holiday_check.py` exists so the claim is checked rather than asserted.

### Timing

Hourly, on the day of the declaration:

- Rain peaks at **03:00** (77 mm in the hour at Berhampore)
- Movement crosses the disruption threshold at **07:00**
- State of emergency declared at **17:25**

Ten hours between the first flagged hour and the declaration. That means the
signal was **visible**, not that it was **predictive** - an operator watching it
would still have had to decide the drop mattered, and the same reading appears on
days that never become emergencies.

## 6. What I would not claim

- Thresholds are fitted to one event. One event is not a validation set.
- Nothing has been tested against a non-weather disruption: a quake, a cordon, a
  major outage.
- Counts are hourly, so nothing can be detected before the end of the hour it
  happens in.
- Sensors cover instrumented streets only. A sensor knocked out by a storm is
  indistinguishable from a street nobody used.
- The ground-truth timeline is from news reporting, not a Council incident log.
  Times are approximate except the declaration.
- 12 April is flagged but falls outside the rainfall window, so it is unverified
  either way.

## 7. Gaps in the public data worth naming in a pitch

- No public marae dataset.
- No aged-care or retirement-village dataset. The most vulnerable populations
  have the worst data.
- No inbound channel from the public - problem 2 is building the missing piece,
  not integrating one.
- No Council incident log, so no clean ground truth for past events.
