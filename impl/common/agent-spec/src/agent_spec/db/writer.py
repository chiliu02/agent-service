"""The bounded queue between a turn and the database, and the task that drains it.

`enqueue()` is the producer side. It is a plain `def` that appends to a deque and
sets an event: no awaits, no locks, no exceptions. That is the whole specification --
`recorder.py` explains at length why a suspension point here would be a
correctness problem in `_send_impl`, not merely a latency one.

## "Synchronous" runs and sessions, reconciled

The persistence design says `runs` and `sessions` rows are "written synchronously at
start and finish", while events are queued. Taken literally that is impossible
here: the recorder protocol is synchronous, so nothing on the producer side can
await a database round trip.

The intent behind that sentence is **durability, not timing** -- "small,
low-frequency, and losing them makes the events orphans". So everything goes
through this one queue, in order, and the distinction becomes **droppability**:

| Item | Dropped when the queue is full? |
|---|---|
| `EventAppended` carrying a `stream_event` | **First.** Token deltas, reconstructible from the assistant message that follows. |
| `EventAppended` carrying anything else | Only past the hard ceiling. |
| `RunStarted` / `RunFinished` / session items | Only past the hard ceiling, and loudly. |

One queue rather than two because ORDER MATTERS: `events.run_id` references
`runs.id`, so a run row must be inserted before its events. Two queues would
race and produce foreign-key failures under exactly the load that makes them
hard to reproduce.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_spec.db import repository
from agent_spec.db.items import EventAppended, Item

log = logging.getLogger(__name__)

# Above this, `stream_event` rows are sacrificed to keep the queue bounded.
_SOFT_CAPACITY = 10_000
# Above this, ANYTHING is dropped, including run rows. Only reachable if the
# database has been unreachable for a long time; the alternative is growing
# until the process dies, which would take the agent down with it.
_HARD_CAPACITY = 50_000
_BATCH_SIZE = 500
_FLUSH_INTERVAL_S = 0.25


@dataclass(slots=True)
class WriterStats:
    """Observability for a path that is deliberately lossy under pressure."""

    enqueued: int = 0
    written: int = 0
    dropped_stream_events: int = 0
    dropped_over_hard_cap: int = 0
    failed_batches: int = 0
    # Set once per contiguous period of loss so a sustained outage produces one
    # WARNING and a final count, not one line per dropped event.
    _warned: bool = field(default=False, repr=False)


class QueueWriter:
    """Owns the queue, the drop policy, and the drain task."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        soft_capacity: int = _SOFT_CAPACITY,
        hard_capacity: int = _HARD_CAPACITY,
        batch_size: int = _BATCH_SIZE,
        flush_interval_s: float = _FLUSH_INTERVAL_S,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._soft = soft_capacity
        self._hard = hard_capacity
        self._batch = batch_size
        self._interval = flush_interval_s
        # A deque, not asyncio.Queue. `Queue.put_nowait` raises QueueFull at a
        # fixed bound, which is the wrong shape twice over: the bound here is
        # per-item-kind (a run row is accepted where a stream_event is refused),
        # and an exception on the producer side would put a `try` in the hot
        # path for an outcome that is expected, not exceptional.
        self._items: deque[Item] = deque()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self.stats = WriterStats()

    # -- producer side ----------------------------------------------------

    def enqueue(self, item: Item) -> None:
        """Never blocks, never raises. Called from inside the SSE drain.

        Deliberately a plain `def`. If this ever needs to become `async`, the
        design is wrong -- see the module docstring and `recorder.py`.
        """
        try:
            self.stats.enqueued += 1
            if len(self._items) >= self._soft and not self._make_room(item):
                return
            self._items.append(item)
            self._wake.set()
        except Exception:  # noqa: BLE001 - must not escape into a turn
            # The recorder specification is absolute: raising here would land in
            # `_send_impl`'s `except BaseException` and mislabel a turn that
            # actually succeeded. Persistence must never corrupt the accounting
            # it exists to observe.
            log.exception("writer.enqueue failed; item dropped")

    def _make_room(self, incoming: Item) -> bool:
        """Return True if `incoming` should still be appended.

        **O(1). This runs on the SSE hot path** -- once per SDK message, for
        every concurrent run, whenever the queue is above the soft mark. An
        earlier version scanned the deque to evict the oldest queued
        `stream_event`, which is O(n) per enqueue with n up to `soft_capacity`:
        quadratic under exactly the sustained pressure that makes the drop
        policy matter in the first place. Refusing the incoming item achieves
        the same goal -- `stream_event` records are what gets sacrificed --
        without touching what is already queued.
        """
        if isinstance(incoming, EventAppended) and incoming.droppable:
            self.stats.dropped_stream_events += 1
            self._warn_once()
            return False

        if len(self._items) >= self._hard:
            # Nothing droppable left and the queue is at the ceiling. Losing a
            # run row is bad -- its events become orphans -- but an unbounded
            # queue kills the process, which loses the agent too.
            self.stats.dropped_over_hard_cap += 1
            log.error(
                "persistence queue at hard capacity (%d); dropping %s. "
                "The database has been unreachable or too slow for a long time.",
                self._hard,
                type(incoming).__name__,
            )
            return False
        return True

    def _warn_once(self) -> None:
        if not self.stats._warned:
            self.stats._warned = True
            log.warning(
                "persistence queue above soft capacity (%d); dropping stream_event "
                "records to keep the response path free. Totals are reported on close.",
                self._soft,
            )

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain_forever())

    async def aclose(self, timeout_s: float = 5.0) -> None:
        """Drain what is queued, then stop.

        Bounded: this runs inside the app's shutdown budget, and a database
        that has stopped answering must not turn shutdown into a hang. See
        `config.shutdown_budget_s`.
        """
        self._closing = True
        self._wake.set()
        if self._task is not None:
            try:
                async with asyncio.timeout(timeout_s):
                    await self._task
            except TimeoutError:
                self._task.cancel()
                log.warning(
                    "persistence writer did not drain within %.1fs; %d items lost",
                    timeout_s,
                    len(self._items),
                )
            self._task = None
        if self.stats.dropped_stream_events or self.stats.dropped_over_hard_cap:
            log.warning(
                "persistence dropped %d stream_event and %d other records",
                self.stats.dropped_stream_events,
                self.stats.dropped_over_hard_cap,
            )

    # -- consumer side ----------------------------------------------------

    async def _drain_forever(self) -> None:
        while True:
            if not self._items:
                if self._closing:
                    return
                self._wake.clear()
                # A bounded wait, not a bare `await`: `_closing` is set by
                # another task and this must notice it even if nothing is ever
                # enqueued again.
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(self._interval):
                        await self._wake.wait()
                continue
            await self._flush_once()

    async def _flush_once(self) -> None:
        batch: list[Item] = []
        while self._items and len(batch) < self._batch:
            batch.append(self._items.popleft())
        if not batch:
            return
        try:
            async with self._sessionmaker() as session, session.begin():
                await repository.apply(session, batch)
            self.stats.written += len(batch)
        except Exception:  # noqa: BLE001 - a failed batch must not kill the task
            # Discarded, not retried indefinitely. These are observability
            # records; the alternative is a wedged writer and an unbounded
            # queue while the agent keeps running perfectly well.
            self.stats.failed_batches += 1
            log.exception("persistence batch of %d failed; discarded", len(batch))
            # Back off before the next batch. Two reasons, one of which turned
            # out to be smaller than it looked:
            #
            # 1. It stops a hot retry loop hammering a database that is failing
            #    slowly rather than instantly. This is the real reason.
            # 2. It is also the only guaranteed yield on this path -- a
            #    sessionmaker that fails SYNCHRONOUSLY (dead pool, DNS failure)
            #    never reaches an await inside the `try`. MEASURED, and the
            #    effect is small: at the configured bounds the whole backlog is
            #    at most `hard_capacity / batch_size` = 100 iterations of a
            #    raise, which a co-running task does not detectably notice. A
            #    test written to pin this passed with the sleep REMOVED, so it
            #    was deleted rather than kept as false coverage.
            await asyncio.sleep(self._interval)
