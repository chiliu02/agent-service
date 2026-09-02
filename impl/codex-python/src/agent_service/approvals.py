"""This service as the approver, so an MCP tool call is neither denied nor self-approved.

## Why this module exists at all

An MCP tool call is an **escalation** in Codex, and until 2026-08-09 this build
had exactly two answers to an escalation, both wrong for MCP:

| `ApprovalMode` | What it does | Why not |
|---|---|---|
| `deny_all` | app-server denies without asking | **every MCP tool call fails.** Measured: *"user rejected MCP tool call"* |
| `auto_review` | the MODEL reviews its own request | the defect (CX-04) exists to describe |

**The third answer is not in the SDK's public API.** `ApprovalsReviewer` has a
value `user` -- *"Override where approval requests are routed for review on this
thread"* -- and `CodexClient` takes an `approval_handler`. Neither is reachable:
`AsyncCodex.thread_start` derives the reviewer from the two-value enum, and
`AsyncCodexClient.__init__` takes no handler. So this module reaches past both,
and `assert_sdk_shape()` is the price of doing that.

## What is asked, and what is deliberately NOT

The policy is **granular**: `mcp_elicitations` only.

    Granular(mcp_elicitations=True, sandbox_approval=False, rules=False,
             request_permissions=False, skill_approval=False)

**Nothing else may escalate**, and that is the load-bearing half. A plain
`on-request` policy would also ask about shell commands and file changes -- and
this service answering those would put it back in the business of approving the
agent's own filesystem access, which is what the sandbox is for. The sandbox
stays the only answer there. **This narrows what can escalate; it does not widen
it.**

Measured end to end in `spike/probe_approval_handler.py`: with this policy, the
reviewer set to `user` and the handler below, the agent's MCP tool call reaches
the server and its output reaches the model.

## The default the SDK ships, which is why the handler denies

`CodexClient._default_approval_handler` **accepts** every
`item/commandExecution/requestApproval` and `item/fileChange/requestApproval` it
is asked about. A build that set `reviewer=user` and forgot to replace it would
be strictly worse than one that never asked at all -- silent blanket approval
rather than a visible denial. So the handler here answers **only** the one method
it understands, for **only** the servers the caller configured, and denies
everything else in a way an operator can find in the log.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agent_service.approvals")

#: The one request method this service answers. Not in any handler, registry or
#: test in the SDK -- read off a real approval request
#: (`spike/probe_approval_handler.py`), where it arrives with
#: `_meta.codex_approval_kind == "mcp_tool_call"`.
MCP_ELICITATION = "mcpServer/elicitation/request"

#: MCP's own elicitation reply, which is NOT the shape the SDK's default handler
#: uses. The first probe answered `{"decision": "accept"}` -- correct for a Codex
#: command approval -- and the tool call was still refused. `action` is one of
#: accept / decline / cancel.
_ACCEPT = {"action": "accept", "content": {}}
_DECLINE = {"action": "decline"}

#: For anything that is not an elicitation. Never `accept`: see the module
#: docstring on what the SDK's own default does.
_DENY = {"decision": "deny"}


class SdkShapeChanged(RuntimeError):
    """The pinned SDK no longer has the shape this module reaches into.

    **Raised at session open, not at the first turn**, which is the difference
    between a container that refuses to serve and one that serves and then
    denies every MCP call for reasons nobody can see from the outside. The same
    lesson as the `RunTimeout` import that would have been a `NameError` at the
    first real timeout (CX-11).
    """


def assert_sdk_shape() -> None:
    """Fail loudly if the SDK's private shape has moved.

    **Every name checked here is one this module or `sessions.py` reaches for**,
    and the check is deliberately about SHAPE rather than version: a bump that
    keeps these is fine, and a bump that keeps the version string while moving
    them is not -- which is the failure a version pin alone would miss.
    """
    missing: list[str] = []

    try:
        from openai_codex import AsyncCodex, AsyncThread  # noqa: F401
        from openai_codex.client import CodexClient
        from openai_codex.generated.v2_all import (
            ApprovalsReviewer,
            AskForApproval,  # noqa: F401
            Granular,
            GranularAskForApproval,  # noqa: F401
            ThreadStartParams,
        )
    except ImportError as exc:  # pragma: no cover - the whole point is the message
        raise SdkShapeChanged(
            f"the Codex SDK no longer exports what agent_service.approvals needs: {exc}. "
            "See that module's docstring; MCP support depends on it."
        ) from exc

    # The third reviewer. Without it there is no way to be asked at all.
    if not hasattr(ApprovalsReviewer, "user"):
        missing.append("ApprovalsReviewer.user")

    # The granular policy. Without it the only way to be asked about MCP is to
    # be asked about shell commands too, which this service refuses to be.
    for field in ("mcp_elicitations", "sandbox_approval"):
        if field not in Granular.model_fields:
            missing.append(f"Granular.{field}")

    # The parameters carrying both, on the call that starts a thread.
    for field in ("approval_policy", "approvals_reviewer"):
        if field not in ThreadStartParams.model_fields:
            missing.append(f"ThreadStartParams.{field}")

    # The attribute the handler is installed on. `AsyncCodexClient` wraps a
    # `CodexClient` as `_sync`, and the handler lives on that.
    if not hasattr(CodexClient, "_default_approval_handler"):
        missing.append("CodexClient._default_approval_handler")

    if missing:
        raise SdkShapeChanged(
            "the pinned Codex SDK has moved under agent_service.approvals: "
            + ", ".join(missing)
            + ". MCP support reaches past the public API on purpose -- see that "
            "module's docstring -- so a bump that moves these must be reviewed "
            "rather than absorbed."
        )


class McpApprovalPolicy:
    """Approves MCP tool calls for the servers this session configured.

    **Not a general approver.** It knows one method and one question: *is this
    elicitation from a server the caller asked for?* Everything else is denied,
    including the two methods the SDK's default handler accepts.

    **Called from the client's reader THREAD**, not the event loop, so it is a
    plain callable that must never block on async work. It also must never
    raise: an exception here happens on a thread nobody is awaiting, and the
    turn would hang rather than fail.
    """

    def __init__(self, servers: frozenset[str]) -> None:
        #: The names the caller sent in `RunOptions.mcp_servers`, which are the
        #: same names `options.py` wrote into `mcp_servers.<name>` config
        #: overrides -- so `serverName` on the request can be matched against
        #: them exactly rather than by pattern.
        self._servers = servers
        #: Bounded, and only what an operator needs to explain a refusal. Tool
        #: PARAMETERS are never recorded: they are model output and may carry
        #: anything the conversation contained.
        self.decisions: list[tuple[str, str, bool]] = []

    def __call__(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return self._decide(method, params or {})
        except Exception:  # noqa: BLE001 - a raise here hangs the turn
            logger.exception("approval handler failed; denying")
            return _DENY

    def _decide(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method != MCP_ELICITATION:
            # **Includes the two the SDK would have accepted.** The granular
            # policy means these should never arrive; one arriving means the
            # policy did not take, and accepting it would be the exact silent
            # widening this module exists to prevent.
            logger.warning(
                "denying an approval request this service does not answer: %s. "
                "The granular policy asks only about MCP elicitations, so this "
                "means the policy was not applied.",
                method,
            )
            return _DENY

        name = params.get("serverName")
        allowed = isinstance(name, str) and name in self._servers
        self.decisions.append((MCP_ELICITATION, str(name), allowed))

        if not allowed:
            # A server the caller did not configure. Reachable if a server is
            # ever inherited from CODEX_HOME's own config.toml rather than from
            # the request -- which is what `strict_mcp_config` is about on the
            # Claude build, and this is the same guarantee enforced at the
            # decision instead of at the configuration.
            logger.warning(
                "declining an MCP elicitation from %r, which this session did "
                "not configure. Configured: %s",
                name,
                sorted(self._servers) or "none",
            )
            return _DECLINE

        return _ACCEPT


# --- the two places this module leaves the public API -------------------------
#
# Both are guarded by `assert_sdk_shape()` and both are called ONLY when a
# session actually configured MCP servers. A session without them takes the
# SDK's ordinary `thread_start` and touches nothing below.


def install_approval_handler(codex: Any, handler: Any) -> None:
    """Replace the SDK's default approval handler on a started client.

    **Reach one of two.** `AsyncCodexClient.__init__` takes no `approval_handler`
    -- it constructs `CodexClient(config=config)` and keeps the default, which
    **accepts every command execution and file change it is asked about**. There
    is no public way to supply one, and leaving the default in place while asking
    to be the reviewer would be strictly worse than never asking.

    The transport must already be up: `AsyncCodex` builds its client lazily, so
    `_ensure_initialized()` or any awaited call has to have run first.
    """
    assert_sdk_shape()
    codex._client._sync._approval_handler = handler


async def start_thread_with_mcp_approvals(codex: Any, kwargs: dict[str, Any]) -> Any:
    """`thread_start`, but asking US about MCP tool calls and nothing else.

    **Reach two of two**, and the argument for it is in this module's docstring:
    `AsyncCodex.thread_start` derives `(approval_policy, approvals_reviewer)`
    from a two-value enum whose options are *deny every escalation* and *let the
    model review its own*. Neither can run an MCP tool.

    So the parameters are built directly and handed to the client's own
    `thread_start`, which accepts them -- the SDK's public method is a
    convenience over exactly this call, not a gate in front of it.

    **`kwargs` comes from `options.thread_kwargs` and its `approval_mode` is
    dropped**, deliberately: the granular policy below replaces it, and passing
    both would be two answers to one question. Sandbox, model and cwd are kept,
    which is where every other permission decision lives.
    """
    assert_sdk_shape()

    from openai_codex import AsyncThread
    from openai_codex._sandbox import _sandbox_mode
    from openai_codex.generated.v2_all import (
        ApprovalsReviewer,
        AskForApproval,
        Granular,
        GranularAskForApproval,
        ThreadStartParams,
    )

    sandbox = kwargs.get("sandbox")
    params = ThreadStartParams(
        # **Granular, and this is the load-bearing line.** A plain `on-request`
        # would also ask about shell commands and file changes, putting this
        # service in the business of approving the agent's own filesystem
        # access -- which is what the sandbox is for and what
        # (CX-06) exists to keep out. Asking about MCP
        # elicitations ALONE is narrower than either public mode.
        approval_policy=AskForApproval(
            root=GranularAskForApproval(
                granular=Granular(
                    mcp_elicitations=True,
                    sandbox_approval=False,
                    rules=False,
                    request_permissions=False,
                    skill_approval=False,
                )
            )
        ),
        approvals_reviewer=ApprovalsReviewer.user,
        base_instructions=kwargs.get("base_instructions"),
        cwd=kwargs.get("cwd"),
        model=kwargs.get("model"),
        sandbox=_sandbox_mode(sandbox) if sandbox is not None else None,
    )
    started = await codex._client.thread_start(params)
    return AsyncThread(codex, started.thread.id)
