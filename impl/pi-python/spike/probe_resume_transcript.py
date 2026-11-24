"""Does a turn on a resumed session append to the copied file? (PI-72)

**Why this exists.** `transcript_path` on a resumed session names its own copy
of the source session's file. `PI-72` verified the copy and inferred the rest:
that a turn taken after the resume appends to that copy rather than starting
another file. This probe measures it with the real agent, through the service.

**Free.** The provider gateway points `anthropic` at a local server that answers
every Messages call with a minimal, well-formed stream ("ok"), so each turn
completes, no byte leaves the machine, and the key is a dummy.

**What it checks:**

1. Turn 1 on session A writes one file, and `transcript_path` names it.
2. After A is deleted and B is opened with `options.resume`, B reports its own
   copy before its first turn, and the copy equals A's file.
3. Two turns on B append to that copy: the old lines are kept as they were, new
   lines follow, the path does not change, and B's directory holds one file.

**Run it** from `impl/pi-python`, after `npm install` in `spike/`:

    uv run python spike/probe_resume_transcript.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL = "anthropic/claude-haiku-4-5"


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class _Answer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        usage = {"input_tokens": 5, "output_tokens": 1}
        body = b"".join([
            _sse("message_start", {"type": "message_start", "message": {
                "id": f"msg_{uuid.uuid4().hex}", "type": "message",
                "role": "assistant", "model": MODEL.split("/", 1)[1],
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": usage}}),
            _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
            _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "ok"}}),
            _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
            _sse("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                   "usage": {"output_tokens": 1}}),
            _sse("message_stop", {"type": "message_stop"}),
        ])
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    from fastapi.testclient import TestClient

    from agent_service.api import create_app
    from agent_service.config import Settings

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    os.environ["ANTHROPIC_API_KEY"] = "dummy-not-a-key"

    bin_dir = Path(__file__).parent / "node_modules" / ".bin"
    pi = bin_dir / ("pi.cmd" if os.name == "nt" else "pi")
    root = Path(tempfile.mkdtemp(prefix="pi-resume-transcript-"))
    (root / "workspace").mkdir()
    store = root / "sessions"
    settings = Settings(
        workspace_dir=root / "workspace",
        agent_dir_root=root / "agent-dirs",
        session_store=store,
        pi_binary=pi,
        require_credentials=False,
        model=MODEL,
        turn_timeout_s=60,
        provider_gateways={"anthropic": {"base_url": base, "headers": {}}},
    )
    print(f"gateway: {base}")
    print(f"store:   {store}")
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    with TestClient(create_app(settings)) as client:
        a = client.post("/v1/sessions", json={"title": "source"}).json()["session_id"]
        t1 = client.post(f"/v1/sessions/{a}/messages", json={"prompt": "turn one"})
        if t1.status_code != 200:
            print(f"FAILED turn 1: {t1.status_code} {t1.text[:400]}")
            return 1
        issued = t1.json()["sdk_session_id"]
        p_a = t1.json()["transcript_path"]
        print(f"turn 1 on A: result={t1.json()['result']!r} id={issued} path={p_a}")
        file_a = store / p_a
        a_after_turn1 = _lines(file_a)
        print(f"  A's file: {len(a_after_turn1)} lines")

        client.delete(f"/v1/sessions/{a}")
        a_on_disk = file_a.exists()
        print(f"deleted A; its file still on disk: {a_on_disk}")

        opened = client.post("/v1/sessions",
                             json={"title": "resumed", "options": {"resume": issued}})
        if opened.status_code != 201:
            print(f"FAILED to resume: {opened.status_code} {opened.text[:400]}")
            return 1
        b = opened.json()["session_id"]
        p_b0 = opened.json()["transcript_path"]
        print(f"opened B with resume: path before a turn={p_b0}")
        file_b = store / p_b0
        copy = _lines(file_b)
        check("B's copy equals A's file after turn 1", copy == a_after_turn1)

        previous = copy
        for n in (2, 3):
            t = client.post(f"/v1/sessions/{b}/messages", json={"prompt": f"turn {n}"})
            if t.status_code != 200:
                print(f"FAILED turn {n}: {t.status_code} {t.text[:400]}")
                return 1
            path = t.json()["transcript_path"]
            now = _lines(file_b)
            files = sorted(p.name for p in file_b.parent.glob("*.jsonl"))
            print(f"turn {n} on B: result={t.json()['result']!r} "
                  f"id={t.json()['sdk_session_id']} path={path}")
            print(f"  B's file: {len(previous)} -> {len(now)} lines; "
                  f"jsonl files in B's dir: {files}")
            check(f"turn {n}: path unchanged", path == p_b0)
            check(f"turn {n}: earlier lines kept as they were",
                  now[:len(previous)] == previous)
            check(f"turn {n}: new lines appended", len(now) > len(previous))
            check(f"turn {n}: one jsonl file in B's directory", len(files) == 1)
            check(f"turn {n}: the prompt is in the file",
                  any(f"turn {n}" in line for line in now[len(previous):]))
            previous = now

        if a_on_disk:
            check("A's file unchanged by B's turns", _lines(file_a) == a_after_turn1)

    server.shutdown()
    print("RESULT:", "all checks passed" if ok else "a check FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
