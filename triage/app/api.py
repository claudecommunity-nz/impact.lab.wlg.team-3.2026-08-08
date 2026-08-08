"""HTTP API.

Everything the UI does is available here, so the prototype composes with the
other Impact Lab modules rather than trapping its data behind a screen:

    GET /api/v1/geojson    → straight into MapLibre or the shared COP
    POST /api/v1/ingest    → any team can push reportings in
"""

from __future__ import annotations

from typing import Any, Optional

import yaml
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from . import audit as audit_mod
from . import config, db, feeds, forward, handover, ingest
from .models import (PRIORITY_LABEL, PRIORITY_RANK, AuditAction, Priority,
                     Reporting, Status, utcnow)
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


@router.get("/handover/preview")
def handover_preview(shift_id: Optional[str] = None, use_llm: bool = False) -> dict:
    shift = db.get_shift(shift_id) if shift_id else db.open_shift()
    briefing = handover.build(shift, use_llm=use_llm)
    return {"briefing": briefing, "markdown": handover.to_markdown(briefing)}


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


class GenerateRulesBody(BaseModel):
    hazard_type: str
    response_timeline: str
    extra: Optional[str] = None
    actor: Optional[str] = None
    apply: bool = False
    retriage: bool = True


@router.post("/rules/generate")
def generate_rules(request: Request, body: GenerateRulesBody):
    """Draft a ruleset from the controller's declaration.

    With `apply=false` (the default) it returns YAML for review — the model
    proposes, a human disposes. With `apply=true` it writes the file and, unless
    told otherwise, re-triages the queue so the effect is immediately visible.
    """
    actor = actor_from(request, body.actor)
    try:
        ruleset = llm.generate_ruleset(body.hazard_type, body.response_timeline,
                                       body.extra)
    except Exception as exc:
        raise HTTPException(502, f"ruleset generation failed: {exc}")

    text = llm.ruleset_to_yaml(ruleset)
    result: dict[str, Any] = {"applied": False, "yaml": text, "ruleset": ruleset}

    if body.apply:
        config.save_text("triage_rules", text)
        audit_mod.record(
            AuditAction.ruleset_generated, actor=actor, field="triage_rules",
            to_value=f"v{ruleset['version']}",
            note=f"Ruleset generated for '{body.hazard_type}' "
                 f"(timeline: {body.response_timeline}) and applied.",
            detail={"hazard_type": body.hazard_type,
                    "response_timeline": body.response_timeline,
                    "rule_count": len(ruleset["rules"]),
                    "model": llm.model_name()})
        result["applied"] = True
        if body.retriage:
            result["retriage"] = engine.retriage_all(actor)
    else:
        audit_mod.record(
            AuditAction.ruleset_generated, actor=actor, field="triage_rules",
            note=f"Ruleset drafted for '{body.hazard_type}' — not applied.",
            detail={"hazard_type": body.hazard_type, "model": llm.model_name()})
    return result


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
