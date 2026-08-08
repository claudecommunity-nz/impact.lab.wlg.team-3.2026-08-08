# Solution brief — Problem 04

*Drafted 7 Aug 2026, the evening before. Every data claim below was probed
against the live endpoints; counts are from that probe and will have moved.*

---

## 1. Two insights, one of which decides the whole build

### a. Triage is a corroboration problem, not a classification problem

The statement reads like text classification: messy reports in, three buckets
out. That framing leads to the obvious build — a text box, an LLM call, a
coloured label. It demos in thirty seconds and it is unconvincing, because the
only question a judge has is *"why should I believe the label?"* and the answer
is "the model said so."

The three lanes are really three states of **evidence**:

| Lane | What it actually means |
|---|---|
| Awareness | Something authoritative already agrees, and consequence is low |
| Verify | Nothing authoritative agrees yet, but consequence would be high |
| Act | Something authoritative agrees **and** consequence is high |

Pulling location/time/issue/urgency out of free text is the easy half, and an
LLM does it well. The half that picks the lane is: *does an independent
authoritative source corroborate this, and does the ground it sits on make it
consequential?* Wellington's GIS stack answers both.

### b. The five problems are one pipeline, and we are its hub

Reading all five statements together, they are not five parallel ideas. They
are stages of a single flow — and 04 is the middle of it:

```
   P02  community form//hub reports ─┐
   P03  public online signals ───────┼──►  P04  TRIAGE  ──►  P01  community view
   P05  movement anomalies ──────────┘     (us)          └─►  shared common
   +    live council feeds ──────────┘                        operating picture
```

- **P02 (Team 5)** builds a two-way channel where residents submit structured
  reports and **"see whether an issue is being checked or acted on."** That
  status *is our lane output*. P02 cannot close its loop without something like
  us.
- **P03 (Team 4)** collects public online content and explicitly produces
  **"signals for an intelligence team to investigate"** — that is a direct
  feed into our VERIFY lane.
- **P05 (Team 7)** detects movement anomalies and wants to compare them with
  **"weather warnings, road closures or public reports."** They are both an
  input to us and a corroborator for us.
- **P01 (Team 1)** shows the public official advice alongside **"trusted
  reports of local conditions,"** distinguishing verified from unverified.
  Our lane + certainty is what lets them label anything honestly.

**Strategic consequence:** if we publish an input and output schema by ~09:45
and walk it round the room, other teams can code against it, and we become
structurally central to the shared common operating picture. The judging brief
says *"prefer outputs that compose."* This is the strongest available version
of composing.

Nothing about our build may *depend* on another team delivering. We build
adapters; the live council feeds are adapter #1 and they already work. Any team
that shows up with data is a bonus we can wire in during the afternoon.

## 2. What we build

**A triage queue that shows its working.** Reports arrive from any adapter, get
parsed, cross-referenced against live council feeds and hazard layers, grouped
with their duplicates, and land in one of three lanes — each with a visible
evidence chain and a link back to source.

The unit of the interface is not a label. It is a **card that argues its case**,
which staff can accept in one click or override in two.

## 3. Why this beats the obvious build

Another team works this same statement and will very likely ship LLM text
classification. Three things separate us:

1. **Evidence, not vibes.** Every lane assignment cites named datasets.
2. **The LLM never picks the lane.** It extracts facts; explicit rules over
   those facts choose the lane. The system therefore *cannot* silently promote
   an unverified public post to "act" — the exact failure mode the ground rules
   single out. This is an auditability argument, and it is the most persuasive
   thing we can say to a room of emergency managers.
3. **Real reports, live, from Wellington.** We don't need to fabricate an inbox.

### Staying out of Team 4's lane

P03 also clusters and corroborates, so there is genuine overlap risk. The line:
**they work public online content and answer "is something emerging?"; we work
every inbound channel and answer "what should staff do next?"** Our
differentiators are the lane rules, the human review queue, and status
write-back. If we find ourselves building a social-media scraper, we have
drifted into their project and should stop.

## 4. The data — verified, not assumed

The catalogue's framing is "hazard-planning layers." That undersells it. **Six
of the 74 datasets are live operational feeds**, and one is a genuine stream of
public reports. Probed 7 Aug, all responding:

| Feed | Live count | Why it matters |
|---|---|---|
| `water-network-faults` | **820 open WCC jobs** | Real public reports — see below |
| `nzta-warnings` | 3 area + 2 point in Wgtn | Road closures, official |
| `nema-cap-alerts` | 2 polygons touching Wgtn | What was broadcast, to which ground |
| `electricity-outages` | 37 national, 0 Wgtn | Corroborates "power's out" |
| `metservice-warnings` | 1 national, **0 Wgtn** | Often empty — don't build on it |
| `shaking-layers` (GNS) | — | Post-quake ground motion |
| `rainfall-observations` | Hilltop telemetry | Corroborates flooding reports |

### The find: `water-network-faults` is already an incoming-report queue

Fields include `description`, `wsadd_formattedaddress`, `reportdate`,
`priority`, `watertype`, and `sourcecode: "Council Integration"` with refs like
`WCCSR-1239122`. These are **customer service requests from the public** —
pre-geocoded to lat/lng, timestamped. Most recent WCC record at probe time was
**17:07 that same day**: `Fault 19 ADAMS TERRACE, Aro Valley [Urgent/Waste Water]`.

So the core demo runs on **real Wellington reports arriving today**. We add a
small, clearly-labelled synthetic set only for the channels the feed lacks
(social post, phone transcript, partner email) — marked synthetic in the UI.

### The duplicates are real too

Of 820 open WCC jobs, **61 sit at an address with more than one open job (7%)**
— and that is exact string matching, so it understates the real rate. Live
examples: `113 Calcutta Street, Khandallah` ×3, `182 The Parade, Island Bay` ×3,
`Riddiford Street, Newtown` ×3. We don't have to stage the dedup demo; the
council's own feed contains duplicates and we catch them.

## 5. Worked example — this is the demo

The real 17:07 report, run through the full join. All of this executed
successfully against live endpoints:

> **`Fault 19 ADAMS TERRACE, Aro Valley`** · Urgent · Waste Water · 17:07 today
>
> **Ground:** NZDep2023 decile **9 of 10** — one of the most deprived SA1s in
> the city, 177 residents.
> **Consequence:** 500 m from **Aro Valley Community Emergency Hub**; on a
> **stage-1 post-quake reopening route** (`wccReopStg: 1`, the highest priority
> stage WCC reopens).
> **Not corroborated by:** ponding areas, overland flowpath, liquefaction
> overlay, tsunami evacuation zone — all miss.
> **Related:** **11 open water faults within 400 m**, including
> `33 ADAMS TERRACE` (22 Jul) and four on Devon Street.
>
> → **ACT.** Urgent wastewater fault, dense cluster, high-deprivation
> population, on a stage-1 lifeline route.

One screen, generated from real data. Worth more than any classifier output.

## 6. Architecture

```
 adapters ──► extract ──► locate ──► corroborate ──► cluster ──► lane ──► queue
 (live +      (LLM,       (gazetteer  (spatial join   (space +   (rules,     │
  other        structured)  or given)   vs layers)     time +     not LLM)   │
  teams)                                               text)                 │
                                                                             ▼
                                              /feed.geojson  +  /status/{id}
```

**Adapters.** Everything normalises to one `Report` shape. One adapter per
source; a new source is a new adapter and nothing else changes.

**Extract.** One LLM call per report, structured output: location text, event
time, issue category, claimed urgency, and the **verbatim quote span** each
field came from. The UI shows the quote beside the extracted value so staff can
check the parse without opening the source.

**Locate.** The water feed is pre-geocoded. For free text, build a gazetteer
from the `roads` layer plus hub suburb names rather than taking an external
geocoder dependency. Keep a confidence on the match — "Aro Valley" is a suburb
polygon, "19 Adams Terrace" is a point, and that difference matters.

**Corroborate.** Spatial join against live feeds and hazard layers. Each hit is
`Evidence{source, dataset_id, relation, detail, weight}`. Record misses too —
"no MetService warning covers this" is real information.

**Cluster.** Proximity (≤400 m) + time window + issue category + text
similarity. One incident, many reports, every source link preserved.

**Lane.** Explicit rules over the evidence (§8).

**Output.** Queue UI, `/feed.geojson`, and `/status/{report_id}` for P02's
acknowledgement loop. Emit CAP vocabulary — `urgency` / `severity` /
`certainty` — since `nema-cap-alerts` already speaks it. `certainty`
(Observed / Likely / Possible / Unlikely) *is* the reliability axis the problem
asks us to expose, and adopting a standard rather than inventing one is worth
saying out loud in the demo.

## 7. The interchange contract — publish this early

Write these two schemas first, put them in the README, and walk them round the
room before 10:00. Cheap to define, and it is what makes us the hub.

**In** — anything anyone sends us:

```json
{ "id": "team5-0042", "source_type": "community_form|social|phone|email|sensor|agency",
  "source_url": "https://…", "received_at": "2026-08-08T14:32:00+12:00",
  "raw_text": "Water over the road at…", "reporter_reliability": "unknown|known|official",
  "geom": {"type":"Point","coordinates":[174.76,-41.29]},   // optional
  "media": ["https://…"] }                                   // optional
```

**Out** — GeoJSON `Feature` per triaged item:

```json
{ "type":"Feature", "geometry": {...},
  "properties": {
    "incident_id":"inc-17", "lane":"act|verify|awareness",
    "urgency":"Immediate", "severity":"Severe", "certainty":"Likely",
    "issue":"wastewater_overflow", "summary":"…",
    "evidence":[{"source":"deprivation-2023","relation":"within","detail":"decile 9"}],
    "member_reports":[{"id":"…","source_url":"…","received_at":"…"}],
    "status":"new|checking|actioned|dismissed",
    "inferred": true, "provenance":"extracted_by_model" }}
```

Two join keys worth agreeing in the room: **`COUNTLINE_ID`** for Team 7 (the
`transport-sensors` layer has 408 countlines with IDs and geometry but no
counts — their movement data lives in Pōneke Travel Insights, so an ID is how
we place their anomalies), and **`SA12023_code`** for anything aggregated by
area.

## 8. The triage rule — the core IP

Keep this in one readable file. Judges will ask, and "here it is, forty lines,
read it" is a strong answer.

```
corroborated  = any evidence from an authoritative live feed
consequential = high deprivation OR near hub OR on emergency route
                OR inside a modelled hazard extent OR cluster size >= 3

if duplicate_of_existing_incident        -> AWARENESS (merge, bump incident weight)
elif corroborated and consequential      -> ACT
elif corroborated and not consequential  -> AWARENESS
elif consequential and not corroborated  -> VERIFY   ← the lane that earns its keep
elif conflicting evidence                -> VERIFY
else                                     -> AWARENESS
```

**VERIFY** is what justifies the project: exactly the reports that matter if
true and that nothing has confirmed yet — the ones a human should spend time
on. Every other lane is the system buying that time back.

## 9. Scope for the day

Six and a half hours minus lunch. Cut lines in order:

**Must (by ~13:30)** — water-faults adapter; extract; corroborate against three
layers (deprivation, hubs, emergency routes); lane rules; list view.
*This alone is a demo.*

**Should (by ~15:00)** — map; clustering/dedup; evidence chain on cards;
synthetic multi-channel reports; `/feed.geojson`; published schemas.

**Could (only if ahead)** — human override + status write-back; rainfall/river
telemetry; a live adapter against whatever Team 5 or Team 4 actually produced.

**Won't** — auth, persistence beyond a JSON file, real social APIs, mobile,
anything not on screen at 16:30.

**Freeze at 15:30.** The last 30 minutes are rehearsal. The most common way
this day goes wrong is a team still wiring at 16:25.

One person should own the cross-team conversation in the morning without
blocking the build — schemas out by 10:00, then back to building.

## 10. The four minutes

1. **(30s) The problem, concretely.** "820 open water jobs in Wellington right
   now. 7% are duplicates. Staff triage this by reading."
2. **(45s) A report arrives** — real, from today. Watch it parse.
3. **(90s) The evidence chain.** Decile 9, 500 m from a hub, stage-1 lifeline
   route, 11 faults within 400 m → ACT. *This is the moment; spend the time.*
4. **(45s) The VERIFY lane.** A consequential report nothing corroborates —
   "this is what we're buying you time to check."
5. **(30s) It composes.** `/feed.geojson` on the shared map, and: "this takes
   Team 5's reports and Team 4's signals, and hands Team 1 something they can
   honestly label verified."

Open on real data, close on the pipeline.

## 11. Traps — verified, not folklore

- **`reportdate > <epoch millis>` returns HTTP 400** on the water faults
  service. Use `reportdate > DATE '2026-07-01'`.
- **Filter `councilid='WCC'`.** A Wellington bbox returns 1,246 faults because
  it catches Hutt City; WCC alone is 820.
- **Paging is real here** — the water feed sets `exceededTransferLimit` at
  1,000 records.
- **`outSR=4326` on everything**, per the README.
- **MetService returned 0 features for Wellington** at probe time. Any demo
  beat that assumes a live weather warning exists will fail on stage. Treat
  empty as the expected case.
- 21 of 74 datasets are **climate-projection rasters** — irrelevant here and
  they refuse feature queries. Ignore the whole `Climate Data` theme.

## 12. Constraints we have to respect

- **The water feed carries residential street addresses.** This repo is public
  and must stay free of personal information. **Query at runtime; never commit
  a dump.** Cache to a gitignored path if we want offline demo resilience.
- **Say what's inferred.** Every card must visually distinguish *reported*
  (what the source said), *extracted* (what the model parsed), and *inferred*
  (what the spatial join added). This is the ground rule these statements care
  most about — and it's a design asset, since showing the seams is what makes
  it credible.
- **Not an operational source.** Banner it. In an emergency, 111.
- **Attribution** per dataset: WCC, Greater Wellington, Wellington Water, GNS,
  NEMA, NZTA.

## 13. Decisions to make at 09:30

- **Stack.** Python for the pipeline (the SDK is Python, no deps) + a
  single-page MapLibre front end over served GeoJSON. Resist a framework.
- **Where the LLM runs.** Batch-extract once at startup over ~50 reports and
  cache to disk rather than inferring live per report. A demo that waits on
  inference is a demo that stalls. Keep one live parse for the "watch it
  arrive" beat.
- **How many corroboration layers.** Three good ones beat ten flaky ones.
  Deprivation, hubs and emergency routes all returned clean results tonight.
