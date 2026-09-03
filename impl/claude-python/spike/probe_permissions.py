"""Live spike: does `can_use_tool` actually run, and does a `PreToolUse` hook,
under the allowed_tools configurations this service can ship?

Task 11's live verification (item 6) found that a real out-of-workspace Write
succeeded with `permission_denials: []` under the service's shipped defaults.
The installed SDK's own `CanUseToolShadowedWarning` explained why:
`default_allowed_tools` grants `Write`/`Edit` as bare, unscoped entries, and an
unscoped `allowed_tools` entry auto-approves that tool before `can_use_tool` is
ever consulted. The plan has already been burned twice by inferring SDK
behaviour instead of measuring it (the limit markers in `probe_limits.py`, and
now this) -- so this script makes five real, minimal API calls instead of
reasoning further from source code alone.

Every callback/hook below unconditionally DENIES and records that it fired,
via a list captured in its closure -- the point of each case is only "did the
callback/hook get invoked at all" and "did the deny decision actually stop the
write", not path-matching logic (that is already covered by `test_policy.py`).

Cases (CP-066 is the write-up):
  1. allowed_tools=["Write"] (whole-tool) + can_use_tool, permission_mode="dontAsk"
  2. allowed_tools=[] (Write NOT allow-listed) + can_use_tool, permission_mode="default"
  3. Same as 2 but permission_mode="dontAsk"
  4. allowed_tools=["Write"] (whole-tool) + a PreToolUse hook, no can_use_tool
  5. Both a hook AND can_use_tool, allowed_tools=["Write"] (whole-tool)
  6. Review round 1, Finding 4: the *shipped* three-way matcher
     "Edit|NotebookEdit|Write" (`options.py`'s `_WRITE_TOOL_MATCHER`, imported
     directly here so this cannot silently drift from what production wires
     up), allowed_tools=["Write", "Edit"], with the agent asked to EDIT (not
     write) a file outside the workspace. Case 4 only ever exercised a bare
     "Write" matcher string; whether pipe-alternation actually matches a tool
     name other than the literal first one was inferred from the SDK's own
     docstring example, not observed -- exactly the class of assumption this
     whole spike exists to stop making.

One shared scratch workspace and "outside" directory are reused across cases
1-5 (only the escaped-to filename differs) so the `cwd` path stays
byte-stable across cases and prompt caching keeps cost down -- distinct
workspaces would mean five cold-cache runs instead of one cold plus four warm.
Case 6 was added later (review round 1) and runs standalone in its own
scratch dir.

`model` is pinned to `claude-sonnet-5` explicitly: these calls build
`ClaudeAgentOptions` directly rather than going through this service's
`options.py`, so none of `config.py`'s defaults apply, and an unset `model`
would resolve to `claude-opus-5[1m]` at roughly double the cold-run cost
(CP-062) -- that would blow the budget.

`max_turns=3` and a one-line prompt on every case, per the brief. Every stray
file that does get created (or, for case 6, edited) is deleted/restored
immediately after that case's report.

    uv run --env-file .env python spike/probe_permissions.py            # all 6
    uv run --env-file .env python spike/probe_permissions.py 1 4        # just these
    uv run --env-file .env python spike/probe_permissions.py 6          # just the alternation check
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    query,
)

# Case 6 (review round 1, Finding 4) imports the actual shipped matcher string
# rather than retyping "Edit|NotebookEdit|Write" by hand -- retyping it would
# only prove the copy is right, not that production wires up the same thing.
from agent_service.options import _WRITE_TOOL_MATCHER  # noqa: E402

TIMEOUT_S = 120
MODEL = "claude-sonnet-5"


async def _stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Single-message streaming format. Required for can_use_tool to run at
    all (Task 11 finding, fixed in runner.py commit e7e494d) -- used
    uniformly here, including the hook-only case, so every case is measured
    under identical prompt-delivery conditions.
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


def make_recording_denier(fired: list[dict[str, Any]]):
    """A can_use_tool callback that always denies and records every call."""

    async def policy(tool_name: str, input_data: dict[str, Any], context: Any):
        fired.append({"tool_name": tool_name, "input": input_data})
        return PermissionResultDeny(message="probe: denying to test enforcement")

    return policy


def make_recording_denying_hook(fired: list[dict[str, Any]]):
    """A PreToolUse hook that always denies and records every call."""

    async def hook(input_data: dict[str, Any], tool_use_id: str | None, context: Any):
        fired.append(
            {
                "tool_name": input_data.get("tool_name"),
                "input": input_data.get("tool_input"),
            }
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "probe: denying to test enforcement",
            }
        }

    return hook


async def run_query(prompt: str, options: ClaudeAgentOptions) -> ResultMessage | None:
    result: ResultMessage | None = None
    try:
        async with asyncio.timeout(TIMEOUT_S):
            async for msg in query(prompt=_stream(prompt), options=options):
                if isinstance(msg, ResultMessage):
                    result = msg
    except TimeoutError:
        print("  !! TIMED OUT before a ResultMessage arrived")
    except Exception as exc:  # noqa: BLE001
        print(f"  !! query() raised {type(exc).__name__}: {exc}")
    return result


def report(
    case_id: str,
    description: str,
    fired: list[dict[str, Any]],
    target: Path,
    result: ResultMessage | None,
    shadow_warnings: list[str],
) -> dict[str, Any]:
    print(f"\n{'=' * 78}\nCASE {case_id}: {description}\n{'=' * 78}")
    print(f"  callback/hook fired : {bool(fired)}  ({len(fired)} call(s))")
    if fired:
        print(f"    first call: {fired[0]}")
    file_exists = target.exists()
    print(f"  file exists on disk : {file_exists}")
    subtype = result.subtype if result else None
    is_error = result.is_error if result else None
    denials = result.permission_denials if result else None
    cost = result.total_cost_usd if result else None
    print(f"  subtype             : {subtype!r}")
    print(f"  is_error            : {is_error!r}")
    print(f"  permission_denials  : {json.dumps(denials, indent=2)}")
    print(f"  cost_usd            : {cost!r}")
    if shadow_warnings:
        print(f"  CanUseToolShadowedWarning captured: {shadow_warnings}")
    if target.exists():
        target.unlink()
        print(f"  (cleaned up stray file at {target})")
    return {
        "case": case_id,
        "description": description,
        "fired": bool(fired),
        "write_succeeded": file_exists,
        "subtype": subtype,
        "is_error": is_error,
        "permission_denials": denials,
        "cost": cost or 0.0,
        "shadow_warnings": shadow_warnings,
    }


async def case_1(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    target = outside_dir / "case1_escape.txt"
    fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        allowed_tools=["Write"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=3,
        can_use_tool=make_recording_denier(fired),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_query(f"Write the word hi to {target}", options)
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    return report(
        "1",
        "allowed_tools=['Write'] (whole-tool) + can_use_tool, permission_mode=dontAsk",
        fired,
        target,
        result,
        shadow,
    )


async def case_2(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    target = outside_dir / "case2_escape.txt"
    fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        allowed_tools=[],
        permission_mode="default",
        setting_sources=[],
        max_turns=3,
        can_use_tool=make_recording_denier(fired),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_query(f"Write the word hi to {target}", options)
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    return report(
        "2",
        "allowed_tools=[] (Write NOT allow-listed) + can_use_tool, permission_mode=default",
        fired,
        target,
        result,
        shadow,
    )


async def case_3(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    target = outside_dir / "case3_escape.txt"
    fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=3,
        can_use_tool=make_recording_denier(fired),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_query(f"Write the word hi to {target}", options)
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    return report(
        "3",
        "allowed_tools=[] (Write NOT allow-listed) + can_use_tool, permission_mode=dontAsk",
        fired,
        target,
        result,
        shadow,
    )


async def case_4(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    target = outside_dir / "case4_escape.txt"
    fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        allowed_tools=["Write"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=3,
        hooks={"PreToolUse": [HookMatcher(matcher="Write", hooks=[make_recording_denying_hook(fired)])]},
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_query(f"Write the word hi to {target}", options)
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    return report(
        "4",
        "allowed_tools=['Write'] (whole-tool) + PreToolUse hook, no can_use_tool",
        fired,
        target,
        result,
        shadow,
    )


async def case_5(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    target = outside_dir / "case5_escape.txt"
    hook_fired: list[dict[str, Any]] = []
    callback_fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        allowed_tools=["Write"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=3,
        can_use_tool=make_recording_denier(callback_fired),
        hooks={"PreToolUse": [HookMatcher(matcher="Write", hooks=[make_recording_denying_hook(hook_fired)])]},
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_query(f"Write the word hi to {target}", options)
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    print(f"\n  (case 5 detail) hook fired: {bool(hook_fired)}, can_use_tool fired: {bool(callback_fired)}")
    combined_fired = hook_fired + callback_fired
    outcome = report(
        "5",
        "hook AND can_use_tool both set, allowed_tools=['Write'] (whole-tool)",
        combined_fired,
        target,
        result,
        shadow,
    )
    outcome["hook_fired"] = bool(hook_fired)
    outcome["can_use_tool_fired"] = bool(callback_fired)
    return outcome


async def case_6(workspace: Path, outside_dir: Path) -> dict[str, Any]:
    """Review round 1, Finding 4: does the shipped three-way matcher fire for
    a tool name it only matches via pipe-alternation ("Edit", not the literal
    "Write" every other case exercises)?

    Uses `_WRITE_TOOL_MATCHER` imported directly from `options.py` -- the
    exact string production wires up, not a hand-typed copy of it -- and
    `allowed_tools=["Write", "Edit"]` to match how this service actually
    grants both tools. The target file is pre-created with known content so
    the agent has something to Edit rather than Write; if the hook fails to
    fire, the content will differ afterwards.
    """
    target = outside_dir / "case6_edit_target.txt"
    original = "PLACEHOLDER_MARKER\n"
    target.write_text(original, encoding="utf-8")

    fired: list[dict[str, Any]] = []
    options = ClaudeAgentOptions(
        cwd=str(workspace),
        model=MODEL,
        # "Read" is added so the agent can inspect the file before editing it
        # without being denied outright (as in cases 2/3) before ever
        # attempting Edit -- Read is not in policy.WRITE_TOOLS, so allowing
        # it does not touch what this case is testing. First attempt (without
        # Read allowed) measured nothing: the agent tried Read, got denied at
        # the CLI layer, then gave up without ever calling Edit.
        allowed_tools=["Read", "Write", "Edit"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=4,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher=_WRITE_TOOL_MATCHER, hooks=[make_recording_denying_hook(fired)])
            ]
        },
    )
    # State the current content up front too, so the agent has no reason to
    # insist on reading first -- belt and suspenders alongside allowing Read.
    prompt = (
        f"The file at {target} currently contains exactly the text "
        f"'PLACEHOLDER_MARKER' (plus a trailing newline). Use the Edit tool "
        f"to change PLACEHOLDER_MARKER to CHANGED_MARKER in that file."
    )
    result = await run_query(prompt, options)

    print(
        f"\n{'=' * 78}\nCASE 6: shipped matcher {_WRITE_TOOL_MATCHER!r}, "
        f"allowed_tools=['Write','Edit'], tool exercised is Edit (alternation, not the literal)\n{'=' * 78}"
    )
    edit_calls = [f for f in fired if f.get("tool_name") == "Edit"]
    other_calls = [f for f in fired if f.get("tool_name") != "Edit"]
    print(f"  hook fired for Edit : {bool(edit_calls)}  (all tool_names seen: {[f.get('tool_name') for f in fired]})")
    if other_calls:
        print(f"  (also fired for): {other_calls}")
    after = target.read_text(encoding="utf-8") if target.exists() else None
    edit_succeeded = after != original
    print(f"  file content changed: {edit_succeeded}  (before={original!r}, after={after!r})")
    subtype = result.subtype if result else None
    is_error = result.is_error if result else None
    denials = result.permission_denials if result else None
    cost = result.total_cost_usd if result else None
    print(f"  subtype             : {subtype!r}")
    print(f"  is_error            : {is_error!r}")
    print(f"  permission_denials  : {json.dumps(denials, indent=2)}")
    print(f"  cost_usd            : {cost!r}")

    target.unlink(missing_ok=True)
    print(f"  (cleaned up test file at {target})")

    return {
        "case": "6",
        "description": (
            f"shipped matcher {_WRITE_TOOL_MATCHER!r} matching Edit via alternation, "
            "allowed_tools=['Write','Edit']"
        ),
        "fired": bool(edit_calls),
        "write_succeeded": edit_succeeded,
        "subtype": subtype,
        "is_error": is_error,
        "permission_denials": denials,
        "cost": cost or 0.0,
        "shadow_warnings": [],
    }


CASES = {
    "1": case_1,
    "2": case_2,
    "3": case_3,
    "4": case_4,
    "5": case_5,
    "6": case_6,
}


async def main() -> None:
    wanted = [a for a in sys.argv[1:] if a in CASES] or list(CASES)

    with tempfile.TemporaryDirectory(prefix="probe_perm_") as td:
        outer = Path(td)
        workspace = outer / "workspace"
        workspace.mkdir()
        outside_dir = outer / "outside"
        outside_dir.mkdir()
        print(f"workspace (cwd): {workspace}")
        print(f"outside target dir (NOT cwd or a subdir of it): {outside_dir}")

        outcomes = []
        total_cost = 0.0
        for case_id in wanted:
            outcome = await CASES[case_id](workspace, outside_dir)
            outcomes.append(outcome)
            total_cost += outcome["cost"]
            print(f"\n  running total spend: ${total_cost:.4f}")
            if total_cost > 0.55 and case_id != wanted[-1]:
                print(
                    "  !! approaching the $0.60 budget -- stopping before the "
                    "remaining cases rather than risk exceeding it."
                )
                break

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    for o in outcomes:
        print(
            f"  case {o['case']}: fired={o['fired']!s:5}  "
            f"write_succeeded={o['write_succeeded']!s:5}  "
            f"subtype={o['subtype']!r}  denials={o['permission_denials']}"
        )
    print(f"\n  TOTAL SPEND: ${total_cost:.4f}")


if __name__ == "__main__":
    # NOTE: do NOT set WindowsSelectorEventLoopPolicy. The SDK spawns the CLI
    # as a subprocess, and the selector loop raises NotImplementedError for
    # subprocess transports on Windows. The default Proactor loop is required.
    asyncio.run(main())
