"""Group reportings that describe the same real-world thing.

Three people phoning about one slip is one incident with three sources, not
three incidents. Clustering does two jobs here:

* it stops the queue filling with the same event, and
* it carries a decision across sources — mark one member a false reporting and
  every future match arrives pre-flagged with that assessment attached.

Similarity is token overlap (Jaccard) with a location and time gate. No
embeddings: it is inspectable, has no dependencies, and an operator can be told
in one sentence why two things were grouped. The grouping is always visible and
always reversible from the UI.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .. import config, db
from ..models import Reporting, new_id, utcnow
from . import geocode

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "to", "of", "in", "on", "at", "by", "for", "with", "from", "as",
    "it", "its", "this", "that", "there", "here", "i", "we", "you", "they",
    "he", "she", "my", "our", "your", "their", "have", "has", "had", "do",
    "does", "did", "not", "no", "yes", "so", "if", "then", "than", "just",
    "about", "up", "down", "out", "over", "very", "can", "cant", "will",
    "would", "should", "could", "get", "got", "im", "its", "hi", "hello",
    "please", "thanks", "thank", "like", "looks", "look", "seems", "some",
    "now", "still", "also", "one", "two", "all", "any", "more", "much",
}

_WORD = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> set[str]:
    words = _WORD.findall((text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(new: Reporting, other: Reporting) -> tuple[float, list[str]]:
    """Returns (score 0..1, human-readable reasons)."""
    reasons: list[str] = []
    text_score = jaccard(tokens(new.effective_text()), tokens(other.effective_text()))
    score = text_score
    if text_score > 0:
        reasons.append(f"{int(text_score * 100)}% wording overlap")

    same_category = (new.triage and other.triage
                     and new.triage.category == other.triage.category
                     and new.triage.category != "general")
    if same_category:
        score += 0.10
        reasons.append(f"both categorised {new.triage.category_label}")

    distance = geocode.distance_m(new.location, other.location)
    radius = float(config.get("settings", "dedupe.distance_m", 700))
    if distance is not None:
        if distance <= radius:
            score += 0.18
            reasons.append(f"{int(distance)} m apart")
        else:
            # Same words, different side of the city: almost certainly separate.
            score -= 0.30
            reasons.append(f"{int(distance / 100) / 10} km apart")
    elif (new.location and other.location and new.location.suburb
          and new.location.suburb == other.location.suburb):
        score += 0.12
        reasons.append(f"both in {new.location.suburb}")

    return max(0.0, min(1.0, score)), reasons


def _recent_candidates(new: Reporting) -> list[Reporting]:
    window = int(config.get("settings", "dedupe.time_window_minutes", 240))
    cutoff = utcnow() - timedelta(minutes=window)
    out = []
    for r in db.all_reportings():
        if r.id == new.id:
            continue
        stamp = r.source.received_at or r.ingested_at
        if stamp and stamp < cutoff:
            continue
        out.append(r)
    return out


def assign_cluster(new: Reporting) -> dict:
    """Attach `new` to an existing cluster or open a fresh one.

    Returns a summary the UI shows in the reporting detail pane, so the operator
    can see what it was grouped with and undo it.
    """
    empty = {"cluster_id": new.cluster_id, "matched": [], "size": 1,
             "flagged_false": False, "best_score": 0.0}

    if not config.get("settings", "dedupe.enabled", True):
        return empty

    threshold = float(config.get("settings", "dedupe.similarity_threshold", 0.34))
    allow_textonly = bool(config.get("settings", "dedupe.allow_textonly_clustering", True))

    best: tuple[float, Reporting, list[str]] | None = None
    matched: list[dict] = []

    for other in _recent_candidates(new):
        score, reasons = similarity(new, other)
        if score < threshold:
            continue
        located = (new.location and new.location.has_coords)
        if not located and not allow_textonly:
            continue
        matched.append({"id": other.id, "score": round(score, 3),
                        "reasons": reasons,
                        "excerpt": (other.effective_text() or "")[:140]})
        if best is None or score > best[0]:
            best = (score, other, reasons)

    if best is None:
        cluster_id = new.cluster_id or new_id("clu")
        db.ensure_cluster(cluster_id, (new.effective_text() or "")[:80],
                          utcnow().isoformat())
        new.cluster_id = cluster_id
        return {**empty, "cluster_id": cluster_id}

    score, other, reasons = best
    cluster_id = other.cluster_id or new_id("clu")
    db.ensure_cluster(cluster_id, (other.effective_text() or "")[:80],
                      utcnow().isoformat())
    if not other.cluster_id:
        other.cluster_id = cluster_id
        db.save_reporting(other)
    new.cluster_id = cluster_id

    cluster = db.get_cluster(cluster_id) or {}
    matched.sort(key=lambda m: m["score"], reverse=True)
    return {
        "cluster_id": cluster_id,
        "matched": matched,
        "size": len(db.cluster_members(cluster_id)),
        "flagged_false": bool(cluster.get("flagged_false")),
        "flagged_by": cluster.get("flagged_by"),
        "flag_reason": cluster.get("flag_reason"),
        "best_score": round(score, 3),
        "best_match_id": other.id,
        "why": reasons,
    }


def cluster_summary(cluster_id: str | None, exclude: str | None = None) -> dict:
    """Everything the detail pane needs to explain a grouping."""
    if not cluster_id:
        return {"cluster_id": None, "size": 0, "members": [], "flagged_false": False}
    cluster = db.get_cluster(cluster_id) or {}
    members = db.cluster_members(cluster_id)
    return {
        "cluster_id": cluster_id,
        "size": len(members),
        "flagged_false": bool(cluster.get("flagged_false")),
        "flagged_by": cluster.get("flagged_by"),
        "flagged_at": cluster.get("flagged_at"),
        "flag_reason": cluster.get("flag_reason"),
        "members": [
            {
                "id": m.id,
                "channel": m.source.channel.value,
                "system": m.source.system,
                "permalink": m.source.permalink,
                "received_at": m.source.received_at.isoformat(),
                "status": m.status.value,
                "priority": m.priority.value,
                "excerpt": (m.effective_text() or "")[:160],
            }
            for m in members if m.id != exclude
        ],
    }
