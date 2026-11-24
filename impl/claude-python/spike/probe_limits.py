"""Live spike: what does the CLI actually report when a limit trips?

Task 7 fix-round Finding 2. `runner._LIMIT_MARKERS` originally guessed four
subtype/terminal_reason strings ("error_max_turns", "max_budget",
"error_max_budget", "budget_exceeded") with zero corroboration in the
installed `claude_agent_sdk` package or in this repo's own spike history.
This script makes two REAL, minimal-cost API calls and prints the full
ResultMessage fields so the real marker strings can be read off instead of
guessed.

Probe A: max_turns=1 against a prompt that certainly needs more than one
         turn (read several files one at a time, then summarise).
Probe B: max_budget_usd=0.01 against a trivial prompt. The measured
         cold-start floor is ~$0.09 (CP-077), so this
         should trip on the very first turn.

Expected total cost: roughly $0.10. Never prints the API key.

    uv run python spike/probe_limits.py            # both probes
    uv run python spike/probe_limits.py A           # just the max_turns probe
    uv run python spike/probe_limits.py B           # just the max_budget_usd probe
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

TIMEOUT_S = 180


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def dump_result(label: str, msg: ResultMessage | None) -> None:
    print(f"\n### {label}")
    if msg is None:
        print("  NO ResultMessage was ever received (stream ended early).")
        return
    print(f"  subtype         : {msg.subtype!r}")
    print(f"  terminal_reason : {msg.terminal_reason!r}")
    print(f"  stop_reason     : {msg.stop_reason!r}")
    print(f"  is_error        : {msg.is_error!r}")
    print(f"  num_turns       : {msg.num_turns!r}")
    print(f"  total_cost_usd  : {msg.total_cost_usd!r}")
    print(f"  duration_ms     : {msg.duration_ms!r}")


async def run_probe(prompt: str, options: ClaudeAgentOptions) -> ResultMessage | None:
    result: ResultMessage | None = None
    try:
        async with asyncio.timeout(TIMEOUT_S):
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, ResultMessage):
                    result = msg
    except TimeoutError:
        print("  !! probe TIMED OUT before a ResultMessage arrived")
    except Exception as exc:  # noqa: BLE001
        print(f"  !! probe raised {type(exc).__name__}: {exc}")
    return result


async def probe_a_max_turns(tmp: Path) -> ResultMessage | None:
    rule("PROBE A -- max_turns=1, a prompt that needs several turns")
    ws = tmp / "a_ws"
    ws.mkdir()
    (ws / "one.md").write_text("# One\nFirst note: the sky is blue.\n", encoding="utf-8")
    (ws / "two.md").write_text("# Two\nSecond note: water is wet.\n", encoding="utf-8")
    (ws / "three.md").write_text("# Three\nThird note: fire is hot.\n", encoding="utf-8")

    options = ClaudeAgentOptions(
        cwd=str(ws),
        allowed_tools=["Read", "Glob"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=1,
    )
    prompt = "Read every .md file in this directory one at a time, then summarise them."
    result = await run_probe(prompt, options)
    dump_result("Probe A result (max_turns=1)", result)
    return result


async def probe_b_max_budget(tmp: Path) -> ResultMessage | None:
    rule("PROBE B -- max_budget_usd=0.01, trivial prompt")
    ws = tmp / "b_ws"
    ws.mkdir()

    options = ClaudeAgentOptions(
        cwd=str(ws),
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        max_budget_usd=0.01,
    )
    prompt = "Say the word 'ready' and nothing else."
    result = await run_probe(prompt, options)
    dump_result("Probe B result (max_budget_usd=0.01)", result)
    return result


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    # Deliberately never print the key itself, not even a prefix -- unlike
    # spike/live.py, this script's only job is limit-marker strings.
    print("API key loaded (not printed).")

    wanted = {a.upper() for a in sys.argv[1:]} or {"A", "B"}
    with tempfile.TemporaryDirectory(prefix="agentprobe_") as td:
        tmp = Path(td)
        print(f"scratch: {tmp}")
        a_result = await probe_a_max_turns(tmp) if "A" in wanted else None
        b_result = await probe_b_max_budget(tmp) if "B" in wanted else None

    rule("SUMMARY")
    if "A" in wanted:
        print(f"Probe A (max_turns)     -> subtype={a_result.subtype if a_result else None!r}, "
              f"terminal_reason={a_result.terminal_reason if a_result else None!r}")
    if "B" in wanted:
        print(f"Probe B (max_budget_usd) -> subtype={b_result.subtype if b_result else None!r}, "
              f"terminal_reason={b_result.terminal_reason if b_result else None!r}")


if __name__ == "__main__":
    asyncio.run(main())
