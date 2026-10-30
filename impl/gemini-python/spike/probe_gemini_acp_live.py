"""What ACP does once a credential exists -- the half `probe_gemini_cli.py` could not reach.

**This one SPENDS MONEY.** It opens a real ACP session and sends real prompts;
the free probe beside it answers everything that can be answered without a key
and should be run first.

**Do not estimate the cost from the prompt size.** That mistake was made once and
it was wrong by an order of magnitude: the spike these probes came from was
budgeted at "cents" and cost about **10 USD**. A short prompt is not a short run
-- a turn that cannot finish keeps calling `invoke_agent`, and each subagent
spends tokens of its own for as long as the cap allows. **The caps and the pinned
`MODEL` below are the cost control**, not the prompts.

    npm install @google/gemini-cli@0.54.4
    GEMINI_API_KEY=... uv run --no-project python probe_gemini_acp_live.py [node_modules]

**It is a real ACP CLIENT, not a line-scraper, and that is the point.** The
questions that matter -- does `session/request_permission` fire, what does
`session/update` actually stream, do `fs/*` and `terminal/*` invert the sandbox
-- are all questions about calls the agent makes *into the host*. Nothing that
only writes to stdin can answer them, so this answers every inbound request and
records what was asked.

**Every answer it gives is "allow"**, deliberately: the question here is whether
the channel exists and what travels over it, not what a policy should decide.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

#: The version every shape here was measured against.
PINNED = "0.54.4"

#: **Pinned to the cheapest tier on purpose** (user, 2026-08-11, after the spike
#: cost real money). The unpinned default is `auto`, which bills **two** models
#: per turn -- a `utility_router` beside the one that answers -- and pinning
#: removes the router entirely (measured). Override with `GEMINI_PROBE_MODEL`.
#:
#: **The findings here do not move with it.** Policy decisions, tool
#: registration and exit codes are engine behaviour. What DOES move is how often
#: the agent flails, so GP-18's nine-trial tally stays pinned to the
#: `gemini-3.5-flash` numbers it was measured on.
MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")


#: The six that answered `-32601 Method not found` on a handshake with NO session
#: open. Re-asked here with a live session id, because a method registered lazily
#: and a method that does not exist are indistinguishable until one exists.
ABSENT_WITHOUT_SESSION = [
    "session/list", "session/close", "session/cancel",
    "session/resume", "session/fork", "session/set_config_option",
]


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


class Acp:
    """A minimal ACP client over stdio: newline-delimited JSON-RPC 2.0."""

    def __init__(self, gemini: Path, cwd: Path, policy: Path | None = None) -> None:
        # **The Policy Engine is the one boundary that survives both interfaces**,
        # and this argument is how that gets tested rather than assumed: pass a
        # policy file and the same turn below must be refused.
        policy_flags = ["--admin-policy", str(policy)] if policy else []
        self.proc = subprocess.Popen(
            # A trust override is NOT optional: an untrusted folder refuses the
            # whole run rather than degrading. `--skip-trust` is the WRONG one for
            # a service and is kept here only because this probe predates the
            # finding and does not touch MCP -- see GP-08.
            [str(gemini), "--acp", "--skip-trust", "-m", MODEL, *policy_flags],
            cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._next_id = 1
        self._replies: dict[int, dict] = {}
        self._events: queue.Queue = queue.Queue()
        #: Every request the AGENT made of US, in order. The whole point.
        self.inbound: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        self.stderr: list[str] = []
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())

    def _read(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" in msg and "id" in msg:
                self._serve(msg)            # the agent is asking US something
            elif "method" in msg:
                self._notify(msg)           # session/update and friends
            else:
                self._replies[msg.get("id")] = msg
                self._events.put(msg.get("id"))

    def _notify(self, msg: dict) -> None:
        if msg["method"] == "session/update":
            self.updates.append(msg.get("params", {}))
        else:
            self.inbound.append((msg["method"], msg.get("params", {})))

    def _serve(self, msg: dict) -> None:
        """Answer an inbound agent->client request. Always permissively."""
        method, params = msg["method"], msg.get("params", {})
        self.inbound.append((method, params))
        result: dict | None = {}
        if method == "session/request_permission":
            # Pick whichever option the agent itself labelled as allowing.
            options = params.get("options", [])
            chosen = next(
                (o for o in options if "allow" in str(o.get("kind", o.get("optionId", ""))).lower()),
                options[0] if options else {"optionId": "allow"},
            )
            result = {"outcome": {"outcome": "selected", "optionId": chosen.get("optionId")}}
        elif method == "fs/read_text_file":
            try:
                result = {"content": Path(params["path"]).read_text(encoding="utf-8")}
            except OSError as exc:
                result = {"content": f"<unreadable: {exc}>"}
        elif method == "fs/write_text_file":
            # The inversion this probe exists to confirm: the HOST does the write.
            path = Path(params["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.get("content", ""), encoding="utf-8")
            result = {}
        elif method.startswith("terminal/"):
            result = {"terminalId": "t1", "exitStatus": {"exitCode": 0}, "output": ""}
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def call(self, method: str, params: dict, timeout: float = 180.0) -> dict:
        rid = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = threading.Event()
        while rid not in self._replies:
            try:
                self._events.get(timeout=timeout)
            except queue.Empty:
                return {"error": {"code": "timeout", "message": f"no reply in {timeout}s"}}
            if deadline.is_set():
                break
        return self._replies.get(rid, {})


def _label(err_or_result: dict) -> str:
    if "error" in err_or_result:
        code = err_or_result["error"].get("code")
        return f"{code}" + ("  ABSENT" if code == -32601 else "")
    return "ok"


def main(argv: list[str]) -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    if not gemini.exists():
        print(f"gemini not found at {gemini}", file=sys.stderr)
        return 2

    # Optional second argument: a policy file, applied at the ADMIN tier. With
    # one, the turn below should be refused and `fs/write_text_file` should never
    # arrive -- which is how "does the Policy Engine reach ACP" gets answered.
    policy = Path(argv[2]).resolve() if len(argv) > 2 else None
    suffix = "-policy" if policy else ""
    workspace = Path(f"./temp/acp-live{suffix}").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "seed.txt").write_text("alpha\n", encoding="utf-8")
    if policy:
        print(f"admin policy: {policy}")

    acp = Acp(gemini, workspace, policy)

    init = acp.call("initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        },
    })
    print(f"initialize: {_label(init)}")

    # --- does a session open with a real key? --------------------------------
    supplied = str(uuid.uuid4())
    new = acp.call("session/new", {"cwd": str(workspace), "mcpServers": []})
    if "error" in new:
        print(f"session/new FAILED: {json.dumps(new['error'])[:300]}")
        return 1
    sid = new["result"]["sessionId"]
    print(f"session/new: ok  sessionId={sid}")
    print(f"  result keys: {sorted(new['result'].keys())}")
    print(f"  modes: {json.dumps(new['result'].get('modes'))[:300]}")
    print(f"  models: {json.dumps(new['result'].get('models'))[:300]}")

    # --- were the six lazily registered? -------------------------------------
    print("\nthe six, re-asked WITH a live session (-32601 = still absent):")
    for method in ABSENT_WITHOUT_SESSION:
        params: dict = {"sessionId": sid}
        if method == "session/set_config_option":
            params |= {"key": "x", "value": "y"}
        print(f"  {method:<28} {_label(acp.call(method, params, timeout=30))}")

    # --- a real turn, and what comes back over session/update ----------------
    print("\nsession/prompt -- a turn that must WRITE, so permission has to be decided:")
    before = len(acp.inbound)
    reply = acp.call("session/prompt", {
        "sessionId": sid,
        "prompt": [{"type": "text",
                    "text": "Create a file named acp-hello.txt in the current directory "
                            "containing exactly HELLO. Then say DONE."}],
    })
    print(f"  reply: {json.dumps(reply.get('result', reply.get('error')))[:200]}")
    print(f"  acp-hello.txt exists: {(workspace / 'acp-hello.txt').exists()}")

    kinds: dict[str, int] = {}
    for update in acp.updates:
        inner = update.get("update", {})
        kinds[inner.get("sessionUpdate", "?")] = kinds.get(inner.get("sessionUpdate", "?"), 0) + 1
    print(f"\nsession/update notifications: {len(acp.updates)}")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind:<28} x{count}")
    for update in acp.updates[:6]:
        print(f"  sample: {json.dumps(update)[:240]}")

    print(f"\nagent -> host requests: {len(acp.inbound) - before} during the turn")
    for method, params in acp.inbound:
        print(f"  {method:<28} {json.dumps(params)[:200]}")

    acp.proc.terminate()
    print(f"\nstderr lines: {len(getattr(acp, 'stderr', []))}")
    for line in getattr(acp, "stderr", [])[:8]:
        print(f"  {line[:160]}")
    print(f"\nsupplied-uuid experiment: session/new took no id; we generated {supplied} "
          f"and the agent answered {sid} -- compare with --session-id/--list-sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
