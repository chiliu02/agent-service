"""Gemini CLI SessionStart hook: report the pane's agent session to Herdr.

Herdr ships this integration for Claude Code, Codex and Pi, not for Gemini.
This does what Herdr's Claude hook does: read the hook's JSON input, then send
`pane.report_agent_session` to the socket named by HERDR_SOCKET_PATH. Herdr 0.9.5
answers `ok` to that and keeps nothing for gemini, so the hook also writes the id
and transcript path to /tmp/proto-agent-sessions/<pane>.json for the shim.

It never fails the agent: every error exits 0, and stdout is always `{}`.
"""
import json
import os
import socket
import sys
import time


def main() -> None:
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return
    pane, path = os.environ.get("HERDR_PANE_ID"), os.environ.get("HERDR_SOCKET_PATH")
    sid = hook.get("session_id")
    if os.environ.get("HERDR_ENV") != "1" or not pane or not path or not isinstance(sid, str) or not sid:
        return
    params = {"pane_id": pane, "source": "proto:gemini", "agent": "gemini", "seq": time.time_ns(),
              "agent_session_id": sid}
    if isinstance(hook.get("transcript_path"), str) and hook["transcript_path"]:
        params["agent_session_path"] = hook["transcript_path"]
    # Herdr 0.9.5 answers ok and keeps nothing for gemini, so the shim reads this file instead.
    os.makedirs("/tmp/proto-agent-sessions", exist_ok=True)
    with open(f"/tmp/proto-agent-sessions/{pane.replace(':', '_')}.json", "w") as f:
        json.dump({"session_id": sid, "transcript_path": hook.get("transcript_path")}, f)
    request = {"id": f"proto:gemini:{time.time_ns()}", "method": "pane.report_agent_session", "params": params}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        s.connect(path)
        s.sendall((json.dumps(request) + "\n").encode())
        try:
            s.recv(4096)
        except OSError:
            pass


try:
    main()
except Exception:  # noqa: BLE001 -- a hook must never break the agent
    pass
print("{}")
