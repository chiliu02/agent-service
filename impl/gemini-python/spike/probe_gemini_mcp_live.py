"""MCP on this target: does it work headless, does it work over ACP, does policy govern it?

**This one SPENDS MONEY** -- five short turns on the pinned cheap model.

    GEMINI_API_KEY=... uv run --no-project python probe_gemini_mcp_live.py [node_modules]

**Why it was the last real gap.** `/v1` carries MCP surface -- 0.8.0 exists
because a consumer needed an MCP route -- and nothing in the Gemini spike had
exercised it. `initialize` *declares* `mcpCapabilities: {http: true, sse: true}`,
which is a claim about the protocol, not evidence that a server is ever reached.

**The finding that matters is about trust, not MCP.** The CLI's own refusal
message offers `--skip-trust` and `GEMINI_CLI_TRUST_WORKSPACE=true` as
alternatives. They are not: `--skip-trust` runs the agent with **no MCP servers
at all**, silently, and the only symptom is the model saying it lacks a tool.
Every other probe in this spike uses `--skip-trust`, so this one changes the
recommendation for the whole build.

**The server is `mcp_spike_server.py` beside this file** -- dependency-free, two
tools, one of which returns a string the model could not invent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The ACP client from the probe next door, rather than a second copy of it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_gemini_acp_live import Acp  # noqa: E402

CAP = 120.0
MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")

#: No underscore, deliberately. The CLI parses an MCP tool name by splitting on
#: the first `_` after `mcp_`, so `spike_server` would make `mcpName` ambiguous.
SERVER = "spikeserver"

PROMPT = "Call the magic_word tool and reply with just the word it returns."

#: What only a real MCP round trip can produce.
MAGIC = "MAGIC-WORD-FROM-MCP"

#: `toolName` is REQUIRED even beside `mcpName`. The published reference says
#: "Target all tools from a server by omitting toolName" -- the schema rejects
#: exactly that, and the rejection discards the WHOLE file.
ALLOW_SERVER = f"""
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
mcpName = "{SERVER}"
toolName = "*"
decision = "allow"
priority = 950
"""

DENY_ONE_TOOL = ALLOW_SERVER + f"""
[[rule]]
mcpName = "{SERVER}"
toolName = "magic_word"
decision = "deny"
priority = 990
"""

#: The shape the documentation recommends and the schema refuses.
AS_DOCUMENTED = f"""
[[rule]]
mcpName = "{SERVER}"
decision = "allow"
priority = 950
"""


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


def _workspace(root: Path, name: str, server: Path) -> Path:
    """A workspace with the MCP server registered in its own `.gemini/settings.json`."""
    workspace = root / f"mcp-{name}"
    shutil.rmtree(workspace, ignore_errors=True)
    (workspace / ".gemini").mkdir(parents=True, exist_ok=True)
    (workspace / ".gemini" / "settings.json").write_text(json.dumps({
        "mcpServers": {SERVER: {"command": sys.executable, "args": [str(server)]}}
    }, indent=2), encoding="utf-8")
    return workspace


def _turn(gemini: Path, workspace: Path, *flags: str, trust_env: bool) -> tuple[str, list[str], str]:
    """Returns `(outcome, tools called, all assistant text)`."""
    env = dict(os.environ)
    if trust_env:
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    else:
        env.pop("GEMINI_CLI_TRUST_WORKSPACE", None)
    try:
        proc = subprocess.run(
            [str(gemini), "-p", PROMPT, "-o", "stream-json", "--approval-mode", "yolo",
             "-m", MODEL, *flags],
            cwd=str(workspace), capture_output=True, text=True, timeout=CAP, env=env)
        outcome, stdout = f"exit {proc.returncode}", proc.stdout
    except subprocess.TimeoutExpired as expired:
        outcome = "DID NOT FINISH"
        raw = expired.stdout
        stdout = raw if isinstance(raw, str) else (raw or b"").decode("utf-8", "replace")

    tools, said = [], []
    for line in stdout.splitlines():
        try:
            event = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool_use":
            tools.append(event["tool_name"])
        elif event.get("type") == "message" and event.get("role") == "assistant":
            said.append(str(event.get("content", "")))
    return outcome, tools, "".join(said)


def _preflight(gemini: Path, root: Path, policy: Path) -> bool:
    """True if the policy file is REJECTED. Free: no key, no turn."""
    proc = subprocess.run(
        [str(gemini), "--list-sessions", "--admin-policy", str(policy)],
        cwd=str(root), capture_output=True, text=True, timeout=90,
        env={k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"})
    return "Policy file error" in proc.stderr


def main(argv: list[str]) -> int:
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    server = Path(__file__).resolve().parent / "mcp_spike_server.py"
    if not gemini.exists() or not server.exists():
        print("gemini or mcp_spike_server.py not found", file=sys.stderr)
        return 2
    root = Path("./temp").resolve()
    root.mkdir(parents=True, exist_ok=True)
    policy_dir = root / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    policies = {}
    for name, body in (("mcp-allow-server", ALLOW_SERVER),
                       ("mcp-deny-one-tool", DENY_ONE_TOOL),
                       ("mcp-as-documented", AS_DOCUMENTED)):
        path = policy_dir / f"{name}.toml"
        path.write_text(body.lstrip(), encoding="utf-8")
        policies[name] = path

    # --- free: the documented rule shape does not validate --------------------
    print("0. the shape the published reference recommends (FREE -- no key, no turn)")
    for name in ("mcp-allow-server", "mcp-as-documented"):
        print(f"  {name+'.toml':<26} rejected={_preflight(gemini, root, policies[name])}")
    print("   ^ the docs say 'omit toolName to target all tools from a server'.")
    print("     That is precisely what the schema refuses -- and a refused file is")
    print("     discarded ENTIRELY, taking its `deny *` with it.\n")

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set -- stopping after the free half.")
        return 0

    # --- 1. the trust flag and the trust env var are NOT equivalent ----------
    print("1. --skip-trust vs GEMINI_CLI_TRUST_WORKSPACE, same workspace, same prompt")
    for label, flags, trust_env in (
        ("--skip-trust", ("--skip-trust",), False),
        ("TRUST_WORKSPACE=true", (), True),
    ):
        workspace = _workspace(root, f"trust-{label.split('=')[0].strip('-')}", server)
        outcome, tools, said = _turn(gemini, workspace, *flags, trust_env=trust_env)
        print(f"  {label:<22} {outcome:<10} magic={'YES' if MAGIC in said else 'NO':<4} "
              f"tools={tools}")
    print("   ^ `gemini mcp list` says it outright in an untrusted folder: 'MCP servers")
    print("     are configured but disabled'. --skip-trust does NOT lift that, and the")
    print("     run does not warn -- the model simply reports a tool it does not have.\n")

    # --- 2. does the Policy Engine govern MCP tools? -------------------------
    print("2. policy over MCP tools (all with the trust env var set)")
    for name, expectation in (("mcp-allow-server", "the MCP tool runs; built-ins are denied"),
                              ("mcp-deny-one-tool", "the MCP tool is not even attempted")):
        workspace = _workspace(root, name, server)
        outcome, tools, said = _turn(gemini, workspace, "--admin-policy", str(policies[name]),
                                     trust_env=True)
        print(f"  {name:<20} {outcome:<10} magic={'YES' if MAGIC in said else 'NO':<4} "
              f"tools={tools}")
        print(f"  {'':<20} expected: {expectation}")
    print("   ^ `mcpName` + `toolName` allowlists a whole server or denies one of its")
    print(f"     tools. The tool is addressed as `mcp_{SERVER}_<tool>`.\n")

    # --- 3. ACP: can the client hand the server over at session/new? ---------
    # **Deliberately WITHOUT the trust env var**, which is the finding: the trust
    # gate suppresses servers the workspace CONFIGURES, not servers the client
    # HANDS OVER. Measured -- the magic word comes back either way.
    print("3. ACP session/new with mcpServers -- no settings.json, no trust env var")
    acp_workspace = root / "mcp-acp"
    shutil.rmtree(acp_workspace, ignore_errors=True)
    acp_workspace.mkdir(parents=True, exist_ok=True)
    os.environ.pop("GEMINI_CLI_TRUST_WORKSPACE", None)
    acp = Acp(gemini, acp_workspace)
    acp.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
        "fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True}})
    new = acp.call("session/new", {
        "cwd": str(acp_workspace),
        # **`env` is REQUIRED and `[]` is a legal value.** Omit it and the union
        # falls through to the HTTP variant, whose complaint is about `headers` --
        # an error message pointing at a branch you were never trying to use.
        # Measured: without `env` it is -32603; with `env: []` it is accepted.
        "mcpServers": [{"name": SERVER, "command": sys.executable,
                        "args": [str(server)], "env": []}],
    })
    if "error" in new:
        print(f"  session/new REJECTED the mcpServers param: "
              f"{json.dumps(new['error'])[:200]}")
    else:
        sid = new["result"]["sessionId"]
        reply = acp.call("session/prompt", {
            "sessionId": sid, "prompt": [{"type": "text", "text": PROMPT}]})
        text = json.dumps(acp.updates)
        print(f"  session/new ok; prompt stopReason="
              f"{(reply.get('result') or {}).get('stopReason')}")
        print(f"  magic word came back over ACP: {MAGIC in text}")
        print(f"  tool_call updates: "
              f"{[u.get('update', {}).get('title') for u in acp.updates if u.get('update', {}).get('sessionUpdate','').startswith('tool_call')][:3]}")
    acp.proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
