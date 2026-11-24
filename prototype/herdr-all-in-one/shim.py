"""agent-service's core HTTP contract, served from Herdr's JSON socket API.

PROTOTYPE. Stdlib only. It answers the routes of this directory's openapi.json
(agent-service's core document plus the changes make_openapi.py lists) and serves
that document at /openapi.json. No streaming: the two `.../stream` routes answer
501, and `/v1/deployment` says so in `behaviour.streaming`. Live output is
watched by attaching a Herdr client over SSH instead.

One container, four CLIs. A session's CLI is `PROTO_AGENT` (the container's
default) unless the request's options carry `agent_kind`, which this document
adds to RunOptions.

Everything the agent does is learned through the socket: `workspace.create`,
`agent.start`, `agent.prompt` with a server-side wait, `agent.wait`,
`agent.read`, `agent.get`, `agent.send_keys`, `pane.close`. The one exception
is opt-in (`PROTO_TRANSCRIPT=1`, the default): when Herdr's integration has
reported the agent's own transcript path on `agent.get`, the final reply is
read from that file instead of from the screen, and the event says which.
"""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as store_mod  # noqa: E402 -- beside this file
import usage  # noqa: E402

STORE = store_mod.Store()

# This prototype's own document (make_openapi.py writes it from agent-service's core document).
OPENAPI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")
OPENAPI_BYTES = open(OPENAPI_FILE, "rb").read()
OPENAPI = json.loads(OPENAPI_BYTES)
DOCUMENT_VERSION = OPENAPI["info"]["version"]
IMPL = {"name": "herdr-all-in-one", "version": "0.0.0.dev2"}
P = "https://agent-service.invalid/problems/"  # the problem-type base agent-service uses
KINDS = ("claude", "codex", "gemini", "pi")
DEFAULT_KIND = os.environ.get("PROTO_AGENT", "claude")
WORKSPACE = os.environ.get("PROTO_WORKSPACE", "/work")
WORKTREE_LOCK = os.environ.get("PROTO_WORKTREE_LOCK", "1") != "0"  # one agent per worktree; 0 only to measure what is behind it
MAX_SESSIONS = int(os.environ.get("PROTO_MAX_SESSIONS", "8"))  # each session is a live TUI process tree
IDLE_TTL_S = int(os.environ.get("PROTO_IDLE_TTL_S", "3600"))
SSH_PORT, SSH_USER = 2222, "ubuntu"  # what entrypoint.sh starts sshd with
TOKEN = os.environ.get("AGENT_SERVICE_TOKEN") or None
# Harness injects AGENT_ID on every container it starts; the builds read it unprefixed and opaque,
# and absent is a normal deployment. Same here.
AGENT_ID = os.environ.get("AGENT_ID") or None
USE_TRANSCRIPT = os.environ.get("PROTO_TRANSCRIPT", "1") == "1"
TURN_LIMIT_S = float(os.environ.get("PROTO_TURN_LIMIT_S", "1800"))
START_LIMIT_MS = 60_000
WAIT_SLICE_MS = 240_000  # each socket wait; the turn limit is enforced across slices
SOCKET = os.environ.get("HERDR_SOCKET_PATH") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "herdr", "herdr.sock")
ROLE_DIR = "/tmp/proto-roles"  # role prompts written per session, outside every worktree
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

# Which RunOptions fields each CLI can carry as launch arguments. Anything else is refused,
# by name, in /v1/deployment's `accepts.unsupported_options` and with 400 on POST /v1/sessions.
# `include_partial_messages` only shapes a stream, and there is none, so it is accepted and inert.
_COMMON = {"model", "resume", "system_prompt", "permission_mode", "working_directory", "timeout_s",
           "include_partial_messages", "include_raw"}
CARRIED = {
    "claude": _COMMON | {"allowed_tools", "disallowed_tools", "setting_sources", "mcp_servers", "strict_mcp_config"},
    "codex": _COMMON, "gemini": _COMMON, "pi": _COMMON,
}
ALL_FIELDS = [k for k in OPENAPI["components"]["schemas"]["RunOptions"]["properties"] if k != "agent_kind"]
# Narrower refusals: the field works, these shapes of it do not.
NARROW = [{"field": "system_prompt", "types": ["object"]},  # a role is a file; a preset object has no carrier
          {"field": "include_raw", "values": [True]}]       # a TUI has no raw SDK payload to include

# The modes each CLI really has, and what an omitted `permission_mode` gets.
MODES = {
    "claude": [("default", "Default", "Asks before each tool that needs permission; the pane reads blocked "
                                      "until someone answers over SSH."),
               ("acceptEdits", "Accept edits", "File edits run without asking; other tools still ask."),
               ("plan", "Plan", "Read-only: the agent plans and changes nothing."),
               ("bypassPermissions", "Bypass permissions", "Every tool runs without asking."),
               ("dontAsk", "Don't ask", "Whatever would have asked is denied instead.")],
    "gemini": [("default", "Default", "Asks before each tool; the pane reads blocked until someone answers "
                                      "over SSH."),
               ("auto_edit", "Auto edit", "Edit tools run without asking; other tools still ask."),
               ("yolo", "YOLO", "Every tool runs without asking."),
               ("plan", "Plan", "Read-only.")],
    "codex": [("bypassPermissions", "Full access", "Sandbox danger-full-access with approval never: every "
                                                   "command runs without asking.")],
    "pi": [("bypassPermissions", "No approval step", "Pi has no permission system: every tool runs.")],
}
DEFAULT_MODE = {"claude": "default", "gemini": "default", "codex": "bypassPermissions", "pi": "bypassPermissions"}
SUPPLIED_ID = {"claude", "pi"}  # the CLIs that take a session id at launch


def unsupported(kind: str) -> list[dict]:
    return [{"field": f} for f in ALL_FIELDS if f not in CARRIED[kind]] + [
        e for e in NARROW if e["field"] in CARRIED[kind]]


def refused(entry: dict, value) -> bool:
    if value is None:
        return False
    if entry.get("values"):
        return value in entry["values"]
    if entry.get("types"):
        return ("object" in entry["types"] and isinstance(value, dict)) or (
            "array" in entry["types"] and isinstance(value, list))
    return value not in ([], {}, False)  # an empty list or object asks for nothing


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- Herdr socket

class HerdrError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


_ids = iter(range(1, 1 << 62))
_ids_lock = threading.Lock()
SOCKET_LOG: list[dict] = []  # every call, for the evaluation


def herdr(method: str, params: dict, timeout_s: float = 30.0) -> dict:
    """One request, one connection, one newline-delimited JSON reply."""
    with _ids_lock:
        rid = f"p{next(_ids)}"
    t0 = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout_s)
        s.connect(SOCKET)
        s.sendall((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    reply = json.loads(buf.decode() or "{}")
    SOCKET_LOG.append({"method": method, "ms": int((time.monotonic() - t0) * 1000),
                       "ok": "result" in reply, "error": reply.get("error")})
    del SOCKET_LOG[:-500]
    if "error" in reply:
        e = reply["error"]
        raise HerdrError(str(e.get("code")), str(e.get("message")))
    return reply.get("result", {})


def find_key(o, key):
    """The first value under `key` anywhere in a reply: Herdr's shapes nest, and differ by method."""
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def screen(target: str, lines: int = 400) -> str:
    r = herdr("agent.read", {"target": target, "source": "recent_unwrapped", "lines": lines})
    return r.get("text") or find_key(r, "text") or ""


def status_of(target: str) -> tuple[str, dict]:
    r = herdr("agent.get", {"target": target})
    return (find_key(r, "agent_status") or "unknown"), r


# --------------------------------------------------------------------------- per-CLI launch



def seed_trust(kind: str, cwd: str) -> None:
    """Pre-accept the workspace-trust prompts that would otherwise hold a fresh pane `blocked`."""
    home = os.path.expanduser("~")
    if kind == "claude":
        path = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.join(home, ".claude")), ".claude.json")
        try:
            cfg = json.load(open(path))
        except (OSError, ValueError):
            cfg = {}
        cfg.setdefault("hasCompletedOnboarding", True)
        cfg.setdefault("theme", "dark")
        cfg.setdefault("bypassPermissionsModeAccepted", True)
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:  # interactive Claude asks before using an env key; the answer is keyed on its last 20 chars
            approved = cfg.setdefault("customApiKeyResponses", {}).setdefault("approved", [])
            if key[-20:] not in approved:
                approved.append(key[-20:])
        proj = cfg.setdefault("projects", {}).setdefault(cwd, {})
        proj["hasTrustDialogAccepted"] = True
        proj.setdefault("hasCompletedProjectOnboarding", True)
        json.dump(cfg, open(path, "w"), indent=1)
    elif kind == "codex":
        path = os.path.join(os.environ.get("CODEX_HOME", os.path.join(home, ".codex")), "config.toml")
        text = open(path).read() if os.path.exists(path) else ""
        header = f'[projects."{cwd}"]'
        if header not in text:
            with open(path, "a") as f:
                f.write(f'\n{header}\ntrust_level = "trusted"\n')


def launch(kind: str, opts: dict, sid: str, sdk_id: str | None, cwd: str) -> tuple[list[str], dict, str | None]:
    """The `args` for agent.start, the pane env, and the agent session id we chose (if the CLI lets us)."""
    args: list[str] = []
    env: dict[str, str] = {}
    resume = opts.get("resume")
    role = opts.get("system_prompt")
    role_file = None
    if isinstance(role, str) and role:
        os.makedirs(ROLE_DIR, exist_ok=True)
        role_file = os.path.join(ROLE_DIR, f"{sid}.md")
        open(role_file, "w").write(role)
    model = opts.get("model")
    chosen = None
    if kind == "claude":
        if resume:
            args += ["--resume", resume]
            chosen = resume
        else:
            chosen = sdk_id or str(uuid.uuid4())
            args += ["--session-id", chosen]
        if model:
            args += ["--model", model]
        if role_file:  # re-passed on every launch, resume included
            args += ["--system-prompt-file", role_file]
        if opts.get("permission_mode"):
            args += ["--permission-mode", opts["permission_mode"]]
        if opts.get("allowed_tools"):
            args += ["--allowedTools", ",".join(opts["allowed_tools"])]
        if opts.get("disallowed_tools"):
            args += ["--disallowedTools", ",".join(opts["disallowed_tools"])]
        if opts.get("setting_sources") is not None:
            args += ["--setting-sources", ",".join(opts["setting_sources"])]
        if opts.get("mcp_servers"):
            args += ["--mcp-config", json.dumps({"mcpServers": opts["mcp_servers"]})]
            if opts.get("strict_mcp_config"):
                args += ["--strict-mcp-config"]
    elif kind == "codex":
        if resume:
            args += ["resume", resume]
            chosen = resume
        if model:
            args += ["-m", model]
        if role_file:
            args += ["-c", f'model_instructions_file="{role_file}"']
    elif kind == "pi":
        if resume:
            args += ["--session", resume]
            chosen = resume
        else:
            chosen = sdk_id or str(uuid.uuid4())
            args += ["--session-id", chosen]
        if model:
            provider, _, name = model.partition("/") if "/" in model else ("anthropic", "", model)
            args += ["--provider", provider, "--model", name]
        else:
            args += ["--provider", "anthropic", "--model", os.environ.get("PROTO_PI_MODEL", "claude-sonnet-4-5")]
        if role_file:
            args += ["--system-prompt", role_file]
    elif kind == "gemini":
        if resume:
            args += ["--resume", resume]
            chosen = resume
        if model:
            args += ["-m", model]
        if role_file:
            env["GEMINI_SYSTEM_MD"] = role_file  # the only carrier Gemini has for a role
        if opts.get("permission_mode"):
            args += ["--approval-mode", opts["permission_mode"]]
    return args, env, chosen


# --------------------------------------------------------------------------- ledger

LOCK = threading.RLock()
SESSIONS: dict[str, dict] = {}
RUNS: dict[str, dict] = {}
EVENTS: list[dict] = []  # StoredEvent, global id order


def add_event(sess: dict, run_id: str, etype: str, subtype: str | None, content) -> dict:
    with LOCK:
        run = RUNS[run_id]
        run["_seq"] += 1
        ev = {"id": len(EVENTS) + 1, "run_id": run_id, "seq": run["_seq"], "at": now_iso(), "type": etype,
              "subtype": subtype, "content": content, "_sid": sess["session_id"]}
        EVENTS.append(ev)
    STORE.insert_event(ev)
    return ev


def record(sess: dict) -> dict:
    last = sess.get("last_turn")
    return {
        "session_id": sess["session_id"], "sdk_session_id": sess.get("sdk_session_id"), "agent_id": AGENT_ID,
        "status": sess["status"], "created_at": sess["created_at"], "last_used_at": sess["last_used_at"],
        "turns": sess["turns"], "total_cost_usd": sess.get("total_cost_usd"),
        "model": sess.get("model") or sess["options"].get("model"),
        "permission_mode": sess["options"].get("permission_mode"), "last_residue_discarded": 0,
        "last_turn": last, "context_usage": sess.get("context_usage"),
        # prototype-only, additive: where to look over SSH
        "herdr": {"agent": sess.get("agent") or "", "pane_id": sess.get("pane_id"), "workspace_id": sess.get("workspace_id"),
                  "kind": sess["kind"], "agent_status": sess.get("agent_status"),
                  "transcript_path": sess.get("_transcript_path"), "transcript_key": transcript_key(sess),
                  "transcript_rows_saved": sess.get("_transcript_rows", 0)},
    }


def transcript_key(sess: dict) -> str | None:
    """`transcript_entries.session_key`: `<kind>-<worktree basename>/<agent session id>`."""
    sdk = sess.get("sdk_session_id")
    return f"{sess['kind']}-{os.path.basename(sess['cwd'].rstrip('/'))}/{sdk}" if sdk else None


def sync_transcript(sess: dict) -> int:
    """Copy the agent's own transcript lines written since the last sync into transcript_entries."""
    path, key = sess.get("_transcript_path"), transcript_key(sess)
    if not STORE.enabled or not path or not key or not os.path.isfile(path):
        return 0
    if sess.get("_tsync_path") != path:
        sess["_tsync_path"], sess["_tsync"] = path, 0
    start, end = sess["_tsync"], os.path.getsize(path)
    rows = [(str(r.get("uuid") or r.get("id") or f"o{pos}"), r) for pos, r in usage.lines(path, start, end)]
    n = STORE.insert_transcript(key, rows, AGENT_ID)
    sess["_tsync"] = end
    sess["_transcript_rows"] = sess.get("_transcript_rows", 0) + n
    return n


def stored_run(run: dict) -> dict:
    return {k: v for k, v in run.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- reply extraction

PROMPT_MARK = re.compile(r"^\s*[❯>›]\s?")
BULLET = re.compile(r"^\s*[●⏺•✦]\s?")
TIMING = re.compile(r"^\s*[✻✶✳✢·*]\s+\w+ for \d")
UI_NOISE = re.compile(r"^[\s─━│┃╭╮╰╯▐▛▜▌▝▘▗▖▄▀█░▒�>❯›•·⎿✻✶✳✢*\-=_|]*$")


def screen_reply(before: str, after: str, prompt: str) -> str:
    """The lines a turn added to the pane, minus box drawing and the echoed prompt. Lossy by nature."""
    a, b = before.splitlines(), after.splitlines()
    added: list[str] = []
    for op, _, _, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("insert", "replace"):
            added += b[j1:j2]
    echoed = {ln.strip() for ln in prompt.strip().splitlines()}
    keep = []
    for ln in added:
        bare = PROMPT_MARK.sub("", ln).strip()
        if UI_NOISE.match(ln) or bare in echoed or TIMING.match(ln):
            continue
        keep.append(BULLET.sub("", ln.rstrip()))
    return "\n".join(keep).strip()


HOOK_DIR = "/tmp/proto-agent-sessions"


def hook_session(pane_id: str) -> dict:
    """What gemini_session_hook.py recorded for this pane: Herdr 0.9.5 accepts a Gemini
    pane.report_agent_session and then keeps nothing, so agent.get cannot return it."""
    try:
        return json.load(open(os.path.join(HOOK_DIR, pane_id.replace(":", "_") + ".json")))
    except (OSError, ValueError):
        return {}


def gemini_transcript(hooked: dict) -> str | None:
    """Gemini's hook path, unless it names no file. On resume, Gemini 0.66.0's SessionStart hook
    reports a path named for the NEW start time, while the chat goes on in the original file."""
    path = hooked.get("transcript_path")
    if path and os.path.isfile(path):
        return path
    return find_transcript("gemini", hooked["session_id"]) if hooked.get("session_id") else path


def find_transcript(kind: str, agent_session_id: str) -> str | None:
    """The agent's own session file, located from the id Herdr's integration reported on agent.get."""
    home = os.path.expanduser("~")
    roots = {
        "claude": os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", home + "/.claude"), "projects", "*", f"{agent_session_id}.jsonl"),
        "codex": os.path.join(os.environ.get("CODEX_HOME", home + "/.codex"), "sessions", "**", f"*{agent_session_id}*.jsonl"),
        "pi": os.path.join(os.environ.get("PI_CODING_AGENT_DIR", home + "/.pi/agent"), "sessions", "**", f"*{agent_session_id}*.jsonl"),
        # named session-<start time>-<first 8 of the id>.jsonl, under the worktree's short name
        "gemini": os.path.join(os.environ.get("GEMINI_CLI_HOME", home), ".gemini", "tmp", "*", "chats", f"session-*-{agent_session_id[:8]}.jsonl"),
    }
    pattern = roots.get(kind)
    hits = sorted(glob.glob(pattern, recursive=True), key=os.path.getmtime) if pattern else []
    return hits[-1] if hits else None


def transcript_offset(path: str | None) -> int:
    """Where this turn starts in the agent's own JSONL, in bytes."""
    if not path or not os.path.isfile(path):
        return 0
    return os.path.getsize(path)


def transcript_reply(path: str, offset: int) -> str | None:
    """The last assistant text in the agent's own JSONL (Claude, Codex rollout, Pi). Best effort."""
    try:
        if not os.path.isfile(path):
            return None
        last = None
        with open(path, "rb") as f:
            f.seek(offset)
            tail = f.read().decode("utf-8", "replace")
        for line in tail.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            msg = r.get("message") if isinstance(r.get("message"), dict) else None
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else None
            cand = None
            if msg and msg.get("role") == "assistant":  # claude, pi
                cand = msg.get("content")
            elif payload and payload.get("type") == "message" and payload.get("role") == "assistant":  # codex
                cand = payload.get("content")
            elif payload and payload.get("type") == "agent_message":
                cand = payload.get("message")
            elif r.get("type") == "gemini":  # gemini chat JSONL
                cand = r.get("content")
            if cand is None:
                continue
            if isinstance(cand, str):
                text = cand
            else:
                text = "".join(p.get("text", "") for p in cand if isinstance(p, dict)
                               and p.get("type", "text") in ("text", "output_text"))
            if text.strip():
                last = text
        return last
    except OSError:
        return None


# --------------------------------------------------------------------------- the turn

def run_turn(sess: dict, run_id: str, prompt: str) -> None:
    target = sess["agent"]
    run = RUNS[run_id]
    t0 = time.time()
    try:
        before = screen(target)
        tpath = sess.get("_transcript_path")
        offset = transcript_offset(tpath)
        add_event(sess, run_id, "user", None, [{"type": "text", "text": prompt}])
        deadline = time.monotonic() + min(TURN_LIMIT_S, float(sess["options"].get("timeout_s") or TURN_LIMIT_S))
        final, seen = None, []
        r = herdr("agent.prompt", {"target": target, "text": prompt,
                                   "wait": {"until": ["idle", "done"], "timeout_ms": WAIT_SLICE_MS}},
                  timeout_s=WAIT_SLICE_MS / 1000 + 15)
        st = find_key(r, "agent_status") or find_key(r, "status")
        seen.append({"after": "agent.prompt", "status": st, "ms": int((time.time() - t0) * 1000)})
        while True:
            st, _ = status_of(target)
            if st in ("idle", "done"):
                final = st
                break
            if st == "blocked" and not run.get("_blocked_reported"):
                run["_blocked_reported"] = True
                add_event(sess, run_id, "system", "blocked",
                          [{"type": "text", "text": "the agent is waiting for input; attach over SSH to answer it",
                            "screen_tail": screen(target, 25)}])
            if time.monotonic() > deadline:
                final = "timed_out"
                break
            try:
                herdr("agent.wait", {"target": target, "until": ["idle", "done"],
                                     "timeout_ms": int(min(WAIT_SLICE_MS, max(1000, (deadline - time.monotonic()) * 1000)))},
                      timeout_s=WAIT_SLICE_MS / 1000 + 15)
            except HerdrError as e:
                if "timeout" not in e.code.lower() and "timeout" not in e.message.lower():
                    raise
        after = screen(target)
        st, info = status_of(target)
        sess["agent_status"] = st
        session_ref = find_key(info, "agent_session")
        if isinstance(session_ref, dict):
            if session_ref.get("kind") == "id" and session_ref.get("value"):
                sess["sdk_session_id"] = session_ref["value"]
            if session_ref.get("kind") == "path":
                sess["_transcript_path"] = session_ref.get("value")
                m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", session_ref.get("value") or "")
                if m and not sess.get("sdk_session_id"):
                    sess["sdk_session_id"] = m.group(1)
        if sess["kind"] == "gemini":
            hooked = hook_session(sess["pane_id"])
            sess["sdk_session_id"] = hooked.get("session_id") or sess.get("sdk_session_id")
            sess["_transcript_path"] = gemini_transcript(hooked) or sess.get("_transcript_path")
        if not sess.get("_transcript_path") and sess.get("sdk_session_id"):
            sess["_transcript_path"] = find_transcript(sess["kind"], sess["sdk_session_id"])
        text, source = None, "screen"
        if USE_TRANSCRIPT and sess.get("_transcript_path"):
            text = transcript_reply(sess["_transcript_path"], offset if sess["_transcript_path"] == tpath else 0)
            source = "transcript" if text else "screen"
        if text is None and run.get("_interrupt_sent") and source == "screen" and sess.get("_transcript_path"):
            # The agent's own record has no reply for an interrupted turn. The screen then holds only
            # the CLI's "interrupted" notice or its banner, and that is not a result.
            source = "none"
        elif text is None:
            text = screen_reply(before, after, prompt)
        u = usage.turn_usage(sess["kind"], sess.get("_transcript_path"),
                             offset if sess.get("_transcript_path") == tpath else 0)
        if u:
            run.update(usage=u["usage"], model_usage=u["model_usage"], cost_usd=u["cost_usd"], _calls=u["calls"],
                       _token_usage=u["token_usage"])
            sess["context_usage"] = usage.context_usage(u["context"]) or sess.get("context_usage")
            if u["context"] and u["context"].get("model"):
                sess["model"] = u["context"]["model"]
            if u["cost_usd"] is not None:
                sess["total_cost_usd"] = round((sess.get("total_cost_usd") or 0) + u["cost_usd"], 6)
        interrupted = bool(run.get("_interrupt_sent"))
        timed_out = final == "timed_out"
        stop_kind = "interrupted" if interrupted else "timed_out" if timed_out else None
        add_event(sess, run_id, "assistant", source, [{"type": "text", "text": text}])
        result = {"result": text, "is_error": timed_out, "interrupted": interrupted, "stop_kind": stop_kind,
                  "subtype": "error_during_execution" if timed_out else "success",
                  "result_source": source, "settled_as": final, "waits": seen}
        add_event(sess, run_id, "result", result["subtype"], [result])
        with LOCK:
            run.update(state="ended", finished_at=now_iso(), result_text=text, result_subtype=result["subtype"],
                       stop_kind=stop_kind, is_error=timed_out, interrupted=interrupted, timed_out=timed_out,
                       duration_ms=int((time.time() - t0) * 1000), sdk_session_id=sess.get("sdk_session_id"),
                       outcome_missing=stop_kind is None)
    except Exception as e:  # noqa: BLE001 -- a prototype records every failure as the run's outcome
        with LOCK:
            run.update(state="ended", finished_at=now_iso(), is_error=True, result_subtype="error_during_execution",
                       stop_kind="error", errors=[repr(e)], duration_ms=int((time.time() - t0) * 1000))
        add_event(sess, run_id, "result", "error_during_execution", [{"error": repr(e)}])
    finally:
        with LOCK:
            sess["turns"] += 1
            sess["last_used_at"] = time.time()
            if sess["status"] == "running":
                sess["status"] = "idle"
            sess["last_turn"] = {k: run.get(k) for k in ("sdk_session_id", "interrupted", "timed_out", "is_error",
                                                         "stop_kind", "duration_ms")} | {
                "outcome_recorded": True, "subtype": run.get("result_subtype")}
            sess["_turn"] = None
        STORE.finish_run(run)
        STORE.upsert_session(sess)
        sync_transcript(sess)
        run["_done"].set()


def run_response(sess: dict, run: dict) -> dict:
    events = [{"seq": e["seq"], "type": e["type"], "subtype": e["subtype"], "content": e["content"]}
              for e in EVENTS if e["run_id"] == run["run_id"]]
    return {"session_id": sess["session_id"], "sdk_session_id": sess.get("sdk_session_id"),
            "outcome_recorded": True, "result": run.get("result_text"), "is_error": bool(run.get("is_error")),
            "interrupted": bool(run.get("interrupted")), "stop_kind": run.get("stop_kind"),
            "subtype": run.get("result_subtype"), "stop_reason": None, "terminal_reason": None, "limit_hit": None,
            "num_turns": run.get("_calls"), "total_cost_usd": sess.get("total_cost_usd"),
            "turn_cost_usd": run.get("cost_usd"), "duration_ms": run.get("duration_ms"),
            "usage": run.get("usage"), "token_usage": run.get("_token_usage") or {k: None for k in usage.TOKEN_KEYS}, "model_usage": run.get("model_usage"), "permission_denials": None, "events": events}


# --------------------------------------------------------------------------- deployment

def deployment() -> dict:
    kind = DEFAULT_KIND
    try:
        ping = herdr("ping", {})
    except Exception:  # noqa: BLE001
        ping = {}
    version = str(find_key(ping, "version") or "unknown")
    protocol = find_key(ping, "protocol")
    claude = kind == "claude"
    return {
        "service": {"spec": {"document_version": DOCUMENT_VERSION}, "impl": IMPL,
                    "sdk": {"name": "herdr", "version": version}, "sdk_version": version},
        "config": {"workspace_dir": WORKSPACE, "reference_dirs": [], "default_model": "", "max_sessions": MAX_SESSIONS,
                   "require_credentials": False, "require_mounts": False, "auth_required": TOKEN is not None,
                   "allow_mcp_servers": "mcp_servers" in CARRIED[kind], "credential_sources": ["env"],
                   "provider_selectors": []},
        "accepts": {"permission_modes": [{"id": i, "name": n, "description": d} for i, n, d in MODES[kind]],
                    "default_permission_mode": DEFAULT_MODE[kind], "effort_levels": [],
                    "setting_sources": ["user", "project", "local"] if claude else [],
                    "default_allowed_tools": [], "always_disallowed_tools": [], "unsupported_options": unsupported(kind),
                    "strict_mcp_config": "strict_mcp_config" in CARRIED[kind],
                    "allow_supplied_sdk_session_id": kind in SUPPLIED_ID,
                    "mcp": {"transports": ["stdio", "http"] if claude else [], "http_headers": "any" if claude else "none"},
                    "limits": {}},
        "behaviour": {"limits": {"session_idle_ttl_s": IDLE_TTL_S},
                      "mcp_tool_call": {"request_timeout_s": None, "idle_timeout_s": None, "total_timeout_s": None,
                                        "progress_resets_idle": None},
                      "sandbox": {"network_access": True, "confines_writes_to_workspace": False},
                      "permission_enforcement": "none", "model_usage_scope": "per_turn", "reports_cost_usd": kind == "pi",
                      "usage_counts_tool_calls": None, "turn_token_overhead": None,
                      "llm_correlation": {"header": None, "measured": False},
                      "sdk_session_id_scope": "conversation", "resume_durability": "agent_local",
                      "query_reports_sdk_session_id": False, "query_consumes_a_session_slot": True,
                      # this document's additions to Behaviour (see info.x-changes-from-core)
                      "streaming": False,
                      "live_output": {"kind": "herdr-over-ssh", "ssh_port": SSH_PORT, "ssh_user": SSH_USER,
                                      "herdr_version": version, "herdr_protocol": protocol},
                      "agent_kinds": list(KINDS), "default_agent_kind": kind,
                      "token_usage_input_includes_cache": False,
                      "result_source": "transcript-then-screen" if USE_TRANSCRIPT else "screen"},
    }


# --------------------------------------------------------------------------- HTTP

class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None, ptype: str = "about:blank", **extra):
        self.body = {"type": ptype, "title": title, "status": status, "detail": detail, **extra}
        self.status = status


def invalid(loc: list, msg: str, typ: str = "value_error"):
    """A 422 in the document's ValidationProblem shape."""
    return Problem(422, "Validation failed", msg, ptype=P + "validation-failed",
                   errors=[{"loc": ["body", *loc], "msg": msg, "type": typ}])


UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def check_options(opts, loc: list) -> tuple[str, dict]:
    """RunOptions as the document declares it (422), then what this CLI cannot carry (400)."""
    if not isinstance(opts, dict):
        raise invalid(loc, "options must be an object", "dict_type")
    known = set(OPENAPI["components"]["schemas"]["RunOptions"]["properties"])
    extra = [k for k in opts if k not in known]
    if extra:
        raise invalid(loc + [extra[0]], f"unknown option {extra[0]!r}", "extra_forbidden")
    kind = opts.get("agent_kind") or DEFAULT_KIND
    if kind not in KINDS:
        raise invalid(loc + ["agent_kind"], f"agent_kind must be one of {list(KINDS)}", "enum")
    for f in ("model", "resume", "working_directory"):
        if opts.get(f) is not None and (not isinstance(opts[f], str) or not opts[f]):
            raise invalid(loc + [f], f"{f} must be a non-empty string", "string_type")
    if opts.get("timeout_s") is not None and (not isinstance(opts["timeout_s"], int) or opts["timeout_s"] < 1):
        raise invalid(loc + ["timeout_s"], "timeout_s must be an integer of at least 1", "greater_than_equal")
    opts = {k: v for k, v in opts.items() if k != "agent_kind"}
    bad = [e["field"] for e in unsupported(kind) if refused(e, opts.get(e["field"]))]
    if bad:
        raise Problem(400, "Unsupported options", f"{kind} cannot carry {bad}; see accepts.unsupported_options",
                      ptype=P + "unsupported-options")
    mode = opts.get("permission_mode")
    if mode is not None and mode not in {m[0] for m in MODES[kind]}:
        raise Problem(400, "Unknown permission mode",
                      f"{mode!r} is not one of {[m[0] for m in MODES[kind]]} for {kind}",
                      ptype=P + "unknown-permission-mode")
    return kind, opts


def open_session(body: dict) -> dict:
    kind, opts = check_options(body.get("options") if "options" in body else {}, ["options"])
    # `session_id` on the REQUEST is the deprecated spelling of `sdk_session_id` (SessionCreate).
    old, new = body.get("session_id"), body.get("sdk_session_id")
    if old is not None and new is not None and old != new:
        raise invalid(["sdk_session_id"], "session_id and sdk_session_id disagree")
    supplied = new if new is not None else old
    if supplied is not None:
        if kind not in SUPPLIED_ID:
            raise Problem(400, "Supplied session id not supported",
                          f"{kind} chooses its own session id; omit sdk_session_id",
                          ptype=P + "sdk-session-id-unsupported")
        if not isinstance(supplied, str) or not UUID_RE.match(supplied):
            raise Problem(400, "Invalid session id", "sdk_session_id must be a UUID")
        if opts.get("resume"):
            raise Problem(400, "Conflicting options", "sdk_session_id names a new conversation and "
                                                      "options.resume an old one; send one")
    cwd = opts.get("working_directory") or WORKSPACE
    if not os.path.isdir(cwd):
        raise Problem(400, "No such working directory", cwd)
    with LOCK:
        live = [s for s in SESSIONS.values() if s["status"] != "closed"]
        if len(live) >= MAX_SESSIONS:
            raise Problem(429, "Too many sessions", f"max_sessions is {MAX_SESSIONS} and all are open")
        for s in live:
            if WORKTREE_LOCK and s["cwd"] == cwd:
                raise Problem(409, "Worktree in use", f"session {s['session_id']} ({s['kind']}) holds {cwd}",
                              ptype=P + "worktree-in-use")
        sid = uuid.uuid4().hex
        sess = {"session_id": sid, "kind": kind, "cwd": cwd, "options": opts, "status": "idle",
                "created_at": time.time(), "last_used_at": time.time(), "turns": 0, "last_turn": None,
                "_turn": None, "_gen": 0}
        SESSIONS[sid] = sess  # holds its slot and its worktree while the TUI starts
    try:
        spawn(sess, opts, supplied)
    except BaseException:
        with LOCK:
            SESSIONS.pop(sid, None)
        raise
    sess["status"] = "idle"
    STORE.upsert_session(sess)
    return sess


def close_agent(sess: dict) -> None:
    for call, params in (("pane.close", {"pane_id": sess.get("pane_id")}),
                         ("workspace.close", {"workspace_id": sess.get("workspace_id")})):
        try:
            herdr(call, params)
        except Exception:  # noqa: BLE001 -- already gone is fine
            pass


def forget(sess: dict) -> None:
    """Close the agent and drop the session: a closed session is a 404, as in agent-service."""
    close_agent(sess)
    sync_transcript(sess)
    with LOCK:
        sess["status"] = "closed"
        SESSIONS.pop(sess["session_id"], None)
    STORE.upsert_session(sess)


def patch_session(sess: dict, body: dict) -> dict:
    """SessionUpdate. A TUI's options are fixed at launch, so the agent is restarted with the new
    ones, resuming its own conversation when it has one."""
    upd = {k: body.get(k) for k in ("model", "permission_mode") if body.get(k) is not None}
    for k, v in upd.items():
        if not isinstance(v, str) or not v:
            raise invalid([k], f"{k} must be a non-empty string", "string_type")
    kind = sess["kind"]
    new = dict(sess["options"], **upd)
    check_options(dict(new, agent_kind=kind), ["options"])
    with LOCK:
        if sess["_turn"]:
            raise Problem(409, "Session busy", f"run {sess['_turn']} is under way", ptype=P + "session-busy")
        sess["_turn"] = "patch"
    try:
        close_agent(sess)
        sdk = sess.get("sdk_session_id")
        has_history = bool(sdk and (find_transcript(kind, sdk) or sess.get("_transcript_path")))
        launch_opts = dict(new, resume=sdk if has_history else None)
        spawn(sess, launch_opts, None if has_history else (sdk if kind in SUPPLIED_ID else None))
        sess["options"] = new
        if "model" in upd:
            sess["model"] = upd["model"]
    finally:
        with LOCK:
            sess["_turn"] = None
    STORE.upsert_session(sess)
    return sess


def reaper() -> None:
    """Close sessions idle for longer than `limits.session_idle_ttl_s`."""
    while True:
        time.sleep(30)
        cutoff = time.time() - IDLE_TTL_S
        with LOCK:
            stale = [s for s in SESSIONS.values() if s["status"] == "idle" and not s["_turn"]
                     and s["last_used_at"] < cutoff]
        for s in stale:
            forget(s)


def spawn(sess: dict, opts: dict, supplied: str | None) -> None:
    """Start the session's CLI in a fresh Herdr workspace and wait until it reads ready."""
    kind, cwd, sid = sess["kind"], sess["cwd"], sess["session_id"]
    sess["_gen"] = sess.get("_gen", 0) + 1
    args, env, chosen = launch(kind, opts, sid, supplied, cwd)
    seed_trust(kind, cwd)
    ws = herdr("workspace.create", {"cwd": cwd, "env": env, "label": f"{kind}:{sid[:8]}"})
    pane = find_key(ws, "root_pane")
    pane_id = (pane or {}).get("pane_id") or find_key(ws, "pane_id")
    ws_id = find_key(ws, "workspace_id")
    name = f"{kind}-{sid[:8]}" + (f"-{sess['_gen']}" if sess["_gen"] > 1 else "")
    sess.update(pane_id=pane_id, workspace_id=ws_id, agent=name)
    started = herdr("agent.start", {"name": name, "kind": kind, "pane_id": pane_id, "args": args,
                                    "timeout_ms": START_LIMIT_MS}, timeout_s=START_LIMIT_MS / 1000 + 10)
    # A fresh TUI takes a moment to draw; wait until Herdr reads it as ready or blocked.
    st = "unknown"
    t_end = time.monotonic() + 45
    settled_since = None
    while time.monotonic() < t_end:
        st, info = status_of(name)
        ready = find_key(info, "interactive_ready") and not find_key(info, "launch_pending")
        if st == "blocked":
            break
        if ready and st in ("idle", "done"):
            # A TUI can draw a first-run dialog a beat after it first reads idle; require 2 s of quiet.
            settled_since = settled_since or time.monotonic()
            if time.monotonic() - settled_since >= 2:
                break
            time.sleep(0.5)
            continue
        settled_since = None
        try:
            herdr("agent.wait", {"target": name, "until": ["idle", "done", "blocked"], "timeout_ms": 5000}, timeout_s=20)
        except HerdrError:
            pass
    sess.update(args=args, agent_status=st, _start=started,
                sdk_session_id=chosen or sess.get("sdk_session_id"))
    if st == "blocked":
        sess["start_screen"] = screen(name, 30)
    if kind == "gemini":  # its SessionStart hook has fired by now
        hooked = hook_session(pane_id)
        sess["sdk_session_id"] = hooked.get("session_id") or sess["sdk_session_id"]
        sess["_transcript_path"] = gemini_transcript(hooked) or sess.get("_transcript_path")
    elif sess["sdk_session_id"]:
        # A resumed conversation's file already exists: knowing it now makes the first turn's usage
        # start at this turn's byte offset, not at the start of the whole conversation.
        sess["_transcript_path"] = find_transcript(kind, sess["sdk_session_id"]) or sess.get("_transcript_path")


def start_turn(sess: dict, body: dict) -> dict:
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise invalid(["prompt"], "prompt is required", "missing")
    run_id = body.get("run_id") or uuid.uuid4().hex
    if not isinstance(run_id, str) or not RUN_ID.match(run_id):
        raise invalid(["run_id"], "run_id does not match its pattern", "string_pattern_mismatch")
    with LOCK:
        if run_id in RUNS:
            raise Problem(409, "Run id in use", run_id, ptype=P + "run-id-in-use")
        if sess["status"] == "closed":
            raise Problem(404, "Session closed", sess["session_id"])
        if sess["_turn"]:
            raise Problem(409, "Session busy", f"run {sess['_turn']} is under way", ptype=P + "session-busy")
        run = {"run_id": run_id, "session_id": sess["session_id"], "sdk_session_id": sess.get("sdk_session_id"),
               "started_at": now_iso(), "finished_at": None, "prompt": prompt, "state": "running",
               "interrupted": False, "timed_out": False, "outcome_missing": False, "_seq": 0,
               "_done": threading.Event()}
        RUNS[run_id] = run
        sess["_turn"] = run_id
        sess["status"] = "running"
    STORE.upsert_session(sess)
    STORE.insert_run(run)
    threading.Thread(target=run_turn, args=(sess, run_id, prompt), daemon=True).start()
    return run


def run_options_schema(kind: str) -> dict:
    """`accepts` rendered as JSON Schema 2020-12: what this CLI takes, and the refusals by name."""
    comp = OPENAPI["components"]["schemas"]
    ro = json.loads(json.dumps(comp["RunOptions"]))
    plain = [e["field"] for e in unsupported(kind) if not e.get("types") and not e.get("values")]
    for f in plain:
        ro["properties"].pop(f, None)
    if "system_prompt" in ro["properties"]:  # the object (preset) form is refused
        ro["properties"]["system_prompt"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    if "include_raw" in ro["properties"]:
        ro["properties"]["include_raw"] = {"anyOf": [{"const": False}, {"type": "null"}]}
    ro["properties"]["permission_mode"] = {
        "oneOf": [{"const": i, "title": n, "description": d} for i, n, d in MODES[kind]],
        "default": DEFAULT_MODE[kind]}
    ro["properties"]["agent_kind"] = {"const": kind}
    ro["allOf"] = [{"not": {"required": [f]}} for f in plain]
    defs: dict = {}

    def walk(o):
        if isinstance(o, dict):
            ref = o.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                o["$ref"] = f"#/$defs/{name}"
                if name not in defs:
                    defs[name] = json.loads(json.dumps(comp[name]))
                    walk(defs[name])
            for v in list(o.values()):
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(ro)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"RunOptions ({kind})",
            **ro, "$defs": defs}


def no_history() -> Problem:
    return Problem(404, "Persistence disabled", "history needs a database: set AGENT_SERVICE_DATABASE_URL",
                   ptype=P + "persistence-disabled")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "herdr-all-in-one/0"

    def log_message(self, fmt, *a):
        sys.stderr.write(f"{self.command} {self.path} {fmt % a}\n")

    def _send(self, status: int, body=None, headers=None):
        headers = dict(headers or {})
        raw = headers.pop("_raw", None)
        out = raw if raw is not None else (b"" if body is None else json.dumps(body, default=str).encode())
        ctype = headers.pop("content-type", "application/problem+json" if status >= 400 else "application/json")
        self.send_response(status)
        if out:
            self.send_header("content-type", ctype)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _body(self) -> dict:
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if not raw:
            return {}
        try:
            v = json.loads(raw)
        except ValueError:
            raise invalid([], "body is not JSON", "json_invalid")
        if not isinstance(v, dict):
            raise invalid([], "body is not an object", "dict_type")
        return v

    def _session(self, sid: str) -> dict:
        with LOCK:
            s = SESSIONS.get(sid)
        if not s:
            raise Problem(404, "No such session", sid)
        return s

    def _route(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        m = self.command
        if parts == ["healthz"]:
            return 200, {"status": "ok", "credentials_configured": True, "workspace_dir": WORKSPACE,
                         "auth_required": TOKEN is not None, "database_configured": STORE.enabled,
                         "database_usable": STORE.usable() if STORE.enabled else None}
        if parts == ["openapi.json"] and m == "GET":
            return 200, None, {"_raw": OPENAPI_BYTES}
        if TOKEN and self.headers.get("authorization") != f"Bearer {TOKEN}":
            raise Problem(401, "Unauthorized")
        if parts[:1] != ["v1"]:
            raise Problem(404, "Not found")
        p = parts[1:]
        if p == ["deployment"] and m == "GET":
            return 200, deployment()
        if p == ["schemas", "run-options"] and m == "GET":
            return 200, run_options_schema(DEFAULT_KIND), {"content-type": "application/schema+json"}
        if p == ["sessions"] and m == "GET":
            with LOCK:
                return 200, {"sessions": [record(s) for s in SESSIONS.values()]}
        if p == ["sessions"] and m == "POST":
            return 201, record(open_session(self._body()))
        is_transcript = p[:1] == ["sessions"] and len(p) == 3 and p[2] == "transcript" and m == "GET"
        is_run = p[:1] == ["runs"] and len(p) == 2 and m == "GET"
        if (is_transcript or is_run) and not STORE.enabled:
            raise no_history()  # history is the database's, as in agent-service: checked before any lookup
        if is_transcript and p[1] not in SESSIONS:
            if not STORE.has_session(p[1]):  # from before a restart, the events are in the database
                raise Problem(404, "No such session", p[1])
            after, limit = int(q.get("after", ["0"])[0]), min(int(q.get("limit", ["1000"])[0]), 1000)
            rows = STORE.events_of_session(p[1], after, limit + 1)
            return 200, {"session_id": p[1], "events": rows[:limit],
                         "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}
        if p[:1] == ["sessions"] and len(p) >= 2:
            if p[2:] == ["messages", "stream"]:
                raise Problem(501, "Streaming not supported", "behaviour.streaming is false; use POST .../messages, "
                              "or attach a Herdr client over SSH to watch", ptype=P + "streaming-not-supported")
            sess = self._session(p[1])
            rest = p[2:]
            if not rest and m == "GET":
                return 200, record(sess)
            if not rest and m == "DELETE":
                forget(sess)
                return 204, None
            if not rest and m == "PATCH":
                return 200, record(patch_session(sess, self._body()))
            if rest == ["messages"] and m == "POST":
                body = self._body()
                run = start_turn(sess, body)
                run["_done"].wait()  # a disconnect cancels nothing: the turn finishes either way
                resp = run_response(sess, run)
                hdr = {"x-sdk-session-id": resp["sdk_session_id"]} if resp.get("sdk_session_id") else {}
                return 200, resp, hdr
            if rest == ["interrupt"] and m == "POST":
                with LOCK:
                    turn = sess["_turn"] if sess["_turn"] in RUNS else None
                if turn:
                    RUNS[turn]["_interrupt_sent"] = True
                    herdr("agent.send_keys", {"target": sess["agent"], "keys": ["esc"]})
                return 200, {"interrupted": bool(turn), "status": sess["status"]}
            if rest == ["transcript"] and m == "GET":
                after = int(q.get("after", ["0"])[0])
                limit = min(int(q.get("limit", ["1000"])[0]), 1000)
                with LOCK:
                    mine = [e for e in EVENTS if e["_sid"] == sess["session_id"] and e["id"] > after]
                page = mine[:limit]
                return 200, {"session_id": sess["session_id"],
                             "events": [{k: v for k, v in e.items() if not k.startswith("_")} for e in page],
                             "next_after": page[-1]["id"] if len(mine) > limit else None}
        if is_run:
            with LOCK:
                run = RUNS.get(p[1])
            if not run:
                found = STORE.get_run(p[1])
                if found:
                    return 200, found
                raise Problem(404, "No such run", p[1])
            return 200, stored_run(run)
        if p == ["query", "stream"]:
            raise Problem(501, "Streaming not supported", "behaviour.streaming is false; use POST /v1/query",
                          ptype=P + "streaming-not-supported")
        if p == ["query"] and m == "POST":
            body = self._body()
            sess = open_session({"options": body.get("options") if "options" in body else {}})
            try:
                run = start_turn(sess, body)
                run["_done"].wait()
                return 200, run_response(sess, run)
            finally:
                forget(sess)
        if p[:2] == ["proto", "agent-transcript"] and len(p) == 3 and m == "GET":
            # prototype-only: the agent's OWN transcript lines, as saved in transcript_entries
            sess = self._session(p[2])
            sync_transcript(sess)
            key = transcript_key(sess)
            after, limit = int(q.get("after", ["0"])[0]), min(int(q.get("limit", ["1000"])[0]), 1000)
            return 200, {"session_key": key, "entries": STORE.transcript_entries(key, after, limit) if key else [],
                         "persisted": STORE.enabled, "store_error": STORE.last_error}
        if p == ["proto", "socket-log"] and m == "GET":  # prototype-only: what the socket was asked
            return 200, {"calls": SOCKET_LOG[-200:]}
        raise Problem(404, "Not found", u.path)

    def _any(self):
        try:
            status, body, *hdr = self._route()
            self._send(status, body, hdr[0] if hdr else None)
        except Problem as p:
            self._send(p.status, p.body)
        except HerdrError as e:
            self._send(502, {"type": P + "herdr", "title": "Herdr refused", "status": 502,
                             "detail": str(e), "herdr_code": e.code})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"type": "about:blank", "title": "Internal error", "status": 500, "detail": repr(e)})

    do_GET = do_POST = do_DELETE = do_PATCH = do_PUT = _any


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=reaper, daemon=True).start()
    sys.stderr.write(f"herdr-all-in-one listening on :{port}, socket {SOCKET}, default agent {DEFAULT_KIND}, "
                     f"document {DOCUMENT_VERSION}\n")
    srv.serve_forever()
