"""Administrative obligations — the timetable a responder is held to.

Briefings, shift handovers, sitreps, public updates: things that are due at a
*time* rather than triggered by an event. They sit in the same queue as the
reportings because that is the screen the operator actually watches, and a
handover missed because it was on a different tab is missed just the same.

Two rules govern how they rank.

* **They climb as the clock runs down.** An obligation four hours out is
  background; the same obligation ten minutes out belongs near the top.
* **They never outrank an action-required reporting.** Someone is in the water
  right now — the sitrep waits. This is a hard ceiling in `queue_score`, not a
  weighting that a close deadline can eventually overcome.

The timetable is uploaded (`config/obligations.json`) and treated as read-only
reference data. Whether an obligation has been *done* is state, so it lives in
the database with the rest of the audit trail rather than being written back
into the uploaded file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import db
from .config import CONFIG_DIR
from .models import utcnow

PATH = CONFIG_DIR / "obligations.json"

MAX_BYTES = 2_000_000

# Ranked most to least urgent. `min_minutes` is minutes remaining until due.
# `score` places the row in the queue — see queue_score() for the ceiling that
# keeps every one of these below an action-required reporting.
BANDS = [
    ("overdue",  None,  900, "Overdue"),
    ("due_now",  15,    800, "Due now"),
    ("soon",     60,    650, "Due soon"),
    ("approaching", 120, 450, "Approaching"),
    ("upcoming", 240,   300, "Upcoming"),
    ("later",    None,  150, "Later"),
]

# An obligation may never be scored at or above this. Action-required reportings
# start here, so the ceiling is what enforces "never above action required".
ACTION_FLOOR = 1000


def exists() -> bool:
    return PATH.exists()


def _parse(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("obligations", [])
    if not isinstance(data, list):
        raise ValueError(
            "expected a JSON array of obligations, or an object with an "
            '"obligations" array')

    cleaned: list[dict] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"obligation {i} is not an object")
        if not item.get("due_at"):
            raise ValueError(
                f"obligation {item.get('id') or i} has no due_at — an "
                "obligation without a time cannot be scheduled")
        if _parse_time(item["due_at"]) is None:
            raise ValueError(
                f"obligation {item.get('id') or i} has an unreadable due_at "
                f"{item['due_at']!r}; use ISO 8601, e.g. 2026-08-08T18:45:00+12:00")
        item.setdefault("id", f"OB-{i + 1:03d}")
        cleaned.append(item)
    return cleaned


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load() -> list[dict]:
    if not PATH.exists():
        return []
    try:
        return _parse(PATH.read_text())
    except (ValueError, json.JSONDecodeError):
        # A malformed timetable must not take the queue down with it.
        return []


def save(raw: str) -> dict:
    """Validate then write. Raises ValueError with a usable message."""
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError("timetable is too large")
    items = _parse(raw)                      # raises on anything unusable
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"obligations": items}, indent=2))
    return info()


def clear() -> None:
    if PATH.exists():
        PATH.unlink()


def info() -> dict:
    items = load()
    return {
        "present": bool(items),
        "count": len(items),
        "path": f"config/{PATH.name}",
        "updated_at": (datetime.fromtimestamp(PATH.stat().st_mtime, timezone.utc)
                       .isoformat() if PATH.exists() else None),
        "text": PATH.read_text() if PATH.exists() else "",
    }


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------


def band_for(minutes_until: float | None, done: bool) -> tuple[str, int, str]:
    """(key, score, label) for an obligation this far from its due time."""
    if done:
        return "done", 0, "Done"
    if minutes_until is None:
        return "later", 150, "Later"
    if minutes_until < 0:
        return "overdue", 900, "Overdue"
    for key, limit, score, label in BANDS:
        if limit is not None and minutes_until <= limit:
            return key, score, label
    return "later", 150, "Later"


def queue_score(minutes_until: float | None, done: bool) -> int:
    """Where this sits in the queue. Hard-capped below action-required."""
    _, score, _ = band_for(minutes_until, done)
    return min(score, ACTION_FLOOR - 1)


def _countdown(minutes: float | None) -> str:
    if minutes is None:
        return ""
    late = minutes < 0
    m = int(abs(minutes))
    if m < 60:
        text = f"{m} min"
    elif m < 1440:
        text = f"{m // 60}h {m % 60:02d}m"
    else:
        text = f"{m // 1440}d {(m % 1440) // 60}h"
    return f"{text} overdue" if late else f"in {text}"


def rows(now: datetime | None = None, include_done: bool = False) -> list[dict]:
    """The timetable as queue rows, ready to interleave with the events."""
    now = now or utcnow()
    state = db.obligation_states()
    out = []

    for item in load():
        due = _parse_time(item.get("due_at"))
        minutes = ((due - now).total_seconds() / 60) if due else None
        done_row = state.get(item["id"])
        done = bool(done_row)
        if done and not include_done:
            continue
        key, score, label = band_for(minutes, done)

        out.append({
            "kind": "obligation",
            "id": item["id"],
            "cluster_id": item["id"],       # the queue addresses rows by this
            "type": item.get("type"),
            "short_label": item.get("short_label") or item.get("type") or "obligation",
            "label": item.get("label") or item.get("short_label") or item["id"],
            "due_at": due.isoformat() if due else None,
            "minutes_until": None if minutes is None else round(minutes, 1),
            "countdown": _countdown(minutes),
            "urgency": key,
            "urgency_label": label,
            "queue_score": queue_score(minutes, done),
            "owner_role": item.get("owner_role"),
            "audience": item.get("audience"),
            "score_bearing": bool(item.get("score_bearing")),
            "shift_ref": item.get("shift_ref"),
            "notes": item.get("notes"),
            "done": done,
            "done_at": done_row.get("done_at") if done_row else None,
            "done_by": done_row.get("done_by") if done_row else None,
            "done_note": done_row.get("note") if done_row else None,
        })

    out.sort(key=lambda o: (-o["queue_score"], o["due_at"] or ""))
    return out


def summary(now: datetime | None = None) -> dict:
    live = rows(now)
    return {
        "total": len(load()),
        "outstanding": len(live),
        "overdue": sum(1 for o in live if o["urgency"] == "overdue"),
        "due_now": sum(1 for o in live if o["urgency"] == "due_now"),
        "next": live[0] if live else None,
    }
