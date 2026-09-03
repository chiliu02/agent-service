"""`RunOptions` -> Codex thread and turn parameters.

**Pure, like `events.py`, and for the same reason.** Nothing here starts an
app-server or spends a token, so every mapping decision below is testable
offline -- and these decisions are where a wrong guess turns into an agent with
more filesystem access than the caller asked for.

## The two vocabularies do not line up, and pretending they do is the risk

| `RunOptions` | Codex |
|---|---|
| `permission_mode` — 6 values | `sandbox` (3) **and** `approval_mode` (2), independently |
| `effort` — `low…max` | `ReasoningEffort` — `none…xhigh`, **no `max`** |
| `allowed_tools` / `disallowed_tools` | *nothing* — Codex governs by sandbox, not by tool list |
| `timeout_s` | *nothing* — **enforced by this service**, `resolve_timeout` below |
| `max_turns`, `max_budget_usd` | *nothing*, **and not enforceable here** — see below |

**Where there is no equivalent this module says so rather than approximating.**
An option silently dropped is worse than one refused: the caller believes a
limit is in force.

## The three "service-enforced" options were enforced by nothing until 2026-08-08

`SERVICE_ENFORCED` used to name all three, `unsupported()` hid all three from the
caller on the strength of that name, and **no code applied any of them** —
written up as (CX-10). One is now enforced and two are
refused, and the split is not arbitrary:

| | |
|---|---|
| **`timeout_s` — ENFORCED** | Wall-clock, and it means the same thing on every build. `sessions.send` takes one deadline at entry and a turn that outlives it is a 504 |
| **`max_budget_usd` — REFUSED, and it is unenforceable in principle** | This build has **no monetary figure at all**: `TurnOutcome.total_cost_usd` is typed `None`, because a grep for `usd` or `cost` over `openai-codex` returns one false positive. A budget cannot be enforced against a number that does not exist, and 0.16.0 made `SessionRecord.total_cost_usd` nullable for exactly this build |
| **`max_turns` — REFUSED, and this one is a judgement** | Countable proxies exist — agent messages within a turn, completed items — but none is the quantity the Claude SDK's `max_turns` bounds. **A limit whose unit differs per implementation is worse than one a caller is told it cannot have**, because the caller cannot tell. Recorded as a candidate rather than dropped: if the specification ever defines the unit, this becomes buildable |

**Both refusals are visible**: `unsupported()` returns them, `REFUSED_OPTIONS`
publishes them on `/v1/capabilities`, and `Registry.create` turns them into a
**400**. That is the rule this module opened with, and until 0.19.0 it was not
true — `unsupported()` was imported by `sessions.py`, called by nothing, and
covered by unit tests that proved the function worked while no caller ever saw
its output. A helper that returns the right answer to nobody is indistinguishable
from the silent drop it was written to prevent, and it is worth noticing that
the tests could not tell the difference either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, Sandbox

#: `RunOptions.permission_mode` -> `(sandbox, approval_mode)`.
#:
#: **The mapping is a SAFETY decision, so it is written out rather than
#: computed.** Our vocabulary came from the Claude CLI and describes *what the
#: agent may do without asking*; Codex splits the same idea into *what the
#: sandbox permits* and *whether approvals are requested at all*. Two axes, one
#: name -- so every value is stated explicitly and the defaults are conservative.
#:
#: `full_access` is deliberately UNREACHABLE from any `permission_mode`. It
#: disables the sandbox entirely, and no value in our vocabulary means that; a
#: deployment that wants it must say so in its own configuration rather than
#: have a caller reach it through a per-request field.
#:
#: **`auto_review` IS UNREACHABLE TOO, as of 2026-08-09, and it is the important
#: one.** Three modes used it and `plan` was one of them, under a comment saying
#: *"read and reason, change nothing."* **Measured, with a real turn** (probe P3
#: in (CX-04)): under `read_only` + `auto_review` the
#: agent said *"I need your approval to write to /workspace. Proceed?"*, and 300
#: milliseconds later an `item/autoApprovalReview` event with
#: `decision_source: "agent"` recorded *"Auto-review returned a low-risk allow
#: decision."* The command ran, exit 0, and `BREACH` landed on the host bind
#: mount. **`plan` was not read-only. It was read-only until the agent decided
#: otherwise.**
#:
#: The reason is structural rather than a bad default: **`auto_review` means "ask
#: for approval", and this service has nobody to ask.** There is no approval
#: channel in `/v1` -- no callback, no interactive prompt, no `can_use_tool`
#: hook -- so the only reviewer available is the model, and the model reviews its
#: own request. An approval mode with no approver is self-approval, and calling
#: it a permission mode is worse than having none.
#:
#: **So the sandbox is the only axis now, and every mode is `deny_all`.** That
#: does NOT mean "deny everything": measured in the same session (probe P4), a
#: `workspace_write` + `deny_all` session wrote inside the workspace normally and
#: was refused `/codex-home` with *"Read-only file system"*. `deny_all` refuses
#: the ESCALATION, not the work.
#:
#: The visible cost is that `acceptEdits` and `dontAsk` now resolve to the same
#: pair. They already differed only in a review nobody was performing.
_PERMISSION_MODES: dict[str, tuple[Sandbox, ApprovalMode]] = {
    # Ask before acting -- and with no approver, the honest reading is "act only
    # where a read-only sandbox already permits it".
    "default": (Sandbox.read_only, ApprovalMode.deny_all),
    # Edits are pre-approved: writes inside the workspace, and no escalation out
    # of it. Same pair as `dontAsk` below, for the reason above.
    "acceptEdits": (Sandbox.workspace_write, ApprovalMode.deny_all),
    # Read and reason, change nothing -- **and now it is true.** This is the one
    # mode whose meaning the old mapping actively contradicted.
    "plan": (Sandbox.read_only, ApprovalMode.deny_all),
    # "Do not stop to ask." NOT "escape the sandbox": the workspace stays the
    # boundary, which is what the container's mount split assumes anyway.
    "dontAsk": (Sandbox.workspace_write, ApprovalMode.deny_all),
    "auto": (Sandbox.workspace_write, ApprovalMode.deny_all),
    # The one value that names an escape. Codex's answer is still the workspace
    # sandbox -- see `full_access` above -- so this is DELIBERATELY not a
    # widening. Recorded because the name promises more than it delivers here.
    "bypassPermissions": (Sandbox.workspace_write, ApprovalMode.deny_all),
}

#: What `/v1/capabilities` publishes, and it is derived from the map above
#: rather than typed out beside it (0.19.0). **A mode this build declares and
#: cannot apply, or applies and does not declare, is the defect the whole change
#: exists to prevent** -- so the ids come from `_PERMISSION_MODES` itself and a
#: test fails if a description goes missing for one.
#:
#: **The descriptions say what happens HERE, not what the id suggests
#: elsewhere.** Every mode on this build denies escalation; only the sandbox
#: moves. That is not what these ids mean on the SDK they were taken from, and a
#: caller comparing two implementations should be able to read the difference
#: rather than infer it. (CX-49)
_MODE_TEXT: dict[str, tuple[str, str]] = {
    "default": (
        "Default",
        "Read-only sandbox, no escalation. With no approval channel this "
        "service can only act where a read-only sandbox already permits it.",
    ),
    "acceptEdits": (
        "Accept edits",
        "Writes inside the workspace, no escape from it, no escalation.",
    ),
    "plan": (
        "Plan",
        "Read and reason, change nothing. Read-only sandbox and no escalation.",
    ),
    "dontAsk": (
        "Do not ask",
        "Writes inside the workspace and never pauses. Identical to accept "
        "edits here: they differed only in a review nobody was performing.",
    ),
    "auto": (
        "Auto",
        "Writes inside the workspace, no escalation. Same pair as do-not-ask.",
    ),
    "bypassPermissions": (
        "Bypass permissions",
        "**Not a widening on this build.** The workspace sandbox still "
        "applies; Codex's own full-access mode is deliberately unreachable "
        "from any permission mode, so this promises more than it delivers "
        "here and is declared so a caller is not surprised.",
    ),
}


def session_modes() -> list[Any]:
    """`SessionMode` objects for `/v1/capabilities`, in the map's own order."""
    from agent_spec.openapi.schemas import SessionMode

    return [
        SessionMode(id=mode, name=_MODE_TEXT[mode][0], description=_MODE_TEXT[mode][1])
        for mode in _PERMISSION_MODES
    ]


class PermissionModeUnsupported(ValueError):
    """`options.permission_mode` names a mode this build did not declare.

    **A 400, and it is new in 0.19.0 because it has to be.** The field was a
    closed `Literal` in the shared models, so pydantic refused an unknown value
    with a 422 before any of this code ran. Now that each build declares its own
    set the field is an opaque string, and the refusal is this build's job --
    without it, `_PERMISSION_MODES[mode]` is a `KeyError` and the caller gets a
    500 for a request that is merely wrong.

    The message names the modes this build has, because the caller's remedy is
    to pick one of them and `/v1/capabilities` is the only other place to look.
    """

#: `RunOptions.effort` -> Codex `ReasoningEffort`, as a plain string because the
#: SDK takes the literal.
#:
#: **`max` has no equivalent and maps to `xhigh`, the highest Codex offers.**
#: That is a widening of nothing and a narrowing of one step; the alternative --
#: refusing the request -- would fail a caller for asking for more effort than
#: this SDK can express, which helps nobody.
_EFFORT: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}

#: What `/v1/capabilities.effort_levels` publishes: the levels this build
#: delivers **exactly**, which is the identity half of the table above.
#:
#: **`max` is deliberately absent, and the request for it is still honoured**
#: (CX-51). Publishing the whole vocabulary said `max` was available and then
#: quietly gave `xhigh`, so a client optimising for the most reasoning it could
#: get was told yes and handed something else -- the narrowing is right, its
#: invisibility was not. Dropping it from the published list is what makes the
#: two agree without failing a caller for asking.
#:
#: **Derived from the mapping rather than typed out beside it**, so a level that
#: starts or stops being honoured exactly cannot disagree with what is
#: advertised -- the drift AS-32 exists to prevent.
HONOURED_EFFORT_LEVELS: tuple[str, ...] = tuple(
    level for level, mapped in _EFFORT.items() if level == mapped
)

#: Options this service enforces itself because the SDK has no equivalent. Named
#: so that `unsupported()` can report them rather than leaving a caller to
#: discover that a limit was never applied.
#:
#: **One name, and it used to be three.** Membership here is a claim that
#: something applies the option, and it went unchecked for two of the three --
#: (CX-10). `test_options.py` now pins the claim against
#: what the code actually does.
SERVICE_ENFORCED = ("timeout_s",)

#: Options with no Codex equivalent AND no service-side enforcement. A caller
#: setting one is asking for something this build cannot do.
#:
#: `max_budget_usd` and `max_turns` joined 2026-08-08, from `SERVICE_ENFORCED`
#: above: the first is unenforceable in principle here (no cost figure exists in
#: the SDK) and the second has no agreed unit. The module docstring has both
#: arguments. **This is a widening of what the caller is told, not of what the
#: build does** -- nothing enforced them before either.
NOT_SUPPORTED = (
    "allowed_tools",
    "disallowed_tools",
    "max_turns",
    "max_budget_usd",
)

#: What `/v1/capabilities.unsupported_options` publishes -- the standing list, as
#: against `unsupported()`'s per-request answer.
#:
#: **`strict_mcp_config` is deliberately ABSENT**, and the line is worth stating
#: because it is the one place this module does not refuse a field it cannot act
#: on. That option only governs whether CLI-side discovery may ADD to the servers
#: a caller sent; `mcp_servers` is refused outright here, so there is no set to be
#: strict about and no behaviour a correct client could branch on. AS-32 governs
#: differences a client must act on, not every field whose value is inert.
#: **Structured since 2026-08-09, and it was Agent Studio who caught why.** This
#: was a tuple of strings ending in `"system_prompt (preset form)"`, and six of
#: the seven entries were identifiers while the seventh was a sentence -- so
#: `if (unsupported_options.contains(fieldName))`, the obvious client, never
#: matched `system_prompt`. **A difference published in a form nobody can branch
#: on is the failure AS-32 exists to prevent**, so the prose became a `types`
#: list: absent means the whole field, present means only those JSON types.
#:
#: `system_prompt` is the only conditional one and it must stay conditional --
#: the string form maps to `base_instructions` and works. Publishing the whole
#: field as refused would cost a caller a feature this build has.
REFUSED_OPTIONS = (
    *({"field": name} for name in NOT_SUPPORTED),
    {"field": "system_prompt", "types": ["object"]},
)


class UnsupportedOptions(ValueError):
    """The request set options this build cannot honour. A 400, per `errors.py`.

    **Refused rather than dropped**, which is the Claude build's rule for
    `mcp_servers` and this build's own rule for a supplied `sdk_session_id`: the
    route is implemented, one or more fields cannot be, and the caller's remedy
    is to omit them. A request that succeeded while ignoring them would run an
    agent without the tools or the budget the caller believes it has, and would
    surface as an agent inexplicably bad at its job rather than as a refusal.

    `deployment.accepts.unsupported_options` publishes the same names before a caller
    hits this, the same way `allow_mcp_servers` and `allow_supplied_sdk_session_id`
    publish theirs.
    """

    def __init__(self, names: list[str]) -> None:
        super().__init__(
            "this implementation cannot honour: "
            + ", ".join(names)
            + ". Omit them, or read `unsupported_options` from GET /v1/capabilities "
            "before sending them."
        )
        self.names = names


class LimitExceeded(ValueError):
    """A requested limit is above this deployment's cap. A 400, per `errors.py`."""

    def __init__(self, field: str, requested: float, cap: float) -> None:
        super().__init__(
            f"{field}={requested:g} exceeds this deployment's cap of {cap:g}. "
            f"Read `limits.max_allowed_timeout_s` from GET /v1/capabilities."
        )


class InvalidWorkspacePath(ValueError):
    """`working_directory` does not name a directory under the root. A 400."""


def resolve_workspace(settings: Any, subdir: str | None) -> Path:
    """The thread's working directory: the root, or a subdirectory of it.

    **Input hygiene, not confinement** -- the sandbox and the mount are the
    boundary, and a working directory restricts nothing a tool may reach. What
    this stops is a request quietly starting the agent somewhere nobody asked
    for: until 2026-09-03 this build concatenated the caller's string onto the
    root with no checks at all, so `../..` walked out of the workspace and a
    missing directory failed later, opaquely, inside the agent (CX-64).

    **It also decides which `AGENTS.md` the thread reads** (CX-14), so an
    unchecked value moves the agent's ambient configuration as well as its cwd.

    **The directory is never created.** It is caller-supplied per request, and
    creating one from request input would litter the caller's mounted workspace.
    """
    root = Path(settings.workspace_dir)
    if not subdir:
        return root
    try:
        resolved = (root / subdir).expanduser().resolve()
    except OSError as exc:
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} cannot be resolved."
        ) from exc
    if not resolved.is_relative_to(root.resolve()):
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} resolves outside the workspace root. "
            "It is a path RELATIVE to `capabilities.workspace_dir` and must stay "
            "under it."
        )
    if not resolved.is_dir():
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} does not exist under the workspace "
            "root. This service does not create it: mount or make the directory "
            "before starting a session there."
        )
    return resolved


def resolve_timeout(requested: float | None, settings: Any) -> float:
    """The turn deadline in seconds: what was asked for, or the default, capped.

    **Refuses rather than clamps**, which is the Claude build's behaviour and the
    right one: silently shortening a caller's deadline produces a 504 they cannot
    explain, where a 400 names the cap and the field.
    """
    if requested is None:
        return float(settings.default_request_timeout_s)
    if requested > settings.max_allowed_timeout_s:
        raise LimitExceeded("timeout_s", requested, settings.max_allowed_timeout_s)
    return float(requested)


def thread_kwargs(options: Any, *, cwd: str | None = None) -> dict[str, Any]:
    """Parameters for `thread_start` / `thread_resume`.

    Only what is set is returned: the SDK's own defaults are better than any
    this module could invent, and passing `None` explicitly is not the same as
    not passing it.
    """
    kwargs: dict[str, Any] = {}
    if cwd is not None:
        kwargs["cwd"] = cwd

    mode = getattr(options, "permission_mode", None)
    if mode is not None:
        if mode not in _PERMISSION_MODES:
            raise PermissionModeUnsupported(
                f"this build does not have a permission mode {mode!r}; it has "
                + ", ".join(_PERMISSION_MODES)
                + ". Read capabilities.permission_modes rather than assuming a "
                "vocabulary -- each implementation declares its own."
            )
        sandbox, approval = _PERMISSION_MODES[mode]
        kwargs["sandbox"] = sandbox
        kwargs["approval_mode"] = approval

    model = getattr(options, "model", None)
    if model:
        kwargs["model"] = model

    prompt = getattr(options, "system_prompt", None)
    if isinstance(prompt, str) and prompt:
        # `base_instructions`, not `developer_instructions`: ours replaces the
        # agent's own framing, which is what `base_` means here. A dict-shaped
        # system_prompt is a Claude preset and has no Codex equivalent -- it is
        # ignored rather than stringified, and reported by `unsupported()`.
        kwargs["base_instructions"] = prompt

    return kwargs


def turn_kwargs(options: Any) -> dict[str, Any]:
    """Parameters for `thread.turn`, which may override the thread's own."""
    kwargs: dict[str, Any] = {}

    effort = getattr(options, "effort", None)
    if effort is not None:
        kwargs["effort"] = _EFFORT[effort]

    model = getattr(options, "model", None)
    if model:
        kwargs["model"] = model

    return kwargs


def unsupported(options: Any) -> list[str]:
    """Which set options this build cannot honour through the SDK.

    **The caller is meant to be told**, and since 0.19.0 they are: a non-empty
    return is an `UnsupportedOptions` 400 raised by `Registry.create`, before the
    session cap is touched and before any subprocess starts. `SERVICE_ENFORCED`
    names are absent because the service applies them itself; everything here is
    a field the caller set and nothing will act on.

    **Truthiness, not `is not None`, and that is right for every member.** An
    empty `mcp_servers: {}` or `allowed_tools: []` asks for nothing, so there is
    nothing to refuse; `max_turns: 0` is not a limit either. A caller sending an
    empty container gets a working request rather than a lecture.
    """
    missing = [name for name in NOT_SUPPORTED if getattr(options, name, None)]
    if isinstance(getattr(options, "system_prompt", None), dict):
        # **The field name, not a sentence.** It used to append
        # `"system_prompt (preset form)"`, which read the same in a log and was
        # unusable in the published list -- see `REFUSED_OPTIONS`. The condition
        # is the object form; the name is the field, and the error message is
        # where the nuance belongs.
        missing.append("system_prompt")
    return missing


# --- MCP: `RunOptions.mcp_servers` -> `--config mcp_servers.<name>.*` ---------
#
# **Codex has no MCP API in its Python SDK at all** -- a grep for `mcp` over the
# installed package returns nothing. What it has is the CLI's configuration,
# reachable through `CodexConfig.config_overrides`, which the client turns into
# `--config key=value` before `app-server`. Measured end to end in
# `spike/probe_mcp.py`: the app-server loads the servers, launches them inside
# the container under bubblewrap, and the tool reaches the model.
#
# The TOML shape was captured by running `codex mcp add` against a scratch
# `CODEX_HOME` and reading what it wrote, rather than guessed:
#
#     [mcp_servers.acme]
#     command = "npx"
#     args = ["-y", "@acme/mcp"]
#     [mcp_servers.acme.env]
#     A = "b"
#
#     [mcp_servers.remote]
#     url = "https://mcp.example.com/mcp"
#     bearer_token_env_var = "MCP_TOKEN"

#: Transports this build can express, published as `Capabilities.mcp.transports`.
#:
#: **`sse` is absent because Codex has no SSE MCP transport** -- `codex mcp add
#: --url` is streamable HTTP and there is no second URL form. A caller sending
#: one is refused rather than quietly given an HTTP client pointed at an SSE
#: endpoint, which would fail later and further away.
MCP_TRANSPORTS = ("stdio", "http")

#: What an `http` server's `headers` may contain here.
#:
#: **Codex takes a bearer token and nothing else**, and it takes it as the NAME
#: of an environment variable rather than a value. So exactly one header is
#: expressible -- `Authorization: Bearer <token>` -- and any other is refused.
MCP_HTTP_HEADERS = "bearer_only"

#: Matched case-insensitively: the scheme token is case-insensitive per RFC 7235
#: and a caller writing `bearer ` is not making a mistake worth a 400.
_BEARER = "bearer "


class McpUnsupported(ValueError):
    """An MCP server this build cannot express. A 400, per `errors.py`.

    **Separate from `UnsupportedOptions` because the FIELD is supported** -- it
    is this particular server's transport or authentication that is not, and a
    caller fixes it by changing the server rather than by dropping the field.
    `unsupported_options` therefore does not name `mcp_servers`, and
    `capabilities.mcp` is where the narrower limits are published.
    """


def _toml(value: Any) -> str:
    """A TOML scalar / array / inline table for a `--config key=value` override.

    **Minimal on purpose.** The values here are strings, string lists and string
    maps -- the whole of what an MCP server configuration is -- so this is not a
    TOML writer and must not grow into one. Anything else raises rather than
    guessing: a silently mis-encoded override is a server that does not start,
    for reasons the log attributes to the CLI.
    """
    import json

    if isinstance(value, str):
        # JSON string escaping is TOML basic-string escaping for the characters
        # that can appear here, and both use double quotes.
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} = {_toml(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"no TOML encoding for {type(value).__name__}")


def _field(server: Any, name: str) -> Any:
    """Read a field off a pydantic model or the dict form, indifferently."""
    if isinstance(server, dict):
        return server.get(name)
    return getattr(server, name, None)


def _bearer_token(headers: dict[str, str] | None) -> str | None:
    """The bearer token from `headers`, or `None` when there is nothing to send.

    Raises `McpUnsupported` for anything Codex cannot carry, which is every
    header except a single `Authorization: Bearer ...`.
    """
    if not headers:
        return None
    extra = sorted(key for key in headers if key.lower() != "authorization")
    if extra:
        raise McpUnsupported(
            f"this implementation cannot send {', '.join(extra)} to an MCP "
            "server: Codex carries a bearer token and no other header. Read "
            "`mcp.http_headers` from GET /v1/capabilities."
        )
    value = next(iter(headers.values()))
    if not value.lower().startswith(_BEARER):
        raise McpUnsupported(
            "this implementation can only send an `Authorization: Bearer ...` "
            "header to an MCP server; Codex has no way to send any other "
            "authorization scheme."
        )
    return value[len(_BEARER) :].strip()


def mcp_overrides(servers: Any) -> tuple[tuple[str, ...], dict[str, str]]:
    """`(config overrides, environment)` for the MCP servers a caller asked for.

    Returns the `--config` arguments **and** the environment the app-server must
    start with, because an HTTP server's token travels as `bearer_token_env_var`
    -- a variable NAME in the configuration and the value in the process
    environment.

    **That is better than it looks and worse than it sounds.** Better: the token
    never enters the process table. Worse: it is still readable by the agent,
    which runs as the same user and can read its own environment. **What this
    buys is audience, not secrecy** (CX-09).
    """
    overrides: list[str] = []
    env: dict[str, str] = {}

    for name, server in (servers or {}).items():
        kind = _field(server, "type")

        if kind == "stdio":
            overrides.append(f"mcp_servers.{name}.command={_toml(_field(server, 'command'))}")
            if _field(server, "args"):
                overrides.append(
                    f"mcp_servers.{name}.args={_toml(list(_field(server, 'args')))}"
                )
            if _field(server, "env"):
                overrides.append(
                    f"mcp_servers.{name}.env={_toml(dict(_field(server, 'env')))}"
                )
        elif kind == "http":
            overrides.append(f"mcp_servers.{name}.url={_toml(_field(server, 'url'))}")
            token = _bearer_token(_field(server, "headers"))
            if token is not None:
                # One variable per server, named after it, so two servers cannot
                # collide on one token.
                var = f"AGENT_SERVICE_MCP_TOKEN_{name.upper()}"
                overrides.append(f"mcp_servers.{name}.bearer_token_env_var={_toml(var)}")
                env[var] = token
        else:
            raise McpUnsupported(
                f"this implementation cannot reach an MCP server over {kind!r}: "
                f"Codex supports {' and '.join(MCP_TRANSPORTS)} only. Read "
                "`mcp.transports` from GET /v1/capabilities."
            )

    return tuple(overrides), env


class McpServersNotAllowed(ValueError):
    """The request sent `mcp_servers` to a deployment that forbids them.

    **The Claude build's error, by the same name and for the same reason.** A
    400 rather than a silent drop: dropping them leaves a request that succeeds
    while doing something other than what it says, and the caller sees an agent
    that is inexplicably bad at its job rather than a configuration refusal.

    Distinct from `McpUnsupported`, which is about a server this BUILD cannot
    express. This one is a deployment saying no to all of them, and
    `deployment.config.allow_mcp_servers` publishes it before it is hit.
    """

    def __init__(self, names: list[str]) -> None:
        super().__init__(
            "this deployment does not allow caller-supplied MCP servers "
            f"(AGENT_SERVICE_ALLOW_MCP_SERVERS=false); refused: {', '.join(names)}. "
            "GET /v1/capabilities reports allow_mcp_servers."
        )
        self.names = names


# --- `setting_sources`: Codex has a project doc, and it can be switched off ---

#: The `SettingSource` members this build can honour, published as
#: `deployment.accepts.setting_sources`.
#:
#: **Measured 2026-08-09** (`spike/probe_project_doc.py`), because Agent Studio
#: asked the question directly: *does the Codex build have a notion of
#: project-level configuration that a session can be pointed at?* It does --
#: Codex reads `AGENTS.md` from the thread's `cwd`, a token planted there reached
#: the model by default, and `project_doc_max_bytes=0` suppressed it.
#:
#: | Source | Here |
#: |---|---|
#: | `user` | **always on and not selectable.** `CODEX_HOME`'s own configuration is read whatever a caller says, so listing it is honest and omitting it would be a promise this build cannot keep either way |
#: | `project` | **selectable**, and that is the bit that matters: present means the project doc is read, absent means `project_doc_max_bytes=0` |
#: | `local` | **no equivalent.** Codex has no third, machine-local layer |
#:
#: `user` being unconditional deserves the caveat rather than a refusal: a caller
#: that omits it gets it anyway, and no configuration of this build changes that.
SUPPORTED_SETTING_SOURCES = ("user", "project")


class SettingSourceUnsupported(ValueError):
    """A `setting_sources` member this build has no equivalent for. A 400.

    Refused by VALUE rather than by field, which is why `unsupported_options`
    does not name `setting_sources`: the field is honoured, and it is `local`
    that is not. `deployment.accepts.setting_sources` publishes the vocabulary, so a
    caller reads which members exist before sending one.
    """


def setting_source_overrides(options: Any) -> tuple[str, ...]:
    """`-c` overrides implementing `RunOptions.setting_sources`.

    **Absent means the deployment's default**, which is Codex's own: the project
    doc IS read. That matches the field's own description -- omitted falls back
    to server configuration -- and it means a caller who never heard of the
    field gets the runtime's ordinary behaviour rather than a silently
    stripped-down agent.

    **An explicit list without `project` switches the project doc off.** That is
    the distinction Studio's two agent modes turn on, and the only one this
    build can express.
    """
    sources = getattr(options, "setting_sources", None)
    if sources is None:
        return ()

    unsupported_members = sorted(
        set(sources) - set(SUPPORTED_SETTING_SOURCES)
    )
    if unsupported_members:
        raise SettingSourceUnsupported(
            f"this implementation has no equivalent for setting_sources "
            f"{', '.join(unsupported_members)}: Codex has "
            f"{' and '.join(SUPPORTED_SETTING_SOURCES)} configuration and no "
            "third machine-local layer. Read `setting_sources` from "
            "GET /v1/capabilities for the members it honours."
        )

    if "project" in sources:
        # The runtime default. Stated by saying nothing, because a positive
        # override would pin a byte budget this service has no opinion about.
        return ()
    return ('project_doc_max_bytes=0',)
