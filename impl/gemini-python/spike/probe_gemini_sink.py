"""What does the agent send to the MODEL, and does the endpoint variable work?

**FREE, and that is the point of the sink** (GP-53). A forwarding proxy answers
the same questions and spends real money doing it; this one answers `401` and
never opens a socket to Google. A dummy key is enough -- the sink refuses before
the model is ever consulted, so no turn is billed and no credential is needed.

Three questions, one captured request:

1. **Does `GOOGLE_GEMINI_BASE_URL` actually redirect?** GP-42 read the name out
   of the bundle and said plainly that the redirect itself was unmeasured.
2. **Which header carries the key?** Getting this wrong fails in a way that
   names neither the endpoint nor the credential.
3. **Does any header carry the session id?** This is what a gateway needs to
   attribute model spend to a session, and it is published as
   `llm_correlation`.

Two things are required or the CLI ends before making a request, and neither is
obvious:

* `security.auth.selectedType` must be `gemini-api-key` in the HOME settings
  file. `GEMINI_API_KEY` alone leaves the CLI at exit `41`, *Invalid auth method
  selected*, with nothing attempted.
* `GEMINI_CLI_TRUST_WORKSPACE=true`, for GP-08's reason.

    uv run --no-project python spike/probe_gemini_sink.py <path-to-gemini.js>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CAPTURED: list[dict] = []
LOCK = threading.Lock()


class _Sink(BaseHTTPRequestHandler):
    """Records the request and answers a plausible 401. Forwards nothing."""

    protocol_version = "HTTP/1.1"

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        with LOCK:
            CAPTURED.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body_bytes": len(body),
                }
            )
        # The agent's own error shape, so it gives up at once instead of
        # retrying against something that never answers.
        payload = json.dumps(
            {"error": {"code": 401, "message": "sink", "status": "UNAUTHENTICATED"}}
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


def main(bundle: Path) -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"sink listening on {base}")

    home = Path(tempfile.mkdtemp(prefix="gemini-sink-home-"))
    workspace = tempfile.mkdtemp(prefix="gemini-sink-ws-")
    settings = home / ".gemini"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "settings.json").write_text(
        json.dumps({"security": {"auth": {"selectedType": "gemini-api-key"}}}),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "GEMINI_API_KEY": "sink-dummy-key-not-a-credential",
        "GOOGLE_GEMINI_BASE_URL": base,
        "GEMINI_CLI_TRUST_WORKSPACE": "true",
    }
    env.pop("GOOGLE_API_KEY", None)

    # Pinned and capped for the reason every live probe here is (GP-18, GP-32),
    # even though this one cannot reach a model: a turn that will not terminate
    # is the expensive failure, and the habit is worth keeping.
    argv = ["node", str(bundle), "-p", "say hi", "-o", "stream-json",
            "-m", "gemini-3.1-flash-lite"]
    try:
        proc = subprocess.run(argv, env=env, cwd=workspace, capture_output=True,
                              text=True, timeout=90)
        print(f"exit={proc.returncode}")
        print(proc.stdout[:1200])
    except subprocess.TimeoutExpired:
        print("TIMEOUT -- the sink answered but the agent did not end")

    server.shutdown()
    print(f"\n=== {len(CAPTURED)} request(s) reached the sink ===")
    print(json.dumps(CAPTURED, indent=2)[:4000])
    if not CAPTURED:
        print("\nNOTHING ARRIVED: the endpoint variable did not redirect, or "
              "the agent never got as far as a model call. Read the exit code.")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
