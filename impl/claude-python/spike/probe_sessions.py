"""Live probe of ClaudeSDKClient — the multi-turn surface Plan 2 is built on.

Plan 1 was burned three times by inferring SDK behaviour instead of measuring it
(the limit markers, can_use_tool, and Starlette's BackgroundTask dispatch). This
script answers the ClaudeSDKClient questions BEFORE the plan is written.

Every case is deliberately tiny. Budget target: under $0.60 total.

    uv run --env-file .env python spike/probe_sessions.py
    uv run --env-file .env python spike/probe_sessions.py S3      # one case

Prints a summary table at the end. Never prints the API key.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

RESULTS: list[tuple[str, str]] = []


def record(case: str, finding: str) -> None:
    RESULTS.append((case, finding))
    print(f"\n>>> {case}: {finding}\n", flush=True)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def base_options(ws: Path) -> ClaudeAgentOptions:
    """Minimal options mirroring the service's own defaults."""
    return ClaudeAgentOptions(
        cwd=str(ws),
        model="claude-sonnet-5",
        allowed_tools=["Read", "Glob"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=4,
        max_budget_usd=0.50,
    )


def describe(msg: Any) -> str:
    name = type(msg).__name__
    if isinstance(msg, SystemMessage):
        return f"{name}(subtype={msg.subtype!r})"
    if isinstance(msg, ResultMessage):
        return (
            f"{name}(subtype={msg.subtype!r} is_error={msg.is_error} "
            f"num_turns={msg.num_turns} terminal_reason={msg.terminal_reason!r} "
            f"cost=${msg.total_cost_usd})"
        )
    text = ""
    for b in getattr(msg, "content", None) or []:
        if isinstance(b, TextBlock):
            text = b.text[:60].replace("\n", " ")
            break
        text = type(b).__name__
    return f"{name}({text!r})"


# ---------------------------------------------------------------- S1
async def s1_turn_boundary(ws: Path) -> None:
    """Does receive_response() terminate cleanly at the end of ONE turn,
    and can the same client then take a second turn with context intact?"""
    rule("S1 — receive_response() turn boundary + context retention")
    (ws / "fact.txt").write_text("the passphrase is ORCHID\n", encoding="utf-8")

    async with ClaudeSDKClient(options=base_options(ws)) as client:
        await client.query("Read fact.txt and reply with only the passphrase.")
        turn1 = []
        t0 = time.monotonic()
        async for msg in client.receive_response():
            turn1.append(describe(msg))
        elapsed1 = time.monotonic() - t0
        print(f"  turn 1 ({elapsed1:.1f}s), {len(turn1)} messages:")
        for m in turn1:
            print(f"    {m}")

        # Second turn on the SAME client — does it remember?
        await client.query("What was that passphrase again? Reply with only the word.")
        turn2 = []
        async for msg in client.receive_response():
            turn2.append(describe(msg))
        print(f"\n  turn 2, {len(turn2)} messages:")
        for m in turn2:
            print(f"    {m}")

    ended_on_result = turn1 and turn1[-1].startswith("ResultMessage")
    remembered = any("ORCHID" in m for m in turn2)
    record(
        "S1",
        f"receive_response ended on ResultMessage={bool(ended_on_result)}; "
        f"turn 2 recalled the passphrase without re-reading={remembered}",
    )


# ---------------------------------------------------------------- S2
async def s2_interrupt(ws: Path) -> None:
    """What does interrupt() do mid-turn, and what messages follow it?"""
    rule("S2 — interrupt() mid-turn")
    opts = base_options(ws)
    opts.allowed_tools = ["Bash", "Read", "Glob"]
    opts.max_turns = 8

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(
            "Count slowly from 1 to 40. After each number, run the bash "
            "command `sleep 1`. Do not skip any."
        )
        await asyncio.sleep(6)
        print("  sending interrupt()...")
        t0 = time.monotonic()
        try:
            await client.interrupt()
            interrupt_err = None
        except Exception as exc:  # noqa: BLE001
            interrupt_err = f"{type(exc).__name__}: {exc}"
        print(f"  interrupt() returned after {time.monotonic() - t0:.1f}s "
              f"(error: {interrupt_err})")

        after = []
        try:
            async with asyncio.timeout(60):
                async for msg in client.receive_response():
                    after.append(describe(msg))
        except TimeoutError:
            after.append("<TIMEOUT draining after interrupt>")
        print(f"  {len(after)} messages after interrupt:")
        for m in after:
            print(f"    {m}")

    tail = after[-1] if after else "<none>"
    record("S2", f"interrupt() error={interrupt_err}; drained {len(after)} msgs; last={tail}")


# ---------------------------------------------------------------- S3
async def s3_concurrent_query(ws: Path) -> None:
    """What happens on a second query() before the first turn completes?
    This decides whether the service needs a per-session lock or can rely
    on the SDK to serialise."""
    rule("S3 — second query() while a turn is still running")
    async with ClaudeSDKClient(options=base_options(ws)) as client:
        await client.query("Say the word ALPHA and nothing else.")
        # Do NOT drain. Immediately fire a second query.
        try:
            await client.query("Say the word BETA and nothing else.")
            second_err = None
        except Exception as exc:  # noqa: BLE001
            second_err = f"{type(exc).__name__}: {exc}"
        print(f"  second query() error: {second_err}")

        seen = []
        try:
            async with asyncio.timeout(90):
                async for msg in client.receive_response():
                    seen.append(describe(msg))
        except TimeoutError:
            seen.append("<TIMEOUT>")
        print(f"  {len(seen)} messages from the first receive_response():")
        for m in seen:
            print(f"    {m}")

    both = any("ALPHA" in m for m in seen), any("BETA" in m for m in seen)
    record(
        "S3",
        f"second query() raised={second_err!r}; saw ALPHA={both[0]} BETA={both[1]} "
        f"in the first drain",
    )


# ---------------------------------------------------------------- S4
async def s4_context_usage_and_setters(ws: Path) -> None:
    """Does get_context_usage() work, what shape is it, and do
    set_model()/set_permission_mode() succeed mid-session?"""
    rule("S4 — get_context_usage(), set_model(), set_permission_mode()")
    async with ClaudeSDKClient(options=base_options(ws)) as client:
        await client.query("Reply with only: OK")
        async for _ in client.receive_response():
            pass

        try:
            usage = await client.get_context_usage()
            usage_repr = repr(usage)[:400]
        except Exception as exc:  # noqa: BLE001
            usage_repr = f"RAISED {type(exc).__name__}: {exc}"
        print(f"  get_context_usage() -> {usage_repr}")

        try:
            await client.set_permission_mode("acceptEdits")
            pm = "ok"
        except Exception as exc:  # noqa: BLE001
            pm = f"RAISED {type(exc).__name__}: {exc}"
        print(f"  set_permission_mode('acceptEdits') -> {pm}")

        try:
            await client.set_model("claude-haiku-4-5")
            sm = "ok"
        except Exception as exc:  # noqa: BLE001
            sm = f"RAISED {type(exc).__name__}: {exc}"
        print(f"  set_model('claude-haiku-4-5') -> {sm}")

        try:
            info = await client.get_server_info()
            info_keys = sorted(info)[:12] if isinstance(info, dict) else repr(info)[:200]
        except Exception as exc:  # noqa: BLE001
            info_keys = f"RAISED {type(exc).__name__}: {exc}"
        print(f"  get_server_info() keys -> {info_keys}")

    record("S4", f"context_usage={usage_repr[:120]}; set_permission_mode={pm}; set_model={sm}")


# ---------------------------------------------------------------- S5
async def s5_disconnect_kills_subprocess(ws: Path) -> None:
    """Does disconnect() reliably terminate the CLI subprocess?

    Plan 1 found query() leaks a subprocess when abandoned. A session
    registry holds these open for minutes, so this is the single most
    important question for Plan 2's reaper.
    """
    rule("S5 — does disconnect() actually kill the subprocess?")
    try:
        import psutil  # type: ignore
    except ImportError:
        record("S5", "SKIPPED — psutil not installed; run `uv add --dev psutil` to measure")
        print("  psutil not available; cannot count child processes.")
        return

    me = psutil.Process(os.getpid())

    def children() -> list[int]:
        return [c.pid for c in me.children(recursive=True)]

    before = children()
    client = ClaudeSDKClient(options=base_options(ws))
    await client.connect()
    await client.query("Reply with only: HELLO")
    async for _ in client.receive_response():
        pass
    during = children()
    print(f"  children before={len(before)} during={len(during)} (new={len(during) - len(before)})")

    await client.disconnect()
    await asyncio.sleep(1.0)
    after = children()
    print(f"  children after disconnect()+1s = {len(after)}")

    leaked = [p for p in after if p not in before]
    record(
        "S5",
        f"spawned={len(during) - len(before)} child(ren); leaked after disconnect={len(leaked)}",
    )


# ---------------------------------------------------------------- S6
async def s6_cost_per_turn_or_cumulative(ws: Path) -> None:
    """Does ResultMessage.total_cost_usd report PER TURN or CUMULATIVE for
    the whole connection?

    AgentSession (Plan 2 fix round 1, Finding 2) currently sums this field
    across turns. Nothing measured whether that is correct: S1's own two
    turns hinted the assumption might be backwards (turn 2 cost about as
    much as turn 1, which is implausible for a cache-warm follow-up if the
    field were already cumulative -- but also not proof, since it could
    genuinely be two similarly-priced independent turns). Three cheap,
    short turns on ONE client, each turn's total_cost_usd plus its delta
    from the previous turn, settles it unambiguously: a per-turn field
    produces similar, independent magnitudes; a cumulative field produces a
    monotonically increasing number whose deltas shrink for a cache-warm
    follow-up.
    """
    rule("S6 — total_cost_usd: per-turn or cumulative?")
    prompts = ["Reply with only the word: ONE", "Reply with only the word: TWO", "Reply with only the word: THREE"]
    costs: list[float | None] = []

    async with ClaudeSDKClient(options=base_options(ws)) as client:
        for i, prompt in enumerate(prompts, start=1):
            await client.query(prompt)
            result = None
            async for msg in client.receive_response():
                if isinstance(msg, ResultMessage):
                    result = msg
            cost = result.total_cost_usd if result is not None else None
            costs.append(cost)
            prev = costs[-2] if len(costs) > 1 else None
            delta = (cost - prev) if (cost is not None and prev is not None) else None
            print(f"  turn {i}: total_cost_usd={cost!r}  delta_from_prev_turn={delta!r}")

    # A cumulative field is monotonically non-decreasing across turns on one
    # connection; a per-turn field has no such constraint (a later turn can
    # easily cost less than an earlier one -- shorter reply, cache hit, etc).
    numeric = [c for c in costs if c is not None]
    monotonic = len(numeric) >= 2 and all(b >= a for a, b in zip(numeric, numeric[1:]))
    record(
        "S6",
        f"turn costs={costs}; monotonically non-decreasing across all turns={monotonic} "
        "(monotonic across 3 independent short turns is the signature of a running "
        "cumulative total, not 3 coincidentally-ordered independent charges)",
    )


CASES = {
    "S1": s1_turn_boundary,
    "S2": s2_interrupt,
    "S3": s3_concurrent_query,
    "S4": s4_context_usage_and_setters,
    "S5": s5_disconnect_kills_subprocess,
    "S6": s6_cost_per_turn_or_cumulative,
}


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"API key loaded: {key[:8]}...{key[-4:]}")

    wanted = [a.upper() for a in sys.argv[1:]] or list(CASES)
    with tempfile.TemporaryDirectory(prefix="sessprobe_") as td:
        for name in wanted:
            fn = CASES.get(name)
            if fn is None:
                print(f"unknown case {name!r}")
                continue
            ws = Path(td) / name.lower()
            ws.mkdir()
            try:
                async with asyncio.timeout(300):
                    await fn(ws)
            except TimeoutError:
                record(name, "TIMED OUT after 300s")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                record(name, "RAISED — see traceback above")

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")


if __name__ == "__main__":
    # NOTE: never set WindowsSelectorEventLoopPolicy — the SDK spawns a
    # subprocess and the selector loop cannot.
    asyncio.run(main())
