"""HTTP API.

Everything the UI does is available here, so the prototype composes with the
other Impact Lab modules rather than trapping its data behind a screen:

    GET /api/v1/geojson    → straight into MapLibre or the shared COP
    POST /api/v1/ingest    → any team can push reportings in
"""

from __future__ import annotations

from json import JSONDecodeError
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi import UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import audit as audit_mod
from . import (config, consolidate, db, feeds, forward, handover, ingest,
               instructions, obligations)
from .models import (LIFE_RISK_LABEL, PRIORITY_LABEL, PRIORITY_RANK,
                     AuditAction, Priority, Reporting, Status, utcnow)
from .triage import dedupe, engine, geocode, llm, rules

router = APIRouter(prefix="/api/v1")


def actor_from(request: Request, supplied: str | None = None) -> str:
    """Who is doing this. Until there is real auth, the UI sends the operator
    name it was told at shift start; the audit trail records whatever arrives."""
    if supplied:
        return supplied
    header = request.headers.get("X-Operator")
    if header:
        return header
    shift = db.open_shift()
    if shift:
        return shift.operator
    return audit_mod.default_actor()


def _need(rid: str) -> Reporting:
    r = db.get_reporting(rid)
    if r is None:
        raise HTTPException(404, f"no reporting '{rid}'")
    return r


# ---------------------------------------------------------------------------
# health / meta
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    shift = db.open_shift()
    return {
        "ok": True,
        "reportings": len(db.all_reportings()),
        "engine_mode": engine.mode().value,
        "ruleset_version": config.rules().get("version"),
        "open_shift": {"id": shift.id, "operator": shift.operator} if shift else None,
        "disclaimer": ("Prototype built for Impact Lab Wellington. Not an "
                       "operational emergency system. In an emergency call 111."),
    }


@router.get("/llm/status")
def llm_status() -> dict:
    return llm.status()


@router.get("/adapters")
def adapters() -> list[dict]:
    return ingest.describe_adapters()


@router.get("/stats")
def stats() -> dict:
    reportings = db.all_reportings()
    unack = sum(1 for r in reportings
                if not r.acknowledged_by and r.status != Status.false_reporting)
    by_category: dict[str, int] = {}
    for r in reportings:
        key = r.triage.category_label if r.triage else "General"
        by_category[key] = by_category.get(key, 0) + 1
    return {
        "total": len(reportings),
        "by_priority": db.counts_by_priority(),
        "by_status": db.counts_by_status(),
        "by_category": by_category,
        "unacknowledged": unack,
        "forwards_awaiting_reply": len(db.forwards_awaiting_ack()),
        "mapped": sum(1 for r in reportings if r.location and r.location.has_coords),
    }


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@router.post("/ingest")
def ingest_endpoint(
    request: Request,
    body: Any = Body(...),
    adapter: Optional[str] = Query(None, description="id from config/sources.yaml"),
    use_llm: Optional[bool] = Query(None),
) -> dict:
    """Accept one reporting, a list, or a batch envelope."""
    adapter_cfg = config.adapter(adapter) if adapter else None
    if adapter and adapter_cfg is None:
        raise HTTPException(400, f"no adapter '{adapter}' in config/sources.yaml")

    payloads = ingest.unpack_batch(body, adapter_cfg)
    if not payloads:
        raise HTTPException(400, "no reportings found in request body")

    result = {"accepted": 0, "duplicates_rejected": 0, "ids": [], "errors": []}
    for payload in payloads:
        try:
            reporting = ingest.to_reporting(payload, adapter)
        except Exception as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            continue
        if db.exists_external(db.external_key(reporting)):
            result["duplicates_rejected"] += 1
            continue
        engine.ingest(reporting, actor=adapter or "api", use_llm=use_llm)
        result["accepted"] += 1
        result["ids"].append(reporting.id)
    return result


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------


def _card(r: Reporting) -> dict:
    t = r.triage
    cluster = db.get_cluster(r.cluster_id) or {}
    return {
        "id": r.id,
        "priority": r.priority.value,
        "priority_label": PRIORITY_LABEL[r.priority],
        "priority_overridden": r.priority_overridden,
        "override_reason": r.override_reason,
        "machine_priority": t.priority.value if t else None,
        "status": r.status.value,
        "score": t.score if t else 0,
        "category": t.category if t else "general",
        "category_label": t.category_label if t else "General",
        "life_risk": t.life_risk.value if t else "none",
        "life_risk_label": LIFE_RISK_LABEL[t.life_risk] if t else "None indicated",
        "sentiment": t.sentiment.value if t else "informational",
        "confidence": t.confidence if t else None,
        "rationale": t.rationale if t else "",
        "disagreement": t.disagreement if t else None,
        "engine": t.engine.value if t else None,
        "summary": r.content.summary,
        "excerpt": (r.effective_text() or "").strip()[:260],
        "channel": r.source.channel.value,
        "source_system": r.source.system,
        "permalink": r.source.permalink,
        "author": r.source.author_display_name or r.source.author_handle,
        "received_at": r.source.received_at.isoformat(),
        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        "ingested_at": r.ingested_at.isoformat(),
        "has_media": bool(r.content.media),
        "media_count": len(r.content.media),
        "location_text": r.location.text if r.location else None,
        "suburb": r.location.suburb if r.location else None,
        "has_coords": bool(r.location and r.location.has_coords),
        "location_precise": bool(r.location and r.location.is_precise),
        "location_method": r.location.method.value if r.location else None,
        "acknowledged_by": r.acknowledged_by,
        "assigned_to": r.assigned_to,
        "cluster_id": r.cluster_id,
        "cluster_size": len(db.cluster_members(r.cluster_id)) if r.cluster_id else 1,
        "cluster_flagged_false": bool(cluster.get("flagged_false")),
        "cluster_flag_reason": cluster.get("flag_reason"),
        "duplicate_of": r.duplicate_of,
        "forward_count": len(db.forwards_for(r.id)),
    }


@router.get("/reportings")
def list_reportings(
    priority: Optional[str] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    unacknowledged: bool = False,
    hide_false: bool = True,
    limit: int = 500,
) -> dict:
    """The queue, ordered the way an operator should work it."""
    rows = db.query_reportings(priority=priority, status=status, channel=channel,
                               category=category, search=q, limit=limit)
    if hide_false:
        rows = [r for r in rows if r.status != Status.false_reporting]
    if unacknowledged:
        rows = [r for r in rows if not r.acknowledged_by]

    def key(r: Reporting):
        return (
            -PRIORITY_RANK[r.priority],           # action first
            0 if not r.acknowledged_by else 1,    # unseen before seen
            -(r.triage.score if r.triage else 0),
            -(r.source.received_at.timestamp()),  # newest first
        )

    rows.sort(key=key)
    return {"count": len(rows), "reportings": [_card(r) for r in rows]}


@router.get("/reportings/{rid}")
def get_reporting(rid: str) -> dict:
    r = _need(rid)
    return {
        "reporting": r.model_dump(mode="json"),
        "card": _card(r),
        "triage": r.triage.model_dump(mode="json") if r.triage else None,
        "audit": audit_mod.timeline(rid),
        "cluster": dedupe.cluster_summary(r.cluster_id, exclude=rid),
        "forwards": [f.model_dump(mode="json") for f in db.forwards_for(rid)],
        "verification": feeds.verification_state(r),
    }


@router.get("/reportings/{rid}/audit")
def get_audit(rid: str) -> list[dict]:
    _need(rid)
    return audit_mod.timeline(rid)


@router.get("/reportings/{rid}/cluster")
def get_cluster(rid: str) -> dict:
    r = _need(rid)
    return dedupe.cluster_summary(r.cluster_id, exclude=rid)


# ---------------------------------------------------------------------------
# operator actions — every one of these writes an audit event
# ---------------------------------------------------------------------------


class ActorBody(BaseModel):
    actor: Optional[str] = None
    note: Optional[str] = None


class PriorityBody(ActorBody):
    priority: Priority
    reason: Optional[str] = None


class StatusBody(ActorBody):
    status: Status


class AssignBody(ActorBody):
    assignee: Optional[str] = None


class NoteBody(BaseModel):
    actor: Optional[str] = None
    note: str


class FalseBody(ActorBody):
    reason: Optional[str] = None
    propagate: bool = True


class DuplicateBody(ActorBody):
    primary_id: str


class ForwardBody(ActorBody):
    destination_id: str
    force_send: bool = False


@router.post("/reportings/{rid}/acknowledge")
def acknowledge(rid: str, request: Request, body: ActorBody = Body(default=ActorBody())):
    r = audit_mod.acknowledge(_need(rid), actor_from(request, body.actor), body.note)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/priority")
def set_priority(rid: str, request: Request, body: PriorityBody):
    r = audit_mod.acknowledge(_need(rid), actor_from(request, body.actor))
    r = audit_mod.set_priority(r, body.priority, actor_from(request, body.actor),
                               body.reason or body.note)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/status")
def set_status(rid: str, request: Request, body: StatusBody):
    actor = actor_from(request, body.actor)
    r = audit_mod.acknowledge(_need(rid), actor)
    if body.status == Status.false_reporting:
        audit_mod.mark_false(r, actor, body.note)
    else:
        r = audit_mod.set_status(r, body.status, actor, body.note)
    return {"ok": True, "card": _card(db.get_reporting(rid)),
            "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/note")
def add_note(rid: str, request: Request, body: NoteBody):
    actor = actor_from(request, body.actor)
    r = audit_mod.acknowledge(_need(rid), actor)
    audit_mod.add_note(r, body.note, actor)
    return {"ok": True, "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/assign")
def assign(rid: str, request: Request, body: AssignBody):
    actor = actor_from(request, body.actor)
    r = audit_mod.acknowledge(_need(rid), actor)
    r = audit_mod.assign(r, body.assignee, actor, body.note)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/false")
def mark_false(rid: str, request: Request, body: FalseBody = Body(default=FalseBody())):
    actor = actor_from(request, body.actor)
    r = audit_mod.acknowledge(_need(rid), actor)
    outcome = audit_mod.mark_false(r, actor, body.reason or body.note, body.propagate)
    return {"ok": True, "result": outcome, "card": _card(db.get_reporting(rid)),
            "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/unfalse")
def unmark_false(rid: str, request: Request, body: ActorBody = Body(default=ActorBody())):
    actor = actor_from(request, body.actor)
    r = audit_mod.unmark_false(_need(rid), actor, body.note)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/duplicate")
def link_duplicate(rid: str, request: Request, body: DuplicateBody):
    actor = actor_from(request, body.actor)
    r = audit_mod.link_duplicate(_need(rid), body.primary_id, actor, body.note)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/forward")
def forward_reporting(rid: str, request: Request, body: ForwardBody):
    actor = actor_from(request, body.actor)
    r = audit_mod.acknowledge(_need(rid), actor)
    try:
        record = forward.forward(r, body.destination_id, actor, body.note,
                                 body.force_send)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": record.ok, "forward": record.model_dump(mode="json"),
            "card": _card(db.get_reporting(rid)), "audit": audit_mod.timeline(rid)}


@router.post("/reportings/{rid}/retriage")
def retriage_one(rid: str, request: Request, body: ActorBody = Body(default=ActorBody()),
                 use_llm: Optional[bool] = Query(None)):
    actor = actor_from(request, body.actor)
    r = _need(rid)
    before = r.priority
    engine.triage(r, use_llm=use_llm)
    r.updated_at = utcnow()
    db.save_reporting(r)
    audit_mod.record(AuditAction.retriaged, reporting_id=rid, actor=actor,
                     is_human=True, field="priority", from_value=before,
                     to_value=r.priority, note=r.triage.rationale)
    return {"ok": True, "card": _card(r), "audit": audit_mod.timeline(rid)}


# ---------------------------------------------------------------------------
# forwarding meta
# ---------------------------------------------------------------------------


@router.get("/destinations")
def list_destinations() -> list[dict]:
    return config.destinations()


@router.post("/forwards/{fid}/ack")
def ack_forward(fid: str, request: Request, body: ActorBody = Body(default=ActorBody())):
    record = forward.acknowledge(fid, actor_from(request, body.actor), body.note)
    if record is None:
        raise HTTPException(404, f"no forward '{fid}'")
    return {"ok": True, "forward": record.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# map feed
# ---------------------------------------------------------------------------


@router.get("/geojson")
def geojson(priorities: Optional[str] = Query(
                None, description="comma-separated; defaults to settings.ui.map_priorities"),
            include_false: bool = False,
            all_priorities: bool = False) -> JSONResponse:
    if all_priorities:
        wanted = None
    elif priorities:
        wanted = [p.strip() for p in priorities.split(",") if p.strip()]
    else:
        wanted = config.get("settings", "ui.map_priorities",
                            ["action_required", "verification_required"])
    return JSONResponse(feeds.collection(db.all_reportings(), wanted, include_false))


# ---------------------------------------------------------------------------
# audit + shifts
# ---------------------------------------------------------------------------


@router.get("/audit")
def audit_feed(limit: int = 300, actor: Optional[str] = None,
               action: Optional[str] = None, humans_only: bool = False,
               shift_id: Optional[str] = None) -> dict:
    events = (db.audit_for_shift(shift_id) if shift_id
              else db.audit_recent(limit, actor, action, humans_only))
    if shift_id:
        events = list(reversed(events))
        if humans_only:
            events = [e for e in events if e.is_human]
    reportings = {r.id: r for r in db.all_reportings()}
    out = []
    for e in events:
        r = reportings.get(e.reporting_id) if e.reporting_id else None
        out.append({
            **e.model_dump(mode="json"),
            "excerpt": ((r.content.summary or r.effective_text() or "")[:110]
                        if r else None),
            "reporting_priority": r.priority.value if r else None,
        })
    return {"count": len(out), "events": out}


class ShiftBody(BaseModel):
    operator: str
    role: str = "Duty controller"
    note: Optional[str] = None


class EndShiftBody(BaseModel):
    actor: Optional[str] = None
    note: Optional[str] = None


@router.get("/shifts")
def list_shifts() -> dict:
    shifts = db.list_shifts()
    return {
        "open": next((s.model_dump(mode="json") for s in shifts if s.is_open), None),
        "shifts": [s.model_dump(mode="json") for s in shifts],
    }


@router.post("/shifts/start")
def start_shift(body: ShiftBody) -> dict:
    shift = audit_mod.start_shift(body.operator, body.role, body.note)
    return {"ok": True, "shift": shift.model_dump(mode="json")}


@router.post("/shifts/{shift_id}/end")
def end_shift(shift_id: str, request: Request,
              body: EndShiftBody = Body(default=EndShiftBody())):
    shift = audit_mod.end_shift(shift_id, actor_from(request, body.actor), body.note)
    if shift is None:
        raise HTTPException(404, f"no shift '{shift_id}'")
    return {"ok": True, "shift": shift.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# handover
# ---------------------------------------------------------------------------


def _shift_to_report(shift_id: Optional[str]):
    """The shift a briefing is about.

    Named explicitly, else the open one, else the most recent — a handover is
    usually written for the shift that has just ended, and by then there is no
    open shift to fall back to.
    """
    if shift_id:
        shift = db.get_shift(shift_id)
        if shift is None:
            raise HTTPException(404, f"no shift '{shift_id}'")
        return shift
    return db.open_shift() or next(iter(db.list_shifts(1)), None)


@router.get("/handover/preview")
def handover_preview(shift_id: Optional[str] = None, use_llm: bool = False) -> dict:
    briefing = handover.build(_shift_to_report(shift_id), use_llm=use_llm)
    return {"briefing": briefing, "markdown": handover.to_markdown(briefing)}


def _pdf_response(briefing: dict) -> Response:
    """Render a briefing to PDF, with the obligations still outstanding."""
    try:
        from . import shiftpdf
    except ImportError:
        raise HTTPException(
            503, "PDF export needs reportlab — pip install -r requirements.txt")
    body = shiftpdf.build(briefing, obligations.rows())
    return Response(
        content=body, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{shiftpdf.filename(briefing)}"'})


@router.get("/handover/pdf")
def handover_pdf(shift_id: Optional[str] = None, use_llm: bool = False) -> Response:
    """The shift report as a PDF: what to pick up, then what the shift did.

    Built from the same briefing the Handover tab shows — which is itself built
    from the audit trail — so the paper and the screen cannot disagree.
    """
    return _pdf_response(handover.build(_shift_to_report(shift_id), use_llm=use_llm))


class HandoverBody(BaseModel):
    actor: Optional[str] = None
    shift_id: Optional[str] = None
    use_llm: bool = False
    end_shift: bool = False
    note: Optional[str] = None


@router.post("/handover")
def make_handover(request: Request, body: HandoverBody = Body(default=HandoverBody())):
    actor = actor_from(request, body.actor)
    shift_id = body.shift_id
    if body.end_shift:
        current = db.get_shift(shift_id) if shift_id else db.open_shift()
        if current:
            shift_id = current.id
            audit_mod.end_shift(current.id, actor, body.note)
    result = handover.generate(shift_id, actor, use_llm=body.use_llm)
    return result


@router.get("/handover")
def list_handovers() -> list[dict]:
    return db.list_handovers()


@router.get("/handover/{hid}")
def get_handover(hid: str) -> dict:
    row = db.get_handover(hid)
    if row is None:
        raise HTTPException(404, f"no handover '{hid}'")
    return row


@router.get("/handover/{hid}/markdown", response_class=PlainTextResponse)
def get_handover_markdown(hid: str) -> str:
    row = db.get_handover(hid)
    if row is None:
        raise HTTPException(404, f"no handover '{hid}'")
    return row["markdown"]


@router.get("/handover/{hid}/pdf")
def get_handover_pdf(hid: str) -> Response:
    """A saved briefing as a PDF — the one that was filed, not a fresh build."""
    row = db.get_handover(hid)
    if row is None:
        raise HTTPException(404, f"no handover '{hid}'")
    return _pdf_response(row["doc"])


# ---------------------------------------------------------------------------
# config + ruleset
# ---------------------------------------------------------------------------


@router.get("/config")
def list_config() -> dict:
    return {"files": sorted(config.KNOWN.keys())}


@router.get("/config/{name}")
def get_config(name: str) -> dict:
    try:
        return {"name": name, "text": config.raw_text(name), "parsed": config.load(name)}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


class ConfigBody(BaseModel):
    text: str
    actor: Optional[str] = None


@router.put("/config/{name}")
def put_config(name: str, request: Request, body: ConfigBody):
    try:
        before = config.raw_text(name)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    try:
        config.save_text(name, body.text)
    except (yaml.YAMLError, ValueError) as exc:
        raise HTTPException(400, f"invalid YAML: {exc}")
    if name == "settings":
        geocode.reload()
    audit_mod.record(AuditAction.config_changed, actor=actor_from(request, body.actor),
                     field=name, note=f"{name}.yaml edited",
                     detail={"bytes_before": len(before), "bytes_after": len(body.text)})
    return {"ok": True, "name": name, "parsed": config.load(name)}


@router.get("/rules")
def get_rules() -> dict:
    return rules.summary()


# ---------------------------------------------------------------------------
# controller instructions (config/instructions.md)
# ---------------------------------------------------------------------------


@router.get("/instructions")
def get_instructions() -> dict:
    return instructions.info()


class InstructionsBody(BaseModel):
    text: str
    actor: Optional[str] = None


@router.put("/instructions")
def put_instructions(request: Request, body: InstructionsBody):
    """Replace the controller's triage instructions."""
    actor = actor_from(request, body.actor)
    before = instructions.info()
    try:
        after = instructions.write(body.text, actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit_mod.record(
        AuditAction.config_changed, actor=actor, field="instructions.md",
        note="Triage instructions updated.",
        detail={"chars_before": before.get("chars"), "chars_after": after.get("chars")})
    return {"ok": True, **after}


@router.post("/instructions/upload")
async def upload_instructions(request: Request, file: UploadFile = File(...),
                              actor: Optional[str] = None):
    """Upload an instructions Markdown file."""
    name = (file.filename or "").lower()
    if name and not name.endswith((".md", ".markdown", ".txt")):
        raise HTTPException(400, "expected a Markdown (.md) or text file")
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "file must be UTF-8 text")

    who = actor_from(request, actor)
    before = instructions.info()
    try:
        after = instructions.write(text, who)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit_mod.record(
        AuditAction.config_changed, actor=who, field="instructions.md",
        note=f"Triage instructions uploaded from {file.filename}.",
        detail={"filename": file.filename, "chars_before": before.get("chars"),
                "chars_after": after.get("chars")})
    return {"ok": True, "filename": file.filename, **after}


@router.delete("/instructions")
def delete_instructions(request: Request):
    actor = actor_from(request, None)
    instructions.clear()
    audit_mod.record(AuditAction.config_changed, actor=actor,
                     field="instructions.md", note="Triage instructions removed.")
    return {"ok": True, **instructions.info()}


# ---------------------------------------------------------------------------
# consolidated queue
# ---------------------------------------------------------------------------


def _consolidated_rows(priority: Optional[str], q: Optional[str],
                       include_done: bool, hide_false: bool,
                       unacknowledged: bool) -> list[dict]:
    rows = db.all_reportings()
    if hide_false:
        rows = [r for r in rows if r.status != Status.false_reporting]
    groups = consolidate.build(rows, include_done=include_done)
    if priority:
        groups = [g for g in groups if g["priority"] == priority]
    if unacknowledged:
        groups = [g for g in groups if not g["acknowledged"]]
    if q:
        needle = q.lower()
        groups = [g for g in groups
                  if needle in (g.get("description") or "").lower()
                  or needle in (g.get("location") or "").lower()
                  or needle in (g.get("category_label") or "").lower()
                  or any(needle in (m.get("description") or "").lower()
                         for m in g["members"])]
    return groups


@router.get("/consolidated")
def consolidated_queue(
    priority: Optional[str] = None,
    q: Optional[str] = None,
    include_done: bool = False,
    hide_false: bool = True,
    unacknowledged: bool = False,
    include_obligations: bool = True,
) -> dict:
    """The queue as an operator works it: one row per event.

    Each event row rolls its members up (highest priority, highest life risk,
    earliest received) and carries them in `members` for the expanded view.
    Administrative obligations from the uploaded timetable are interleaved by
    how close their deadline is — never above an action-required reporting.
    """
    groups = _consolidated_rows(priority, q, include_done, hide_false, unacknowledged)

    due: list[dict] = []
    if include_obligations and not priority and not unacknowledged:
        # A priority filter is about reportings; obligations have no priority,
        # so they drop out rather than being shoehorned into a band.
        due = obligations.rows(include_done=include_done)
        if q:
            needle = q.lower()
            due = [o for o in due
                   if needle in (o["label"] or "").lower()
                   or needle in (o["short_label"] or "").lower()
                   or needle in (o.get("owner_role") or "").lower()]

    rows = consolidate.merge_rows(groups, due)
    return {
        "count": len(groups),
        "reportings": sum(g["sources"] for g in groups),
        "obligations": len(due),
        "server_time": utcnow().isoformat(),
        "columns": [{"key": k, "header": h} for k, h in consolidate.CSV_COLUMNS],
        "groups": groups,
        "rows": rows,
        "obligation_summary": obligations.summary(),
    }


# ---------------------------------------------------------------------------
# administrative obligations (config/obligations.json)
# ---------------------------------------------------------------------------


@router.get("/obligations")
def list_obligations(include_done: bool = True) -> dict:
    return {**obligations.info(),
            "summary": obligations.summary(),
            "rows": obligations.rows(include_done=include_done)}


class ObligationsBody(BaseModel):
    text: str
    actor: Optional[str] = None


@router.put("/obligations")
def put_obligations(request: Request, body: ObligationsBody):
    actor = actor_from(request, body.actor)
    try:
        after = obligations.save(body.text)
    except (ValueError, JSONDecodeError) as exc:
        raise HTTPException(400, f"invalid timetable: {exc}")
    audit_mod.record(AuditAction.config_changed, actor=actor,
                     field="obligations.json",
                     note=f"Obligations timetable updated ({after['count']} entries).")
    return {"ok": True, **after}


@router.post("/obligations/upload")
async def upload_obligations(request: Request, file: UploadFile = File(...),
                             actor: Optional[str] = None):
    name = (file.filename or "").lower()
    if name and not name.endswith((".json", ".txt")):
        raise HTTPException(400, "expected a JSON file")
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "file must be UTF-8 text")
    who = actor_from(request, actor)
    try:
        after = obligations.save(text)
    except (ValueError, JSONDecodeError) as exc:
        raise HTTPException(400, f"invalid timetable: {exc}")
    audit_mod.record(AuditAction.config_changed, actor=who,
                     field="obligations.json",
                     note=f"Obligations timetable uploaded from {file.filename} "
                          f"({after['count']} entries).",
                     detail={"filename": file.filename})
    return {"ok": True, "filename": file.filename, **after}


@router.delete("/obligations")
def delete_obligations(request: Request):
    actor = actor_from(request, None)
    obligations.clear()
    audit_mod.record(AuditAction.config_changed, actor=actor,
                     field="obligations.json", note="Obligations timetable removed.")
    return {"ok": True, **obligations.info()}


class ObligationDoneBody(ActorBody):
    done: bool = True


@router.post("/obligations/{oid}/done")
def set_obligation_done(oid: str, request: Request,
                        body: ObligationDoneBody = Body(default=ObligationDoneBody())):
    """Discharge (or reopen) an obligation. Audited like any other decision."""
    known = {o["id"] for o in obligations.load()}
    if oid not in known:
        raise HTTPException(404, f"no obligation '{oid}' in the timetable")
    actor = actor_from(request, body.actor)
    db.set_obligation_done(oid, body.done, actor, body.note)
    audit_mod.record(
        AuditAction.status_changed, actor=actor, field="obligation",
        from_value=oid, to_value="done" if body.done else "outstanding",
        note=body.note or ("Obligation discharged." if body.done
                           else "Obligation reopened."),
        detail={"obligation_id": oid})
    row = next((o for o in obligations.rows(include_done=True) if o["id"] == oid), None)
    return {"ok": True, "obligation": row}


@router.get("/consolidated.csv")
def consolidated_csv(
    priority: Optional[str] = None,
    q: Optional[str] = None,
    include_done: bool = True,
    hide_false: bool = True,
    unacknowledged: bool = False,
    include_description: bool = False,
) -> Response:
    """The same rows as CSV, for handing to someone outside the tool."""
    groups = _consolidated_rows(priority, q, include_done, hide_false, unacknowledged)
    body = consolidate.to_csv(groups, include_description=include_description)
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="eoc-triage-{stamp}.csv"'})


def _cluster_members(cluster_id: str) -> list[Reporting]:
    members = db.cluster_members(cluster_id)
    if not members:
        # A single unconsolidated reporting is addressed by its own id.
        one = db.get_reporting(cluster_id)
        if one is None:
            raise HTTPException(404, f"no consolidated reporting '{cluster_id}'")
        members = [one]
    return members


@router.get("/consolidated/{cluster_id}")
def get_consolidated(cluster_id: str) -> dict:
    return consolidate.group(_cluster_members(cluster_id))


class GroupPriorityBody(ActorBody):
    priority: Priority
    reason: Optional[str] = None


@router.post("/consolidated/{cluster_id}/priority")
def set_group_priority(cluster_id: str, request: Request, body: GroupPriorityBody):
    """Override the priority for the whole event.

    Applied to every member so the row and its sources cannot disagree, and
    audited once per reporting — the override is a human decision about each of
    them, and the handover briefing reads it off the individual trails.
    """
    actor = actor_from(request, body.actor)
    reason = body.reason or body.note
    changed = []
    for m in _cluster_members(cluster_id):
        m = audit_mod.acknowledge(m, actor)
        before = m.priority
        audit_mod.set_priority(m, body.priority, actor, reason)
        if before != body.priority:
            changed.append(m.id)
    return {"ok": True, "changed": changed,
            "group": consolidate.group(_cluster_members(cluster_id))}


class GroupDoneBody(ActorBody):
    done: bool = True


@router.post("/consolidated/{cluster_id}/done")
def set_group_done(cluster_id: str, request: Request,
                   body: GroupDoneBody = Body(default=GroupDoneBody())):
    """Mark the event actioned (or reopen it)."""
    actor = actor_from(request, body.actor)
    target = Status.actioned if body.done else Status.in_review
    note = body.note or ("Marked done on the consolidated queue."
                         if body.done else "Reopened from the consolidated queue.")
    changed = []
    for m in _cluster_members(cluster_id):
        if body.done and m.status in consolidate.DONE_STATUSES:
            continue
        m = audit_mod.acknowledge(m, actor)
        audit_mod.set_status(m, target, actor, note)
        changed.append(m.id)
    return {"ok": True, "changed": changed,
            "group": consolidate.group(_cluster_members(cluster_id))}


@router.post("/consolidated/{cluster_id}/acknowledge")
def acknowledge_group(cluster_id: str, request: Request,
                      body: ActorBody = Body(default=ActorBody())):
    """Opening a consolidated row counts as opening everything under it."""
    actor = actor_from(request, body.actor)
    for m in _cluster_members(cluster_id):
        audit_mod.acknowledge(m, actor, body.note)
    return {"ok": True, "group": consolidate.group(_cluster_members(cluster_id))}


class RetriageBody(BaseModel):
    actor: Optional[str] = None
    use_llm: Optional[bool] = None
    include_overridden: bool = False


@router.post("/retriage")
def retriage(request: Request, body: RetriageBody = Body(default=RetriageBody())):
    return engine.retriage_all(actor_from(request, body.actor),
                               use_llm=body.use_llm,
                               include_overridden=body.include_overridden)


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------


class SeedBody(BaseModel):
    reset: bool = True
    use_llm: bool = False
    scenario: str = "storm"


@router.post("/demo/seed")
def seed(body: SeedBody = Body(default=SeedBody())):
    from .demo import seed_demo
    return seed_demo(reset=body.reset, use_llm=body.use_llm, scenario=body.scenario)
