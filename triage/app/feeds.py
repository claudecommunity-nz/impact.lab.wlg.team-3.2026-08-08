"""Outbound representations: GeoJSON for the shared common operating picture.

The map tab and the COP feed both read from here, so what the other teams
consume is exactly what our operators see. Every feature carries its provenance
and its verification state — a consumer must be able to tell an unverified
public post from a confirmed partner-agency update without asking us.
"""

from __future__ import annotations

from .models import (PRIORITY_LABEL, Priority, Reporting, Status)

VERIFIED_STATUSES = {Status.verified, Status.actioned}


def verification_state(r: Reporting) -> str:
    if r.status == Status.false_reporting:
        return "assessed_false"
    if r.status in VERIFIED_STATUSES:
        return "verified_by_operator"
    if r.priority == Priority.verification_required:
        return "unverified_needs_checking"
    return "unverified"


def feature(r: Reporting) -> dict | None:
    if not (r.location and r.location.has_coords):
        return None
    t = r.triage
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r.location.lon, r.location.lat]},
        "properties": {
            "id": r.id,
            "priority": r.priority.value,
            "priority_label": PRIORITY_LABEL[r.priority],
            "status": r.status.value,
            "verification": verification_state(r),
            "category": t.category if t else "general",
            "category_label": t.category_label if t else "General",
            "summary": (r.content.summary or r.effective_text() or "")[:220],
            "channel": r.source.channel.value,
            "source_system": r.source.system,
            "permalink": r.source.permalink,
            "received_at": r.source.received_at.isoformat(),
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            # Honesty about the pin itself: a gazetteer hit is a guess.
            "location_method": r.location.method.value,
            "location_precise": r.location.is_precise,
            "location_confidence": r.location.confidence,
            "location_text": r.location.text,
            "suburb": r.location.suburb,
            "cluster_id": r.cluster_id,
            "score": t.score if t else None,
            "triage_engine": t.engine.value if t else None,
            "priority_overridden": r.priority_overridden,
            "acknowledged_by": r.acknowledged_by,
            "assigned_to": r.assigned_to,
            "disagreement": t.disagreement if t else None,
        },
    }


def collection(reportings: list[Reporting], priorities: list[str] | None = None,
               include_false: bool = False) -> dict:
    feats = []
    for r in reportings:
        if priorities and r.priority.value not in priorities:
            continue
        if not include_false and r.status == Status.false_reporting:
            continue
        f = feature(r)
        if f:
            feats.append(f)
    return {
        "type": "FeatureCollection",
        "features": feats,
        "properties": {
            "source": "Impact Lab Wellington Team 3 — reporting triage prototype",
            "disclaimer": (
                "Prototype output built on hazard-planning data and simulated "
                "reportings. Not an operational emergency source. In an "
                "emergency call 111."),
            "filtered_priorities": priorities,
            "count": len(feats),
        },
    }
