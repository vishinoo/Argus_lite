"""The console, served locally.

A small threaded HTTP server, no framework and no build step, because the
thing most likely to break in front of judges is the thing with the most
machinery behind it. The agent is unchanged: this posts the same incident text
the CLI takes and returns the same result object the CLI prints.

Bound to localhost only. It runs real lookups and, where credentials exist,
sends real messages — that is not something to expose on a conference network.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ic.agent import IncidentCommander, LiveInvestigator
from ic.cli import extract_address
from ic.config import load_env, status as integration_status
from ic.reason import Incident

WEB = Path(__file__).parent / "web"
_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8"}

_counter = {"n": 0}
_lock = threading.Lock()


def _next_id() -> str:
    with _lock:
        _counter["n"] += 1
        return f"IC-{1846 + _counter['n']}"


class Handler(BaseHTTPRequestHandler):
    # The default logger writes a line per asset to stderr, which buries the
    # banner the operator actually needs.
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/integrations":
            return self._json(200, [asdict(i) for i in integration_status()])

        name = "app.html" if path == "/" else path.lstrip("/")
        target = (WEB / name).resolve()
        # Never serve outside the web directory, however the path is written.
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._json(404, {"error": "not found"})
        self._send(200, target.read_bytes(),
                   _TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/api/run":
            return self._json(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "malformed request"})

        text = (payload.get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "no incident text given"})

        # Everything said since the opening line. The address is still taken
        # from the first thing said: a later update saying "he's at the
        # hospital now" must not move the incident.
        updates = tuple(
            u.strip() for u in (payload.get("updates") or []) if str(u).strip()
        )

        address = payload.get("address") or extract_address(text)
        if not address:
            # The same refusal the CLI makes: a guessed address sends the whole
            # investigation somewhere else.
            return self._json(200, {
                "error": "No address could be identified in that description. "
                         "Argus does not guess a location."
            })

        commander = IncidentCommander(
            LiveInvestigator(),
            notify_email=payload.get("notify") or "command@example.gov",
        )
        incident_id = (payload.get("incident_id") or "").strip() or _next_id()
        result = commander.run(
            Incident(incident_id, address, text, updates=updates),
            execute=payload.get("execute", True),
        )
        self._json(200, result.to_dict())


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    load_env()
    server = ThreadingHTTPServer((host, port), Handler)
    live = sum(1 for i in integration_status() if i.live)
    total = len(integration_status())
    print(f"\n  ARGUS INCIDENT COMMANDER")
    print(f"  console   http://{host}:{port}")
    print(f"  {live}/{total} integrations live"
          + ("" if live == total else "  ·  the rest will rehearse"))
    print(f"  ctrl-c to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("  stopped\n")
    finally:
        server.server_close()
