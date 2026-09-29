"""Write-confinement decision logic, plus its two SDK wiring points.

allowed_tools cannot express policy -- it is per-tool rather than per-path (L3)
and ignores scoped syntax such as Bash(git status:*) (L7). `can_use_tool` and a
`PreToolUse` hook are the two SDK mechanisms that receive the actual tool input
and can rule on it -- but they are NOT interchangeable in practice. Five live
probes (spike/probe_permissions.py, CP-066 "Permission
enforcement -- measured, not guessed") found `can_use_tool` never fires under
this service's tool configuration: a whole-tool `allowed_tools` entry (e.g.
`"Write"`) shadows it when the tool is granted, and the CLI denies outright
without consulting it when the tool is not granted. The `PreToolUse` hook DID
fire in both cases tested, and its deny decision genuinely blocked the write.

Consequently `config.Settings.permission_enforcement` only offers `"hook"` as
an in-process control (`"can_use_tool"` is not offered -- see config.py). Both
`make_policy` (the `can_use_tool` callback) and `make_permission_hook` (the
`PreToolUse` hook) are kept here and both call the same `_denial_reason`
predicate, so the two cannot silently drift from each other even though only
the hook is currently wired up by `options.py`. `make_policy` remains directly
unit-testable (`test_policy.py`) and available for manual/experimental use.

Denials appear in ResultMessage.permission_denials, so this audits itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    CanUseTool,
    HookCallback,
    HookContext,
    PermissionResultAllow,
    PermissionResultDeny,
    PreToolUseHookInput,
)

# Tools whose target path must stay inside the workspace.
WRITE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})


def _denial_reason(
    tool_name: str, input_data: dict[str, Any], root: Path, base: Path
) -> str | None:
    """Return a denial message if this call would write outside `root`, else None.

    `root` is the confinement boundary: every write must resolve inside it.
    `base` is the directory a *relative* file_path is resolved against -- the
    SDK subprocess's actual cwd (which may be a subdir of the workspace), not
    this process's own os.getcwd(). Both `root` and `base` must already be
    resolved by the caller.
    """
    if tool_name not in WRITE_TOOLS:
        return None
    raw_path = input_data.get("file_path")
    if not raw_path:
        return f"{tool_name} requires a file_path and none was supplied"
    try:
        # Expand ~ FIRST, then decide absolute-vs-relative, and only join onto
        # `base` if still relative after expansion. A tilde path is not
        # is_absolute(), and expanduser() only expands a *leading* ~
        # component -- deciding the branch before expanding, or joining
        # before expanding, buries the ~ inside base/~/foo.txt where
        # expanduser() becomes a no-op and the path wrongly resolves inside
        # the workspace (fix round 2).
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        target = candidate.resolve()
    except (TypeError, ValueError, OSError, RuntimeError):
        return f"unresolvable path: {raw_path!r}"
    if not target.is_relative_to(root):
        return f"writes are confined to the workspace ({root}); refused {target}"
    return None


def make_policy(workspace_root: Path, effective_cwd: Path | None = None) -> CanUseTool:
    """Build a can_use_tool callback bound to a workspace root.

    Not wired up by `options.py` by default -- see the module docstring and
    CP-066 for why. Kept for `test_policy.py` and for manual
    experimentation (e.g. against a future SDK version, or a non-whole-tool
    `allowed_tools` configuration that was not covered by the probe).
    """
    root = workspace_root.resolve()
    base = (effective_cwd or workspace_root).resolve()

    async def policy(
        tool_name: str, input_data: dict[str, Any], context: Any
    ) -> PermissionResultAllow | PermissionResultDeny:
        denial = _denial_reason(tool_name, input_data, root, base)
        if denial is not None:
            return PermissionResultDeny(message=denial)
        return PermissionResultAllow()

    return policy


def make_permission_hook(workspace_root: Path, effective_cwd: Path | None = None) -> HookCallback:
    """Build a PreToolUse hook bound to a workspace root.

    This is the mechanism `options.py` wires up for
    `permission_enforcement="hook"` -- the one measured live to actually run
    and actually block a write, unlike `make_policy` above.
    """
    root = workspace_root.resolve()
    base = (effective_cwd or workspace_root).resolve()

    async def hook(
        input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input") or {}
        denial = _denial_reason(tool_name, tool_input, root, base)
        if denial is not None:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": denial,
                }
            }
        return {}

    return hook
