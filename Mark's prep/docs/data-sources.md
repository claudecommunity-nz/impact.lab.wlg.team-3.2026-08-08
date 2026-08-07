# Wellington emergency data — what exists, and what it's good for

A distillation for Team 3. Everything below was hit and confirmed returning real
data. Status figures are from `python3 scripts/check_feeds.py`, which takes about
seven seconds — run it rather than trusting this page.

## Three things that will cost you an hour each

**1. Most emergency feeds are empty by design, and that is correct.**
GWRC's incident layer, WCC's Emergency Assistance Centres layer and the Civil
Defence alert RSS publish nothing between activations. They are not broken. Do
not debug them. Either handle empty as a real state or drive the demo from the
April 2026 replay bundle in `data/replay/april-2026/`.

**2. Coordinates are NZTM2000 (EPSG:2193), not lat/long.**
Always pass `outSR=4326`. Without it you get numbers in the millions and a map
centred off the coast of Africa. The exception is Hilltop, which returns WGS84
directly.

**3. Queries cap silently.**
ArcGIS layers stop at `maxRecordCount` (usually 1000–2000) and set
`exceededTransferLimit` instead of erroring. A suspiciously round number of
records means you are being truncated.

## Live right now

All 19 checked feeds were up this morning. Counts are what each held at the time.

| Feed | Holds | Good for |
|---|---|---|
| Wellington Water faults | ~1,437 open jobs | **Real inbound operational text**, addresses, priorities, statuses |
| WCC emergency routes | 429 segments | Post-quake road reopening order |
| NZTA traffic cameras | 319 | Live JPEGs; check `Offline`/`UnderMaintenance` first |
| WCC transport sensor lines | 408 countlines | Movement; hourly counts are separate CSVs |
| NZTA delays | ~118 | Current road delays |
| Community emergency hubs | 126 | Where communities gather post-disaster |
| NEMA mobile alert polygons | 108 | **Was an official alert broadcast over this area** |
| GeoNet quakes | 100 | Seconds-to-minutes latency |
| Hilltop rainfall gauges | 51 listed | The only genuinely high-cadence local observation |
| WCC road closures | ~60 | Includes planned events, not just incidents |
| NEMA electricity outages | ~44 | 18 lines companies nationally |
| RNZ national news RSS | ~42 | The only working news feed — WCC's and GWRC's own both 404 |
| 2degrees mobile outages | ~11 | Only public telco outage feed that is a plain GET |
| GeoNet felt reports | ~5 | **Crowdsourced**, pairs with instrumented intensity |
| MetService warnings (CAP) | 3 active | Official warnings, licence-safe route |
| Wellington Electricity outages | ~2 | Higher resolution than NEMA for our patch |
| Wellington harbour sea level | live | Detided residual — a ready-made surge detector |
| GWRC incident areas | ~1 | Populated during an activation |
| Civil Defence alert RSS | 0 | **Empty is normal** between events |

## By what you actually want

### Official warnings — "has someone in authority said something?"

- **MetService weather warnings (CAP)** via the Eagle ArcGIS layer. Use this
  rather than `metservice.com`'s JSON, which works keylessly but carries a
  restricted-use notice in every payload — demo only.
- **NEMA Emergency Mobile Alert polygons.** The authoritative record of what was
  actually broadcast, with the cell-broadcast target area. Live and historic
  share the layer; filter on `historic`.
- **GeoNet CAP feed** for quakes.
- **Civil Defence alert RSS** — empty between events, by design.

### Observations — "what is actually happening on the ground?"

- **Hilltop telemetry** (`hilltop.gw.govt.nz/Telemetry.hts`) is the important
  one: rainfall, river level and flow, 5-minute to hourly, WGS84 coordinates,
  and it serves history back to at least 2016. That last property is what makes
  replay possible.
- **GeoNet** quakes, measured intensity, and crowdsourced felt reports. The
  measured-versus-felt pair is the cleanest available demonstration that two
  sources can disagree.
- **Wellington harbour sea level** (Tilde, 15-second, detided).
- **Open-Meteo** for forecasts, including 30-day river discharge — the only free
  forward-looking hydrology.

### Infrastructure state — "what is broken?"

Electricity (NEMA national, Wellington Electricity local), water (Wellington
Water's live job list), roads (WCC closures, NZTA delays and cameras), telco
(2degrees only).

### Operational text — "what do real reports look like?"

**Wellington Water's ~1,437 open jobs** are the only realistic corpus of messy
inbound operational text that is public. Real addresses, request types, statuses
and priorities. The live layer is index **5**, not 0 — two similarly named
layers on the same service are dead since 2018.

Also: **FENZ national incident CSVs**, eight years, CC-BY 4.0, no coordinates
(geocode via suburb and territorial authority).

### People — "who is affected, and who can't cope?"

- **NZDep2023** deprivation by small area — 1,936 units intersect Wellington City.
- **EHINZ Social Vulnerability Indicators** — built specifically for natural
  hazards, nine dimensions at SA2 level. Better suited than NZDep for this.
- **Stats NZ 250 m population grid** — population grid × hazard polygon gives a
  defensible "people affected" number with no boundary-join arguments.
- **WCC building footprints** (100,501) and **address points** (101,415).
- **MoE school directory** — 82 schools in Wellington City, 38,197 students.

### Movement

**WCC transport sensors.** 408 countlines, hourly directional counts by mode
(pedestrian, car, cyclist, e-scooter, bus, LGV, OGV, motorbike), back to
November 2023, as monthly CSVs on S3 (~45 MB, 1.4M rows each). Not in the
organisers' catalogue. Also Metlink GTFS (realtime needs a free key) and
OpenSky flights.

### Hazard layers — the organisers' catalogue

74 datasets: **45 queryable feature layers, 25 raster-only, 4 alternative
routes.** Roughly: 21 climate projections, 9 earthquake hazard, 8 flood, 5
landslide, 4 coastal inundation, plus emergency management and lifelines. These
are hazard *planning* layers, not live information.

WCC also published a purpose-built hackathon bundle — 24 layers on one
FeatureServer (`EM_Hackathon_WCC_Layers`) with a `GW_Layers` companion. Largely
overlapping, but it is the officially blessed stack in a single call.

## Traps, in one table

| Trap | What you see | Fix |
|---|---|---|
| NZTM2000 native projection | Coordinates in the millions | `outSR=4326` |
| Silent record caps | A round number, no error | Check `exceededTransferLimit`, then page |
| Hilltop gzips unasked | `not well-formed (invalid token): line 1, column 0` | Decompress when body starts `\x1f\x8b` |
| Hilltop root element varies | `GetData`→`<Hilltop>`, `SiteList`→`<HilltopServer>`, errors also `<HilltopServer>` | Detect errors by the `<Error>` child, never the root tag |
| Listed ≠ reporting | Empty series, no error | 51 rainfall gauges listed; only 19 held data for our window |
| Spaces in Hilltop site names | `No data for site` | Encode as `%20`; a `+` is not decoded server-side |
| Wellington Water layer index | Plausible-looking dead layers | Live one is index **5** |
| NZTA region filter | Silently returns nothing | The string is `'09 - Wellington'` |
| Dead NZTA cameras | Still appear in the feed | Check `Offline` and `UnderMaintenance` |
| Retracted quakes | Appear inline in the feed | Filter `quality == "deleted"` |
| Overpass named areas | Zero results | Use bbox `-41.36,174.70,-41.14,174.90` |
| Some hosts 403 scripts | Ferries, airport, some council pages | Send a User-Agent |
| Same street name, many streets | A point in none of them | Wellington has several Rata Streets — keep candidates apart |
| Street types are wrong in reports | Lookup misses entirely | "Wetherby Street" is really Wetherby Grove — match on the name body |

## Licensing

| Terms | Sources |
|---|---|
| CC-BY | GeoNet (3.0 NZ), LINZ, Stats NZ, Open-Meteo, FENZ incident CSVs, WCC water tanks, EHINZ |
| ODbL | OpenStreetMap / Overpass — attribution and share-alike |
| Restricted | GWRC community hubs (**CC BY-NC-ND**), WCC emergency routes ("consult WCC prior to use"), MetService JSON (demo only) |
| Unstated | Most council ArcGIS services. Fine for the weekend; attribute the publisher |

Attribute publishers in the demo. It costs one line and it is explicitly in the
ground rules.

## What does not exist

Worth saying out loud in the pitch, because it bounds what anyone can honestly
claim:

- **No public inbound channel from the public.** There is no Council intake API.
  Anything on the receiving side is built, not integrated.
- **No Council incident log**, so no clean ground truth for past events. Ours is
  reconstructed from news reporting.
- **No marae dataset.**
- **No aged-care or retirement-village dataset.** The most vulnerable
  populations have the worst data.
- **No usable social media at scale.** Do not build the demo around it.
- **No telco coverage data** beyond 2degrees' outage list.

## For problem 4 specifically

The load-bearing sources are **Wellington Water's job list** (real messy text),
**Hilltop** (the instrument that can corroborate a weather report), **NEMA alert
polygons** (what was officially broadcast), and **deprivation or social
vulnerability** (a defensible prioritisation input that is not just who shouted
loudest).

The one part of this problem where public data does real work is **reliability**:
a report can be checked against an instrument. `scripts/corroborate.py` does
that, and `data/corpus/` gives 76 reports with an answer key so the sorting can
be scored rather than admired.

Remember the brief's own constraint: *"Display reliability explicitly. Never
present unverified public posts as confirmed fact."*
