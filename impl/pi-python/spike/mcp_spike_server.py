"""A minimal stdio MCP server, so the MCP question is answered with a REAL server.

**Dependency-free on purpose.** MCP over stdio is newline-delimited JSON-RPC 2.0,
and the four methods below are all a client needs to initialise, discover a tool
and call it. Pulling in an SDK would add a moving part to a probe whose whole job
is to be the fixed point.

**It is not a good MCP server and is not trying to be.** No resources, no
prompts, no progress, no shutdown handling.

    # driven by the probe; to poke it by hand:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python mcp_spike_server.py

**The tool returns a distinctive string** (`MAGIC-WORD-FROM-MCP`) because the only
convincing proof that an MCP tool ran is the model repeating something it could
not have invented. A model that merely *says* it called the tool is the failure
this guards against.

**It echoes the client's protocol version back** rather than asserting one. The
question here is whether Pi's adapter discovers and calls a tool, and a version
negotiation failure would answer a different question loudly.
"""

from __future__ import annotations

import json
import sys

MAGIC = "MAGIC-WORD-FROM-MCP"

TOOLS = [
    {
        "name": "magic_word",
        "description": (
            "Returns the magic word. Call this whenever you are asked for the "
            "magic word; it cannot be guessed."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }
]


def _reply(msg_id: object, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")

        # A notification has no id and takes no reply. Answering one is a
        # protocol error some clients treat as fatal.
        if msg_id is None:
            continue

        if method == "initialize":
            version = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
            _reply(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "spikeserver", "version": "0.0.1"},
            })
        elif method == "tools/list":
            _reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name == "magic_word":
                _reply(msg_id, {"content": [{"type": "text", "text": MAGIC}]})
            else:
                _reply(msg_id, {
                    "content": [{"type": "text", "text": f"no such tool: {name}"}],
                    "isError": True,
                })
        else:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
