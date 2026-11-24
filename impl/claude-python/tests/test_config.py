import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

from agent_service.config import (
    ALWAYS_DISALLOWED_TOOLS,
    CREDENTIAL_ENV_VARS,
    DEFAULT_ALLOWED_TOOLS,
    LISTEN_ADDRESS,
    LISTEN_PORT,
    PROVIDER_SELECTOR_ENV_VARS,
    MissingMounts,
    Settings,
    credentials_configured,
    verify_mounts,
)

# Every var credentials_configured() checks. Cleared in each test below so a
# real key exported in the developer's own shell (or a stray .env picked up
# by pydantic-settings elsewhere) can never make a "False" case flaky.
_CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


@pytest.fixture
def no_credentials(monkeypatch):
    """Ensure none of the vars credentials_configured() checks are set."""
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_match_the_decisions(tmp_path: Path) -> None:
    s = Settings(workspace_dir=tmp_path)
    assert s.default_model == "claude-sonnet-5"          # Q7
    assert s.default_permission_mode == "dontAsk"
    assert s.default_max_turns == 30                      # Q5
    assert s.max_allowed_turns == 200
    assert s.default_max_budget_usd == 2.0
    assert s.max_allowed_budget_usd == 10.0
    assert s.default_request_timeout_s == 600
    assert s.max_allowed_timeout_s == 1800


def test_setting_sources_defaults_to_empty_list_not_none(tmp_path: Path) -> None:
    # Must be [] and never None: unset loads ~/.claude and ./.claude (F8).
    s = Settings(workspace_dir=tmp_path)
    assert s.default_setting_sources == []


def test_ask_user_question_is_always_disallowed() -> None:
    assert "AskUserQuestion" in ALWAYS_DISALLOWED_TOOLS


def test_default_allowed_tools_excludes_ask_user_question() -> None:
    assert "AskUserQuestion" not in DEFAULT_ALLOWED_TOOLS


def test_workspace_dir_is_resolved_and_created(tmp_path: Path) -> None:
    target = tmp_path / "ws"
    s = Settings(workspace_dir=target)
    assert s.workspace_dir.is_absolute()
    assert s.workspace_dir.is_dir()


def test_env_prefix_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_SERVICE_DEFAULT_MODEL", "claude-opus-5")
    monkeypatch.setenv("AGENT_SERVICE_DEFAULT_MAX_TURNS", "7")
    s = Settings(workspace_dir=tmp_path)
    assert s.default_model == "claude-opus-5"
    assert s.default_max_turns == 7


def test_the_session_lifecycle_settings_are_env_overridable(
    monkeypatch, tmp_path: Path
) -> None:
    """The three that size the registry had no override test.

    They are the ones an operator most often changes per deployment -- the cap
    is a real resource bound (one CLI subprocess each), and the two reaper
    numbers decide how long an abandoned session holds one of those slots. A
    silently-ignored override here overcommits a container's memory, which is
    exactly the failure `compose.yaml` sets `max_sessions: 4` to avoid.
    """
    monkeypatch.setenv("AGENT_SERVICE_MAX_SESSIONS", "3")
    monkeypatch.setenv("AGENT_SERVICE_SESSION_IDLE_TTL_S", "45")
    monkeypatch.setenv("AGENT_SERVICE_SESSION_REAPER_INTERVAL_S", "5")
    s = Settings(workspace_dir=tmp_path)
    assert s.max_sessions == 3
    assert s.session_idle_ttl_s == 45
    assert s.session_reaper_interval_s == 5


def test_every_settings_field_is_documented_in_design_md() -> None:
    """The table drifts silently, and it drifted: `include_raw_events` was
    missing (Plan 2 follow-up, cosmetic list), and by 2026-07-31 so were five
    more -- `database_url`, `log_level`, `require_mounts`,
    `session_store_load_timeout_ms`, `shutdown_budget_s`. CP-100 is the single
    source of truth for defaults, so a field absent from it is a field nobody
    knows they can set.

    Deliberately asserts one direction only. A row for something that is not a
    field is a different defect, and the table already carries a "not settings,
    despite appearing here in earlier drafts" section that this must not fight.
    """
    import re

    # **Reads ONE entry, not the whole file** (2026-08-10): the six documents
    # merged into one references file, which carries other `| \x60field\x60 |` tables.
    # Slicing to CP-100 keeps this asserting what it always asserted -- a field
    # is in the settings table -- rather than "a field is mentioned somewhere".
    references = (
        Path(__file__).resolve().parents[1] / "docs" / "claude-python-references.md"
    ).read_text(encoding="utf-8")
    entry = re.search(r"^## CP-100 .*?(?=^## CP-)", references, re.M | re.S)
    assert entry, "CP-100 is gone; the settings table moved and this test is blind"
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", entry.group(0), re.M))
    missing = sorted(set(Settings.model_fields) - documented)
    assert not missing, f"Settings fields absent from CP-100: {missing}"


# --- credentials_configured() (I2, final review: previously untested, and --
# now load-bearing since main.py's load_dotenv() call depends on this being
# right) --------------------------------------------------------------------


def test_credentials_configured_false_when_nothing_set(no_credentials) -> None:
    assert credentials_configured() is False


def test_credentials_configured_true_with_anthropic_api_key(no_credentials, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-real")
    assert credentials_configured() is True


@pytest.mark.parametrize(
    "var",
    ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"],
)
def test_credentials_configured_true_for_each_alternative_auth_provider(
    no_credentials, monkeypatch, var: str
) -> None:
    monkeypatch.setenv(var, "1")
    assert credentials_configured() is True


# --- the published specification IS the gate --------------------------------------


def test_the_published_credential_specification_is_the_one_the_gate_checks(
    no_credentials, monkeypatch
) -> None:
    """`GET /v1/capabilities` exports these two lists so a caller can check,
    before starting a container, that the credential it is about to inject is
    one this image reads. That promise is only worth anything if the published
    names and the checked names are the same set -- so this pins it in BOTH
    directions.

    Publishing a name the gate ignores sends a caller to inject something
    useless; checking a name the gate never publishes leaves the caller with the
    original problem, which was a whole delivery mechanism built around an
    `ANTHROPIC_API_KEY_FILE` that does not exist anywhere in this image.
    """
    published = [*CREDENTIAL_ENV_VARS, *PROVIDER_SELECTOR_ENV_VARS]

    # Every published name, on its own, satisfies the gate.
    for name in published:
        monkeypatch.setenv(name, "x")
        assert credentials_configured() is True, f"{name} is published but not checked"
        monkeypatch.delenv(name)

    # And nothing outside the published set does. `_CREDENTIAL_VARS` is this
    # module's own hand-written list, kept separate on purpose: if the two ever
    # disagree, one of them is the drift this test exists to catch.
    assert set(published) == set(_CREDENTIAL_VARS)
    assert credentials_configured() is False


# --- I2: the documented quick start (`cp .env.example .env`, set
# ANTHROPIC_API_KEY, run) must actually work. Nothing loaded .env before this
# fix -- Settings.env_prefix="AGENT_SERVICE_" means pydantic-settings' own
# .env support never sees an unprefixed ANTHROPIC_API_KEY, and `uv run` does
# not load .env on its own. These use a synthetic .env with a fake key in a
# tmp_path; the project's real .env (with the real key) is never opened.


def test_env_var_absent_until_dotenv_is_loaded(no_credentials, tmp_path: Path) -> None:
    """Pins the bug itself: with a `.env` present on disk but not yet loaded
    into the process, credentials_configured() must still be False -- proving
    the failure this fix addresses is real, not hypothetical."""
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-fake-not-real\n")
    assert credentials_configured() is False


def test_load_dotenv_populates_the_key_so_credentials_become_configured(
    no_credentials, tmp_path: Path
) -> None:
    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-fake-not-real\n")

    load_dotenv(dotenv_path=env_file, override=False)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-fake-not-real"
    assert credentials_configured() is True


def test_load_dotenv_does_not_override_an_already_exported_real_key(
    monkeypatch, tmp_path: Path
) -> None:
    """main.py must not let a stale/example value in .env clobber a real key
    the operator already exported in the shell."""
    from dotenv import load_dotenv

    monkeypatch.setenv("ANTHROPIC_API_KEY", "already-exported-real-value")
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-dotenv-should-not-win\n")

    load_dotenv(dotenv_path=env_file, override=False)

    assert os.environ["ANTHROPIC_API_KEY"] == "already-exported-real-value"


async def test_healthz_reports_configured_true_once_dotenv_is_loaded(
    no_credentials, tmp_path: Path
) -> None:
    """End-to-end proof of the documented quick start: with the key present
    only in a `.env` (nothing exported), loading it must make GET /healthz
    report `credentials_configured: true` -- not just the underlying
    function. Uses an explicit synthetic `dotenv_path`, exactly like the two
    unit tests above, so this never touches the project's real .env either."""
    from dotenv import load_dotenv
    from httpx import ASGITransport, AsyncClient

    from agent_service.api import create_app

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-fake-not-real\n")
    load_dotenv(dotenv_path=env_file, override=False)

    app = create_app(settings=Settings(workspace_dir=tmp_path / "ws"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/healthz")

    assert response.status_code == 200
    assert response.json()["credentials_configured"] is True


def test_main_module_calls_load_dotenv_before_create_app(monkeypatch) -> None:
    """Proves main.py's wiring order (load_dotenv() before create_app())
    without ever touching the filesystem: load_dotenv()'s default search
    walks upward from the *calling file's own directory* (not the process
    cwd -- see dotenv.main.find_dotenv), so a real, unpatched import of
    main.py would climb straight to this repo's real, gitignored .env
    regardless of any monkeypatch.chdir(). Patching both functions with
    recording fakes before import proves the ordering with no I/O at all."""
    import importlib

    import dotenv

    import agent_service.api as api_module

    calls: list[str] = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append("load_dotenv"))
    monkeypatch.setattr(api_module, "create_app", lambda: calls.append("create_app") or object())

    sys.modules.pop("agent_service.main", None)
    try:
        importlib.import_module("agent_service.main")
        assert calls == ["load_dotenv", "create_app"]
    finally:
        sys.modules.pop("agent_service.main", None)


def test_session_defaults(tmp_path: Path) -> None:
    s = Settings(workspace_dir=tmp_path)
    assert s.max_sessions == 8
    assert s.session_idle_ttl_s == 1800
    assert s.session_reaper_interval_s == 60
    assert s.shutdown_budget_s == 60.0


def test_the_published_listen_specification_is_the_image_command() -> None:
    """`LISTEN_ADDRESS`/`LISTEN_PORT` must be what the image actually runs.

    THIS TEST IS THE FEATURE, not a check on it. 0.13.0 publishes these two
    values through `python -m agent_service.spec` so that Agent Studio can
    look the port up instead of hardcoding it, and a published value that has
    drifted from the `CMD` is worse than publishing nothing -- it would send a
    caller confidently to a port nothing is bound to. The container ships no
    Dockerfile, so nothing at run time can derive them; same shape, and same
    reasoning, as `db/revision.py`'s `EXPECTED_REVISION`.

    `EXPOSE` is checked too. It is documentation rather than a binding, but a
    `CMD` and an `EXPOSE` that disagree is a quiet contradiction in the one file
    a reader goes to for this answer.
    """
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    host = re.search(r'"--host",\s*"([^"]+)"', dockerfile)
    port = re.search(r'"--port",\s*"(\d+)"', dockerfile)
    expose = re.search(r"^EXPOSE\s+(\d+)\s*$", dockerfile, re.M)
    assert host and port and expose, "the Dockerfile CMD/EXPOSE shape changed"

    assert host.group(1) == LISTEN_ADDRESS, (
        f"the image binds {host.group(1)} but config publishes {LISTEN_ADDRESS}"
    )
    assert int(port.group(1)) == LISTEN_PORT, (
        f"the image listens on {port.group(1)} but config publishes {LISTEN_PORT}"
    )
    assert int(expose.group(1)) == LISTEN_PORT, (
        f"EXPOSE {expose.group(1)} contradicts the CMD's --port {LISTEN_PORT}"
    )


def test_the_listen_address_is_not_loopback() -> None:
    """The clause, as an assertion: never bind loopback inside the container.

    Consumers reach a container by name on a Docker network, so loopback in
    here removes their only route. It is worth its own test because the change
    that would make it happen READS LIKE A SECURITY FIX -- this service's own
    security posture describes loopback binding as a control, and it means the
    HOST side (`compose.yaml` publishes `127.0.0.1:8000:8000`, which is right).
    Somebody hardening the container side would be applying a true sentence in
    the wrong place, and the diff would look like an improvement.

    Agent Studio raised exactly this (CP-136): "a change
    that looks like a security fix and breaks a consumer is the shape that gets
    shipped."
    """
    assert LISTEN_ADDRESS not in ("127.0.0.1", "localhost", "::1"), (
        "binding loopback inside the container removes the only route a "
        "consumer on the same Docker network has. Host-side publishing is "
        "where loopback belongs -- see compose.yaml."
    )
    assert LISTEN_PORT > 1024, (
        f"port {LISTEN_PORT} is privileged and would need CAP_NET_BIND_SERVICE; "
        "this image is measured to run under --cap-drop ALL"
    )


def test_the_compose_grace_period_follows_the_shutdown_budget(tmp_path: Path) -> None:
    """`stop_grace_period` is DERIVED, not measured. Pin the derivation.

    Docker sends SIGTERM, waits `stop_grace_period`, then SIGKILLs. Two
    budgets run sequentially inside that window and only the first is bounded
    by uvicorn: the request drain (`--timeout-graceful-shutdown`, in the
    Dockerfile CMD), and THEN the lifespan shutdown, i.e. close_all(), bounded
    by `shutdown_budget_s`. Task 4 measured what happens when the grace period
    is smaller than their sum: SIGKILL mid-close_all(), ExitCode 137, agent
    subprocess still alive.

    So this reads all three numbers out of the three files that own them and
    fails if the arithmetic stops holding -- which is what stops someone
    raising `shutdown_budget_s` (or lowering the grace) without seeing the
    other, the way 90s was once chosen against a bound that did not exist.
    """
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    drain = float(
        re.search(r'"--timeout-graceful-shutdown",\s*"(\d+(?:\.\d+)?)"', dockerfile)
        .group(1)  # type: ignore[union-attr]
    )
    grace = float(
        re.search(r"^\s*stop_grace_period:\s*(\d+(?:\.\d+)?)s\s*$", compose, re.M)
        .group(1)  # type: ignore[union-attr]
    )
    budget = Settings(workspace_dir=tmp_path).shutdown_budget_s

    # `+ 5`: the two budgets are not the whole shutdown. uvicorn's own teardown
    # and process exit ran ~1.5s beyond close_all() in the Task 4 measurement,
    # and a grace period equal to drain + budget leaves that nothing at all.
    assert grace >= drain + budget + 5.0, (
        f"stop_grace_period {grace}s cannot cover the {drain}s request drain "
        f"plus the {budget}s close_all() budget plus a margin"
    )
    # ...and it is not absurdly larger either: a grace period much bigger than
    # the bound is the same guess in the other direction.
    assert grace <= drain + budget + 30.0, (grace, drain, budget)


# Task 7's `docker stats` figures, in MiB and pids. These are the ONLY inputs
# the resource limits are derived from, so they live here where the derivation
# is checked rather than being re-typed into each assertion.
#
#   idle, just booted              59.3 MiB    3 pids
#   one live session, mid-turn  355-368 MiB   20-21 pids
#   after DELETE, warm          243-247 MiB    3 pids
#
# The baseline is the WARM one (~250), not the 59.3 MiB boot figure: the
# difference is the 262 MiB bundled binary paged in, and cgroup accounting
# includes page cache, so a container that has served even one session never
# returns to 59 MiB. Sizing against 59 would under-count by ~190 MiB.
_WARM_BASELINE_MIB = 250.0
_PER_SESSION_MIB = 110.0
_BASELINE_PIDS = 3
_PER_SESSION_PIDS = 17

# What fraction of `mem_limit` a full house of sessions may project to.
#
# NOT 1.0, and that is the whole point. `max_sessions` and `mem_limit` bound the
# same resource but fail very differently: the cap refuses with 429 and the
# caller retries, while the limit OOM-kills (exit 137) and -- with
# `restart: "no"` -- takes every other live session down with it and stays down.
# The cap is therefore meant to trip FIRST, which it only does if the projection
# leaves real room underneath the ceiling.
#
# The room is not slack, it is the UNMEASURED cost of subagents. The agent's own
# `Task` tool spawns subagents INSIDE a session's existing subprocess: they cost
# memory and pids while consuming NO cap slot, so one session that fans out
# counts as 1 against `max_sessions` but costs well above the 110 MiB the single
# measured session did. Nothing bounds that, and nothing has measured it. 0.6
# says: at most 60% of the ceiling may be spoken for by sessions of the shape we
# actually measured, and the remaining 40% absorbs the shape we did not.
_MAX_PROJECTED_FRACTION = 0.6


def _mib(literal: str) -> float:
    """`1536m` / `2g` -> MiB. Compose accepts both; the test must too."""
    value, unit = float(literal[:-1]), literal[-1].lower()
    return value * 1024 if unit == "g" else value


def test_the_compose_memory_limit_follows_max_sessions(tmp_path: Path) -> None:
    """`mem_limit` and `pids_limit` are DERIVED from `max_sessions`. Pin it.

    Same precedent as the grace-period test above: numbers in `compose.yaml`
    that nothing enforces, derived by arithmetic that lives only in a comment.
    The failure this prevents is specific and quiet -- raising
    `AGENT_SERVICE_MAX_SESSIONS` back toward config.py's default of 8 without
    touching `mem_limit`. Nothing errors at deploy time; the container simply
    becomes able to OOM-kill itself under a load the session cap still reports
    as acceptable, and because `restart: "no"` it stays down afterwards.

    Note which `max_sessions` this reads. config.py's default is 8 and that is
    correct for the library -- it is what the code is tested at. compose.yaml
    overrides it to 4 as a DEPLOYMENT decision about a container that may be one
    of several on a host. The deployed number is the one that has to satisfy the
    deployed limit, so it is parsed out of compose.yaml, not read off `Settings`.
    """
    root = Path(__file__).resolve().parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    max_sessions = int(
        re.search(
            r"^\s*AGENT_SERVICE_MAX_SESSIONS:\s*\$\{AGENT_SERVICE_MAX_SESSIONS:-(\d+)\}\s*$",
            compose,
            re.M,
        )
        .group(1)  # type: ignore[union-attr]
    )
    mem_limit_mib = _mib(
        re.search(r"^\s*mem_limit:\s*(\d+[mMgG])\s*$", compose, re.M)
        .group(1)  # type: ignore[union-attr]
    )
    pids_limit = int(
        re.search(r"^\s*pids_limit:\s*(\d+)\s*$", compose, re.M)
        .group(1)  # type: ignore[union-attr]
    )

    projected_mib = _WARM_BASELINE_MIB + max_sessions * _PER_SESSION_MIB
    assert projected_mib <= mem_limit_mib * _MAX_PROJECTED_FRACTION, (
        f"max_sessions={max_sessions} projects to {projected_mib:.0f} MiB "
        f"({_WARM_BASELINE_MIB:.0f} warm baseline + {max_sessions} x "
        f"{_PER_SESSION_MIB:.0f} MiB), which is "
        f"{projected_mib / mem_limit_mib:.0%} of mem_limit {mem_limit_mib:.0f} MiB "
        f"-- above the {_MAX_PROJECTED_FRACTION:.0%} ceiling. The session cap is "
        f"supposed to refuse with 429 before mem_limit OOM-kills the container, "
        f"and the margin underneath is what absorbs subagent fanout (unmeasured, "
        f"consumes no cap slot). Raise mem_limit with max_sessions, or lower "
        f"max_sessions back."
    )

    # ...and mem_limit is not absurdly larger either, which would make the
    # coupling vacuous -- a ceiling nothing can reach bounds nothing. Same
    # both-directions check the grace-period test makes.
    assert mem_limit_mib <= projected_mib * 4.0, (
        f"mem_limit {mem_limit_mib:.0f} MiB is more than 4x the "
        f"{projected_mib:.0f} MiB max_sessions={max_sessions} can project to; "
        f"it is no longer bounding this container in any practical sense"
    )

    # pids gets a FLOOR only, deliberately -- no upper bound. 512 is far above
    # the {3 + n x 17} projection on purpose: `Bash` is in the default tool set
    # with permission_enforcement="none", so the agent legitimately runs things
    # that fan out hard (`make -j`, `npm install`, a worker test suite), any of
    # which can spend 50-100 pids inside a SINGLE session. A tight limit kills
    # those mid-turn with a fork error that reads like a bug in the agent's
    # command. The limit is fork-bomb protection, not capacity planning.
    projected_pids = _BASELINE_PIDS + max_sessions * _PER_SESSION_PIDS
    assert projected_pids <= pids_limit, (
        f"max_sessions={max_sessions} projects to {projected_pids} pids "
        f"({_BASELINE_PIDS} + {max_sessions} x {_PER_SESSION_PIDS}), which "
        f"exceeds pids_limit {pids_limit}; sessions would fail to fork before "
        f"the cap refused them"
    )


def test_the_compose_git_config_env_block_is_self_consistent() -> None:
    """`GIT_CONFIG_COUNT` must equal the number of KEY_n/VALUE_n pairs.

    Same precedent as the grace-period test above: a number in `compose.yaml`
    that nothing enforces. Git reads exactly `GIT_CONFIG_COUNT` pairs starting
    at 0 and SILENTLY IGNORES anything beyond it -- no warning, no error, the
    setting simply does not apply. Adding a third pair without bumping the
    count would therefore look right and do nothing.

    The pairs themselves matter enough to name: `core.autocrlf` is what stops
    the agent committing the entire repository's line endings into history on a
    Windows-host bind mount (Task 5 measured 26,261 insertions / 26,261
    deletions, and the commit that follows), and `core.filemode` is what stops
    all 66 of 66 tracked files reading as mode changes. Both are supplied
    through this channel rather than baked into the image because `.git/config`
    is inside the mount and repo scope beats system scope; the environment is
    read after every config file and is the only scope that wins.
    """
    root = Path(__file__).resolve().parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    count = int(
        re.search(r"^\s*GIT_CONFIG_COUNT:\s*\"?(\d+)\"?\s*$", compose, re.M)
        .group(1)  # type: ignore[union-attr]
    )
    keys = {int(n): k for n, k in re.findall(
        r"^\s*GIT_CONFIG_KEY_(\d+):\s*(\S+)\s*$", compose, re.M
    )}
    values = {int(n) for n, in re.findall(
        r"^\s*GIT_CONFIG_VALUE_(\d+):", compose, re.M
    )}

    assert count == len(keys) == len(values), (
        f"GIT_CONFIG_COUNT is {count} but compose.yaml defines {len(keys)} "
        f"key(s) and {len(values)} value(s); git reads the first {count} pairs "
        f"and silently ignores the rest"
    )
    # Indices must be contiguous from 0 -- git stops at the count, so a gap
    # drops everything after it just as silently.
    assert set(keys) == values == set(range(count)), (sorted(keys), sorted(values))
    assert keys[0] == "core.autocrlf", keys
    assert keys[1] == "core.filemode", keys


# --- follow-up item 8: refuse to boot without credentials ------------------
#
# User decision (2026-07-27). Previously the lifespan booted cleanly with every
# credential variable cleared, and `credentials_configured()` was read by
# `/healthz` and nowhere else -- so an operator who forgot the key got up to
# `max_sessions` (8) sessions, each spawning a doomed subprocess and holding
# its cap slot until the reaper swept it at `session_idle_ttl_s` (1800s),
# instead of a refusal to boot.
#
# Accepted cost, stated by the user: a credential blip becomes a crash-loop,
# and the service can no longer start for docs-only use without the escape
# hatch below.


def _app_with(settings):  # noqa: ANN001
    from agent_service.api import create_app

    return create_app(settings=settings)


def test_the_lifespan_refuses_to_start_without_credentials(
    no_credentials, tmp_path: Path
) -> None:
    """Driven through `app.router.lifespan_context`, which is exactly what an
    ASGI server drives on startup.

    Also pins the check's PLACEMENT -- before `start_reaper()` and outside the
    `try`. Moving it inside the try still refuses to boot, so nothing else
    here can tell the difference; what changes is that the reaper is started
    and then immediately torn down by the `finally`, and `close_all()` runs
    against a registry that never held anything. A refused boot must start no
    background task at all, so this asserts on the CALL COUNT: `stop_reaper()`
    sets `_reaper` back to None, so inspecting the attribute afterwards cannot
    distinguish "never started" from "started and stopped".
    """
    from agent_service.config import MissingCredentials
    from agent_service.registry import SessionRegistry

    class _RecordingRegistry(SessionRegistry):
        def __init__(self, s) -> None:  # noqa: ANN001
            super().__init__(s)
            self.start_calls = 0

        def start_reaper(self) -> None:
            self.start_calls += 1
            super().start_reaper()

    from agent_service.api import create_app

    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=True)
    registry = _RecordingRegistry(settings)
    app = create_app(settings=settings, registry=registry)

    async def boot() -> None:
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover - the enter above must raise

    with pytest.raises(MissingCredentials):
        asyncio.run(boot())

    assert registry.start_calls == 0
    assert registry.list() == []


def test_the_refusal_names_what_an_operator_must_set(
    no_credentials, tmp_path: Path
) -> None:
    """A refusal that does not say what to do turns a five-second fix into a
    support ticket. The message must name a credential to set AND the escape
    hatch, or an operator who legitimately wants a docs-only boot is stuck."""
    from agent_service.config import MissingCredentials, verify_credentials

    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=True)
    with pytest.raises(MissingCredentials) as excinfo:
        verify_credentials(settings)

    message = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "ANTHROPIC_AUTH_TOKEN" in message
    # At least one cloud-provider route, or a Bedrock/Vertex operator is told
    # to set a key they do not have.
    assert "CLAUDE_CODE_USE_BEDROCK" in message
    assert "CLAUDE_CODE_USE_VERTEX" in message
    # ...and the way out.
    assert "AGENT_SERVICE_REQUIRE_CREDENTIALS" in message


def test_the_lifespan_starts_normally_when_credentials_are_present(
    no_credentials, monkeypatch, tmp_path: Path
) -> None:
    """The other direction. Without this, a check that always raised -- or one
    whose condition was inverted -- would look identical to a working one."""
    import asyncio

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-real")
    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=True)
    app = _app_with(settings)

    reached = []

    async def boot() -> None:
        async with app.router.lifespan_context(app):
            reached.append(True)

    asyncio.run(boot())
    assert reached == [True]


def test_require_credentials_false_is_the_escape_hatch(
    no_credentials, tmp_path: Path
) -> None:
    """The mechanism the test suite itself runs on, so it is exercised rather
    than merely available."""
    import asyncio

    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=False)
    app = _app_with(settings)

    reached = []

    async def boot() -> None:
        async with app.router.lifespan_context(app):
            reached.append(True)

    asyncio.run(boot())
    assert reached == [True]


def test_require_credentials_defaults_to_true_and_is_env_overridable(
    monkeypatch, tmp_path: Path
) -> None:
    """The default is the whole point -- an operator gets the refusal without
    opting in. The override follows the same `AGENT_SERVICE_` convention as
    every other field, which is why it is a `Settings` field rather than an
    ad-hoc environment read."""
    assert Settings(workspace_dir=tmp_path).require_credentials is True
    monkeypatch.setenv("AGENT_SERVICE_REQUIRE_CREDENTIALS", "false")
    assert Settings(workspace_dir=tmp_path).require_credentials is False


async def test_healthz_still_reports_credentials_lost_after_boot(
    no_credentials, monkeypatch, tmp_path: Path
) -> None:
    """The check gates BOOT, not liveness. Credentials that disappear after a
    successful start must not kill a running service or make it lie: the
    process stays up and `/healthz` reports `credentials_configured: false`,
    which is what it has always been for. Re-checking at request time would
    turn a transient blip into an outage on a route whose job is to describe
    one."""
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-real")
    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=True)
    app = _app_with(settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            before = await ac.get("/healthz")
            monkeypatch.delenv("ANTHROPIC_API_KEY")
            after = await ac.get("/healthz")

    assert before.json()["credentials_configured"] is True
    assert after.status_code == 200
    assert after.json()["credentials_configured"] is False


async def test_a_real_server_exits_non_zero_when_credentials_are_missing(
    no_credentials, tmp_path: Path
) -> None:
    """The operator-visible behaviour, not just the exception.

    "The lifespan raises" is only useful if something acts on it. uvicorn's
    `Server.startup()` sets `should_exit` from the failed lifespan and calls
    `sys.exit(STARTUP_FAILURE)`, so `serve()` raises `SystemExit` with a
    non-zero code -- which is what makes a container restart rather than sit
    there serving 502s. Asserted against the real server object, no socket
    ever bound.
    """
    import uvicorn
    from uvicorn.config import STARTUP_FAILURE

    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=True)
    app = _app_with(settings)

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical")
    )
    with pytest.raises(SystemExit) as excinfo:
        # BOUNDED, and that is not decoration. `startup()` reaches
        # `sys.exit()` before it ever calls `loop.create_server`, so on the
        # correct code no socket is bound and this returns immediately. If the
        # refusal is ever removed, the server starts for real and serves
        # forever -- measured: this test hung the whole suite past a 600s
        # bound when run against the pre-fix code, reporting nothing. A
        # regression must FAIL, not hang.
        await asyncio.wait_for(server.serve(), timeout=10.0)

    assert excinfo.value.code == STARTUP_FAILURE
    assert excinfo.value.code != 0


# --- logging: the level, and the one call site that applies it ---------------
#
# Both were untested. Deleting the `log_level` validator, and deleting the
# `configure_logging(...)` call from main.py entirely, each left the whole
# suite green -- while the second one is the defect Task 6 measured in a
# container: nothing configured logging, so the reaper's "closed N idle
# session(s)" and close_all()'s shutdown summary (both INFO) produced ZERO
# matches in `docker compose logs`.


def test_the_log_level_is_normalised_to_the_name_logging_understands(
    tmp_path: Path,
) -> None:
    """`logging` matches level names case-SENSITIVELY, so an operator's
    `AGENT_SERVICE_LOG_LEVEL=info` would abort the boot from inside
    basicConfig with `Unknown level: 'info'` -- a confusing place for a
    configuration typo to surface."""
    assert Settings(workspace_dir=tmp_path, log_level="info").log_level == "INFO"
    assert Settings(workspace_dir=tmp_path, log_level=" debug ").log_level == "DEBUG"
    assert Settings(workspace_dir=tmp_path).log_level == "INFO"


def test_an_unknown_log_level_is_rejected_by_name_at_construction(
    tmp_path: Path,
) -> None:
    """Rejected HERE, naming the valid set, rather than at basicConfig."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as caught:
        Settings(workspace_dir=tmp_path, log_level="verbose")

    message = str(caught.value)
    assert "unknown log level" in message
    assert "'verbose'" in message
    assert "INFO" in message  # names what IS accepted


def test_main_module_configures_logging_between_dotenv_and_create_app(
    monkeypatch, tmp_path: Path
) -> None:
    """The entrypoint must actually CALL it, at the right moment.

    Ordering is load-bearing in both directions: after `load_dotenv`, so
    `AGENT_SERVICE_LOG_LEVEL` may live in `.env` alongside the credential, and
    before `create_app`, so anything logged while the app is being built
    already has somewhere to go. Asserted by patching `logging.basicConfig` --
    the same recording-fakes-before-import technique as the test above, so no
    real root handler is installed under pytest's capture and the repo's real
    `.env` is never opened.
    """
    import importlib
    import logging as logging_module

    import dotenv

    import agent_service.api as api_module
    from agent_service.config import get_settings

    monkeypatch.setenv("AGENT_SERVICE_LOG_LEVEL", "warning")
    monkeypatch.setenv("AGENT_SERVICE_WORKSPACE_DIR", str(tmp_path / "ws"))
    # `get_settings` is lru_cached, and an earlier test in this session may
    # already have populated it. Cleared on both sides so this test both SEES
    # the level set above and leaves nothing behind.
    get_settings.cache_clear()

    calls: list[str] = []
    levels: list[object] = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append("load_dotenv"))
    monkeypatch.setattr(api_module, "create_app", lambda: calls.append("create_app") or object())

    def fake_basic_config(**kwargs) -> None:  # noqa: ANN003
        calls.append("configure_logging")
        levels.append(kwargs.get("level"))

    monkeypatch.setattr(logging_module, "basicConfig", fake_basic_config)

    sys.modules.pop("agent_service.main", None)
    try:
        importlib.import_module("agent_service.main")
        assert calls == ["load_dotenv", "configure_logging", "create_app"]
        # ...with the CONFIGURED level, normalised -- not a hardcoded one.
        assert levels == ["WARNING"]
    finally:
        sys.modules.pop("agent_service.main", None)
        get_settings.cache_clear()


# --- plan-03 Task 8: the database credential must not reach the agent --------


def test_get_settings_removes_the_database_url_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SECURITY requirement, not tidiness.

    The agent's subprocess inherits this process's entire environment -- read
    from the SDK source, which builds `process_env` as `{**os.environ, ...}` --
    and `Bash` is enabled by default, so `env` is one tool call away. Anything
    left here is readable by the agent and by whatever can influence its prompt.

    `ClaudeAgentOptions.env` cannot substitute: it is merged ON TOP of the
    inherited environment, so it adds and overrides but never removes.
    CP-130 states this pop as a hard requirement in config.py.
    """
    import os

    from agent_service.config import get_settings

    monkeypatch.setenv("AGENT_SERVICE_DATABASE_URL", "postgresql://u:secret@h/db")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        # Read into the settings object...
        assert settings.database_url == "postgresql://u:secret@h/db"
        # ...and gone from where the agent could read it.
        assert "AGENT_SERVICE_DATABASE_URL" not in os.environ
    finally:
        get_settings.cache_clear()


def test_the_api_key_is_deliberately_not_popped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The honest limit of the mitigation above.

    The subprocess AUTHENTICATES with `ANTHROPIC_API_KEY`, so it must stay in
    the environment and is always readable by the agent. Controls there are
    budget, key scoping and spend monitoring -- not concealment. A test asserts
    it so nobody "fixes" the asymmetry and breaks every run.
    """
    import os

    from agent_service.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    get_settings.cache_clear()
    try:
        get_settings()
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"
    finally:
        get_settings.cache_clear()


def test_the_persistence_service_is_opt_in_and_does_not_break_a_plain_config() -> None:
    """`postgres` must be behind a profile, with no REQUIRED variables.

    Compose interpolates every service in the file whatever profile is active,
    so a `${VAR:?...}` in the postgres block fails `config`, `ps` and `logs`
    for someone who never asked for persistence -- the same trap CP-092
    records for the mount paths. Caught exactly that way while writing it.
    """
    compose = Path(__file__).resolve().parents[1] / "compose.yaml"
    text = compose.read_text(encoding="utf-8")
    postgres_block = text[text.index("  postgres:") :]
    assert 'profiles: ["persistence"]' in postgres_block
    # COMMENTS STRIPPED FIRST: the block explains why `:?` is wrong, and a
    # naive substring check matches that prose and fails on the explanation.
    directives = [
        line for line in postgres_block.splitlines() if not line.strip().startswith("#")
    ]
    assert not [ln for ln in directives if ":?" in ln], (
        "a required variable here breaks compose for everyone"
    )
    # Not published: the service reaches it over the compose network. Checked
    # against the stripped directives for the same reason as above -- the
    # comment right there explains why there is no `ports:` key, and a raw
    # substring search matches the explanation.
    assert not [ln for ln in directives if ln.strip().startswith("ports:")]


# -- require_mounts -----------------------------------------------------------
#
# The failure this guards is silent in both directions, which is why it is a
# boot check and not a log line. See `config.verify_mounts`.


def test_require_mounts_is_off_by_default_so_a_checkout_still_boots(
    tmp_path: Path,
) -> None:
    """Unlike `require_credentials`, this defaults FALSE.

    Outside a container there is nothing to verify: `workspace_dir` defaults to
    `./workspace` and the validator creates it on first run, which is correct
    behaviour there. Defaulting true would break every non-container run and
    the whole test suite.
    """
    settings = Settings(workspace_dir=tmp_path / "ws")
    assert settings.require_mounts is False
    verify_mounts(settings)  # must not raise


def test_an_unmounted_workspace_refuses_the_boot(tmp_path: Path) -> None:
    """A directory this service created is exactly the state the bug produces.

    `tmp_path` is on an ordinary filesystem, so nothing below the drive root is
    a mount point -- which is the same shape as a container missing its
    `-v ...:/workspace`.
    """
    settings = Settings(workspace_dir=tmp_path / "ws", require_mounts=True)
    assert settings.workspace_dir.exists(), "the validator creates it; that is the trap"

    with pytest.raises(MissingMounts) as excinfo:
        verify_mounts(settings)

    message = str(excinfo.value)
    assert "AGENT_SERVICE_WORKSPACE_DIR" in message
    assert "-v /host/path:/workspace" in message, "name the fix, not just the fault"
    assert "AGENT_SERVICE_REQUIRE_MOUNTS=false" in message, "name the escape hatch"


def test_a_reference_dir_that_does_not_exist_refuses_the_boot(tmp_path: Path) -> None:
    """The mount-target/env-var mismatch, which today is accepted silently:
    `reference_dirs` is resolved and never checked."""
    settings = Settings(
        workspace_dir=tmp_path / "ws",
        reference_dirs=[tmp_path / "typo-in-this-name"],
        require_mounts=True,
    )
    with pytest.raises(MissingMounts) as excinfo:
        verify_mounts(settings)
    assert "typo-in-this-name" in str(excinfo.value)


def test_a_reference_dir_need_only_EXIST_not_be_a_mount_point(
    tmp_path: Path, monkeypatch
) -> None:
    """Asymmetric on purpose. A reference directory is never created by this
    service, so existence already separates a good config from a typo -- and
    requiring a mount point would reject naming a SUBDIRECTORY of one, which is
    a legitimate layout."""
    ref = tmp_path / "reference-repo"
    ref.mkdir()
    settings = Settings(
        workspace_dir=tmp_path / "ws", reference_dirs=[ref], require_mounts=True
    )
    # Workspace still fails (nothing is mounted here), so pin the reference
    # half by asserting it is absent from the complaint.
    with pytest.raises(MissingMounts) as excinfo:
        verify_mounts(settings)
    assert "reference-repo" not in str(excinfo.value)


def test_a_workspace_under_a_mount_point_is_accepted(tmp_path: Path, monkeypatch) -> None:
    """`ismount` on the path itself is too strict: `-v host:/data` with
    `AGENT_SERVICE_WORKSPACE_DIR=/data/ws` is a correct configuration. The
    check walks up, so an ancestor being a mount is enough."""
    import os as _os

    mount_root = tmp_path / "data"
    (mount_root / "ws").mkdir(parents=True)
    real_ismount = _os.path.ismount
    monkeypatch.setattr(
        _os.path, "ismount", lambda p: Path(p) == mount_root or real_ismount(p)
    )

    settings = Settings(workspace_dir=mount_root / "ws", require_mounts=True)
    verify_mounts(settings)  # must not raise


def test_the_root_is_not_counted_as_a_mount(tmp_path: Path, monkeypatch) -> None:
    """A container's `/` IS a mount point. Counting it would make the check
    pass for every path and quietly do nothing -- the exact failure mode this
    whole function exists to remove."""
    import os as _os

    anchor = Path(tmp_path.anchor)
    real_ismount = _os.path.ismount
    monkeypatch.setattr(
        _os.path, "ismount", lambda p: Path(p) == anchor or real_ismount(p)
    )

    settings = Settings(workspace_dir=tmp_path / "ws", require_mounts=True)
    with pytest.raises(MissingMounts):
        verify_mounts(settings)


def test_a_refused_boot_starts_no_reaper(no_credentials, tmp_path: Path) -> None:
    """Same guarantee `verify_credentials` has: refusing must leave nothing
    running. `verify_mounts` is called from the lifespan before
    `start_reaper()` and outside the `try`, so this pins the ordering."""
    from agent_service.api import create_app
    from agent_service.registry import SessionRegistry

    class _RecordingRegistry(SessionRegistry):
        def __init__(self, s) -> None:  # noqa: ANN001
            super().__init__(s)
            self.start_calls = 0

        def start_reaper(self) -> None:
            self.start_calls += 1
            super().start_reaper()

    settings = Settings(
        workspace_dir=tmp_path / "ws",
        require_credentials=False,
        require_mounts=True,
    )
    registry = _RecordingRegistry(settings)
    app = create_app(settings=settings, registry=registry)

    async def boot() -> None:
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover - the enter above must raise

    with pytest.raises(MissingMounts):
        asyncio.run(boot())

    assert registry.start_calls == 0


def test_compose_turns_the_check_on() -> None:
    """The setting is only useful where the mounts are meant to exist, so the
    container config must opt in -- otherwise the guard ships switched off."""
    compose = Path(__file__).resolve().parents[1] / "compose.yaml"
    directives = [
        line
        for line in compose.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    ]
    assert any("AGENT_SERVICE_REQUIRE_MOUNTS" in ln and "true" in ln for ln in directives)


def test_no_database_is_the_default() -> None:
    """plan-03's global constraint: unset is a supported configuration, not a
    degraded one. If this ever defaults to a URL, the no-database path stops
    being exercised by every other test in the suite.

    **Here rather than with the ORM tests since 2026-08-08.** It asserts a
    default on THIS build's `Settings`, which is per-implementation; the shared
    package cannot import an implementation to check one.
    """
    assert Settings(workspace_dir="./workspace").database_url is None
