"""Stopping the processes an agent's tools started, found by their tag.

Most of this runs against a fake `/proc`, so it runs on any platform. The last
test runs real processes and needs Linux, which is where the image runs.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_service import processes
from agent_service.processes import (
    TAG_ENV_VAR,
    agent_sessions,
    find_tagged,
    new_tag,
    stop_tagged,
    tag_of,
)


def _proc(root: Path, pid: int, *, ppid: int, sid: int, env: dict[str, str],
          state: str = "S", comm: str = "sh") -> None:
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "environ").write_bytes(
        b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0"
    )
    # pid (comm) state ppid pgrp session ...
    (d / "stat").write_text(f"{pid} ({comm}) {state} {ppid} {pid} {sid} 0 -1 0")


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    (root / "self").mkdir()  # not a pid: ignored
    return root


def test_finds_only_its_own_tag(proc: Path) -> None:
    _proc(proc, 10, ppid=1, sid=1, env={TAG_ENV_VAR: "a", "PATH": "/bin"})
    _proc(proc, 11, ppid=10, sid=11, env={TAG_ENV_VAR: "a"})
    _proc(proc, 12, ppid=1, sid=12, env={TAG_ENV_VAR: "ab"})
    _proc(proc, 13, ppid=1, sid=13, env={"PATH": "/bin"})
    assert sorted(p.pid for p in find_tagged("a", proc_root=proc)) == [10, 11]


def test_a_prefix_finds_every_turn_of_a_session(proc: Path) -> None:
    _proc(proc, 10, ppid=1, sid=10, env={TAG_ENV_VAR: "s1.turn1"})
    _proc(proc, 11, ppid=1, sid=11, env={TAG_ENV_VAR: "s1.turn2"})
    _proc(proc, 12, ppid=1, sid=12, env={TAG_ENV_VAR: "s10.turn1"})
    found = find_tagged("s1.", prefix=True, proc_root=proc)
    assert sorted(p.pid for p in found) == [10, 11]


def test_an_orphan_is_found_by_its_session_not_its_parent(proc: Path) -> None:
    """The case that was measured: the shell is gone, the command is PID 1's."""
    _proc(proc, 104, ppid=1, sid=102, env={TAG_ENV_VAR: "t"}, comm="tail")
    [p] = find_tagged("t", proc_root=proc)
    assert (p.pid, p.ppid, p.sid) == (104, 1, 102)


def test_a_comm_with_a_parenthesis_does_not_shift_the_fields(proc: Path) -> None:
    _proc(proc, 20, ppid=7, sid=9, env={TAG_ENV_VAR: "t"}, comm="a) b (c")
    [p] = find_tagged("t", proc_root=proc)
    assert (p.ppid, p.sid) == (7, 9)


def test_zombies_are_skipped(proc: Path) -> None:
    _proc(proc, 30, ppid=1, sid=30, env={TAG_ENV_VAR: "t"}, state="Z")
    assert find_tagged("t", proc_root=proc) == []


def test_no_proc_finds_nothing_and_stops_nothing(tmp_path: Path) -> None:
    assert find_tagged("t", proc_root=tmp_path / "absent") == []
    assert stop_tagged("t", proc_root=tmp_path / "absent") == 0


def test_tag_of(proc: Path) -> None:
    _proc(proc, 40, ppid=1, sid=40, env={"A": "1", TAG_ENV_VAR: "s1.x"})
    assert tag_of(40, proc_root=proc) == "s1.x"
    assert tag_of(41, proc_root=proc) is None


def test_new_tags_differ_and_keep_their_prefix() -> None:
    a, b = new_tag("s1."), new_tag("s1.")
    assert a != b and a.startswith("s1.") and b.startswith("s1.")


def _record_kills(monkeypatch: pytest.MonkeyPatch, proc: Path) -> list[int]:
    """`os.kill` that removes the fake process, as a real kill would."""
    killed: list[int] = []

    def kill(pid: int, sig: int) -> None:
        assert sig == processes._SIGKILL == 9
        killed.append(pid)
        shutil.rmtree(proc / str(pid))

    monkeypatch.setattr(processes.os, "kill", kill)
    return killed


def test_an_interrupt_spares_the_agent_and_stops_the_tools(
    proc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The agent and an MCP server it started, before any tool ran.
    _proc(proc, 18, ppid=1, sid=1, env={TAG_ENV_VAR: "t"}, comm="claude")
    _proc(proc, 19, ppid=18, sid=1, env={TAG_ENV_VAR: "t"}, comm="mcp")
    spare = agent_sessions("t", proc_root=proc)
    assert spare == frozenset({1})
    # Then a tool: a shell in a session of its own, and its orphaned command.
    _proc(proc, 102, ppid=18, sid=102, env={TAG_ENV_VAR: "t"}, comm="bash")
    _proc(proc, 104, ppid=1, sid=102, env={TAG_ENV_VAR: "t"}, comm="tail")
    killed = _record_kills(monkeypatch, proc)
    assert stop_tagged("t", spare_sessions=spare, proc_root=proc) == 2
    assert sorted(killed) == [102, 104]
    assert sorted(p.pid for p in find_tagged("t", proc_root=proc)) == [18, 19]


def test_a_close_stops_everything_tagged_and_nothing_else(
    proc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _proc(proc, 18, ppid=1, sid=1, env={TAG_ENV_VAR: "t"})
    _proc(proc, 104, ppid=1, sid=102, env={TAG_ENV_VAR: "t"})
    _proc(proc, 200, ppid=1, sid=200, env={TAG_ENV_VAR: "other"})
    killed = _record_kills(monkeypatch, proc)
    assert stop_tagged("t", proc_root=proc) == 2
    assert sorted(killed) == [18, 104]
    assert (proc / "200").exists()


def test_a_process_that_will_not_die_does_not_hold_the_caller(
    proc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _proc(proc, 50, ppid=1, sid=50, env={TAG_ENV_VAR: "t"})
    calls: list[int] = []
    monkeypatch.setattr(processes.os, "kill", lambda pid, sig: calls.append(pid))
    stop_tagged("t", proc_root=proc)
    assert len(calls) == processes._MAX_PASSES


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc")
def test_real_processes_in_their_own_sessions_are_stopped() -> None:
    """The measured shape, with real processes: a shell that is the leader of a
    new session, and a command in a process group of its own inside it."""
    tag = new_tag()
    env = {**os.environ, TAG_ENV_VAR: tag}
    shell = subprocess.Popen(
        ["setsid", "sh", "-c", "setsid sleep 300 & wait"], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if len(find_tagged(tag)) >= 2:
                break
            time.sleep(0.05)
        assert len(find_tagged(tag)) >= 2
        stop_tagged(tag)
        shell.wait(timeout=5)
        for _ in range(50):
            if not find_tagged(tag):
                break
            time.sleep(0.05)
        assert find_tagged(tag) == []
    finally:
        if shell.poll() is None:
            shell.kill()
