# The five problems, mapped to data that exists

Written before team assignments were published, so it covers all five. For each:
what the load-bearing sources are, what is missing, and the honest trap.

Every problem shares one constraint worth designing for from the start:
prototypes are meant to feed a shared common operating picture. Emitting a
clean, documented feed of your own output is worth more than a prettier map.

---

## 1. Official warnings plus local conditions in one community view

**Load-bearing sources**

- MetService weather warnings, CAP format, via the Eagle ArcGIS layer. This is
  the licence-safe route; the `metservice.com` JSON works keylessly but every
  payload carries a restricted-use notice, so it is demo-only.
- NEMA mobile alert polygons - the authoritative "was an official alert actually
  broadcast over this area".
- Hilltop rainfall and river level - the only genuinely high-cadence local
  observation, 5-minute to hourly.
- GeoNet quakes and the Wellington harbour detided sea level.
- WCC road closures, Wellington Water faults, electricity and 2degrees outages
  for what is actually broken near you.

**What is missing**: nothing publishes "conditions on my street". The gap
between a regional warning and a street-level observation is the whole problem,
and no dataset closes it. Say so rather than implying otherwise.

**The trap**: a warning polygon covers half the region, so "you are in a
warning" is almost always true and almost never useful. The value is in joining
the warning to a local observation - this gauge, this closure, this outage -
and being explicit that absence of a local signal is not absence of risk.

---

## 2. Two-way channel between communities and Council

**Load-bearing sources**

- Community emergency hubs (126 region-wide, 36 in Wellington City) - the
  existing physical two-way channel. Licence is CC BY-NC-ND 4.0, the one
  restrictive one.
- WCC Emergency Assistance Centres layer - published but intentionally empty; it
  populates when Council activates. Wire it in and it lights up on its own.
- Address points and building footprints for locating a report.
- CDEM group boundaries for routing a report to whoever owns the response.

**What is missing**: the inbound half. There is no public intake API. You are
building the missing piece, not integrating an existing one, so the interesting
design questions are acknowledgement, deduplication and triage, not transport.

**The trap**: a reporting tool with no one on the other end is worse than no
tool, because it implies a response that will not come. Design the acknowledgement
honestly - "received, not yet reviewed" beats a green tick. WCC had ten
activations in two years; ask what their actual intake volume looks like before
assuming your queue design is realistic.

---

## 3. Detect and verify emerging impacts from public information

**Load-bearing sources**

- RNZ national RSS - live, 45 items on a quiet day. Note WCC's and GWRC's own
  news RSS both 404; RNZ is the working feed.
- GeoNet felt reports (crowdsourced) against measured intensity - a ready-made
  worked example of an unverified signal next to an instrumented one.
- Wellington Water faults (1,442 open jobs) - real, addressed, near-real-time
  impact reports.
- Electricity and telco outages, road closures, FENZ incidents.
- Transport counts as an independent corroborating signal.

**What is missing**: social media at any usable scale. Do not build the demo
around it.

**The trap**: this problem explicitly asks you to show reliability limits, so
the scoring is as much about the honesty surface as the detection. A signal
presented for verification with its provenance, timestamp, and what would
falsify it beats a confident wrong answer. The felt-vs-measured intensity pair
is the cleanest available demonstration that two sources can disagree.

---

## 4. Help staff sort and prioritise incoming information

**This is team 3's assigned problem.** A grounded corpus with an answer key and a
corroboration engine are already built - see the main SKILL.md. What follows is
the original survey, which still holds.

**Load-bearing sources**

- Wellington Water's 1,442 open jobs, with addresses, priorities and status -
  the only realistic corpus of messy inbound operational text available publicly.
- FENZ historic incident CSVs, eight years, CC-BY 4.0, no coordinates - geocode
  via suburb and territorial authority.
- Deprivation and social vulnerability indices for a defensible prioritisation
  input that is not just "who shouted loudest".
- Emergency routes with staged reopening order, for prioritising by consequence.

**What is missing**: real Council intake - the phone, email and social traffic
the problem describes. You will have to synthesise it, so be explicit that you
did, and derive the synthetic set from the real fault corpus rather than
inventing it.

**The trap**: any ranking encodes a value judgement about whose problem matters
most. Make the weighting visible and adjustable rather than burying it, and
expect the WCC expert in the room to have strong views about it - that
conversation is the point.

---

## 5. Detect unusual changes in movement

**Load-bearing sources**

- **WCC transport sensors.** 408 countlines, hourly directional counts by mode,
  back to November 2023, as monthly CSVs. This is the load-bearing source and it
  is not in the organisers' catalogue. Countline geometry is an ArcGIS layer; the
  counts are separate S3 CSVs, about 45 MB per month.
- NZTA carriageway status, delays and cameras.
- Metlink GTFS for the network graph; realtime needs a free key, so register
  beforehand.
- OpenSky flight movements - a drop to zero is a fast unofficial airport-closure
  signal.

**What is missing**: Pōneke Travel Insights itself is a Council dashboard, not a
public API. The sensor counts above are the underlying public data.

**The trap**: a public holiday looks almost exactly like an emergency in total
volume. Good Friday 2026 was -43% on the day; the April flood was -44%. Without
a discriminator your detector cries wolf every long weekend. See
`scripts/detect_disruption.py` for the mode-composition approach, which clears
all three April public holidays but still has a known false positive. Also, a
sensor knocked out by the storm is indistinguishable from a street nobody used.

---

## If you get to choose an angle

The cross-problem joins are where the interesting work is, and they are cheap
now that the sources are verified:

- Movement anomaly plus rainfall - separates "unusual" from "unusual and
  explained", and is the difference between an alert and an insight (3 and 5).
- Alert polygon plus hubs plus outages - "an alert went out over this area;
  which hubs are inside it and do they have power" (1 and 2).
- Any impact signal plus deprivation - who in the affected area is least able to
  self-evacuate (all five).
