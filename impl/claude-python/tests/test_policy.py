import os
from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from agent_service.policy import make_permission_hook, make_policy


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


async def test_write_inside_the_workspace_is_allowed(workspace: Path) -> None:
    policy = make_policy(workspace)
    result = await policy("Write", {"file_path": str(workspace / "a.txt")}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_write_outside_the_workspace_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace)
    result = await policy("Write", {"file_path": "/etc/passwd"}, None)
    assert isinstance(result, PermissionResultDeny)
    assert "workspace" in result.message


async def test_traversal_out_of_the_workspace_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace)
    result = await policy("Edit", {"file_path": str(workspace / ".." / "escape.txt")}, None)
    assert isinstance(result, PermissionResultDeny)


async def test_reads_are_not_path_restricted(workspace: Path) -> None:
    # Reference mounts live outside the workspace and must stay readable.
    policy = make_policy(workspace)
    result = await policy("Read", {"file_path": "/reference/acme/main.py"}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_a_write_with_no_path_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace)
    result = await policy("Write", {}, None)
    assert isinstance(result, PermissionResultDeny)


async def test_unrecognised_tools_are_allowed(workspace: Path) -> None:
    policy = make_policy(workspace)
    result = await policy("Glob", {"pattern": "**/*.py"}, None)
    assert isinstance(result, PermissionResultAllow)


# --- fix round 1 -------------------------------------------------------
# Finding 1 (CRITICAL): a non-string file_path is truthy (so it survives the
# `not raw_path` guard) but Path(...) raises TypeError for it, which the
# `except OSError` did not catch -- the callback crashed instead of denying.


@pytest.mark.parametrize(
    "bad_file_path",
    [12345, {"a": 1}, ["a"], True],
    ids=["int", "dict", "list", "bool"],
)
async def test_non_string_file_path_is_denied_not_raised(workspace: Path, bad_file_path) -> None:
    policy = make_policy(workspace)
    result = await policy("Write", {"file_path": bad_file_path}, None)
    assert isinstance(result, PermissionResultDeny)


# fix round 2, (b): the null-byte coverage here was replaced -- it used an
# absolute out-of-workspace path and so passed via ordinary containment
# rather than exercising the broadened except clause. See the monkeypatched
# and POSIX-only tests in the "fix round 2" section below.


# Finding 2 (CRITICAL): a relative file_path was resolved against the policy
# process's own os.getcwd(), not against the workspace or the SDK subprocess's
# actual cwd -- so a legitimate relative write inside the workspace was
# falsely denied, and the base used for the check was an operational
# accident rather than a boundary.


async def test_relative_write_inside_effective_cwd_is_allowed(workspace: Path) -> None:
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "a.txt"}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_relative_write_inside_a_working_directory_cwd_is_allowed(workspace: Path) -> None:
    subdir = workspace / "sub"
    subdir.mkdir()
    policy = make_policy(workspace, subdir)
    result = await policy("Write", {"file_path": "a.txt"}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_relative_traversal_escaping_workspace_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "../outside.txt"}, None)
    assert isinstance(result, PermissionResultDeny)


def _can_make_symlinks(target: Path, link: Path) -> bool:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return True


async def test_symlink_escaping_workspace_is_denied(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret")
    link = workspace / "link.txt"
    if not _can_make_symlinks(secret, link):
        pytest.skip("cannot create symlinks in this environment (needs elevated privileges)")

    policy = make_policy(workspace)
    result = await policy("Write", {"file_path": str(link)}, None)
    assert isinstance(result, PermissionResultDeny)


# --- fix round 2 -------------------------------------------------------
# NEW FINDING (CRITICAL, a regression introduced by fix round 1): the
# absolute/relative branch decision ran on the raw, un-expanded path, with
# .expanduser() applied only afterwards to the already-joined result. A
# tilde path is not is_absolute(), so it took the relative branch and got
# joined onto `base` (e.g. <workspace>/sub/~/foo.txt`) *before* expansion was
# attempted -- and expanduser() only expands a *leading* ~ component, so once
# it is buried inside the joined path it is a no-op. The result resolved
# INSIDE the workspace and was incorrectly ALLOWED, where both the pre-fix
# code and the original brief correctly expanded ~ to the real home
# directory and denied it.


async def test_tilde_path_write_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "~/escape.txt"}, None)
    assert isinstance(result, PermissionResultDeny)


async def test_tilde_alone_write_is_denied(workspace: Path) -> None:
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "~"}, None)
    assert isinstance(result, PermissionResultDeny)


async def test_existing_relative_write_tests_are_unaffected_by_the_reorder(workspace: Path) -> None:
    # The reorder (expand first, then decide absolute-vs-relative) must not
    # change behavior for ordinary relative paths without a tilde.
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "a.txt"}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_a_path_resolution_error_is_denied_not_raised(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (b): the null-byte test previously added did not actually exercise the
    # broadened except clause -- it passed via ordinary containment, for an
    # unrelated reason. This monkeypatches the resolution call itself so the
    # handler is genuinely exercised on every platform.
    # Build the policy (which itself calls .resolve() on the workspace root
    # and effective cwd) BEFORE patching, so only the in-callback resolution
    # of the candidate path is affected.
    policy = make_policy(workspace, workspace)

    def _raise_value_error(self: Path) -> Path:
        raise ValueError("embedded null byte")

    monkeypatch.setattr(Path, "resolve", _raise_value_error)
    result = await policy("Write", {"file_path": "a.txt"}, None)
    assert isinstance(result, PermissionResultDeny)


async def test_an_expanduser_runtime_error_is_denied_not_raised(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (a): Path.expanduser() raises RuntimeError when no home directory can
    # be resolved. That was not in the caught tuple and would have crashed
    # the callback -- the same fail-crash class as the original Finding 1.
    def _raise_runtime_error(self: Path) -> Path:
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(Path, "expanduser", _raise_runtime_error)
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "~/escape.txt"}, None)
    assert isinstance(result, PermissionResultDeny)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not raise for an embedded null byte")
async def test_a_real_null_byte_in_path_is_denied_not_raised_posix(workspace: Path) -> None:
    policy = make_policy(workspace, workspace)
    result = await policy("Write", {"file_path": "hello\x00.txt"}, None)
    assert isinstance(result, PermissionResultDeny)


# --- shared predicate parity (Task 11 follow-up) ------------------------
#
# make_policy (the can_use_tool callback) and make_permission_hook (the
# PreToolUse hook actually wired up by options.py -- see
# CP-066, "Permission enforcement -- measured, not guessed")
# both call the same _denial_reason predicate. These tests assert that
# directly: the two mechanisms cannot give different answers to the same
# input, even though only one of them is ever consulted by the SDK in a live
# run under this service's tool configuration.


async def test_policy_and_hook_agree_on_an_allowed_write(workspace: Path) -> None:
    policy = make_policy(workspace)
    hook = make_permission_hook(workspace)
    target = str(workspace / "a.txt")

    policy_result = await policy("Write", {"file_path": target}, None)
    hook_result = await hook(
        {"tool_name": "Write", "tool_input": {"file_path": target}}, None, {"signal": None}
    )

    assert isinstance(policy_result, PermissionResultAllow)
    assert hook_result == {}


async def test_policy_and_hook_agree_on_a_denied_write(workspace: Path) -> None:
    policy = make_policy(workspace)
    hook = make_permission_hook(workspace)
    outside = "/etc/passwd"

    policy_result = await policy("Write", {"file_path": outside}, None)
    hook_result = await hook(
        {"tool_name": "Write", "tool_input": {"file_path": outside}}, None, {"signal": None}
    )

    assert isinstance(policy_result, PermissionResultDeny)
    hook_output = hook_result["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny"
    assert hook_output["hookEventName"] == "PreToolUse"
    # Same predicate, so the same human-readable reason on both paths.
    assert policy_result.message == hook_output["permissionDecisionReason"]


async def test_policy_and_hook_agree_that_reads_are_unrestricted(workspace: Path) -> None:
    policy = make_policy(workspace)
    hook = make_permission_hook(workspace)
    outside = "/reference/acme/main.py"

    policy_result = await policy("Read", {"file_path": outside}, None)
    hook_result = await hook(
        {"tool_name": "Read", "tool_input": {"file_path": outside}}, None, {"signal": None}
    )

    assert isinstance(policy_result, PermissionResultAllow)
    assert hook_result == {}
