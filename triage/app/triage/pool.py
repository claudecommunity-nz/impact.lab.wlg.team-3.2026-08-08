"""Background workers that add the model's assessment after the fact.

A model call takes around four seconds. During an event, reportings arrive far
faster than that - the 20 April replay delivers 348 of them in a couple of
minutes - so waiting for the model inside the ingest path would put the whole
queue minutes behind the clock, which is worse than useless to a controller.

So ingest stays synchronous and rules-only: a reporting is in the queue,
scored and visible, the moment it lands. Its id goes on this queue, a worker
picks it up, asks the model, and updates the record in place. The interface
polls, so the operator sees the verdict arrive a few seconds later, and sees
where the model disagrees with the ruleset.

Nothing here is required. With workers stopped, or the model unreachable, the
queue still works on the ruleset alone - the assessments simply never arrive.
"""

from __future__ import annotations

import queue
import threading
import time

from .. import config, db
from ..models import AuditAction

_queue: "queue.Queue[str]" = queue.Queue()
_threads: list[threading.Thread] = []
_stop = threading.Event()
_lock = threading.Lock()

_stats = {"queued": 0, "assessed": 0, "failed": 0, "skipped": 0, "in_flight": 0}


def enabled() -> bool:
    return bool(config.get("settings", "engine.llm_async", True))


def _worker() -> None:
    # Imported here rather than at module scope: engine imports this module,
    # and importing it back at the top would be a cycle.
    from . import engine

    while not _stop.is_set():
        try:
            rid = _queue.get(timeout=0.5)
        except queue.Empty:
            continue

        with _lock:
            _stats["in_flight"] += 1
        try:
            reporting = db.get_reporting(rid)
            if reporting is None:
                with _lock:
                    _stats["skipped"] += 1
                continue

            before = reporting.priority
            engine.triage(reporting, use_llm=True)
            db.save_reporting(reporting)

            result = reporting.triage
            note = "Model assessment added"
            if result and result.disagreement:
                note = result.disagreement
            elif before != reporting.priority:
                note = (f"Model raised priority from {before.value} to "
                        f"{reporting.priority.value}")

            from .. import audit as audit_mod
            audit_mod.record(
                AuditAction.retriaged, reporting_id=rid, actor="model",
                is_human=False, note=note,
                detail={"model": result.model if result else None,
                        "priority_before": before.value,
                        "priority_after": reporting.priority.value})
            with _lock:
                _stats["assessed"] += 1
        except Exception as exc:
            # A model failure must never lose the reporting. It keeps its
            # rules verdict and stays in the queue where a human can see it.
            with _lock:
                _stats["failed"] += 1
            print(f"  model assessment failed for {rid}: {exc}", flush=True)
        finally:
            with _lock:
                _stats["in_flight"] -= 1
            _queue.task_done()


def submit(reporting_id: str) -> None:
    """Queue a reporting for assessment. Returns immediately."""
    if not enabled() or not _threads:
        return
    with _lock:
        _stats["queued"] += 1
    _queue.put(reporting_id)


def warm() -> None:
    """Pay the prompt-cache write before anyone is watching.

    The first call of the day writes the rubric into the cache and takes over
    a minute; every call after it reads the cache and takes about four
    seconds. Doing that at startup keeps the minute out of the demo.
    """
    from . import llm

    if llm.provider_name() not in ("anthropic", "claude"):
        return
    try:
        started = time.monotonic()
        # Same system prompt the classifier uses, so this writes the cache
        # entry the real calls will read.
        llm.provider().complete_json(
            system=llm.CLASSIFY_SYSTEM,
            prompt="Reply with ready set to true. This is a warm-up, not a reporting.",
            schema={"type": "object",
                    "properties": {"ready": {"type": "boolean"}},
                    "required": ["ready"], "additionalProperties": False},
            cfg=llm._cfg(), max_tokens=256, effort="low", cache_system=True)
        print(f"  model cache warmed in {time.monotonic() - started:.0f}s "
              f"({llm.model_name()})", flush=True)
    except Exception as exc:
        print(f"  model cache warm failed: {exc}", flush=True)


def start(workers: int | None = None) -> None:
    if not enabled() or _threads:
        return
    count = int(workers or config.get("settings", "engine.llm_workers", 8))
    _stop.clear()
    for n in range(max(1, count)):
        thread = threading.Thread(target=_worker, name=f"triage-llm-{n}",
                                  daemon=True)
        thread.start()
        _threads.append(thread)
    threading.Thread(target=warm, name="triage-llm-warm", daemon=True).start()
    print(f"  {len(_threads)} model workers started", flush=True)


def stop() -> None:
    _stop.set()
    _threads.clear()


def stats() -> dict:
    with _lock:
        pending = _queue.qsize()
        return {**_stats, "pending": pending, "workers": len(_threads),
                "enabled": enabled()}
