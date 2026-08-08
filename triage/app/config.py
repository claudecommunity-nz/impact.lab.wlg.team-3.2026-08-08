"""YAML config loading with mtime-based hot reload.

Everything tunable lives in triage/config/*.yaml so the ruleset can be edited
mid-demo (or mid-event) without restarting anything.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}

KNOWN = {
    "settings": CONFIG_DIR / "settings.yaml",
    "triage_rules": CONFIG_DIR / "triage_rules.yaml",
    "destinations": CONFIG_DIR / "destinations.yaml",
    "sources": CONFIG_DIR / "sources.yaml",
}


def path_for(name: str) -> Path:
    if name not in KNOWN:
        raise KeyError(f"unknown config '{name}' (have: {', '.join(KNOWN)})")
    return KNOWN[name]


def load(name: str) -> dict:
    """Return the parsed config, re-reading only when the file changed."""
    p = path_for(name)
    mtime = p.stat().st_mtime
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        data = yaml.safe_load(p.read_text()) or {}
        _cache[name] = (mtime, data)
        return data


def raw_text(name: str) -> str:
    return path_for(name).read_text()


def save_text(name: str, text: str) -> dict:
    """Validate then write. Raises yaml.YAMLError if the operator's edit is
    malformed, so the UI can show the parse error instead of bricking triage."""
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("config must be a YAML mapping at the top level")
    p = path_for(name)
    p.write_text(text)
    with _lock:
        _cache.pop(name, None)
    return parsed


def save_data(name: str, data: dict) -> dict:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    return save_text(name, text)


def get(name: str, dotted: str, default: Any = None) -> Any:
    """`get("settings", "llm.model")`"""
    node: Any = load(name)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def settings() -> dict:
    return load("settings")


def rules() -> dict:
    return load("triage_rules")


def destinations() -> list[dict]:
    return load("destinations").get("destinations", [])


def destination(dest_id: str) -> dict | None:
    for d in destinations():
        if d.get("id") == dest_id:
            return d
    return None


def adapters() -> list[dict]:
    return load("sources").get("adapters", [])


def adapter(adapter_id: str) -> dict | None:
    for a in adapters():
        if a.get("id") == adapter_id:
            return a
    return None
