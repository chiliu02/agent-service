"""The only module that writes A.1 rows.

`writer.py` owns the queue and the drain task; this owns the SQL. Splitting them
keeps the drop policy testable without a database and the statements testable
without a queue.

## Order within a batch is preserved, deliberately

`events.run_id` references `runs.id`, so a run row must land before its events.
Items are therefore applied **in queue order**, with only *consecutive* runs of
`EventAppended` coalesced into one bulk insert. Sorting the batch by type would
be faster and would produce foreign-key violations the first time a run started
and finished inside a single flush window.

## Every ResultMessage field the outcome carries is stored

`runs.duration_api_ms`, `runs.errors` and `runs.api_error_status` were NULL until
`RunOutcome` was widened to carry them (plan-03, after Task 4). They are
deliberately NOT on `RunResponse`: the wire format is fixed by plan-03's global
constraints, and these are diagnostic detail a stored row wants more than a
streaming caller does.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_spec.db.models import Event, Run, Session
from agent_spec.db.items import (
    EventAppended,
    Item,
    RunFinished,
    RunStarted,
    SessionClosed,
    SessionOpened,
)


def _at(epoch: float) -> datetime:
    """Epoch float -> aware datetime.

    Aware, because every timestamp column is TIMESTAMPTZ. Handing asyncpg a
    naive datetime for one of those is how a deployment ends up with timestamps
    silently shifted by the server's local offset.
    """
    return datetime.fromtimestamp(epoch, tz=UTC)


async def apply(session: AsyncSession, items: Sequence[Item]) -> None:
    """Apply one batch. Caller owns the transaction."""
    pending: list[dict[str, Any]] = []

    async def flush_events() -> None:
        if pending:
            await session.execute(insert(Event), pending)
            pending.clear()

    for item in items:
        if isinstance(item, EventAppended):
            pending.append(_event_row(item))
            continue
        # A non-event item: everything queued before it must land first, or a
        # RunFinished could overtake its own run's events.
        await flush_events()
        await _apply_one(session, item)

    await flush_events()


def _event_row(item: EventAppended) -> dict[str, Any]:
    event = item.event
    return {
        "run_id": item.run_id,
        # The driver's own counter, not arrival order at the writer -- batching
        # means arrival order is not the order the agent produced them in.
        "seq": event.get("seq"),
        "type": event.get("type"),
        "subtype": event.get("subtype"),
        "content": event.get("content"),
        # Absent unless the run was made with include_raw. Q3.
        "raw": event.get("raw"),
    }


async def _apply_one(session: AsyncSession, item: Item) -> None:
    if isinstance(item, SessionOpened):
        await session.execute(
            insert(Session).values(
                id=item.sid,
                title=item.title,
                model=item.model,
                permission_mode=item.permission_mode,
                agent_id=item.agent_id,
                status="idle",
                created_at=_at(item.at),
                last_used_at=_at(item.at),
            )
        )
    elif isinstance(item, SessionClosed):
        await session.execute(
            update(Session)
            .where(Session.id == item.sid)
            .values(status=item.status, closed_at=_at(item.at), last_used_at=_at(item.at))
        )
    elif isinstance(item, RunStarted):
        await session.execute(
            insert(Run).values(
                id=item.run_id,
                # NULL for a one-shot run, which is never registered and so has
                # no `sessions` row to reference.
                session_id=item.sid,
                sdk_session_id=item.sdk_session_id,
                prompt=item.prompt,
                started_at=_at(item.at),
            )
        )
    elif isinstance(item, RunFinished):
        await session.execute(
            update(Run).where(Run.id == item.run_id).values(**_finish_values(item))
        )
        await _roll_up_session(session, item)


async def _roll_up_session(session: AsyncSession, item: RunFinished) -> None:
    """Keep `sessions.total_turns` / `total_cost_usd` in step with the turn.

    Skipped entirely for a one-shot run (no `sid`, no `sessions` row) and for a
    turn that never reached a `ResultMessage` -- `total_turns` means "turns that
    reached a result", exactly as `SessionRecord.turns` does, and must not
    depend on how the consumer behaved afterwards.

    `total_cost_usd` is ASSIGNED, never accumulated. The SDK's figure is already
    cumulative for the connection (S6); summing per-turn values across a session
    would multiply the real number by roughly the turn count, which is the trap
    `CLAUDE.md` calls out by name.
    """
    if item.sid is None or item.outcome is None:
        return
    values: dict[str, Any] = {
        "total_turns": Session.total_turns + 1,
        "last_used_at": _at(item.at),
    }
    if item.outcome.total_cost_usd is not None:
        values["total_cost_usd"] = item.outcome.total_cost_usd
    if item.sdk_session_id is not None:
        values["sdk_session_id"] = item.sdk_session_id
    await session.execute(update(Session).where(Session.id == item.sid).values(**values))


def _finish_values(item: RunFinished) -> dict[str, Any]:
    outcome = item.outcome
    values: dict[str, Any] = {
        "finished_at": _at(item.at),
        "interrupted": item.interrupted,
        "timed_out": item.timed_out,
        # The run never consumed its own ResultMessage: crash, abandoned
        # consumer, or timeout. Stored explicitly rather than inferred from a
        # dozen NULLs, and distinct from a clean finish -- `runner.Run` tells
        # callers they MUST handle it separately.
        "outcome_missing": outcome is None,
        # NULL means "nobody can say", never 0.0. An aborted turn is
        # unattributed, not free (`runner.unattributed_abort`).
        "cost_usd": item.turn_cost_usd,
    }
    if item.sdk_session_id is not None:
        values["sdk_session_id"] = item.sdk_session_id
    if outcome is None:
        return values

    values.update(
        {
            "result_text": outcome.result,
            "result_subtype": outcome.subtype,
            "stop_reason": outcome.stop_reason,
            "terminal_reason": outcome.terminal_reason,
            "limit_hit": outcome.limit_hit,
            "num_turns": outcome.num_turns,
            "duration_ms": outcome.duration_ms,
            "duration_api_ms": outcome.duration_api_ms,
            "api_error_status": outcome.api_error_status,
            "errors": outcome.errors,
            "usage": outcome.usage,
            "model_usage": outcome.model_usage,
            "permission_denials": outcome.permission_denials,
            # The AGENT reporting its task failed -- a successful run with a bad
            # outcome. Distinct from `runs.error`, which is the MACHINERY
            # failing. Collapsing them makes "how often does the agent fail?"
            # unanswerable.
            "is_error": outcome.is_error,
        }
    )
    return values
