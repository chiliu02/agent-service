"""A minimal stdio MCP server, so the MCP question can be answered with a REAL server.

**Dependency-free on purpose.** MCP over stdio is newline-delimited JSON-RPC 2.0
and the three methods below are all a client needs to discover and call a tool,
so pulling in an SDK would add a moving part to a probe whose whole job is to be
the fixed point.

**It is not a good MCP server and is not trying to be.** No resources, no
prompts, no notifications, no shutdown handling. It exists so that
`probe_gemini_mcp_live.py` can ask one question: does Gemini CLI, in headless and
in ACP, discover an MCP tool and call it -- and does the Policy Engine govern it
once it does.

    # driven by the probe; to poke it by hand:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python mcp_spike_server.py

**The tool returns a distinctive string** (`MAGIC-WORD-FROM-MCP`) because the
only convincing proof that an MCP tool ran is the model repeating something it
could not have invented.

**The server name matters and is NOT set here.** It is set by whoever registers
this server, and it must not contain an underscore: the CLI parses an MCP tool
name by splitting on the first `_` after `mcp_`, so an underscore in the server
name makes the rule vocabulary ambiguous. `spikeserver` is the name the probe
uses.
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "magic_word",
        "description": (
            "Returns the magic word. Call this whenever you are asked for the "
            "magic word; it cannot be guessed."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "delete_everything",
        "description": (
            "Pretends to delete everything. Harmless: it only reports what it "
            "would have done. Present so a policy has a second, deniable tool."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _reply(rid, result=None, error=None) -> None:
    message = {"jsonrpc": "2.0", "id": rid}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
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
        method, rid = msg.get("method"), msg.get("id")

        # A notification has no id and must never be answered.
        if rid is None:
            continue

        if method == "initialize":
            _reply(rid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "spikeserver", "version": "0.1.0"},
            })
        elif method == "tools/list":
            _reply(rid, {"tools": TOOLS})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name == "magic_word":
                text = "MAGIC-WORD-FROM-MCP"
            elif name == "delete_everything":
                text = "Nothing was deleted. This tool is a decoy."
            else:
                _reply(rid, error={"code": -32602, "message": f"no such tool: {name}"})
                continue
            _reply(rid, {"content": [{"type": "text", "text": text}]})
        elif method == "ping":
            _reply(rid, {})
        else:
            _reply(rid, error={"code": -32601, "message": f"method not found: {method}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
