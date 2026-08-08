"""Deterministic rule engine.

Reads config/triage_rules.yaml and produces a priority plus the list of rules
that fired. Fully explainable: every point of the score is attributable to a
named rule, which is what the UI shows in the "why" panel.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .. import config
from ..models import (PRIORITY_RANK, Channel, EngineMode, LifeRisk, Priority,
                      Reporting, Sentiment, Signal, TriageResult, utcnow)


def _haystack(r: Reporting) -> str:
    """Text the keyword rules run against.

    Deliberately excludes the reporter's organisation: "Fire and Emergency NZ"
    in a sender field is not a reporting about a fire, and matching it there
    pushed routine agency sitreps to the top of the queue. Whether a source is
    official is expressed by the `reporter_is_official` condition instead.
    """
    parts = [r.effective_text() or ""]
    if r.location and r.location.text:
        parts.append(r.location.text)
    parts.extend(r.tags)
    return "\n".join(parts).lower()


_scenario_now: "datetime | None" = None


def scenario_now() -> "datetime":
    """The present moment, as the queue understands it.

    Live, that is the wall clock. Replaying a past event it is not: every
    reporting from 20 April 2026 is months old by the wall clock, so the
    `stale` rule fires on all of them and no freshness rule can ever fire.
    The whole queue lands in situational awareness and the triage looks
    broken when it is the clock that is wrong.

    During a replay the present moment is the newest reporting received. That
    advances by itself as the replay runs, so "20 minutes old" means twenty
    minutes of event time, which is what the rules were written to mean.
    """
    return utcnow() if _scenario_now is None else _scenario_now


def note_received(stamp: "datetime | None") -> None:
    """Advance the scenario clock, if this reporting is from further ahead.

    Only reportings dated well in the past move it. A live prototype never
    calls this with anything old enough to matter, so it stays on the wall
    clock unless something is genuinely being replayed.
    """
    global _scenario_now
    if stamp is None:
        return
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=utcnow().tzinfo)
    if stamp > utcnow() - timedelta(hours=12):
        return          # recent enough to be live; leave the wall clock alone
    if _scenario_now is None or stamp > _scenario_now:
        _scenario_now = stamp


def reset_scenario_clock() -> None:
    global _scenario_now
    _scenario_now = None


def _age_minutes(r: Reporting) -> float:
    stamp = r.source.received_at or r.ingested_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=utcnow().tzinfo)
    return max(0.0, (scenario_now() - stamp).total_seconds() / 60.0)


def matches(when: dict, r: Reporting, hay: str, ctx: dict) -> bool:
    """Evaluate one rule condition. All present keys must hold (AND)."""
    if not when:
        return False

    any_kw = when.get("any_keywords")
    if any_kw is not None and not any(str(k).lower() in hay for k in any_kw):
        return False

    all_kw = when.get("all_keywords")
    if all_kw is not None and not all(str(k).lower() in hay for k in all_kw):
        return False

    none_kw = when.get("none_keywords")
    if none_kw is not None and any(str(k).lower() in hay for k in none_kw):
        return False

    channels = when.get("channel")
    if channels is not None and r.source.channel.value not in channels:
        return False

    if "has_media" in when and bool(r.content.media) != bool(when["has_media"]):
        return False

    if "has_location" in when:
        has = bool(r.location and (r.location.has_coords or r.location.text))
        if has != bool(when["has_location"]):
            return False

    if "has_precise_location" in when:
        precise = bool(r.location and r.location.is_precise)
        if precise != bool(when["has_precise_location"]):
            return False

    if "reporter_is_official" in when:
        official = bool(r.reporter and r.reporter.is_official)
        if official != bool(when["reporter_is_official"]):
            return False

    if "credibility_at_least" in when:
        hint = r.source.credibility_hint
        if hint is None or hint < float(when["credibility_at_least"]):
            return False

    if "cluster_size_min" in when and ctx.get("cluster_size", 1) < int(when["cluster_size_min"]):
        return False

    if "cluster_flagged_false" in when:
        if bool(ctx.get("cluster_flagged_false")) != bool(when["cluster_flagged_false"]):
            return False

    if "within_minutes" in when and _age_minutes(r) > float(when["within_minutes"]):
        return False

    if "older_than_minutes" in when and _age_minutes(r) < float(when["older_than_minutes"]):
        return False

    return True


def categorise(r: Reporting, hay: str, ruleset: dict) -> tuple[str, str]:
    for cat in ruleset.get("categories", []):
        for needle in cat.get("match", []) or []:
            if str(needle).lower() in hay:
                return cat.get("id", "general"), cat.get("label", "General")
    return "general", "General"


def assess_life_risk(hay: str, ruleset: dict) -> LifeRisk:
    """Could someone die? Answered from the words, highest band wins.

    Deliberately independent of priority: a confirmed road closure is urgent
    with no life risk, and a vague third-hand report of someone in the water is
    only worth verifying while still carrying the worst possible consequence.
    """
    bands = ruleset.get("life_risk", {}) or {}
    for level in ("confirmed", "likely", "possible"):
        for needle in bands.get(level, []) or []:
            if str(needle).lower() in hay:
                return LifeRisk(level)
    return LifeRisk.none


def assess_sentiment(r: Reporting, hay: str, ruleset: dict) -> Sentiment:
    """The register the reporting is written in.

    Used with location proximity to decide what consolidates with what, so it
    has to separate "help me" from "is it true that…" even when both mention
    the same street.
    """
    bands = ruleset.get("sentiment", {}) or {}
    order = ("distress", "speculative", "supportive", "urgent",
             "concerned", "informational")
    for level in order:
        for needle in bands.get(level, []) or []:
            if str(needle).lower() in hay:
                return Sentiment(level)

    # Fall back on the channel: an official filing a situation report and a
    # member of the public phoning in are not the same register.
    if r.source.channel in (Channel.partner_agency, Channel.news, Channel.sensor):
        return Sentiment.informational
    if r.source.channel == Channel.phone_call:
        return Sentiment.concerned
    return Sentiment.informational


def _priority_for(score: float, thresholds: dict) -> Priority:
    if score >= float(thresholds.get("action_required", 62)):
        return Priority.action_required
    if score >= float(thresholds.get("verification_required", 30)):
        return Priority.verification_required
    return Priority.situational_awareness


def evaluate(r: Reporting, ctx: dict | None = None,
             ruleset: dict | None = None) -> TriageResult:
    """Score one reporting. Pass `ruleset` to try a candidate without saving it."""
    ruleset = ruleset if ruleset is not None else config.rules()
    ctx = ctx or {}
    hay = _haystack(r)

    defaults = ruleset.get("defaults", {}) or {}
    score = float(defaults.get("base_score", 10))
    signals: list[Signal] = []
    forced: Priority | None = None
    capped: Priority | None = None

    for rule in ruleset.get("rules", []) or []:
        if not matches(rule.get("when", {}) or {}, r, hay, ctx):
            continue
        points = float(rule.get("score", 0))
        score += points
        signals.append(Signal(
            rule_id=rule.get("id", "?"),
            label=rule.get("label", rule.get("id", "?")),
            score=points,
            rationale=rule.get("rationale"),
        ))
        if rule.get("force_priority"):
            candidate = Priority(rule["force_priority"])
            if forced is None or PRIORITY_RANK[candidate] > PRIORITY_RANK[forced]:
                forced = candidate
        if rule.get("cap_priority"):
            candidate = Priority(rule["cap_priority"])
            if capped is None or PRIORITY_RANK[candidate] < PRIORITY_RANK[capped]:
                capped = candidate

    thresholds = ruleset.get("thresholds", {}) or {}
    priority = _priority_for(score, thresholds)

    # A cap holds the priority back unless a rule explicitly forced it higher —
    # "trapped in a car" beats "it came from social media".
    if capped is not None and PRIORITY_RANK[priority] > PRIORITY_RANK[capped]:
        priority = capped
    if forced is not None and PRIORITY_RANK[forced] > PRIORITY_RANK[priority]:
        priority = forced

    category, category_label = categorise(r, hay, ruleset)
    life_risk = assess_life_risk(hay, ruleset)
    sentiment = assess_sentiment(r, hay, ruleset)

    top = sorted(signals, key=lambda s: abs(s.score), reverse=True)[:3]
    if top:
        rationale = "; ".join(s.label for s in top)
    else:
        rationale = "No rules matched — defaulted to situational awareness."

    # Confidence reflects how much evidence the rules actually had, not how
    # certain we are the reporting is true.
    evidence = len([s for s in signals if s.score])
    confidence = min(0.95, 0.35 + 0.09 * evidence)

    return TriageResult(
        priority=priority,
        score=round(score, 1),
        category=category,
        category_label=category_label,
        life_risk=life_risk,
        sentiment=sentiment,
        confidence=round(confidence, 2),
        rationale=rationale,
        signals=signals,
        engine=EngineMode.rules,
        ruleset_version=ruleset.get("version"),
    )


def summary() -> dict:
    """Shape the Settings tab renders."""
    ruleset = config.rules()
    return {
        "version": ruleset.get("version"),
        "name": ruleset.get("name"),
        "generated_by": ruleset.get("generated_by"),
        "notes": ruleset.get("notes"),
        "event": ruleset.get("event", {}),
        "thresholds": ruleset.get("thresholds", {}),
        "rule_count": len(ruleset.get("rules", []) or []),
        "categories": [
            {"id": c.get("id"), "label": c.get("label")}
            for c in ruleset.get("categories", []) or []
        ],
        "rules": [
            {"id": r.get("id"), "label": r.get("label"), "score": r.get("score"),
             "force_priority": r.get("force_priority"),
             "cap_priority": r.get("cap_priority"),
             "rationale": r.get("rationale")}
            for r in ruleset.get("rules", []) or []
        ],
    }
