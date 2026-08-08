# EOC Reporting Triage

**Problem 04 — Help emergency staff sort and prioritise incoming information.**

Sorts incoming disaster reportings into **action required**, **verification
required** and **situational awareness**, keeps a complete audit trail of every
human decision, and turns that trail into a **shift handover briefing** so
nothing received on one shift dies at the changeover.

> Prototype built for Impact Lab Wellington. The reportings are simulated.
> **Not an operational emergency system — in an emergency, call 111.**

```bash
pip install -r requirements.txt
echo "CLAUDE_API_KEY=sk-ant-..." > .env   # gitignored; or use provider: ollama
./run.sh --seed          # loads a Wellington storm scenario and starts on :8000
```

Open <http://localhost:8000>. API docs at `/docs`.

---

## What it does

**1. Takes reportings from anywhere.** Call centre, email, web form, social
media, news and partner agencies each get an *adapter* in
[`config/sources.yaml`](config/sources.yaml) that maps their fields onto one
canonical schema. Adding a feed is a YAML edit, not a code change.

**2. Triages assistively, not automatically.** A rule engine scores each
reporting and shows its working — every point traces to a named rule. An LLM
gives a second opinion, or drafts a whole ruleset from the controller's declared
hazard and response timeline. The machine orders the queue; the human decides.

**3. Records everything.** Every acknowledgement, override, note, status change
and forward is an append-only audit event, stamped with the operator and the
shift. Click any reporting to see its full history.

**4. Consolidates duplicates.** Reportings about one event collapse into a
single queue row — see below. **5. Hands over cleanly.** The briefing is
assembled from the live queue and the audit trail, led by the reportings
**nobody has ever opened**.

---

## The three priorities

| | Meaning |
|---|---|
| **Action required** | Credible, specific, and something must be tasked now. |
| **Verification required** | Plausible and significant, but not solid enough to send a crew on. |
| **Situational awareness** | Background, commentary, minor or already known. |

Priority is separate from **status** (`new`, `acknowledged`, `in_review`,
`verified`, `forwarded`, `false_reporting`, `closed`, …). A reporting can be
*action required* and still *new* — nobody has picked it up. That gap is exactly
what the handover briefing exists to surface.

---

## The queue

One row per **event**, not per reporting, in the order an operator scans:

| Date-time received | Due by | Location | Category | Potential loss of life | Triage status | Done |
|---|---|---|---|---|---|---|

There is deliberately no description column: it is per-reporting, it is long,
and a consolidated row has several of them. The description lives in the
expanded view, which is the only place the individual reportings appear.
Download the same rows as CSV from the toolbar, or `GET /api/v1/consolidated.csv`.

**Nothing moves under the cursor.** Opening a row does not reorder it — being
read is not a fact about the event, so it is not in the ordering. The only
thing that moves a row is ticking it **Done**, which sends it to the bottom of
the queue where it stays visible and struck through rather than vanishing.
Untick to bring it back.

### Due by

*When does this have to be dealt with?* — the question the received time cannot
answer.

- **Action-required events** get one. If the reporting states an interval —
  "the concentrator goes flat in about three hours" — that is the deadline,
  counted from when that reporting arrived, and the row shows the phrase it was
  read from. Otherwise the row gets **30 minutes** from arrival, tagged
  `assumed`, because a deadline nobody chose should not read like one somebody
  did.
- **Obligations** are due at a time by definition; theirs is the time from the
  timetable. Their received column is blank — they were never received.
- **Everything else** shows an em dash. Awareness and verification rows have no
  deadline to miss, and a clock on every row is a clock nobody reads.

The countdown ticks client-side and an **Overdue** badge appears the moment the
time passes, rather than at the next poll. Extraction is deliberately narrow
(`app/duetime.py`): explicit relative intervals only, nothing in a past-tense
clause, nothing over three days. A due time that is wrong is worse than none,
because it moves a row for a reason nobody can see.

**Potential loss of life is a separate column from priority on purpose.**
Priority answers *what do I work on next*; life risk answers *could someone
die*. They usually agree and sometimes don't — a confirmed road closure is
action-required with no life risk, and a vague third-hand report of someone in
the water is only verification-required while carrying the worst possible
consequence. An operator scanning a queue needs both.

### Administrative obligations

Upload a timetable of the admin obligations a responder is held to — handovers,
sitreps, public updates — in Settings → **Administrative timetable**, or
`PUT /api/v1/obligations`. Only `due_at` is required (ISO 8601 with an offset);
everything else is shown in the row when present.

```json
{"obligations": [
  {"id": "BR-001", "type": "handover", "short_label": "handover",
   "label": "Shift handover briefing — day to night (OP-1)",
   "due_at": "2026-08-07T18:45:00+12:00",
   "owner_role": "Control", "audience": "internal",
   "score_bearing": false, "shift_ref": "SH-N1", "notes": "..."}
]}
```

They appear in the same queue as the reportings, on pink rows, because that is
the screen the operator actually watches — a handover missed because it was on
another tab is missed just the same. Each one carries a live countdown and a
**Done** tick, and discharging one is audited like any other decision — it
drops to the bottom of the queue rather than disappearing.

**They climb as the deadline runs down** — overdue and due-now rows sit near the
top, a four-hour-out obligation sits near the bottom.

**They can never outrank an action-required reporting.** Someone is in the water
right now; the sitrep waits. This is a hard ceiling, not a weighting: everything
in the queue is placed on one numeric scale, action-required reportings start at
1000, and `obligations.queue_score` caps below that. A close deadline cannot
overcome it, and no amount of tuning the bands can accidentally break it.

Between those two rules, obligations do interleave with verification-required
and situational-awareness reportings — an overdue sitrep outranks a social post
that needs checking, which is the point.

The completion state lives in the database, not written back into the uploaded
file: the timetable is reference data, whether a thing was *done* is state.

### Consolidation

Reportings merge into one row when they are **in very close proximity
(250 m), in the same register, and about the same category**. Wording overlap
is a supporting signal, not the deciding one — people describe the same event in
completely different words, and different events on one street in very similar
ones.

The register test (`sentiment`) is what stops a rumour being merged into a real
incident. A caller sounds *distressed*, the crew confirming the same slip sounds
*informational*, a bystander sounds *concerned* — all three are one event. But
"is it true there's a tsunami warning" is *speculative*, and never merges into a
report of an actual tsunami. Commentary is likewise kept apart.

On the demo corpus this collapses 26 reportings into 19 rows: the Ngaio Gorge
slip becomes one row with three sources (call, social post, roading confirmation)
and the tsunami rumour becomes one row with four.

Consolidated rows carry a caret. Expanding one shows the event description and
every source under it; each source clicks through to its full record.

### Row actions

- **The Done tick** closes the whole event and sends the row to the bottom of
  the queue. A group is not done while any member is still open, and every
  member gets its own audit event.
- **The priority dropdown** overrides the automated triage. It applies to every
  reporting in the group so the row and its sources cannot disagree, and asks
  for a reason that goes into the audit trail and the handover briefing.
- **Opening a consolidated row** acknowledges everything under it — which is
  what keeps "never opened" honest.

## The audit trail and shift handover

The end user changes on a shift basis, and the event does not stop for the
changeover. The risk this system is built around is specific: a call that came
in at 03:10, that nobody ever opened, still sitting in the queue when the next
controller arrives and starts from the top.

Two mechanisms close it.

**Per-reporting audit trail.** Click any row in the priority-sorted queue and
the detail pane shows every event against it in order — who opened it first,
who changed the priority and the reason they typed, every note, every forward
and whether the receiving agency replied. Opening a reporting is itself an
audited event, which is what makes "never opened" a real measurement rather
than a guess.

**Handover briefing** (Handover tab). Assembled on demand from the queue and
the audit trail, so it cannot drift from them. It is *optional* — the queue and
the per-reporting trails hold the same information — but it arranges that
information the way an incoming controller needs it:

1. **Never opened** — nobody has looked at these at all.
2. **Open and action required** — live work.
3. **Stalled** — opened, then no activity for 45+ minutes.
4. **Awaiting verification** — leads to chase.
5. **Forwarded, no reply** — we asked another agency and heard nothing.
6. **Ruled out this shift** — already assessed false, so nobody redoes the work.
7. **Every operator decision**, with the reason given.

Every line clicks through to the reporting. The shift picker beside the buttons
chooses which shift the briefing is about — usually the one that just ended.
The model can add a summary paragraph on top; the lists remain the record.

**Export.** Markdown at `/api/v1/handover/{id}/markdown`, or **Export PDF** for
the A4 shift report the outgoing controller hands over: the same briefing, with
part 1 for what to pick up first and part 2 for every decision the last shift
made and the reason given, read straight off the audit trail. Built from the
same object the screen renders, so the paper and the screen cannot disagree.
`GET /api/v1/handover/pdf?shift_id=…` builds one fresh for any shift;
`GET /api/v1/handover/{id}/pdf` renders a briefing that was already filed.

---

## Configuration

Everything that governs triage is YAML in [`config/`](config/), hot-reloaded and
editable from the Settings tab.

| File | What |
|---|---|
| [`settings.yaml`](config/settings.yaml) | Engine mode, LLM, dedupe, geocoding, forwarding |
| [`destinations.yaml`](config/destinations.yaml) | Where reportings can be forwarded |
| [`sources.yaml`](config/sources.yaml) | Input adapters and field mappings |

### How a rule works

Each reporting starts at `base_score`. Every matching rule adds its `score`.
The total decides the bucket. A rule can also `force_priority` (escalate) or
`cap_priority` (hold back):

```yaml
- id: life_safety_language
  label: Life-safety language in reporting
  when:
    any_keywords: [trapped, unconscious, drowning, "can't get out"]
  score: 55
  force_priority: action_required

- id: unverified_social
  label: Social media — unverified by default
  when:
    channel: [social_media]
  score: 0
  cap_priority: verification_required
```

A cap holds a reporting back unless a rule explicitly forced it higher — so a
social post saying someone is trapped still reaches *action required*, while an
ordinary post cannot climb past *verification required* without a human.

## Model provider

Set `llm.provider` in [`settings.yaml`](config/settings.yaml):

| | |
|---|---|
| `anthropic` (default) | Claude API — `claude-opus-5`. Needs `CLAUDE_API_KEY` in `triage/.env` (gitignored). |
| `ollama` | A local model. No API key, no network egress — the option if reporting content must not leave the building. |

Everything works either way; the difference is quality and where the data goes.
Both are exercised by the same prompts and the same JSON schemas, so switching
is a one-line config change with no code edit.

Three things the Claude path does that the local path can't:

- **Schema-enforced output.** `output_config.format` makes the API guarantee the
  response shape, so there is no fence-stripping or brace-matching to go wrong —
  and for ruleset drafting it constrains the model to valid condition keys.
- **Prompt caching.** The classification system prompt is identical for every
  reporting, so it is marked cacheable and paid for once per event rather than
  once per reporting.
- **Refusal handling.** Emergency content (entrapment, fire, injury) is exactly
  the sort of material that can trip a safety classifier. `stop_reason` is
  checked before the response body is read, and `refusal_fallbacks: true` lets
  the API re-run a declined request on a fallback model in the same call rather
  than dropping the reporting.

Effort is set per job in `settings.yaml` — classification is high-volume and runs
at `low` (~4-5s per reporting); ruleset drafting is the one genuinely hard
reasoning task and runs at `high`.

### Triage instructions for the event

Settings → **Triage instructions**. Write or upload a Markdown file describing
how *this* event should be triaged, in the words you would use for a colleague:

```markdown
## Already known — do not escalate
- Ngaio Gorge Road is closed and a crew is on site. Further reports are awareness only.

## Treat as action required
- Anyone dependent on powered medical equipment while the power is out.
```

It is handed to the model with every reporting, and it works — a post about the
Ngaio slip comes back *"already known with a crew on site, so further reports
are awareness only"*, and a report of a home dialysis machine with no power
comes back action-required citing the instruction.

The scoring rules still run underneath and still produce the explainable score.
The instructions steer the model; they do not switch off the guard rails —
social media is still capped at verification-required, and clusters a controller
marked false are still held back, whatever the Markdown says. The instructions
also cannot *lower* a priority on their own, because the model may escalate but
not de-escalate; a human can, per row, from the queue.

Stored at `config/instructions.md`. Empty is a valid state — with no file the
system behaves exactly as it did before.

---

## Input schema

Canonical shape in [`app/models.py`](app/models.py). Post to
`/api/v1/ingest?adapter=<id>` in the source system's own shape and the adapter
maps it; post without an adapter and the body must already be canonical.

```
Reporting
  source     channel, system, external_id, permalink, author, received_at,
             ingested_by, credibility_hint
  content    text, transcript (call audio), subject, summary, language,
             media[] { kind, url, caption, caption_source, model_caption }
  location   text, lat, lon, accuracy_m, method, suburb, confidence
  reporter   name, phone, email, organisation, is_official
  occurred_at, tags, raw
```

Two invariants:

- **`source.permalink` and `raw` are always preserved.** Nothing inferred
  replaces what was actually said, and an operator can always get back to the
  original.
- **Anything the machine derived lives under `triage`**, never mixed into
  `content` — so the UI can always show *what came in* separately from *what we
  think about it*. A model-generated image caption is labelled as such and never
  presented as the author's words.

### For the social-media team

Full contract with an annotated example payload is in
[`config/sources.yaml`](config/sources.yaml) under the `social_media` adapter.

```
POST /api/v1/ingest?adapter=social_media
{"items": [{ "post_id": "...", "platform": "x", "url": "...",
             "posted_at": "...", "text": "...",
             "author": {...}, "media": [...], "geo": {...},
             "engagement": {...}, "credibility": 0.4 }]}
```

Re-posting the same `post_id` is a no-op, so replays are safe. Any field not in
the mapping is still kept verbatim under `raw` and shown in the detail pane.

---

## Duplicate grouping

Reportings are grouped by token overlap plus a location and time gate — no
embeddings, so an operator can be told in one sentence why two things were
grouped, and the grouping is always visible and reversible.

Grouping carries decisions forward. Mark one member a **false reporting** and
every member is marked too; any *future* reporting that matches arrives held
back and flagged with the original assessment attached — visible to an operator,
never silently discarded.

---

## Map and the common operating picture

The Map tab plots only what is operationally relevant (action + verification by
default). Pin opacity carries confidence: solid means a location we were given,
faded means one inferred from the wording. An inferred pin must never look like
a known one.

The same data is a plain GeoJSON feed for the other Impact Lab modules:

```
GET /api/v1/geojson                                  # map_priorities from settings
GET /api/v1/geojson?priorities=action_required
GET /api/v1/geojson?all_priorities=true
```

Each feature carries its provenance, `verification` state, `location_method`
and `location_precise`, so a consumer can tell an unverified public post from a
confirmed partner-agency update without asking us.

---

## Forwarding

Destinations are configured in `destinations.yaml` — email (SMTP) or HTTP API.
`forwarding.dry_run: true` (the default) composes and records the exact outbound
payload without sending it. The composed email carries the verification status,
the triage reasoning, the source link and the operator action log, so the
receiving agency gets the reasoning rather than a bare assertion.

Forwards with no reply are a headline section in the handover briefing.

---

## API

| | |
|---|---|
| `POST /api/v1/ingest` | Accept reportings (single, list or batch) |
| `GET /api/v1/reportings` | The queue, ordered as an operator should work it |
| `GET /api/v1/reportings/{id}` | Detail, triage reasoning, audit trail, cluster, forwards |
| `POST /api/v1/reportings/{id}/{acknowledge,priority,status,note,assign,false,forward,retriage}` | Operator actions — all audited |
| `GET /api/v1/geojson` | Map feed for the shared COP |
| `GET /api/v1/audit` | Audit stream, filterable by shift, actor, action |
| `POST /api/v1/shifts/start`, `POST /api/v1/shifts/{id}/end` | Shift management |
| `GET /api/v1/handover/preview`, `POST /api/v1/handover` | Briefing |
| `GET /api/v1/handover/pdf`, `GET /api/v1/handover/{id}/pdf` | The shift report as an A4 PDF |
| `GET/PUT /api/v1/config/{name}` | Live configuration |
| `GET /api/v1/consolidated` | The queue, one row per event |
| `GET /api/v1/consolidated.csv` | The same rows as CSV |
| `POST /api/v1/consolidated/{id}/{done,priority,acknowledge}` | Whole-event actions |
| `GET/PUT/DELETE /api/v1/instructions` | The controller's triage instructions |
| `GET/PUT/DELETE /api/v1/obligations` | The administrative timetable |
| `POST /api/v1/obligations/{id}/done` | Discharge or reopen an obligation |
| `POST /api/v1/instructions/upload` | Upload an instruction.md |
| `POST /api/v1/retriage` | Re-run triage (operator overrides are preserved) |

---

## Design decisions worth knowing

- **A machine may escalate, only a human may de-escalate.** In hybrid mode the
  LLM can raise a priority but not lower one (`engine.llm_may_downgrade`).
  Quietly demoting a reporting has the worst consequences of any error here.
  A worked example: on a social post saying someone is trapped in a car, the
  rules force *action required* and the model says *verification required*
  (unverified source). The higher is kept and the disagreement is shown.
- **Disagreements are surfaced, not resolved.** When the rules and the model
  disagree the higher priority is kept and the conflict is shown to the operator.
- **Operator overrides survive re-triage.** Changing the ruleset never silently
  moves something a human decided.
- **Nothing is deleted.** Reversing a false-reporting call supersedes the
  original assessment in the trail rather than erasing it.

## Layout

```
app/
  models.py      canonical schema (Reporting, TriageResult, AuditEvent, Shift)
  ingest.py      adapters: upstream payload → canonical
  db.py          SQLite; audit_events is append-only
  audit.py       shifts + the only supported path for state changes
  handover.py    briefing assembly and Markdown rendering
  forward.py     email / API forwarding
  feeds.py       GeoJSON for the map and the COP
  api.py         HTTP API
  consolidate.py rolls clusters up into one queue row per event
  instructions.py the controller's instructions.md
  obligations.py the administrative timetable and its due-time banding
  demo.py        Wellington storm corpus + a partly-worked night shift
  triage/
    rules.py     deterministic scoring
    llm.py       prompts + JSON schemas: classify, draft rulesets, summarise
    providers/   claude.py (Claude API) and ollama.py, one interface
    dedupe.py    grouping
    geocode.py   Wellington gazetteer
    engine.py    orchestration and merge policy
static/          no build step — plain ES modules, MapLibre vendored locally
config/          the YAML above
```
