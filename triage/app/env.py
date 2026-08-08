"""Environment loading.

Reads `triage/.env` so the API key never has to live in a shell profile or,
worse, in the repo. `.env` is gitignored — this repo is public.

The Anthropic SDK looks for `ANTHROPIC_API_KEY`; this project's `.env` uses
`CLAUDE_API_KEY`, so we bridge the two rather than making anyone rename a key
they already have working.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# Accepted aliases, in priority order.
KEY_ALIASES = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_KEY")

_loaded = False


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True

    if ENV_PATH.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(ENV_PATH, override=False)
        except ImportError:  # tiny fallback so python-dotenv stays optional
            for line in ENV_PATH.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

    if not os.getenv("ANTHROPIC_API_KEY"):
        for alias in KEY_ALIASES[1:]:
            value = os.getenv(alias)
            if value:
                os.environ["ANTHROPIC_API_KEY"] = value
                break


def api_key() -> str | None:
    load()
    return os.getenv("ANTHROPIC_API_KEY")


def has_api_key() -> bool:
    return bool(api_key())


def key_source() -> str:
    """For the Settings tab — says where the key came from, never what it is."""
    load()
    if not os.getenv("ANTHROPIC_API_KEY"):
        return "not configured"
    if ENV_PATH.exists():
        text = ENV_PATH.read_text()
        for alias in KEY_ALIASES:
            if f"{alias}=" in text:
                return f"{ENV_PATH.name} ({alias})"
    return "environment"
