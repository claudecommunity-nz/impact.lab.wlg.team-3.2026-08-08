# Sightline — a live triage board for an Emergency Operations Centre

**Impact Lab Wellington · Team 3 · Problem Statement 04**
Wellington City Council Emergency Management × Claude Code Community NZ — Saturday 8 August 2026

> **Hazard-planning exercise data. Not an operational emergency source.**
> All reports, names and timings in this folder are synthetic. In an emergency, call 111.

## Demo video

https://drive.google.com/file/d/1AxcZkZwVv3L2ePE4eSiHi0Vyy0EP4eW1/view?usp=drive_link

##

Online demo temporarily available at https://queensland-physics-leaders-barely.trycloudflare.com

---

## The problem

> **How might we help emergency staff rapidly sort incoming reports into information for
> awareness, information requiring verification, and information requiring action?**

During an event, information arrives through phone calls, emails, forms, social media,
news reports and partner agencies. Collecting it is not the hard part. Staff have to work
out where it relates to, whether it is new or a duplicate of something already on the
board, how reliable it might be, and whether it needs someone tasked to it.

**Desired outcome:** staff spend less time sorting information and more time checking
significant reports and coordinating action.

---

## What Sightline is

A live triage board built around one test:
**someone walks into the EOC cold and can answer: "what are the top three things that need to happen next, and why?" in under thirty seconds.**

The board holds two time streams of action items in one view

- **Incoming event reports** — what the public, hubs, agencies and media are telling us.
- **EOC plan obligations** — sit reps, handovers, public information releases and checkpoints that fall due at fixed times whether or not anything is happening.

### What the AI does

|                      |                                                                                                                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Triage**           | Sorts each report into _awareness_, _verification required_, or _action required_                                                                                                   |
| **Consolidate**      | Groups reports about the same event into a single action item, so one thing that happened is one row on the board — not eight                                                       |
| **Handover summary** | Writes the top paragraph and up to eight watch items over the shift briefing, badged as AI-generated. The lists underneath it are assembled deterministically and remain the record |
| **Sit rep**          | _(not built yet)_ Draft a situational report from themes derived across the whole board, traceable back to the report IDs behind each claim                                         |

### What the human does

|                                                  |                                                                                                                                                                      |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Override the triage**                          | The machine assigns a priority, the operator can change it — with a reason, applied to every report in a consolidated row so the row and its sources cannot disagree |
| **Complete and clear**                           | Mark an event done and take it off the action board. A group is not done while any member is still open                                                              |
| **Acknowledge, note, assign, forward, rule out** | The rest of the operator vocabulary, each one audited                                                                                                                |
| **Set a time due**                               | _(not built yet)_ Attach a deadline to an incident so it ages and escalates against the clock. Obligations already carry due times and countdowns; reports do not    |

Every one of those decisions is written to an **event log**, so the board can always say who did what, when, and why. Also what makes an after-action review or an OIA response possible.

---

## Running it

```bash
cd triage && pip install -r requirements.txt && ./run.sh --seed
```

`--seed` loads a Wellington storm scenario with a partly-worked night shift behind it.
Board on <http://localhost:8000>, API docs at `/docs`, map feed at `/api/v1/geojson`.

FastAPI + SQLite. The front end is plain ES modules with no build step; MapLibre is
vendored locally.

## How it works

**Reports come in from anywhere.** Call centre, email, web form, social media, news and
partner agencies each get an _adapter_ in `triage/config/sources.yaml` that maps their
fields onto one canonical schema. Adding a feed is a YAML edit, not a code change. The
social-media contract is `POST /api/v1/ingest?adapter=social_media`; re-posting the same
`post_id` is a no-op, so replays are safe.

**Nothing inferred overwrites what was said.** The original permalink and the raw payload
are always preserved, and everything the machine derived lives under `triage`, never mixed
into the content — so the UI can always show _what came in_ separately from _what we think
about it_.

**Triage is assistive, not automatic.** A rule engine scores each report and shows its
working: every point traces to a named rule. The model gives a second opinion. Where they
disagree the higher priority is kept and the conflict is shown rather than resolved — a
machine may escalate, only a human may de-escalate. Operator overrides survive re-triage.

**Consolidation** merges reports within 250 m, in the same register, about the same
category. Wording overlap is a supporting signal, not the deciding one. The register test
is what stops a rumour merging into a real incident — "is it true there's a tsunami
warning" is speculative and never joins a report of an actual tsunami. On the demo corpus
this collapses 26 reports into 19 rows: the Ngaio Gorge slip becomes one row with three
sources (call, social post, roading confirmation).

**Obligations share the queue** with the reports, on their own rows, because that is the
screen the operator actually watches. They climb as their deadline runs down, and they can
never outrank an action-required report — a hard ceiling on one numeric scale, not a
weighting that a close deadline could eventually overcome. Someone is in the water right
now; the sitrep waits.

**Triage instructions for this event** are Markdown, written the way you would brief a
colleague ("Ngaio Gorge Road is closed and a crew is on site — further reports are
awareness only"). Handed to the model with every report. They steer it; they do not switch
off the guard rails — social media stays capped at verification-required, and the
instructions cannot lower a priority on their own.

**The handover briefing** is the risk this system is built around: a call that came in at
03:10, that nobody ever opened, still sitting in the queue when the next controller
arrives and starts from the top. Assembled on demand from the live queue and the audit
trail so it cannot drift from them, led by the reports **nobody has ever opened**, then
open action-required work, stalled items, leads awaiting verification, forwards that got
no reply, and what was ruled out this shift. Every line clicks through. Export as Markdown.

## Feeding the common operating picture

The map plots only what is operationally relevant. Pin opacity carries confidence: solid
is a location we were given, faded is one inferred from the wording — an inferred pin must
never look like a known one.

The same data is a plain GeoJSON feed for the other Impact Lab modules:

```
GET /api/v1/geojson                                  # operationally relevant by default
GET /api/v1/geojson?priorities=action_required
GET /api/v1/geojson?all_priorities=true
```

Each feature carries its provenance, verification state, location method and whether the
location is precise — so a consumer can tell an unverified public post from a confirmed
partner-agency update without asking us.

## Model provider

`anthropic` by default (Claude API, `claude-opus-5`, needs `CLAUDE_API_KEY` in
`triage/.env`, gitignored), or `ollama` for a local model with no network egress — the
option if report content must not leave the building. One line in `settings.yaml`, no code
change. Same prompts, same JSON schemas either way.

## Not built yet

Kept here deliberately so we know what is outstanding.

- **Time due on a report.** Obligations have `due_at`, a live countdown and deadline-driven
  ordering. Reports have no equivalent — an operator cannot attach a deadline to an
  incident and watch it escalate against the clock.
- **Sit rep drafting.** The model writes a summary and watch items over the handover
  briefing today. It does not derive themes across the whole board or cite the report IDs
  behind each claim.

## Layout

```
triage/
  app/       models, ingest adapters, append-only audit, handover assembly,
             forwarding, GeoJSON feeds, consolidation, obligations, HTTP API
  app/triage/ deterministic rules, LLM prompts and schemas, provider adapters
             (Claude / Ollama), grouping, Wellington gazetteer, orchestration
  config/    settings, sources, destinations, triage rules, instructions — all YAML,
             hot-reloaded and editable from the Settings tab
  static/    the board — plain ES modules, no build step
```

Full detail on the input schema, the rule format and the ingest contract is in
[triage/README.md](triage/README.md).
