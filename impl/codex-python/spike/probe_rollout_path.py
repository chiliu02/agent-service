"""Which file holds a thread's conversation, and does a resume keep writing to it? (CX-75)

**Why this exists.** Agent Harness lets a user download one conversation's
transcript and needs the service to name the file. Codex writes a thread's
rollout under `CODEX_HOME/sessions`, in a name that carries a timestamp, so the
file cannot be derived from the thread id. This probe answers three things:

1. Where the rollout is after the first turn, and whether the app-server's
   `Thread.path` (marked UNSTABLE in the generated schema) names it.
2. Whether a thread that has taken no turn has a rollout on disk.
3. Whether a turn taken after `thread/resume`, in a second app-server process,
   is appended to the SAME file, or starts a new one.

**Free.** The model endpoint is a local server that answers every `/responses`
call with a minimal, well-formed Responses stream ("ok"), so each turn
completes, no byte leaves the machine, and the key is a dummy.

**Run it** from `impl/codex-python`:

    uv run python spike/probe_rollout_path.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_spec.openapi.schemas import RunOptions

from agent_service.sessions import CodexSession


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class _Answer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        rid = f"resp_{uuid.uuid4().hex}"
        mid = f"msg_{uuid.uuid4().hex}"
        item = {
            "type": "message",
            "id": mid,
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        }
        body = b"".join(
            [
                _sse("response.created", {"type": "response.created", "response": {"id": rid}}),
                _sse("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
                _sse(
                    "response.completed",
                    {
                        "type": "response.completed",
                        "response": {
                            "id": rid,
                            "usage": {
                                "input_tokens": 10,
                                "input_tokens_details": {"cached_tokens": 0},
                                "output_tokens": 1,
                                "output_tokens_details": {"reasoning_tokens": 0},
                                "total_tokens": 11,
                            },
                        },
                    },
                ),
            ]
        )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


def _rollouts(home: Path) -> list[str]:
    return sorted(p.relative_to(home).as_posix() for p in home.glob("sessions/**/rollout-*.jsonl"))


def _turns_in(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        p = rec.get("payload") or {}
        if rec.get("type") == "event_msg" and p.get("type") == "task_started":
            out.append(p.get("turn_id"))
    return out


async def _path_of(s: CodexSession) -> str | None:
    read = await s._thread.read()
    return read.thread.path


async def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    root = Path(tempfile.mkdtemp(prefix="cx-rollout-")).resolve()
    home, ws = root / "home", root / "ws"
    print(f"CODEX_HOME={home}")
    try:
        s = CodexSession(cwd=str(ws), codex_home=str(home), api_key="sk-dummy", base_url=url)
        await s.open(RunOptions())
        tid = s.sdk_session_id
        print(f"\nprocess 1: thread {tid}")
        print(f"  before any turn: files={_rollouts(home)} Thread.path={await _path_of(s)!r}")
        out = await s.send("say ok", RunOptions(), timeout_s=60)
        print(f"  turn 1 status={out.status}")
        print(f"  after turn 1:    files={_rollouts(home)} Thread.path={await _path_of(s)!r}")
        await s.close()

        r = CodexSession(cwd=str(ws), codex_home=str(home), api_key="sk-dummy", base_url=url)
        await r.open(RunOptions(), resume=tid)
        print(f"\nprocess 2: resumed {r.sdk_session_id}")
        print(f"  after resume:    files={_rollouts(home)} Thread.path={await _path_of(r)!r}")
        out = await r.send("say ok again", RunOptions(), timeout_s=60)
        print(f"  turn 2 status={out.status}")
        print(f"  after turn 2:    files={_rollouts(home)} Thread.path={await _path_of(r)!r}")
        await r.close()

        for rel in _rollouts(home):
            print(f"\n  {rel}: task_started turn ids {_turns_in(home / rel)}")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
