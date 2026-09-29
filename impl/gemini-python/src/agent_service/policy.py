"""The tool boundary: an admin-tier policy file, generated from `allowed_tools`.

**This module IS the sandbox on this target, and that is not a figure of
speech.** The agent's own `--approval-mode` is neither a boundary nor
deterministic (GP-18), its `--sandbox` cannot start inside a container (GP-31),
and ACP's permission channel only decides what the policy already permits
(GP-27). What confines the agent is the file this module writes.

**Six rules, each paid for by a measurement**, and every one of them is a way to
get this wrong that was actually observed:

1. **Deny `*` and allow explicitly. Never deny by name** (GP-20) -- a denied
   tool is removed from the model's context rather than refused, so the agent
   experiences a world without it and solves the problem with the shell instead.
2. **Emit `allow` and `deny` only** (GP-22). `ask_user` does not become `deny`
   in headless the way the published documentation says; the tool stays
   registered, throws `unhandled_exception`, and the turn goes back to flailing.
3. **`mcpName` needs `toolName` beside it** (GP-29), which is precisely the
   shape the documentation tells you to omit.
4. **Deny redirection explicitly** (GP-24). The built-in guard is switched off
   under `yolo` and `auto_edit`, so `echo X > file` writes anything.
5. **`modes` spells it `autoEdit`; the CLI flag spells it `auto_edit`** (GP-25).
   One bad enum value discards the WHOLE file and the run proceeds with no
   policy at exit 0.
6. **Validate before use** (GP-26), keylessly, and refuse to start if rejected.

**Rule 5 is why this module exists at all rather than a template string.** The
trap is a vocabulary mismatch between two spellings the agent itself prints, and
code that cannot spell `auto_edit` into a `modes` field cannot fall into it.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: The approval modes a `modes = [...]` rule may name. **The CLI's
#: `--approval-mode` flag accepts `auto_edit`; this field does not** (GP-25).
#: Kept as a frozen set so an unknown value fails here, in Python, rather than
#: silently voiding the file the agent loads.
POLICY_MODES = frozenset({"default", "autoEdit", "yolo", "plan"})

#: `--approval-mode`'s vocabulary, which is NOT the above. The mapping between
#: them is the only place the two spellings meet.
FLAG_MODES: dict[str, str] = {
    "default": "default",
    "auto_edit": "autoEdit",
    "yolo": "yolo",
    "plan": "plan",
}

#: Deny-by-default sits below every allow, and every allow sits below the
#: redirection deny. In-tier numbers only order rules within one file; the tier
#: is what beats another file (GP-21), which is why this build writes ADMIN.
_DENY_ALL_PRIORITY = 900
_ALLOW_PRIORITY = 950
_HARD_DENY_PRIORITY = 990

class RawToml(str):
    """A value written as a TOML *literal* string, in single quotes.

    **Regexes need this and tool names must not have it.** `commandRegex` is
    anchored just after the opening quote of the serialized command, so the
    useful patterns contain a `"` -- which a basic string would have to escape
    and which `_toml_string` refuses on purpose. A literal string processes no
    escapes, so the pattern reaches the agent as written.

    Deliberately a distinct type rather than a flag: a caller-supplied tool name
    can never become one by accident.
    """

    __slots__ = ()


def _toml_literal(value: str) -> str:
    if "'" in value or "\n" in value or "\r" in value:
        raise PolicyError(f"{value!r} cannot be written as a TOML literal string")
    return f"'{value}'"


#: The tool a caller names when it wants a shell.
SHELL_TOOL = "run_shell_command"

#: "the serialized command contains a `>`" -- anchored just after the opening
#: quote, which is where `commandRegex` matches (GP-24).
_REDIRECTION = RawToml(r'[^"]*>')


class PolicyError(ValueError):
    """A policy this build refuses to write, or one the agent refused to load."""


@dataclass(frozen=True)
class ToolPolicy:
    """What a session is allowed to do, in this build's own vocabulary.

    `allowed_tools` is the caller's list from `RunOptions`. `None` means "this
    build's default", which is deliberately NOT "everything".
    """

    allowed_tools: tuple[str, ...] | None = None
    #: MCP servers whose tools are permitted, by server name. A server name with
    #: an underscore is refused: the agent parses an MCP tool name by splitting
    #: on the first `_` after `mcp_`, so it would make the rule ambiguous
    #: (GP-28).
    allowed_mcp_servers: tuple[str, ...] = ()
    #: Command prefixes the shell may run, e.g. `("git", "ls")`. Empty means the
    #: shell is not allowed at all.
    shell_prefixes: tuple[str, ...] = ()
    #: Rules scoped to one approval mode, if any. Keys are POLICY_MODES values.
    modes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for name in self.allowed_mcp_servers:
            if "_" in name:
                raise PolicyError(
                    f"MCP server name {name!r} contains an underscore; the agent "
                    "splits an MCP tool name on the first '_' after 'mcp_', which "
                    "makes the rule ambiguous (GP-28)"
                )
        for mode in self.modes:
            if mode not in POLICY_MODES:
                raise PolicyError(
                    f"{mode!r} is not a policy mode. Expected one of "
                    f"{sorted(POLICY_MODES)} -- note that the --approval-mode FLAG "
                    "spells it 'auto_edit' and this field spells it 'autoEdit', and "
                    "that one bad value discards the whole file (GP-25)"
                )
        if SHELL_TOOL in (self.allowed_tools or ()) and not self.shell_prefixes:
            raise PolicyError(
                f"{SHELL_TOOL} was allowed with no command prefixes. An "
                "unrestricted shell voids every other rule in the policy -- the "
                "agent writes files with it instead of the tool you denied "
                "(GP-20). Give prefixes, or leave the shell out."
            )


def _toml_string(value: str) -> str:
    """A TOML basic string. Refuses anything needing an escape.

    **Deliberately narrow.** Every value this module writes is a tool name, a
    server name or a command prefix; none of them legitimately contains a quote,
    a backslash or a newline, and a value that does is far more likely to be an
    injection attempt than a real prefix.
    """
    if any(ch in value for ch in '"\\\n\r\t') or not value:
        raise PolicyError(f"{value!r} cannot be written to a policy file")
    return f'"{value}"'


def _rule(**fields: object) -> str:
    lines = ["[[rule]]"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, RawToml):
            lines.append(f"{key} = {_toml_literal(value)}")
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, str):
            lines.append(f"{key} = {_toml_string(value)}")
        elif isinstance(value, (list, tuple)):
            joined = ", ".join(_toml_string(str(item)) for item in value)
            lines.append(f"{key} = [{joined}]")
        else:  # pragma: no cover - the dispatch above is exhaustive for our uses
            raise PolicyError(f"cannot write {key}={value!r}")
    return "\n".join(lines)


def build_admin_policy(policy: ToolPolicy) -> str:
    """Render `policy` as an admin-tier TOML document.

    **Admin tier, always** (GP-21): a tier base beats any in-tier priority, so a
    fragment loaded at the user tier -- which is where a caller's own file would
    land -- can widen nothing this build imposed.
    """
    modes = list(policy.modes) or None
    blocks = [
        "# GENERATED. Do not edit: `agent_service.policy` writes this per session.",
        "#",
        "# Deny-by-default with an explicit allowlist. Denying a tool BY NAME does",
        "# not work -- the agent reaches for the shell instead (GP-20).",
        _rule(toolName="*", decision="deny", priority=_DENY_ALL_PRIORITY, modes=modes),
    ]

    tools = [t for t in (policy.allowed_tools or ()) if t != SHELL_TOOL]
    if tools:
        blocks.append(
            _rule(toolName=sorted(tools), decision="allow",
                  priority=_ALLOW_PRIORITY, modes=modes)
        )

    for server in policy.allowed_mcp_servers:
        # `toolName` is REQUIRED beside `mcpName`, and omitting it -- which is
        # what the published reference tells you to do -- is rejected by the
        # schema, discarding the WHOLE file (GP-29).
        blocks.append(
            _rule(mcpName=server, toolName="*", decision="allow",
                  priority=_ALLOW_PRIORITY, modes=modes)
        )

    if policy.shell_prefixes:
        blocks.append(
            _rule(toolName=SHELL_TOOL, commandPrefix=sorted(policy.shell_prefixes),
                  decision="allow", priority=_ALLOW_PRIORITY, modes=modes)
        )
        # **The redirection deny is not optional and outranks the allow above.**
        # The agent's own guard is switched off under `yolo` and `auto_edit`
        # (GP-24), so `echo HELLO > file` writes an arbitrary file through an
        # `echo`-only allowlist unless this rule exists.
        blocks.append(
            _rule(toolName=SHELL_TOOL, commandRegex=_REDIRECTION, decision="deny",
                  priority=_HARD_DENY_PRIORITY, modes=modes)
        )

    return "\n\n".join(blocks) + "\n"


def write_admin_policy(policy: ToolPolicy, path: Path) -> Path:
    """Render and write, returning the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_admin_policy(policy), encoding="utf-8")
    return path


def validate_admin_policy(path: Path, gemini: Path, cwd: Path | None = None) -> None:
    """Ask the AGENT whether it accepts the file. Free: no credential, no turn.

    **The only defence against GP-25**, where one bad enum value discards the
    whole file, the run proceeds with no policy at all, and the exit code is 0
    with nothing in the event stream. The error goes to stderr and nowhere else,
    so this reads stderr.

    Raises `PolicyError` if the agent rejects it. **A turn must not start after
    that**: a rejected file is not a weaker boundary, it is no boundary.

    **Three guards, and each one exists because its absence made this function
    pass when it should have failed** (GP-37):

    1. **The file must exist, checked here.** A `--admin-policy` naming a missing
       file is accepted *silently* -- exit 0, zero bytes of stderr, no policy
       applied. The agent will never tell us, so absence of complaint cannot be
       read as success.
    2. **An absolute path**, because a relative one is resolved against the
       agent's `cwd` and lands in exactly the same silent hole.
    3. **The probe must have RUN.** The first version stripped the environment to
       `PATH`, which on Windows is not enough to start the agent's shim: it
       exited 1 with both streams empty, so the marker was absent and every file
       validated. Silence only means "accepted" if the process spoke at all.
    """
    resolved = path.resolve()
    if not resolved.is_file():
        raise PolicyError(
            f"{resolved} is not a file. The agent accepts a --admin-policy that "
            "does not exist without a word of complaint and applies no policy at "
            "all, so this is checked here rather than inferred from its silence."
        )
    # **The environment is passed through unchanged.** Validation takes no turn
    # and spends nothing, and the agent parses the policy BEFORE it reaches its
    # credential gate -- measured: with no credential the run exits 41 and the
    # policy error still appears. Stripping the environment is what broke this
    # function the first time (GP-37).
    proc = subprocess.run(
        [str(gemini), "--list-sessions", "--admin-policy", str(resolved)],
        cwd=str(cwd or resolved.parent), capture_output=True, text=True, timeout=90,
    )
    if "Policy file error" in proc.stderr:
        detail = "\n".join(
            line for line in proc.stderr.splitlines() if "Policy" in line or "Field" in line
        )
        raise PolicyError(f"the agent rejected the generated policy:\n{detail}")
    # **The exit code is NOT the signal, and neither is stdout alone.** A run
    # with a credential exits 0 with a session listing; one without exits 41 with
    # its error envelope on stderr -- both parsed the policy. A shim that never
    # started produces zero bytes on BOTH streams, which is the only case where
    # the absence of a complaint means nothing.
    if not (proc.stdout.strip() or proc.stderr.strip()):
        raise PolicyError(
            f"the policy could not be validated: the agent exited "
            f"{proc.returncode} without writing to either stream, so it did not "
            "run. Its silence about the policy proves nothing."
        )


def parses_as_toml(document: str) -> dict:
    """A cheap local check, and NOT a substitute for `validate_admin_policy`.

    TOML validity says nothing about whether the agent's schema accepts the
    rules -- `mcpName` without `toolName` is perfectly good TOML and is rejected
    (GP-29). This exists so a unit test can read back what was written.
    """
    return tomllib.loads(document)
