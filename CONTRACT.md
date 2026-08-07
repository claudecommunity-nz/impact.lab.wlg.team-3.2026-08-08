# The contract

Two developers, two Claude instances, one repo. This file is the seam between
them. If you only read one thing before starting, read this.

## The pipe

```
  corpus (76 reports, 20 April 2026)  ─┐
                                       ├─→  server.py  ─→  triage.assess()  ─→  store
  live reports typed into the form    ─┘                                          │
                                                                                  ↓
                                        GET /api/state          →  the dashboard
                                        GET /api/reports.geojson →  everyone else's map
```

Reports arrive two ways and are treated identically from the moment they land.
Nothing downstream knows or cares which was which, beyond a `source` field.

## The seam: `triage.assess(report) -> dict`

This is the only place the two halves meet. Change what is *inside* `assess`
freely. Changing the keys it returns means telling the other person.

Input — one report:

```json
{
  "id": "R0023",
  "received_at": "2026-04-20T04:19:00",
  "channel": "form",
  "text": "Water coming up over the road at Hataitai, getting deeper",
  "source_url": null
}
```

`channel` is one of `phone`, `form`, `social`, `email`, `news`, `partner`.

Output — the assessment:

| Key | Type | Meaning |
|---|---|---|
| `place` | str \| null | Place name as matched |
| `lat`, `lon` | float \| null | Coordinates. Null when unlocated **or ambiguous** |
| `candidates` | list | Every gazetteer match. More than one means ambiguous |
| `ambiguous` | bool | Same name exists in more than one place |
| `issue` | str | `flooding`, `slip`, `road`, `power`, `water`, `tree`, `other` |
| `category` | str | `action`, `verify`, `awareness` |
| `confidence` | float | 0.0–1.0 |
| `incident` | str \| null | Grouping key. Reports sharing one are duplicates |
| `signals` | list[str] | Human-readable reasons, shown in the interface |
| `assessed_by` | str | Which assessor produced this |

`signals` is not decoration. The brief asks for reliability to be visible, and
the judging criteria reward honesty about limits. Every assessment has to be
able to say why it landed where it did.

Two deliberate decisions worth keeping:

- **Ambiguous places get no coordinates.** Frederick Street is in both Tawa and
  Te Aro. We do not pick one. Silently guessing a location is the exact failure
  mode this problem statement is most wary of.
- **A broken assessor never loses a report.** `server.py` catches exceptions
  from `assess` and stores the report unassessed with the error in `signals`.
  Losing an incoming report is worse than showing an unassessed one.

## The API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Clock, summary counts, every report received so far. The dashboard polls this |
| GET | `/api/reports.geojson` | Assessed located reports as a FeatureCollection — the common operating picture output |
| POST | `/api/reports` | Live intake. `{channel, text, source_url?}` → the assessed record |
| POST | `/api/clock` | `{action: start\|pause\|reset, speed?}` |

Run it:

```bash
python3 server.py        # http://localhost:8777/
```

Stdlib only. No pip install, no API keys, no network needed.

## The number to beat

Scored against `data/answer-key.json`, on the **32 human-written reports**
(the other 44 are partner job records with no ground-truth location):

| | Baseline |
|---|---|
| Location correct | 25/32 — 78% |
| Category correct | 6/32 — **19%** |
| Incident groups found | 11 vs 16 true |

The category number is the interesting one. Truth on those 32 is 18 `action`
and 14 `verify`, with no `awareness` at all. The baseline calls `action`
**twice**, and puts 13 reports in `awareness` where none belong.

It systematically buries things that need action. For an emergency tool that is
the worst possible direction to be wrong in, and it is the gap worth closing.

Score it yourself:

```bash
python3 score.py
```

## Working agreement

1. **Split by file.** Two Claude instances editing one file is the thing that
   will cost you an hour. Agree who owns what before you start.
2. **Decisions go in `CLAUDE.md`, not just in the room.** The other person's
   Claude cannot hear you. If it matters, write it down and push it.
3. **Small commits, push often, say when you push.** Straight to `main` — on a
   five-hour clock, branches cost more in merge overhead than they save.
