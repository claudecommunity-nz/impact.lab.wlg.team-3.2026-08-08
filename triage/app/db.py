"""SQLite store.

Each reporting is kept as a JSON document plus a handful of extracted columns
for filtering and sorting. Audit events, shifts, clusters, forwards and
generated handovers each get a real table — the audit trail is the part of this
system that has to be trustworthy, so it is append-only and never rewritten.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR
from .models import (AuditEvent, Forward, Priority, Reporting, Shift, Status)

DB_PATH = Path(DATA_DIR) / "triage.db"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS reportings (
    id              TEXT PRIMARY KEY,
    external_key    TEXT UNIQUE,
    ingested_at     TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    occurred_at     TEXT,
    channel         TEXT,
    priority        TEXT,
    status          TEXT,
    category        TEXT,
    score           REAL,
    cluster_id      TEXT,
    lat             REAL,
    lon             REAL,
    acknowledged_by TEXT,
    ingest_shift_id TEXT,
    doc             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rpt_priority ON reportings(priority, score DESC);
CREATE INDEX IF NOT EXISTS ix_rpt_status   ON reportings(status);
CREATE INDEX IF NOT EXISTS ix_rpt_cluster  ON reportings(cluster_id);
CREATE INDEX IF NOT EXISTS ix_rpt_shift    ON reportings(ingest_shift_id);

-- Append-only. Nothing in the application ever UPDATEs or DELETEs this table.
CREATE TABLE IF NOT EXISTS audit_events (
    id           TEXT PRIMARY KEY,
    at           TEXT NOT NULL,
    reporting_id TEXT,
    shift_id     TEXT,
    actor        TEXT NOT NULL,
    is_human     INTEGER NOT NULL DEFAULT 1,
    action       TEXT NOT NULL,
    field        TEXT,
    from_value   TEXT,
    to_value     TEXT,
    note         TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS ix_aud_rpt   ON audit_events(reporting_id, at);
CREATE INDEX IF NOT EXISTS ix_aud_shift ON audit_events(shift_id, at);
CREATE INDEX IF NOT EXISTS ix_aud_at    ON audit_events(at DESC);

CREATE TABLE IF NOT EXISTS shifts (
    id            TEXT PRIMARY KEY,
    operator      TEXT NOT NULL,
    role          TEXT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    handover_note TEXT
);

CREATE TABLE IF NOT EXISTS clusters (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    label          TEXT,
    flagged_false  INTEGER NOT NULL DEFAULT 0,
    flagged_by     TEXT,
    flagged_at     TEXT,
    flag_reason    TEXT
);

CREATE TABLE IF NOT EXISTS forwards (
    id           TEXT PRIMARY KEY,
    reporting_id TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    shift_id     TEXT,
    ok           INTEGER NOT NULL DEFAULT 1,
    acknowledged_at TEXT,
    doc          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fwd_rpt   ON forwards(reporting_id);
CREATE INDEX IF NOT EXISTS ix_fwd_shift ON forwards(shift_id);

CREATE TABLE IF NOT EXISTS handovers (
    id           TEXT PRIMARY KEY,
    shift_id     TEXT,
    generated_at TEXT NOT NULL,
    generated_by TEXT,
    markdown     TEXT,
    doc          TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def reset() -> None:
    """Wipe everything. Used by the demo seeder."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        if DB_PATH.exists():
            DB_PATH.unlink()
        for suffix in ("-wal", "-shm"):
            side = DB_PATH.with_name(DB_PATH.name + suffix)
            if side.exists():
                side.unlink()
    connect()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dump(model) -> str:
    return model.model_dump_json()


# ---------------------------------------------------------------------------
# reportings
# ---------------------------------------------------------------------------


def external_key(r: Reporting) -> str | None:
    """Identity in the origin system, used to make re-ingest idempotent."""
    if r.source.external_id:
        return f"{r.source.channel.value}:{r.source.external_id}"
    return None


def save_reporting(r: Reporting) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO reportings (id, external_key, ingested_at, updated_at,
                    occurred_at, channel, priority, status, category, score,
                    cluster_id, lat, lon, acknowledged_by, ingest_shift_id, doc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                    updated_at=excluded.updated_at, occurred_at=excluded.occurred_at,
                    priority=excluded.priority, status=excluded.status,
                    category=excluded.category, score=excluded.score,
                    cluster_id=excluded.cluster_id, lat=excluded.lat, lon=excluded.lon,
                    acknowledged_by=excluded.acknowledged_by, doc=excluded.doc""",
            (
                r.id, external_key(r), _iso(r.ingested_at), _iso(r.updated_at),
                _iso(r.occurred_at), r.source.channel.value, r.priority.value,
                r.status.value, (r.triage.category if r.triage else None),
                (r.triage.score if r.triage else 0.0), r.cluster_id,
                (r.location.lat if r.location else None),
                (r.location.lon if r.location else None),
                r.acknowledged_by, r.ingest_shift_id, _dump(r),
            ),
        )
        conn.commit()


def exists_external(key: str | None) -> bool:
    if not key:
        return False
    row = connect().execute(
        "SELECT 1 FROM reportings WHERE external_key=?", (key,)).fetchone()
    return row is not None


def get_reporting(rid: str) -> Reporting | None:
    row = connect().execute("SELECT doc FROM reportings WHERE id=?", (rid,)).fetchone()
    return Reporting.model_validate_json(row["doc"]) if row else None


def all_reportings() -> list[Reporting]:
    rows = connect().execute("SELECT doc FROM reportings").fetchall()
    return [Reporting.model_validate_json(r["doc"]) for r in rows]


def query_reportings(
    priority: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    category: str | None = None,
    cluster_id: str | None = None,
    search: str | None = None,
    limit: int = 500,
) -> list[Reporting]:
    sql = "SELECT doc FROM reportings WHERE 1=1"
    args: list[Any] = []
    if priority:
        sql += " AND priority=?"; args.append(priority)
    if status:
        sql += " AND status=?"; args.append(status)
    if channel:
        sql += " AND channel=?"; args.append(channel)
    if category:
        sql += " AND category=?"; args.append(category)
    if cluster_id:
        sql += " AND cluster_id=?"; args.append(cluster_id)
    if search:
        sql += " AND lower(doc) LIKE ?"; args.append(f"%{search.lower()}%")
    sql += " LIMIT ?"; args.append(limit)
    rows = connect().execute(sql, args).fetchall()
    return [Reporting.model_validate_json(r["doc"]) for r in rows]


def cluster_members(cluster_id: str) -> list[Reporting]:
    return query_reportings(cluster_id=cluster_id, limit=1000)


def counts_by_priority() -> dict[str, int]:
    rows = connect().execute(
        "SELECT priority, COUNT(*) n FROM reportings GROUP BY priority").fetchall()
    return {r["priority"]: r["n"] for r in rows}


def counts_by_status() -> dict[str, int]:
    rows = connect().execute(
        "SELECT status, COUNT(*) n FROM reportings GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def append_audit(ev: AuditEvent) -> AuditEvent:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO audit_events (id, at, reporting_id, shift_id, actor,
                    is_human, action, field, from_value, to_value, note, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ev.id, _iso(ev.at), ev.reporting_id, ev.shift_id, ev.actor,
             1 if ev.is_human else 0, ev.action.value, ev.field, ev.from_value,
             ev.to_value, ev.note, json.dumps(ev.detail, default=str)),
        )
        conn.commit()
    return ev


def _audit_rows_to_models(rows: Iterable[sqlite3.Row]) -> list[AuditEvent]:
    out = []
    for r in rows:
        out.append(AuditEvent(
            id=r["id"], at=r["at"], reporting_id=r["reporting_id"],
            shift_id=r["shift_id"], actor=r["actor"], is_human=bool(r["is_human"]),
            action=r["action"], field=r["field"], from_value=r["from_value"],
            to_value=r["to_value"], note=r["note"],
            detail=json.loads(r["detail"] or "{}"),
        ))
    return out


def audit_for_reporting(rid: str) -> list[AuditEvent]:
    rows = connect().execute(
        "SELECT * FROM audit_events WHERE reporting_id=? ORDER BY at ASC, rowid ASC",
        (rid,)).fetchall()
    return _audit_rows_to_models(rows)


def audit_for_shift(shift_id: str) -> list[AuditEvent]:
    rows = connect().execute(
        "SELECT * FROM audit_events WHERE shift_id=? ORDER BY at ASC, rowid ASC",
        (shift_id,)).fetchall()
    return _audit_rows_to_models(rows)


def audit_recent(limit: int = 300, actor: str | None = None,
                 action: str | None = None, humans_only: bool = False) -> list[AuditEvent]:
    sql = "SELECT * FROM audit_events WHERE 1=1"
    args: list[Any] = []
    if actor:
        sql += " AND actor=?"; args.append(actor)
    if action:
        sql += " AND action=?"; args.append(action)
    if humans_only:
        sql += " AND is_human=1"
    sql += " ORDER BY at DESC, rowid DESC LIMIT ?"; args.append(limit)
    return _audit_rows_to_models(connect().execute(sql, args).fetchall())


# ---------------------------------------------------------------------------
# shifts
# ---------------------------------------------------------------------------


def save_shift(s: Shift) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO shifts (id, operator, role, started_at, ended_at, handover_note)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET ended_at=excluded.ended_at,
                   handover_note=excluded.handover_note, operator=excluded.operator,
                   role=excluded.role""",
            (s.id, s.operator, s.role, _iso(s.started_at), _iso(s.ended_at),
             s.handover_note))
        conn.commit()


def _row_to_shift(row: sqlite3.Row | None) -> Shift | None:
    if not row:
        return None
    return Shift(id=row["id"], operator=row["operator"], role=row["role"] or "",
                 started_at=row["started_at"], ended_at=row["ended_at"],
                 handover_note=row["handover_note"])


def open_shift() -> Shift | None:
    row = connect().execute(
        "SELECT * FROM shifts WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return _row_to_shift(row)


def get_shift(shift_id: str) -> Shift | None:
    row = connect().execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
    return _row_to_shift(row)


def list_shifts(limit: int = 50) -> list[Shift]:
    rows = connect().execute(
        "SELECT * FROM shifts ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_shift(r) for r in rows]


# ---------------------------------------------------------------------------
# clusters
# ---------------------------------------------------------------------------


def ensure_cluster(cluster_id: str, label: str, created_at: str) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO clusters (id, created_at, label) VALUES (?,?,?)
               ON CONFLICT(id) DO NOTHING""", (cluster_id, created_at, label))
        conn.commit()


def get_cluster(cluster_id: str | None) -> dict | None:
    if not cluster_id:
        return None
    row = connect().execute("SELECT * FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    return dict(row) if row else None


def flag_cluster_false(cluster_id: str, by: str, reason: str | None) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """UPDATE clusters SET flagged_false=1, flagged_by=?, flagged_at=?,
                                   flag_reason=? WHERE id=?""",
            (by, datetime.now().astimezone().isoformat(), reason, cluster_id))
        conn.commit()


def unflag_cluster(cluster_id: str) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """UPDATE clusters SET flagged_false=0, flagged_by=NULL,
                                   flagged_at=NULL, flag_reason=NULL WHERE id=?""",
            (cluster_id,))
        conn.commit()


def false_cluster_ids() -> set[str]:
    rows = connect().execute(
        "SELECT id FROM clusters WHERE flagged_false=1").fetchall()
    return {r["id"] for r in rows}


# ---------------------------------------------------------------------------
# forwards
# ---------------------------------------------------------------------------


def save_forward(f: Forward) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO forwards (id, reporting_id, sent_at, shift_id, ok,
                                     acknowledged_at, doc)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET acknowledged_at=excluded.acknowledged_at,
                                             ok=excluded.ok, doc=excluded.doc""",
            (f.id, f.reporting_id, _iso(f.sent_at), f.shift_id, 1 if f.ok else 0,
             _iso(f.acknowledged_at), _dump(f)))
        conn.commit()


def forwards_for(rid: str) -> list[Forward]:
    rows = connect().execute(
        "SELECT doc FROM forwards WHERE reporting_id=? ORDER BY sent_at ASC",
        (rid,)).fetchall()
    return [Forward.model_validate_json(r["doc"]) for r in rows]


def forwards_awaiting_ack() -> list[Forward]:
    rows = connect().execute(
        """SELECT doc FROM forwards WHERE acknowledged_at IS NULL AND ok=1
           ORDER BY sent_at ASC""").fetchall()
    return [Forward.model_validate_json(r["doc"]) for r in rows]


def get_forward(fid: str) -> Forward | None:
    row = connect().execute("SELECT doc FROM forwards WHERE id=?", (fid,)).fetchone()
    return Forward.model_validate_json(row["doc"]) if row else None


# ---------------------------------------------------------------------------
# handovers
# ---------------------------------------------------------------------------


def save_handover(hid: str, shift_id: str | None, generated_at: str,
                  generated_by: str, markdown: str, doc: dict) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            """INSERT INTO handovers (id, shift_id, generated_at, generated_by,
                                      markdown, doc)
               VALUES (?,?,?,?,?,?)""",
            (hid, shift_id, generated_at, generated_by, markdown,
             json.dumps(doc, default=str)))
        conn.commit()


def list_handovers(limit: int = 25) -> list[dict]:
    rows = connect().execute(
        """SELECT id, shift_id, generated_at, generated_by
           FROM handovers ORDER BY generated_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_handover(hid: str) -> dict | None:
    row = connect().execute("SELECT * FROM handovers WHERE id=?", (hid,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["doc"] = json.loads(out["doc"])
    return out
