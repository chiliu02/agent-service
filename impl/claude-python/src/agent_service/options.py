"""Translate a RunOptions request into ClaudeAgentOptions.

This module owns three responsibilities the SDK will not do for us:
  1. Enforce the two-valued limits (default + hard cap) from Q5.
  2. Keep workspace_subdir inside the workspace root.
  3. Force the invariants: AskUserQuestion disallowed, setting_sources explicit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from agent_service.config import ALWAYS_DISALLOWED_TOOLS, Settings
from agent_service.policy import WRITE_TOOLS, make_permission_hook
from agent_spec.openapi.schemas import RunOptions

# HookMatcher.matcher is a "|"-joined tool-name pattern, per the SDK's own
# example ("Write|MultiEdit|Edit"). Built from WRITE_TOOLS so the hook's
# scope cannot drift from policy.py's own idea of which tools write files.
_WRITE_TOOL_MATCHER = "|".join(sorted(WRITE_TOOLS))


class LimitExceeded(ValueError):
    def __init__(self, field: str, value: float, cap: float) -> None:
        super().__init__(f"{field}={value} exceeds the maximum allowed value of {cap}")
        self.field = field
        self.value = value
        self.cap = cap


class InvalidWorkspacePath(ValueError):
    pass


class McpServersNotAllowedError(ValueError):
    """The request sent `mcp_servers` to a deployment that forbids them.

    A 400 rather than a silent drop. Dropping them leaves a request that
    succeeds while doing something other than what it says: the agent runs
    without tools the caller believes it has, and the caller sees an agent
    that is inexplicably bad at its job rather than a configuration refusal.

    `Capabilities.allow_mcp_servers` publishes this before it is hit, the same
    way `credential_sources` publishes the credential specification.
    """

    def __init__(self, names: list[str]) -> None:
        super().__init__(
            "this deployment does not allow caller-supplied MCP servers "
            f"(AGENT_SERVICE_ALLOW_MCP_SERVERS=false); refused: {', '.join(names)}. "
            "GET /v1/capabilities reports allow_mcp_servers."
        )
        self.names = names


#: The permission modes THIS BUILD honours, published on `/v1/capabilities`
#: (0.19.0). **All six are the Claude Agent SDK's own enum**, which is exactly
#: why the specification carried them as a closed union until now: this build
#: was the first, so its SDK's vocabulary became everyone's, and the second
#: implementation had to map six Anthropic-shaped values onto a sandbox and an
#: approval mode. A build declares what it has now, and this build genuinely has
#: these.
#:
#: **The descriptions are the SDK's own claims plus the one measured caveat that
#: changes what they mean here**: this service runs with
#: `permission_enforcement="none"` and `Bash` enabled, so the container is the
#: enforcement boundary rather than the mode. A caller reading "bypass all
#: permission checks" should know that the checks below it were never the thing
#: standing between the agent and the filesystem.
#:
#: `auto` is in the SDK's `PermissionMode` union and is NOT in its docstring,
#: which documents the other five. Declared, with that said rather than a
#: guess written in its place. See CP-143
_MODE_TEXT: dict[str, tuple[str, str]] = {
    "default": (
        "Default",
        "Standard permission behaviour; prompts for dangerous operations. "
        "With no approval channel on /v1 a prompt cannot be answered, so in "
        "practice this denies what it would have asked about.",
    ),
    "acceptEdits": ("Accept edits", "Auto-accept file edit operations."),
    "plan": ("Plan", "Planning mode: no execution of tools."),
    "dontAsk": (
        "Do not ask",
        "Never prompt; deny anything not pre-approved.",
    ),
    "bypassPermissions": (
        "Bypass permissions",
        "Bypass all permission checks. **The container is still the boundary** "
        "-- this service runs with permission enforcement off and Bash "
        "enabled, so the checks this bypasses were not what confined the "
        "agent.",
    ),
    "auto": (
        "Auto",
        "Present in the SDK's own permission-mode union and absent from its "
        "documentation, so what it does here is the SDK's behaviour and is not "
        "described by this service.",
    ),
}


def session_modes() -> list:
    """`SessionMode` objects for `/v1/capabilities`, in declaration order."""
    from agent_spec.openapi.schemas import SessionMode

    return [
        SessionMode(id=mode, name=text[0], description=text[1])
        for mode, text in _MODE_TEXT.items()
    ]


class PermissionModeUnsupported(ValueError):
    """`options.permission_mode` names a mode this build did not declare.

    **A 400, and new in 0.19.0 because it has to be.** The field was a closed
    `Literal` in the shared models, so pydantic refused an unknown value with a
    422 before this module ran. Each build declares its own set now, so the
    field is an opaque string and the refusal belongs here -- otherwise an
    unknown mode reaches the SDK, which is the one place a wrong value becomes
    a failed turn rather than a rejected request.
    """


def check_permission_mode(mode: str | None) -> None:
    """Refuse a mode this build did not declare. Returns or raises."""
    if mode is not None and mode not in _MODE_TEXT:
        raise PermissionModeUnsupported(
            f"this build does not have a permission mode {mode!r}; it has "
            + ", ".join(_MODE_TEXT)
            + ". Read capabilities.permission_modes rather than assuming a "
            "vocabulary -- each implementation declares its own."
        )


class InvalidSessionId(ValueError):
    """A caller-supplied SDK session id the CLI would refuse.

    Rejected HERE, before a subprocess is started, because the CLI's own
    refusal is `exit 1` -- which reaches the caller as a 502 naming nothing.
    Both cases are measured (CP-071 X5, CP-072 P1).
    """


@dataclass(slots=True)
class ResolvedLimits:
    max_turns: int
    max_budget_usd: float
    timeout_s: int


def _within_cap(field: str, requested: float | None, default: float, cap: float) -> float:
    if requested is None:
        return default
    if requested > cap:
        raise LimitExceeded(field, requested, cap)
    return requested


def resolve_workspace(settings: Settings, subdir: str | None) -> Path:
    """Resolve an optional subdirectory under the workspace root.

    Input hygiene, not confinement. The mount and the container are the real
    boundary -- neither cwd nor add_dirs restricts where a tool may operate (L3).
    """
    root = settings.workspace_dir
    if not subdir:
        return root
    candidate = (root / subdir).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise InvalidWorkspacePath(f"cannot resolve {subdir!r}") from exc
    if not resolved.is_relative_to(root):
        raise InvalidWorkspacePath(f"{subdir!r} resolves outside the workspace root")
    # Path.resolve() does not raise for a target that doesn't exist, so a
    # syntactically valid, in-root, but nonexistent subdir would otherwise sail
    # through and only fail later -- opaquely -- when the SDK tries to chdir
    # into it. Fail fast here instead. Do NOT create the directory: it is
    # caller-supplied per request, and auto-creating from request input would
    # litter the workspace.
    if not resolved.is_dir():
        raise InvalidWorkspacePath(f"{subdir!r} does not exist under the workspace root")
    return resolved


def workspace_description(settings: Settings) -> str:
    """Describe the mounts to the agent.

    Mounting a directory and listing it in add_dirs does not tell the model it
    exists; without this it will not look there (Q9).
    """
    lines = [
        "Directories available to you:",
        f"- {settings.workspace_dir} - your working directory, read-write.",
    ]
    for ref in settings.reference_dirs:
        lines.append(
            f"- {ref} - read-only reference copy. You may read and search it; "
            "you cannot modify it."
        )
    return "\n".join(lines)


def _apply_description(
    system_prompt: str | dict[str, Any] | None, description: str
) -> str | dict[str, Any]:
    if system_prompt is None:
        return description
    if isinstance(system_prompt, dict):
        merged = dict(system_prompt)
        existing = merged.get("append")
        merged["append"] = f"{existing}\n\n{description}" if existing else description
        return merged
    return f"{system_prompt}\n\n{description}"


def validate_sdk_session_id(value: str, resume: str | None) -> str:
    """Check a caller-supplied SDK session id, or raise `InvalidSessionId`.

    Two rules, both measured rather than inferred:

    * **Must be a UUID.** The SDK documents it and the CLI enforces it.
    * **Never together with `resume`.** The CLI exits 1 with
      "--session-id can only be used with --continue or --resume if
      --fork-session is also specified" (X5). This service does not set
      `fork_session`: a fork is a new conversation, not a continuation.

    Nothing is lost by the second rule -- a plain resume was measured to report
    the id it resumed (X5 control), which is the value the caller already has.
    """
    if resume:
        raise InvalidSessionId(
            "session_id cannot be combined with options.resume: the CLI refuses "
            "that combination outright. Omit session_id when resuming -- the "
            "resumed conversation reports the id you passed as resume."
        )
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidSessionId(
            f"session_id must be a UUID; got {value!r}. The CLI rejects "
            "anything else and exits before this service can explain why."
        ) from exc
    return value


def build_options(
    req: RunOptions,
    settings: Settings,
    session_store: Any | None = None,
    sdk_session_id: str | None = None,
) -> tuple[ClaudeAgentOptions, ResolvedLimits]:
    limits = ResolvedLimits(
        max_turns=int(
            _within_cap("max_turns", req.max_turns, settings.default_max_turns, settings.max_allowed_turns)
        ),
        max_budget_usd=_within_cap(
            "max_budget_usd",
            req.max_budget_usd,
            settings.default_max_budget_usd,
            settings.max_allowed_budget_usd,
        ),
        timeout_s=int(
            _within_cap(
                "timeout_s", req.timeout_s, settings.default_request_timeout_s, settings.max_allowed_timeout_s
            )
        ),
    )

    allowed = list(req.allowed_tools if req.allowed_tools is not None else settings.default_allowed_tools)
    disallowed = list(req.disallowed_tools or [])
    for tool in ALWAYS_DISALLOWED_TOOLS:
        if tool not in disallowed:
            disallowed.append(tool)
    allowed = [t for t in allowed if t not in ALWAYS_DISALLOWED_TOOLS]

    setting_sources = (
        req.setting_sources if req.setting_sources is not None else settings.default_setting_sources
    )

    system_prompt: str | dict[str, Any] | None = req.system_prompt
    if settings.include_workspace_description:
        system_prompt = _apply_description(system_prompt, workspace_description(settings))

    effective_cwd = resolve_workspace(settings, req.workspace_subdir)

    # REFUSED, not silently dropped. A caller that sent MCP servers to a
    # deployment which forbids them has a working request that would do
    # something different from what it says -- the agent would run without the
    # tools the caller believes it has, and the failure would surface as the
    # agent being inexplicably unable to do its job. `allow_mcp_servers` is
    # published on /v1/capabilities so this is checkable before it is hit.
    if req.mcp_servers and not settings.allow_mcp_servers:
        raise McpServersNotAllowedError(sorted(req.mcp_servers))

    # `strict_mcp_config` defaults TRUE here, which is not the SDK's default.
    # See RunOptions.strict_mcp_config: the workspace is agent-writable, so
    # CLI-side discovery can add servers the caller never sent.
    strict_mcp = (
        req.strict_mcp_config
        if req.strict_mcp_config is not None
        else settings.default_strict_mcp_config
    )

    # permission_enforcement is opt-in and defaults to "none": the container
    # and its mount split are the only boundary unless a request-independent
    # in-process control is explicitly turned on. "can_use_tool" is not a
    # selectable value at all -- five live probes found it never fires under
    # this service's allowed_tools style (CP-066,
    # "Permission enforcement -- measured, not guessed"). Only "hook" is
    # wired here, since it is the one measured to actually block a write.
    hooks = None
    if settings.permission_enforcement == "hook":
        hooks = {
            "PreToolUse": [
                HookMatcher(
                    matcher=_WRITE_TOOL_MATCHER,
                    hooks=[make_permission_hook(settings.workspace_dir, effective_cwd)],
                )
            ]
        }

    # Before the SDK options exist: an undeclared mode is a rejected
    # request, not a failed turn. See CP-143
    check_permission_mode(req.permission_mode)
    options = ClaudeAgentOptions(
        cwd=str(effective_cwd),
        add_dirs=[str(p) for p in settings.reference_dirs],
        model=req.model or settings.default_model,
        system_prompt=system_prompt,
        allowed_tools=allowed,
        disallowed_tools=disallowed,
        permission_mode=req.permission_mode or settings.default_permission_mode,
        setting_sources=list(setting_sources),
        max_turns=limits.max_turns,
        max_budget_usd=limits.max_budget_usd,
        include_partial_messages=req.include_partial_messages,
        effort=req.effort,
        hooks=hooks,
        # A.2. `None` whenever persistence is off, which is the shipped default
        # and the value the SDK already expects to mean "no mirroring".
        #
        # `session_store_flush` is left at its "batched" default deliberately:
        # it flushes once per turn (or at 500 entries / 1 MiB), which keeps the
        # adapter's latency off the streaming hot path. "eager" would mirror in
        # near real time and is not worth the round trips for a copy nothing
        # reads live.
        session_store=session_store,
        # `{}` and not None when unset: the SDK's own default is an empty
        # dict, and passing None would be a type it does not declare.
        # `model_dump(exclude_none=True)` because the SDK's TypedDicts mark
        # `args`/`env`/`headers` NotRequired -- an explicit null is not the
        # same as absent, and the CLI receives this as JSON.
        mcp_servers={
            name: server.model_dump(exclude_none=True)
            for name, server in (req.mcp_servers or {}).items()
        },
        strict_mcp_config=strict_mcp,
        # The SDK session id to continue. Passed through untouched -- this
        # service never mints or rewrites it.
        resume=req.resume,
        # The SDK session id to USE, when the caller supplied one. Validated by
        # `validate_sdk_session_id` before we get here; `None` leaves the CLI to
        # mint its own, which is what happens for every caller that does not ask.
        session_id=sdk_session_id,
        # Bound each `load()` during resume materialization. See the Settings
        # field for why this is shorter than the SDK's own default.
        load_timeout_ms=settings.session_store_load_timeout_ms,
    )
    return options, limits
