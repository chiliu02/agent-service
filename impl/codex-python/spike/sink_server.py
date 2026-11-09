"""A model endpoint that records the request and answers 401. Forwards nothing.

**Free by construction** (CX-20): no byte reaches OpenAI, so no turn is billed
and a dummy key is enough. It exists to answer one question the app-server
cannot be asked directly -- what, if anything, does the agent send that a gateway
could join to a session?

Every captured request is printed as one JSON line on stdout, which is how the
driver reads it back: `docker compose logs` is already a channel out of the
stack, so the sink needs no API of its own.

Runs in the compose stack as its own service, on 8080, reachable only over the
compose network.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARKER = "SINK-CAPTURE "


class _Sink(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        print(
            MARKER
            + json.dumps(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body_bytes": len(body),
                }
            ),
            flush=True,
        )
        payload = json.dumps(
            {"error": {"message": "sink", "type": "invalid_request_error"}}
        ).encode()
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.close_connection = True
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _record

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("0.0.0.0", port), _Sink)  # noqa: S104
    print(f"sink listening on 0.0.0.0:{port}", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()
