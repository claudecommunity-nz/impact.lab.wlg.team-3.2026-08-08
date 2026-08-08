"""Claude API provider.

Uses the official `anthropic` SDK against the Messages API. Three things matter
more here than in the Ollama provider:

* **Structured outputs.** `output_config.format` with a JSON Schema means the
  API guarantees the shape of what comes back — no fence-stripping, no
  brace-matching, no "the model returned prose today". The schema is a
  constraint on the *request*, not a check on the output.
* **Prompt caching.** The classification system prompt is byte-identical for
  every reporting in an event, so it is marked cacheable. During a real event
  that is the difference between paying for it once and paying for it on every
  single call.
* **Refusals are a normal outcome, not an exception.** A safety classifier can
  decline a request with HTTP 200 and `stop_reason: "refusal"`. Emergency
  content (injuries, fire, entrapment) is exactly the kind of material that can
  trip a false positive, so we check `stop_reason` before touching `content`
  and let the API fall back to another model rather than losing the reporting.
"""

from __future__ import annotations

import json
from typing import Any

from ... import env

MODEL = "claude-opus-5"

# Server-side refusal fallback: on a policy decline the API re-runs the request
# on Anthropic's recommended fallback model inside the same call, instead of
# handing us a refusal we would have to handle by dropping the reporting.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


def _sdk():
    import anthropic
    return anthropic


def client():
    global _client
    if _client is None:
        key = env.api_key()
        if not key:
            raise RuntimeError(
                "No Anthropic API key. Put CLAUDE_API_KEY=... in triage/.env "
                "(the file is gitignored) or export ANTHROPIC_API_KEY.")
        _client = _sdk().Anthropic(api_key=key)
    return _client


def reset() -> None:
    global _client
    _client = None


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def status(cfg: dict) -> dict:
    """Cheap reachability probe for the Settings tab."""
    model = cfg.get("model") or MODEL
    base = {"provider": "anthropic", "model": model,
            "key_source": env.key_source()}
    if not env.has_api_key():
        return {**base, "available": False,
                "error": "No API key. Add CLAUDE_API_KEY to triage/.env."}
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return {**base, "available": False,
                "error": "anthropic SDK not installed — pip install anthropic"}
    try:
        info = client().models.retrieve(model)
        return {**base, "available": True, "model_present": True,
                "display_name": info.display_name,
                "max_input_tokens": info.max_input_tokens,
                "max_output_tokens": info.max_tokens}
    except Exception as exc:
        return {**base, "available": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------


def _text_of(message) -> str:
    return "".join(b.text for b in message.content if b.type == "text")


class Refusal(RuntimeError):
    """The request was declined by a safety classifier, and any fallback model
    declined it too. Surfaced to the operator rather than silently dropped."""

    def __init__(self, category: str | None, explanation: str | None):
        self.category = category
        self.explanation = explanation
        super().__init__(
            f"declined by the model{f' ({category})' if category else ''}"
            + (f": {explanation}" if explanation else ""))


def complete_json(
    *,
    system: str,
    prompt: str,
    schema: dict,
    cfg: dict,
    max_tokens: int = 4096,
    effort: str | None = None,
    cache_system: bool = False,
    stream: bool = False,
) -> dict:
    """One request, returning a dict guaranteed to match `schema`."""
    anthropic = _sdk()
    model = cfg.get("model") or MODEL

    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
    if cache_system:
        # Stable prefix — cached so an event's worth of reportings pays for the
        # instructions once rather than once per reporting.
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": schema}
    }
    if effort:
        output_config["effort"] = effort

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": output_config,
    }
    # No temperature/top_p — removed on Opus 5 and rejected with a 400.

    use_fallbacks = bool(cfg.get("refusal_fallbacks", True))
    if use_fallbacks:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"

    timeout = float(cfg.get("timeout_s", 120))
    api = client().with_options(timeout=timeout)

    def _send(extra: dict[str, Any]) -> Any:
        merged = {**kwargs, **extra}
        if merged.get("betas"):
            if stream:
                with api.beta.messages.stream(**merged) as s:
                    return s.get_final_message()
            return api.beta.messages.create(**merged)
        merged.pop("betas", None)
        merged.pop("fallbacks", None)
        if stream:
            with api.messages.stream(**merged) as s:
                return s.get_final_message()
        return api.messages.create(**merged)

    try:
        message = _send({})
    except anthropic.BadRequestError as exc:
        # If this SDK/account can't do server-side fallbacks, don't lose the
        # whole call over an optional resilience feature.
        if not use_fallbacks or "fallback" not in str(exc).lower():
            raise
        message = _send({"betas": None, "fallbacks": None})

    # Check stop_reason BEFORE reading content — on a refusal, content is empty
    # or partial and indexing into it would raise or return a truncated answer.
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise Refusal(getattr(details, "category", None),
                      getattr(details, "explanation", None))

    text = _text_of(message)
    if not text.strip():
        raise RuntimeError(f"empty response (stop_reason={message.stop_reason})")

    data = json.loads(text)  # schema-constrained, so this is safe
    usage = getattr(message, "usage", None)
    if usage is not None:
        data["_usage"] = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        }
    data["_model"] = message.model
    return data
