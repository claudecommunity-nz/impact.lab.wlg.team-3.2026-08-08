"""Consolidate reportings that describe the same event.

Three people phoning about one slip is one incident with three sources, not
three rows in the queue. Consolidation does two jobs:

* it collapses the queue to one row per event, with the individual reportings
  underneath; and
* it carries a decision across sources — mark one member a false reporting and
  every future match arrives pre-flagged with that assessment attached.

**The consolidation test is location proximity + sentiment + category.** Two
reportings merge when they are physically close, written in the same register,
and about the same kind of hazard. Wording overlap is a supporting signal, not
the deciding one — people describe the same event in completely different words,
and different events on the same street in very similar ones.

Sentiment is what stops a distress call being merged with commentary from the
same corner. Category is what stops a fire and a flood at one intersection
becoming a single row.

No embeddings: an operator can be told in one sentence why two things were
grouped, the grouping is always visible, and it is always reversible.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .. import config, db
from ..models import Reporting, Sentiment, new_id, utcnow
from . import geocode

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "to", "of", "in", "on", "at", "by", "for", "with", "from", "as",
    "it", "its", "this", "that", "there", "here", "i", "we", "you", "they",
    "he", "she", "my", "our", "your", "their", "have", "has", "had", "do",
    "does", "did", "not", "no", "yes", "so", "if", "then", "than", "just",
    "about", "up", "down", "out", "over", "very", "can", "cant", "will",
    "would", "should", "could", "get", "got", "im", "hi", "hello",
    "please", "thanks", "thank", "like", "looks", "look", "seems", "some",
    "now", "still", "also", "one", "two", "all", "any", "more", "much",
}

_WORD = re.compile(r"[a-z0-9']+")

# Registers that count as "the same sentiment" for consolidation.
#
# The split that matters operationally is not how agitated someone sounds — it
# is whether they are reporting an incident, repeating a rumour, or making
# conversation. A caller describing a slip sounds urgent, the roading crew
# confirming the same slip sounds informational, and a bystander sounds
# concerned; all three are the same event and belong on one row. Keeping those
# apart split obvious duplicates across three rows, which is the problem this
# feature exists to solve.
#
# What must never merge into an incident is a rumour about it — "is it true
# there's a tsunami warning" is not a report of a tsunami — or commentary.
# Those stay in families of their own.
SENTIMENT_FAMILIES = [
    {Sentiment.distress, Sentiment.urgent,
     Sentiment.concerned, Sentiment.informational},   # someone reporting something
    {Sentiment.speculative},                          # rumour, hearsay, asking
    {Sentiment.supportive},                           # commentary
]


def tokens(text: str) -> set[str]:
    words = _WORD.findall((text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _sentiment_of(r: Reporting) -> Sentiment:
    return r.triage.sentiment if r.triage else Sentiment.informational


def _same_register(a: Sentiment, b: Sentiment) -> bool:
    if a == b:
        return True
    return any(a in family and b in family for family in SENTIMENT_FAMILIES)


def _same_category(a: Reporting, b: Reporting) -> bool:
    if not (a.triage and b.triage):
        return False
    if a.triage.category == "general" or b.triage.category == "general":
        return True          # uncategorised doesn't block a merge
    return a.triage.category == b.triage.category


def consolidates(new: Reporting, other: Reporting) -> tuple[bool, list[str]]:
    """Should these two be one row? Returns (verdict, human-readable reasons)."""
    reasons: list[str] = []
    cfg = config.get("settings", "dedupe", {}) or {}
    radius = float(cfg.get("distance_m", 250))

    # --- 1. same place -----------------------------------------------------
    distance = geocode.distance_m(new.location, other.location)
    if distance is not None:
        if distance > radius:
            return False, [f"{int(distance)} m apart — beyond the {int(radius)} m radius"]
        reasons.append(f"{int(distance)} m apart")
    else:
        # No coordinates on one or both. Fall back to the suburb, and only if
        # both actually name one.
        a = (new.location.suburb if new.location else None)
        b = (other.location.suburb if other.location else None)
        if a and b and a == b:
            reasons.append(f"both in {a}")
        elif not bool(cfg.get("allow_textonly_clustering", True)):
            return False, ["no location on one or both"]
        else:
            # Text-only: demand a strong wording match to stand in for place.
            overlap = jaccard(tokens(new.effective_text()),
                              tokens(other.effective_text()))
            if overlap < 0.5:
                return False, ["no shared location, and wording differs"]
            reasons.append(f"no location, but {int(overlap * 100)}% wording overlap")

    # --- 2. same register --------------------------------------------------
    sa, sb = _sentiment_of(new), _sentiment_of(other)
    if not _same_register(sa, sb):
        return False, [f"different register ({sa.value} vs {sb.value})"]
    reasons.append(f"both {sa.value}" if sa == sb
                   else f"{sa.value} / {sb.value} — same register")

    # --- 3. same kind of thing ---------------------------------------------
    if not _same_category(new, other):
        return False, [f"different category "
                       f"({new.triage.category} vs {other.triage.category})"]
    if new.triage and new.triage.category != "general":
        reasons.append(f"both {new.triage.category_label}")

    # --- supporting signal --------------------------------------------------
    overlap = jaccard(tokens(new.effective_text()), tokens(other.effective_text()))
    if overlap:
        reasons.append(f"{int(overlap * 100)}% wording overlap")

    return True, reasons


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
    """Attach `new` to an existing consolidated reporting, or open a new one.

    Runs *after* triage, because it needs `sentiment` and `category`.
    """
    empty = {"cluster_id": new.cluster_id, "matched": [], "size": 1,
             "flagged_false": False}

    if not config.get("settings", "dedupe.enabled", True):
        return empty

    best: Reporting | None = None
    best_reasons: list[str] = []
    matched: list[dict] = []

    for other in _recent_candidates(new):
        ok, reasons = consolidates(new, other)
        if not ok:
            continue
        matched.append({"id": other.id, "reasons": reasons,
                        "excerpt": (other.effective_text() or "")[:140]})
        # Prefer the earliest match — the consolidated row keeps the identity
        # of the first reporting that described the event.
        if best is None or (other.source.received_at < best.source.received_at):
            best, best_reasons = other, reasons

    if best is None:
        cluster_id = new.cluster_id or new_id("clu")
        db.ensure_cluster(cluster_id, (new.effective_text() or "")[:80],
                          utcnow().isoformat())
        new.cluster_id = cluster_id
        return {**empty, "cluster_id": cluster_id}

    cluster_id = best.cluster_id or new_id("clu")
    db.ensure_cluster(cluster_id, (best.effective_text() or "")[:80],
                      utcnow().isoformat())
    if not best.cluster_id:
        best.cluster_id = cluster_id
        db.save_reporting(best)
    new.cluster_id = cluster_id

    cluster = db.get_cluster(cluster_id) or {}
    return {
        "cluster_id": cluster_id,
        "matched": matched,
        "size": len(db.cluster_members(cluster_id)),
        "flagged_false": bool(cluster.get("flagged_false")),
        "flagged_by": cluster.get("flagged_by"),
        "flag_reason": cluster.get("flag_reason"),
        "best_match_id": best.id,
        "why": best_reasons,
    }


def cluster_summary(cluster_id: str | None, exclude: str | None = None) -> dict:
    """Everything the detail pane needs to explain a consolidation."""
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
