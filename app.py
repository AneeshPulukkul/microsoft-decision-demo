from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from config import build_client
from decision_client import DecisionAPIError, MockDecisionClient
from samples import SAMPLE_TICKETS
from triage import POLICY, QUESTIONS, evaluate

ROOT = Path(__file__).resolve().parent
WEB_DIST = ROOT / "web" / "dist"

RATE_LOCK = threading.Lock()
RATE_EVENTS: dict[str, deque[float]] = defaultdict(deque)


def allow_request(ip: str, limit: int) -> tuple[bool, int]:
    if limit <= 0:
        return True, 0
    now = time.monotonic()
    with RATE_LOCK:
        events = RATE_EVENTS[ip]
        while events and now - events[0] > 60:
            events.popleft()
        if len(events) >= limit:
            retry_after = max(1, int(60 - (now - events[0])))
            return False, retry_after
        events.append(now)
        return True, 0

NO_UI = """<!doctype html>
<html><head><meta charset="utf-8"><title>Decision Triage API</title>
<style>body{font-family:system-ui,sans-serif;background:#0b1020;color:#e8ecf8;padding:40px;line-height:1.6}
code{background:#18213a;padding:2px 6px;border-radius:5px}pre{background:#111a30;padding:16px;border-radius:10px;overflow:auto}</style>
</head><body>
<h1>API is running</h1>
<p>The React UI is not built yet. Either build it:</p>
<pre>cd web
npm install
npm run build</pre>
<p>or run the Vite dev server in another terminal:</p>
<pre>cd web
npm run dev</pre>
<p>API: <code>GET /api/config</code>, <code>POST /api/decide</code>, <code>GET /api/health</code></p>
</body></html>
"""


def safe_file(dist: Path, relative: str) -> Path | None:
    try:
        candidate = (dist / relative.lstrip("/")).resolve()
        candidate.relative_to(dist.resolve())
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


EXPLICIT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


def content_type(path: Path) -> str:
    explicit = EXPLICIT_TYPES.get(path.suffix.lower())
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def make_handler(client, serve_spa: bool):
    mock = isinstance(client, MockDecisionClient)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DecisionTriage/1.1"

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write(f"[web] {self.address_string()} {fmt % args}\n")

        def _cors_headers(self) -> dict[str, str]:
            allowed = getattr(self.server, "cors_origins", [])
            origin = self.headers.get("Origin")
            if not allowed or not origin:
                return {}
            if "*" in allowed:
                return {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                }
            if origin in allowed:
                return {
                    "Access-Control-Allow-Origin": origin,
                    "Vary": "Origin",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                }
            return {}

        def _send(self, status: int, body: bytes | str, content_type_value: str, extra: dict[str, str] | None = None) -> None:
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type_value)
            self.send_header("Content-Length", str(len(data)))
            headers = {"Cache-Control": "no-store"}
            headers.update(self._cors_headers())
            if extra:
                headers.update(extra)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, payload: dict, extra: dict[str, str] | None = None) -> None:
            self._send(status, json.dumps(payload), "application/json; charset=utf-8", extra)

        def _send_file(self, path: Path) -> None:
            data = path.read_bytes()
            cache = "public, max-age=31536000, immutable" if "assets" in path.parts else "no-store"
            self._send(200, data, content_type(path), {"Cache-Control": cache})

        def do_OPTIONS(self) -> None:
            self._send(204, b"", "text/plain; charset=utf-8")

        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/api/health":
                self._json(200, {"ok": True, "mock": mock, "deployment": client.deployment})
                return
            if path == "/api/config":
                self._json(
                    200,
                    {
                        "mock": mock,
                        "deployment": client.deployment,
                        "samples": SAMPLE_TICKETS,
                        "questions": QUESTIONS,
                        "policy": POLICY,
                    },
                )
                return
            if path.startswith("/api/"):
                self._json(404, {"ok": False, "error": "Not found"})
                return

            if not serve_spa:
                self._json(404, {"ok": False, "error": "UI disabled (--api-only). API lives under /api/."})
                return

            if not WEB_DIST.is_dir():
                self._send(200, NO_UI, "text/html; charset=utf-8")
                return

            relative = "index.html" if path == "/" else path
            file = safe_file(WEB_DIST, relative)
            if file is not None:
                self._send_file(file)
                return

            if "." not in Path(path).name:
                index = WEB_DIST / "index.html"
                if index.is_file():
                    self._send_file(index)
                    return

            self._json(404, {"ok": False, "error": "Not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/decide":
                self._json(404, {"ok": False, "error": "Not found"})
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 200_000:
                self._json(413, {"ok": False, "error": "Request body is missing or too large."})
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json(400, {"ok": False, "error": "Body must be valid JSON."})
                return

            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                self._json(400, {"ok": False, "error": "Field 'text' must be a non-empty string."})
                return
            if len(text) > 8000:
                self._json(400, {"ok": False, "error": "Keep the ticket under 8000 characters."})
                return

            allowed, retry_after = allow_request(
                self.client_address[0], getattr(self.server, "rate_limit", 0)
            )
            if not allowed:
                self._json(
                    429,
                    {
                        "ok": False,
                        "error": f"Rate limit reached. Try again in {retry_after} seconds.",
                    },
                    {"Retry-After": str(retry_after)},
                )
                return

            try:
                decision = client.ask(text, QUESTIONS)
                assessment = evaluate(decision, text)
            except DecisionAPIError as exc:
                self._json(502, {"ok": False, "error": str(exc), "status": exc.status})
                return
            except Exception as exc:
                self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                return

            self._json(200, {"ok": True, "result": assessment, "raw": decision.raw})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Decision Triage API and React UI.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--mock", action="store_true", help="Use the offline deterministic stub.")
    parser.add_argument("--api-only", action="store_true", help="Do not serve the built UI.")
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=int(os.environ.get("RATE_LIMIT_PER_MIN", "20")),
        help="Decisions allowed per IP per minute. 0 disables the limit.",
    )
    args = parser.parse_args()

    try:
        client = build_client(mock=args.mock)
    except DecisionAPIError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    origins = [item.strip() for item in os.environ.get("CORS_ORIGINS", "").split(",") if item.strip()]
    server = ThreadingHTTPServer((args.host, args.port), make_handler(client, not args.api_only))
    server.cors_origins = origins
    server.rate_limit = args.rate_limit

    mode = "mock" if isinstance(client, MockDecisionClient) else "live"
    ui = "ui" if (not args.api_only and WEB_DIST.is_dir()) else "api-only"
    print(f"Decision Triage on http://{args.host}:{args.port}  ({mode} mode, {ui})")
    print(
        f"Deployment: {client.deployment}   rate limit: "
        f"{args.rate_limit if args.rate_limit > 0 else 'off'}/min per IP   Ctrl+C to stop"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
