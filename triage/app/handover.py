"""Shift handover briefing.

The controller changes every few hours; the event does not. The risk this
module exists to close is a specific one: a reporting that came in at 03:10,
was never opened by anyone, and is still sitting in the queue when the next
person arrives and starts from the top.

The briefing is assembled from the two sources of truth the system already
keeps — the priority-ordered queue and the audit trail — so it can never drift
from them. It is a convenience, not the record: an operator who reads nothing
but the queue and clicks into each reporting's audit trail has the same
information. It is generated on demand, never automatically emailed anywhere.

Sections are ordered by how badly the incoming controller needs them:

1. Never acknowledged        — nobody has looked at these at all.
2. Open and action required  — live work.
3. Stalled                   — action required, opened, then nothing for a while.
4. Awaiting verification     — leads someone has to chase.
5. Forwarded, no reply       — we asked another agency and heard nothing.
6. Already ruled out         — so the next shift does not redo the work.
7. Decisions made this shift — the human judgement calls, with reasons.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import audit as audit_mod
from . import db
from .models import (DECISION_ACTIONS, OPEN_STATUSES, PRIORITY_LABEL,
                     PRIORITY_RANK, AuditAction, AuditEvent, Priority,
                     Reporting, Shift, Status, new_id, utcnow)
from .triage import llm

STALL_MINUTES = 45


def _excerpt(r: Reporting, n: int = 150) -> str:
    text = (r.content.summary or r.effective_text() or "").strip().replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "")


def _where(r: Reporting) -> str:
    if not r.location:
        return "no location"
    if r.location.text:
        return r.location.text + ("" if r.location.is_precise else " (inferred)")
    if r.location.has_coords:
        return f"{r.location.lat:.4f}, {r.location.lon:.4f}"
    return "no location"


def _age(r: Reporting) -> str:
    stamp = r.source.received_at or r.ingested_at
    minutes = int((utcnow() - stamp).total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 1440:
        return f"{minutes // 60}h {minutes % 60}m ago"
    return f"{minutes // 1440}d ago"


def _card(r: Reporting, **extra: Any) -> dict:
    card = {
        "id": r.id,
        "priority": r.priority.value,
        "priority_label": PRIORITY_LABEL[r.priority],
        "status": r.status.value,
        "category": r.triage.category_label if r.triage else "General",
        "channel": r.source.channel.value,
        "source_system": r.source.system,
        "permalink": r.source.permalink,
        "received_at": r.source.received_at.isoformat(),
        "age": _age(r),
        "location": _where(r),
        "excerpt": _excerpt(r),
        "acknowledged_by": r.acknowledged_by,
        "assigned_to": r.assigned_to,
        "priority_overridden": r.priority_overridden,
        "override_reason": r.override_reason,
        "cluster_id": r.cluster_id,
    }
    card.update(extra)
    return card


def _sort_key(r: Reporting) -> tuple:
    stamp = r.source.received_at or r.ingested_at
    return (-PRIORITY_RANK[r.priority], stamp)


def build(shift: Shift | None = None, *, use_llm: bool = False) -> dict:
    """Assemble the briefing for `shift` (defaults to the open one)."""
    shift = shift or db.open_shift()
    reportings = db.all_reportings()
    now = utcnow()

    events: list[AuditEvent] = db.audit_for_shift(shift.id) if shift else []
    touched_this_shift = {e.reporting_id for e in events
                          if e.reporting_id and e.is_human
                          and e.action in DECISION_ACTIONS}

    open_reportings = [r for r in reportings if r.status in OPEN_STATUSES]

    # 1. Nobody has opened these. The headline risk at a shift change.
    never_seen = sorted(
        [r for r in open_reportings if not r.acknowledged_by], key=_sort_key)

    # 2. Live work.
    open_action = sorted(
        [r for r in open_reportings
         if r.priority == Priority.action_required
         and r.status != Status.forwarded],
        key=_sort_key)

    # 3. Opened, then nothing for a while.
    stalled = []
    for r in open_reportings:
        if r.priority != Priority.action_required or not r.acknowledged_by:
            continue
        last = audit_mod.last_human_touch(r.id)
        since = last.at if last else r.ingested_at
        idle = int((now - since).total_seconds() / 60)
        if idle >= STALL_MINUTES:
            stalled.append(_card(
                r, idle_minutes=idle,
                last_action=(f"{last.actor}: {last.action.value}" if last else "none"),
                last_note=last.note if last else None))
    stalled.sort(key=lambda c: -c["idle_minutes"])

    # 4. Leads to chase.
    awaiting_verification = sorted(
        [r for r in open_reportings
         if r.priority == Priority.verification_required
         and r.status not in (Status.verified, Status.actioned)],
        key=_sort_key)

    # 5. We asked someone else and never heard back.
    by_id = {r.id: r for r in reportings}
    forwarded_pending = []
    for f in db.forwards_awaiting_ack():
        r = by_id.get(f.reporting_id)
        if not r or r.status in (Status.closed, Status.false_reporting):
            continue
        waited = int((now - f.sent_at).total_seconds() / 60)
        forwarded_pending.append(_card(
            r, forward_id=f.id, destination=f.destination_name, target=f.target,
            transport=f.transport, dry_run=f.dry_run,
            sent_at=f.sent_at.isoformat(), sent_by=f.sent_by,
            waiting_minutes=waited))
    forwarded_pending.sort(key=lambda c: -c["waiting_minutes"])

    # 6. Already ruled out — so nobody redoes the work.
    ruled_out = []
    for r in reportings:
        if r.status != Status.false_reporting:
            continue
        marked = next((e for e in reversed(db.audit_for_reporting(r.id))
                       if e.action == AuditAction.marked_false), None)
        if not marked:
            continue
        if shift and marked.shift_id != shift.id:
            continue
        ruled_out.append(_card(r, marked_by=marked.actor,
                               marked_at=marked.at.isoformat(),
                               reason=marked.note))

    # 7. Human judgement calls made this shift, with their reasons.
    decisions = []
    for e in events:
        if not e.is_human or e.action not in DECISION_ACTIONS:
            continue
        r = by_id.get(e.reporting_id) if e.reporting_id else None
        decisions.append({
            "at": e.at.isoformat(),
            "actor": e.actor,
            "action": e.action.value,
            "reporting_id": e.reporting_id,
            "excerpt": _excerpt(r, 90) if r else None,
            "field": e.field,
            "from": e.from_value,
            "to": e.to_value,
            "note": e.note,
        })

    overrides = [d for d in decisions if d["action"] == "priority_overridden"]

    ingested = [r for r in reportings
                if shift and r.ingest_shift_id == shift.id]
    by_channel: dict[str, int] = {}
    for r in ingested:
        by_channel[r.source.channel.value] = by_channel.get(r.source.channel.value, 0) + 1

    briefing: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "shift": {
            "id": shift.id if shift else None,
            "operator": shift.operator if shift else None,
            "role": shift.role if shift else None,
            "started_at": shift.started_at.isoformat() if shift else None,
            "ended_at": shift.ended_at.isoformat() if shift and shift.ended_at else None,
            "handover_note": shift.handover_note if shift else None,
            "duration_minutes": int(
                ((shift.ended_at or now) - shift.started_at).total_seconds() / 60)
            if shift else None,
        },
        "totals": {
            "reportings_in_system": len(reportings),
            "received_this_shift": len(ingested),
            "by_channel_this_shift": by_channel,
            "open": len(open_reportings),
            "open_action_required": len(open_action),
            "open_verification_required": len(awaiting_verification),
            "never_acknowledged": len(never_seen),
            "human_decisions_this_shift": len(decisions),
            "reportings_touched_this_shift": len(touched_this_shift),
        },
        "never_acknowledged": [_card(r) for r in never_seen],
        "open_action_required": [_card(r) for r in open_action],
        "stalled": stalled,
        "awaiting_verification": [_card(r) for r in awaiting_verification],
        "forwarded_awaiting_reply": forwarded_pending,
        "ruled_out_this_shift": ruled_out,
        "priority_overrides": overrides,
        "decisions": decisions,
    }

    if use_llm:
        summary = llm.summarise_shift({
            "shift": briefing["shift"],
            "totals": briefing["totals"],
            "never_acknowledged": briefing["never_acknowledged"][:15],
            "open_action_required": briefing["open_action_required"][:15],
            "stalled": briefing["stalled"][:10],
            "forwarded_awaiting_reply": briefing["forwarded_awaiting_reply"][:10],
            "priority_overrides": overrides[:10],
        })
        briefing["llm_summary"] = summary

    return briefing


# ---------------------------------------------------------------------------
# markdown rendering
# ---------------------------------------------------------------------------


def _line(card: dict, *extras: str) -> str:
    bits = [f"- **[{card['priority_label']}]** `{card['id']}` — {card['excerpt'] or '(no text)'}"]
    meta = [card["location"], card["channel"], card["age"], f"status: {card['status']}"]
    if card.get("assigned_to"):
        meta.append(f"assigned: {card['assigned_to']}")
    bits.append(f"  · {' · '.join(str(m) for m in meta if m)}")
    for extra in extras:
        if extra:
            bits.append(f"  · {extra}")
    if card.get("permalink"):
        bits.append(f"  · source: {card['permalink']}")
    return "\n".join(bits)


def to_markdown(b: dict) -> str:
    s = b["shift"]
    out: list[str] = []
    out.append("# Shift handover briefing")
    out.append("")
    out.append(f"**Outgoing operator:** {s.get('operator') or 'unknown'} "
               f"({s.get('role') or 'operator'})  ")
    out.append(f"**Shift:** {s.get('started_at') or '?'} → "
               f"{s.get('ended_at') or 'still open'}  ")
    out.append(f"**Generated:** {b['generated_at']}")
    out.append("")

    llm_summary = b.get("llm_summary") or {}
    if llm_summary.get("summary"):
        out.append("> " + llm_summary["summary"].replace("\n", "\n> "))
        out.append(">")
        out.append("> *Drafted by a local language model from the data below. "
                   "The lists are the record; this paragraph is a convenience.*")
        out.append("")
        if llm_summary.get("watch_items"):
            out.append("**Watch items**")
            out += [f"- {i}" for i in llm_summary["watch_items"]]
            out.append("")

    t = b["totals"]
    out.append("## At a glance")
    out.append("")
    out.append("| | |")
    out.append("|---|---|")
    out.append(f"| Received this shift | {t['received_this_shift']} |")
    out.append(f"| Open now | {t['open']} |")
    out.append(f"| Open — action required | {t['open_action_required']} |")
    out.append(f"| Open — verification required | {t['open_verification_required']} |")
    out.append(f"| **Never acknowledged by anyone** | **{t['never_acknowledged']}** |")
    out.append(f"| Human decisions this shift | {t['human_decisions_this_shift']} |")
    out.append("")

    def section(title: str, key: str, empty: str, *,
                extra=lambda c: ()) -> None:
        cards = b.get(key) or []
        out.append(f"## {title} ({len(cards)})")
        out.append("")
        if not cards:
            out.append(f"_{empty}_")
        else:
            for c in cards:
                out.append(_line(c, *extra(c)))
        out.append("")

    section("Never acknowledged — nobody has opened these", "never_acknowledged",
            "Everything open has been seen by someone.")
    section("Open and action required", "open_action_required",
            "Nothing outstanding at action level.")
    section("Stalled — opened, then no activity", "stalled",
            "Nothing has gone quiet.",
            extra=lambda c: (f"idle {c['idle_minutes']}m; last: {c['last_action']}"
                             + (f" — “{c['last_note']}”" if c.get("last_note") else ""),))
    section("Awaiting verification", "awaiting_verification",
            "No open verification tasks.")
    section("Forwarded — no reply yet", "forwarded_awaiting_reply",
            "No outstanding forwards.",
            extra=lambda c: (f"sent to {c['destination']} ({c['target']}) by "
                             f"{c['sent_by']}, waiting {c['waiting_minutes']}m"
                             + (" [dry run]" if c.get("dry_run") else ""),))
    section("Ruled out this shift — do not rework", "ruled_out_this_shift",
            "Nothing was assessed as a false reporting this shift.",
            extra=lambda c: (f"marked false by {c['marked_by']}"
                             + (f" — “{c['reason']}”" if c.get("reason") else ""),))

    overrides = b.get("priority_overrides") or []
    out.append(f"## Priority overrides this shift ({len(overrides)})")
    out.append("")
    if not overrides:
        out.append("_No automated priorities were overridden._")
    else:
        for o in overrides:
            out.append(f"- `{o['reporting_id']}` {o['from']} → **{o['to']}** "
                       f"by {o['actor']} at {o['at']}")
            if o.get("note"):
                out.append(f"  · reason: “{o['note']}”")
            if o.get("excerpt"):
                out.append(f"  · {o['excerpt']}")
    out.append("")

    decisions = b.get("decisions") or []
    out.append(f"## Full decision log this shift ({len(decisions)})")
    out.append("")
    if not decisions:
        out.append("_No operator decisions recorded._")
    else:
        out.append("| Time | Operator | Action | Reporting | Change | Note |")
        out.append("|---|---|---|---|---|---|")
        for d in decisions:
            change = ""
            if d.get("from") or d.get("to"):
                change = f"{d.get('from') or '—'} → {d.get('to') or '—'}"
            note = (d.get("note") or "").replace("|", "\\|").replace("\n", " ")
            out.append(f"| {d['at']} | {d['actor']} | {d['action']} | "
                       f"`{d.get('reporting_id') or '—'}` | {change} | {note} |")
    out.append("")

    if s.get("handover_note"):
        out.append("## Note from the outgoing operator")
        out.append("")
        out.append(s["handover_note"])
        out.append("")

    out.append("---")
    out.append("")
    out.append("_Generated by the Impact Lab Wellington Team 3 triage prototype "
               "from the live queue and the audit trail. Every line traces back "
               "to an audit event you can open in the app. Prototype only — not "
               "an operational emergency system._")
    return "\n".join(out)


def generate(shift_id: str | None, actor: str, *, use_llm: bool = False) -> dict:
    """Build, render and persist a briefing, and audit that it happened."""
    shift = db.get_shift(shift_id) if shift_id else db.open_shift()
    briefing = build(shift, use_llm=use_llm)
    markdown = to_markdown(briefing)
    hid = new_id("hov")
    db.save_handover(hid, shift.id if shift else None, briefing["generated_at"],
                     actor, markdown, briefing)
    audit_mod.record(
        AuditAction.handover_generated, actor=actor,
        shift_id=shift.id if shift else None,
        note=f"Handover briefing generated ({briefing['totals']['never_acknowledged']} "
             f"never acknowledged, {briefing['totals']['open_action_required']} open at "
             f"action level).",
        detail={"handover_id": hid, "totals": briefing["totals"],
                "llm": bool(use_llm)})
    return {"id": hid, "briefing": briefing, "markdown": markdown}
