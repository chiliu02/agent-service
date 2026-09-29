"""Live probe: what does an interrupted turn actually cost, and can the budget see it?

Answers three questions the Plan 4 live run left open (CP-090, "An
interrupted turn is billed to nobody"):

  Q1  Does an interrupted turn consume real tokens while its price stays flat?
  Q2  Is that cost DEFERRED to a later turn on the same connection, or LOST?
  Q3  Is `max_budget_usd` blind to it? (enforced inside the CLI, not by us)

Real money. Each part prints a running total taken from the SDK's own
`total_cost_usd`, which is CUMULATIVE PER CONNECTION (spike case S6) -- the LAST
value seen on a connection is that connection's total. Never summed per turn.

    uv run --env-file .env python spike/probe_interrupt_cost.py A   # Q1+Q2
    uv run --env-file .env python spike/probe_interrupt_cost.py B   # Q3
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_service.config import Settings  # noqa: E402
from agent_spec.openapi.schemas import RunOptions  # noqa: E402
from agent_service.serialization import result_fields  # noqa: E402
from agent_service.sessions import AgentSession  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".superpowers" / "sdd" / "interrupt-cost"

# Long enough to produce real output tokens before we cut it off.
LONG_PROMPT = (
    "Write a detailed 900-word essay on the history of the semicolon in "
    "programming languages, from ALGOL 60 to today. Write it out in full, "
    "in prose, with no headings and no tool use."
)
SHORT_PROMPT_1 = "Reply with exactly one word: ping"
SHORT_PROMPT_3 = "Reply with exactly one word: pong"


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def summarise(tag: str, session: AgentSession, fields: dict[str, Any]) -> dict[str, Any]:
    turn = session.last_turn
    row = {
        "tag": tag,
        "cumulative_total_cost_usd": fields.get("total_cost_usd"),
        "our_turn_cost_usd": turn.turn_cost_usd if turn else None,
        "our_interrupted": bool(turn.interrupted) if turn else None,
        "session_running_total": session.total_cost_usd,
        "subtype": fields.get("subtype"),
        "is_error": fields.get("is_error"),
        "terminal_reason": fields.get("terminal_reason"),
        "stop_reason": fields.get("stop_reason"),
        "num_turns": fields.get("num_turns"),
        "duration_ms": fields.get("duration_ms"),
        "usage": fields.get("usage"),
        "model_usage": fields.get("model_usage"),
    }
    print(json.dumps(row, indent=2, ensure_ascii=False)[:4000], flush=True)
    return row


async def plain_turn(session: AgentSession, prompt: str, tag: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    kinds: list[str] = []
    async for ev in session.send(prompt):
        kinds.append(f"{ev['type']}/{ev.get('subtype')}")
        if ev["type"] == "result":
            fields = ev.get("raw") or {}
    row = summarise(tag, session, fields)
    row["message_kinds"] = kinds
    return row


async def interrupted_turn(
    session: AgentSession, prompt: str, tag: str, delay_s: float
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    kinds: list[str] = []

    async def drain() -> None:
        nonlocal fields
        async for ev in session.send(prompt):
            kinds.append(f"{ev['type']}/{ev.get('subtype')}")
            if ev["type"] == "result":
                fields = ev.get("raw") or {}

    task = asyncio.create_task(drain())
    await asyncio.sleep(delay_s)
    issued = False
    try:
        issued = await session.interrupt()
    except Exception as exc:  # noqa: BLE001
        print(f"  interrupt() raised: {exc!r}", flush=True)
    print(f"  interrupt issued={issued} after {delay_s}s", flush=True)
    try:
        await asyncio.wait_for(task, timeout=180)
    except Exception as exc:  # noqa: BLE001
        print(f"  drain ended: {exc!r}", flush=True)
    row = summarise(tag, session, fields)
    row["message_kinds"] = kinds
    row["interrupt_issued"] = issued
    return row


def new_session(*, budget: float | None = None, raw: bool = True) -> AgentSession:
    settings = Settings()
    opts = RunOptions(include_raw=raw, max_turns=8)
    if budget is not None:
        opts = RunOptions(include_raw=raw, max_turns=8, max_budget_usd=budget)
    return AgentSession(opts, settings, title="interrupt-cost probe")


async def part_a() -> dict[str, Any]:
    """Q1 + Q2: normal -> interrupted -> normal, on ONE connection."""
    rule("PART A -- turn 1 normal, turn 2 interrupted, turn 3 normal (one connection)")
    session = new_session()
    await session.open()
    rows = []
    try:
        rows.append(await plain_turn(session, SHORT_PROMPT_1, "A1-normal"))
        rows.append(await interrupted_turn(session, LONG_PROMPT, "A2-interrupted", 8.0))
        rows.append(await plain_turn(session, SHORT_PROMPT_3, "A3-normal"))
    finally:
        await session.close()
    connection_total = session.total_cost_usd
    print(f"\nPART A connection total (last cumulative): ${connection_total:.6f}", flush=True)
    return {"part": "A", "rows": rows, "connection_total_usd": connection_total}


def _limit(session: AgentSession) -> str | None:
    out = session.last_turn.outcome if session.last_turn else None
    return out.limit_hit if out is not None else None


async def part_b(max_iters: int, budget: float, spend_ceiling: float) -> dict[str, Any]:
    """Q3: low max_budget_usd + a start-then-interrupt loop. Does the budget trip?

    Three phases on ONE connection, so the answer cannot be "the budget never
    works":
      1. one cheap NORMAL turn, which pays the ~24.5k-token cold cache write
         and lands the reported cumulative just UNDER the budget;
      2. N interrupted turns -- if the CLI's own accumulator counts interrupted
         work at all, this must push it over;
      3. one more NORMAL turn as a POSITIVE CONTROL: its reported cost alone
         takes the cumulative over the budget, so a trip here proves the
         mechanism is live on this connection and a trip in phase 2 was not
         simply impossible.
    """
    rule(f"PART B -- max_budget_usd={budget}, normal -> interrupted x{max_iters} -> normal")
    session = new_session(budget=budget)
    await session.open()
    rows = []
    tripped = None
    try:
        rows.append(await plain_turn(session, SHORT_PROMPT_1, "B0-normal-baseline"))
        rows[-1]["limit_hit"] = _limit(session)
        print(f"  baseline cumulative=${session.total_cost_usd:.6f}", flush=True)

        for i in range(1, max_iters + 1):
            row = await interrupted_turn(session, LONG_PROMPT, f"B{i}-interrupted", 8.0)
            rows.append(row)
            limit = _limit(session)
            row["limit_hit"] = limit
            print(
                f"  iter {i}: cumulative=${session.total_cost_usd:.6f} limit_hit={limit}",
                flush=True,
            )
            if limit == "budget":
                tripped = f"interrupted-{i}"
                print(f"  BUDGET TRIPPED on interrupted iteration {i}", flush=True)
                break
            if session.total_cost_usd >= spend_ceiling:
                print(f"  reported-spend ceiling ${spend_ceiling} reached; stopping", flush=True)
                break

        if tripped is None:
            rows.append(await plain_turn(session, SHORT_PROMPT_3, "B-control-normal"))
            control_limit = _limit(session)
            rows[-1]["limit_hit"] = control_limit
            print(
                f"  CONTROL normal turn: cumulative=${session.total_cost_usd:.6f} "
                f"limit_hit={control_limit}",
                flush=True,
            )
            if control_limit == "budget":
                tripped = "control-normal"
    finally:
        await session.close()
    print(f"\nPART B connection total: ${session.total_cost_usd:.6f} tripped={tripped}", flush=True)
    return {
        "part": "B",
        "max_budget_usd": budget,
        "rows": rows,
        "tripped_on": tripped,
        "connection_total_usd": session.total_cost_usd,
    }


async def part_c(n_interrupt: int, n_normal: int, budget: float) -> dict[str, Any]:
    """Q3, decisive: does the CLI's budget accumulator see interrupted work?

    Phase 1 spends REAL money the reported cumulative cannot see (N interrupted
    turns). Phase 2 then spends REPORTED money until the budget trips. If the
    budget trips in phase 2 at roughly `budget` of REPORTED spend, after phase 1
    already burned more than `budget` of unreported spend, then the CLI's
    accumulator IS the reported `total_cost_usd` -- and it is blind.

    The phase-2 trip is what makes this conclusive rather than a null result:
    without it, "the budget never fired" would be indistinguishable from
    "the budget was never approached".
    """
    rule(f"PART C -- max_budget_usd={budget}: {n_interrupt} interrupted, then normal until trip")
    session = new_session(budget=budget)
    await session.open()
    rows = []
    tripped = None
    try:
        for i in range(1, n_interrupt + 1):
            row = await interrupted_turn(session, LONG_PROMPT, f"C-int-{i}", 8.0)
            row["limit_hit"] = _limit(session)
            rows.append(row)
            print(
                f"  interrupted {i}: reported cumulative=${session.total_cost_usd:.6f} "
                f"limit_hit={row['limit_hit']}",
                flush=True,
            )
            if row["limit_hit"] == "budget":
                tripped = f"interrupted-{i}"
                break
        after_interrupts = session.total_cost_usd
        if tripped is None:
            for j in range(1, n_normal + 1):
                row = await plain_turn(session, f"{SHORT_PROMPT_3} {j}", f"C-norm-{j}")
                row["limit_hit"] = _limit(session)
                rows.append(row)
                print(
                    f"  normal {j}: reported cumulative=${session.total_cost_usd:.6f} "
                    f"limit_hit={row['limit_hit']} terminal={row['terminal_reason']} "
                    f"subtype={row['subtype']}",
                    flush=True,
                )
                if row["limit_hit"] == "budget":
                    tripped = f"normal-{j}"
                    print(f"  BUDGET TRIPPED on normal turn {j}", flush=True)
                    break
    finally:
        await session.close()
    print(
        f"\nPART C: reported after {n_interrupt} interrupted turns = ${after_interrupts:.6f}; "
        f"connection total ${session.total_cost_usd:.6f}; tripped={tripped}",
        flush=True,
    )
    return {
        "part": "C",
        "max_budget_usd": budget,
        "rows": rows,
        "reported_after_interrupts_usd": after_interrupts,
        "tripped_on": tripped,
        "connection_total_usd": session.total_cost_usd,
    }


async def main() -> None:
    which = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if which == "A":
        data = await part_a()
    elif which == "B":
        iters = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        budget = float(sys.argv[3]) if len(sys.argv) > 3 else 0.10
        ceiling = float(sys.argv[4]) if len(sys.argv) > 4 else 0.25
        data = await part_b(iters, budget, ceiling)
    elif which == "C":
        n_int = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        n_norm = int(sys.argv[3]) if len(sys.argv) > 3 else 8
        budget = float(sys.argv[4]) if len(sys.argv) > 4 else 0.05
        data = await part_c(n_int, n_norm, budget)
    else:
        raise SystemExit("usage: probe_interrupt_cost.py [A|B|C]")
    data["elapsed_s"] = round(time.time() - started, 2)
    path = OUT / f"raw-part-{which.lower()}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
