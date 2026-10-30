"""Live probe: the two unknowns left on the caller-supplied-session-id feature.

P1  What does the CLI do when a supplied `--session-id` ALREADY has a transcript
    in that working directory? This is the failure mode of a client bug (an id
    reused across sessions), and a service that accepts caller-supplied ids owes
    an answer on it.
P2  Under `include_partial_messages`, is the first message of a turn still the
    init that carries `session_id`? Decides whether `x-sdk-session-id` can be
    absent on a first streaming turn that DID produce messages.

Two turns for P1, one for P2. `claude-haiku-4-5`, one-word prompts.

    uv run --env-file .env python spike/probe_supplied_id.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)

RESULTS: list[tuple[str, str]] = []
MODEL = "claude-haiku-4-5"


def record(case: str, finding: str) -> None:
    RESULTS.append((case, finding))
    print(f"\n>>> {case}: {finding}\n", flush=True)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def base_options(ws: Path, **extra: Any) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(ws),
        model=MODEL,
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=2,
        max_budget_usd=0.25,
        **extra,
    )


async def p1_reused_id(ws: Path) -> None:
    """Same id, same cwd, a second connection. Error, fresh, or resumed?"""
    rule("P1 -- a supplied session id that already has a transcript")
    sid = str(uuid.uuid4())
    print(f"  session id: {sid}")

    async with ClaudeSDKClient(options=base_options(ws, session_id=sid)) as client:
        await client.query("Remember this word: ORCHID. Reply with only: OK")
        first_ids = []
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                first_ids.append((msg.data or {}).get("session_id"))
    print(f"  turn 1 ok, init id(s)={first_ids}")

    # A NEW connection, same cwd, the SAME id.
    text = ""
    err = None
    second_id = None
    try:
        async with ClaudeSDKClient(options=base_options(ws, session_id=sid)) as client:
            await client.query("What word did I ask you to remember? One word only.")
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and second_id is None:
                    second_id = (msg.data or {}).get("session_id")
                if isinstance(msg, ResultMessage):
                    text = msg.result or ""
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"

    remembered = "ORCHID" in text.upper()
    print(f"  turn 2: error={err} init_id={second_id} result={text[:80]!r}")
    record(
        "P1",
        f"reusing a supplied id in the same cwd: error={err}; "
        f"id reported={second_id}; conversation history carried over={remembered} "
        f"({'RESUMED the old transcript' if remembered else 'started FRESH' if not err else 'REJECTED'})",
    )


async def p2_partial_messages(ws: Path) -> None:
    """With partial messages on, what is the first message, and does it carry
    a session id?"""
    rule("P2 -- include_partial_messages: is the first message still the init?")
    seen: list[tuple[str, Any]] = []
    async with ClaudeSDKClient(
        options=base_options(ws, include_partial_messages=True)
    ) as client:
        await client.query("Reply with only: OK")
        async for msg in client.receive_response():
            sid = None
            if isinstance(msg, SystemMessage):
                sid = (msg.data or {}).get("session_id")
            else:
                sid = getattr(msg, "session_id", None)
            if len(seen) < 5:
                seen.append((type(msg).__name__, sid))
            if isinstance(msg, ResultMessage):
                break
    for i, (kind, sid) in enumerate(seen, start=1):
        print(f"    [{i}] {kind:<20} session_id={sid}")
    first_kind, first_sid = seen[0] if seen else ("(none)", None)
    record(
        "P2",
        f"first message={first_kind} carrying session_id={first_sid!r}; "
        f"first-is-SystemMessage={first_kind == 'SystemMessage'}",
    )


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    print(f"model={MODEL}")
    with tempfile.TemporaryDirectory(prefix="supid_") as td:
        root = Path(td)
        for name, fn in (("P1", p1_reused_id), ("P2", p2_partial_messages)):
            ws = root / name.lower()
            ws.mkdir()
            try:
                async with asyncio.timeout(300):
                    await fn(ws)
            except TimeoutError:
                record(name, "TIMED OUT")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                record(name, "RAISED -- see traceback")

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")


if __name__ == "__main__":
    asyncio.run(main())
