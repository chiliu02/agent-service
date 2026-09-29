"""Reads. `repository.py` stays the sole WRITER; this is the sole reader.

Split for the same reason the writer and the SQL are split: a read path has
different failure modes (a slow scan degrades a page, it does not lose a turn)
and different tests, and mixing them makes "who can write?" harder to answer than
it should be.

## Ordering

A session's transcript is ordered by `events.id`, the insertion sequence, NOT by
`(run, seq)`. Both give the same answer, because a session serialises its turns
behind a lock and `repository.apply` preserves queue order within a batch -- but
`events.id` is a single monotonic column, so it also works as a **cursor**. A
compound sort would need a compound cursor to paginate without gaps or repeats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_spec.db.models import Event, Run, Session
from agent_spec.openapi.stop_kind import derive_stop_kind


@dataclass(slots=True)
class TranscriptPage:
    events: list[dict[str, Any]]
    next_after: int | None


async def session_exists(session: AsyncSession, sid: str) -> bool:
    return (
        await session.scalar(select(Session.id).where(Session.id == sid))
    ) is not None


async def transcript(
    session: AsyncSession, sid: str, *, limit: int, after: int | None
) -> TranscriptPage:
    """One page of a session's events, oldest first.

    Fetches `limit + 1` rows to decide whether a next page exists without a
    second COUNT query -- which on a long transcript costs a full scan to
    answer a question the page itself already implies.
    """
    stmt = (
        select(Event, Run.id)
        .join(Run, Event.run_id == Run.id)
        .where(Run.session_id == sid)
        .order_by(Event.id)
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(Event.id > after)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return TranscriptPage(
        events=[
            {
                "id": event.id,
                "run_id": run_id,
                "seq": event.seq,
                "at": event.at,
                "type": event.type,
                "subtype": event.subtype,
                "content": event.content,
            }
            for event, run_id in rows
        ],
        next_after=rows[-1][0].id if has_more and rows else None,
    )


def stop_kind_of(row: Any) -> Any:
    """`stop_kind` for a stored run. **Derived on read, never stored.**

    `StoredRun.stop_kind` was published on all three documents and populated by
    nobody: the live path derived it, and a stored run was rebuilt straight from
    a row, so the field a client had been told to branch on came back null from
    history every single time.

    **A column would have meant a fourth DDL revision for a value that is a pure
    function of six already in the row** -- and a stored derivation can go stale
    against its own inputs, which this one cannot.

    **History is the surface it matters most on.** A turn that ran out of wall
    clock answered `504` and produced no run response at all; `timed_out` here
    is the only thing left that says so, long after the 504 was read.

    Derived through the one shared function rather than beside it, so no build
    and no surface can answer differently.
    """
    return derive_stop_kind(
        outcome_recorded=not row.outcome_missing,
        is_error=bool(row.is_error),
        interrupted=bool(row.interrupted),
        timed_out=bool(row.timed_out),
        limit_hit=row.limit_hit,
        raw=row.stop_reason or row.result_subtype,
    )


async def run(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    row = await session.scalar(select(Run).where(Run.id == run_id))
    if row is None:
        return None
    return {
        "run_id": row.id,
        "session_id": row.session_id,
        "sdk_session_id": row.sdk_session_id,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "prompt": row.prompt,
        "result_text": row.result_text,
        "result_subtype": row.result_subtype,
        "stop_reason": row.stop_reason,
        "terminal_reason": row.terminal_reason,
        "limit_hit": row.limit_hit,
        "num_turns": row.num_turns,
        "duration_ms": row.duration_ms,
        "duration_api_ms": row.duration_api_ms,
        "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
        "usage": row.usage,
        "model_usage": row.model_usage,
        "permission_denials": row.permission_denials,
        "errors": row.errors,
        "api_error_status": row.api_error_status,
        "is_error": row.is_error,
        "interrupted": row.interrupted,
        "timed_out": row.timed_out,
        "outcome_missing": row.outcome_missing,
        # **Derived on read, never stored, and derived HERE so no build can
        # answer differently.** `StoredRun.stop_kind` was published on all three
        # documents and populated by nobody: the live path derives it, and a
        # stored run was rebuilt straight from this dict, so the field a client
        # was told to branch on came back null from history every time.
        #
        # A column would have meant a fourth DDL revision for a value that is a
        # pure function of six that are already here -- and a stored derivation
        # can go stale against its own inputs, which this one cannot.
        #
        # **History is the surface it matters most on.** A timed-out turn
        # answered 504 live and the response is long gone; `timed_out` in this
        # row is the only thing left that says so.
        "stop_kind": stop_kind_of(row),
    }
