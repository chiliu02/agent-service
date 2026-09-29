"""Serve console.html and proxy the API through one origin. Dev only.

Why this exists rather than a CORS middleware: the service has no auth and the
agent's `Bash` tool is unconfined (see the README's opening warning), so adding
`allow_origins=["*"]` to it would widen a security surface for the sake of a
development page. A proxy keeps the service exactly as it is -- nothing under
`src/` changes -- and the browser sees a single origin, which is all it wanted.

    python impl/common/web/serve.py           # proxies to http://127.0.0.1:8000
    python impl/common/web/serve.py --target http://127.0.0.1:8001 --port 8080

Binds 127.0.0.1 only. Streaming responses (SSE) are forwarded chunk by chunk
with `read1`, which returns as soon as bytes are available -- a plain `read(n)`
would block until the buffer filled and turn a live stream into a stalled one.
Standard library only; no dependency on the service's own environment.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "console.html"

# Hop-by-hop headers, plus the two whose framing this proxy decides itself.
_SKIP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "content-encoding",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    target = "http://127.0.0.1:8000"

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- routing ----------------------------------------------------------
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html", "/console.html"):
            return self._serve_page()
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")

    def do_PATCH(self) -> None:
        self._proxy("PATCH")

    def do_PUT(self) -> None:
        self._proxy("PUT")

    def do_DELETE(self) -> None:
        self._proxy("DELETE")

    def do_HEAD(self) -> None:
        self._proxy("HEAD")

    # -- the page ---------------------------------------------------------
    def _serve_page(self) -> None:
        try:
            body = PAGE.read_bytes()
        except OSError as exc:
            return self._fail(500, f"cannot read {PAGE}: {exc}")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- the proxy --------------------------------------------------------
    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(self.target.rstrip("/") + self.path, data=body, method=method)
        for key, value in self.headers.items():
            if key.lower() in _SKIP or key.lower() == "host":
                continue
            req.add_header(key, value)

        try:
            # No timeout: a streaming turn legitimately stays open for minutes,
            # and the service already bounds every turn with its own timeout_s.
            upstream = urllib.request.urlopen(req, timeout=None)
        except urllib.error.HTTPError as exc:
            upstream = exc  # 4xx/5xx still carry a body worth forwarding
        except urllib.error.URLError as exc:
            return self._fail(
                502,
                # Deliberately names no implementation. This proxy speaks /v1
                # and nothing else, so it serves any conforming build -- naming
                # `agent_service.main:app` here, as it did while it lived under
                # impl/claude-python/, would send a Codex or Gemini user to
                # start the wrong thing.
                f"cannot reach {self.target} ({exc.reason}). "
                "Is a conforming agent-service running there? Start one from "
                "its own implementation directory under impl/.",
            )

        with upstream:
            declared = upstream.headers.get("Content-Length")
            streaming = declared is None

            self.send_response(upstream.status)
            for key, value in upstream.headers.items():
                if key.lower() not in _SKIP:
                    self.send_header(key, value)
            if streaming:
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("X-Accel-Buffering", "no")
            else:
                self.send_header("Content-Length", declared)
            self.end_headers()

            if method == "HEAD":
                return
            try:
                if streaming:
                    self._pump_chunked(upstream)
                else:
                    remaining = int(declared)
                    while remaining > 0:
                        chunk = upstream.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # The browser hung up mid-stream. That is a normal thing for a
                # console to do -- it is how the service's own disconnect path
                # gets exercised -- so it is not an error here.
                pass

    def _pump_chunked(self, upstream) -> None:
        while True:
            # read1: return what is available now. read() would wait for a full
            # buffer and stall every SSE frame behind the next one.
            chunk = upstream.read1(65536)
            if not chunk:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _fail(self, status: int, message: str) -> None:
        body = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", default="http://127.0.0.1:8000", help="the agent-service base URL")
    ap.add_argument("--port", type=int, default=8080, help="port to serve the console on")
    args = ap.parse_args()

    if not PAGE.exists():
        print(f"console.html not found next to this script ({PAGE})", file=sys.stderr)
        return 1

    Handler.target = args.target
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"console  http://127.0.0.1:{args.port}/")
    print(f"proxying -> {args.target}")
    print("Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
