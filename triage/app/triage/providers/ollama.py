"""Ollama provider — local models, no API key, no network egress.

Kept as a first-class alternative to the Claude provider for two reasons: it
works with no connectivity at all, and an EOC may have a policy against sending
reporting content off-site.

The trade-off is that Ollama has no schema enforcement. It is asked for JSON and
usually complies, so the response still has to be dug out of whatever the model
wrapped it in — the salvage logic below is why the Claude provider's
`output_config.format` is the better path when it is available.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def base_url(cfg: dict) -> str:
    return str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")


def status(cfg: dict) -> dict:
    model = cfg.get("model", "qwen3.5:4b")
    try:
        r = httpx.get(f"{base_url(cfg)}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        return {"provider": "ollama", "available": True, "model": model,
                "base_url": base_url(cfg), "model_present": model in models,
                "models": models}
    except Exception as exc:
        return {"provider": "ollama", "available": False, "model": model,
                "base_url": base_url(cfg), "error": str(exc)}


def _strip_think(text: str, cfg: dict) -> str:
    if cfg.get("strip_think_tags", True):
        text = _THINK.sub("", text)
    return text.strip()


def _extract_json(text: str, cfg: dict) -> Any:
    text = _strip_think(text, cfg)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
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


def complete_json(*, system: str, prompt: str, schema: dict, cfg: dict,
                  max_tokens: int = 4096, effort: str | None = None,
                  cache_system: bool = False, stream: bool = False) -> dict:
    """`schema`, `effort`, `cache_system` and `stream` are accepted for
    interface parity and ignored — Ollama supports none of them. The schema is
    still described to the model inside the prompt by the caller."""
    body: dict[str, Any] = {
        "model": cfg.get("model", "qwen3.5:4b"),
        "prompt": prompt,
        "system": system,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": float(cfg.get("temperature", 0))},
    }
    r = httpx.post(f"{base_url(cfg)}/api/generate", json=body,
                   timeout=float(cfg.get("timeout_s", 120)))
    r.raise_for_status()
    data = _extract_json(r.json().get("response", ""), cfg)
    if not isinstance(data, dict):
        raise ValueError("model returned a non-object")
    data["_model"] = cfg.get("model", "qwen3.5:4b")
    return data
