"""A stand-in for `gemini -p … -o stream-json`, so the runner is testable free.

**Faithful to what was measured, and no further.** Every shape below comes from
a real turn (GP-15, GP-06, GP-09, GP-16): `message` events carry `delta`, `init`
reports the model as the literal string `auto`, `tool_result` carries an empty
or absent `output`, and a failing run puts its envelope on **stderr** while a
successful one puts it on stdout.

**Driven by the prompt text**, so one file covers the cases that matter:

| prompt contains | what this does |
|---|---|
| `exit:<n>` | exits `<n>` with a JSON envelope on stderr, as the agent does |
| `plain:<n>` | exits `<n>` with PLAIN TEXT on stderr -- the `--sandbox` shape |
| `tools` | emits a tool_use/tool_result pair with an empty output |
| `hang` | never exits, so the caller's timeout is the only way out |
| anything else | init, two message deltas, and a result with per-model stats |

It also writes a transcript where the agent would (`$HOME/.gemini/tmp/<cwd
basename>/chats/`), because the runner's job includes finding and copying it
before the agent's own cleanup can (GP-10, GP-39).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

SESSION = "11111111-2222-3333-4444-555555555555"


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")


def write_transcript(session_id: str) -> None:
    """Where the real agent puts it -- under HOME, keyed by the cwd's basename."""
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    chats = home / ".gemini" / "tmp" / Path.cwd().name.lower() / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M")
    path = chats / f"session-{stamp}-{session_id[:8]}.jsonl"
    path.write_text(
        json.dumps({"sessionId": session_id, "kind": "main"}) + "\n"
        + json.dumps({"$set": {"messages": [{"type": "user", "content": "hi"}]}}) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-p", "--prompt", default="")
    parser.add_argument("-o", "--output-format", default="json")
    parser.add_argument("-m", "--model", default=None)
    parser.add_argument("--approval-mode", default="default")
    parser.add_argument("--admin-policy", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--session-file", default=None)
    args, _unknown = parser.parse_known_args()
    prompt = args.prompt

    if "hang" in prompt:
        while True:  # the caller's timeout is the only exit (GP-18)
            time.sleep(1)

    if prompt.startswith("plain:"):
        # The `--sandbox` shape: NOT a JSON envelope, just a line of text (GP-09).
        code = int(prompt.split(":", 1)[1])
        sys.stderr.write("GEMINI_SANDBOX is true but failed to determine command\n")
        return code

    if prompt.startswith("exit:"):
        code = int(prompt.split(":", 1)[1])
        # A failed run: stdout EMPTY, the whole envelope on stderr (GP-09).
        sys.stderr.write(json.dumps({
            "session_id": SESSION,
            "error": {"type": "Error", "message": f"fake failure {code}", "code": code},
        }))
        return code

    # **A resumed turn mints a NEW id** (GP-11); a supplied one is honoured.
    session_id = args.session_id or (str(uuid.uuid4()) if args.session_file else SESSION)

    emit({"type": "init", "timestamp": "t", "session_id": session_id, "model": "auto"})
    emit({"type": "message", "timestamp": "t", "role": "user", "content": prompt})

    if "tools" in prompt:
        emit({"type": "tool_use", "timestamp": "t", "tool_name": "read_file",
              "tool_id": "read_file__x1", "parameters": {"file_path": "seed.txt"}})
        # Empty on purpose: this is what every work tool returns (GP-17, GP-40).
        emit({"type": "tool_result", "timestamp": "t", "tool_id": "read_file__x1",
              "status": "success", "output": ""})

    emit({"type": "message", "timestamp": "t", "role": "assistant",
          "content": "hello ", "delta": True})
    emit({"type": "message", "timestamp": "t", "role": "assistant",
          "content": "world", "delta": True})
    # **The counts are the ones a real turn emitted** (GP-60), not a plausible
    # block: this stats shape carried only `total_tokens` until 2026-08-15, and
    # a fake that reports no per-direction counts is a fake against which an
    # unmapped `token_usage` looks correct.
    emit({"type": "result", "timestamp": "t", "status": "success", "stats": {
        "total_tokens": 11911, "input_tokens": 11251, "output_tokens": 39,
        "cached": 8103, "input": 3148, "duration_ms": 10, "tool_calls": 1,
        # Two models on one turn, which is what `auto` bills (GP-16).
        "models": {
            "gemini-3.5-flash": {"total_tokens": 10877, "input_tokens": 10637,
                                 "output_tokens": 3, "cached": 8103, "input": 2534},
            "gemini-3.1-flash-lite": {"total_tokens": 1034, "input_tokens": 614,
                                      "output_tokens": 36, "cached": 0, "input": 614},
        },
    }})
    write_transcript(session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
