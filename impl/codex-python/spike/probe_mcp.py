"""Does a `mcp_servers.*` config override give the agent a callable tool?

**The question this answers, and why reading could not.** `CodexConfig` has
`config_overrides`, the CLI turns each into `--config key=value`, and
`codex mcp list` reflects them -- all three verified free. None of that proves
the **app-server** loads them, that the server is launched inside the container,
or that the tool reaches the model. That needs a turn.

    docker run --rm -e OPENAI_API_KEY=... \
      -v <spike dir>:/spike -v <workspace>:/workspace \
      --cap-drop ALL --security-opt no-new-privileges:true \
      --security-opt seccomp=unconfined \
      --entrypoint python3 agent-service-codex-python:<tag> /spike/probe_mcp.py

**Costs one turn.** The prompt is one sentence and the model is the cheapest
that answers.

The evidence is `SPIKE-OK:`, which `mcp_echo_server.py` prefixes onto whatever it
is given. A model told to echo something can produce the echo on its own; it
cannot produce that prefix without the tool's output.
"""

from __future__ import annotations

import asyncio
import os
import sys

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

SERVER = "/spike/mcp_echo_server.py"
MODEL = os.environ.get("PROBE_MODEL", "gpt-5-mini")


async def main() -> int:
    config = CodexConfig(
        # Exactly the shape `options.py` would build. Written out here rather
        # than imported so the probe measures the CLI's contract, not this
        # service's opinion of it.
        config_overrides=(
            'mcp_servers.spike.command="python3"',
            f'mcp_servers.spike.args=["{SERVER}"]',
            'mcp_servers.spike.env={PROBE="1"}',
            # **The whole question, second run.** Under `deny_all` the first
            # run's tool call came back "user rejected MCP tool call": MCP
            # calls are an escalation, and `deny_all` denies escalations. This
            # asks whether a per-app approval mode PRE-approves them, so the
            # call never becomes an escalation at all -- which is the only
            # route to working MCP that needs neither self-approval nor a
            # private SDK attribute.
            #
            # `apps.<name>` is typed (a string there is rejected as "expected
            # struct AppConfig") and `mcp_servers.<name>.default_tools_approval_mode`
            # is rejected outright, so this is the shape the CLI recognises.
            *(
                ()
                if os.environ.get("PROBE_NO_PREAPPROVE")
                else ('apps.spike.default_tools_approval_mode="auto"',)
            ),
        ),
    )
    codex = AsyncCodex(config)
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")
    if not key:
        print("no credential; set OPENAI_API_KEY")
        return 2
    await codex.login_api_key(key)

    thread = await codex.thread_start(
        cwd="/workspace",
        # workspace_write + deny_all: the measured pair that confines to the
        # workspace without letting the agent approve its own escalation.
        sandbox=Sandbox.workspace_write,
        # deny_all, deliberately -- the mode this service ships. If MCP
        # needs auto_review it does not work here at all.
        approval_mode=ApprovalMode.deny_all,
        model=MODEL,
    )

    turn = await thread.turn(
        "Call the spike_echo tool with the text HELLO and report its exact "
        "output. Do not answer from memory and do not use any other tool."
    )

    saw_tool_call = False
    text: list[str] = []
    # `.stream()`, not `async for turn:` -- the handle is not itself an
    # async iterable, which is what `sessions.py` already knew and this
    # probe had to learn.
    async for event in turn.stream():
        name = getattr(event, "method", type(event).__name__)
        blob = repr(event)
        if "spike_echo" in blob:
            saw_tool_call = True
        if "SPIKE-OK" in blob:
            text.append(blob)
        print(f"  {name}: {blob[:160]}")

    print()
    print(f"tool named in the stream : {saw_tool_call}")
    print(f"SPIKE-OK seen            : {bool(text)}")
    return 0 if (saw_tool_call and text) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
