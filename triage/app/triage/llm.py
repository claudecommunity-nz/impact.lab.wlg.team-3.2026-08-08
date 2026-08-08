"""Local LLM via Ollama.

Three jobs, all optional — if Ollama is not running the whole application still
works on rules alone, which is the behaviour you want in an EOC anyway.

1. `classify`  — a second opinion on one reporting.
2. `generate_ruleset` — a controller declares "storm, 6-hour response window"
   and we draft a ruleset they then EDIT. The model writes the rules; the rules
   do the triage. That keeps every live decision explainable and reviewable.
3. `summarise_shift` — prose for the top of a handover briefing.

The model is never the sole authority. In hybrid mode it may escalate a
priority but not lower one (see settings.engine.llm_may_downgrade).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import yaml

from .. import config
from ..models import Priority, Reporting

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _cfg() -> dict:
    return config.get("settings", "llm", {}) or {}


def base_url() -> str:
    return str(_cfg().get("base_url", "http://localhost:11434")).rstrip("/")


def model_name() -> str:
    return str(_cfg().get("model", "qwen3.5:4b"))


def status() -> dict:
    """Used by the Settings tab to show a green/red dot."""
    try:
        r = httpx.get(f"{base_url()}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        return {"available": True, "base_url": base_url(), "model": model_name(),
                "model_present": model_name() in models, "models": models}
    except Exception as exc:
        return {"available": False, "base_url": base_url(), "model": model_name(),
                "error": str(exc)}


def available() -> bool:
    return status()["available"]


def _strip_think(text: str) -> str:
    if _cfg().get("strip_think_tags", True):
        text = _THINK.sub("", text)
    return text.strip()


def _extract_json(text: str) -> Any:
    text = _strip_think(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Models sometimes wrap JSON in prose or fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start != -1:
        for end in range(len(text), start, -1):
            chunk = text[start:end]
            if chunk[-1] not in "}]":
                continue
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"model did not return JSON: {text[:300]}")


def generate(prompt: str, *, system: str | None = None,
             json_mode: bool = True, timeout: float | None = None) -> str:
    cfg = _cfg()
    body: dict[str, Any] = {
        "model": model_name(),
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": float(cfg.get("temperature", 0))},
    }
    if system:
        body["system"] = system
    if json_mode:
        body["format"] = "json"
    r = httpx.post(f"{base_url()}/api/generate", json=body,
                   timeout=timeout or float(cfg.get("timeout_s", 90)))
    r.raise_for_status()
    return r.json().get("response", "")


# ---------------------------------------------------------------------------
# 1. classify one reporting
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are assisting a duty controller in the Wellington \
Emergency Operations Centre during a live event. You DO NOT make decisions; you \
sort an incoming queue so a human looks at the right things first.

Assign exactly one priority:
- "action_required": credible and specific, and something needs to be done or \
tasked now. Risk to life, injury, entrapment, fire, active flooding of occupied \
buildings, blocked critical access.
- "verification_required": plausible and significant, but the source or the \
detail is not solid enough to task a crew on. Anything from social media or \
second-hand accounts belongs here at most.
- "situational_awareness": useful background, commentary, minor or historic \
detail, or something already known.

Rules you must follow:
- An unverified public post is a signal to investigate, never a confirmed fact.
- Never invent a location, a time, or a detail that is not in the text.
- If the text is too vague to act on, say so in the reason.
- Be brief. One sentence of reasoning.

Reply ONLY with JSON:
{"priority": "...", "category": "...", "confidence": 0.0-1.0,
 "reason": "one sentence", "summary": "max 15 words",
 "location_text": "place mentioned, or null",
 "needs_callback": true|false}"""


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
    """Returns a normalised verdict dict, or None if the model was unusable."""
    categories = [c.get("id") for c in (config.rules().get("categories") or [])]
    prompt = (
        f"{_describe(r, ctx)}\n\n"
        f"Choose `category` from exactly this list: {', '.join(categories)}.\n"
        "Return the JSON object now."
    )
    try:
        raw = generate(prompt, system=CLASSIFY_SYSTEM)
        data = _extract_json(raw)
    except Exception as exc:
        return {"error": str(exc)}

    if not isinstance(data, dict):
        return {"error": "model returned a non-object"}

    try:
        priority = Priority(str(data.get("priority", "")).strip())
    except ValueError:
        return {"error": f"unknown priority {data.get('priority')!r}"}

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    category = str(data.get("category") or "general")
    if category not in categories:
        category = "general"

    return {
        "priority": priority,
        "category": category,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(data.get("reason") or "")[:400],
        "summary": str(data.get("summary") or "")[:200] or None,
        "location_text": data.get("location_text") or None,
        "needs_callback": bool(data.get("needs_callback")),
        "model": model_name(),
    }


# ---------------------------------------------------------------------------
# 2. draft a ruleset from a controller's declaration
# ---------------------------------------------------------------------------

RULESET_SYSTEM = """You write triage rulesets for an emergency operations \
centre. A responder tells you the hazard and their response timeline; you \
produce rules that put the reportings they must act on inside that timeline at \
the top of the queue.

HOW THE SCORING ENGINE WORKS — follow this exactly:
- Every reporting starts at 10 points.
- Each rule that matches ADDS its `score` to the total.
- HIGHER TOTAL = MORE URGENT. A rule that should raise urgency MUST have a
  POSITIVE score. Only use a negative score to push something DOWN the queue
  (rumour, chatter, stale, already known to be false).
- Typical positive scores are +5 to +60. Typical negative scores are -5 to -45.
- Thresholds are positive totals. action_required must be GREATER than
  verification_required. Sensible values: action_required around 60-70,
  verification_required around 25-35.

Condition keys you may use inside `when`:
  any_keywords, all_keywords, none_keywords  (lists of lowercase phrases)
  channel        (list from: phone_call,email,web_form,social_media,news,partner_agency,sensor)
  has_media, has_location, has_precise_location, reporter_is_official  (booleans)
  cluster_size_min (int), cluster_flagged_false (bool)
  within_minutes (int MINUTES, not hours — 6 hours is within_minutes: 360)
  older_than_minutes (int MINUTES)

Do NOT put `within_minutes` or `has_location` on a life-safety rule. Someone
trapped is urgent whether or not they managed to give an address, and whether
the call came in two minutes or two hours ago.

Each rule: id, label, when, score, optionally force_priority / cap_priority
(action_required | verification_required | situational_awareness) and a
one-line rationale.

Hard requirements:
- A life-safety rule with a LARGE POSITIVE score and force_priority: action_required.
- A rule matching channel [social_media] with cap_priority: verification_required.
- A rule matching cluster_flagged_false: true with a large NEGATIVE score and
  cap_priority: situational_awareness.
- 14 to 20 rules. Keyword phrases must be things people actually say when
  phoning a council during this hazard, in New Zealand English.

Reply ONLY with JSON of this shape:
{"name": "...", "notes": "...",
 "thresholds": {"action_required": 65, "verification_required": 30},
 "categories": [{"id": "...", "label": "...", "match": ["..."]}],
 "rules": [{"id": "...", "label": "...", "when": {...}, "score": 40,
            "force_priority": "...", "cap_priority": "...", "rationale": "..."}]}"""


def generate_ruleset(hazard_type: str, response_timeline: str,
                     extra: str | None = None) -> dict:
    """Draft a ruleset. The caller writes it to config for a human to edit —
    it is never applied without the controller seeing it."""
    prompt = (
        f"Hazard: {hazard_type}\n"
        f"Response timeline stated by the controller: {response_timeline}\n"
        + (f"Additional context: {extra}\n" if extra else "")
        + "\nWrite the ruleset JSON now."
    )
    data = _extract_json(generate(prompt, system=RULESET_SYSTEM, timeout=240))
    if not isinstance(data, dict) or not data.get("rules"):
        raise ValueError("model did not produce a usable ruleset")

    thresholds = data.get("thresholds") or {}
    ruleset = {
        "version": int(config.rules().get("version", 1)) + 1,
        "name": data.get("name") or f"{hazard_type} ruleset",
        "generated_by": f"llm:{model_name()}",
        "notes": data.get("notes") or "",
        "event": {"hazard_type": hazard_type, "response_timeline": response_timeline},
        "defaults": {"base_score": 10, "priority": "situational_awareness"},
        "thresholds": {
            "action_required": int(thresholds.get("action_required", 62)),
            "verification_required": int(thresholds.get("verification_required", 30)),
        },
        "categories": data.get("categories") or config.rules().get("categories", []),
        "rules": [],
    }

    valid_priorities = {p.value for p in Priority}
    for rule in data["rules"]:
        if not isinstance(rule, dict) or not rule.get("when"):
            continue
        clean = {
            "id": str(rule.get("id") or f"rule_{len(ruleset['rules'])}"),
            "label": str(rule.get("label") or rule.get("id") or "rule"),
            "when": rule["when"],
            "score": int(rule.get("score", 0)),
        }
        for key in ("force_priority", "cap_priority"):
            if rule.get(key) in valid_priorities:
                clean[key] = rule[key]
        if rule.get("rationale"):
            clean["rationale"] = str(rule["rationale"])
        ruleset["rules"].append(clean)

    if not ruleset["rules"]:
        raise ValueError("model produced no valid rules")
    return ruleset


def ruleset_to_yaml(ruleset: dict) -> str:
    header = (
        "# Generated by the local LLM from the controller's event declaration.\n"
        "# REVIEW BEFORE RELYING ON IT. Edit freely — this file is the authority,\n"
        "# not the model that drafted it.\n\n"
    )
    return header + yaml.safe_dump(ruleset, sort_keys=False, allow_unicode=True,
                                   width=100)


# ---------------------------------------------------------------------------
# 3. shift handover prose
# ---------------------------------------------------------------------------

HANDOVER_SYSTEM = """You write the opening paragraph of a shift handover for an \
emergency operations centre. The reader is the controller coming ON shift and \
has not seen any of this.

Be concrete and short: at most 6 sentences. Lead with what is unresolved and \
what will bite them. Name counts and specific reportings. Do not reassure, do \
not editorialise, do not invent anything not in the data.

Reply ONLY with JSON: {"summary": "...", "watch_items": ["...", "..."]}"""


def summarise_shift(briefing: dict) -> dict | None:
    payload = json.dumps(briefing, default=str)[:14000]
    try:
        data = _extract_json(generate(
            f"Shift data:\n{payload}\n\nWrite the handover JSON now.",
            system=HANDOVER_SYSTEM, timeout=180))
    except Exception as exc:
        return {"error": str(exc)}
    if not isinstance(data, dict):
        return {"error": "model returned a non-object"}
    items = data.get("watch_items")
    return {
        "summary": str(data.get("summary") or "").strip(),
        "watch_items": [str(i) for i in items][:8] if isinstance(items, list) else [],
        "model": model_name(),
    }
