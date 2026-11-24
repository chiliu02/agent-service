"""An interrupt and a close stop every process the session's tools started (PI-70).

Pi starts its `bash` tool as the leader of a new session, so the group kill an
interrupt has always done misses the shell and its command. No agent runs here:
`stop_tagged` and `tag_of` are recorded or stubbed, so this needs no Linux.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service import pi as pi_module
from agent_service import registry as registry_module
from agent_service.config import Settings
from agent_service.pi import PiRunner, kill_process_tree
from agent_service.processes import TAG_ENV_VAR
from agent_service.registry import Registry


def _runner(tmp_path: Path, **kwargs) -> PiRunner:
    return PiRunner(binary=Path("pi"), workspace=tmp_path,
                    agent_dir=tmp_path / "agent",
                    session_dir=tmp_path / "sessions", **kwargs)


def test_each_spawn_gets_its_own_tag_under_the_session_prefix(tmp_path: Path) -> None:
    runner = _runner(tmp_path, process_tag_prefix="s1.")
    a, b = runner.env()[TAG_ENV_VAR], runner.env()[TAG_ENV_VAR]
    assert a.startswith("s1.") and b.startswith("s1.") and a != b


def test_no_prefix_no_tag(tmp_path: Path) -> None:
    assert TAG_ENV_VAR not in _runner(tmp_path).env()


class _Proc:
    pid = 4242
    returncode = None

    def kill(self) -> None:
        pass


def test_killing_the_agent_also_stops_what_its_tools_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(pi_module, "tag_of", lambda pid: order.append(f"read {pid}") or "s1.t")
    monkeypatch.setattr(pi_module, "_kill_group", lambda proc: order.append("killpg"))
    monkeypatch.setattr(pi_module, "stop_tagged", lambda tag: order.append(f"sweep {tag}"))
    kill_process_tree(_Proc())
    # The tag is read while the agent can still be read, then the sweep follows.
    assert order == ["read 4242", "killpg", "sweep s1.t"]


def test_an_untagged_agent_is_still_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[object] = []
    monkeypatch.setattr(pi_module, "tag_of", lambda pid: None)
    monkeypatch.setattr(pi_module, "_kill_group", killed.append)
    monkeypatch.setattr(pi_module, "stop_tagged",
                        lambda tag: pytest.fail("nothing to sweep"))
    kill_process_tree(proc := _Proc())
    assert killed == [proc]


def test_a_close_stops_every_turn_of_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    swept: list[tuple[str, bool]] = []
    monkeypatch.setattr(registry_module, "stop_tagged",
                        lambda tag, *, prefix=False: swept.append((tag, prefix)))
    settings = Settings(workspace_dir=tmp_path / "workspace",
                        agent_dir_root=tmp_path / "agent-dirs",
                        session_store=tmp_path / "sessions",
                        pi_binary=Path("pi-not-installed"),
                        require_credentials=False)
    registry = Registry(settings)
    session = registry.create()
    registry.close(session.session_id)
    assert swept == [(f"{session.session_id}.", True)]
