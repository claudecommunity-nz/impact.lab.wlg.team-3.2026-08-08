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
reporting and shows its working — every point traces to a named rule. A local
LLM can give a second opinion, or draft a whole ruleset from the controller's
declared hazard and response timeline. The machine orders the queue; the human
decides.

**3. Records everything.** Every acknowledgement, override, note, status change
and forward is an append-only audit event, stamped with the operator and the
shift. Click any reporting to see its full history.

**4. Hands over cleanly.** The briefing is assembled from the live queue and the
audit trail, led by the reportings **nobody has ever opened**.

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

Every line clicks through to the reporting. Export as Markdown at
`/api/v1/handover/{id}/markdown`. A local model can add a summary paragraph on
top; the lists remain the record.

---

## Configuration

Everything that governs triage is YAML in [`config/`](config/), hot-reloaded and
editable from the Settings tab.

| File | What |
|---|---|
| [`triage_rules.yaml`](config/triage_rules.yaml) | Scoring rules, thresholds, hazard categories |
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

### Generating a ruleset from the event

In Settings, describe the hazard and your response timeline ("crews tasked in
2-hour blocks; anything I can't action within 6 hours goes to the morning
plan"). The local model drafts a ruleset. **You review and edit it before it
takes effect** — it is written to `triage_rules.yaml` and shown to you first.
The model writes rules; the rules do the triage, which keeps every live
decision explainable.

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
| `GET/PUT /api/v1/config/{name}` | Live configuration |
| `POST /api/v1/rules/generate` | Draft a ruleset from the event declaration |
| `POST /api/v1/retriage` | Re-run triage (operator overrides are preserved) |

---

## Design decisions worth knowing

- **A machine may escalate, only a human may de-escalate.** In hybrid mode the
  LLM can raise a priority but not lower one (`engine.llm_may_downgrade`).
  Quietly demoting a reporting has the worst consequences of any error here.
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
  demo.py        Wellington storm corpus + a partly-worked night shift
  triage/
    rules.py     deterministic scoring
    llm.py       Ollama: classify, draft rulesets, summarise a shift
    dedupe.py    grouping
    geocode.py   Wellington gazetteer
    engine.py    orchestration and merge policy
static/          no build step — plain ES modules, MapLibre vendored locally
config/          the YAML above
```
