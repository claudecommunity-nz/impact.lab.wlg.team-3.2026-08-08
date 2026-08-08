"""LLM assistance — provider-agnostic.

Three jobs, all optional. If the provider is unreachable the application still
works on rules alone, which is the behaviour you want in an EOC anyway.

1. `classify`        — a second opinion on one reporting, steered by the
                       controller's own `config/instructions.md`.
2. `summarise_shift` — prose for the top of a handover briefing.

The model is never the sole authority. In hybrid mode it may escalate a
priority but not lower one (see settings.engine.llm_may_downgrade).

Switch backends with `llm.provider` in settings.yaml — `anthropic` (default,
Claude API) or `ollama` (local, no network egress). The JSON schemas below are
enforced by the API on the Claude provider and described in the prompt on
Ollama, so the same prompts and result handling serve both.
"""

from __future__ import annotations

import json
from typing import Any

from .. import config, instructions
from ..models import LifeRisk, Priority, Reporting, Sentiment
from .providers import get as get_provider
from .providers.claude import Refusal

PRIORITY_VALUES = [p.value for p in Priority]
LIFE_RISK_VALUES = [v.value for v in LifeRisk]
SENTIMENT_VALUES = [v.value for v in Sentiment]


def _cfg() -> dict:
    return config.get("settings", "llm", {}) or {}


def provider_name() -> str:
    return str(_cfg().get("provider", "anthropic"))


def provider():
    return get_provider(provider_name())


def model_name() -> str:
    """The model for the *active* provider.

    Each provider reads its own key so switching `llm.provider` doesn't send a
    Claude model id to Ollama, or the reverse.
    """
    cfg = _cfg()
    if provider_name() in ("anthropic", "claude"):
        return str(cfg.get("model") or "claude-opus-5")
    return str(cfg.get("ollama_model") or "qwen3.5:4b")


def _call_cfg() -> dict:
    """Provider config with the effective model resolved."""
    return {**_cfg(), "model": model_name()}


def status() -> dict:
    """Used by the Settings tab to show a green/red dot."""
    try:
        return provider().status(_call_cfg())
    except Exception as exc:
        return {"available": False, "provider": provider_name(),
                "model": model_name(), "error": f"{type(exc).__name__}: {exc}"}


def available() -> bool:
    return bool(status().get("available"))


# ---------------------------------------------------------------------------
# schema helpers
# ---------------------------------------------------------------------------
#
# Structured outputs require `additionalProperties: false` and every property
# listed in `required`. Genuinely optional fields are therefore expressed as
# "this type OR null" and the nulls stripped afterwards — they are an artefact
# of the encoding, not data.


def _opt(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _strip_nulls(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_nulls(v) for k, v in node.items()
                if v is not None and not k.startswith("_")}
    if isinstance(node, list):
        return [_strip_nulls(v) for v in node]
    return node


def _categories() -> list[str]:
    return [c.get("id") for c in (config.rules().get("categories") or [])
            if c.get("id")] or ["general"]


# ---------------------------------------------------------------------------
# 1. classify one reporting
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are assisting a duty controller in the Wellington \
Emergency Operations Centre during a live event. You DO NOT make decisions; you \
sort an incoming queue so a human looks at the right things first.

Three things drive escalation, in this order: impact to human life, scale of \
impact, and how quickly a response is needed.

Assign exactly one priority. These tests are Wellington City Council's own, \
from emergency-event-report-examples.md - apply them as written:
- "action_required": confirmed or highly credible, life safety or critical \
infrastructure at risk, and the response window is measured in minutes to \
hours. The next step is to respond and decide.
- "verification_required": potential for significant impact, but the source is \
single, unconfirmed, or contradicted by other data. The next step is to \
confirm the facts. Consequence-if-true can be severe and this is still the \
right bucket - severity alone does not make something actionable. Anything \
from social media or second-hand accounts belongs here at most.
- "situational_awareness": known state, no immediate life safety risk, and the \
impact is either contained or already owned by another party. The next step is \
to log and monitor.

Read past the wording. "Can't get out of the driveway, water up to the wheel \
arches" describes a person trapped by rising water, however calm they sound. A \
formal agency email about a scheduled inspection is not urgent however official \
it looks. Weigh what is happening to people, not which words were used.

Rules you must follow:
- An unverified public post is a signal to investigate, never a confirmed fact.
- Never invent a location, a time, or a detail that is not in the text. If the \
reporting does not name a place, `location_text` is null.
- If the text is too vague to act on, say so in `reason` and set \
`needs_callback` to true.
- `reason` is one sentence. `summary` is at most 15 words and says what \
happened, not what you think about it.

Choose `category` from the list given in the request.

`life_risk` is about consequence, not urgency — could someone die?
- "confirmed": injury or death is stated.
- "likely": someone is described as in immediate danger right now.
- "possible": people could be hurt, or someone vulnerable is involved.
- "none": nothing suggests anyone is at risk.
A confirmed road closure is "none". A vague third-hand report of someone in the
water is still "likely" — consequence does not depend on how sure you are.

`sentiment` is the register the reporting is written in, and it decides what
gets consolidated with what:
- "distress": first-hand, they need help now.
- "urgent": reporting something serious, not themselves in danger.
- "concerned": worried, wants someone to look.
- "informational": passing on facts, no emotional load.
- "supportive": commentary, thanks, well-wishing.
- "speculative": rumour, hearsay, or asking whether something is true."""


def _classify_schema() -> dict:
    return _obj({
        "priority": {"type": "string", "enum": PRIORITY_VALUES},
        "category": {"type": "string", "enum": _categories()},
        "life_risk": {"type": "string", "enum": LIFE_RISK_VALUES},
        "sentiment": {"type": "string", "enum": SENTIMENT_VALUES},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "summary": {"type": "string"},
        "location_text": _opt({"type": "string"}),
        "needs_callback": {"type": "boolean"},
    })


def _describe(r: Reporting, ctx: dict | None = None) -> str:
    ctx = ctx or {}
    lines = [
        f"Channel: {r.source.channel.value}",
        f"Source system: {r.source.system or 'unknown'}",
        f"Received: {r.source.received_at.isoformat()}",
    ]
    if r.reporter and r.reporter.is_official:
        lines.append(f"Reporter is an official from {r.reporter.organisation or 'an agency'}")
    if r.source.credibility_hint is not None:
        lines.append(f"Upstream credibility hint: {r.source.credibility_hint}")
    if r.location and (r.location.text or r.location.has_coords):
        where = r.location.text or f"{r.location.lat}, {r.location.lon}"
        lines.append(f"Stated location: {where} (method: {r.location.method.value})")
    if r.content.subject:
        lines.append(f"Subject: {r.content.subject}")
    if r.content.transcript:
        lines.append(f"Call transcript:\n{r.content.transcript}")
    if r.content.text:
        lines.append(f"Text:\n{r.content.text}")
    for m in r.content.media:
        if m.caption:
            lines.append(f"Attached {m.kind.value} caption: {m.caption}")
        if m.model_caption:
            lines.append(f"Attached {m.kind.value} AI-generated caption: {m.model_caption}")
    if ctx.get("cluster_size", 1) > 1:
        lines.append(f"{ctx['cluster_size']} similar reportings already received.")
    if ctx.get("cluster_flagged_false"):
        lines.append("A controller previously assessed this cluster as a FALSE reporting.")
    return "\n".join(lines)


def classify(r: Reporting, ctx: dict | None = None) -> dict | None:
    """Returns a normalised verdict dict, or `{"error": ...}` if unusable."""
    cats = _categories()
    # The controller's own instructions ride at the end of the stable system
    # prompt so the cached prefix survives until they actually edit them.
    system = CLASSIFY_SYSTEM + instructions.as_prompt_section()
    if provider_name() == "ollama":
        # No schema enforcement there, so the shape goes in the prompt.
        system += ("\n\nReply ONLY with JSON: "
                   '{"priority": "...", "category": "...", "life_risk": "...", '
                   '"sentiment": "...", "confidence": 0.0-1.0, '
                   '"reason": "one sentence", "summary": "max 15 words", '
                   '"location_text": "place or null", "needs_callback": true|false}')

    prompt = (f"Valid categories: {', '.join(cats)}\n\n"
              f"--- REPORTING ---\n{_describe(r, ctx)}")

    try:
        data = provider().complete_json(
            system=system, prompt=prompt, schema=_classify_schema(),
            cfg=_call_cfg(),
            max_tokens=int(_cfg().get("classify_max_tokens", 4096)),
            effort=_cfg().get("classify_effort", "low"),
            cache_system=True,
        )
    except Refusal as exc:
        return {"error": f"declined: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    try:
        priority = Priority(str(data.get("priority", "")).strip())
    except ValueError:
        return {"error": f"unknown priority {data.get('priority')!r}"}

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    category = str(data.get("category") or "general")
    if category not in cats:
        category = "general"

    try:
        life_risk = LifeRisk(str(data.get("life_risk", "")).strip())
    except ValueError:
        life_risk = LifeRisk.none
    try:
        sentiment = Sentiment(str(data.get("sentiment", "")).strip())
    except ValueError:
        sentiment = Sentiment.informational

    return {
        "priority": priority,
        "category": category,
        "life_risk": life_risk,
        "sentiment": sentiment,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(data.get("reason") or "")[:400],
        "summary": str(data.get("summary") or "")[:200] or None,
        "location_text": data.get("location_text") or None,
        "needs_callback": bool(data.get("needs_callback")),
        "model": data.get("_model") or model_name(),
        "usage": data.get("_usage"),
    }


# ---------------------------------------------------------------------------
# 2. shift handover prose
# ---------------------------------------------------------------------------

HANDOVER_SYSTEM = """You write the opening paragraph of a shift handover for an \
emergency operations centre. The reader is the controller coming ON shift and \
has not seen any of this.

Be concrete and short: at most 6 sentences. Lead with what is unresolved and \
what will bite them. Give counts, and name reportings by a short plain-English \
description ("the Petone person-in-water call", "the Island Bay oxygen \
welfare call"). Do NOT quote reporting IDs — the reader has the linked list \
directly below your paragraph, so an id in prose is noise.

Do not reassure, do not editorialise, and do not state anything that is not in \
the data you are given.

`watch_items` is at most 6 short lines, each one thing to keep an eye on, \
written as ordinary prose without ids or punctuation tricks."""


def _handover_schema() -> dict:
    return _obj({
        "summary": {"type": "string"},
        "watch_items": {"type": "array", "items": {"type": "string"}},
    })


def _digest_cards(cards: list[dict], extra: tuple[str, ...] = ()) -> list[dict]:
    """Trim briefing cards to what the summary actually needs.

    The raw cards carry twenty-odd fields each. Feeding all of them in gives the
    model a large, repetitive payload to hold while writing prose — which is
    where transcription drift comes from. Keep the few fields that carry meaning.
    """
    keep = ("excerpt", "priority", "status", "age", "location", "channel") + extra
    return [{k: c.get(k) for k in keep if c.get(k) is not None} for c in cards]


def summarise_shift(briefing: dict) -> dict | None:
    totals = briefing.get("totals", {})
    digest = {
        "shift": {k: briefing.get("shift", {}).get(k)
                  for k in ("operator", "started_at", "ended_at")},
        "totals": totals,
        "never_opened_by_anyone": _digest_cards(
            briefing.get("never_acknowledged", [])[:12]),
        "open_action_required": _digest_cards(
            briefing.get("open_action_required", [])[:12], ("assigned_to",)),
        "stalled": _digest_cards(
            briefing.get("stalled", [])[:8], ("idle_minutes", "last_note")),
        "forwarded_no_reply": _digest_cards(
            briefing.get("forwarded_awaiting_reply", [])[:8],
            ("destination", "waiting_minutes", "dry_run")),
        "priority_overrides": [
            {"from": o.get("from"), "to": o.get("to"),
             "reason": o.get("note"), "what": o.get("excerpt")}
            for o in briefing.get("priority_overrides", [])[:8]
        ],
    }
    payload = json.dumps(digest, default=str, indent=1)[:40000]
    system = HANDOVER_SYSTEM
    if provider_name() == "ollama":
        system += '\n\nReply ONLY with JSON: {"summary": "...", "watch_items": ["..."]}'
    try:
        data = provider().complete_json(
            system=system,
            prompt=f"Shift data:\n{payload}\n\nWrite the handover now.",
            schema=_handover_schema(), cfg=_call_cfg(),
            max_tokens=int(_cfg().get("handover_max_tokens", 8000)),
            effort=_cfg().get("handover_effort", "medium"),
        )
    except Refusal as exc:
        return {"error": f"declined: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    items = data.get("watch_items")
    return {
        "summary": str(data.get("summary") or "").strip(),
        "watch_items": [str(i) for i in items][:8] if isinstance(items, list) else [],
        "model": data.get("_model") or model_name(),
        "usage": data.get("_usage"),
    }
