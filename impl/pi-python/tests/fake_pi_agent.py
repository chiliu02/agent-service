"""A stand-in for `pi --mode json -p …`, so the runner is testable free.

**Faithful to what was measured, and no further.** Every shape below comes from a
real turn against Pi 0.85.1 (`PI-13`, `PI-15`, `PI-16`, `PI-17`, `PI-35`): the
opening `session` event carries the id, `message_update` carries an
`assistantMessageEvent` with a `text_delta`, `turn_end` carries the finished
message with its own per-call `usage.cost` in USD, and a failing run puts a plain
line on **stderr** and exits 1 -- there is no JSON error envelope on this target.

**Driven by the prompt text**, so one file covers the cases that matter:

| prompt contains | what this does |
|---|---|
| `nokey` | exits 1 with the agent's own no-credential wording on stderr |
| `nosession` | exits 1 with the agent's own unknown-session wording |
| `fail:<text>` | exits 1 with `<text>` on stderr -- an unclassified failure |
| `refused:<text>` | **exits 0** with a `turn_end` carrying `stopReason: "error"` and `<text>` as its `errorMessage` -- a turn the VENDOR refused (`PI-61`) |
| `tools` | emits a `tool_execution_start`/`_end` pair with real result text |
| `twocalls` | two `turn_end` frames, so per-turn cost SUMMING is exercised |
| `hang` | never exits, so the caller's timeout is the only way out |
| anything else | session, one text turn, `agent_end`, `agent_settled` |

**`refused:` is read from the agent's own source, not from a live refusal.**
`dist/modes/print-mode.js` checks `stopReason === "error" || "aborted"` and sets
exit 1 **inside its `mode === "text"` branch**, so under `--mode json` -- the
only mode this build uses -- the process exits 0 and the sole record of the
failure is the final message. The exact `errorMessage` text a vendor produces is
NOT measured here and nothing branches on it.

**It honours `--session` and `--session-id` the way the agent does** (`PI-14`):
a supplied id is echoed back verbatim in the opening event, and a resume reuses
the id it was given. That is the whole of what this build's continuity rests on,
so the double has to get it right or the tests prove nothing.

**It writes a session file under `--session-dir`**, because the real agent does
and because `PI-09` turns on that file staying put.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

#: The wording this build classifies on (`PI-15`). Copied from the agent.
NO_KEY = "No API key found for the selected model."
NO_SESSION = "No session found matching '{sid}'"

#: One anthropic-shaped usage block, with the keys a real turn carried. The
#: `cacheWrite1h` key is anthropic-only and is here on purpose: the mapper must
#: ignore what it does not name rather than choke on it (`PI-34`).
def usage(input_tokens: int, output_tokens: int, cost: float) -> dict:
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": input_tokens + output_tokens,
        "cost": {
            "input": round(cost * 0.7, 8),
            "output": round(cost * 0.3, 8),
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": cost,
        },
        "cacheWrite1h": 0,
        "reasoning": 0,
    }


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")


def assistant(text: str, cost: float, tokens: tuple[int, int]) -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "api": "anthropic-messages",
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "usage": usage(tokens[0], tokens[1], cost),
        "stopReason": "stop",
    }


def write_session_file(session_dir: Path, session_id: str) -> None:
    """Where the real agent puts it: under `--session-dir`, named by id."""
    session_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    path = session_dir / f"{stamp}_{session_id}.jsonl"
    if not path.exists():
        path.write_text(
            json.dumps({"type": "session", "id": session_id}) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-p", "--prompt", default="")
    parser.add_argument("--mode", default="json")
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--session-dir", default=None)
    parser.add_argument("--session", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--system-prompt", default=None)
    parser.add_argument("--tools", default=None)
    parser.add_argument("--exclude-tools", default=None)
    parser.add_argument("--no-tools", action="store_true")
    parser.add_argument("--no-skills", action="store_true")
    parser.add_argument("--no-extensions", action="store_true")
    parser.add_argument("--no-context-files", action="store_true")
    args, _unknown = parser.parse_known_args()
    prompt = args.prompt or ""

    if "hang" in prompt:
        while True:  # the caller's wall clock is the only way out
            time.sleep(3600)

    if "nokey" in prompt:
        sys.stderr.write(NO_KEY + "\n")
        return 1
    if "nosession" in prompt:
        sys.stderr.write(NO_SESSION.format(sid=args.session or "?") + "\n")
        return 1
    if "fail:" in prompt:
        sys.stderr.write(prompt.split("fail:", 1)[1].strip() + "\n")
        return 1

    # **A supplied id wins, then a resumed one, then a fresh one** (`PI-14`).
    session_id = args.session_id or args.session or str(uuid.uuid4())
    emit({"type": "session", "version": 3, "id": session_id,
          "timestamp": "2026-09-07T00:00:00.000Z", "cwd": str(Path.cwd())})
    if args.session_dir:
        write_session_file(Path(args.session_dir), session_id)
    emit({"type": "agent_start"})

    emit({"type": "turn_start"})
    emit({"type": "message_start",
          "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})
    emit({"type": "message_end",
          "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})
    emit({"type": "message_update", "usage": usage(100, 1, 0.0001),
          "assistantMessageEvent": {"type": "text_start", "contentIndex": 0}})
    emit({"type": "message_update", "usage": usage(100, 2, 0.0002),
          "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0,
                                    "delta": "ok"}})

    if "tools" in prompt:
        emit({"type": "tool_execution_start", "toolCallId": "toolu_1",
              "toolName": "write", "args": {"path": "hello.txt", "content": "hi"}})
        emit({"type": "tool_execution_end", "toolCallId": "toolu_1",
              "toolName": "write",
              # **Real text, unlike the Gemini target** (`PI-36`).
              "result": {"content": [{"type": "text",
                                      "text": "Successfully wrote to hello.txt"}]},
              "isError": False})

    if "refused:" in prompt:
        # **The whole point is the exit code below** (`PI-61`): the agent
        # records its own failure and still leaves with 0, so nothing outside
        # this message says the turn did not happen.
        refused = assistant("", 0.0, (548, 0))
        refused["content"] = []
        refused["stopReason"] = "error"
        refused["errorMessage"] = prompt.split("refused:", 1)[1].strip()
        emit({"type": "turn_end", "message": refused, "toolResults": []})
        emit({"type": "agent_end", "messages": [refused], "willRetry": False})
        emit({"type": "agent_settled"})
        return 0

    first = assistant("ok", 0.000758, (548, 42))
    emit({"type": "turn_end", "message": first, "toolResults": []})

    messages = [first]
    if "twocalls" in prompt:
        # **A second model call in the SAME invocation** (`PI-16`), with a lower
        # input count than the first -- which is what proves the figures are per
        # call rather than cumulative.
        second = assistant("done", 0.002210, (520, 23))
        emit({"type": "turn_end", "message": second, "toolResults": []})
        messages.append(second)

    emit({"type": "agent_end", "messages": messages, "willRetry": False})
    emit({"type": "agent_settled"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
