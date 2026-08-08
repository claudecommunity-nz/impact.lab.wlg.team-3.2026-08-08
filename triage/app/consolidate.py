"""The consolidated queue — one row per event, not one row per reporting.

Three calls about one slip are one line an operator works, with the three
sources tucked underneath it. This module rolls the members of each cluster up
into that single row and decides what the row says when its members disagree.

The rollup rules, and why:

* **Priority takes the maximum.** If any member is action-required, the event
  is. Averaging would let two pieces of chatter bury a life-safety call filed
  about the same corner.
* **Life risk takes the maximum**, for the same reason and more so — it is a
  statement about consequence.
* **Received time takes the earliest**, because that is when the EOC first
  heard about this event, which is the number that matters for how long it has
  been sitting there. The latest is carried alongside for "still coming in".
* **Location prefers a confirmed pin** over an inferred one, whichever member
  it came from — one caller giving a real address upgrades the whole row.
* **Done means every member is done.** A group is not finished while any part
  of it is still open.
* **A due time is only ever put on action-required work.** Awareness and
  verification rows have no deadline to miss, and a clock on every row is a
  clock nobody reads.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from . import db, duetime
from .models import (LIFE_RISK_LABEL, LIFE_RISK_RANK, PRIORITY_LABEL,
                     PRIORITY_RANK, SENTIMENT_LABEL, LifeRisk, Priority,
                     Reporting, Sentiment, Status)

# A row is finished when every member has reached one of these.
DONE_STATUSES = {Status.actioned, Status.closed, Status.false_reporting,
                 Status.duplicate}

# How long an action-required event gets when nobody said. Half an hour is the
# EOC's own rule of thumb for "come back to this or hand it on"; it is a
# placeholder that makes the row start counting, not a promise about the work.
DEFAULT_ACTION_DUE_MINUTES = 30


def _best_location(members: list[Reporting]) -> dict:
    """Prefer a confirmed pin; fall back to any pin; then to any place name."""
    precise = [m for m in members if m.location and m.location.is_precise]
    coarse = [m for m in members if m.location and m.location.has_coords]
    named = [m for m in members if m.location and m.location.text]
    pick = (precise or coarse or named or [None])[0]
    if pick is None or pick.location is None:
        return {"location": None, "suburb": None, "lat": None, "lon": None,
                "location_precise": False, "location_method": None}
    loc = pick.location
    return {
        "location": loc.text or loc.suburb,
        "suburb": loc.suburb,
        "lat": loc.lat,
        "lon": loc.lon,
        "location_precise": loc.is_precise,
        "location_method": loc.method.value,
    }


def _description(members: list[Reporting]) -> str:
    """What the event is, for the expanded view.

    Prefers a machine summary if one exists, otherwise the fullest thing
    anyone actually said — the longest excerpt is usually the call transcript
    rather than a two-word social post.
    """
    summaries = [m.content.summary for m in members if m.content.summary]
    if summaries:
        return summaries[0]
    texts = [(m.effective_text() or "").strip() for m in members]
    return max(texts, key=len) if texts else ""


def _due(members: list[Reporting], priority: Priority) -> dict:
    """When this event has to be dealt with by.

    Only action-required events carry one. If a reporter gave an interval —
    "expecting it in three hours" — that is the deadline, counted from when
    that reporting arrived; the earliest one wins, because the event is due
    when the first of its parts is. Otherwise the row gets the default half
    hour, marked as a default so the interface can say so rather than implying
    somebody chose it.
    """
    if priority is not Priority.action_required or not members:
        return {"due_at": None, "due_source": None, "due_phrase": None}

    found = [hit for hit in
             (duetime.extract(m.effective_text(), m.source.received_at)
              for m in members) if hit]
    if found:
        due, phrase, _ = min(found, key=lambda hit: hit[0])
        return {"due_at": due.isoformat(), "due_source": "extracted",
                "due_phrase": phrase}

    first = min(m.source.received_at for m in members)
    return {
        "due_at": (first + timedelta(minutes=DEFAULT_ACTION_DUE_MINUTES)).isoformat(),
        "due_source": "default",
        "due_phrase": None,
    }


def _member_card(r: Reporting) -> dict:
    t = r.triage
    return {
        "id": r.id,
        "received_at": r.source.received_at.isoformat(),
        "channel": r.source.channel.value,
        "source_system": r.source.system,
        "permalink": r.source.permalink,
        "author": r.source.author_display_name or r.source.author_handle,
        "priority": r.priority.value,
        "priority_label": PRIORITY_LABEL[r.priority],
        "priority_overridden": r.priority_overridden,
        "status": r.status.value,
        "life_risk": (t.life_risk.value if t else "none"),
        "sentiment": (t.sentiment.value if t else "informational"),
        "category_label": (t.category_label if t else "General"),
        "description": (r.effective_text() or "").strip(),
        "summary": r.content.summary,
        "location": (r.location.text if r.location else None),
        "location_precise": bool(r.location and r.location.is_precise),
        "acknowledged_by": r.acknowledged_by,
        "assigned_to": r.assigned_to,
        "has_media": bool(r.content.media),
        "rationale": (t.rationale if t else ""),
        "score": (t.score if t else 0),
    }


def group(members: list[Reporting]) -> dict:
    """Roll a cluster's members up into one queue row."""
    members = sorted(members, key=lambda m: m.source.received_at)
    first, latest = members[0], members[-1]

    priority = max((m.priority for m in members),
                   key=lambda p: PRIORITY_RANK[p])
    life_risk = max((m.triage.life_risk if m.triage else LifeRisk.none
                     for m in members), key=lambda v: LIFE_RISK_RANK[v])

    categorised = [m for m in members
                   if m.triage and m.triage.category != "general"]
    lead = (categorised or members)[0]
    sentiment = (lead.triage.sentiment if lead.triage else Sentiment.informational)

    cluster = db.get_cluster(first.cluster_id) or {}
    open_members = [m for m in members if m.status not in DONE_STATUSES]

    return {
        "cluster_id": first.cluster_id,
        "primary_id": first.id,
        "received_at": first.source.received_at.isoformat(),
        "latest_at": latest.source.received_at.isoformat(),
        **_due(members, priority),
        **_best_location(members),
        "category": (lead.triage.category if lead.triage else "general"),
        "category_label": (lead.triage.category_label if lead.triage else "General"),
        "life_risk": life_risk.value,
        "life_risk_label": LIFE_RISK_LABEL[life_risk],
        "sentiment": sentiment.value,
        "sentiment_label": SENTIMENT_LABEL[sentiment],
        "priority": priority.value,
        "priority_label": PRIORITY_LABEL[priority],
        "priority_overridden": any(m.priority_overridden for m in members),
        "status": (first.status.value if len(members) == 1
                   else ("open" if open_members else "done")),
        "done": not open_members,
        "sources": len(members),
        "channels": sorted({m.source.channel.value for m in members}),
        "consolidated": len(members) > 1,
        "description": _description(members),
        "acknowledged": any(m.acknowledged_by for m in members),
        "acknowledged_by": next((m.acknowledged_by for m in members
                                 if m.acknowledged_by), None),
        "assigned_to": next((m.assigned_to for m in members if m.assigned_to), None),
        "flagged_false": bool(cluster.get("flagged_false")),
        "flag_reason": cluster.get("flag_reason"),
        "open_count": len(open_members),
        "members": [_member_card(m) for m in members],
    }


# Where each priority band starts on the shared queue scale. Administrative
# obligations are scored on the same scale (see obligations.py) so the two
# kinds of row interleave — but obligations are hard-capped just below
# ACTION_FLOOR, which is why a deadline can never push paperwork above a
# life-safety reporting no matter how close it gets.
ACTION_FLOOR = 1000
PRIORITY_FLOOR = {
    Priority.action_required: ACTION_FLOOR,
    Priority.verification_required: 500,
    Priority.situational_awareness: 200,
}


def queue_score(g: dict) -> int:
    """Where a consolidated event sits on the shared queue scale.

    Deliberately made only of things about the event itself — its priority and
    its life risk. Whether anyone has *opened* it used to add a few points,
    which meant the row jumped somewhere else the moment an operator clicked
    it. A queue that reorders under the cursor is a queue people lose their
    place in, so being read is now worth nothing here; the filter and the
    counter still surface what nobody has looked at.
    """
    base = PRIORITY_FLOOR[Priority(g["priority"])]
    risk = LIFE_RISK_RANK[LifeRisk(g["life_risk"])] * 10
    return base + risk


def build(reportings: Iterable[Reporting], *, include_done: bool = False) -> list[dict]:
    """Group reportings into consolidated rows, ordered the way to work them."""
    buckets: dict[str, list[Reporting]] = {}
    for r in reportings:
        buckets.setdefault(r.cluster_id or r.id, []).append(r)

    rows = [group(members) for members in buckets.values()]
    if not include_done:
        rows = [g for g in rows if not g["done"]]

    for g in rows:
        g["kind"] = "event"
        g["queue_score"] = queue_score(g)

    rows.sort(key=sort_key)
    return rows


def sort_key(r: dict) -> tuple:
    """The order the queue is worked in.

    Finished rows fall to the bottom rather than vanishing — an operator who
    ticks something off wants to see where it went, and the next shift wants to
    see what this one closed. Everything still open is ordered by the band it
    sits in and then by its deadline, oldest first.
    """
    return (
        1 if r.get("done") else 0,                  # done sinks to the bottom
        -r["queue_score"],
        r.get("due_at") or r.get("received_at") or "",
    )


def merge_rows(events: list[dict], obligations: list[dict]) -> list[dict]:
    """Interleave events and obligations on the shared queue score.

    Obligations climb as their deadline approaches and can overtake
    verification-required and situational-awareness reportings. They can never
    overtake an action-required one — `obligations.queue_score` caps below
    `ACTION_FLOOR`, so the ordering guarantee holds by construction rather than
    by a tie-break that could be tuned away by accident.
    """
    rows = [*events, *obligations]
    rows.sort(key=sort_key)
    return rows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    ("received_at", "Date-time received"),
    ("due_at", "Due by"),
    ("location", "Location"),
    ("category_label", "Category"),
    ("life_risk_label", "Potential loss of life"),
    ("priority_label", "Triage status"),
    ("sources", "Reportings consolidated"),
    ("status", "Status"),
    ("cluster_id", "Group ID"),
]


def to_csv(rows: list[dict], include_description: bool = False) -> str:
    """The queue as CSV — the same columns the table shows.

    The description is off by default because it is the one field the table
    deliberately hides: it is per-reporting, it is long, and in a consolidated
    row there are several of them. Pass include_description to get the event
    description as a final column for offline analysis.
    """
    import csv
    import io

    columns = list(CSV_COLUMNS)
    if include_description:
        columns.append(("description", "Event description"))

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in columns])
    return buf.getvalue()
