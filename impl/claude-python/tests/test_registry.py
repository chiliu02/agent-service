import asyncio
import logging
import re
import time
from pathlib import Path

import pytest

from agent_service.config import Settings
from agent_service.options import InvalidSessionId
from agent_service.registry import (
    SessionLimitReached,
    SessionNotFound,
    SessionOpenTimeout,
    SessionRegistry,
)
from agent_spec.openapi.schemas import RunOptions


class FakeSession:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.idle = 0.0
        # Mirrors AgentSession.status: "idle" once open()ed. Defaulting to
        # "idle" (not "running") keeps every existing test in this file
        # honest about what it's exercising -- only the busy-skip tests
        # below flip it to "running".
        self.status = "idle"

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    @property
    def idle_seconds(self) -> float:
        return self.idle


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        max_sessions=2,
        session_idle_ttl_s=10,
        session_reaper_interval_s=1,
    )


def make_registry(settings: Settings) -> tuple[SessionRegistry, list[FakeSession]]:
    made: list[FakeSession] = []

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = FakeSession()
        made.append(s)
        return s

    return SessionRegistry(settings, session_factory=factory), made


async def test_create_opens_and_returns_a_distinct_id(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid1 = await reg.create(RunOptions(), None)
    sid2 = await reg.create(RunOptions(), None)
    assert sid1 != sid2
    assert all(s.opened for s in made)


async def test_get_returns_the_session(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    assert reg.get(sid) is made[0]


async def test_get_unknown_raises(settings: Settings) -> None:
    reg, _ = make_registry(settings)
    with pytest.raises(SessionNotFound):
        reg.get("nope")


async def test_a_bad_supplied_session_id_is_rejected_by_the_registry_itself(
    settings: Settings,
) -> None:
    """Enforced by the thing that creates sessions, not by one route into it.

    The HTTP tests show a 400; they would still show one with the check living
    in `api.py`, which would leave every other caller of `create()` unguarded.
    This calls the registry directly, so it fails if the validation ever moves
    back up into the route.

    Both rules are the CLI's own: the id must be a UUID, and it cannot be
    combined with `resume` (measured -- the CLI exits 1).
    """
    made: list[object] = []

    def factory(options, settings_, title=None, *, sdk_session_id=None):  # noqa: ANN001, ARG001
        made.append(sdk_session_id)
        return FakeSession()

    registry = SessionRegistry(settings, session_factory=factory)

    with pytest.raises(InvalidSessionId):
        await registry.create(RunOptions(), None, "not-a-uuid")

    with pytest.raises(InvalidSessionId):
        await registry.create(
            RunOptions(resume="e13345e0-80a8-473d-a5ed-720253de700a"),
            None,
            "7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55",
        )

    # Neither attempt built a session, and neither consumed a slot -- the check
    # runs before the reservation, so a rejected request cannot hold capacity.
    assert made == []
    assert len(registry.list()) == 0


async def test_cap_is_enforced(settings: Settings) -> None:
    reg, _ = make_registry(settings)
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    with pytest.raises(SessionLimitReached):
        await reg.create(RunOptions(), None)


async def test_closing_frees_a_slot(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    await reg.close(sid)
    assert made[0].closed is True
    await reg.create(RunOptions(), None)  # must not raise


async def test_close_unknown_raises(settings: Settings) -> None:
    reg, _ = make_registry(settings)
    with pytest.raises(SessionNotFound):
        await reg.close("nope")


async def test_list_returns_live_sessions_only(settings: Settings) -> None:
    reg, _ = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    await reg.close(sid)
    assert len(reg.list()) == 1


async def test_reaper_closes_idle_sessions(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0
    await reg.reap_once()
    assert made[0].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid)


async def test_reaper_leaves_fresh_sessions_alone(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 1.0
    await reg.reap_once()
    assert made[0].closed is False
    assert reg.get(sid) is made[0]


async def test_close_all_closes_everything(settings: Settings) -> None:
    reg, made = make_registry(settings)
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    await reg.close_all()
    assert all(s.closed for s in made)
    assert reg.list() == []


async def test_reaper_task_starts_and_stops(settings: Settings) -> None:
    reg, _ = make_registry(settings)
    reg.start_reaper()
    await asyncio.sleep(0)
    assert reg._reaper is not None
    await reg.stop_reaper()
    assert reg._reaper is None


# -- the unresolved question: reaper vs. a busy session ----------------------
#
# disconnect() was only ever measured to terminate the CLI subprocess
# cleanly at a clean turn boundary (spike S5). Racing it against an actively
# draining turn is untested territory, and AgentSession.send() holds its
# per-session lock for the whole turn -- so a reaper that force-closed a
# "running" session could plausibly surface as a surprise failure to
# whichever caller is mid-turn. The chosen policy: the reaper SKIPS any
# session whose status == "running" and leaves it for the next tick, rather
# than force-closing it. These tests pin that behaviour.


async def test_reaper_skips_busy_sessions(settings: Settings) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0
    made[0].status = "running"
    await reg.reap_once()
    assert made[0].closed is False
    assert reg.get(sid) is made[0]


async def test_reaper_closes_a_previously_busy_session_once_it_goes_idle(
    settings: Settings,
) -> None:
    reg, made = make_registry(settings)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0
    made[0].status = "running"
    await reg.reap_once()
    assert made[0].closed is False  # skipped this tick

    made[0].status = "idle"  # turn finished by the next tick
    await reg.reap_once()
    assert made[0].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid)


# -- the other race the brief calls out: create() vs. the cap ----------------
#
# The cap check and the insert must be atomic across concurrent create()
# calls, or two callers can each observe room for one more and both succeed,
# overshooting max_sessions. FakeSession.open() never actually suspends (no
# internal await), so it can't exercise this on its own -- a race needs a
# real yield point inside the "slot reserved but not yet inserted" window,
# which this test manufactures with an open() that awaits asyncio.sleep(0).


async def test_concurrent_creates_do_not_exceed_the_cap(settings: Settings) -> None:
    made: list[FakeSession] = []

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = FakeSession()

        async def slow_open() -> None:
            await asyncio.sleep(0)
            s.opened = True

        s.open = slow_open  # type: ignore[method-assign]
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)

    async def attempt() -> str | None:
        try:
            return await reg.create(RunOptions(), None)
        except SessionLimitReached:
            return None

    results = await asyncio.gather(*(attempt() for _ in range(5)))
    successes = [r for r in results if r is not None]

    assert len(successes) == settings.max_sessions
    assert len(reg.list()) == settings.max_sessions
    # The cap check must gate BEFORE the factory runs, not merely before the
    # insert -- otherwise a losing caller would still spin up a session it
    # can never register.
    assert len(made) == settings.max_sessions


# -- fix round 1, Critical 1: open() must not run under the exclusive lock --
#
# The first version of create() held `_lock` across `await session.open()`.
# open() spawns a CLI subprocess and is not measured to be fast or reliably
# bounded (unlike disconnect(), which spike S5 covers) -- so a slow or hung
# spawn for one session blocked close()/reap_once() on every OTHER,
# already-open session too, destroying the mechanism an operator would use to
# shed load. The fix: reserve a cap slot under the lock, release the lock,
# run open() unlocked, then reconcile (insert on success, release the
# reservation on failure/timeout) under the lock again.


async def test_slow_open_does_not_block_reap_once_on_other_sessions(
    settings: Settings,
) -> None:
    entered_open = asyncio.Event()
    release_open = asyncio.Event()
    made: list[FakeSession] = []

    class SlowOpenSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    calls = {"n": 0}

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        s = FakeSession() if calls["n"] == 1 else SlowOpenSession()
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)

    sid_b = await reg.create(RunOptions(), None)  # opens instantly
    made[0].idle = 999.0  # stale, so reap_once() has real work to do on it

    task = asyncio.create_task(reg.create(RunOptions(), None))  # session A
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)

    # Session A is stuck inside open() with no lock held across it. A reap
    # tick touching only session B must complete promptly -- if `_lock` were
    # still held across A's open(), this would hang until release_open.set().
    reaped = await asyncio.wait_for(reg.reap_once(), timeout=1.0)
    assert reaped == 1
    assert made[0].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid_b)

    release_open.set()
    sid_a = await asyncio.wait_for(task, timeout=1.0)
    assert made[1].opened is True
    assert reg.get(sid_a) is made[1]


async def test_slow_open_does_not_block_close_of_other_sessions(
    settings: Settings,
) -> None:
    entered_open = asyncio.Event()
    release_open = asyncio.Event()
    made: list[FakeSession] = []

    class SlowOpenSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    calls = {"n": 0}

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        s = FakeSession() if calls["n"] == 1 else SlowOpenSession()
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)
    sid_b = await reg.create(RunOptions(), None)

    task = asyncio.create_task(reg.create(RunOptions(), None))  # session A
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)

    # close() on B must not wait for A's open() to finish.
    await asyncio.wait_for(reg.close(sid_b), timeout=1.0)
    assert made[0].closed is True

    release_open.set()
    sid_a = await asyncio.wait_for(task, timeout=1.0)
    assert reg.get(sid_a) is made[1]


async def test_a_failed_open_releases_its_reservation(settings: Settings) -> None:
    calls = {"n": 0}

    class FailingSession(FakeSession):
        async def open(self) -> None:
            raise RuntimeError("boom")

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        return FailingSession() if calls["n"] == 1 else FakeSession()

    reg = SessionRegistry(settings, session_factory=factory)  # max_sessions=2

    with pytest.raises(RuntimeError, match="boom"):
        await reg.create(RunOptions(), None)

    # The failed attempt must not have permanently consumed a cap slot: both
    # real slots are still available afterwards.
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    assert len(reg.list()) == 2


async def test_a_failing_factory_releases_its_reservation(settings: Settings) -> None:
    # Distinct from test_a_failed_open_releases_its_reservation: here the
    # FACTORY itself raises (e.g. bad options), before any session object --
    # let alone open() -- exists. The reservation is taken before the
    # factory runs, so it must be released here too, not only on a failing
    # open().
    calls = {"n": 0}

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad options")
        return FakeSession()

    reg = SessionRegistry(settings, session_factory=factory)  # max_sessions=2

    with pytest.raises(ValueError, match="bad options"):
        await reg.create(RunOptions(), None)

    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    assert len(reg.list()) == 2


async def test_a_timed_out_open_releases_its_reservation(settings: Settings) -> None:
    class HangingOpenSession(FakeSession):
        async def open(self) -> None:
            await asyncio.Event().wait()  # never released

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        return HangingOpenSession()

    reg = SessionRegistry(settings, session_factory=factory, open_timeout_s=0.05)

    with pytest.raises(SessionOpenTimeout):
        await reg.create(RunOptions(), None)

    assert len(reg.list()) == 0

    def ok_factory(options, settings, title=None):  # noqa: ANN001, ARG001
        return FakeSession()

    reg._factory = ok_factory
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    assert len(reg.list()) == 2


# -- fix round 1, Important 4: close_all() must not orphan the unprocessed --


async def test_close_all_cancelled_midway_leaves_unprocessed_sessions_tracked(
    settings: Settings,
) -> None:
    entered = asyncio.Event()
    proceed = asyncio.Event()

    class GatedSession(FakeSession):
        async def close(self) -> None:
            entered.set()
            await proceed.wait()
            self.closed = True

    reg, made = make_registry(settings)
    sid_a = await reg.create(RunOptions(), None)  # plain FakeSession

    def gated_factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = GatedSession()
        made.append(s)
        return s

    reg._factory = gated_factory
    await reg.create(RunOptions(), None)  # sid_b, inserted after sid_a

    task = asyncio.create_task(reg.close_all())
    # dict.popitem() is LIFO, so close_all() reaches the more-recently
    # inserted session (B) first and gets stuck inside its close().
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # A was never reached by the cancelled loop -- it must still be tracked,
    # not silently dropped by an upfront `_sessions.clear()`.
    assert reg.get(sid_a) is made[0]

    proceed.set()  # let the gated close() finish so nothing lingers


# -- fix round 1, Minor: close() must not orphan a session whose teardown --
# -- raised ------------------------------------------------------------------


async def test_close_leaves_the_session_registered_if_teardown_raises(
    settings: Settings,
) -> None:
    class FlakyCloseSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self._raise_next = True

        async def close(self) -> None:
            if self._raise_next:
                self._raise_next = False
                raise RuntimeError("disconnect blew up")
            await super().close()

    made: list[FlakyCloseSession] = []

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = FlakyCloseSession()
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)
    sid = await reg.create(RunOptions(), None)

    with pytest.raises(RuntimeError, match="disconnect blew up"):
        await reg.close(sid)

    # Still registered: a failed close does not silently vanish the session.
    assert reg.get(sid) is made[0]
    assert made[0].closed is False

    # A retry (the fake only raises once) succeeds and removes it.
    await reg.close(sid)
    assert made[0].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid)


# -- fix round 2: cancellation between a successful open() and the reconcile
#
# Round 1's reconcile re-acquired `_lock` after open() finished (success and
# both exception branches). A reviewer reproduced, against the real
# SessionRegistry, that if another coroutine held `_lock` at exactly that
# moment (a realistic in-flight close()/reap_once()) and the create() task
# was cancelled while awaiting that contended lock, `_reserved` was never
# decremented -- permanent capacity loss -- and, in the success case, the
# already-opened session was never inserted into `_sessions` either: a live,
# unreachable subprocess nothing could ever close.
#
# The fix removes the second acquisition entirely: every reconcile-side
# mutation of `_reserved`/`_sessions` is now a bare synchronous statement, so
# there is no `await` -- hence no suspension point -- between "open()
# returned" and "the reservation is released / the session is registered."


async def test_create_reconciles_without_waiting_for_the_registry_lock(
    settings: Settings,
) -> None:
    # Directly reproduces the reviewer's scenario shape: another coroutine
    # holds `_lock` for as long as it likes while THIS create()'s open() is
    # still pending and after it finishes. Round 1's code would block trying
    # to reacquire `_lock` to reconcile once open() succeeded -- this test
    # would hang past its wait_for and fail loudly against that code. The
    # fix must complete regardless of who else holds the lock.
    entered_open = asyncio.Event()
    release_open = asyncio.Event()
    lock_released = asyncio.Event()
    made: list[FakeSession] = []

    class ControllableSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = ControllableSession()
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)

    task = asyncio.create_task(reg.create(RunOptions(), None))
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)
    # The initial reservation is already done (create() released `_lock`
    # before calling open()), so grabbing the lock now is uncontended.
    assert reg._reserved == 1

    async def hold_lock_indefinitely() -> None:
        async with reg._lock:
            await lock_released.wait()

    holder = asyncio.create_task(hold_lock_indefinitely())
    await asyncio.sleep(0)  # let holder actually acquire `_lock`

    release_open.set()  # let open() finish while `_lock` is held elsewhere
    # If reconcile still needed `_lock`, this would hang until
    # lock_released.set() below -- which we deliberately never call before
    # this wait_for, so a regression here fails loudly, not flakily.
    sid = await asyncio.wait_for(task, timeout=1.0)

    assert reg._reserved == 0
    assert reg.get(sid) is made[0]
    assert made[0].opened is True

    lock_released.set()
    await holder


async def test_cancelling_create_while_the_lock_is_held_elsewhere_does_not_leak(
    settings: Settings,
) -> None:
    """Why `create()`'s reconcile must be BARE SYNCHRONOUS statements.

    The reconcile used to re-acquire `_lock` a second time. Reproduced against
    the real registry: with another coroutine holding `_lock` throughout (an
    entirely realistic in-flight close()/reap_once()), a `create()` cancelled
    while AWAITING that contended acquisition left `_reserved` incremented AND
    the already-opened session unregistered -- unreachable via `get()`/`list()`,
    so nothing could ever close it either. A permanent capacity leak plus an
    orphaned subprocess, once per occurrence.

    With no `await` between "open() returned" and "registered / reservation
    released", there is no suspension point for a cancellation to land on: on a
    single-threaded loop a task can only be preempted at an `await`. The
    sequence is atomic and cancellation-immune BY CONSTRUCTION, not by locking
    -- correctness never needed the lock for a plain int decrement, only the
    check-and-increment the reservation came from did.

    Because that is true, this test can no longer reach the interleaving it was
    written to catch: the cancellation lands inside the still-suspended
    `open()` every time (measured, 200/200). It is kept because it is the only
    test that holds `_lock` contended while a `create()` is cancelled, which is
    the exact situation the old shape deadlocked in -- see the comment on the
    assertions below.
    """
    entered_open = asyncio.Event()
    release_open = asyncio.Event()
    lock_released = asyncio.Event()
    made: list[FakeSession] = []

    class ControllableSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        s = ControllableSession()
        made.append(s)
        return s

    reg = SessionRegistry(settings, session_factory=factory)

    task = asyncio.create_task(reg.create(RunOptions(), None))
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)

    async def hold_lock_indefinitely() -> None:
        async with reg._lock:
            await lock_released.wait()

    holder = asyncio.create_task(hold_lock_indefinitely())
    await asyncio.sleep(0)

    release_open.set()
    task.cancel()  # try to land the cancellation right as open() succeeds

    result: str | None = None
    try:
        result = await asyncio.wait_for(task, timeout=1.0)
    except asyncio.CancelledError:
        pass

    # MEASURED, and the opposite of what this comment used to claim: the
    # cancellation always wins -- 200/200 runs left `result is None`. It is
    # requested while `open()` is still suspended at `release_open.wait()`, so
    # it lands there, inside a real suspension point, and never reaches the
    # reconcile at all.
    #
    # What the test actually pins is therefore the `except BaseException`
    # branch releasing the reservation -- the same guarantee as the test below,
    # reached by a different route (a CONTENDED second acquisition is what the
    # old shape would have blocked on here).
    #
    # `_reserved == 0` is the assertion that matters and holds unconditionally.
    # The `result is not None` branch is kept as a GUARD, not as an observed
    # path: if a future change reintroduces a suspension point after `open()`
    # returns, the race becomes real again and the bookkeeping must still be
    # consistent. Do not delete it because coverage says it is unreached.
    assert reg._reserved == 0
    if result is not None:  # pragma: no cover - guard; measured never taken
        assert reg.get(result) is made[0]
        assert made[0].opened is True
    else:
        assert reg.list() == []

    lock_released.set()
    await holder


async def test_cancelling_create_while_open_is_in_flight_releases_the_reservation(
    settings: Settings,
) -> None:
    # The same failure mode, for the two exception branches: a create() task
    # cancelled while genuinely suspended INSIDE open() (a real suspension
    # point -- CancelledError is a BaseException, caught by the generic
    # except clause) must still release its reservation.
    entered_open = asyncio.Event()

    class HangingOpenSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await asyncio.Event().wait()  # never released

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        return HangingOpenSession()

    reg = SessionRegistry(settings, session_factory=factory)

    task = asyncio.create_task(reg.create(RunOptions(), None))
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)
    assert reg._reserved == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert reg._reserved == 0
    assert reg.list() == []


# -- Plan 2 follow-up 3: no close path may drop a session whose teardown -----
# -- failed, and follow-up 5: reap_once() must count successes ---------------
#
# registry.close() has always looked the session up and removed it only once
# close() actually returned (see the test three blocks above). reap_once() and
# close_all() did the opposite: they POPPED first and then awaited close(), so
# a failing disconnect() dropped the registry's only handle on a subprocess
# that is still connected -- no retry, and nothing left to observe. Measured
# against the pre-fix code: `registry.close` left still_registered=True while
# `reap_once` and `close_all` both left still_registered=False,
# disconnected=False. All three now remove the session only after close()
# succeeds; they differ only in what they do with the failure (raise / retry
# next tick / report at shutdown).


class RaisingCloseSession(FakeSession):
    """Teardown fails `fail_times` times, then succeeds. Mirrors a
    disconnect() that blows up but leaves the session retryable (which is what
    AgentSession.close() does -- it leaves `status` non-terminal on that
    path)."""

    def __init__(self, fail_times: int = 1) -> None:
        super().__init__()
        self._left = fail_times

    async def close(self) -> None:
        if self._left > 0:
            self._left -= 1
            raise RuntimeError("disconnect blew up")
        await super().close()


def _registry_of(settings: Settings, sessions: list[FakeSession]) -> SessionRegistry:
    it = iter(sessions)

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        return next(it)

    return SessionRegistry(settings, session_factory=factory)


async def test_reap_once_leaves_a_session_registered_if_its_close_raises(
    settings: Settings,
) -> None:
    made = [RaisingCloseSession()]
    reg = _registry_of(settings, made)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0

    reaped = await reg.reap_once()

    # The subprocess is still connected, so the registry must still hold the
    # handle -- dropping it here orphans the process with no way to retry and
    # no way to see that it is there.
    assert reaped == 0
    assert reg.get(sid) is made[0]
    assert made[0].closed is False

    # ...and the next tick retries it, because it is still idle and still
    # stale. That is the whole point of keeping it.
    reaped = await reg.reap_once()
    assert reaped == 1
    assert made[0].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid)


async def test_reap_once_returns_sessions_closed_not_sessions_attempted(
    settings: Settings,
) -> None:
    # The reaper's return value is its only observability. Counting attempts
    # meant a tick that failed EVERY close still reported a full sweep while
    # leaving the subprocesses running.
    made: list[FakeSession] = [RaisingCloseSession(), FakeSession()]
    reg = _registry_of(settings, made)
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    for s in made:
        s.idle = 999.0

    reaped = await reg.reap_once()

    assert reaped == 1  # two attempted, one actually closed
    assert len(reg.list()) == 1
    assert made[1].closed is True


async def test_close_all_leaves_a_failed_session_registered_and_closes_the_rest(
    settings: Settings,
) -> None:
    # close_all() runs at ASGI shutdown, so nobody will retry what it leaves
    # behind. It still must not drop the handle: `list()` afterwards is the
    # only record of which subprocesses were still connected when the process
    # went away, and one failure must not stop the remaining sessions from
    # being torn down.
    made: list[FakeSession] = [RaisingCloseSession(fail_times=99), FakeSession()]
    reg = _registry_of(settings, made)
    sid_bad = await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)

    await asyncio.wait_for(reg.close_all(), timeout=1.0)

    assert made[1].closed is True
    assert [sid for sid, _ in reg.list()] == [sid_bad]


async def test_close_all_terminates_when_every_close_fails(
    settings: Settings,
) -> None:
    # Guards the shape of the fix, not just its effect: the old loop was
    # `while self._sessions: popitem()`, which terminated only because the pop
    # was unconditional. Removing on success alone means the loop must track
    # what it has already attempted, or it spins forever on a session that
    # never closes.
    made: list[FakeSession] = [
        RaisingCloseSession(fail_times=99),
        RaisingCloseSession(fail_times=99),
    ]
    reg = _registry_of(settings, made)
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)

    await asyncio.wait_for(reg.close_all(), timeout=1.0)

    assert len(reg.list()) == 2
    # Exactly one attempt each per call -- close_all() does not retry within
    # itself; a caller that wants another pass calls it again.
    assert all(s.closed is False for s in made)


async def test_all_three_close_paths_agree_on_a_failed_disconnect(
    settings: Settings,
) -> None:
    # The defect was the INCONSISTENCY between the three call sites, so pin
    # them together: none of them may leave a session unregistered while its
    # close() has not succeeded.
    async def still_registered_after(op: str) -> bool:
        made = [RaisingCloseSession(fail_times=99)]
        reg = _registry_of(settings, made)
        sid = await reg.create(RunOptions(), None)
        made[0].idle = 999.0
        if op == "close":
            with pytest.raises(RuntimeError):
                await reg.close(sid)
        elif op == "reap_once":
            assert await reg.reap_once() == 0
        else:
            await reg.close_all()
        return sid in dict(reg.list()) and made[0].closed is False

    for op in ("close", "reap_once", "close_all"):
        assert await still_registered_after(op) is True, op


async def test_reap_count_and_registry_stay_truthful_with_a_create_in_flight(
    settings: Settings,
) -> None:
    # The distilled concurrent case from the fuzz harness that drove this
    # round (400 randomised rounds over create/close/reap_once/close_all with
    # failing and slow disconnects: 323 violations against the pre-fix code,
    # 0 after). A reap sweeping a mix of a failing and a healthy session,
    # while a create()'s open() is still in flight, must report exactly what
    # it closed and must not drop what it did not.
    entered_open = asyncio.Event()
    release_open = asyncio.Event()

    class SlowOpenSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    made: list[FakeSession] = [RaisingCloseSession(fail_times=99), FakeSession()]
    pending = [*made, SlowOpenSession()]
    settings.max_sessions = 3
    reg = _registry_of(settings, pending)
    sid_bad = await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)
    for s in made:
        s.idle = 999.0

    creating = asyncio.create_task(reg.create(RunOptions(), None))
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)

    reaped = await asyncio.wait_for(reg.reap_once(), timeout=1.0)

    assert reaped == 1  # one of the two stale sessions actually closed
    assert made[1].closed is True
    assert reg.get(sid_bad) is made[0]  # the failure kept its handle

    release_open.set()
    sid_new = await asyncio.wait_for(creating, timeout=1.0)
    assert reg.get(sid_new) is pending[2]
    assert reg._reserved == 0
    assert sorted(sid for sid, _ in reg.list()) == sorted([sid_bad, sid_new])


# -- fix round: three behaviours the round above asserted in prose only ------
#
# A mutation pass over the follow-up-3 change found three edits that survived
# the whole suite -- i.e. three claims the docstrings make that nothing
# checked: re-reading `_sessions` each iteration (M4), the summary log line
# (M5), and its "N of M" denominator (M6). Confirmed surviving before these
# tests were written, killed after.


async def test_close_all_picks_up_a_session_registered_while_it_was_running(
    settings: Settings,
) -> None:
    # M4. `create()`'s reconcile inserts into `_sessions` WITHOUT taking
    # `_lock` (deliberately -- see the module docstring), so a create() whose
    # open() was in flight when close_all() started can register its session
    # while close_all() is parked inside some other session's close(). The
    # loop therefore re-reads `_sessions` every iteration instead of
    # snapshotting it once; a snapshot leaves that session open and
    # registered at shutdown, which is exactly the orphan this round set out
    # to prevent.
    entered_close = asyncio.Event()
    release_close = asyncio.Event()
    entered_open = asyncio.Event()
    release_open = asyncio.Event()

    class GatedCloseSession(FakeSession):
        async def close(self) -> None:
            entered_close.set()
            await release_close.wait()
            self.closed = True

    class SlowOpenSession(FakeSession):
        async def open(self) -> None:
            entered_open.set()
            await release_open.wait()
            self.opened = True

    made: list[FakeSession] = [GatedCloseSession(), SlowOpenSession()]
    reg = _registry_of(settings, made)
    await reg.create(RunOptions(), None)

    creating = asyncio.create_task(reg.create(RunOptions(), None))
    await asyncio.wait_for(entered_open.wait(), timeout=1.0)

    sweeping = asyncio.create_task(reg.close_all())
    await asyncio.wait_for(entered_close.wait(), timeout=1.0)

    # The late session lands in `_sessions` while close_all() is suspended
    # inside the first session's close().
    release_open.set()
    sid_late = await asyncio.wait_for(creating, timeout=1.0)
    assert reg.get(sid_late) is made[1]

    release_close.set()
    await asyncio.wait_for(sweeping, timeout=1.0)

    assert made[1].closed is True, "close_all() missed a late-registered session"
    assert reg.list() == []


async def test_close_all_logs_a_summary_naming_the_sessions_it_could_not_close(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # M5. The docstring makes this summary load-bearing: it is what carries
    # the "not known to have closed cleanly" list into the log, since nothing
    # calls list() after shutdown. Per-session `_log.exception` records are
    # not a substitute -- they say a close failed, not what survived the sweep.
    made: list[FakeSession] = [
        RaisingCloseSession(fail_times=99),
        RaisingCloseSession(fail_times=99),
        FakeSession(),
    ]
    settings.max_sessions = 3
    reg = _registry_of(settings, made)
    sids = [await reg.create(RunOptions(), None) for _ in range(3)]

    with caplog.at_level(logging.ERROR, logger="agent_service.registry"):
        await asyncio.wait_for(reg.close_all(), timeout=1.0)

    summaries = [
        r.getMessage()
        for r in caplog.records
        if "still registered" in r.getMessage()
    ]
    assert len(summaries) == 1, caplog.text
    assert sids[0] in summaries[0] and sids[1] in summaries[0]
    assert sids[2] not in summaries[0]  # that one actually closed


async def test_the_close_all_summary_counts_failures_out_of_attempts(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # M6. "2 of 3" and "2 of 2" are both true statements about a number; only
    # the first says how much of the shutdown succeeded, which is the whole
    # reason the line exists.
    made: list[FakeSession] = [
        RaisingCloseSession(fail_times=99),
        RaisingCloseSession(fail_times=99),
        FakeSession(),
    ]
    settings.max_sessions = 3
    reg = _registry_of(settings, made)
    for _ in range(3):
        await reg.create(RunOptions(), None)

    with caplog.at_level(logging.ERROR, logger="agent_service.registry"):
        await asyncio.wait_for(reg.close_all(), timeout=1.0)

    summary = next(
        r.getMessage() for r in caplog.records if "still registered" in r.getMessage()
    )
    assert "2 of 3 session(s) failed" in summary, summary


# -- follow-up 5, second half: the count has to reach somebody ---------------
#
# reap_once() returning closes rather than attempts is worth nothing while
# the only caller discards it. Measured before this: a background reaper that
# closed two sessions emitted zero log records.


async def test_the_background_reaper_logs_what_it_closed(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    settings.session_reaper_interval_s = 0
    reg, made = make_registry(settings)
    await reg.create(RunOptions(), None)
    made[0].idle = 999.0

    with caplog.at_level(logging.INFO, logger="agent_service.registry"):
        reg.start_reaper()
        try:
            async with asyncio.timeout(2.0):
                while not made[0].closed:
                    await asyncio.sleep(0.01)
                while not any("reaper: closed" in r.getMessage() for r in caplog.records):
                    await asyncio.sleep(0.01)
        finally:
            await reg.stop_reaper()

    said = [r.getMessage() for r in caplog.records if "reaper: closed" in r.getMessage()]
    assert said, caplog.text
    assert "closed 1 idle session(s)" in said[0]


async def test_the_background_reaper_stays_quiet_when_it_closes_nothing(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # The common case is once a minute, forever, with nothing to do. A reaper
    # that narrates that is a reaper whose log nobody reads.
    settings.session_reaper_interval_s = 0
    reg, made = make_registry(settings)
    await reg.create(RunOptions(), None)
    made[0].idle = 1.0  # fresh: nothing to reap

    with caplog.at_level(logging.INFO, logger="agent_service.registry"):
        reg.start_reaper()
        await asyncio.sleep(0.05)  # many ticks at interval 0
        await reg.stop_reaper()

    assert [r.getMessage() for r in caplog.records] == []
    assert made[0].closed is False


# -- Plan 2 follow-up 15: the registry lock is NOT held across close() -------
#
# Every registry operation runs under one asyncio.Lock, and close(),
# close_all() and reap_once() all used to hold it across `await
# session.close()` -- so a session whose close is slow (the measured driver: a
# turn that does not end, giving _finalize_live_turn the whole timeout_s
# deadline, 600s default) stalled create(), the reaper and every other DELETE
# for a session nobody asked about. Measured against the pre-fix code with a
# wedged real AgentSession and a HEALTHY control channel: at the default
# timeout_s=600 both reap_once and create were still blocked at a 5s probe
# bound; at timeout_s=4 reap_once took 3.938s and the DELETE 4.001s.
#
# The fix: close FIRST, then remove only on success (the other obvious shape
# -- unregister first, then close -- silently reverts follow-up 3's "no
# deregistration while the subprocess is still connected"). The caller who
# asked for the close still waits the full close; nobody else does.


class GatedCloseSession(FakeSession):
    """close() parks on `proceed` so a test can hold a teardown in flight.

    `entered` fires on every call; `calls` counts them, so a test can wait for
    a SECOND caller to reach close() concurrently -- something the pre-fix
    lock made impossible.
    """

    def __init__(self, entered: asyncio.Event, proceed: asyncio.Event) -> None:
        super().__init__()
        self._entered = entered
        self._proceed = proceed
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self._entered.set()
        await self._proceed.wait()
        self.closed = True


async def test_a_slow_close_does_not_block_reap_once_on_other_sessions(
    settings: Settings,
) -> None:
    """No teardown path may hold `_lock` across `await session.close()`.

    Holding it was justified by "disconnect() is measured (S5) to be fast at a
    clean boundary" -- but `AgentSession.close()` is bounded by `timeout_s`,
    NOT by `disconnect()`. A turn that does not end gives its retry loop the
    whole deadline (600s default, 1800s cap) and the registry waited with it.

    Measured with a wedged real session and a HEALTHY control channel: at the
    default `timeout_s=600`, `reap_once` and `create` were both still blocked
    at a 5s probe bound while one DELETE's close was in flight; at
    `timeout_s=4`, `reap_once` took 3.938s. Post-change, the same probes:
    `reap_once` 0.000s, `create` 0.000s -- while the DELETE still waits its own
    full close, which is correct. The caller who asked for the close waits;
    nobody else does.
    """
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed), FakeSession()]
    reg = _registry_of(settings, made)
    sid_a = await reg.create(RunOptions(), None)  # slow close
    sid_b = await reg.create(RunOptions(), None)  # stale, reap fodder
    made[1].idle = 999.0

    deleting = asyncio.create_task(reg.close(sid_a))
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    # A's close is in flight. A reap tick touching only B must complete
    # promptly -- pre-fix, this hung until proceed.set() (i.e. up to the
    # slow session's whole timeout_s deadline, 600s at the default).
    reaped = await asyncio.wait_for(reg.reap_once(), timeout=1.0)
    assert reaped == 1
    assert made[1].closed is True
    with pytest.raises(SessionNotFound):
        reg.get(sid_b)
    # A is still registered: its close has not succeeded yet.
    assert reg.get(sid_a) is made[0]

    proceed.set()
    await asyncio.wait_for(deleting, timeout=1.0)
    with pytest.raises(SessionNotFound):
        reg.get(sid_a)


async def test_a_slow_close_does_not_block_create(settings: Settings) -> None:
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed), FakeSession()]
    reg = _registry_of(settings, made)
    sid_a = await reg.create(RunOptions(), None)

    deleting = asyncio.create_task(reg.close(sid_a))
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    # A still counts against the cap while its close is in flight
    # (max_sessions=2, so this create takes the second slot), but the create
    # itself must not wait for A's close.
    sid_new = await asyncio.wait_for(reg.create(RunOptions(), None), timeout=1.0)
    assert reg.get(sid_new) is made[1]

    proceed.set()
    await asyncio.wait_for(deleting, timeout=1.0)


async def test_a_slow_close_does_not_block_delete_of_other_sessions(
    settings: Settings,
) -> None:
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed), FakeSession()]
    reg = _registry_of(settings, made)
    sid_a = await reg.create(RunOptions(), None)
    sid_b = await reg.create(RunOptions(), None)

    deleting_a = asyncio.create_task(reg.close(sid_a))
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    # DELETE on B must not queue behind A's in-flight close.
    await asyncio.wait_for(reg.close(sid_b), timeout=1.0)
    assert made[1].closed is True

    proceed.set()
    await asyncio.wait_for(deleting_a, timeout=1.0)


async def test_a_slow_reap_close_does_not_block_a_delete(
    settings: Settings,
) -> None:
    # Same stall, driven from the other side: the REAPER is parked inside a
    # slow close, and an explicit DELETE of another session must not wait.
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed), FakeSession()]
    reg = _registry_of(settings, made)
    await reg.create(RunOptions(), None)
    sid_b = await reg.create(RunOptions(), None)
    made[0].idle = 999.0  # only A is stale

    reaping = asyncio.create_task(reg.reap_once())
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    await asyncio.wait_for(reg.close(sid_b), timeout=1.0)
    assert made[1].closed is True

    proceed.set()
    assert await asyncio.wait_for(reaping, timeout=1.0) == 1


async def test_the_delete_caller_itself_still_waits_for_the_close(
    settings: Settings,
) -> None:
    # The point of the fix is WHO waits, not whether anyone does: the caller
    # who asked for the close waits the full close -- that is correct -- and
    # the session stays registered until the close has actually succeeded.
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed)]
    reg = _registry_of(settings, made)
    sid = await reg.create(RunOptions(), None)

    deleting = asyncio.create_task(reg.close(sid))
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    await asyncio.sleep(0.05)

    assert deleting.done() is False  # still waiting on the close
    assert reg.get(sid) is made[0]  # and no early deregistration

    proceed.set()
    await asyncio.wait_for(deleting, timeout=1.0)
    with pytest.raises(SessionNotFound):
        reg.get(sid)


async def test_a_concurrent_delete_and_reap_claim_one_teardown_between_them(
    settings: Settings,
) -> None:
    """The counting hazard created by running the closes unlocked.

    A DELETE and a reap tick can now both be inside the SAME session's
    `close()` at once, and both then reach their pop. `AgentSession.close()`
    tolerates that -- the second caller queues on the session's own lock and
    returns once it sees `status == "closed"` -- but counting on the close
    alone reports one deregistration twice. Measured with that shape:
    `reap_once returned=1, DELETE=204, close_calls=2` for a SINGLE
    deregistration.

    The guard is to count only a pop that ACTUALLY removed something, which is
    why removal is `pop(sid, None)` on every teardown path rather than `del`.
    """
    #
    # The DELETE enters close() FIRST, so it wakes first (Event waiters are
    # FIFO) and pops first; the reap's pop then finds nothing and must not
    # count it.
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed)]
    reg = _registry_of(settings, made)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0

    deleting = asyncio.create_task(reg.close(sid))
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    reaping = asyncio.create_task(reg.reap_once())

    async def both_inside_close() -> None:
        while made[0].close_calls < 2:
            await asyncio.sleep(0.001)

    # Pre-fix this hangs: the reap cannot even reach the session's close()
    # while the DELETE holds the registry lock across it.
    await asyncio.wait_for(both_inside_close(), timeout=1.0)

    proceed.set()
    await asyncio.wait_for(deleting, timeout=1.0)  # the DELETE claims it
    reaped = await asyncio.wait_for(reaping, timeout=1.0)

    assert reaped == 0  # one teardown, already claimed by the DELETE
    assert reg.list() == []
    assert made[0].closed is True


async def test_a_concurrent_reap_and_delete_where_the_reap_wins(
    settings: Settings,
) -> None:
    # Mirror image: the REAP enters the close first and pops first. The
    # DELETE's own close() call still succeeded, so it reports success (its
    # pop simply finds nothing) rather than blowing up on a session the reap
    # already deregistered.
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed)]
    reg = _registry_of(settings, made)
    sid = await reg.create(RunOptions(), None)
    made[0].idle = 999.0

    reaping = asyncio.create_task(reg.reap_once())
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    deleting = asyncio.create_task(reg.close(sid))

    async def both_inside_close() -> None:
        while made[0].close_calls < 2:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(both_inside_close(), timeout=1.0)

    proceed.set()
    assert await asyncio.wait_for(reaping, timeout=1.0) == 1  # the reap claims it
    await asyncio.wait_for(deleting, timeout=1.0)  # and the DELETE does not raise

    assert reg.list() == []


async def test_reap_once_skips_a_session_that_started_running_mid_sweep(
    settings: Settings,
) -> None:
    # The stale scan happens before the sweep's first await; once closes run
    # unlocked, a turn can start on a later stale session while the sweep is
    # parked inside an earlier one's close(). "reap_once() skips running
    # sessions" has to hold at close time, not just at scan time.
    entered, proceed = asyncio.Event(), asyncio.Event()
    made: list[FakeSession] = [GatedCloseSession(entered, proceed), FakeSession()]
    reg = _registry_of(settings, made)
    await reg.create(RunOptions(), None)
    sid_b = await reg.create(RunOptions(), None)
    for s in made:
        s.idle = 999.0

    reaping = asyncio.create_task(reg.reap_once())
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    # B starts a turn while the sweep is stuck inside A's close.
    made[1].status = "running"
    proceed.set()

    assert await asyncio.wait_for(reaping, timeout=1.0) == 1
    assert made[1].closed is False  # skipped: it was running at close time
    assert reg.get(sid_b) is made[1]


async def test_reserved_settles_to_zero_across_concurrent_mixed_outcomes(
    settings: Settings,
) -> None:
    # `_reserved` must never go negative and must never be double-decremented
    # for one reservation. Runs a batch of concurrent create() calls with
    # mixed outcomes (success, a failing open(), and cap rejections) and
    # checks the counter settles to exactly 0 -- not just "eventually looks
    # fine", but consistent with exactly one decrement per reservation.
    calls = {"n": 0}

    class MaybeFailingSession(FakeSession):
        def __init__(self, should_fail: bool) -> None:
            super().__init__()
            self._should_fail = should_fail

        async def open(self) -> None:
            await asyncio.sleep(0)  # a real suspension point, so this is a
            # genuine race across the concurrent attempts, not an accident
            # of scheduling.
            if self._should_fail:
                raise RuntimeError("boom")
            self.opened = True

    def factory(options, settings, title=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        return MaybeFailingSession(should_fail=(calls["n"] % 2 == 0))

    reg = SessionRegistry(settings, session_factory=factory)  # max_sessions=2

    async def attempt() -> str | None:
        try:
            return await reg.create(RunOptions(), None)
        except (SessionLimitReached, RuntimeError):
            return None

    results = await asyncio.gather(*(attempt() for _ in range(6)))

    assert reg._reserved == 0
    successes = [r for r in results if r is not None]
    assert len(successes) == len(reg.list())


# -- Plan 4 follow-up: close_all() needs an AGGREGATE bound ------------------
#
# Reproduced against 2638616 with N sessions whose close() is slow, modelling
# the cost the container measured for a session wedged mid-turn (5.4-5.9s):
#
#   n=0        -> 0.000s      n=8 x 0.5s -> 4.043s
#   n=1 x 0.5s -> 0.506s      n=8 x 2.0s -> 16.085s
#   n=3 x 0.5s -> 1.523s      n=8 x 5.9s -> 47.255s
#
# Exactly N x per-session cost, with nothing capping the total. The real worst
# case is far worse: `AgentSession.close()` is bounded by its own `timeout_s`
# (600s default, 1800s cap), so max_sessions x 600s = 80 MINUTES of shutdown
# against a compose stop_grace_period of 90s. Docker SIGKILLs long before
# that -- ExitCode 137 with the CLI subprocess still alive, measured in Task 4 --
# which is precisely the leaked-subprocess outcome close_all() exists to
# prevent. A grace period can only be justified against a bound the code
# actually enforces.


class HangingCloseSession(FakeSession):
    """close() never returns -- a session wedged for its whole `timeout_s`."""

    def __init__(self) -> None:
        super().__init__()
        self.close_entered = 0
        self.entered = asyncio.Event()

    async def close(self) -> None:
        self.close_entered += 1
        self.entered.set()
        await asyncio.Event().wait()  # forever
        self.closed = True  # unreachable by construction


class KillableHangingSession(HangingCloseSession):
    """...but its subprocess can still be killed. Mirrors AgentSession.kill(),
    which disconnects without waiting on the turn or on the session lock."""

    def __init__(self) -> None:
        super().__init__()
        self.killed = False

    async def kill(self) -> None:
        self.killed = True


async def test_close_all_is_bounded_in_aggregate_however_many_sessions(
    settings: Settings,
) -> None:
    """THE bound. Eight sessions that never close, ONE budget for all of them.

    A per-session bound does not satisfy this and never did -- `timeout_s`
    already is one, and N x it is the defect. The assertion is on the TOTAL,
    with every session still attempted.
    """
    settings.max_sessions = 8
    settings.shutdown_budget_s = 1.0
    made: list[FakeSession] = [HangingCloseSession() for _ in range(8)]
    reg = _registry_of(settings, made)
    for _ in range(8):
        await reg.create(RunOptions(), None)

    started = time.monotonic()
    await asyncio.wait_for(reg.close_all(), timeout=30.0)
    elapsed = time.monotonic() - started

    assert elapsed <= settings.shutdown_budget_s * 1.5, f"overran: {elapsed:.3f}s"
    # ...and it genuinely SPENT the budget trying rather than bailing at the
    # first session that did not answer. A bound that gives up immediately is
    # bounded and useless.
    assert elapsed >= settings.shutdown_budget_s * 0.5, f"gave up early: {elapsed:.3f}s"
    assert all(s.close_entered == 1 for s in made), "not every session was attempted"


async def test_close_all_still_closes_the_healthy_sessions_when_one_is_wedged(
    settings: Settings,
) -> None:
    # Best effort WITHIN the budget. The wedged session is created last, so
    # the LIFO sweep hits it FIRST: bailing out there -- or handing it the
    # whole budget -- costs the three healthy sessions their clean teardown.
    settings.max_sessions = 4
    settings.shutdown_budget_s = 1.0
    fast: list[FakeSession] = [FakeSession(), FakeSession(), FakeSession()]
    made: list[FakeSession] = [*fast, HangingCloseSession()]
    reg = _registry_of(settings, made)
    sids = [await reg.create(RunOptions(), None) for _ in range(4)]

    await asyncio.wait_for(reg.close_all(), timeout=30.0)

    assert all(s.closed for s in fast), "a wedged session cost the healthy ones"
    assert [sid for sid, _ in reg.list()] == [sids[3]]


async def test_close_all_kills_a_session_it_could_not_close_within_the_budget(
    settings: Settings,
) -> None:
    # The alternative to killing is a subprocess that outlives the container --
    # the exact failure the exec-form CMD, the lifespan and close_all() all
    # exist to prevent. A kill is NOT a clean close, so the session stays
    # registered and the summary names it as killed rather than as closed.
    settings.shutdown_budget_s = 1.0
    made: list[FakeSession] = [KillableHangingSession()]
    reg = _registry_of(settings, made)
    sid = await reg.create(RunOptions(), None)

    await asyncio.wait_for(reg.close_all(), timeout=30.0)

    assert made[0].killed is True, "left the subprocess running"
    assert [s for s, _ in reg.list()] == [sid]


async def test_close_all_does_not_start_a_teardown_it_cannot_wait_for(
    settings: Settings,
) -> None:
    """Once the clean budget is gone, the sweep must STOP closing, not close
    with a zero-length wait.

    Found by mutation: deleting the loop's `remaining <= 0` check survived the
    whole suite, because a negative fair share still "bounds" each attempt --
    `asyncio.wait()` just returns immediately. The total stays bounded either
    way, so the bound tests cannot see it. What it costs is real, though:
    entering `AgentSession.close()` latches `_closing` before its first await
    and starts a teardown nobody is left to wait for, when the honest move is
    to go straight to the kill.

    Deterministic, not timing-sensitive: A is the only session when the sweep
    starts, so it is handed the WHOLE clean window as its fair share and
    consumes all of it. B registers (an in-flight create(), which inserts
    without the lock) while the sweep is parked in A, so it is picked up by
    the next scan with provably nothing left.
    """
    settings.max_sessions = 2
    settings.shutdown_budget_s = 0.5
    made: list[FakeSession] = [KillableHangingSession(), KillableHangingSession()]
    reg = _registry_of(settings, made)
    a, b = made[0], made[1]
    await reg.create(RunOptions(), None)

    sweeping = asyncio.create_task(reg.close_all())
    await asyncio.wait_for(a.entered.wait(), timeout=1.0)
    await reg.create(RunOptions(), None)  # B lands mid-sweep

    await asyncio.wait_for(sweeping, timeout=5.0)

    assert a.close_entered == 1
    assert b.close_entered == 0, "started a teardown it had no time to wait for"
    # ...and B is not simply forgotten: the kill reserve is what it is for.
    assert a.killed is True and b.killed is True


async def test_the_shutdown_budget_is_configurable(settings: Settings) -> None:
    # Kills a hardcoded bound: the number has to come from Settings, because
    # compose.yaml's stop_grace_period is derived from it.
    async def sweep(budget: float) -> float:
        settings.max_sessions = 2
        settings.shutdown_budget_s = budget
        reg = _registry_of(settings, [HangingCloseSession(), HangingCloseSession()])
        for _ in range(2):
            await reg.create(RunOptions(), None)
        started = time.monotonic()
        await asyncio.wait_for(reg.close_all(), timeout=30.0)
        return time.monotonic() - started

    small = await sweep(0.4)
    large = await sweep(1.6)
    assert small <= 0.4 * 1.5, small
    assert large <= 1.6 * 1.5, large
    assert large > small * 2, (small, large)


async def test_close_all_with_nothing_to_close_does_not_spend_the_budget(
    settings: Settings,
) -> None:
    # The common case, and the one Task 4 measured at 0.046 ms. A deadline is
    # not a sleep.
    settings.shutdown_budget_s = 5.0
    reg, _ = make_registry(settings)
    started = time.monotonic()
    await reg.close_all()
    assert time.monotonic() - started < 0.5


async def test_close_all_says_what_it_closed_killed_and_could_not(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # Task 4: on success close_all() logged NOTHING, so an operator reading a
    # container's shutdown could not tell a clean sweep from one that never
    # ran. One line, every outcome, and whether the budget was hit.
    settings.max_sessions = 3
    settings.shutdown_budget_s = 1.0
    made: list[FakeSession] = [
        FakeSession(),
        KillableHangingSession(),
        RaisingCloseSession(fail_times=99),
    ]
    reg = _registry_of(settings, made)
    for _ in range(3):
        await reg.create(RunOptions(), None)

    with caplog.at_level(logging.INFO, logger="agent_service.registry"):
        await asyncio.wait_for(reg.close_all(), timeout=30.0)

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("close_all: swept")
    ]
    assert len(lines) == 1, caplog.text
    assert "3 session(s)" in lines[0]
    assert "1 closed cleanly" in lines[0]
    assert "1 killed" in lines[0]
    assert "shutdown budget hit" in lines[0]
    assert "1.0s budget" in lines[0]


async def test_close_all_reports_a_clean_sweep_too(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    reg, made = make_registry(settings)
    await reg.create(RunOptions(), None)
    await reg.create(RunOptions(), None)

    with caplog.at_level(logging.INFO, logger="agent_service.registry"):
        await reg.close_all()

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("close_all: swept")
    ]
    assert len(lines) == 1, caplog.text
    assert "2 closed cleanly" in lines[0]
    assert "shutdown budget hit" not in lines[0]


class VanishingCloseSession(FakeSession):
    """Its close() fails AND the session is deregistered mid-sweep.

    Stands in for the one race that reaches `_kill_all`'s missing-session
    branch: a DELETE lands while close_all() is sweeping, its own close()
    returns and pops the session, and by the time the kill phase looks the sid
    up there is nothing there.
    """

    def __init__(self) -> None:
        super().__init__()
        self.registry: SessionRegistry | None = None
        self.sid: str | None = None

    async def close(self) -> None:
        assert self.registry is not None and self.sid is not None
        self.registry._sessions.pop(self.sid, None)
        raise RuntimeError("disconnect blew up")


async def test_the_shutdown_summary_accounts_for_every_session_it_swept(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """`swept N` must equal `closed + killed + neither`. Always.

    `_kill_all` used to `continue` past a sid whose session had been popped
    concurrently, putting it in NEITHER returned list -- while `close_all()`
    still counted it in `swept`. The arithmetic of the one line billed as
    "says what it did, always" therefore did not add up on exactly the path
    where an operator most needs it to.
    """
    settings.max_sessions = 3
    settings.shutdown_budget_s = 1.0
    made: list[FakeSession] = [
        FakeSession(),
        KillableHangingSession(),
        VanishingCloseSession(),
    ]
    reg = _registry_of(settings, made)
    sids = [await reg.create(RunOptions(), None) for _ in range(3)]
    made[2].registry, made[2].sid = reg, sids[2]

    with caplog.at_level(logging.INFO, logger="agent_service.registry"):
        await asyncio.wait_for(reg.close_all(), timeout=30.0)

    line = next(
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("close_all: swept")
    )
    swept, closed, killed, neither = (
        int(n) for n in re.findall(r"(\d+) (?:session|closed|killed|neither)", line)
    )
    assert swept == closed + killed + neither, line
    assert (swept, closed, killed, neither) == (3, 1, 1, 1)
