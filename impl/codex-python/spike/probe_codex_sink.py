"""Does any header the Codex agent sends EQUAL the `sdk_session_id` we report?

**The equality is the whole claim** (CX-20). A header carrying some id is useless
to a gateway unless it is the same string this service reports, and a header name
read off a different front end is an inference rather than a measurement -- which
is the one thing `llm_correlation` exists not to be.

**Free.** The sink answers 401 and forwards nothing, so no turn is billed and the
dummy key in the overlay is enough. What costs time is the image build.

    uv run --no-project python spike/probe_codex_sink.py

Run it from THIS directory: compose resolves the overlay's relative mount
against the project directory, and the driver addresses `compose.yaml` the same
way `.ci/ci.py` does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PROJECT = "codex-sink-probe"
PORT = int(os.environ.get("SINK_HOST_PORT", "8130"))
BASE = f"http://127.0.0.1:{PORT}"
MARKER = "SINK-CAPTURE "

COMPOSE = [
    "docker", "compose",
    "-f", "compose.yaml",
    "-f", "spike/compose.sink.yaml",
    "-p", PROJECT,
]


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run([*COMPOSE, *args], cwd=HERE, capture_output=True, text=True)
    if check and proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"compose {args[0]} failed ({proc.returncode})")
    return proc


def api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310
        BASE + path, data=data, method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_for_health(seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            status, _ = api("GET", "/healthz")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(2)
    raise SystemExit("the service never became healthy; try `docker compose logs`")


def captures() -> list[dict]:
    """Every request the agent made, read back out of the sink's stdout."""
    logs = compose("logs", "--no-log-prefix", "sink").stdout
    return [
        json.loads(line.split(MARKER, 1)[1])
        for line in logs.splitlines()
        if MARKER in line
    ]


def main() -> int:
    # A real directory, because the workspace mount is a boot gate and compose
    # silently CREATES a missing host path on some platforms rather than failing.
    #
    # Passed through this process's environment rather than through a file:
    # compose reads `.env` beside `compose.yaml` and nothing else, and writing
    # THAT would overwrite a developer's own.
    workspace = Path(tempfile.mkdtemp(prefix="codex-sink-ws-"))
    os.environ["WORKSPACE_HOST_PATH"] = str(workspace)
    print(f"workspace: {workspace}")

    try:
        print("building and starting the stack ...")
        compose("up", "-d", "--build")
        wait_for_health()

        status, created = api("POST", "/v1/sessions", {})
        print(f"POST /v1/sessions -> {status}")
        if status != 201:
            print(json.dumps(created, indent=2)[:1200])
            return 1
        session_id = created["session_id"]
        sdk_session_id = created.get("sdk_session_id")
        print(f"session_id     = {session_id}")
        print(f"sdk_session_id = {sdk_session_id!r}")

        status, turn = api(
            "POST", f"/v1/sessions/{session_id}/messages", {"prompt": "say hi"}
        )
        print(f"turn -> {status}")
        print(json.dumps(turn, indent=2)[:900])

        captured = captures()
        print(f"\n=== {len(captured)} request(s) reached the sink ===")
        if not captured:
            print("NOTHING ARRIVED. Either the endpoint override did not take "
                  "effect or the app-server failed before its first model call.")
            return 1

        first = captured[0]
        print(f"{first['method']} {first['path']}")
        print(json.dumps(first["headers"], indent=2))

        print("\n=== headers whose value EQUALS sdk_session_id ===")
        exact = [k for k, v in first["headers"].items() if v == sdk_session_id]
        print(exact or "NONE")
        print("\n=== headers CONTAINING it (a metadata blob counts here) ===")
        loose = [
            k for k, v in first["headers"].items()
            if sdk_session_id and sdk_session_id in v and k not in exact
        ]
        print(loose or "NONE")
        return 0
    finally:
        print("\ntearing the stack down ...")
        compose("down", "-v", check=False)


if __name__ == "__main__":
    raise SystemExit(main())
