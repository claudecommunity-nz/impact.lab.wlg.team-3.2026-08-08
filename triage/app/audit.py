"""Audit and shift engine.

Every change to a reporting goes through this module. Nothing else in the
application is allowed to call `db.save_reporting` for a state change, because
the point of this system is that the next person on shift can reconstruct
exactly what the previous person did and why.

Two things make the trail useful rather than merely present:

* every event is stamped with the **shift** it happened in, so "what changed on
  the night shift" is a query, not an archaeology exercise; and
* `acknowledged_by` records the first human to actually open a reporting, which
  is what lets the handover briefing say "these six were never looked at".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from . import config, db
from .models import (AuditAction, AuditEvent, Priority, Reporting, Shift,
                     Status, utcnow)


# ---------------------------------------------------------------------------
# shifts
# ---------------------------------------------------------------------------


def default_actor() -> str:
    return config.get("settings", "audit.default_actor", "duty.controller")


def current_shift(auto_open: bool = True) -> Optional[Shift]:
    """The open shift, opening a default one on first use so a demo never
    produces audit events that belong to nobody."""
    shift = db.open_shift()
    if shift or not auto_open:
        return shift
    return start_shift(default_actor(), "Duty controller",
                       note="Shift opened automatically on first activity.")


def start_shift(operator: str, role: str = "Duty controller",
                note: str | None = None) -> Shift:
    """Open a new shift, closing any shift still open."""
    existing = db.open_shift()
    if existing:
        end_shift(existing.id, actor=existing.operator,
                  note=f"Closed automatically when {operator} came on shift.")
    shift = Shift(operator=operator, role=role)
    db.save_shift(shift)
    record(AuditAction.shift_started, actor=operator, shift_id=shift.id,
           note=note or f"{operator} started shift.",
           detail={"role": role})
    return shift


def end_shift(shift_id: str, actor: str, note: str | None = None) -> Shift | None:
    shift = db.get_shift(shift_id)
    if not shift or not shift.is_open:
        return shift
    shift.ended_at = utcnow()
    if note:
        shift.handover_note = note
    db.save_shift(shift)
    record(AuditAction.shift_ended, actor=actor, shift_id=shift.id, note=note)
    return shift


# ---------------------------------------------------------------------------
# the audit sink
# ---------------------------------------------------------------------------


def record(action: AuditAction, *, reporting_id: str | None = None,
           actor: str | None = None, is_human: bool = True,
           field: str | None = None, from_value: Any = None,
           to_value: Any = None, note: str | None = None,
           shift_id: str | None = None,
           detail: dict | None = None) -> AuditEvent:
    if shift_id is None:
        shift = current_shift(auto_open=action != AuditAction.shift_started)
        shift_id = shift.id if shift else None
    ev = AuditEvent(
        reporting_id=reporting_id,
        shift_id=shift_id,
        actor=actor or ("system" if not is_human else default_actor()),
        is_human=is_human,
        action=action,
        field=field,
        from_value=None if from_value is None else str(_val(from_value)),
        to_value=None if to_value is None else str(_val(to_value)),
        note=note,
        detail=detail or {},
    )
    return db.append_audit(ev)


def _val(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _touch(r: Reporting) -> None:
    r.updated_at = utcnow()
    db.save_reporting(r)


# ---------------------------------------------------------------------------
# reporting mutations — the only supported way to change state
# ---------------------------------------------------------------------------


def acknowledge(r: Reporting, actor: str, note: str | None = None) -> Reporting:
    """Mark that a human has actually laid eyes on this.

    Idempotent, and quiet on purpose. Only the first acknowledgement is
    recorded as such, because "who first saw it" is the fact the handover
    cares about. A *different* operator opening it later is recorded once as a
    view — useful at handover — but repeat visits by the same person are not,
    since logging every click buries the decisions in noise.
    """
    if r.acknowledged_by:
        seen_before = any(e.actor == actor for e in db.audit_for_reporting(r.id))
        if not seen_before:
            record(AuditAction.viewed, reporting_id=r.id, actor=actor,
                   is_human=True, note=f"{actor} opened this for the first time.")
        return r
    r.acknowledged_by = actor
    r.acknowledged_at = utcnow()
    if r.status == Status.new:
        r.status = Status.acknowledged
    _touch(r)
    record(AuditAction.acknowledged, reporting_id=r.id, actor=actor,
           field="acknowledged_by", to_value=actor, note=note)
    return r


def set_priority(r: Reporting, priority: Priority, actor: str,
                 reason: str | None = None) -> Reporting:
    """Human override of the machine's priority. Always audited, and the
    machine's original verdict is retained in `r.triage` for comparison."""
    if r.priority == priority:
        return r
    previous = r.priority
    r.priority = priority
    r.priority_overridden = True
    r.override_reason = reason
    _touch(r)
    record(AuditAction.priority_overridden, reporting_id=r.id, actor=actor,
           field="priority", from_value=previous, to_value=priority,
           note=reason,
           detail={"machine_priority": r.triage.priority.value if r.triage else None,
                   "machine_score": r.triage.score if r.triage else None})
    return r


def set_status(r: Reporting, status: Status, actor: str,
               note: str | None = None) -> Reporting:
    if r.status == status:
        return r
    previous = r.status
    r.status = status
    _touch(r)
    record(AuditAction.status_changed, reporting_id=r.id, actor=actor,
           field="status", from_value=previous, to_value=status, note=note)
    return r


def assign(r: Reporting, assignee: str | None, actor: str,
           note: str | None = None) -> Reporting:
    previous = r.assigned_to
    r.assigned_to = assignee
    _touch(r)
    record(AuditAction.assigned, reporting_id=r.id, actor=actor,
           field="assigned_to", from_value=previous, to_value=assignee, note=note)
    return r


def add_note(r: Reporting, note: str, actor: str) -> Reporting:
    """A free-text operator note. These carry most of the handover value —
    'called back, no answer', 'FENZ already on site'."""
    record(AuditAction.note_added, reporting_id=r.id, actor=actor, note=note)
    _touch(r)
    return r


def mark_false(r: Reporting, actor: str, reason: str | None = None,
               propagate: bool = True) -> dict:
    """Mark a reporting as false.

    When `propagate` is set (the default) the whole cluster is flagged, so any
    *future* reporting that matches it is held back and labelled rather than
    silently discarded — an operator still sees it, with the previous
    assessment attached.
    """
    previous = r.status
    r.status = Status.false_reporting
    r.priority = Priority.situational_awareness
    r.priority_overridden = True
    r.override_reason = reason or "Assessed as a false reporting."
    _touch(r)
    record(AuditAction.marked_false, reporting_id=r.id, actor=actor,
           field="status", from_value=previous, to_value=Status.false_reporting,
           note=reason)

    affected: list[str] = []
    if propagate and r.cluster_id:
        db.flag_cluster_false(r.cluster_id, actor, reason)
        record(AuditAction.cluster_flagged_false, reporting_id=r.id, actor=actor,
               field="cluster", to_value=r.cluster_id, note=reason,
               detail={"cluster_id": r.cluster_id})
        for member in db.cluster_members(r.cluster_id):
            if member.id == r.id or member.status == Status.false_reporting:
                continue
            member.status = Status.false_reporting
            member.priority = Priority.situational_awareness
            member.priority_overridden = True
            member.override_reason = (
                f"Cluster marked false via {r.id} by {actor}.")
            _touch(member)
            record(AuditAction.marked_false, reporting_id=member.id, actor=actor,
                   field="status", to_value=Status.false_reporting,
                   note=f"Propagated from {r.id}: {reason or 'no reason given'}",
                   detail={"propagated_from": r.id, "cluster_id": r.cluster_id})
            affected.append(member.id)

    return {"reporting_id": r.id, "cluster_id": r.cluster_id,
            "also_marked": affected}


def unmark_false(r: Reporting, actor: str, reason: str | None = None) -> Reporting:
    """Reverse a false-reporting call. The original assessment stays in the
    audit trail — nothing is erased, only superseded."""
    previous = r.status
    r.status = Status.in_review
    _touch(r)
    record(AuditAction.status_changed, reporting_id=r.id, actor=actor,
           field="status", from_value=previous, to_value=Status.in_review,
           note=reason or "False-reporting assessment reversed.")
    if r.cluster_id:
        db.unflag_cluster(r.cluster_id)
        record(AuditAction.cluster_flagged_false, reporting_id=r.id, actor=actor,
               field="cluster", from_value="flagged_false", to_value="cleared",
               note=reason, detail={"cluster_id": r.cluster_id})
    return r


def link_duplicate(r: Reporting, primary_id: str, actor: str,
                   note: str | None = None) -> Reporting:
    r.duplicate_of = primary_id
    previous = r.status
    r.status = Status.duplicate
    _touch(r)
    record(AuditAction.linked_duplicate, reporting_id=r.id, actor=actor,
           field="duplicate_of", from_value=previous, to_value=primary_id, note=note)
    return r


# ---------------------------------------------------------------------------
# read helpers for the UI
# ---------------------------------------------------------------------------


def timeline(reporting_id: str) -> list[dict]:
    """Full audit trail for one reporting, shaped for the detail drawer."""
    out = []
    for ev in db.audit_for_reporting(reporting_id):
        out.append({
            "id": ev.id,
            "at": ev.at.isoformat(),
            "actor": ev.actor,
            "is_human": ev.is_human,
            "action": ev.action.value,
            "field": ev.field,
            "from": ev.from_value,
            "to": ev.to_value,
            "note": ev.note,
            "shift_id": ev.shift_id,
            "detail": ev.detail,
        })
    return out


def last_human_touch(reporting_id: str) -> AuditEvent | None:
    for ev in reversed(db.audit_for_reporting(reporting_id)):
        if ev.is_human and ev.action != AuditAction.viewed:
            return ev
    return None
