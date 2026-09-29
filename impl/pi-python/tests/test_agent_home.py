"""The agent directory: a root of minted directories, and the seed that reaches them.

**Free: nothing is spawned.** A session here is directories and a lock, so
everything below is a path on disk or a refusal.

`PI-58` is the entry. What this pins is the distinction a consumer cannot see
from outside: the directory the published variable names is a PARENT, so a file
written into it reaches no turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.config import Settings, UnusableAgentHomeSeed, check_boot
from agent_service.registry import Registry


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_dir_root": tmp_path / "agent-dirs",
        "session_store": tmp_path / "sessions",
        "pi_binary": Path("pi-not-installed"),
        "require_credentials": False,
    }
    return Settings(**{**base, **kwargs})


def _seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    (seed / "user.md").write_text("the user's own preferences\n")
    return seed


def test_the_agent_dir_is_a_child_of_the_root_and_the_root_holds_nothing(
    tmp_path: Path,
) -> None:
    """`PI-58`. The correction: a file at the root reaches no agent."""
    settings = _settings(tmp_path)
    settings.agent_dir_root.mkdir(parents=True)
    (settings.agent_dir_root / "user.md").write_text("never read\n")

    session = Registry(settings).create()

    assert session.agent_dir.parent == settings.agent_dir_root
    assert session.agent_dir != settings.agent_dir_root
    assert not (session.agent_dir / "user.md").exists()


def test_a_seed_is_copied_into_every_minted_agent_dir(tmp_path: Path) -> None:
    """`PI-58`. What the root could not do."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    registry = Registry(settings)

    for session in (registry.create(), registry.create()):
        delivered = session.agent_dir / "user.md"
        assert delivered.read_text() == "the user's own preferences\n"


def test_closing_a_session_takes_the_seeded_dir_and_leaves_the_seed(
    tmp_path: Path,
) -> None:
    """`PI-58`. Why a seed is a copy: the directory is removed with the session."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    registry = Registry(settings)
    session = registry.create()
    agent_dir = session.agent_dir

    registry.close(session.session_id)

    assert not agent_dir.exists()
    assert (settings.agent_home_seed / "user.md").exists()


def test_a_seed_that_is_not_a_directory_refuses_the_boot(tmp_path: Path) -> None:
    """`PI-58`. Every session would start with an empty directory, silently."""
    missing = tmp_path / "nothing-is-here"
    with pytest.raises(UnusableAgentHomeSeed) as refusal:
        check_boot(_settings(tmp_path, agent_home_seed=missing))
    assert str(missing) in str(refusal.value)


def test_no_seed_is_the_ordinary_case_and_changes_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.agent_home_seed is None
    check_boot(settings)
    session = Registry(settings).create()
    assert list(session.agent_dir.iterdir()) == []


def test_the_uniform_name_wins_over_this_builds_own(monkeypatch) -> None:  # noqa: ANN001
    """`PI-58`. The image sets the old name, so it is never absent."""
    monkeypatch.setenv(
        "AGENT_SERVICE_AGENT_DIR_ROOT", "/var/lib/agent-service/agent-dirs"
    )
    monkeypatch.setenv("AGENT_SERVICE_AGENT_HOME", "/mnt/persona-dirs")
    assert Settings.from_env().agent_dir_root == Path("/mnt/persona-dirs").resolve()


def test_the_old_name_still_works_alone(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("AGENT_SERVICE_AGENT_HOME", raising=False)
    monkeypatch.setenv(
        "AGENT_SERVICE_AGENT_DIR_ROOT", "/var/lib/agent-service/agent-dirs"
    )
    assert (
        Settings.from_env().agent_dir_root
        == Path("/var/lib/agent-service/agent-dirs").resolve()
    )


def test_a_read_only_seed_still_yields_a_writable_agent_dir(tmp_path: Path) -> None:
    """`PI-58`. `copytree` would stamp the seed's mode onto the directory."""
    seed = _seed(tmp_path)
    (seed / "user.md").chmod(0o444)
    seed.chmod(0o555)
    try:
        session = Registry(_settings(tmp_path, agent_home_seed=seed)).create()

        (session.agent_dir / "written-by-the-agent").write_text("ok")
        (session.agent_dir / "user.md").write_text("rewritten")
    finally:
        seed.chmod(0o755)


def test_every_reserved_path_really_is_overwritten_by_the_runner(
    tmp_path: Path,
) -> None:
    """`PI-58`. The published list is a promise, so it is checked against reality."""
    from agent_service.config import AGENT_HOME_SOURCE
    from agent_service.pi import PiRunner

    reserved = AGENT_HOME_SOURCE["seed_reserved_paths"]
    seed = tmp_path / "seed"
    seed.mkdir()
    for relative in reserved:
        (seed / relative).write_text("planted by the seed\n")

    session = Registry(_settings(tmp_path, agent_home_seed=seed)).create()
    for relative in reserved:
        assert (session.agent_dir / relative).read_text() == "planted by the seed\n"

    # Both files are written only when their feature is configured, so the
    # runner is built with both -- which is the deployment the list is about.
    PiRunner(
        binary=Path("pi-not-installed"),
        workspace=tmp_path / "workspace",
        agent_dir=session.agent_dir,
        session_dir=session.session_dir,
        provider_gateways={"anthropic": {"base_url": "https://gw.example/p/anthropic"}},
        mcp_adapter_path=Path("adapter.js"),
        mcp_servers={"echo": {"type": "stdio", "command": "echo", "args": []}},
    ).write_config()

    for relative in reserved:
        assert (session.agent_dir / relative).read_text() != "planted by the seed\n", (
            f"{relative} is published as reserved and the seed's copy survived"
        )


def test_a_one_shot_query_agent_dir_is_seeded_too(tmp_path: Path) -> None:
    """`PI-58`. One provisioning path: a `/v1/query` turn is not a smaller one."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    session = Registry(settings).ephemeral()
    assert (session.agent_dir / "user.md").exists()
