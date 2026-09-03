"""The generated tool boundary.

**Free, and mostly local.** Everything except the last test is string and
structure; the last one asks the real agent to validate a file, which needs the
binary but no credential and no turn (GP-26).

**Each test names the way it went wrong when measured.** A policy generator is
exactly the kind of module whose tests drift into asserting its own output back
at it, so every case here is a defect that was observed rather than imagined.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agent_service.policy import (
    POLICY_MODES,
    SHELL_TOOL,
    PolicyError,
    ToolPolicy,
    build_admin_policy,
    parses_as_toml,
    validate_admin_policy,
    write_admin_policy,
)

ROOT = Path(__file__).resolve().parents[1]


def _rules(policy: ToolPolicy) -> list[dict]:
    return parses_as_toml(build_admin_policy(policy))["rule"]


def test_it_always_denies_everything_first() -> None:
    """GP-20: deny by wildcard and allow explicitly, never deny by name."""
    rules = _rules(ToolPolicy(allowed_tools=("read_file",)))
    assert rules[0] == {"toolName": "*", "decision": "deny", "priority": 900}


def test_the_allowlist_is_allowed_above_the_deny() -> None:
    rules = _rules(ToolPolicy(allowed_tools=("read_file", "write_file")))
    allow = next(r for r in rules if r.get("decision") == "allow")
    assert allow["toolName"] == ["read_file", "write_file"]
    assert allow["priority"] > rules[0]["priority"]


def test_it_never_emits_ask_user() -> None:
    """GP-22: `ask_user` does NOT degrade to deny in headless.

    The tool stays registered, throws `unhandled_exception`, and the turn goes
    back to flailing. There is no configuration in which this build should write
    one, so the assertion is over every decision the generator can produce.
    """
    policy = ToolPolicy(
        allowed_tools=("read_file", SHELL_TOOL),
        allowed_mcp_servers=("spikeserver",),
        shell_prefixes=("git",),
    )
    assert {r["decision"] for r in _rules(policy)} <= {"allow", "deny"}


def test_an_mcp_rule_carries_toolName_beside_mcpName() -> None:
    """GP-29: the documented shape -- `mcpName` alone -- is REJECTED.

    And a rejected file is discarded entirely, taking its `deny *` with it, so
    following the published reference here removes the boundary rather than
    widening it.
    """
    rules = _rules(ToolPolicy(allowed_mcp_servers=("spikeserver",)))
    mcp = next(r for r in rules if "mcpName" in r)
    assert mcp["toolName"] == "*", "mcpName without toolName is refused by the schema"


def test_an_mcp_server_name_with_an_underscore_is_refused() -> None:
    """GP-28: the agent splits on the first `_` after `mcp_`."""
    with pytest.raises(PolicyError, match="underscore"):
        ToolPolicy(allowed_mcp_servers=("spike_server",))


def test_allowing_the_shell_without_prefixes_is_refused() -> None:
    """GP-20: an unrestricted shell voids every other rule in the file.

    Measured: with `write_file` denied, the agent wrote the file anyway through
    `run_shell_command`. A policy that allows both is not a boundary, so this
    build refuses to write one rather than writing something that looks like it.
    """
    with pytest.raises(PolicyError, match="unrestricted shell"):
        ToolPolicy(allowed_tools=("read_file", SHELL_TOOL))


def test_a_permitted_shell_always_denies_redirection() -> None:
    """GP-24: the built-in guard is OFF under yolo and auto_edit.

    So `echo HELLO > hello.txt` writes an arbitrary file through an `echo`-only
    allowlist unless the policy says otherwise itself. The deny must also outrank
    the allow, or the allow wins.
    """
    rules = _rules(ToolPolicy(shell_prefixes=("echo",)))
    allow = next(r for r in rules if r.get("commandPrefix"))
    deny = next(r for r in rules if r.get("commandRegex"))
    assert deny["decision"] == "deny"
    assert deny["priority"] > allow["priority"]
    assert ">" in deny["commandRegex"]


def test_the_flag_spelling_is_refused_in_a_modes_rule() -> None:
    """GP-25: `--approval-mode` says `auto_edit`; `modes` says `autoEdit`.

    One bad enum value discards the WHOLE file and the run proceeds with no
    policy at exit 0, with nothing in the event stream. This is the single most
    dangerous typo available on this target, so it fails in Python.
    """
    assert "auto_edit" not in POLICY_MODES
    with pytest.raises(PolicyError, match="autoEdit"):
        ToolPolicy(modes=("auto_edit",))


def test_modes_scope_every_rule_when_given() -> None:
    """A mode-scoped policy must scope ALL of its rules or it is incoherent."""
    rules = _rules(ToolPolicy(allowed_tools=("read_file",), modes=("yolo",)))
    assert all(r["modes"] == ["yolo"] for r in rules)


def test_values_needing_an_escape_are_refused() -> None:
    with pytest.raises(PolicyError):
        build_admin_policy(ToolPolicy(allowed_tools=('read_file"',)))


def test_the_default_policy_is_not_everything() -> None:
    """No `allowed_tools` means this build's default, and it is deny-only.

    A generator whose empty case emits an empty file would hand the agent an
    unrestricted session, which is the opposite of the intended default.
    """
    rules = _rules(ToolPolicy())
    assert rules == [{"toolName": "*", "decision": "deny", "priority": 900}]


@pytest.mark.skipif(
    not (ROOT / "node_modules" / ".bin").exists(),
    reason="the agent is not installed; run `npm install --no-save @google/gemini-cli@0.54.4`",
)
def test_the_agent_itself_accepts_what_we_generate(tmp_path: Path) -> None:
    """GP-26: the preflight, against the real binary. No credential, no turn.

    **This is the test that matters.** Every assertion above is this module
    agreeing with itself; this one asks the thing that will actually load the
    file. It caught `mcpName`-without-`toolName` when the documentation said
    that shape was correct.
    """
    binary = ROOT / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")
    if not binary.exists():  # pragma: no cover - guarded by skipif above
        pytest.skip("gemini binary missing")
    policy = ToolPolicy(
        allowed_tools=("read_file", "write_file", "list_directory"),
        allowed_mcp_servers=("spikeserver",),
        shell_prefixes=("git", "ls"),
        modes=("yolo",),
    )
    path = write_admin_policy(policy, tmp_path / "admin.toml")
    validate_admin_policy(path, binary, cwd=tmp_path)


def test_a_missing_policy_file_is_refused_here_rather_than_by_the_agent(
    tmp_path: Path,
) -> None:
    """GP-37, and it needs no agent because the agent is the problem.

    A `--admin-policy` naming a file that does not exist is accepted **in
    silence**: exit 0, zero bytes of stderr, and no policy applied. That is a
    second way to run with no boundary, and unlike a malformed file it leaves no
    evidence at all. So existence is checked in Python.
    """
    with pytest.raises(PolicyError, match="not a file"):
        validate_admin_policy(tmp_path / "never-written.toml", Path("gemini"))


@pytest.mark.skipif(
    not (ROOT / "node_modules" / ".bin").exists(),
    reason="the agent is not installed",
)
def test_the_preflight_actually_rejects_a_bad_file(tmp_path: Path) -> None:
    """The negative control, without which the test above proves nothing.

    A preflight that accepts everything looks identical to a passing one.
    """
    binary = ROOT / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")
    bad = tmp_path / "bad.toml"
    # The GP-25 typo, written by hand because the generator refuses to produce it.
    bad.write_text(
        '[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 900\n\n'
        '[[rule]]\ntoolName = "write_file"\ndecision = "deny"\npriority = 990\n'
        'modes = ["auto_edit"]\n',
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="rejected"):
        validate_admin_policy(bad, binary, cwd=tmp_path)
