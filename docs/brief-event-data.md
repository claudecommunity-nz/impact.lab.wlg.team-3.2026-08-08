# Brief: event data generation and replay

For the agent building the data half of the prototype. The other half — the
server and the dashboard — is owned by someone else. See [CONTRACT.md](../CONTRACT.md)
for the seam between them.

---

You are building the data generation half of a Wellington City Council emergency
management prototype, at a one-day Impact Lab. It is Saturday 8 August 2026 and
submissions close at 16:00. Scope accordingly: a narrow thing that works beats a
broad thing that doesn't demo.

## The problem

Team 3's problem statement, verbatim from WCC:

> How might we help emergency staff rapidly sort incoming reports into
> information for awareness, information requiring verification, and
> information requiring action?

During an event, information arrives through phone calls, emails, forms, social
media, news reports and partner agencies. Staff must identify where it relates
to, whether it is new or duplicated, how reliable it may be, and whether it
requires action.

## Your job, precisely

Produce a replayable stream of incoming reports for a real Wellington
emergency, plus the observational data needed to corroborate them, and a pusher
that plays the stream into a running server in accelerated real time.

You do NOT build the dashboard, and you do NOT modify `server.py` or anything
under `app/`. Another developer owns those. Your boundary is: everything under
`build/` and `data/event/`, plus `push.py`. Stay inside it.

## The event

Monday 20 April 2026. Wellington region flooding. A state of emergency was
declared at 17:25 by the Wellington CDEM Group joint committee. 134 mm of rain
fell at Berhampore, 77 mm of it in the single hour to 03:00 — three times any
other hour in the last nine months of record. Around 200 weather-related
callouts were attended from 02:00. Streets in Wainuiomata were evacuated.
Roughly ten dwellings across Berhampore, Mornington and South Karori were left
uninhabitable. An Emergency Assistance Centre opened at 18:00 at the Wellington
City Mission, Oxford Terrace.

Ground truth is in `Mark's prep/data/replay/april-2026/ground-truth.json`. Read
it first. Everything you generate must be traceable to something in it, to the
gauge record, or to the cited news reporting.

## What is real and what you must generate

**Real — fetch once, freeze to disk, never fetch at demo time:**

- Rainfall, 19 reporting gauges, hourly. GWRC Hilltop, full history.
- River level (Stage), same source.
- Transport counts, 408 countlines, hourly by mode. WCC S3 CSVs.
- Six NEMA CAP alerts issued 18–23 April 2026. That layer keeps history.
- RNZ article URLs from the day, listed in `ground-truth.json`.

**Generate — no public record exists for that day, so build them into the real
schema and label every record as generated:**

- The incoming report stream. This is your primary deliverable.
- Wellington Water fault jobs (30-field schema, live layer index 5).
- WCC road closures (10-field polyline schema).
- Electricity outages (14-field NEMA schema).

`.claude/skills/wellington-emergency-data/` documents every endpoint and a dozen
traps that each cost an hour. Read it before writing a single request.
`Mark's prep/scripts/sources.py` has stdlib-only helpers that already handle the
gzip, projection and encoding traps. Reuse it rather than reinventing.

## The report stream — the thing that matters

Target 200–400 reports across 03:00 to 22:00, weighted so the queue visibly
drowns during the 03:00 downpour and again around the 17:25 declaration. A human
must not be able to keep up. That is the point: the triage has to visibly earn
its place.

Use all six channels the problem statement names, in a realistic mix. Phone
calls and social media should dominate, not partner records. Partner job records
are pre-structured and are the easy case — keep them a minority.

The stream must contain, because staff really face all of these:

- **Duplicates.** The same incident reported by several people, in different
  words, on different channels, minutes apart. This is what makes grouping worth
  doing — aim for clusters of 3 to 8.
- **Vague locations.** "the bottom of the valley", "near the school".
- **Ambiguous locations.** Wellington has several Rata Streets; the evacuated one
  is in Wainuiomata. 46 names in the gazetteer have more than one location.
  Include some, because refusing to guess is a feature.
- **Second-hand chatter.** "Someone posted that…", "can anyone confirm".
- **At least two plausible but unfounded reports**, placed where every nearby
  gauge was dry, so false-positive handling can be demonstrated.
- **Reports out of step with the instruments** — some arriving before anything
  shows on a gauge, some long after the incident. Time matters as much as place.
- **A handful with no resolvable location at all.**

Write like the channel. A 3am phone call transcript is fragmentary and
frightened. A social post is short with poor punctuation. A partner agency email
is formal and structured. If every report reads the same, the demo dies.

## Two contracts you must honour

### 1. The bundle

Your output is a frozen directory the server knows nothing about beyond its
shape:

```
data/event/2026-04-20/
  manifest.json          provenance per file: real or generated, source
                         endpoint, licence, publisher, when fetched
  reports.jsonl          the stream, one JSON object per line, sorted by
                         received_at ascending
  answer-key.json        ground truth, held SEPARATELY so triage is scored
                         not admired
  observations/          rainfall.json river.json movement.json
                         cap-alerts.json — all real
  feeds/                 water-faults.json road-closures.json outages.json
                         — all generated, in real schemas
```

A `reports.jsonl` record:

```json
{"id": "R0001",
 "received_at": "2026-04-20T03:41:00+12:00",
 "channel": "phone|email|form|social|news|partner",
 "text": "...",
 "source_url": null,
 "origin": "generated"}
```

Nothing else. No truth fields, no assessments. The answer key holds truth, keyed
by id, and records: true location and coordinates, the issue, which incident it
belongs to (so duplicate detection can be measured), whether it is unfounded,
and a one-line basis citing the ground truth or gauge reading that justifies it.

### 2. The pusher

`push.py` reads the bundle and POSTs each report to
`http://localhost:8777/api/reports` as its moment arrives. It owns the clock and
therefore owns what "realtime" means.

| Flag | Meaning |
|---|---|
| `--speed N` | Wall-clock seconds to event seconds. Default 600, so the 19-hour night runs in under two minutes |
| `--from HH:MM` | Start partway through, for rehearsing a specific moment |
| `--once` | Push everything immediately, for testing |

It must be interruptible with Ctrl-C, print a readable ticker, and be re-runnable
without duplicating — the server is a dumb store, so make `push.py` idempotent on
report id.

## Honesty rules, non-negotiable

This repo is public, and "honesty about limits" is an explicit judging criterion.
Generated content that could be mistaken for a real Council record is the failure
mode these problem statements are most wary of.

- Every generated record carries a flag saying so. Every generated file is listed
  as generated in the manifest.
- No real people. No real phone numbers, names, or addresses of actual residents.
  Streets and suburbs are fine; house numbers on evacuated streets are not.
- Attribute every real source to its publisher, with the licence, in the
  manifest. The data belongs to WCC, GWRC, NEMA and MetService, not to us.
- Do not overstate the ground truth. It comes from news reporting, not a Council
  incident log. Say so in the manifest.

## Verification before you claim it works

1. `python3 build/build_event.py` regenerates the whole bundle from scratch and
   is deterministic — same input, same output, seeded RNG.
2. The answer key covers every report id, and every id appears exactly once.
3. Duplicate clusters actually cluster: report the distribution of cluster sizes
   and eyeball a few.
4. Start the server, run `python3 push.py --speed 900`, and confirm reports land
   through the API. Show the ticker output.
5. Print counts by channel, by hour and by incident, and check the surge lands
   where the rain did.

Do not report the bundle as finished until you have run all five and can paste
the output.

## Git

Work in an isolated worktree off the `mark` branch:

```bash
git worktree add .worktrees/event-data -b feat/event-data mark
cd .worktrees/event-data
```

Commit early and often — the repo is the submission. Conventional commit
messages, lower-case subject. Do not merge yourself; push the branch and say it
is ready.

## Read these first, in this order

1. [CONTRACT.md](../CONTRACT.md) — the seam between the halves, and the current
   baseline score.
2. `.claude/skills/wellington-emergency-data/` — endpoints and traps. Note the
   path-map table at the top; the skill was written against a different layout.
3. `Mark's prep/data/replay/april-2026/ground-truth.json` — what actually
   happened.
4. `Mark's prep/data/corpus/reports.json` and `answer-key.json` — the existing
   76-report corpus. Right idea, wrong scale and wrong mix: 54% of it is
   pre-structured partner job records, which are the easy case. Reuse its
   structure and its discipline of a separate answer key; replace its contents.

Ask before you widen scope. If something in this brief is wrong or impossible,
say so rather than working around it silently.

## Known wrinkle

`server.py` currently runs its own internal replay clock that releases the old
76-report corpus. If it is still doing that when you run `push.py`, reports will
arrive from both sources at once. Raise it rather than working around it — the
clock is being removed from the server, because the pusher owns time.
