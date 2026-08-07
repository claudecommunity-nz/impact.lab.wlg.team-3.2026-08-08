# Brief: the dashboard

For the developer building what emergency staff actually look at. The other
half — generating the report stream and replaying it — is briefed separately in
[brief-event-data.md](brief-event-data.md).

This is a brief, not a specification. The contracts and constraints below are
firm because other people are building against them. Everything else — layout,
interaction, what earns space on screen — is your call. You will have better
instincts about that than this document does.

## The problem

Team 3's problem statement, verbatim from WCC:

> How might we help emergency staff rapidly sort incoming reports into
> information for awareness, information requiring verification, and
> information requiring action?

During an event, information arrives through phone calls, emails, forms, social
media, news reports and partner agencies. Staff must identify where it relates
to, whether it is new or duplicated, how reliable it may be, and whether it
requires action.

**Desired outcome:** staff spend less time sorting information and more time
checking significant reports and coordinating action.

Note what that outcome is about. It is not "a beautiful map". It is staff time.
The strongest thing the demo can end on is a number: how much reading the queue
saved, and how quickly the first thing needing action reached a human.

## The event

Monday 20 April 2026. Wellington region flooding, state of emergency declared at
17:25. 134 mm of rain at Berhampore, 77 mm of it in the single hour to 03:00.
Streets evacuated in Wainuiomata; around ten dwellings left uninhabitable across
Berhampore, Mornington and South Karori.

The WCC people judging this worked that night. They will recognise every street
name on your map, which cuts both ways.

## What already runs

```bash
python3 server.py --replay      # http://localhost:8777/
```

That serves the API below and drives 76 reports from an internal clock, so you
have live data to build against from minute one. Press start in your interface,
or `POST /api/clock {"action":"start","speed":900}`.

When the event bundle lands, the same server runs **without** `--replay` as a
dumb store and a separate pusher feeds it. Your dashboard does not need to know
or care which is happening — the API is identical either way.

## The API — this is firm

| Method | Path | Returns |
|---|---|---|
| GET | `/api/state` | `{clock, summary, reports}` — everything received so far. Poll this |
| GET | `/api/reports.geojson` | Located reports as a FeatureCollection |
| POST | `/api/reports` | `{channel, text, source_url?}` → the assessed record. For the intake form |
| POST | `/api/clock` | `{action: start\|pause\|reset, speed?}` |

Each report in `/api/state` looks like:

```json
{
  "id": "R0023",
  "received_at": "2026-04-20T04:19:00",
  "channel": "form",
  "text": "Water coming up over the road at Hataitai, getting deeper",
  "source_url": null,
  "source": "replay | pushed | live",
  "assessment": {
    "place": "Hataitai",
    "lat": -41.3041, "lon": 174.7980,
    "candidates": [ ... ],
    "ambiguous": false,
    "issue": "flooding",
    "category": "action",
    "confidence": 1.0,
    "incident": "flooding:hataitai",
    "signals": ["urgency wording: “trapped”"],
    "assessed_by": "baseline-v1"
  }
}
```

`summary` gives you `total`, `categories`, `incidents`, `duplicates`,
`unlocated` and `ambiguous` already counted.

Full field meanings are in [CONTRACT.md](../CONTRACT.md). Do not change this
shape without telling the other two — the pusher and the triage both write to it.

## What you own, and what you must not touch

| Yours | `app/` — the dashboard, and only that |
|---|---|
| Not yours | `server.py`, `triage.py`, `score.py` — Mark's |
| Not yours | `build/`, `data/event/`, `push.py` — the data agent's |

Three-way split, no shared files. If you need something from the API that isn't
there, ask rather than editing `server.py`.

## What the interface has to do

These come straight from the problem statement, and each should be visible
without clicking:

- **Where it relates to.** A map. Reports have coordinates, or honestly don't.
- **New or duplicated.** Reports carry an `incident` key; those sharing one
  describe the same thing. Showing 40 separate pins when there are 12 incidents
  is the failure this is meant to fix.
- **How reliable it may be.** Every assessment carries `signals` — plain-English
  reasons it landed where it did. Surface them. Do not make a confidence number
  the only answer.
- **Whether it requires action.** The three buckets, ordered so the urgent one
  cannot be missed.

Two behaviours matter more than they look:

**Show what it could not place.** Some reports have no location. Others are
ambiguous — Wellington has several Rata Streets, and the evacuated one was in
Wainuiomata, so the assessor deliberately refuses to pick. Those must not vanish
just because they have no pin. A report the machine could not handle is exactly
the one a human needs to see.

**Show that it is arriving.** The queue filling in accelerated time is the whole
demo. A static table of 76 rows says nothing; the same 76 arriving over ninety
seconds, faster than anyone could read them, says everything.

## Constraints

- **No network at demo time.** MapLibre is vendored in `app/vendor/`, suburb
  polygons in `data/suburbs.geojson`. No tile keys, no CDN. The venue wifi is a
  coin toss and a four-minute demo cannot survive a timeout.
- **Python 3.9+ and a browser.** No build step, no npm, no framework unless you
  genuinely want one and can guarantee it runs offline.
- **Never present an unverified report as fact.** The judging criteria are
  explicit about this, and it is the failure mode the problem statement is most
  wary of. If something is inferred, say so in the interface.
- **This repo is public.** No participant names or contact details.

## The triage underneath is currently poor, on purpose

`python3 score.py` scores it against a held-back answer key. Right now, on the 32
human-written reports:

| | Baseline |
|---|---|
| Location correct | 25/32 — 78% |
| Category correct | 6/32 — **19%** |
| Incident groups found | 11 vs 16 true |

Truth on those 32 is 18 `action` and 14 `verify`. The baseline calls `action`
**twice**. It systematically buries things that need action.

That is being worked on separately, and it will improve under you without any
API change. Two things follow for the interface:

1. Design for a fallible assessor. A human must be able to disagree with it
   quickly, and see why it decided what it did.
2. Do not hard-code around today's numbers.

## Verification before calling it done

- Runs from a clean clone with `python3 server.py --replay` and nothing else.
- Works with the network off.
- Legible on a projector from the back of a room — that is the actual display.
- Readable in both light and dark; you will not control the room's setup.
- Type a report into the intake form and watch it appear, assessed, on the map.
- Let the full replay run start to finish without the interface degrading.

## Git

Work in an isolated worktree off the `mark` branch:

```bash
git worktree add .worktrees/dashboard -b feat/dashboard mark
cd .worktrees/dashboard
```

Commit early and often — the repo is the submission. Conventional commit
messages, lower-case subject. Push the branch; don't merge to `main` yourself.

## Read these first

1. [CONTRACT.md](../CONTRACT.md) — the API and assessment shape in full.
2. [brief-event-data.md](brief-event-data.md) — what the other half is
   generating, so you know what will eventually flow through.
3. `.claude/skills/wellington-emergency-data/` — endpoints and the traps in the
   Wellington data. Note the path-map table at the top.

## Where the time will go

Highest value first, in the order I would build it:

1. Reports arriving live, grouped by incident, sorted so `action` is unmissable.
2. The map, with unlocated and ambiguous reports visibly accounted for.
3. Evidence on demand — the `signals` behind any assessment.
4. The intake form, so someone in the room can type a report and watch it land.
5. A closing number that speaks to the desired outcome: reports in, incidents
   out, time to first action item, reading avoided.

Number 5 is what the demo should end on, and it is the easiest to run out of
time for. Consider building it early.

If you disagree with any of this, say so — most of it is one person's opinion
formed in a couple of hours.
