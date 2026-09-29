"""What Pi offers a service that wants to front it, measured free.

**Nothing here needs a credential and nothing here spends a token.** That is the
whole design. The four questions that decide whether a fourth build is worth
starting -- can a session be resumed non-interactively, is usage reported with a
cost, is the agent's home relocatable, and what does the RPC surface actually
dispatch -- are all answerable before a key is looked at, and answering them
first is what keeps the go/no-go cheap. The gemini spike was estimated at
"cents" and cost about 10 USD; that estimate was made from prompt sizes and the
prompts were never the cost.

    npm install --no-save @earendil-works/pi-coding-agent@0.85.1
    uv run --no-project python probe_pi_cli.py [path/to/node_modules]

**Pinned to 0.85.1**, which is what every finding below was read from. The
version actually measured is printed on every run and a mismatch is reported
rather than raised: a probe that refuses to start on a new release tells you
nothing about that release.

**Five commands are named and NEVER sent.** `prompt`, `steer`, `follow_up`,
`compact` and `bash` reach a model or a shell. A probe that advertises itself as
free and then queues a turn is the failure this file exists to avoid, so they are
listed as withheld and their existence is left unmeasured -- absence of evidence,
printed as such.

**What it cannot answer, and says so rather than guessing:**

* the shape of a REAL turn's events, and whether `usage.cost` is populated once
  a provider has actually billed something -- only the SHAPE of the stats
  envelope on an empty session is free;
* whether a resumed session replays its MESSAGES. This measures whether a
  second process LOADS a session written by a first, with no turn in either, so
  a load that succeeds and a transcript that is empty are indistinguishable
  here. **Answered live on 2026-09-07 and the answer is yes, on all three
  providers**: a second `-p` process given `--session <id>` named the file the
  first had written, on anthropic, openai and google alike, for 0.001366 USD
  in total. So the free tier's silence here is a limit of the tier, not a
  limit of Pi, and the documentation saying print mode does not resume is
  wrong;
* whether `.pi/mcp.json` is honoured, which needs the adapter installed and a
  tool call to prove;
* anything about sandboxing. Pi documents that it has no built-in sandbox, so
  there is nothing to measure -- the container is the boundary.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: The version every finding here was read from. Printed, not asserted: a
#: mismatch is a finding rather than a failure, and a probe that refuses to run
#: on a new version tells you nothing about it.
PINNED = "0.85.1"

#: Kept OUT of every child process, so a machine that happens to be logged in
#: cannot make the keyless run look like a working one. `~/.pi/agent/auth.json`
#: takes priority over these anyway, which is why the agent home is relocated
#: for every child as well.
_CREDENTIALS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "XAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY", "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID", "GOOGLE_CLOUD_PROJECT",
)

#: Commands that neither reach a model nor run a shell. Sent with deliberately
#: junk parameters: the question is whether a handler EXISTS, and valid
#: parameters would only buy a different error from the same place.
_SAFE = (
    "get_state", "get_messages", "get_last_assistant_text", "get_session_stats",
    "get_entries", "get_tree", "get_fork_messages", "get_commands",
    "get_available_models", "get_available_thinking_levels",
    "set_model", "cycle_model", "set_thinking_level", "cycle_thinking_level",
    "new_session", "switch_session", "fork", "clone", "set_session_name",
    "clear_queue", "abort", "abort_bash", "abort_retry",
    "set_auto_compaction", "set_auto_retry", "set_steering_mode",
    "set_follow_up_mode", "export_html",
)

#: Named so the table is honest about its own gaps, and withheld so this stays
#: free. Each one either bills a provider or executes on this machine.
_WITHHELD = {
    "prompt": "takes a turn",
    "steer": "queues into a turn",
    "follow_up": "queues into a turn",
    "compact": "calls the summarisation model",
    "bash": "executes a shell command here",
}

#: The commands whose PAYLOAD is the finding rather than merely their presence.
#: `get_available_thinking_levels` is what a build would publish as its exact
#: effort vocabulary, and `get_session_stats` is the only free look at whether a
#: cost figure exists at all.
_ANSWER_BEARING = (
    "get_available_thinking_levels", "get_session_stats", "get_state",
    "get_available_models", "get_commands",
)


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")


def _env(home: Path, **extra: str) -> dict[str, str]:
    """A hermetic, keyless, offline environment.

    `PI_OFFLINE` and `PI_SKIP_VERSION_CHECK` are set on every child because a
    probe that reaches pi.dev on startup measures the network as much as the
    binary, and a version check inside a container is one more thing to explain
    when it fails.
    """
    env = {k: v for k, v in os.environ.items() if k not in _CREDENTIALS}
    env["PI_CODING_AGENT_DIR"] = str(home)
    env["PI_OFFLINE"] = "1"
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env["PI_TELEMETRY"] = "0"
    env.update(extra)
    return env


def _run(argv: list[str], cwd: Path, env: dict[str, str],
         seconds: int = 60) -> tuple[int, str, str]:
    """`(exit code, stdout, stderr)`. **Never piped.**

    A pipeline reports the LAST command's status, so `pi … | tail` reads 0 for a
    run that exited non-zero. That was measured on the gemini CLI and is the
    reason this returns the code from `subprocess` instead.

    **`stdin=DEVNULL`, and it is load-bearing rather than tidy.** With the MCP
    adapter installed, `pi -p` and `pi --mode json` HANG FOREVER on an inherited
    stdin -- no session header, no error, no output at all, measured at 5+
    minutes and killed. Closing stdin makes the same command answer instantly.
    Any service spawning this agent per turn must close the child's stdin or use
    `--mode rpc`, where stdin is the protocol and the question does not arise.
    """
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              env=env, timeout=seconds, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as expired:
        out = expired.stdout or b""
        err = expired.stderr or b""
        decode = (lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else b)
        return -1, decode(out), decode(err)
    return proc.returncode, proc.stdout, proc.stderr


def _rpc(pi: Path, cwd: Path, env: dict[str, str], commands: list[dict],
         extra_argv: list[str] | None = None, ephemeral: bool = True,
         seconds: int = 90) -> tuple[list[dict], str]:
    """Send JSONL commands to `pi --mode rpc` and collect every JSON line back.

    **The wire is `{"id": …, "type": "<command>", …}` in and
    `{"id": …, "type": "response", "command": …, "success": …}` out.** Both
    halves are read here rather than assumed: a response whose `command` does not
    match what was sent, or a run that answers nothing at all, is exactly the
    finding that would sink a driver written from the documentation.

    stdin is closed after the last command. If the agent does not exit on EOF it
    is killed and whatever it buffered is still read -- a partial table beats no
    table, and a hang is itself reportable.

    **`ephemeral` is not cosmetic and getting it wrong cost this probe its first
    session finding.** `--no-session` keeps the session in memory, so the
    round-trip below wrote no file, resumed nothing, and reported success --
    the agent said so itself, in the one command that failed:
    `export_html` -> `'Cannot export in-memory session to HTML'`. The dispatch
    table wants it (nothing should be persisted by a junk-parameter sweep); the
    round-trip must not have it.
    """
    argv = [str(pi), "--mode", "rpc", *(["--no-session"] if ephemeral else []),
            *(extra_argv or [])]
    payload = "".join(json.dumps(c) + "\n" for c in commands)
    proc = subprocess.Popen(argv, cwd=cwd, env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(input=payload, timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        err = (err or "") + f"\n[probe] no exit on EOF within {seconds}s -- killed"
    messages = []
    for line in (out or "").splitlines():
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages, err or ""


def _replies(messages: list[dict]) -> dict[str, dict]:
    """Responses keyed by the `id` that was sent, ignoring streamed events."""
    return {
        str(m.get("id")): m
        for m in messages
        if m.get("type") == "response" and m.get("id") is not None
    }


def _verdict(reply: dict | None) -> str:
    """`ok`, `reached`, `ABSENT` or `(no reply)`.

    **Only an unknown-command error means absent.** Any other failure means the
    handler was reached and disliked the junk parameters, which is the answer the
    dispatch table is actually after. This classifies by error text because the
    protocol has no error code -- so the pattern is printed alongside the table,
    and a Pi release that rewords the message shows up as a wall of `reached`
    rather than silently as a wall of `ABSENT`.
    """
    if reply is None:
        return "(no reply)"
    if reply.get("success"):
        return "ok"
    error = str(reply.get("error", ""))
    if re.search(r"unknown|unrecogni[sz]ed|not (a )?(valid|known)|no such", error, re.I):
        return "ABSENT"
    return "reached"


def main(argv: list[str]) -> int:
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    pi = _bin(node_modules)
    if not pi.exists():
        print(f"pi not found at {pi}", file=sys.stderr)
        return 2

    root = Path(tempfile.mkdtemp(prefix="pi-probe-"))
    home, workspace = root / "agent-home", root / "workspace"
    workspace.mkdir(parents=True)
    env = _env(home)

    code, out, err = _run([str(pi), "--version"], workspace, env)
    version = (out or err).strip().splitlines()[-1] if (out or err).strip() else "?"
    note = "" if version == PINNED else (f"  (PINNED {PINNED})" if PINNED else "  (UNPINNED)")
    print(f"pi {version}{note}")
    print(f"probe root: {root}")

    _package_facts(node_modules)
    _flags(pi, workspace, env)
    _keyless(pi, workspace, env)
    _dispatch(pi, workspace, env)
    _session_round_trip(pi, workspace, env, root)
    _home_containment(pi, workspace, home)
    _mcp(node_modules, pi, workspace, env)
    return 0


def _package_facts(node_modules: Path) -> None:
    """Licence, entry points and declared engines, read from the package.

    **The licence is a go/no-go and costs one file read.** An image is built from
    this package and tagged, and that is the wrong moment to discover the terms.
    """
    manifest = node_modules / "@earendil-works" / "pi-coding-agent" / "package.json"
    print("\npackage:")
    if not manifest.exists():
        print(f"  {manifest} NOT FOUND -- installed under a different name?")
        return
    data = json.loads(manifest.read_text(encoding="utf-8"))
    print(f"  name {data.get('name')}  version {data.get('version')}")
    print(f"  license {data.get('license')!r}")
    print(f"  engines {data.get('engines')}")
    print(f"  bin {list((data.get('bin') or {}).keys())}")
    licence = next((p for p in manifest.parent.glob("LICENSE*")), None)
    print(f"  LICENSE file: {licence.name if licence else 'NONE'}")


#: An option line in `pi --help`: two spaces, then the flag, then its aliases and
#: description. **Anchored, and that anchor is the whole fix.** The first version
#: of this matched any flag-shaped token anywhere in the help text and reported
#: `--plan` and `--path--` as undocumented flags this binary had. `--plan` came
#: out of the sentence *"Extensions can register additional flags (e.g., --plan
#: from plan-mode extension)"* and `--path--` out of an example path. Neither is
#: an option: a stock install answers `Error: Unknown option: --plan`, character
#: for character what it answers for a flag invented on the spot.
_OPTION_LINE = re.compile(r"^ {2}(--[a-z][\w-]*)", re.M)

#: The same tokens ANYWHERE in the help, used only to compute the difference.
_ANY_FLAG = re.compile(r"(?<![\w-])--[a-z][\w-]+")


def _flags(pi: Path, workspace: Path, env: dict[str, str]) -> None:
    """Which documented flags the binary actually has, and what else it has.

    Read from `--help` rather than from the documentation, because the
    documentation is what is being checked -- and read from the OPTION LINES
    rather than from the help text, because prose in a help screen names flags
    the binary does not have.

    **Every flag reported as present is then invoked**, which is the check that
    would have caught the original bug on its own. It is free: an unknown option
    is rejected by the argument parser before a credential is looked at, and
    `--version` exits without a turn.
    """
    _, out, err = _run([str(pi), "--help"], workspace, env)
    text = out + err
    wanted = (
        "--mode", "--print", "--session", "--session-dir", "--no-session",
        "--fork", "--continue", "--resume", "--model", "--provider", "--api-key",
        "--thinking", "--tools", "--exclude-tools", "--no-builtin-tools",
        "--no-tools", "--approve", "--no-approve", "--name", "--list-models",
        "--export",
    )
    options = set(_OPTION_LINE.findall(text))
    print("\nflags claimed by the docs:")
    for flag in wanted:
        print(f"  {flag:<22} {'present' if flag in options else 'MISSING'}")

    extra = sorted(options - set(wanted))
    print(f"  undocumented ({len(extra)}): {', '.join(extra) if extra else '(none)'}")

    # **Named in the help text but NOT an option**, printed rather than dropped:
    # a flag mentioned in prose is usually a flag some EXTENSION registers, which
    # is a fact about the product's shape rather than noise.
    prose = sorted(set(_ANY_FLAG.findall(text)) - options)
    print(f"  named in prose, not options ({len(prose)}): "
          f"{', '.join(prose) if prose else '(none)'}")

    # The verification pass. `--version` short-circuits before any turn, so a
    # rejection here is the parser's and nothing else's.
    rejected = []
    for flag in sorted(options):
        code, o, e = _run([str(pi), flag, "--version"], workspace, env, seconds=30)
        if "Unknown option" in (o + e):
            rejected.append(flag)
    print(f"  rejected when invoked: {rejected or '(none -- every option line is real)'}")


def _keyless(pi: Path, workspace: Path, env: dict[str, str]) -> None:
    """What a run with no credential does -- the shape a boot gate copies.

    **Two things are wanted and only one of them is the error.** The other is
    whether the `session` header event, which carries the id a service would
    hand back as `sdk_session_id`, is emitted BEFORE the failure. If it is, the
    id exists without a turn; if it is not, a service cannot mint one until a
    provider has answered.
    """
    print("\nkeyless run (--mode json):")
    code, out, err = _run([str(pi), "--mode", "json", "-p", "say hi"],
                          workspace, env, seconds=90)
    print(f"  exit {code}, stdout {len(out)} byte(s), stderr {len(err)} byte(s)")
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    print(f"  event types before failure: {[e.get('type') for e in events][:12]}")
    header = next((e for e in events if e.get("type") == "session"), None)
    print(f"  session header emitted keyless: {bool(header)}"
          + (f"  id={header.get('id')}" if header else ""))
    named = sorted(set(re.findall(r"\b[A-Z][A-Z0-9_]{6,}\b", (err or out))[:40]))
    print(f"  variables named in the failure: {named or '(none)'}")

    code, _, _ = _run([str(pi), "--mode", "nonsense"], workspace, env, seconds=30)
    print(f"  invalid --mode value: exit {code}")


def _dispatch(pi: Path, workspace: Path, env: dict[str, str]) -> None:
    """Which RPC commands the agent actually REGISTERS.

    **This is the centre of the probe.** A driver is written against this table,
    and a command that turns out not to exist is a `/v1` operation that cannot be
    built: `abort` is `POST /v1/sessions/{sid}/interrupt`, `switch_session` is
    `RunOptions.resume`, and `get_session_stats` is the entire usage half of a
    turn result.

    Free because dispatch is decided before any credential is looked at. One
    honest caveat, printed with the table: this runs with `--no-session` and no
    turn, so a command registered lazily would be indistinguishable from one that
    does not exist.
    """
    commands = [{"id": name, "type": name, "sessionId": "x", "path": "x",
                 "modelId": "x", "provider": "x", "level": "x", "name": "x",
                 "mode": "x", "enabled": True, "cursor": 0}
                for name in _SAFE]
    messages, err = _rpc(pi, workspace, env, commands)
    replies = _replies(messages)

    print("\nRPC dispatch (--no-session, no turn; ABSENT = unknown-command error):")
    print("  classifier: error text matching /unknown|unrecognised|not valid|no such/i")
    for name in _SAFE:
        reply = replies.get(name)
        mark = _verdict(reply)
        detail = ""
        if reply is not None and not reply.get("success"):
            detail = f"  {str(reply.get('error'))[:70]!r}"
        print(f"  {name:<30} {mark}{detail}")
    for name, why in _WITHHELD.items():
        print(f"  {name:<30} NOT SENT -- {why}")

    print("\nanswer-bearing payloads:")
    for name in _ANSWER_BEARING:
        reply = replies.get(name)
        if reply is None:
            print(f"  {name}: (no reply)")
            continue
        body = {k: v for k, v in reply.items()
                if k not in ("id", "type", "command", "success")}
        print(f"  {name}: {json.dumps(body)[:600]}")

    unsolicited = [m.get("type") for m in messages if m.get("type") != "response"]
    print(f"\n  unsolicited events on a session-less run: "
          f"{sorted(set(t for t in unsolicited if t))or '(none)'}")
    if err.strip():
        print(f"  stderr: {err.strip()[:400]}")


def _session_round_trip(pi: Path, workspace: Path, env: dict[str, str],
                        root: Path) -> None:
    """Can a SECOND process load a session a first process wrote, with no turn?

    **The question the whole build turns on.** `RunOptions.resume` is the field,
    and the documentation says `-p` does not resume and is silent about RPC. If
    the answer is no, `resume` is refused with a 400 on this build and that is a
    large row in the divergence table; if it is yes, the driver is a
    `switch_session` away from the behaviour the other three builds already have.

    **Two processes, deliberately.** Resuming inside one process only proves the
    session object survived in memory, which is not what a service restart does.

    The caveat printed with the result matters: with no turn there are no
    messages, so this measures whether the session LOADS, not whether a
    transcript comes back with it.
    """
    sessions = root / "sessions"
    argv = ["--session-dir", str(sessions)]
    print("\nsession round-trip (two processes, no turn):")

    first, _ = _rpc(pi, workspace, env, [
        {"id": "name", "type": "set_session_name", "name": "probe"},
        {"id": "state", "type": "get_state"},
    ], extra_argv=argv, ephemeral=False)
    header = next((m for m in first if m.get("type") == "session"), None)
    state = _replies(first).get("state", {})
    sid = (header or {}).get("id") or _dig(state, "sessionId")
    print(f"  process A: session id {sid!r}")
    written = sorted(p.name for p in sessions.rglob("*.jsonl")) if sessions.exists() else []
    print(f"  files written without a turn: {written or '(none)'}")

    if not sid:
        print("  process B: SKIPPED -- no id to resume, which is itself the finding")
        return
    second, err = _rpc(pi, workspace, env, [
        {"id": "state", "type": "get_state"},
        {"id": "messages", "type": "get_messages"},
        {"id": "entries", "type": "get_entries"},
    ], extra_argv=[*argv, "--session", str(sid)], ephemeral=False)
    replies = _replies(second)
    for name in ("state", "messages", "entries"):
        print(f"  process B {name:<9} {_verdict(replies.get(name))}"
              f"  {json.dumps(replies.get(name, {}))[:200]}")
    loaded = _dig(replies.get("state", {}), "sessionId")
    print(f"  process B reports session {loaded!r} -- "
          f"{'SAME as A' if loaded == sid else 'DIFFERENT from A'}")
    # **The expected free result is a MISS, and that is the finding.** A session
    # file is not written until a turn is taken, so process A mints a real id
    # that resolves to nothing and B answers `No session found matching '<id>'`.
    # A resume proven here would mean Pi persists on startup; a miss means the
    # free tier has reached its limit, and the live measurement in the module
    # docstring is what carries the answer.
    print("  caveat: a MISS here is expected -- no turn, so nothing was "
          "persisted for B to find. Only a HIT would be news.")
    if err.strip():
        print(f"  stderr: {err.strip()[:300]}")


def _dig(payload: dict, *keys: str) -> str | None:
    """First of `keys` found anywhere in a response's `data`, as a string.

    **`data` and not the envelope, which is the bug this docstring records.**
    Searching the whole reply found the envelope's own `id` -- the correlation
    string this probe had just sent -- and reported process B as resuming a
    session called `'state'`, matching process A because both had been handed the
    same made-up id. A round-trip that compares two of your own inputs will
    always agree.
    """
    stack = [payload.get("data") or {}]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in keys:
                value = node.get(key)
                if isinstance(value, str) and value:
                    return value
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _home_containment(pi: Path, workspace: Path, home: Path) -> None:
    """Does `PI_CODING_AGENT_DIR` hold EVERYTHING, or does `~/.pi` leak?

    **Two of this platform's builds have already paid for this question and it
    is the reason to ask it early.** One was declared unsupported on a whole
    operating system over a relative agent home resolved against the workspace;
    another writes its state into the container's real `$HOME` with no override
    at all. A container that cannot confine an agent's state to a path it chose
    is a deployment problem discovered late.

    The override is documented, so what is measured here is whether it is
    COMPLETE -- every run above already had it set, so a populated `~/.pi` means
    something ignored it.
    """
    print("\nagent home containment:")
    print(f"  PI_CODING_AGENT_DIR contents: "
          f"{sorted(p.name for p in home.iterdir()) if home.exists() else '(not created)'}")
    default = Path.home() / ".pi"
    print(f"  ~/.pi exists: {default.exists()}"
          + (f"  entries {sorted(p.name for p in default.iterdir())[:8]}"
             if default.exists() else ""))
    print("  NOTE: a pre-existing ~/.pi from an interactive install is not a leak. "
          "Re-read this line on a machine that has never run pi.")


def _mcp(node_modules: Path, pi: Path, workspace: Path, env: dict[str, str]) -> None:
    """Is MCP present at all, and is it core or an extension?

    Pi's own documentation index has no MCP page and the adapter is a separate
    npm package, which would make MCP an image build step rather than a
    capability -- a row in the divergence table either way. What is free to check
    is whether the core binary knows the word.
    """
    print("\nMCP:")
    adapter = node_modules / "pi-mcp-adapter"
    print(f"  pi-mcp-adapter installed: {adapter.exists()}")
    _, out, err = _run([str(pi), "--help"], workspace, env)
    print(f"  'mcp' appears in --help: {'mcp' in (out + err).lower()}")
    messages, _ = _rpc(pi, workspace, env, [
        {"id": "commands", "type": "get_commands"},
    ])
    body = json.dumps(_replies(messages).get("commands", {}))
    print(f"  'mcp' appears in get_commands: {'mcp' in body.lower()}")
    print("  MEASURED LIVE 2026-09-07 (not by this free tier): with the adapter")
    print("    installed, an mcp.json is honoured and a real tool call succeeds --")
    print("    but the agent sees ONE proxy tool named `mcp`, never the server's")
    print("    own tool names, so `allowed_tools` cannot govern an individual MCP")
    print("    tool on this target. Servers are lazy: not connected until used.")
    print("  UNMEASURED: what ends a long tool call. Needs a server that stalls.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
