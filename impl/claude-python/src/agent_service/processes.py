"""Stopping every process an agent's tools started (CP-159).

**Found by an environment tag, not by the process tree.** The agent starts a
tool's shell as the leader of a new session, and the command inside it in a
process group of its own; when the agent stops the shell, the command is
re-parented to PID 1. Neither a group kill nor a walk of the agent's children
reaches it. What it keeps is its environment, which it inherited from the agent
at `exec` -- so every process this service's agent started carries
`AGENT_SERVICE_PROCESS_TAG`, and `/proc/<pid>/environ` names it.

**Linux only**, which is where the image runs. Without `/proc` every function
here finds nothing and stops nothing, so a test on another platform is not
misled into thinking the guarantee holds there.

**What escapes it**: a process that replaced its own environment (`env -i`,
or an `exec` with a fresh one). The agent's tools do not do that.
"""

from __future__ import annotations

import os
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The variable every process of one agent carries.
TAG_ENV_VAR = "AGENT_SERVICE_PROCESS_TAG"

#: A process killed between two scans can fork once more, so a sweep scans
#: again until it finds nothing. Bounded so a fork bomb cannot hold a request.
_MAX_PASSES = 5

_PROC = Path("/proc")

#: `signal.SIGKILL` does not exist off POSIX, where nothing is found anyway.
_SIGKILL = getattr(signal, "SIGKILL", 9)


def new_tag(prefix: str = "") -> str:
    """A tag no other agent in this container carries."""
    return f"{prefix}{uuid.uuid4().hex}"


@dataclass(frozen=True)
class TaggedProcess:
    pid: int
    ppid: int
    sid: int


def _read(entry: Path) -> tuple[bytes, str] | None:
    try:
        return (entry / "environ").read_bytes(), (entry / "stat").read_text()
    except OSError:
        # Gone between the listing and the read, or not ours to read.
        return None


def find_tagged(tag: str, *, prefix: bool = False,
                proc_root: Path = _PROC) -> list[TaggedProcess]:
    """Every live process whose tag is `tag` (or starts with it, if `prefix`).

    Zombies are skipped: they are already dead, and a kill does nothing to them.
    """
    if not proc_root.is_dir():
        return []
    needle = f"{TAG_ENV_VAR}={tag}".encode()
    own = os.getpid()
    found: list[TaggedProcess] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        read = _read(entry)
        if read is None:
            continue
        environ, stat = read
        if not any(
            (var.startswith(needle) if prefix else var == needle)
            for var in environ.split(b"\0")
        ):
            continue
        # `comm` is in parentheses and may itself contain ") ", so split after
        # the LAST one: state, ppid, pgrp, session follow it.
        fields = stat[stat.rindex(")") + 2:].split()
        if fields[0] in ("Z", "X"):
            continue
        found.append(TaggedProcess(int(entry.name), int(fields[1]), int(fields[3])))
    return found


def tag_of(pid: int, *, proc_root: Path = _PROC) -> str | None:
    """The tag process `pid` carries, or `None`."""
    try:
        environ = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    needle = f"{TAG_ENV_VAR}=".encode()
    for var in environ.split(b"\0"):
        if var.startswith(needle):
            return var[len(needle):].decode("utf-8", "replace")
    return None


def agent_sessions(tag: str, *, proc_root: Path = _PROC) -> frozenset[int]:
    """The sessions of the agent itself: what an interrupt must not stop.

    **Call it once, right after the agent starts and before it can run a tool.**
    At that moment every tagged process is the agent or something it started for
    itself -- an MCP server, a helper -- and none is a tool's. Afterwards that
    cannot be told apart: without an init, an orphaned tool command is
    re-parented to PID 1, which is this service, and looks like the agent.
    """
    return frozenset(p.sid for p in find_tagged(tag, proc_root=proc_root))


def stop_tagged(tag: str, *, prefix: bool = False,
                spare_sessions: frozenset[int] = frozenset(),
                proc_root: Path = _PROC) -> int:
    """`SIGKILL` every process carrying `tag`. Returns how many. **Never raises.**

    `spare_sessions` keeps the agent alive on a build whose agent outlives the
    turn: pass `agent_sessions()`. A tool's shell is always the leader of a
    session of its own, so it is never in that set.
    """
    killed = 0
    for _ in range(_MAX_PASSES):
        found = [p for p in find_tagged(tag, prefix=prefix, proc_root=proc_root)
                 if p.sid not in spare_sessions]
        if not found:
            break
        for p in found:
            try:
                os.kill(p.pid, _SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError, OSError):
                pass
    return killed
