"""A streamable-HTTP MCP server whose tools are slow in three different ways.

**Written to settle one question**: when an MCP tool call on this build dies at
~60 s, is the bound the agent's or is it something in the path? A consumer
measured the failure on 2026-08-18 and their control could not separate a
client-side "response must begin" timer from an intermediary enforcing
time-to-first-byte, because both predict exactly the same four rows.

**Three tools rather than one with a flag**, which is the consumer's own design
and the right one: given a flag, the model sets it itself and answers a
different question.

| Tool | What the SERVER does while working |
| --- | --- |
| `quick` | answers at once. Proves the wiring, costs one cheap turn |
| `slowsilent` | **sends nothing at all** -- no headers, no bytes -- then one JSON body after the delay |
| `slowstream` | **SSE headers at once**, comment frames every 10 s, the result at the delay |

`slowsilent` versus `slowstream` is the whole experiment. A timer that is
satisfied by *responding* kills the first and spares the second; so does a
first-byte timeout in a proxy. What separates them is not the rows -- it is
whether a proxy is in the path at all, and this image sets none of
`HTTP_PROXY`, `HTTPS_PROXY` or `NO_PROXY`.

**Dependency-free on purpose**, like the stdio server beside it: the fixed point
of an experiment should not have moving parts.

    MCP_DELAY_S=90 uv run --no-project python spike/mcp_http_delay_server.py 9010

**It binds 0.0.0.0**, because the client is inside a container reaching back out
through `host.docker.internal`. Nothing it serves is secret and it exits with
the probe.
"""

from __future__ import annotations

import json
import os
import select
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: How long the two slow tools take to produce an answer. 90 s is the
#: consumer's figure: comfortably past the ~60 s that killed their silent row
#: and comfortably inside the 600 s this build publishes as its total bound.
DELAY_S = float(os.environ.get("MCP_DELAY_S", "90"))

#: How often `slowstream` emits an SSE comment. Comments carry no JSON-RPC, so
#: they are invisible to the MCP layer and visible only to the transport --
#: which is what makes them the right probe for a transport-level timer.
KEEPALIVE_S = 10.0

#: What only a real round trip can produce. The model cannot invent it, so an
#: answer containing it is proof the tool ran rather than proof it was asked.
MAGIC = "MAGIC-FROM-SLOW-MCP"

TOOLS = [
    {
        "name": "quick",
        "description": (
            "Returns the secret token immediately. Call this when asked for the "
            "quick token."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "slowsilent",
        "description": (
            "Returns the secret token after a long wait. Call this when asked "
            "for the silent token. It takes over a minute; wait for it."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "slowstream",
        "description": (
            "Returns the secret token after a long wait. Call this when asked "
            "for the streaming token. It takes over a minute; wait for it."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

_START = time.monotonic()


def log(message: str) -> None:
    """Timestamped from process start, because every finding here is a duration."""
    sys.stderr.write(f"[{time.monotonic() - _START:8.2f}s] {message}\n")
    sys.stderr.flush()


def _result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _text(token: str):
    return {"content": [{"type": "text", "text": token}], "isError": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # noqa: ANN002
        """Silenced: this class logs what matters itself, with durations."""

    # `GET` is the server->client stream of streamable HTTP. Nothing here ever
    # pushes, and the CLI's own transport wrapper rewrites a 404 on GET into a
    # 405 -- so either answer is understood. 405 is the honest one.
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            message = json.loads(raw or b"{}")
        except ValueError:
            self._json(400, {"error": "not json"})
            return

        method = message.get("method")
        rid = message.get("id")
        log(f"--> {method} id={rid} accept={self.headers.get('Accept')!r}")

        # A notification has no id and gets no body. 202 is what the streamable
        # HTTP transport expects.
        if rid is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            asked = (message.get("params") or {}).get("protocolVersion")
            self._json(200, _result(rid, {
                "protocolVersion": asked or "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "slow-mcp", "version": "0.0.1"},
            }))
            return

        if method == "tools/list":
            self._json(200, _result(rid, {"tools": TOOLS}))
            return

        if method == "tools/call":
            self._call(rid, (message.get("params") or {}).get("name"))
            return

        if method in ("ping", "resources/list", "prompts/list"):
            self._json(200, _result(rid, {} if method == "ping" else {method.split("/")[0]: []}))
            return

        self._json(200, {"jsonrpc": "2.0", "id": rid,
                         "error": {"code": -32601, "message": f"no method {method}"}})

    # --- the three behaviours ------------------------------------------------

    def _call(self, rid, name: str | None) -> None:
        if name == "quick":
            log("    quick: answering at once")
            self._json(200, _result(rid, _text(f"{MAGIC}-QUICK")))
            return

        if name == "slowsilent":
            # **Nothing goes on the wire until the answer does.** No status
            # line, no headers. Whatever gives up first gives up here.
            log(f"    slowsilent: sending NOTHING for {DELAY_S}s")
            # **Watch for the client giving up, because that instant IS the
            # measurement.** A blocked `sleep` would report only that the write
            # failed at the end; polling the socket for readable-with-zero-bytes
            # -- a peer that closed -- times the abort to the second.
            dropped = self._wait_watching_for_close(DELAY_S)
            if dropped is not None:
                log(f"    slowsilent: THE CLIENT GAVE UP AFTER {dropped:.1f}s")
                return
            log("    slowsilent: sending the single JSON body now")
            try:
                self._json(200, _result(rid, _text(f"{MAGIC}-SILENT")))
            except OSError as exc:
                log(f"    slowsilent: the connection was gone -- {exc!r}")
            return

        if name == "slowstream":
            self._stream(rid)
            return

        self._json(200, {"jsonrpc": "2.0", "id": rid,
                         "error": {"code": -32602, "message": f"no tool {name}"}})

    def _stream(self, rid) -> None:
        """SSE headers immediately, then comments, then the result.

        The comments are the control: they are not JSON-RPC and not progress, so
        anything that survives on them survived because the RESPONSE HAD BEGUN
        rather than because something kept telling it to wait.
        """
        log("    slowstream: SSE headers at once")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()

        waited = 0.0
        try:
            while waited < DELAY_S:
                nap = min(KEEPALIVE_S, DELAY_S - waited)
                time.sleep(nap)
                waited += nap
                if waited < DELAY_S:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    log(f"    slowstream: comment frame at {waited:.0f}s")
            body = json.dumps(_result(rid, _text(f"{MAGIC}-STREAM")))
            self.wfile.write(f"event: message\ndata: {body}\n\n".encode())
            self.wfile.flush()
            log("    slowstream: result sent")
        except OSError as exc:
            log(f"    slowstream: the connection was gone -- {exc!r}")
        self.close_connection = True

    def _wait_watching_for_close(self, seconds: float) -> float | None:
        """Sleep, and return WHEN the peer closed if it did -- else `None`.

        A socket whose peer has closed becomes readable and reads empty. The
        request body has already been consumed, so anything readable here is the
        close rather than data.
        """
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([self.connection], [], [], min(0.5, remaining))
            if not readable:
                continue
            try:
                if self.connection.recv(1, socket.MSG_PEEK) == b"":
                    return seconds - (deadline - time.monotonic())
            except OSError:
                return seconds - (deadline - time.monotonic())

    # --- plumbing ------------------------------------------------------------

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    """**`allow_reuse_address = False`, and it cost a run to learn why.**

    `ThreadingHTTPServer` sets it true. On Windows that lets a SECOND process
    bind a port a first is already listening on, and connections are then
    distributed between them unpredictably. A server left over from an earlier
    run at a different delay went on answering while the new one logged
    `listening` -- so the probe measured 8 s, reported that nothing was bounded,
    and was right about the wrong server. Refusing to start is the only outcome
    that cannot be mistaken for a result.
    """

    allow_reuse_address = False
    daemon_threads = True


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9010
    server = Server(("0.0.0.0", port), Handler)
    log(f"listening on 0.0.0.0:{port}, delay={DELAY_S}s, keepalive={KEEPALIVE_S}s")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log("stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
