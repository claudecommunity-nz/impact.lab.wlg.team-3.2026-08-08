"""Provider dispatch.

`settings.yaml` → `llm.provider` selects the backend. Both expose the same two
functions — `status(cfg)` and `complete_json(...)` — so the prompts and the
result handling in `llm.py` are written once and work either way.
"""

from __future__ import annotations

from . import claude, ollama

PROVIDERS = {
    "anthropic": claude,
    "claude": claude,      # accept either spelling in config
    "ollama": ollama,
}


def get(name: str):
    key = (name or "anthropic").strip().lower()
    if key not in PROVIDERS:
        raise ValueError(
            f"unknown llm.provider '{name}' — choose one of: "
            f"{', '.join(sorted(set(PROVIDERS)))}")
    return PROVIDERS[key]
