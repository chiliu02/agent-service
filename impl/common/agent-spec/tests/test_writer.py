"""plan-03 Task 3: the write path that cannot stall a turn.

The load-bearing assertions here are the negative ones. It is easy to write a
writer that stores rows correctly and still ruins the service, by blocking the
SSE drain or by turning a database outage into a failed turn. Those are what
these tests are for; correctness of the SQL itself is Task 4's integration
surface.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

import pytest

from agent_spec.db.items import (
    EventAppended,
    RunFinished,
    RunStarted,
    SessionClosed,
    SessionOpened,
)
from agent_spec.db.writer import QueueWriter


def _event(run_id: str = "r1", type_: str = "assistant", seq: int = 1) -> EventAppended:
    return EventAppended(run_id, {"seq": seq, "type": type_, "subtype": None, "content": []})


def _writer(**kw) -> QueueWriter:  # noqa: ANN003
    # No sessionmaker: every test below either never drains, or drains into a
    # deliberately broken one. Task 4 covers the happy path against Postgres.
    return QueueWriter(None, **kw)  # type: ignore[arg-type]


# -- the specification that matters most -------------------------------------------


def test_enqueue_is_not_a_coroutine_function() -> None:
    """Structural, not behavioural, and that is the point.

    A synchronous signature is what makes stalling the SSE drain *impossible*
    rather than merely discouraged. If this test fails, someone has made
    `enqueue` awaitable and the guarantee in `recorder.py` is gone.
    """
    assert not inspect.iscoroutinefunction(QueueWriter.enqueue)


def test_the_producer_never_blocks_or_raises_past_capacity() -> None:
    # Nothing drains, so the queue only grows. Push far past both bounds and
    # assert the producer neither raises nor slows down.
    writer = _writer(soft_capacity=100, hard_capacity=200)
    started = time.perf_counter()
    for i in range(20_000):
        writer.enqueue(_event(seq=i, type_="stream_event"))
    elapsed = time.perf_counter() - started

    assert writer.stats.enqueued == 20_000
    # What this reliably pins is "completes, never raises, never awaits". The
    # timing bound is a weak smoke check, NOT a proof that the drop policy is
    # O(1): with a small `soft_capacity` an O(n) scan would still finish inside
    # it. Sizing the test to catch that would make it take minutes to fail,
    # which is a worse test. `_make_room` carries the complexity argument.
    assert elapsed < 2.0, f"20k enqueues took {elapsed:.2f}s"


def test_the_queue_stays_bounded_when_nothing_drains() -> None:
    writer = _writer(soft_capacity=50, hard_capacity=100)
    for i in range(5_000):
        writer.enqueue(_event(seq=i, type_="stream_event"))
    assert len(writer._items) <= 100


# -- the drop policy ----------------------------------------------------------


def test_stream_events_are_dropped_before_anything_else() -> None:
    writer = _writer(soft_capacity=3, hard_capacity=1_000)
    for i in range(3):
        writer.enqueue(_event(seq=i))

    # At the soft mark. A stream_event is refused...
    writer.enqueue(_event(seq=99, type_="stream_event"))
    assert writer.stats.dropped_stream_events == 1
    assert writer.stats.dropped_over_hard_cap == 0

    # ...while an assistant message and a run row are still accepted, because
    # losing a run row orphans every event that references it.
    writer.enqueue(_event(seq=100, type_="assistant"))
    writer.enqueue(RunStarted("r2", None, None, "p", time.time()))
    kinds = [type(i).__name__ for i in writer._items]
    assert kinds.count("RunStarted") == 1
    assert all(
        i.event["type"] != "stream_event" for i in writer._items if isinstance(i, EventAppended)
    )


def test_run_and_session_rows_survive_past_the_soft_mark() -> None:
    writer = _writer(soft_capacity=1, hard_capacity=1_000)
    writer.enqueue(_event())
    for item in (
        SessionOpened("s1", None, None, None, time.time()),
        RunStarted("r1", "s1", None, "p", time.time()),
        RunFinished("r1", "s1", None, None, None, False, False, time.time()),
        SessionClosed("s1", "closed", time.time()),
    ):
        writer.enqueue(item)
    assert writer.stats.dropped_stream_events == 0
    assert writer.stats.dropped_over_hard_cap == 0
    assert len(writer._items) == 5


def test_past_the_hard_ceiling_even_run_rows_are_dropped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The ceiling exists so a long outage cannot grow the queue until the
    # process dies -- which would take the agent down with it.
    writer = _writer(soft_capacity=2, hard_capacity=4)
    with caplog.at_level(logging.ERROR):
        for i in range(20):
            writer.enqueue(RunStarted(f"r{i}", None, None, "p", time.time()))

    assert len(writer._items) == 4
    assert writer.stats.dropped_over_hard_cap == 16
    assert any("hard capacity" in r.message for r in caplog.records)


def test_dropping_is_counted_and_warned_once_not_per_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A sustained outage must not produce one log line per dropped event; that
    # turns a degradation into a second incident.
    writer = _writer(soft_capacity=2, hard_capacity=1_000)
    with caplog.at_level(logging.WARNING):
        for i in range(500):
            writer.enqueue(_event(seq=i, type_="stream_event"))

    assert writer.stats.dropped_stream_events == 498
    assert len([r for r in caplog.records if "soft capacity" in r.message]) == 1


# -- failure of the database itself -------------------------------------------


@pytest.mark.anyio
async def test_a_database_outage_drops_batches_and_keeps_running() -> None:
    """The turn must survive the database, not the other way round."""

    class BrokenSessionmaker:
        def __call__(self):  # noqa: ANN204
            raise ConnectionError("postgres is gone")

    writer = QueueWriter(BrokenSessionmaker(), batch_size=10, flush_interval_s=0.01)  # type: ignore[arg-type]
    writer.start()
    for i in range(50):
        writer.enqueue(_event(seq=i))

    await asyncio.sleep(0.2)

    # The drain task is still alive and the queue drained -- batches were
    # discarded rather than retried forever behind an ever-growing backlog.
    assert writer.stats.failed_batches > 0
    assert writer.stats.written == 0
    await writer.aclose(timeout_s=1.0)

    # And the producer never saw any of it.
    assert writer.stats.enqueued == 50


@pytest.mark.anyio
async def test_close_is_bounded_when_the_writer_cannot_drain() -> None:
    # Shutdown runs inside `config.shutdown_budget_s`; a database that stopped
    # answering must not turn shutdown into a hang.
    class HangingSessionmaker:
        def __call__(self):  # noqa: ANN204
            raise ConnectionError("nope")

    writer = QueueWriter(HangingSessionmaker(), flush_interval_s=0.01)  # type: ignore[arg-type]
    writer.start()
    writer.enqueue(_event())
    started = time.perf_counter()
    await writer.aclose(timeout_s=0.5)
    assert time.perf_counter() - started < 2.0


# -- the SQL, against a real Postgres -----------------------------------------

postgres = pytest.mark.postgres


@postgres
@pytest.mark.anyio
async def test_a_batch_round_trips_through_real_sql(postgres_url: str) -> None:
    """Proves `repository.apply` executes, and that ORDER within a batch holds.

    The ordering claim is the one worth a database: `events.run_id` references
    `runs.id`, so a batch containing a run and its events in queue order must
    insert cleanly. A version that grouped by type to save round trips would
    fail here with a foreign-key violation.
    """
    from sqlalchemy import text as sql

    from agent_spec.db import Base, create_engine, create_sessionmaker
    from agent_spec.db.outcome import RunOutcome

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    writer = QueueWriter(create_sessionmaker(engine), batch_size=1_000, flush_interval_s=0.01)
    writer.start()
    now = time.time()
    writer.enqueue(SessionOpened("s1", "t", "m", "dontAsk", now))
    writer.enqueue(RunStarted("r1", "s1", "sdk-1", "hello", now))
    for i in range(1, 4):
        writer.enqueue(_event(seq=i))
    writer.enqueue(
        RunFinished("r1", "s1", "sdk-1", RunOutcome(result="done", num_turns=2), 0.25, False, False, now)
    )
    writer.enqueue(SessionClosed("s1", "closed", now))
    await writer.aclose(timeout_s=5.0)

    assert writer.stats.failed_batches == 0
    async with engine.connect() as conn:
        assert await conn.scalar(sql("SELECT count(*) FROM events WHERE run_id='r1'")) == 3
        assert await conn.scalar(sql("SELECT status FROM sessions WHERE id='s1'")) == "closed"
        row = (
            await conn.execute(
                sql("SELECT result_text, cost_usd, outcome_missing, num_turns FROM runs WHERE id='r1'")
            )
        ).one()
    assert row.result_text == "done"
    assert float(row.cost_usd) == 0.25
    assert row.outcome_missing is False
    assert row.num_turns == 2
    await engine.dispose()
