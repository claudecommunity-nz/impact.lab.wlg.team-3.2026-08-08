#!/usr/bin/env python3
"""Serve the repo so site/ can load the replay bundle.

    python3 scripts/serve.py        then open http://localhost:8777/site/

Use this rather than `python3 -m http.server`. That server is single-threaded:
the page asks for the MapLibre bundle, five JSON files and a 480 KB GeoJSON at
once, the requests queue behind each other, and the map's source never finishes
loading - so MapLibre never fires its 'load' event and the map stays blank with
no error. It works often enough to be confusing.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import socketserver


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Stops a stale index.html surviving an edit, which wastes debugging time.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "404" in (fmt % args):
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    handler = functools.partial(Handler, directory=str(root))
    with Server(("127.0.0.1", args.port), handler) as httpd:
        print(f"Serving {root}")
        print(f"Open http://localhost:{args.port}/site/   (ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
