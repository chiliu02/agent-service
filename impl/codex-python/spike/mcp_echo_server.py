"""A minimal MCP stdio server, for measuring whether Codex launches one at all.

**Committed as evidence, per this repo's `spike/` convention.** It exists to
answer one question that could not be answered by reading: does a `mcp_servers.*`
config override reaching `codex app-server` actually produce a tool the agent can
call, inside this container, under bubblewrap?

Nothing in `src/` imports this and nothing should. It is deliberately dependency
free -- stdlib JSON over stdin/stdout -- so it runs in the shipped image, which
has no MCP SDK and no `npx`.

## The protocol, only as much as is needed

Newline-delimited JSON-RPC 2.0. Three requests and one notification:

    initialize                 -> capabilities + serverInfo
    notifications/initialized  -> no reply (it is a notification)
    tools/list                 -> one tool
    tools/call                 -> its result

**`protocolVersion` is echoed back rather than asserted.** Which version this
CLI negotiates is exactly the sort of thing that changes under a bump, and a
probe that fails on a version mismatch would answer a different question than
the one it was written for.

## The tool

`spike_echo` returns `SPIKE-OK:<text>`. The prefix is the point: a model can be
told to say "OK" without calling anything, so the evidence has to be a string the
model could not have produced without the tool's output.
"""

from __future__ import annotations

import json
import sys

TOOL = {
    "name": "spike_echo",
    "description": (
        "Echo a string back with a SPIKE-OK: prefix. Use this whenever you are "
        "asked to echo something."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _result(request_id, result: dict) -> None:  # noqa: ANN001
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue

        method = message.get("method")
        request_id = message.get("id")

        # A notification has no id and MUST NOT be answered -- replying to one
        # is a protocol error, and the CLI is entitled to drop the connection.
        if request_id is None:
            continue

        if method == "initialize":
            params = message.get("params") or {}
            _result(
                request_id,
                {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "spike-echo", "version": "0.0.1"},
                },
            )
        elif method == "tools/list":
            _result(request_id, {"tools": [TOOL]})
        elif method == "tools/call":
            params = message.get("params") or {}
            text = (params.get("arguments") or {}).get("text", "")
            _result(
                request_id,
                {"content": [{"type": "text", "text": f"SPIKE-OK:{text}"}]},
            )
        else:
            # Unknown method: an error, not silence. A server that ignores a
            # request it does not implement looks identical to one that hung.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"no method {method}"},
                }
            )


if __name__ == "__main__":
    main()
