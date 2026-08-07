"""Intake and dashboard server for the report triage prototype.

Two ways in:

  Replay   the April 2026 flood corpus arrives on an accelerated clock, so
           the queue fills the way it did on the night.
  Live     anyone can post a report and it is triaged and on the map in the
           same second.

One way out: every report that has been received so far, assessed, as JSON
and as GeoJSON. The GeoJSON is the point - it composes into the shared
common operating picture rather than sitting inside this interface.

    python3 server.py            # then open http://localhost:8777/

Stdlib only. No pip install, no API keys.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

import triage

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"
PORT = 8777

# One second of wall clock is this many seconds of the emergency. The corpus
# spans 03:36 to 22:10 on 20 April - about 18.5 hours - so at 600x the whole
# night runs in under two minutes, which fits inside a four-minute demo.
DEFAULT_SPEED = 600


class Clock:
    """Maps wall-clock time onto the timeline of the emergency."""

    def __init__(self, start: datetime.datetime, end: datetime.datetime):
        self.start = start
        self.end = end
        self.now = start
        self.speed = DEFAULT_SPEED
        self.running = False
        self._lock = threading.Lock()

    def tick(self, elapsed: float) -> None:
        with self._lock:
            if not self.running:
                return
            self.now += datetime.timedelta(seconds=elapsed * self.speed)
            if self.now >= self.end:
                self.now = self.end
                self.running = False

    def state(self) -> dict:
        with self._lock:
            span = (self.end - self.start).total_seconds()
            done = (self.now - self.start).total_seconds()
            return {
                "now": self.now.isoformat(),
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
                "speed": self.speed,
                "running": self.running,
                "progress": round(done / span, 4) if span else 1.0,
            }

    def control(self, action: str, speed: float | None = None) -> None:
        with self._lock:
            if action == "start":
                if self.now >= self.end:
                    self.now = self.start
                self.running = True
            elif action == "pause":
                self.running = False
            elif action == "reset":
                self.running = False
                self.now = self.start
            if speed:
                self.speed = max(1, min(5000, float(speed)))


class Intake:
    """Holds every report received so far, with its assessment."""

    def __init__(self, corpus: list[dict], clock: Clock):
        self._pending = sorted(corpus, key=lambda r: r["received_at"])
        self._received: list[dict] = []
        self._live_count = 0
        self._lock = threading.Lock()
        self.clock = clock

    def release_due(self) -> int:
        """Move any corpus reports whose time has come into the queue."""
        now = self.clock.state()["now"]
        released = 0
        with self._lock:
            while self._pending and self._pending[0]["received_at"] <= now:
                report = self._pending.pop(0)
                self._received.append(self._assess(report, source="replay"))
                released += 1
        return released

    def submit(self, channel: str, text: str, source_url: str | None) -> dict:
        """Take a report typed in live and put it at the head of the queue."""
        with self._lock:
            self._live_count += 1
            report = {
                "id": f"L{self._live_count:04d}",
                "received_at": self.clock.state()["now"],
                "channel": channel,
                "text": text,
                "source_url": source_url,
            }
            record = self._assess(report, source="live")
            self._received.append(record)
            return record

    def reset(self, corpus: list[dict]) -> None:
        with self._lock:
            self._pending = sorted(corpus, key=lambda r: r["received_at"])
            self._received = []
            self._live_count = 0

    @staticmethod
    def _assess(report: dict, source: str) -> dict:
        record = dict(report)
        record["source"] = source
        try:
            record["assessment"] = triage.assess(report)
        except Exception as exc:
            # A broken assessor must not swallow the report. Losing an
            # incoming report is worse than showing it unassessed.
            record["assessment"] = {
                "place": None, "lat": None, "lon": None, "candidates": [],
                "ambiguous": False, "issue": "other", "category": "verify",
                "confidence": 0.0, "incident": None,
                "signals": [f"assessment failed: {exc}"],
                "assessed_by": "failed",
            }
        return record

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._received)


def load_corpus() -> list[dict]:
    with open(DATA / "reports.json") as fh:
        return json.load(fh)["reports"]


CORPUS = load_corpus()
_times = [r["received_at"] for r in CORPUS]
CLOCK = Clock(
    datetime.datetime.fromisoformat(min(_times)),
    datetime.datetime.fromisoformat(max(_times)) + datetime.timedelta(minutes=5),
)
INTAKE = Intake(CORPUS, CLOCK)


def summarise(records: list[dict]) -> dict:
    counts = {"action": 0, "verify": 0, "awareness": 0}
    incidents: dict[str, int] = {}
    unlocated = ambiguous = 0
    for record in records:
        a = record["assessment"]
        counts[a["category"]] = counts.get(a["category"], 0) + 1
        if a["incident"]:
            incidents[a["incident"]] = incidents.get(a["incident"], 0) + 1
        if a["ambiguous"]:
            ambiguous += 1
        elif a["lat"] is None:
            unlocated += 1
    return {
        "total": len(records),
        "categories": counts,
        "incidents": len(incidents),
        "duplicates": sum(n - 1 for n in incidents.values() if n > 1),
        "unlocated": unlocated,
        "ambiguous": ambiguous,
    }


def geojson(records: list[dict]) -> dict:
    features = []
    for record in records:
        a = record["assessment"]
        if a["lat"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
            "properties": {
                "id": record["id"],
                "received_at": record["received_at"],
                "channel": record["channel"],
                "text": record["text"],
                "source_url": record.get("source_url"),
                "place": a["place"],
                "issue": a["issue"],
                "category": a["category"],
                "confidence": a["confidence"],
                "incident": a["incident"],
                "signals": a["signals"],
                "assessed_by": a["assessed_by"],
            },
        })
    return {
        "type": "FeatureCollection",
        "note": ("Assessed incoming reports, Wellington flooding 20 April 2026. "
                 "Machine triage for human review - not verified fact, and not "
                 "an operational emergency source. In an emergency call 111."),
        "generated_at": CLOCK.state()["now"],
        "features": features,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass  # the console is for the replay ticker, not request noise

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            records = INTAKE.snapshot()
            return self._send({
                "clock": CLOCK.state(),
                "summary": summarise(records),
                "reports": records,
            })
        if path == "/api/reports.geojson":
            return self._send(geojson(INTAKE.snapshot()))
        if path == "/":
            self.path = "/app/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/reports":
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"error": "text is required"}, 400)
            record = INTAKE.submit(
                channel=body.get("channel") or "form",
                text=text,
                source_url=body.get("source_url"),
            )
            return self._send(record, 201)

        if path == "/api/clock":
            action = body.get("action", "")
            if action == "reset":
                INTAKE.reset(CORPUS)
            CLOCK.control(action, body.get("speed"))
            return self._send(CLOCK.state())

        return self._send({"error": "not found"}, 404)


def replay_loop() -> None:
    """Advance the clock and release reports as their time arrives."""
    last = time.monotonic()
    while True:
        time.sleep(0.25)
        now = time.monotonic()
        elapsed, last = now - last, now
        was_running = CLOCK.state()["running"]
        CLOCK.tick(elapsed)
        released = INTAKE.release_due()
        if released and was_running:
            state = CLOCK.state()
            print(f"  {state['now'][11:16]}  +{released} report(s)   "
                  f"{len(INTAKE.snapshot())} total", flush=True)


def main() -> None:
    threading.Thread(target=replay_loop, daemon=True).start()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"Report triage prototype  ->  http://localhost:{PORT}/")
    print(f"{len(CORPUS)} reports in the corpus, "
          f"{CLOCK.start:%H:%M} to {CLOCK.end:%H:%M} on 20 April 2026")
    print("Press the clock in the interface to start the replay.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
