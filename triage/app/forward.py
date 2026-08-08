"""Forward a reporting to a partner agency by email or HTTP.

Destinations live in config/destinations.yaml so an operator can add one
without a deploy. `forwarding.dry_run` (default on) composes and records the
message without sending it — safe for a demo, and the recorded payload is
exactly what would have gone out.

Every forward, sent or not, becomes an audit event. Forwards that have not been
acknowledged by the receiving agency are a headline item in the shift handover:
"we asked FENZ about this 40 minutes ago and have heard nothing back" is
precisely the thing that gets lost at a shift change.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from . import audit as audit_mod
from . import config, db, feeds
from .models import (PRIORITY_LABEL, AuditAction, Forward, Reporting, Status,
                     utcnow)


def destinations() -> list[dict]:
    return [d for d in config.destinations() if d.get("enabled", True)]


# ---------------------------------------------------------------------------
# message construction
# ---------------------------------------------------------------------------


def _verification_banner(r: Reporting) -> str:
    state = feeds.verification_state(r)
    return {
        "verified_by_operator": "STATUS: Checked and confirmed by a WCC EOC operator.",
        "unverified_needs_checking": (
            "STATUS: UNVERIFIED — flagged for verification. Treat as a lead to "
            "check, not as confirmed fact."),
        "assessed_false": (
            "STATUS: ASSESSED AS A FALSE REPORTING by a WCC EOC controller."),
        "unverified": (
            "STATUS: UNVERIFIED. Treat as a lead to check, not as confirmed fact."),
    }[state]


def compose_email(r: Reporting, dest: dict, note: str | None, actor: str) -> dict:
    where = "Location not stated"
    if r.location:
        bits = [r.location.text or ""]
        if r.location.has_coords:
            precision = "confirmed" if r.location.is_precise else "INFERRED from text"
            bits.append(f"{r.location.lat:.5f}, {r.location.lon:.5f} ({precision})")
        where = " — ".join(b for b in bits if b) or where

    lines = [
        f"Forwarded from Wellington EOC reporting triage by {actor}.",
        "",
        _verification_banner(r),
        "",
        f"Priority:   {PRIORITY_LABEL[r.priority]}"
        + ("  (set by an operator, overriding the automated assessment)"
           if r.priority_overridden else "  (automated assessment)"),
        f"Category:   {r.triage.category_label if r.triage else 'General'}",
        f"Received:   {r.source.received_at.isoformat()}",
        f"Channel:    {r.source.channel.value}"
        + (f" via {r.source.system}" if r.source.system else ""),
        f"Location:   {where}",
        f"Our ref:    {r.id}",
    ]
    if r.cluster_id:
        size = len(db.cluster_members(r.cluster_id))
        lines.append(f"Related:    {size} similar reporting(s), group {r.cluster_id}")
    if r.source.permalink:
        lines.append(f"Original:   {r.source.permalink}")

    lines += ["", "--- WHAT WAS REPORTED (verbatim) ---"]
    if r.content.subject:
        lines.append(f"Subject: {r.content.subject}")
    if r.content.transcript:
        lines += ["Call transcript:", r.content.transcript]
    if r.content.text:
        lines.append(r.content.text)
    for m in r.content.media:
        label = f"Attached {m.kind.value}: {m.url or '(no url)'}"
        if m.caption:
            label += f" — {m.caption}"
        if m.model_caption:
            label += f" — AI-generated caption: {m.model_caption}"
        lines.append(label)

    if r.reporter and (r.reporter.name or r.reporter.phone):
        lines += ["", "--- REPORTER ---",
                  f"{r.reporter.name or 'not given'} "
                  f"{r.reporter.phone or ''} {r.reporter.email or ''}".strip()]

    if r.triage:
        lines += ["", "--- HOW THIS WAS TRIAGED ---", r.triage.rationale]
        for s in r.triage.signals:
            lines.append(f"  · {s.label} ({s.score:+g})")
        if r.triage.disagreement:
            lines.append(f"  ! {r.triage.disagreement}")

    trail = db.audit_for_reporting(r.id)
    human = [e for e in trail if e.is_human]
    if human:
        lines += ["", "--- OPERATOR ACTIONS ---"]
        for e in human:
            piece = f"  {e.at.isoformat()}  {e.actor}  {e.action.value}"
            if e.from_value or e.to_value:
                piece += f"  {e.from_value or '—'} → {e.to_value or '—'}"
            if e.note:
                piece += f"  “{e.note}”"
            lines.append(piece)

    if note:
        lines += ["", "--- NOTE FROM THE FORWARDING OPERATOR ---", note]
    if dest.get("default_note"):
        lines += ["", dest["default_note"].strip()]

    lines += ["", "-" * 68,
              "Impact Lab Wellington prototype. Not an operational emergency "
              "system. In an emergency, call 111."]

    subject = (f"[{PRIORITY_LABEL[r.priority]}] "
               f"{(r.content.summary or r.content.subject or r.effective_text() or 'Reporting')[:70]}"
               f" — ref {r.id}")
    return {"subject": subject, "body": "\n".join(lines)}


def compose_api_payload(r: Reporting, dest: dict, note: str | None,
                        actor: str) -> dict:
    return {
        "forwarded_at": utcnow().isoformat(),
        "forwarded_by": actor,
        "note": note,
        "verification": feeds.verification_state(r),
        "disclaimer": ("Prototype output. Unverified unless the verification "
                       "field says otherwise. Not an operational source."),
        "reporting": r.model_dump(mode="json"),
        "feature": feeds.feature(r),
        "audit_trail": [e.model_dump(mode="json") for e in db.audit_for_reporting(r.id)],
    }


# ---------------------------------------------------------------------------
# transports
# ---------------------------------------------------------------------------


def _send_email(dest: dict, subject: str, body: str) -> tuple[bool, str]:
    smtp = config.get("settings", "forwarding.smtp", {}) or {}
    msg = EmailMessage()
    msg["From"] = smtp.get("from_address", "eoc-triage@wcc.example.nz")
    msg["To"] = dest["address"]
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp.get("host", "localhost"),
                          int(smtp.get("port", 25)), timeout=15) as server:
            if smtp.get("use_tls"):
                server.starttls()
            if smtp.get("username"):
                server.login(smtp["username"], smtp.get("password") or "")
            server.send_message(msg)
        return True, f"delivered to {dest['address']}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _send_api(dest: dict, payload: dict) -> tuple[bool, str]:
    try:
        resp = httpx.request(
            dest.get("method", "POST").upper(), dest["url"], json=payload,
            headers=dest.get("headers") or {}, timeout=20.0)
        ok = resp.status_code < 400
        return ok, f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def forward(r: Reporting, destination_id: str, actor: str,
            note: str | None = None, force_send: bool = False) -> Forward:
    dest = config.destination(destination_id)
    if dest is None:
        raise ValueError(f"no destination '{destination_id}' in config/destinations.yaml")
    if not dest.get("enabled", True) and not force_send:
        raise ValueError(f"destination '{destination_id}' is disabled")

    dry_run = bool(config.get("settings", "forwarding.dry_run", True)) and not force_send
    transport = dest.get("type", "email")
    shift = audit_mod.current_shift()

    if transport == "email":
        message = compose_email(r, dest, note, actor)
        target = dest.get("address", "")
        payload: dict[str, Any] = message
    elif transport == "api":
        payload = compose_api_payload(r, dest, note, actor)
        target = dest.get("url", "")
    else:
        raise ValueError(f"unsupported destination type '{transport}'")

    if dry_run:
        ok, response = True, "DRY RUN — composed and recorded, not transmitted"
    elif transport == "email":
        ok, response = _send_email(dest, payload["subject"], payload["body"])
    else:
        ok, response = _send_api(dest, payload)

    record = Forward(
        reporting_id=r.id, destination_id=destination_id,
        destination_name=dest.get("name", destination_id), transport=transport,
        target=target, note=note, sent_by=actor,
        shift_id=shift.id if shift else None, dry_run=dry_run, ok=ok,
        response=response, payload=payload,
    )
    db.save_forward(record)

    audit_mod.record(
        AuditAction.forwarded if ok else AuditAction.forward_failed,
        reporting_id=r.id, actor=actor, field="forwarded_to",
        to_value=f"{dest.get('name', destination_id)} <{target}>",
        note=note,
        detail={"forward_id": record.id, "destination_id": destination_id,
                "transport": transport, "dry_run": dry_run, "ok": ok,
                "response": response,
                "subject": payload.get("subject") if transport == "email" else None})

    if ok and r.status in (Status.new, Status.acknowledged, Status.in_review):
        audit_mod.set_status(r, Status.forwarded, actor,
                             note=f"Forwarded to {dest.get('name', destination_id)}")

    return record


def acknowledge(forward_id: str, actor: str, note: str | None = None) -> Forward | None:
    """Record that the receiving agency came back to us."""
    record = db.get_forward(forward_id)
    if record is None:
        return None
    record.acknowledged_at = utcnow()
    db.save_forward(record)
    audit_mod.record(
        AuditAction.note_added, reporting_id=record.reporting_id, actor=actor,
        note=note or f"{record.destination_name} acknowledged the forward.",
        detail={"forward_id": forward_id, "acknowledged": True})
    return record
