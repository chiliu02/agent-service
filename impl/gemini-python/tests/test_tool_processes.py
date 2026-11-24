"""An interrupt and a close stop every process the session's agent started (GP-82).

No shell reaches this agent today, but a process that leaves the agent's group
would outlive the group kill, so the guarantee does not rest on that. No agent
runs here: `stop_tagged` and `tag_of` are recorded or stubbed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service import cli as cli_module
from agent_service import registry as registry_module
from agent_service.cli import CliRunner, kill_process_tree
from agent_service.config import Settings
from agent_service.processes import TAG_ENV_VAR
from agent_service.registry import Registry


def _runner(tmp_path: Path, **kwargs) -> CliRunner:
    return CliRunner(binary=Path("gemini"), workspace=tmp_path, home=tmp_path / "home", **kwargs)


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


def test_killing_the_agent_also_stops_what_it_started(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(cli_module, "tag_of", lambda pid: order.append(f"read {pid}") or "s1.t")
    monkeypatch.setattr(cli_module, "_kill_group", lambda proc: order.append("killpg"))
    monkeypatch.setattr(cli_module, "stop_tagged", lambda tag: order.append(f"sweep {tag}"))
    kill_process_tree(_Proc())
    assert order == ["read 4242", "killpg", "sweep s1.t"]


def test_a_close_stops_every_turn_of_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    swept: list[tuple[str, bool]] = []
    monkeypatch.setattr(registry_module, "stop_tagged",
                        lambda tag, *, prefix=False: swept.append((tag, prefix)))
    settings = Settings(workspace_dir=tmp_path / "workspace",
                        agent_home_root=tmp_path / "homes",
                        transcript_store=tmp_path / "store",
                        gemini_binary=Path("gemini-not-installed"),
                        require_credentials=False)
    registry = Registry(settings)
    session = registry.create()
    registry.close(session.session_id)
    assert swept == [(f"{session.session_id}.", True)]
