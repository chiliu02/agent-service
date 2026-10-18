"""The approval policy, and the guard on the SDK shape it reaches through.

No app-server, no credential, no cost: the policy is a pure decision over a
method name and a dict, which is exactly why it can be pinned this cheaply.

**What is NOT tested here is that the app-server asks us at all.** That is a fact
about the CLI, it needed a turn, and it is measured in
`spike/probe_approval_handler.py` and written up in (CX-06).
This file pins the half that a unit test can see -- and the day's lesson is that
those two halves are different: `unsupported()` was covered six ways while
nothing called it.
"""

from __future__ import annotations

import pytest

from agent_service.approvals import (
    MCP_ELICITATION,
    McpApprovalPolicy,
    SdkShapeChanged,
    assert_sdk_shape,
)


def test_the_sdk_still_has_the_shape_this_build_reaches_through() -> None:
    """**The guard, and it runs on every test run rather than at the first turn.**

    MCP support reaches past the public API in two places -- the third
    `ApprovalsReviewer` value and the handler attribute on the sync client --
    because the SDK exposes neither. A bump that moves either must fail here,
    loudly and in CI, rather than in production as an MCP call that is silently
    denied for reasons no log explains.
    """
    assert_sdk_shape()


def test_a_configured_server_is_approved() -> None:
    policy = McpApprovalPolicy(frozenset({"acme"}))

    decision = policy(MCP_ELICITATION, {"serverName": "acme", "mode": "form"})

    # MCP's own elicitation reply, NOT the `{"decision": ...}` shape the SDK's
    # default handler uses for a Codex command approval. Measured: replying with
    # the wrong one leaves the tool call refused and looks like a denial.
    assert decision["action"] == "accept"


def test_a_server_this_session_did_not_configure_is_declined() -> None:
    """The policy is *these servers*, not *MCP is on*.

    Reachable if a server is ever inherited from `CODEX_HOME`'s own
    `config.toml` rather than from the request -- the guarantee
    `strict_mcp_config` describes on the Claude build, enforced here at the
    decision instead of at the configuration.
    """
    policy = McpApprovalPolicy(frozenset({"acme"}))

    assert policy(MCP_ELICITATION, {"serverName": "somebody-else"})["action"] == "decline"


def test_a_session_that_configured_nothing_approves_nothing() -> None:
    policy = McpApprovalPolicy(frozenset())

    assert policy(MCP_ELICITATION, {"serverName": "acme"})["action"] == "decline"


@pytest.mark.parametrize(
    "method",
    [
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "something/nobody/expected",
    ],
)
def test_everything_that_is_not_an_mcp_elicitation_is_denied(method: str) -> None:
    """**Including the two the SDK's own default handler ACCEPTS.**

    `CodexClient._default_approval_handler` answers `{"decision": "accept"}` to
    both of those. This service must never: the granular policy asks only about
    MCP elicitations, so one arriving means the policy did not take, and
    accepting it would let the agent escalate out of its sandbox -- the exact
    widening (CX-06) exists to describe.
    """
    policy = McpApprovalPolicy(frozenset({"acme"}))

    assert policy(method, {"serverName": "acme"}) == {"decision": "deny"}


def test_a_missing_server_name_is_declined_rather_than_crashing() -> None:
    """The handler runs on the client's reader THREAD, where a raise hangs the
    turn rather than failing it. Malformed input must therefore be a decision,
    not an exception."""
    policy = McpApprovalPolicy(frozenset({"acme"}))

    assert policy(MCP_ELICITATION, {})["action"] == "decline"
    assert policy(MCP_ELICITATION, None)["action"] == "decline"


def test_an_exception_inside_the_policy_denies_instead_of_propagating() -> None:
    """Same reason. A policy that raises would leave the app-server waiting for
    an answer nobody is going to send."""

    class Exploding(McpApprovalPolicy):
        def _decide(self, method, params):  # noqa: ANN001, ANN202
            raise RuntimeError("boom")

    assert Exploding(frozenset())(MCP_ELICITATION, {}) == {"decision": "deny"}


def test_decisions_are_recorded_without_the_tool_parameters() -> None:
    """An operator needs to know a call was refused and which server asked.

    **Tool parameters are deliberately absent**: they are model output and may
    carry anything the conversation contained, and this service does not log
    that anywhere else either.
    """
    policy = McpApprovalPolicy(frozenset({"acme"}))
    policy(MCP_ELICITATION, {"serverName": "acme", "_meta": {"tool_params": {"secret": "x"}}})

    assert policy.decisions == [(MCP_ELICITATION, "acme", True)]
    assert "secret" not in repr(policy.decisions)


def test_the_shape_error_is_its_own_type() -> None:
    """So a caller can tell "the SDK moved" from any other RuntimeError, which is
    the difference between a bump to review and a bug to fix."""
    assert issubclass(SdkShapeChanged, RuntimeError)
