#!/usr/bin/env python3
"""Play the 20 April 2026 event bundle into the running triage server.

    python3 push.py                  # 600x - the 19-hour night in under two minutes
    python3 push.py --speed 900      # faster, for a four-minute demo slot
    python3 push.py --from 17:00     # rehearse the declaration surge on its own
    python3 push.py --once           # everything at once, for testing

This owns the clock. The bundle is a flat file with timestamps in it and nothing
that moves; what "realtime" means for this prototype is decided here and nowhere
else. Ctrl-C stops it cleanly at any point.

Each report goes to `/api/v1/ingest` through the adapter matching its channel,
so the channel a reporting claims comes from the adapter rather than from the
payload. Its bundle id travels as `source.external_id`, which is what makes
re-running safe: the server rejects an id it already holds instead of creating a
second copy. Stop this halfway, run it again, and it picks up where it stopped.

Start the server first:

    cd triage && .venv/bin/python -m uvicorn app.main:app --port 8000

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
SERVER = "http://localhost:8000"
API = f"{SERVER}/api/v1"
DEFAULT_SPEED = 600

# The bundle's channel names onto the adapters in triage/config/sources.yaml.
# Each adapter declares its own channel, so a replayed report cannot claim to
# have arrived by a channel it did not.
ADAPTERS = {
    "phone": "event_phone",
    "social": "event_social",
    "form": "event_form",
    "email": "event_email",
    "partner": "event_partner",
    "news": "event_news",
}

PRIORITY_MARK = {
    "action_required": "!",
    "verification_required": "?",
    "situational_awareness": ".",
}


def load_reports() -> list[dict]:
    path = BUNDLE / "reports.jsonl"
    if not path.exists():
        sys.exit(f"{path} is missing. Run: python3 build/build_event.py")
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def api_get(path: str, timeout: int = 10) -> dict | None:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def post(report: dict, timeout: int = 10) -> dict | None:
    """Send one report through the adapter for its channel."""
    adapter = ADAPTERS.get(report["channel"])
    if adapter is None:
        print(f"    no adapter for channel {report['channel']!r}, skipping")
        return None

    body = json.dumps({
        "id": report["id"],
        "received_at": report["received_at"],
        "text": report["text"],
        "source_url": report.get("source_url"),
    }).encode()
    request = urllib.request.Request(
        f"{API}/ingest?adapter={adapter}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:160]
        print(f"    server refused {report['id']}: {exc.code} {detail}")
    except (urllib.error.URLError, OSError) as exc:
        print(f"    could not reach the server: {exc}")
    return None


def parse_from(value: str, day: datetime.datetime) -> datetime.datetime:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        sys.exit(f"--from wants HH:MM, not {value!r}")
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def check_server() -> None:
    """Confirm something is listening and that it knows our adapters."""
    health = api_get("/health")
    if health is None:
        sys.exit(f"Nothing answering at {API}. Start it with:\n"
                 "  cd triage && .venv/bin/python -m uvicorn app.main:app --port 8000")

    known = {a["id"] for a in (api_get("/adapters") or [])}
    missing = sorted(set(ADAPTERS.values()) - known)
    if missing:
        sys.exit("The server does not have these adapters: "
                 + ", ".join(missing)
                 + "\nThey live in triage/config/sources.yaml.")

    held = health.get("reportings", 0)
    if held:
        print(f"  the server already holds {held} reporting(s); ids it already "
              "has will be rejected rather than duplicated.\n")


def ticker(report: dict, result: dict | None, card: dict | None,
           index: int, total: int) -> None:
    if result is None:
        outcome, priority, place = "failed", "", ""
    elif result.get("duplicates_rejected"):
        outcome, priority, place = "dup", "", ""
    elif result.get("errors"):
        outcome, priority, place = "error", "", str(result["errors"][0])[:30]
    else:
        outcome = "ok"
        priority = (card or {}).get("priority", "")
        place = (card or {}).get("location_text") or (
            "unplaced" if card else "")

    mark = PRIORITY_MARK.get(priority, " ")
    text = report["text"][:52].replace("\n", " ")
    # Flushed every line. Python buffers stdout when it is not a terminal, and
    # the ticker piped to a file or a pager would otherwise show nothing until
    # the run ended - or nothing at all, if it ended with Ctrl-C.
    print(f"  {report['received_at'][11:16]}  {report['id']:>6}  {mark} "
          f"{report['channel']:7} {text:<52}  {outcome:5} "
          f"{priority[:20]:<20} {place[:22]:<22} {index}/{total}", flush=True)


def run(reports: list[dict], speed: float, once: bool, quiet: bool) -> int:
    total = len(reports)
    first = datetime.datetime.fromisoformat(reports[0]["received_at"])
    started = time.monotonic()
    counts = {"ok": 0, "dup": 0, "failed": 0}

    print(f"Pushing {total} reports to {API}/ingest", flush=True)
    if once:
        print("  --once: no waiting, everything goes now.\n", flush=True)
    else:
        span = (datetime.datetime.fromisoformat(reports[-1]["received_at"])
                - first).total_seconds()
        print(f"  {speed:g}x - {span / 3600:.1f} event hours in "
              f"{span / speed / 60:.1f} wall minutes. Ctrl-C to stop.\n",
              flush=True)

    for index, report in enumerate(reports, start=1):
        if not once:
            due = (datetime.datetime.fromisoformat(report["received_at"])
                   - first).total_seconds() / speed
            wait = due - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)

        result = post(report)
        card = None
        if result and result.get("ids") and not quiet:
            # One extra local call so the ticker shows what the triage decided,
            # which is the thing worth watching while the queue fills.
            card = api_get(f"/reportings/{result['ids'][0]}", timeout=5)

        if result is None:
            counts["failed"] += 1
        elif result.get("duplicates_rejected"):
            counts["dup"] += 1
        else:
            counts["ok"] += 1
        ticker(report, result, card, index, total)

    print(f"\nDone. {counts['ok']} accepted, {counts['dup']} already held, "
          f"{counts['failed']} failed.")
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
    parser.add_argument("--quiet", action="store_true",
                        help="skip the follow-up lookup that shows the triage "
                             "decision in the ticker")
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

    check_server()
    try:
        return run(reports, args.speed, args.once, args.quiet)
    except KeyboardInterrupt:
        print("\n\nStopped. Re-run to carry on - reports already sent are "
              "rejected as duplicates rather than repeated.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
