#!/usr/bin/env python3
"""Play the 20 April 2026 event bundle into the running server.

    python3 push.py                  # 600x - the 19-hour night in under two minutes
    python3 push.py --speed 900      # faster, for a four-minute demo slot
    python3 push.py --from 17:00     # rehearse the declaration surge on its own
    python3 push.py --once           # everything at once, for testing

This owns the clock. The bundle is a flat file with timestamps in it and nothing
that moves; what "realtime" means for this prototype is decided here and nowhere
else. Ctrl-C stops it cleanly at any point.

Each report is posted with its own id and its own `received_at`, so a report
from 03:41 lands in the queue at 03:41 rather than at whatever the server thinks
the time is. The server stores by id, so re-running this cannot duplicate
anything - a second run replaces each record with an identical one. Reports
already delivered are skipped anyway, which is what makes resuming after Ctrl-C
quick rather than merely harmless.

Run the server without `--replay`. With that flag it drives its own 76-report
corpus from an internal clock, and the queue fills from both ends at once.

Stdlib only. No pip install.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BUNDLE = pathlib.Path(__file__).parent / "data" / "event" / "2026-04-20"
SERVER = "http://localhost:8777"
DEFAULT_SPEED = 600

CATEGORY_MARK = {"action": "!", "verify": "?", "awareness": "."}


def load_reports() -> list[dict]:
    path = BUNDLE / "reports.jsonl"
    if not path.exists():
        sys.exit(f"{path} is missing. Run: python3 build/build_event.py")
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def get_state() -> dict | None:
    try:
        with urllib.request.urlopen(f"{SERVER}/api/state", timeout=10) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError):
        return None


def post(report: dict, timeout: int = 10) -> dict | None:
    """Send one report, keeping its own id and its own moment in the event."""
    body = json.dumps({
        "id": report["id"],
        "received_at": report["received_at"],
        "channel": report["channel"],
        "text": report["text"],
        "source_url": report["source_url"],
    }).encode()
    request = urllib.request.Request(
        f"{SERVER}/api/reports", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"    server refused it: {exc.code} {exc.reason}")
    except (urllib.error.URLError, OSError) as exc:
        print(f"    could not reach the server: {exc}")
    return None


def parse_from(value: str, day: datetime.datetime) -> datetime.datetime:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        sys.exit(f"--from wants HH:MM, not {value!r}")
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def check_server(reports: list[dict]) -> set[str]:
    """Which report ids the server already holds, plus a warning about --replay.

    If the server was started with --replay it is releasing its own 76-report
    corpus from an internal clock while this pushes. Two clocks feeding one queue
    makes a demo that shows two different events at once, and the corpus reuses
    the same R-numbered ids, so some of it would be overwritten mid-run. Worth
    stopping for rather than quietly working around.
    """
    state = get_state()
    if state is None:
        sys.exit(f"Nothing answering at {SERVER}. Start it with: python3 server.py")

    if state.get("clock", {}).get("running"):
        print("  WARNING: the server's internal replay clock is running, so it was")
        print("  probably started with --replay. Restart it as plain `python3")
        print("  server.py` or the queue will fill from both ends at once.\n")

    delivered = {r["id"] for r in state.get("reports", [])}
    already = sum(1 for r in reports if r["id"] in delivered)
    if already:
        print(f"  {already} of {len(reports)} reports are already on the server; "
              "skipping those.\n")
    return delivered


def ticker(report: dict, record: dict | None, index: int, total: int) -> None:
    assessment = (record or {}).get("assessment") or {}
    category = assessment.get("category", "")
    place = assessment.get("place") or ("ambiguous" if assessment.get("ambiguous")
                                        else "unplaced")
    mark = CATEGORY_MARK.get(category, " ")
    text = report["text"][:58].replace("\n", " ")
    # Flushed every line. Python buffers stdout when it is not a terminal, and
    # the ticker piped to a file or a pager would otherwise show nothing until
    # the run ended - or nothing at all, if it ended with Ctrl-C.
    print(f"  {report['received_at'][11:16]}  {report['id']}  {mark} "
          f"{report['channel']:7} {text:<58}  {category:9} {place[:24]:<24} "
          f"{index}/{total}", flush=True)


def run(reports: list[dict], speed: float, once: bool, delivered: set[str]) -> int:
    pending = [r for r in reports if r["id"] not in delivered]
    if not pending:
        print("Everything in the bundle is already on the server. Nothing to do.")
        return 0

    total = len(pending)
    first = datetime.datetime.fromisoformat(pending[0]["received_at"])
    started = time.monotonic()
    sent = 0

    print(f"Pushing {total} reports to {SERVER}/api/reports", flush=True)
    if once:
        print("  --once: no waiting, everything goes now.\n", flush=True)
    else:
        span = (datetime.datetime.fromisoformat(pending[-1]["received_at"])
                - first).total_seconds()
        print(f"  {speed:g}x - {span / 3600:.1f} event hours in "
              f"{span / speed / 60:.1f} wall minutes. Ctrl-C to stop.\n",
              flush=True)

    for report in pending:
        if not once:
            due = (datetime.datetime.fromisoformat(report["received_at"])
                   - first).total_seconds() / speed
            wait = due - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)
        record = post(report)
        sent += 1
        ticker(report, record, sent, total)

    print(f"\nDone. {sent} report(s) pushed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                        help="wall-clock seconds to event seconds "
                             f"(default {DEFAULT_SPEED})")
    parser.add_argument("--from", dest="start", metavar="HH:MM",
                        help="start partway through the night")
    parser.add_argument("--once", action="store_true",
                        help="push everything immediately, no clock")
    args = parser.parse_args()

    if args.speed <= 0:
        sys.exit("--speed must be greater than zero")

    reports = load_reports()
    if args.start:
        day = datetime.datetime.fromisoformat(reports[0]["received_at"])
        cutoff = parse_from(args.start, day)
        reports = [r for r in reports
                   if datetime.datetime.fromisoformat(r["received_at"]) >= cutoff]
        if not reports:
            sys.exit(f"No reports at or after {args.start}.")
        print(f"Starting at {args.start} - {len(reports)} report(s) from there.\n")

    delivered = check_server(reports)
    try:
        return run(reports, args.speed, args.once, delivered)
    except KeyboardInterrupt:
        print("\n\nStopped. Re-run to carry on - reports already sent are skipped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
