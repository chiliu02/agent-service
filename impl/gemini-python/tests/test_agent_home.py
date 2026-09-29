"""The agent home: a root of minted homes, and the seed that reaches them.

**Free: nothing is spawned.** A session here writes files and takes no turn, so
everything below is a directory on disk or a refusal.

GP-72 is the entry. The behaviour this pins is the one Agent Harness could not
see from outside: the directory the published variable names is a PARENT of
homes, so the only way to deliver a user's own configuration is the seed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.config import Settings, UnusableAgentHomeSeed, check_boot
from agent_service.registry import Registry


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "homes",
        "transcript_store": tmp_path / "store",
        "gemini_binary": Path("gemini-not-installed"),
        "require_credentials": False,
    }
    return Settings(**{**base, **kwargs})


def _seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    (seed / ".gemini").mkdir(parents=True)
    (seed / ".gemini" / "user.md").write_text("the user's own preferences\n")
    return seed


def test_the_home_is_a_child_of_the_root_and_the_root_holds_nothing(
    tmp_path: Path,
) -> None:
    """GP-72. The correction: a file at the root reaches no agent."""
    settings = _settings(tmp_path)
    (settings.agent_home_root).mkdir(parents=True)
    (settings.agent_home_root / "user.md").write_text("never read\n")

    session = Registry(settings).create()

    assert session.agent_home.parent == settings.agent_home_root
    assert session.agent_home != settings.agent_home_root
    assert not (session.agent_home / "user.md").exists()


def test_a_seed_is_copied_into_every_minted_home(tmp_path: Path) -> None:
    """GP-72. What the root could not do."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    registry = Registry(settings)

    first = registry.create()
    second = registry.create()

    for session in (first, second):
        delivered = session.agent_home / ".gemini" / "user.md"
        assert delivered.read_text() == "the user's own preferences\n"


def test_the_seed_cannot_overwrite_what_confines_the_agent(tmp_path: Path) -> None:
    """GP-72. The seed goes down FIRST, so this service's files win.

    A seed that could replace the policy would let whoever composes it widen
    the tool policy of every session on the container.
    """
    seed = _seed(tmp_path)
    (seed / "admin-policy.toml").write_text("# a policy the deployment wrote\n")
    (seed / "settings.json").write_text("{}\n")

    session = Registry(_settings(tmp_path, agent_home_seed=seed)).create()

    assert "a policy the deployment wrote" not in session.policy_file.read_text()
    assert (session.agent_home / ".gemini" / "user.md").exists()


def test_closing_a_session_takes_the_seeded_home_with_it(tmp_path: Path) -> None:
    """GP-72. The copy is why a seed is a copy: the home is removed."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    registry = Registry(settings)
    session = registry.create()
    home = session.agent_home

    registry.close(session.session_id)

    assert not home.exists()
    assert (settings.agent_home_seed / ".gemini" / "user.md").exists()


def test_a_seed_that_is_not_a_directory_refuses_the_boot(tmp_path: Path) -> None:
    """GP-72. Silence here is worse than a refusal: every home would be empty."""
    missing = tmp_path / "nothing-is-here"
    with pytest.raises(UnusableAgentHomeSeed) as refusal:
        check_boot(_settings(tmp_path, agent_home_seed=missing))
    assert str(missing) in str(refusal.value)


def test_no_seed_is_the_ordinary_case_and_changes_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.agent_home_seed is None
    check_boot(settings)
    session = Registry(settings).create()
    assert list(session.agent_home.iterdir())  # the service's own files, and only those


def test_the_uniform_name_wins_over_this_builds_own(monkeypatch) -> None:  # noqa: ANN001
    """GP-72. The image sets the old name, so it is never absent."""
    monkeypatch.setenv("AGENT_SERVICE_AGENT_HOME_ROOT", "/var/lib/agent-service/homes")
    monkeypatch.setenv("AGENT_SERVICE_AGENT_HOME", "/mnt/persona-homes")
    assert Settings.from_env().agent_home_root == Path("/mnt/persona-homes").resolve()


def test_the_old_name_still_works_alone(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("AGENT_SERVICE_AGENT_HOME", raising=False)
    monkeypatch.setenv("AGENT_SERVICE_AGENT_HOME_ROOT", "/var/lib/agent-service/homes")
    assert (
        Settings.from_env().agent_home_root
        == Path("/var/lib/agent-service/homes").resolve()
    )


def test_a_read_only_seed_still_yields_a_writable_home(tmp_path: Path) -> None:
    """GP-73. `copytree` would stamp the seed's mode onto the home.

    Measured before the fix: a seed at `0o555` holding a `0o444` file produced a
    home at `0o555`. A read-only seed mount is the obvious deployment, so the
    obvious implementation failed on it.
    """
    seed = _seed(tmp_path)
    (seed / ".gemini" / "user.md").chmod(0o444)
    seed.chmod(0o555)
    try:
        session = Registry(_settings(tmp_path, agent_home_seed=seed)).create()

        # The home is the agent's to write, whatever the seed's own mode is.
        (session.agent_home / "written-by-the-agent").write_text("ok")
        (session.agent_home / ".gemini" / "user.md").write_text("rewritten")
    finally:
        seed.chmod(0o755)


def test_every_reserved_path_really_is_written_after_the_seed(tmp_path: Path) -> None:
    """GP-73. The published list is a promise, so it is checked against reality.

    A path that stopped being written would leave a consumer refusing a
    configuration for no reason; one that started being written and was not
    added here would overwrite a user's preference in silence.
    """
    from agent_service.config import AGENT_HOME_SOURCE

    reserved = AGENT_HOME_SOURCE["seed_reserved_paths"]
    seed = tmp_path / "seed"
    for relative in reserved:
        planted = seed / relative
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text("planted by the seed\n")

    registry = Registry(_settings(tmp_path, agent_home_seed=seed))
    session = registry.create(system_prompt="a prompt")
    one_shot = registry.ephemeral(system_prompt="a prompt")

    # **`transcript.jsonl` is reserved by a TURN rather than by provisioning**,
    # which is the one asymmetry in the list. A one-shot session's transcript
    # lands in its own home, so a seed placing that name has it overwritten the
    # moment the turn runs -- later than the others, and just as silently.
    assert one_shot.transcript == one_shot.agent_home / "transcript.jsonl"
    written_by_provisioning = [p for p in reserved if p != "transcript.jsonl"]

    for relative in written_by_provisioning:
        clobbered = [
            (s.agent_home / relative)
            for s in (session, one_shot)
            if (s.agent_home / relative).exists()
        ]
        assert clobbered, f"{relative} is published as reserved and nothing writes it"
        assert any(
            path.read_text() != "planted by the seed\n" for path in clobbered
        ), f"{relative} is published as reserved and the seed's copy survived"


def test_a_one_shot_query_home_is_seeded_too(tmp_path: Path) -> None:
    """GP-72. One provisioning path, deliberately: `/v1/query` is not a turn
    with a smaller boundary."""
    settings = _settings(tmp_path, agent_home_seed=_seed(tmp_path))
    session = Registry(settings).ephemeral()
    assert (session.agent_home / ".gemini" / "user.md").exists()
