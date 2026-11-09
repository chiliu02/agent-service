"""Do the PER-PROVIDER base-URL variables redirect this agent, and what happens
to a provider that has none?

**Agent Harness asked for exactly this and was right to.** The `endpoint_source`
this build publishes was measured as a proxy: `HTTPS_PROXY` produces a real
`CONNECT`. What was never measured is whether `ANTHROPIC_BASE_URL` and its
siblings redirect anything -- and a separate measurement showed only that a
qualified model billed the right vendor, which is a different claim. Their gateway
cannot sit behind a `CONNECT` tunnel (it swaps the credential and counts tokens,
and it can do neither through ciphertext), so the per-provider set is the whole
question.

Two questions, and the second is the one with teeth:

1. **Does `<VENDOR>_BASE_URL` move that vendor's traffic?** A sink on this
   machine records what arrives.
2. **What does a provider with NO override do?** If it silently reaches the
   vendor directly, a gateway holding credentials for three providers out of
   thirty has thirty-odd holes rather than three doors.

    uv run --no-project python probe_pi_endpoints_live.py <path-to-pi>

**Cost: about nothing, and never nothing by accident.** Every redirected run
dies at the sink's `401` before a token is billed. The one run that may reach a
real vendor (question 2) carries a deliberately invalid key, so it dies at that
vendor's own `401` -- which is the observation, not a side effect.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: Every `*_BASE_URL` name found in the shipped bundle, and the provider each
#: belongs to. Read out of the package rather than guessed -- but a name in a
#: bundle is not a redirect, which is what this file exists to settle.
CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("anthropic", "ANTHROPIC_BASE_URL", "anthropic/claude-haiku-4-5"),
    ("openai", "OPENAI_BASE_URL", "openai/gpt-5-nano"),
    ("google", "GOOGLE_GEMINI_BASE_URL", "google/gemini-3.1-flash-lite"),
)

#: A syntactically plausible key for each, so the client does not refuse before
#: making a request -- which would pass this probe for the wrong reason.
DUMMY = {
    "ANTHROPIC_API_KEY": "sk-ant-probe-not-a-real-key",
    "OPENAI_API_KEY": "sk-probe-not-a-real-key",
    "GEMINI_API_KEY": "AIzaSyProbeProbeProbeProbeProbeProbeProbe",
}


class _Sink(BaseHTTPRequestHandler):
    """Records `HOST + path` and answers 401. Forwards nothing, ever."""

    protocol_version = "HTTP/1.1"
    seen: list[str] = []

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen.append(f"{self.headers.get('host', '?')}{self.path}")
        body = b'{"error":{"code":401,"message":"probe sink"}}'
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_PUT = do_POST = _record

    def do_CONNECT(self) -> None:  # noqa: N802 - the base class's spelling
        """A proxy's opening verb. Recorded so the two shapes stay separable."""
        type(self).seen.append(f"CONNECT {self.path}")
        self.send_response(502)
        self.send_header("content-length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        """Silence."""


def _run(pi: str, env_extra: dict[str, str], model: str, cwd: Path) -> tuple[int, str]:
    env = {
        "PATH": os.environ["PATH"],
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PI_CODING_AGENT_DIR": str(cwd / "endpoint-probe-home"),
        "PI_SKIP_VERSION_CHECK": "1",
        **DUMMY,
        **env_extra,
    }
    proc = subprocess.run(
        [pi, "--mode", "json", "--model", model, "--no-tools",
         "--no-skills", "--no-extensions", "--no-context-files", "-p", "hi"],
        capture_output=True, text=True, env=env, timeout=180,
        stdin=subprocess.DEVNULL,
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    line = next((ln for ln in reversed(text.strip().splitlines()) if ln.strip()), "")
    return proc.returncode, line[:200]


def main() -> int:
    pi = sys.argv[1]
    cwd = Path.cwd()
    sink = ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    port = sink.server_address[1]
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    print(f"sink: {base}\n")
    print("=== 1. does <VENDOR>_BASE_URL redirect that vendor? ===")
    for provider, variable, model in CANDIDATES:
        _Sink.seen.clear()
        code, said = _run(pi, {variable: base}, model, cwd)
        arrived = list(_Sink.seen)
        verdict = "REDIRECTED" if arrived else "NOT redirected"
        print(f"  {variable:<26} {verdict:<15} exit {code}")
        print(f"    reached: {arrived[:2] or 'nothing'}")
        print(f"    agent  : {said}")

    print("\n=== 2. a provider with NO override: does it leave? ===")
    # anthropic redirected at the sink, and openai deliberately not configured.
    # If nothing reaches the sink and the agent reports a vendor-shaped refusal,
    # the request went straight out -- which is what Harness must not have.
    _Sink.seen.clear()
    code, said = _run(pi, {"ANTHROPIC_BASE_URL": base}, "openai/gpt-5-nano", cwd)
    print(f"  unconfigured provider exit {code}")
    print(f"    reached sink: {list(_Sink.seen) or 'nothing'}")
    print(f"    agent       : {said}")
    print("    (a vendor-shaped 401 with an empty sink means it reached the "
          "vendor directly)")

    print("\n=== 3. does the proxy still cover what a base URL does not? ===")
    _Sink.seen.clear()
    code, said = _run(pi, {"HTTPS_PROXY": base, "HTTP_PROXY": base},
                      "openai/gpt-5-nano", cwd)
    print(f"  HTTPS_PROXY only, unconfigured provider: exit {code}")
    print(f"    reached: {list(_Sink.seen)[:2] or 'nothing'}")
    print(f"    agent  : {said}")

    sink.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
