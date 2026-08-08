"""Turn whatever an upstream system sends into a canonical `Reporting`.

The mapping is declared in config/sources.yaml, not in code, so a teammate can
wire up a new feed by editing YAML while the server is running.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from . import config
from .models import Channel, Reporting

NZ_TZ = timezone(timedelta(hours=12))  # NZST; close enough for a prototype
_INDEX = re.compile(r"^(.*?)\[(\d+)\]$")


# ---------------------------------------------------------------------------
# dotted-path helpers
# ---------------------------------------------------------------------------


def dig(obj: Any, dotted: str) -> Any:
    """Read `a.b[0].c` out of nested dicts/lists. Returns None if absent."""
    node = obj
    for part in dotted.split("."):
        m = _INDEX.match(part)
        idx = None
        if m:
            part, idx = m.group(1), int(m.group(2))
        if part:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        if idx is not None:
            if isinstance(node, (list, tuple)) and len(node) > idx:
                node = node[idx]
            else:
                return None
        if node is None:
            return None
    return node


def plant(target: dict, dotted: str, value: Any) -> None:
    """Write into nested dicts, creating them as needed."""
    parts = dotted.split(".")
    node = target
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):  # pragma: no cover - malformed mapping
            return
    node[parts[-1]] = value


def _resolve(payload: dict, expr: Any) -> Any:
    """`"=literal"` yields the literal; anything else is a source path."""
    if not isinstance(expr, str):
        return expr
    if expr.startswith("="):
        lit = expr[1:]
        if lit.lower() in ("true", "false"):
            return lit.lower() == "true"
        return lit
    return dig(payload, expr)


# ---------------------------------------------------------------------------
# time normalisation
# ---------------------------------------------------------------------------


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=NZ_TZ)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=NZ_TZ)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=NZ_TZ)
        except ValueError:
            continue
    return None


_TIME_FIELDS = {"source.received_at", "occurred_at"}


# ---------------------------------------------------------------------------
# adapter application
# ---------------------------------------------------------------------------


def unpack_batch(body: Any, adapter: dict | None) -> list[dict]:
    """Accept a bare object, a bare list, or {"<batch_key>": [...]}."""
    if isinstance(body, list):
        return [b for b in body if isinstance(b, dict)]
    if not isinstance(body, dict):
        return []
    keys = ["items", "reportings", "reports", "results", "data"]
    if adapter and adapter.get("batch_key"):
        keys.insert(0, adapter["batch_key"])
    for k in keys:
        if isinstance(body.get(k), list):
            return [b for b in body[k] if isinstance(b, dict)]
    return [body]


def apply_adapter(payload: dict, adapter: dict) -> dict:
    """Map one upstream payload onto a canonical Reporting dict."""
    out: dict[str, Any] = {}

    for canonical, expr in (adapter.get("mapping") or {}).items():
        value = _resolve(payload, expr)
        if value is None or value == "":
            continue
        if canonical in _TIME_FIELDS:
            parsed = parse_time(value)
            if parsed is None:
                continue
            value = parsed.isoformat()
        plant(out, canonical, value)

    for canonical, spec in (adapter.get("collections") or {}).items():
        rows = dig(payload, spec.get("from", "")) or []
        if not isinstance(rows, list):
            continue
        item_map = spec.get("item") or {}
        built = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            entry = {}
            for field, expr in item_map.items():
                v = _resolve(row, expr)
                if v not in (None, ""):
                    entry[field] = v
            if entry:
                built.append(entry)
        if built:
            plant(out, canonical, built)

    # The channel comes from the adapter definition, not the payload — an
    # upstream system does not get to declare itself a partner agency.
    plant(out, "source.channel", adapter.get("channel", Channel.other.value))
    if adapter.get("id"):
        out.setdefault("source", {}).setdefault("ingested_by", adapter["id"])

    out["raw"] = payload
    return out


def _clean(node: Any) -> Any:
    """Drop empty containers so pydantic defaults win over `{}`."""
    if isinstance(node, dict):
        cleaned = {k: _clean(v) for k, v in node.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, {}, [])}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def to_reporting(payload: dict, adapter_id: str | None = None) -> Reporting:
    """Map (if an adapter is named) and validate into a `Reporting`."""
    if adapter_id:
        adapter = config.adapter(adapter_id)
        if adapter is None:
            raise ValueError(f"no adapter '{adapter_id}' in config/sources.yaml")
        payload = apply_adapter(payload, adapter)
    else:
        payload = dict(payload)
        payload.setdefault("raw", {})

    body = _clean(payload)

    # `raw` must survive cleaning verbatim, empty values and all.
    if "raw" in payload:
        body["raw"] = payload["raw"]

    # Media captions coming from a model must not masquerade as the author's.
    for media in (body.get("content") or {}).get("media", []) or []:
        if media.get("model_caption") and not media.get("caption"):
            media.setdefault("caption_source", "model")

    return Reporting.model_validate(body)


def describe_adapters() -> list[dict]:
    """Summary for the Settings tab."""
    out = []
    for a in config.adapters():
        out.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "channel": a.get("channel"),
            "description": a.get("description"),
            "endpoint": f"/api/v1/ingest?adapter={a.get('id')}",
            "fields": sorted((a.get("mapping") or {}).keys()),
            "collections": sorted((a.get("collections") or {}).keys()),
        })
    return out
