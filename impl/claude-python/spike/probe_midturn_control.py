"""Live probe: are set_model / set_permission_mode safe MID-TURN?

Follow-up item 10. `PATCH /v1/sessions/{sid}` takes no lock and happily
lands while a turn is draining. Offline we measured only that the HTTP
call returns 200. What nobody has measured is whether the SDK tolerates a
control request interleaved with an in-flight `receive_response()` drain,
and — the practically useful part — WHEN the change takes effect.

Driven through ClaudeSDKClient directly, not over HTTP: the question is
about the SDK, and a background drain task gives deterministic timing.

Observables that make this measurable rather than vibes-based:
  * ``AssistantMessage.model``     -> which model produced each message
  * ``ResultMessage.model_usage``  -> per-model cost breakdown for the turn
  * ``ResultMessage.permission_denials``
  * wall-clock timestamps on every message, so a control request that
    stalls or reorders the stream shows up as a gap

    uv run --env-file .env python spike/probe_midturn_control.py
    uv run --env-file .env python spike/probe_midturn_control.py P1

Never prints the API key.
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
    ToolResultBlock,
    ToolUseBlock,
)

RESULTS: list[tuple[str, str]] = []
CONNECTION_TOTALS: list[tuple[str, float | None]] = []

START_MODEL = "claude-haiku-4-5"
SWITCH_MODEL = "claude-sonnet-5"


def record(case: str, finding: str) -> None:
    RESULTS.append((case, finding))
    print(f"\n>>> {case}: {finding}\n", flush=True)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def base_options(ws: Path) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(ws),
        model=START_MODEL,
        # NOTE (measured, P1): on Windows the CLI offers a `PowerShell` tool,
        # NOT `Bash`. allowed_tools=["Bash"] under permission_mode="dontAsk"
        # therefore DENIES the shell call and the turn collapses after ~2
        # inferences. Both names are listed so the slow-count trick works.
        allowed_tools=["Bash", "PowerShell", "Read", "Glob", "Write"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=40,
        max_budget_usd=0.30,
    )


def describe(msg: Any) -> str:
    name = type(msg).__name__
    if isinstance(msg, SystemMessage):
        return f"{name}(subtype={msg.subtype!r})"
    if isinstance(msg, ResultMessage):
        return (
            f"{name}(subtype={msg.subtype!r} is_error={msg.is_error} "
            f"num_turns={msg.num_turns} stop_reason={msg.stop_reason!r} "
            f"terminal_reason={msg.terminal_reason!r} "
            f"cum_cost=${msg.total_cost_usd} "
            f"model_usage={sorted((msg.model_usage or {}).keys())} "
            f"denials={len(msg.permission_denials or [])} errors={msg.errors!r})"
        )
    bits: list[str] = []
    for b in getattr(msg, "content", None) or []:
        if isinstance(b, TextBlock):
            bits.append(f"text={b.text[:50]!r}".replace("\n", " "))
        elif isinstance(b, ToolUseBlock):
            bits.append(f"tool_use({b.name} {str(b.input)[:50]})")
        elif isinstance(b, ToolResultBlock):
            bits.append(f"tool_result(err={b.is_error} {str(b.content)[:60]})")
        else:
            bits.append(type(b).__name__)
    model = getattr(msg, "model", None)
    prefix = f"{name}[model={model}]" if model else name
    return f"{prefix}({'; '.join(bits)[:120]})"


class Drain:
    """Runs receive_response() in a background task, timestamping everything."""

    def __init__(self, client: ClaudeSDKClient) -> None:
        self.client = client
        self.rows: list[tuple[float, Any]] = []
        self.t0 = time.monotonic()
        self.done = False
        self.error: str | None = None
        self.result: ResultMessage | None = None
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.t0 = time.monotonic()
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async for msg in self.client.receive_response():
                self.rows.append((time.monotonic() - self.t0, msg))
                if isinstance(msg, ResultMessage):
                    self.result = msg
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            self.done = True

    def assistant_count(self) -> int:
        return sum(1 for _, m in self.rows if isinstance(m, AssistantMessage))

    async def wait_until_mid_turn(self, min_assistants: int, timeout: float) -> bool:
        """Block until the turn is DEMONSTRABLY still draining.

        Returns True only if we saw >= min_assistants assistant messages and
        the drain has NOT finished. A control request that lands after the
        turn already ended proves nothing, so this gate is the whole point.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.done:
                return False
            if self.assistant_count() >= min_assistants:
                return not self.done
            await asyncio.sleep(0.05)
        return False

    async def join(self, timeout: float) -> None:
        assert self.task is not None
        try:
            await asyncio.wait_for(asyncio.shield(self.task), timeout)
        except TimeoutError:
            self.rows.append((time.monotonic() - self.t0, "<TIMEOUT waiting for drain>"))
            self.task.cancel()

    def dump(self, label: str) -> None:
        print(f"  --- {label}: {len(self.rows)} messages ---")
        for t, m in self.rows:
            print(f"    t+{t:6.2f}s  {m if isinstance(m, str) else describe(m)}")


def models_seen(rows: list[tuple[float, Any]], after: float | None = None) -> list[str]:
    out = []
    for t, m in rows:
        if not isinstance(m, AssistantMessage):
            continue
        if after is not None and t < after:
            continue
        if m.model not in out:
            out.append(m.model)
    return out


# ---------------------------------------------------------------- P1
async def p1_midturn_set_model(ws: Path) -> None:
    """Fire set_model() into the middle of a draining turn."""
    rule(f"P1 — set_model({SWITCH_MODEL!r}) mid-turn (started on {START_MODEL})")
    opts = base_options(ws)

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(
            "Count from 1 to 8. Say each number in a separate message, and "
            "after each number run the bash command `sleep 2`. Do not skip any."
        )
        drain = Drain(client)
        drain.start()

        mid = await drain.wait_until_mid_turn(min_assistants=3, timeout=90)
        print(f"  genuinely mid-turn when firing control request: {mid} "
              f"(assistant msgs so far={drain.assistant_count()}, drain.done={drain.done})")

        ctl_t0 = time.monotonic() - drain.t0
        msgs_before = len(drain.rows)
        try:
            await client.set_model(SWITCH_MODEL)
            ctl_err = None
        except Exception as exc:  # noqa: BLE001
            ctl_err = f"{type(exc).__name__}: {exc}"
        ctl_t1 = time.monotonic() - drain.t0
        print(f"  set_model() fired at t+{ctl_t0:.2f}s, returned at t+{ctl_t1:.2f}s "
              f"({(ctl_t1 - ctl_t0) * 1000:.0f}ms), error={ctl_err}, "
              f"messages already drained={msgs_before}")

        await drain.join(240)
        drain.dump("turn 1")

        before_models = models_seen(drain.rows[:msgs_before])
        after_models = models_seen(drain.rows, after=ctl_t1)
        r1 = drain.result
        print(f"\n  models on AssistantMessages BEFORE control request: {before_models}")
        print(f"  models on AssistantMessages AFTER  control request: {after_models}")
        if r1 is not None and r1.model_usage:
            for name, u in r1.model_usage.items():
                print(f"  turn1 model_usage[{name}] = in={u.get('inputTokens')} "
                      f"out={u.get('outputTokens')} cost=${u.get('costUSD')}")

        # --- turn 2 on the SAME client: which model answers now?
        await client.query("Reply with only your model id, nothing else.")
        drain2 = Drain(client)
        drain2.start()
        await drain2.join(120)
        drain2.dump("turn 2")
        r2 = drain2.result
        turn2_models = models_seen(drain2.rows)
        print(f"\n  turn 2 AssistantMessage models: {turn2_models}")
        if r2 is not None and r2.model_usage:
            print(f"  turn 2 model_usage keys: {sorted(r2.model_usage)}")

        CONNECTION_TOTALS.append(
            ("P1", (r2.total_cost_usd if r2 else None) or (r1.total_cost_usd if r1 else None))
        )

    record(
        "P1",
        f"fired_mid_turn={mid}; set_model error={ctl_err!r} "
        f"(returned in {(ctl_t1 - ctl_t0) * 1000:.0f}ms); "
        f"turn1 completed={r1 is not None} is_error={getattr(r1, 'is_error', None)} "
        f"terminal_reason={getattr(r1, 'terminal_reason', None)!r} "
        f"drain_exception={drain.error!r}; "
        f"turn1 models before={before_models} after={after_models}; "
        f"turn1 model_usage={sorted((getattr(r1, 'model_usage', None) or {}))}; "
        f"turn2 models={turn2_models}",
    )


# ---------------------------------------------------------------- P2
async def p2_midturn_set_permission_mode(ws: Path) -> None:
    """Fire set_permission_mode('plan') into the middle of a draining turn.

    'plan' is the mode with the most visible effect: the CLI is supposed to
    stop executing mutating tools. If the switch takes effect on the CURRENT
    turn we should see later Write calls denied / the turn pivot; if it only
    takes effect NEXT turn, turn 1 finishes all 6 writes and turn 2 is the
    one that gets blocked.
    """
    rule("P2 — set_permission_mode('plan') mid-turn (started on 'acceptEdits')")
    opts = base_options(ws)
    opts.permission_mode = "acceptEdits"

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(
            "Do exactly this, one step at a time, one tool call per message: "
            "for i = 1,2,3,4,5,6 use the Write tool to create a file named "
            "step<i>.txt whose only content is the number i, then run a shell "
            "command that sleeps for 2 seconds. Announce each step. Do not "
            "batch the steps together and do not stop early."
        )
        drain = Drain(client)
        drain.start()

        mid = await drain.wait_until_mid_turn(min_assistants=3, timeout=90)
        files_at_switch = sorted(p.name for p in ws.glob("step*.txt"))
        print(f"  genuinely mid-turn: {mid} (assistant msgs={drain.assistant_count()}, "
              f"done={drain.done}); files on disk at switch={files_at_switch}")

        ctl_t0 = time.monotonic() - drain.t0
        msgs_before = len(drain.rows)
        try:
            await client.set_permission_mode("plan")
            ctl_err = None
        except Exception as exc:  # noqa: BLE001
            ctl_err = f"{type(exc).__name__}: {exc}"
        ctl_t1 = time.monotonic() - drain.t0
        print(f"  set_permission_mode('plan') fired t+{ctl_t0:.2f}s returned t+{ctl_t1:.2f}s "
              f"({(ctl_t1 - ctl_t0) * 1000:.0f}ms), error={ctl_err}")

        await drain.join(240)
        drain.dump("turn 1")
        r1 = drain.result
        files_after = sorted(p.name for p in ws.glob("step*.txt"))
        print(f"\n  files on disk after turn 1: {files_after}")
        print(f"  turn1 permission_denials: {(r1.permission_denials if r1 else None)!r}")

        # --- turn 2: is 'plan' in force now?
        await client.query("Use the Write tool to create after.txt containing DONE.")
        drain2 = Drain(client)
        drain2.start()
        await drain2.join(150)
        drain2.dump("turn 2")
        r2 = drain2.result
        after_exists = (ws / "after.txt").exists()
        print(f"\n  after.txt exists after turn 2: {after_exists}")
        print(f"  turn2 permission_denials: {(r2.permission_denials if r2 else None)!r}")

        CONNECTION_TOTALS.append(
            ("P2", (r2.total_cost_usd if r2 else None) or (r1.total_cost_usd if r1 else None))
        )

    record(
        "P2",
        f"fired_mid_turn={mid}; set_permission_mode error={ctl_err!r} "
        f"(returned in {(ctl_t1 - ctl_t0) * 1000:.0f}ms); "
        f"turn1 completed={r1 is not None} is_error={getattr(r1, 'is_error', None)} "
        f"terminal_reason={getattr(r1, 'terminal_reason', None)!r} "
        f"drain_exception={drain.error!r}; "
        f"files at switch={files_at_switch} -> after turn1={files_after}; "
        f"turn1 denials={len(getattr(r1, 'permission_denials', None) or [])}; "
        f"turn2 wrote after.txt={after_exists} "
        f"denials={len(getattr(r2, 'permission_denials', None) or [])}",
    )


CASES = {
    "P1": p1_midturn_set_model,
    "P2": p2_midturn_set_permission_mode,
}


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"API key loaded: {key[:8]}...{key[-4:]}")

    wanted = [a.upper() for a in sys.argv[1:]] or list(CASES)
    with tempfile.TemporaryDirectory(prefix="midturn_") as td:
        for name in wanted:
            fn = CASES.get(name)
            if fn is None:
                print(f"unknown case {name!r}")
                continue
            ws = Path(td) / name.lower()
            ws.mkdir()
            try:
                async with asyncio.timeout(600):
                    await fn(ws)
            except TimeoutError:
                record(name, "TIMED OUT after 600s")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                record(name, "RAISED — see traceback above")

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")
    print("\n  SPEND (total_cost_usd is CUMULATIVE per connection — spike S6 —")
    print("  so this takes the LAST value per connection and sums across connections):")
    total = 0.0
    for case, c in CONNECTION_TOTALS:
        print(f"    {case} connection total: ${c}")
        total += c or 0.0
    print(f"    GRAND TOTAL: ${total:.4f}")


if __name__ == "__main__":
    # NOTE: never set WindowsSelectorEventLoopPolicy — the SDK spawns a
    # subprocess and the selector loop cannot.
    asyncio.run(main())
