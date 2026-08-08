"""Triage orchestration: geocode → cluster → rules → (LLM) → merge.

The merge policy is the important bit. The machine's job is to order a queue,
not to close it. So:

* the ruleset is always evaluated and always shown;
* in hybrid mode the LLM's verdict is shown *beside* it, not instead of it;
* the LLM may escalate a priority, but may not lower one unless
  `engine.llm_may_downgrade` is turned on — a machine quietly demoting a
  reporting is the failure mode with the worst consequences;
* a human override beats everything and is never recomputed.
"""

from __future__ import annotations

from .. import audit as audit_mod
from .. import config, db
from ..models import (LIFE_RISK_RANK, PRIORITY_RANK, AuditAction, EngineMode,
                      Priority, Reporting, Signal, Status, utcnow)
from . import dedupe, geocode, llm, pool, rules


def mode() -> EngineMode:
    raw = config.get("settings", "engine.mode", "rules")
    try:
        return EngineMode(raw)
    except ValueError:
        return EngineMode.rules


def _context_for(r: Reporting) -> dict:
    cluster = db.get_cluster(r.cluster_id) or {}
    size = len(db.cluster_members(r.cluster_id)) if r.cluster_id else 1
    return {
        "cluster_size": max(1, size),
        "cluster_flagged_false": bool(cluster.get("flagged_false")),
        "cluster_flag_reason": cluster.get("flag_reason"),
    }


def triage(r: Reporting, *, use_llm: bool | None = None) -> Reporting:
    """Compute a triage result for `r` and write it onto the reporting.

    Does not save; the caller decides whether this is an ingest or a retriage
    so the right audit action is recorded.
    """
    ctx = _context_for(r)
    result = rules.evaluate(r, ctx)

    engine_mode = mode()
    wants_llm = use_llm if use_llm is not None else engine_mode in (
        EngineMode.llm, EngineMode.hybrid)

    if wants_llm:
        verdict = llm.classify(r, ctx)
        if verdict and not verdict.get("error"):
            result.llm_priority = verdict["priority"]
            result.llm_rationale = verdict["reason"]
            result.model = verdict.get("model")
            if verdict.get("summary"):
                r.content.summary = verdict["summary"]

            floor = float(config.get("settings", "engine.llm_min_confidence", 0.45))
            may_downgrade = bool(config.get("settings", "engine.llm_may_downgrade", False))
            trusted = verdict["confidence"] >= floor

            if engine_mode == EngineMode.llm:
                if trusted:
                    result.priority = verdict["priority"]
                    result.category = verdict["category"]
                    result.life_risk = verdict["life_risk"]
                    result.sentiment = verdict["sentiment"]
                    result.confidence = verdict["confidence"]
                    result.rationale = verdict["reason"] or result.rationale
                result.engine = EngineMode.llm
            else:  # hybrid
                result.engine = EngineMode.hybrid
                rule_priority = result.priority
                llm_priority = verdict["priority"]
                if rule_priority != llm_priority:
                    result.disagreement = (
                        f"Rules said {rule_priority.value}; model said "
                        f"{llm_priority.value} ({verdict['confidence']:.0%} confidence).")
                if trusted and PRIORITY_RANK[llm_priority] > PRIORITY_RANK[rule_priority]:
                    result.priority = llm_priority
                    result.signals.append(Signal(
                        rule_id="llm_escalation", label="Model escalated",
                        score=0.0, rationale=verdict["reason"]))
                elif trusted and PRIORITY_RANK[llm_priority] < PRIORITY_RANK[rule_priority]:
                    if may_downgrade:
                        result.priority = llm_priority
                        result.signals.append(Signal(
                            rule_id="llm_downgrade", label="Model de-escalated",
                            score=0.0, rationale=verdict["reason"]))
                    # otherwise: kept high, disagreement surfaced to the operator
                # Life risk is a consequence judgement, so take the *higher* of
                # the two. A machine may raise the stated consequence; it never
                # quietly lowers it.
                if LIFE_RISK_RANK[verdict["life_risk"]] > LIFE_RISK_RANK[result.life_risk]:
                    result.life_risk = verdict["life_risk"]
                # Sentiment is a reading of tone, which the model does better
                # than a keyword table — and it only affects consolidation.
                if verdict.get("sentiment"):
                    result.sentiment = verdict["sentiment"]
                if result.category == "general" and verdict["category"] != "general":
                    result.category = verdict["category"]
                    for cat in config.rules().get("categories", []):
                        if cat.get("id") == result.category:
                            result.category_label = cat.get("label", result.category)
                            break
        elif verdict:
            result.disagreement = f"Model unavailable: {verdict['error']}"

    # Guard rail that no ruleset can switch off: a cluster a human already
    # called false never comes back as action_required by machine alone.
    if ctx["cluster_flagged_false"] and result.priority == Priority.action_required:
        result.priority = Priority.verification_required
        result.signals.append(Signal(
            rule_id="false_cluster_guard",
            label="Held at verification — cluster previously marked false",
            score=0.0,
            rationale=ctx.get("cluster_flag_reason")))

    r.triage = result
    if not r.priority_overridden:
        r.priority = result.priority
    return r


# ---------------------------------------------------------------------------
# ingest pipeline
# ---------------------------------------------------------------------------


def ingest(r: Reporting, *, actor: str = "ingest", use_llm: bool | None = None) -> Reporting:
    """Full pipeline for one new reporting, with audit events written."""
    shift = audit_mod.current_shift()
    r.ingest_shift_id = shift.id if shift else None
    r.ingested_at = utcnow()
    r.updated_at = r.ingested_at

    # Keep the rules' sense of "now" alongside the reportings arriving. Live
    # this does nothing; replaying a past event it is what stops every
    # reporting being scored as months stale.
    rules.note_received(r.source.received_at)

    r.location = geocode.enrich(
        r.location, r.content.text, r.content.transcript, r.content.subject)

    # Consolidation keys off sentiment and category, but full triage wants to
    # know how big the group is — so run the cheap deterministic pass first to
    # get those two, consolidate, then triage properly with the group context.
    # The rules pass costs nothing and is thrown away a line later.
    r.triage = rules.evaluate(r, {})
    cluster_info = dedupe.assign_cluster(r)

    # Rules only on the way in, so the reporting is in the queue immediately.
    # The model runs behind it (see pool.py) and updates the record when its
    # verdict arrives, unless the caller explicitly asked to wait for it.
    deferred = use_llm is None and pool.enabled()
    triage(r, use_llm=False if deferred else use_llm)

    db.save_reporting(r)

    audit_mod.record(
        AuditAction.ingested, reporting_id=r.id, actor=actor, is_human=False,
        note=f"Received via {r.source.channel.value}"
             + (f" ({r.source.system})" if r.source.system else ""),
        detail={
            "channel": r.source.channel.value,
            "permalink": r.source.permalink,
            "external_id": r.source.external_id,
            "cluster_id": r.cluster_id,
            "cluster_matches": cluster_info.get("matched", [])[:5],
        })

    audit_mod.record(
        AuditAction.triaged, reporting_id=r.id, actor=f"engine:{r.triage.engine.value}",
        is_human=False, field="priority", to_value=r.priority,
        note=r.triage.rationale,
        detail={
            "score": r.triage.score,
            "category": r.triage.category,
            "confidence": r.triage.confidence,
            "ruleset_version": r.triage.ruleset_version,
            "signals": [s.model_dump() for s in r.triage.signals],
            "llm_priority": r.triage.llm_priority.value if r.triage.llm_priority else None,
            "disagreement": r.triage.disagreement,
        })

    if cluster_info.get("flagged_false"):
        audit_mod.record(
            AuditAction.cluster_flagged_false, reporting_id=r.id, actor="engine",
            is_human=False,
            note=("Matches a cluster a controller already assessed as false: "
                  f"{cluster_info.get('flag_reason') or 'no reason recorded'}"),
            detail={"cluster_id": r.cluster_id,
                    "flagged_by": cluster_info.get("flagged_by")})

    # Last, so a fast worker cannot write its assessment into the audit trail
    # ahead of this reporting's own ingest and triage events.
    if deferred:
        pool.submit(r.id)

    return r


def retriage_all(actor: str, *, use_llm: bool | None = None,
                 include_overridden: bool = False) -> dict:
    """Re-run triage across the queue, e.g. after the ruleset changed.

    Human overrides are preserved unless explicitly included, and every change
    of priority is audited so a re-run can never quietly move something.
    """
    changed, skipped, unchanged = 0, 0, 0
    for r in db.all_reportings():
        if r.priority_overridden and not include_overridden:
            skipped += 1
            continue
        if r.status == Status.false_reporting:
            skipped += 1
            continue
        before = r.priority
        if include_overridden:
            r.priority_overridden = False
        triage(r, use_llm=use_llm)
        r.updated_at = utcnow()
        db.save_reporting(r)
        if before != r.priority:
            changed += 1
            audit_mod.record(
                AuditAction.retriaged, reporting_id=r.id, actor=actor, is_human=False,
                field="priority", from_value=before, to_value=r.priority,
                note=f"Re-triaged: {r.triage.rationale}",
                detail={"ruleset_version": r.triage.ruleset_version,
                        "score": r.triage.score})
        else:
            unchanged += 1
    return {"changed": changed, "unchanged": unchanged, "skipped": skipped,
            "ruleset_version": config.rules().get("version")}
