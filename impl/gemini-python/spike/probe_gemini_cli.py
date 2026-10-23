"""What Gemini CLI 0.54.4 offers a service that wants to front it, measured free.

**Nothing here needs a credential and nothing here spends money.** That is the
whole design: the questions this answers -- which flags exist, which stream
events carry which fields, what a keyless run does, whether ACP is real -- are
all answerable from the binary and its bundle, and answering them before asking
for a key is what keeps the go/no-go cheap.

    npm install @google/gemini-cli@0.54.4
    uv run --no-project python probe_gemini_cli.py [path/to/node_modules]

**Pinned to 0.54.4.** Every field name below was read out of that bundle; a
later version may rename any of them, and this script prints the version it
actually measured so a stale finding is visible rather than assumed.

**What it cannot answer, and says so rather than guessing:** the shape of a
REAL turn's events, whether `--approval-mode` changes what a headless run will
actually execute, and whether `--sandbox` starts inside a container. All three
need `GEMINI_API_KEY` and a container, and all three are named in the write-up
as unmeasured.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

#: The version every field name here was read from. Printed, not asserted: a
#: mismatch is a finding rather than a failure, and a probe that refuses to run
#: on a new version tells you nothing about it.
PINNED = "0.54.4"

#: The bundle chunk carrying the CLI's own entry point. Located by content
#: rather than by name -- esbuild names chunks by hash and the name changes on
#: every release.
_ENTRY_MARKER = 'type: "tool_use"'


def _bin(node_modules: Path) -> Path:
    name = "gemini.cmd" if os.name == "nt" else "gemini"
    return node_modules / ".bin" / name


def _run(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """`(exit code, stdout, stderr)`. **Never piped.**

    A pipeline reports the LAST command's status, so `gemini … | tail` reads 0
    for a run that exited 41 -- measured, and it is the reason this returns the
    code from `subprocess` instead.
    """
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _entry_chunk(node_modules: Path) -> Path | None:
    bundle = node_modules / "@google" / "gemini-cli" / "bundle"
    for path in sorted(bundle.glob("*.js")):
        try:
            if _ENTRY_MARKER in path.read_text(encoding="utf-8", errors="replace"):
                return path
        except OSError:
            continue
    return None


def _event_shapes(source: str) -> dict[str, list[str]]:
    """The keys each `stream-json` event is CONSTRUCTED with.

    Read from the emitter rather than from a run, so it covers events a probe
    would have to provoke -- a tool error, a turn that hits the limit.
    """
    shapes: dict[str, list[str]] = {}
    for event in ("init", "message", "tool_use", "tool_result", "result"):
        match = re.search(rf'type: "{event}"[^;]{{0,600}}', source)
        if not match:
            continue
        keys = re.findall(r"(\w+):", match.group(0))
        shapes[event] = [k for k in dict.fromkeys(keys) if k != "type"]
    return shapes


def main(argv: list[str]) -> int:
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    if not gemini.exists():
        print(f"gemini not found at {gemini}", file=sys.stderr)
        return 2
    workspace = Path("./gemini-probe-workspace").resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    code, out, _ = _run([str(gemini), "--version"], workspace)
    version = out.strip().splitlines()[-1] if out.strip() else "?"
    print(f"gemini-cli {version}" + ("" if version == PINNED else f"  (PINNED {PINNED})"))

    # --- the keyless run -----------------------------------------------------
    #
    # **The credential gate, and it is the one a boot gate would copy.** The
    # message names the accepted variables itself, which is what lets the
    # pre-boot specification publish a list it did not invent.
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY",)}
    proc = subprocess.run(
        [str(gemini), "-p", "say hi", "-o", "json"],
        cwd=workspace, capture_output=True, text=True, env=env,
    )
    print(f"\nkeyless run: exit {proc.returncode}, "
          f"stdout {len(proc.stdout)} byte(s), stderr {len(proc.stderr)} byte(s)")
    envelope = proc.stderr or proc.stdout
    try:
        parsed = json.loads(envelope)
        print(f"  session_id minted: {bool(parsed.get('session_id'))}")
        print(f"  error.code: {parsed.get('error', {}).get('code')}")
        named = re.findall(r"\b(GEMINI_API_KEY|GOOGLE_GENAI_USE_\w+)\b",
                           parsed.get("error", {}).get("message", ""))
        print(f"  variables named: {sorted(set(named))}")
    except json.JSONDecodeError:
        print("  (not JSON -- the envelope moved)")

    # An invalid flag value is yargs, not the agent, and comes back a different
    # way. Worth knowing before mapping an exit code to an HTTP status.
    code, _, _ = _run([str(gemini), "-p", "hi", "--approval-mode", "nonsense"], workspace)
    print(f"  invalid --approval-mode value: exit {code}")

    # --- what the bundle says ------------------------------------------------
    chunk = _entry_chunk(node_modules)
    if chunk is None:
        print("\nentry chunk not found -- the bundle was restructured", file=sys.stderr)
        return 1
    source = chunk.read_text(encoding="utf-8", errors="replace")
    print(f"\nentry chunk: {chunk.name}")

    print("\nstream-json events, as CONSTRUCTED:")
    for event, keys in _event_shapes(source).items():
        print(f"  {event:<12} {', '.join(keys)}")

    # **ACP is the finding this probe exists to keep current.** A JSON-RPC
    # protocol with a host-side permission call is a different integration from
    # scraping a CLI, and the method list is what makes that concrete.
    print("\nACP:")
    for label, pattern in (
        ("protocol", r"var PROTOCOL_VERSION = ([^;]{1,40});"),
        ("agent methods", r"var AGENT_METHODS = \{(.{0,1400}?)\};"),
        ("client methods", r"var CLIENT_METHODS = \{(.{0,900}?)\};"),
    ):
        match = re.search(pattern, source, re.S)
        if not match:
            print(f"  {label}: NOT FOUND")
            continue
        if label == "protocol":
            print(f"  version {match.group(1)}")
            continue
        methods = re.findall(r'"([\w/]+)"', match.group(1))
        print(f"  {label} ({len(methods)}): {', '.join(methods)}")

    # The one that decides whether a headless agent can stall waiting for an
    # answer nobody will give.
    asks = "ASK_USER_TOOL_NAME" in source
    excluded = bool(re.search(r"if \(!interactive \|\| isAcpMode\).{0,120}ASK_USER_TOOL_NAME", source, re.S))
    print(f"\nask-user tool present: {asks}; excluded when non-interactive: {excluded}")

    _acp_dispatch(gemini, workspace)
    return 0


def _acp_dispatch(gemini: Path, workspace: Path) -> None:
    """Which ACP methods does the agent actually REGISTER?

    **The table in the bundle is the protocol's vocabulary, not this agent's**,
    and reading it as an implementation is how this probe got ACP wrong the
    first time: six of thirteen answer `-32601 Method not found`, including
    `session/cancel`, which is the verb behind
    `POST /v1/sessions/{sid}/interrupt`.

    **Free, and that is why it is worth running every release.** A
    method-not-found is decided before any credential is looked at, so this
    costs nothing and catches a method appearing or disappearing between
    versions. `-32000`/`-32603` both mean DISPATCHED -- the handler was reached
    and disliked the credential or the junk params below -- and only `-32601`
    means absent.

    One honest caveat, stated in the output: this runs with no session open, so
    a method registered lazily would be indistinguishable from one that does not
    exist.
    """
    methods = [
        "session/new", "session/list", "session/close", "session/prompt",
        "session/cancel", "session/load", "session/resume", "session/fork",
        "session/set_model", "session/set_mode", "session/set_config_option",
        "authenticate",
    ]
    lines = [json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True}},
    })]
    for offset, method in enumerate(methods):
        lines.append(json.dumps({
            "jsonrpc": "2.0", "id": 11 + offset, "method": method,
            # Deliberately junk: the question is whether a handler EXISTS, and
            # valid params would only buy a different error from the same place.
            "params": {"sessionId": "x", "cwd": str(workspace), "mcpServers": []},
        }))
    proc = subprocess.run(
        [str(gemini), "--acp"], cwd=workspace, input="\n".join(lines) + "\n",
        capture_output=True, text=True, timeout=180,
    )

    replies: dict[int, str] = {}
    handshake: dict = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and "result" in msg:
            handshake = msg["result"]
            replies[1] = "ok"
        elif "error" in msg:
            replies[msg.get("id")] = f"{msg['error']['code']}"
        elif "result" in msg:
            replies[msg.get("id")] = "ok"

    print("\nACP dispatch (no session open; -32601 = absent, anything else = reached):")
    print(f"  {'initialize':<28} {replies.get(1, '(no reply)')}")
    for offset, method in enumerate(methods):
        code = replies.get(11 + offset, "(no reply)")
        mark = "  ABSENT" if code == "-32601" else ""
        print(f"  {method:<28} {code}{mark}")

    if handshake:
        caps = handshake.get("agentCapabilities", {})
        print("\ninitialize result:")
        print(f"  agent: {handshake.get('agentInfo', {})}")
        print(f"  auth methods: {[m.get('id') for m in handshake.get('authMethods', [])]}")
        print(f"  mcp: {caps.get('mcpCapabilities')}  prompt: {caps.get('promptCapabilities')}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
