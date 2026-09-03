from pathlib import Path

import pytest

from agent_service.config import Settings
from agent_service.options import (
    InvalidWorkspacePath,
    LimitExceeded,
    McpServersNotAllowedError,
    build_options,
    resolve_workspace,
    workspace_description,
)
from agent_spec.openapi.schemas import RunOptions


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    ref = tmp_path / "reference" / "acme-api"
    ref.mkdir(parents=True)
    return Settings(workspace_dir=tmp_path / "ws", reference_dirs=[ref])


def test_defaults_are_applied(settings: Settings) -> None:
    opts, limits = build_options(RunOptions(), settings)
    assert opts.model == "claude-sonnet-5"
    assert opts.permission_mode == "dontAsk"
    assert limits.max_turns == 30
    assert limits.max_budget_usd == 2.0
    assert limits.timeout_s == 600


def test_request_overrides_win(settings: Settings) -> None:
    opts, limits = build_options(
        RunOptions(model="claude-opus-5", max_turns=5, max_budget_usd=0.5), settings
    )
    assert opts.model == "claude-opus-5"
    assert limits.max_turns == 5
    assert limits.max_budget_usd == 0.5


def test_exceeding_a_cap_raises_rather_than_clamping(settings: Settings) -> None:
    with pytest.raises(LimitExceeded) as exc:
        build_options(RunOptions(max_turns=9999), settings)
    assert exc.value.field == "max_turns"
    assert exc.value.cap == 200

    with pytest.raises(LimitExceeded):
        build_options(RunOptions(max_budget_usd=50.0), settings)
    with pytest.raises(LimitExceeded):
        build_options(RunOptions(timeout_s=99999), settings)


def test_ask_user_question_cannot_be_re_enabled(settings: Settings) -> None:
    opts, _ = build_options(
        RunOptions(allowed_tools=["AskUserQuestion", "Read"], disallowed_tools=[]), settings
    )
    assert "AskUserQuestion" in opts.disallowed_tools
    assert "AskUserQuestion" not in opts.allowed_tools


def test_setting_sources_is_always_explicit(settings: Settings) -> None:
    # Never None: unset loads ambient ~/.claude and ./.claude (F8).
    opts, _ = build_options(RunOptions(), settings)
    assert opts.setting_sources == []

    opts, _ = build_options(RunOptions(setting_sources=["project"]), settings)
    assert opts.setting_sources == ["project"]


def test_reference_dirs_become_add_dirs(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(), settings)
    assert [str(p) for p in opts.add_dirs] == [str(settings.reference_dirs[0])]


def test_cwd_is_the_workspace(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(), settings)
    assert Path(opts.cwd) == settings.workspace_dir


def test_working_directory_is_resolved_under_the_root(settings: Settings) -> None:
    (settings.workspace_dir / "proj").mkdir()
    assert resolve_workspace(settings, "proj") == settings.workspace_dir / "proj"


@pytest.mark.parametrize("bad", ["../escape", "/etc", "a/../../b"])
def test_working_directory_cannot_escape(settings: Settings, bad: str) -> None:
    with pytest.raises(InvalidWorkspacePath):
        resolve_workspace(settings, bad)


def test_working_directory_that_does_not_exist_is_rejected(settings: Settings) -> None:
    # In-root and syntactically valid, but never created on disk. Path.resolve()
    # does not raise for a missing target, so this must be checked explicitly
    # rather than relying on the except OSError branch (fix round 1, finding 1).
    with pytest.raises(InvalidWorkspacePath):
        resolve_workspace(settings, "does-not-exist")


def test_workspace_description_names_both_mount_kinds(settings: Settings) -> None:
    text = workspace_description(settings)
    assert str(settings.workspace_dir) in text
    assert "read-write" in text
    assert str(settings.reference_dirs[0]) in text
    assert "read-only" in text


def test_description_is_appended_to_a_plain_system_prompt(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(system_prompt="You are terse."), settings)
    assert opts.system_prompt.startswith("You are terse.")
    assert "read-only" in opts.system_prompt


def test_description_uses_append_on_a_preset_system_prompt(settings: Settings) -> None:
    preset = {"type": "preset", "preset": "claude_code"}
    opts, _ = build_options(RunOptions(system_prompt=preset), settings)
    assert opts.system_prompt["type"] == "preset"
    assert "read-only" in opts.system_prompt["append"]


def test_description_preserves_and_prepends_an_existing_append(settings: Settings) -> None:
    preset = {"type": "preset", "preset": "claude_code", "append": "Existing instruction."}
    opts, _ = build_options(RunOptions(system_prompt=preset), settings)
    appended = opts.system_prompt["append"]
    assert appended.startswith("Existing instruction.")
    assert "read-only" in appended
    assert appended.index("Existing instruction.") < appended.index("read-only")


def test_description_is_the_whole_prompt_when_none_was_given(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(system_prompt=None), settings)
    assert opts.system_prompt == workspace_description(settings)


def test_description_can_be_disabled(tmp_path: Path) -> None:
    s = Settings(workspace_dir=tmp_path / "ws", include_workspace_description=False)
    opts, _ = build_options(RunOptions(system_prompt="Hi."), s)
    assert opts.system_prompt == "Hi."


def test_build_options_does_not_mutate_settings_owned_lists(settings: Settings) -> None:
    allowed_before = list(settings.default_allowed_tools)
    reference_dirs_before = list(settings.reference_dirs)

    build_options(RunOptions(), settings)

    assert settings.default_allowed_tools == allowed_before
    assert settings.reference_dirs == reference_dirs_before


def test_limits_exactly_at_the_cap_are_accepted(settings: Settings) -> None:
    opts, limits = build_options(
        RunOptions(max_turns=200, max_budget_usd=10.0, timeout_s=1800), settings
    )
    assert limits.max_turns == 200
    assert limits.max_budget_usd == 10.0
    assert limits.timeout_s == 1800
    assert opts.max_turns == 200
    assert opts.max_budget_usd == 10.0


def test_explicit_ask_user_question_disallow_is_not_duplicated(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(disallowed_tools=["AskUserQuestion"]), settings)
    assert opts.disallowed_tools.count("AskUserQuestion") == 1


# --- permission_enforcement (Task 11 follow-up) -------------------------
#
# Five live probes (spike/probe_permissions.py, CP-066
# "Permission enforcement -- measured, not guessed") found that can_use_tool
# never fires under this service's allowed_tools style, so it is not offered
# as a selectable enforcement mode at all -- only "hook" is, since it is the
# mechanism measured to actually block a write. Default is "none": neither
# can_use_tool nor hooks is wired, and the container/mount is the only
# boundary.


def test_permission_enforcement_defaults_to_none_and_wires_nothing(settings: Settings) -> None:
    opts, _ = build_options(RunOptions(), settings)
    assert opts.can_use_tool is None
    assert opts.hooks is None


def test_permission_enforcement_hook_wires_a_pretooluse_hook_only(tmp_path: Path) -> None:
    s = Settings(workspace_dir=tmp_path / "ws", permission_enforcement="hook")
    opts, _ = build_options(RunOptions(), s)

    assert opts.can_use_tool is None
    assert opts.hooks is not None
    assert set(opts.hooks) == {"PreToolUse"}
    matchers = opts.hooks["PreToolUse"]
    assert len(matchers) == 1
    # Built from policy.WRITE_TOOLS via "|".join(sorted(...)) -- alphabetical.
    assert matchers[0].matcher == "Edit|NotebookEdit|Write"
    assert len(matchers[0].hooks) == 1


async def test_permission_enforcement_hook_effective_cwd_is_the_working_directory(
    tmp_path: Path,
) -> None:
    # Same fix-round-1 concern as the old can_use_tool test this replaces: a
    # relative file_path must resolve against the subdir actually used as
    # cwd, not against the whole workspace root.
    s = Settings(workspace_dir=tmp_path / "ws", permission_enforcement="hook")
    (s.workspace_dir / "proj").mkdir()
    opts, _ = build_options(RunOptions(working_directory="proj"), s)

    hook = opts.hooks["PreToolUse"][0].hooks[0]
    result = await hook({"tool_name": "Write", "tool_input": {"file_path": "a.txt"}}, None, {"signal": None})

    assert result == {}


# --- MCP servers (0.8.0) ----------------------------------------------------


def test_no_mcp_servers_sends_an_empty_dict_not_none(settings: Settings) -> None:
    """`{}` is the SDK's own default for `mcp_servers`; `None` is not a type it
    declares. The empty case is the shipped default, so it is the one that must
    not surprise the SDK."""
    opts, _ = build_options(RunOptions(), settings)

    assert opts.mcp_servers == {}


def test_mcp_servers_reach_the_sdk_without_null_placeholders(settings: Settings) -> None:
    """`args`, `env` and `headers` are NotRequired in the SDK's TypedDicts, and
    this crosses to the CLI as JSON -- where an explicit `null` is NOT the same
    as absent. `model_dump(exclude_none=True)` is what keeps them out, and this
    is the test that says so: an http server must carry no `env` key at all,
    not `env: null`."""
    opts, _ = build_options(
        RunOptions(
            mcp_servers={
                "remote": {"type": "http", "url": "https://mcp.example.com/mcp"},
                "local": {"type": "stdio", "command": "npx", "args": ["-y", "@acme/mcp"]},
            }
        ),
        settings,
    )

    assert opts.mcp_servers["remote"] == {
        "type": "http",
        "url": "https://mcp.example.com/mcp",
    }
    assert opts.mcp_servers["local"] == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@acme/mcp"],
    }


def test_strict_mcp_config_defaults_true_which_is_not_the_sdk_default(
    settings: Settings,
) -> None:
    """The SDK defaults `strict_mcp_config` to False. This service defaults it
    to True because the workspace is mounted from the host and writable by the
    agent, so CLI-side discovery (`.mcp.json`) could add servers the caller
    never sent and cannot see in its own request."""
    opts, _ = build_options(RunOptions(), settings)
    assert opts.strict_mcp_config is True

    opts, _ = build_options(RunOptions(strict_mcp_config=False), settings)
    assert opts.strict_mcp_config is False


def test_mcp_servers_are_refused_not_dropped_when_the_deployment_forbids_them(
    tmp_path: Path,
) -> None:
    """A 400, never a silent drop.

    Dropping them leaves a request that succeeds while doing something other
    than what it says -- the agent runs without tools the caller believes it
    has, and the caller sees an agent that is inexplicably bad at its job
    rather than a configuration refusal.
    """
    s = Settings(workspace_dir=tmp_path / "ws", allow_mcp_servers=False)

    with pytest.raises(McpServersNotAllowedError) as excinfo:
        build_options(
            RunOptions(mcp_servers={"b": {"type": "http", "url": "https://e.com"}}), s
        )

    # Names what was refused and where to check before retrying.
    assert "b" in str(excinfo.value)
    assert "allow_mcp_servers" in str(excinfo.value)


def test_forbidding_mcp_servers_does_not_break_a_request_without_them(
    tmp_path: Path,
) -> None:
    """The gate fires on the FIELD, not on the setting. A deployment with MCP
    off still serves every ordinary request."""
    s = Settings(workspace_dir=tmp_path / "ws", allow_mcp_servers=False)

    opts, _ = build_options(RunOptions(), s)

    assert opts.mcp_servers == {}


def test_the_sdk_only_mcp_shape_cannot_be_expressed(settings: Settings) -> None:
    """`McpSdkServerConfig` carries a live in-process object (`instance`), so it
    could never cross an HTTP boundary. It is absent from the union rather than
    rejected at runtime, which makes the OpenAPI document say so."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RunOptions(mcp_servers={"x": {"type": "sdk", "name": "in-process"}})
