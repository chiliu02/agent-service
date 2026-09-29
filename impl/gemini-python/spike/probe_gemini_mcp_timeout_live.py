"""Does THIS build cut off an MCP tool call that has not begun answering?

**This one SPENDS MONEY** -- three short turns on the pinned cheap model. The
prompts are three sentences; the wall clock is two waits of 90 s, which cost
nothing because the model is not thinking during them.

    # 1. the server, in one shell, reachable from the container
    MCP_DELAY_S=90 uv run --no-project python spike/mcp_http_delay_server.py 9010

    # 2. the service, in a container, with a real key
    docker run -d --name mcp-timeout-probe --cap-drop ALL \\
      -p 127.0.0.1:8794:8000 -e GEMINI_API_KEY=... \\
      -e AGENT_SERVICE_MODEL=gemini-3.1-flash-lite \\
      -e AGENT_SERVICE_TURN_TIMEOUT_S=200 \\
      -v "<abs>/workspace:/workspace" \\
      agent-service-gemini-python:0.0.8

    # 3. this
    uv run --no-project python spike/probe_gemini_mcp_timeout_live.py \\
      http://127.0.0.1:8794 http://host.docker.internal:9010/mcp

**The question, and why a source read could not answer it.** A consumer measured
an MCP tool call failing at ~60 s with `fetch failed` when the server withheld
its response headers, and succeeding at 90 s when the server sent headers at
once. Five reads of the installed bundle say this build imposes no such bound:
the live tool path passes 600 s explicitly, the SDK's own request timeout raises
a different error, the transport's `requestInit` carries neither signal nor
timeout, the CLI's fetch wrapper adds no timer, and both dispatchers default
`headersTimeout` to 300 s.

**But a proxy enforcing time-to-first-byte predicts exactly the same rows**, and
that is what a source read cannot rule out from here. So this runs the same two
rows in a container with no proxy variables set at all.

| What the run shows | What it means |
| --- | --- |
| `slowsilent` **succeeds** at ~90 s | the build imposes no request bound; the consumer's 60 s is in their path |
| `slowsilent` **fails** near 60 s | the build does impose one and `request_timeout_s` is 60 |

`slowstream` is the control in both directions: if it fails too, nothing is
being measured and the setup is wrong. `quick` proves the wiring before either
slow turn is paid for.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

#: No underscore. This build refuses a server name containing one, because the
#: agent parses an MCP tool name by splitting on the first `_` after `mcp_`.
SERVER = "slowmcp"

#: Long enough that a 90 s tool call is never the thing that ends the turn.
#: `AGENT_SERVICE_TURN_TIMEOUT_S` on the container must allow it too.
TIMEOUT_S = 200

CASES = [
    ("quick", "Call the quick tool and reply with exactly the token it returns."),
    ("slowsilent",
     "Call the slowsilent tool and reply with exactly the token it returns. "
     "It takes over a minute. Wait for it and do not call anything else."),
    ("slowstream",
     "Call the slowstream tool and reply with exactly the token it returns. "
     "It takes over a minute. Wait for it and do not call anything else."),
]

MAGIC = "MAGIC-FROM-SLOW-MCP"


def _call(url: str, payload=None, method: str | None = None, timeout: float = 260.0):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, body


def main(argv: list[str]) -> int:
    base = (argv[1] if len(argv) > 1 else "http://127.0.0.1:8794").rstrip("/")
    mcp_url = argv[2] if len(argv) > 2 else "http://host.docker.internal:9010/mcp"

    status, caps = _call(f"{base}/v1/capabilities", timeout=20)
    if status != 200:
        print(f"FAIL: /v1/capabilities answered {status}")
        return 2
    print(f"impl        {caps['impl']['name']} {caps['impl']['version']}")
    # **Absent on the image the consumer measured**, which is the point rather
    # than a defect: `mcp.tool_call` was added after it was built. Reporting
    # "not published" keeps this probe runnable against both.
    published = caps["mcp"].get("tool_call")
    print(f"published   mcp.tool_call = "
          f"{json.dumps(published) if published else 'not published by this image'}")
    print(f"server      {mcp_url}\n")

    # A third argument narrows the run to named cases, which is what makes a
    # second pass -- timing the abort against a long delay -- cost one turn
    # rather than three.
    wanted = set(argv[3].split(",")) if len(argv) > 3 else {tool for tool, _ in CASES}

    results = []
    for tool, prompt in [case for case in CASES if case[0] in wanted]:
        body = {
            "options": {
                "mcp_servers": {SERVER: {"type": "http", "url": mcp_url}},
                "timeout_s": TIMEOUT_S,
            },
            "title": f"mcp-timeout-{tool}",
        }
        status, record = _call(f"{base}/v1/sessions", body, timeout=60)
        if status != 201:
            print(f"{tool:<12} FAIL: create answered {status}: {record}")
            results.append((tool, None, "create failed"))
            continue
        sid = record["session_id"]

        started = time.monotonic()
        status, turn = _call(f"{base}/v1/sessions/{sid}/messages", {"prompt": prompt})
        elapsed = time.monotonic() - started

        text = json.dumps(turn)[:400] if turn else ""
        got_magic = MAGIC in text
        # An error the agent reports comes back INSIDE a successful turn, as the
        # tool's own failure text -- so a 200 is not by itself a pass.
        print(f"{tool:<12} {status} in {elapsed:6.1f}s  magic={got_magic}")
        print(f"             {text[:300]}")
        results.append((tool, elapsed, "magic" if got_magic else text[:120]))

        _call(f"{base}/v1/sessions/{sid}", method="DELETE", timeout=30)

    print("\n--- what it says -------------------------------------------------")
    silent = next((r for r in results if r[0] == "slowsilent"), None)
    stream = next((r for r in results if r[0] == "slowstream"), None)
    if not silent or silent[1] is None or not stream or stream[1] is None:
        print("inconclusive: a case did not run")
        return 1
    if stream[2] != "magic":
        print("INCONCLUSIVE: the streaming control failed too, so the setup is")
        print("wrong rather than the build being bounded.")
        return 1
    if silent[2] == "magic":
        print(f"NO REQUEST BOUND: a silent {silent[1]:.0f}s call was held to the end.")
        print("`request_timeout_s: null` is right, and a ~60s failure elsewhere is")
        print("in that deployment's path rather than in this build.")
    else:
        print(f"BOUNDED: the silent call died after {silent[1]:.0f}s while the")
        print("streaming one survived. `request_timeout_s` is real; publish it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
