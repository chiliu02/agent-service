"""Can this SERVICE be the approver, so MCP works without self-approval?

**The question `probe_mcp.py` left open.** MCP tool calls are escalations;
`deny_all` denies them and `auto_review` lets the model approve itself. The SDK's
public `ApprovalMode` offers only those two. But `ApprovalsReviewer` has a third
value -- `user` -- documented in the generated schema as *"Override where
approval requests are routed for review on this thread and subsequent turns"*,
and `CodexClient` already takes an `approval_handler`.

Neither is reachable publicly, so this probe reaches past both to find out
whether the mechanism exists at all before any of it is built:

* `client.thread_start(params)` accepts a `ThreadStartParams` directly, so
  `approvals_reviewer=user` can be sent where `AsyncCodex.thread_start` would
  have derived it from a two-value enum.
* `codex._client._sync._approval_handler` is replaced, because
  `AsyncCodexClient.__init__` takes no handler and keeps the SDK's default --
  **which accepts every command execution and file change it is asked about.**

It prints every approval request it receives, which is the part that cannot be
read out of the SDK: the method name for an MCP tool call appears in no handler,
no registry and no test in the package.

    docker run --rm -e OPENAI_API_KEY=... -v <spike>:/spike -v <ws>:/workspace \
      --entrypoint python3 agent-service-codex-python:<tag> \
      /spike/probe_approval_handler.py

Costs one turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from openai_codex import AsyncCodex, AsyncThread, CodexConfig
from openai_codex._sandbox import _sandbox_mode
from openai_codex import Sandbox
from openai_codex.generated.v2_all import (
    ApprovalsReviewer,
    AskForApproval,
    Granular,
    GranularAskForApproval,
    ThreadStartParams,
)

SERVER = "/spike/mcp_echo_server.py"
MODEL = os.environ.get("PROBE_MODEL", "gpt-5-mini")

#: Every approval request the app-server sends us, in order. The point of the
#: probe: the method name for an MCP tool call is not written down anywhere.
SEEN: list[tuple[str, str]] = []


def approve_everything(method: str, params: dict | None) -> dict:
    """Accept, and record what was asked.

    **Deliberately permissive, because this probe is measuring the CHANNEL**, not
    a policy. The real handler denies by default; see the write-up.

    Called from the client's reader THREAD, not the event loop -- so it is a
    plain function and must never block on async work.
    """
    SEEN.append((method, json.dumps(params, default=str)))
    print(f"  APPROVAL REQUEST -> {method}")
    print(f"    {json.dumps(params, default=str)}")
    # **MCP elicitation, not a Codex approval.** The first run replied
    # `{"decision": "accept"}` -- the shape the SDK's own default handler uses
    # for `item/commandExecution/requestApproval` -- and the call was still
    # refused. `mcpServer/elicitation/request` is the MCP protocol's own
    # elicitation, whose reply is `{action, content}` with action one of
    # accept / decline / cancel.
    if method == "mcpServer/elicitation/request":
        return {"action": "accept", "content": {}}
    return {"decision": "accept"}


async def main() -> int:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")
    if not key:
        print("no credential; set OPENAI_API_KEY")
        return 2

    codex = AsyncCodex(
        CodexConfig(
            config_overrides=(
                'mcp_servers.spike.command="python3"',
                f'mcp_servers.spike.args=["{SERVER}"]',
            )
        )
    )
    await codex.login_api_key(key)
    # Force the transport up before reaching for the sync client underneath it.
    await codex._ensure_initialized()
    codex._client._sync._approval_handler = approve_everything

    params = ThreadStartParams(
        # **GRANULAR, which is the whole point.** `on-request` would ask about
        # shell commands and file changes too, and this service must not be
        # asked those -- the sandbox is the answer there and 2's fix depends on
        # nothing escalating past it. Asking about MCP elicitations ALONE is a
        # narrower policy than either public mode can express.
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
        cwd="/workspace",
        sandbox=_sandbox_mode(Sandbox.workspace_write),
        model=MODEL,
    )
    started = await codex._client.thread_start(params)
    thread = AsyncThread(codex, started.thread.id)

    turn = await thread.turn(
        "Call the spike_echo tool with the text HELLO and report its exact "
        "output. Do not answer from memory and do not use any other tool."
    )

    saw_output = False
    async for event in turn.stream():
        blob = repr(event)
        if "SPIKE-OK" in blob:
            saw_output = True

    print()
    print(f"approval requests received : {len(SEEN)}")
    for method, payload in SEEN:
        print(f"  {method}  {payload[:200]}")
    print(f"SPIKE-OK seen              : {saw_output}")
    return 0 if saw_output else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
