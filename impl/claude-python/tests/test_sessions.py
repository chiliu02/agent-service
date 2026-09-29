import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from agent_service.config import Settings
from agent_service.errors import RunTimeout
from agent_spec.openapi.schemas import RunOptions
from agent_service.sessions import (
    _STALE_INTERRUPT_BUDGET_S,
    AgentSession,
    InterruptTimeout,
    SessionBusy,
    SessionClosed,
)


class FakeClient:
    """Stands in for ClaudeSDKClient. Records calls; replays canned turns."""

    def __init__(self, turns: list[list[object]] | None = None) -> None:
        self.turns = turns or []
        self.connected = False
        self.disconnected = False
        # A COUNT, not just the flag: idempotence ("a second teardown must not
        # push a second disconnect at the SDK") is invisible to a boolean that
        # is already True.
        self.disconnects = 0
        self.queries: list[str] = []
        self.interrupts = 0
        self.model: str | None = None
        self.permission_mode: str | None = None
        self._turn_index = 0

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.disconnected = True

    async def query(self, prompt, session_id="default"):  # noqa: ANN001, ARG002
        self.queries.append(prompt)

    async def receive_response(self):
        turn = self.turns[self._turn_index]
        self._turn_index += 1
        for msg in turn:
            yield msg

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def set_model(self, model=None) -> None:  # noqa: ANN001
        self.model = model

    async def set_permission_mode(self, mode) -> None:  # noqa: ANN001
        self.permission_mode = mode

    async def get_context_usage(self):
        return {"categories": [{"name": "Messages", "tokens": 7}]}


def _result(**kw) -> ResultMessage:
    base = dict(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=False,
        num_turns=1,
        session_id="sdk-sess-1",
        terminal_reason="completed",
        total_cost_usd=0.05,
        result="done",
    )
    base.update(kw)
    return ResultMessage(**base)


def _normal_turn() -> list[object]:
    return [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="hello")], model="claude-sonnet-5"),
        _result(),
    ]


def _unpriced_turn() -> list[object]:
    """The measured gateway shape (probe C2): a SUCCESSFUL turn the SDK
    attributed nothing to -- zero price, every token count zero, no model."""
    return [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        _result(
            total_cost_usd=0,
            usage={
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
            },
            model_usage={},
        ),
    ]


def _interrupted_turn() -> list[object]:
    # Measured shape (spike S2): an interrupt looks exactly like a failure.
    return [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        _result(
            subtype="error_during_execution",
            is_error=True,
            terminal_reason="aborted_streaming",
            result=None,
        ),
    ]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_dir=tmp_path / "ws")


def make_session(settings: Settings, client: FakeClient) -> AgentSession:
    return AgentSession(RunOptions(), settings, client_factory=lambda _opts: client)


async def _until(
    predicate: Callable[[], bool], *, what: str, timeout: float = 5.0
) -> None:
    """Yield to the loop until `predicate()` holds. **Never a fixed sleep.**

    `await asyncio.sleep(0.005)` is not synchronisation: it is a bet that some
    other task reaches a particular point within five milliseconds. The bet is
    usually safe on an idle machine and is exactly what breaks under load --
    and it breaks by failing an assertion about the state, so it reads as a
    defect in the code under test rather than as a slow machine.

    That is not hypothetical here. `test_close_is_bounded_when_a_turn_is_
    abandoned_after_an_advance` set the turn's own bound to 50ms and then spent
    two 5ms sleeps setting up; one CI run -- with Docker builds and two other
    suites on the same machine -- overshot it, the turn expired before the
    first assertion, and the failure was `assert 'idle' == 'running'`.

    `timeout` is a ceiling for a test that will never finish, not a schedule.
    Reaching it is an assertion failure naming what was awaited, because a bare
    hang tells the reader nothing.
    """
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        # A real yield rather than sleep(0): the task being waited for is often
        # blocked on a timer, and spinning on sleep(0) starves the loop.
        await asyncio.sleep(0.001)


async def test_open_connects_the_client(settings: Settings) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    assert client.connected is True
    assert session.status == "idle"


async def test_send_drains_one_turn_and_records_outcome(settings: Settings) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    events = [e async for e in session.send("hi")]
    assert [e["type"] for e in events] == ["system", "assistant", "result"]
    assert session.last_turn.outcome.result == "done"
    assert session.last_turn.interrupted is False
    assert session.session_id == "sdk-sess-1"
    assert session.turns == 1
    assert session.total_cost_usd == pytest.approx(0.05)


async def test_session_id_survives_a_second_init(settings: Settings) -> None:
    # Measured (spike S1/S3): SystemMessage(init) arrives on EVERY turn.
    client = FakeClient([_normal_turn(), _normal_turn()])
    session = make_session(settings, client)
    await session.open()
    [e async for e in session.send("one")]
    first = session.session_id
    [e async for e in session.send("two")]
    assert session.session_id == first
    assert session.turns == 2


async def test_total_cost_usd_tracks_the_latest_cumulative_value(settings: Settings) -> None:
    """ASSIGN the latest value, never sum -- summing double-counts every turn.

    Measured (spike S6): `ResultMessage.total_cost_usd` is cumulative for the
    whole CONNECTION, not per-turn. Three real turns on one client came back
    0.0926565, 0.100344, 0.10803255 -- monotonically non-decreasing, with small
    deltas that are exactly what a cache-warm follow-up costs on top of a
    running total.

    `AgentSession` originally summed, on the untested assumption carried over
    from the one-shot `Run` (where there is only ever one `ResultMessage`, so
    summing and assigning are indistinguishable). Code review caught it before
    any caller shipped. The per-turn figure is a SEPARATE field, differenced in
    `_record_turn` -- see
    `test_the_delta_is_taken_before_the_running_total_is_updated`.
    """
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.05)
    turn_two = _normal_turn()
    turn_two[-1] = _result(total_cost_usd=0.08)

    client = FakeClient([turn_one, turn_two])
    session = make_session(settings, client)
    await session.open()
    [e async for e in session.send("one")]
    assert session.total_cost_usd == pytest.approx(0.05)
    [e async for e in session.send("two")]
    assert session.total_cost_usd == pytest.approx(0.08)


async def test_interrupt_labels_the_turn_rather_than_reporting_a_crash(
    settings: Settings,
) -> None:
    # Realistic ordering (fix-round Finding 1): a turn is already draining
    # when interrupt() is called -- there is nothing to interrupt beforehand.
    # A slow client gated on events lets interrupt() land mid-drain, exactly
    # like the real concurrent caller this module exists to serialize.
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            started.set()
            await release.wait()
            for msg in _interrupted_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    async def run_turn() -> list[dict]:
        return [e async for e in session.send("count to a million")]

    task = asyncio.create_task(run_turn())
    await started.wait()
    await session.interrupt()
    release.set()
    await task

    assert client.interrupts == 1
    assert session.last_turn.interrupted is True
    # is_error stays true -- we do not rewrite what the SDK reported ...
    assert session.last_turn.outcome.is_error is True
    # ... the flag is what tells a caller it was deliberate.


async def test_an_aborted_turn_we_did_not_request_is_not_labelled_interrupted(
    settings: Settings,
) -> None:
    client = FakeClient([_interrupted_turn()])
    session = make_session(settings, client)
    await session.open()
    [e async for e in session.send("something")]
    assert session.last_turn.interrupted is False


async def test_interrupt_flag_does_not_leak_into_the_next_turn(
    settings: Settings,
) -> None:
    # Fix-round Finding 1: the interrupt flag must be scoped to the turn it
    # was raised against. Turn 1 is genuinely interrupted mid-drain; turn 2
    # independently ends up aborted-shaped too (an unrelated failure, not an
    # interrupt) -- without the fix, turn 1's flag survives and mislabels
    # turn 2 as interrupted even though nobody called interrupt() for it.
    started = asyncio.Event()
    release = asyncio.Event()

    class GatedClient(FakeClient):
        def __init__(self, turns: list[list[object]]) -> None:
            super().__init__(turns)
            self._calls = 0

        async def receive_response(self):
            self._calls += 1
            if self._calls == 1:
                started.set()
                await release.wait()
            turn = self.turns[self._turn_index]
            self._turn_index += 1
            for msg in turn:
                yield msg

    client = GatedClient([_interrupted_turn(), _interrupted_turn()])
    session = make_session(settings, client)
    await session.open()

    async def run_turn_one() -> list[dict]:
        return [e async for e in session.send("one")]

    task = asyncio.create_task(run_turn_one())
    await started.wait()
    await session.interrupt()
    release.set()
    await task
    assert session.last_turn.interrupted is True  # sanity check on turn 1

    [e async for e in session.send("two")]
    assert session.last_turn.interrupted is False


async def test_last_turn_is_not_stale_after_a_failed_drain(settings: Settings) -> None:
    # Fix round 1, Finding 3: if receive_response() raises partway, the
    # postscript that would normally set last_turn never runs. Without a
    # fix, last_turn is left pointing at the PREVIOUS successful turn --
    # indistinguishable from a stale success for a turn that never finished.
    class FlakyClient(FakeClient):
        def __init__(self, turns: list[list[object]]) -> None:
            super().__init__(turns)
            self._calls = 0

        async def receive_response(self):
            self._calls += 1
            if self._calls == 1:
                for msg in self.turns[0]:
                    yield msg
                return
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
            raise RuntimeError("boom mid-drain")

    client = FlakyClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    [e async for e in session.send("one")]
    assert session.last_turn.outcome.result == "done"  # sanity: turn 1 succeeded

    with pytest.raises(RuntimeError, match="boom mid-drain"):
        [e async for e in session.send("two")]

    assert session.last_turn.outcome is None
    assert session.status == "idle"


async def test_interrupt_flag_does_not_survive_a_failed_drain(
    settings: Settings,
) -> None:
    # Fix round 2, Finding A. Round 1 moved the read/clear of the interrupt
    # flag into the postscript AFTER the drain -- correct for a turn that
    # completes normally, but `raise` skips a postscript. So an interrupt
    # that lands mid-drain on a turn that then dies (the interrupt-then-
    # client-disconnect path: the disconnect cancels the drain) leaves the
    # flag set, and the NEXT turn -- which nobody interrupted -- gets
    # labelled interrupted the moment it comes back aborted-shaped for its
    # own reasons. Same original defect, different trigger.
    started = asyncio.Event()
    release = asyncio.Event()

    class InterruptedThenCrashingClient(FakeClient):
        def __init__(self, turns: list[list[object]]) -> None:
            super().__init__(turns)
            self._calls = 0

        async def receive_response(self):
            self._calls += 1
            if self._calls == 1:
                yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
                started.set()
                await release.wait()
                raise RuntimeError("drain died after the interrupt")
            for msg in self.turns[0]:
                yield msg

    client = InterruptedThenCrashingClient([_interrupted_turn()])
    session = make_session(settings, client)
    await session.open()

    async def turn_one() -> None:
        [e async for e in session.send("one")]

    task = asyncio.create_task(turn_one())
    await started.wait()
    await session.interrupt()  # lands mid-drain, on the turn that is running
    release.set()
    with pytest.raises(RuntimeError, match="drain died after the interrupt"):
        await task

    # Turn 2: nobody interrupted it. It happens to come back aborted-shaped
    # (measured S2 shape) for reasons of its own -- that must NOT be read as
    # a deliberate stop just because turn 1's flag was never cleared.
    [e async for e in session.send("two")]
    assert session.last_turn.interrupted is False


async def test_interrupt_with_no_turn_running_is_a_no_op(settings: Settings) -> None:
    # Fix round 2, Finding A (second half). There is nothing to interrupt when
    # no turn is running: asking the SDK to stop is meaningless, and arming a
    # flag can only mislabel some later, unrelated turn that ends aborted-
    # shaped. So the call is a no-op rather than an error -- "the turn just
    # finished" is an inherent race that a caller cannot avoid, and punishing
    # it with an exception would be worse than doing nothing.
    client = FakeClient([_interrupted_turn()])
    session = make_session(settings, client)
    await session.open()

    await session.interrupt()
    assert client.interrupts == 0  # the SDK is not asked to stop nothing

    [e async for e in session.send("something")]
    assert session.last_turn.interrupted is False


class SharedStreamClient(FakeClient):
    """Models the SDK's REAL message plumbing, not a per-turn stream.

    `Query.__init__` creates exactly ONE `anyio.create_memory_object_stream`
    for the whole connection (query.py:138) and every `receive_response()`
    call re-wraps that same stream (client.py:571-610, via
    `receive_messages()` -> `Query.receive_messages()`). So messages a turn
    produced but nobody consumed stay queued for whatever reads next.
    """

    def __init__(self, turns: list[list[object]]) -> None:
        super().__init__(turns)
        send, receive = anyio.create_memory_object_stream(max_buffer_size=100)
        self._send = send
        self.receive = receive
        # ClaudeSDKClient._query is a Query, which holds _message_receive.
        self._query = SimpleNamespace(_message_receive=receive)

    async def query(self, prompt, session_id="default"):  # noqa: ANN001, ARG002
        # The CLI produces this turn's messages onto the shared stream.
        self.queries.append(prompt)
        for msg in self.turns[self._turn_index]:
            self._send.send_nowait(msg)
        self._turn_index += 1

    async def receive_response(self):
        while True:
            msg = self.receive.receive_nowait()
            yield msg
            if isinstance(msg, ResultMessage):
                return


async def test_a_turn_does_not_absorb_the_previous_turns_residue(
    settings: Settings,
) -> None:
    """One caller's turn must never be reported as another's.

    `receive_response()` does NOT create a fresh stream per call: there is
    exactly ONE connection-scoped anyio message stream per `Query` (read from
    the SDK source, not inferred). So when turn 1 is abandoned mid-drain -- the
    ordinary SSE disconnect -- its remaining messages, ResultMessage included,
    are still queued when turn 2 starts, and turn 2's drain would read them as
    its own.

    That is the same misattribution the `SessionBusy` lock exists to prevent,
    reached down a different path, which is why `_discard_residue` runs at the
    TOP of every suspect turn -- before `query()` is written, where nothing
    queued can possibly belong to the turn about to start.

    NOTE the limit of this guard: it can only drop what is ALREADY buffered.
    Messages still in flight from the subprocess arrive DURING the next turn's
    drain and are not coverable here -- only telling the SDK to stop covers
    those, which is what `api.py`'s `close_stream()` interrupt is for.
    """
    turn_one = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="one")], model="claude-sonnet-5"),
        _result(result="TURN ONE"),
    ]
    turn_two = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="two")], model="claude-sonnet-5"),
        _result(result="TURN TWO"),
    ]
    client = SharedStreamClient([turn_one, turn_two])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("one")
    await gen.__anext__()  # consume only the init message ...
    await gen.aclose()  # ... then the consumer goes away mid-turn

    assert session.last_turn.outcome is None  # turn 1 ended abnormally
    # Turn 1's assistant message and its ResultMessage are still queued.
    assert client.receive.statistics().current_buffer_used == 2

    events = [e async for e in session.send("two")]

    assert session.last_turn.outcome.result == "TURN TWO"
    assert [e["type"] for e in events] == ["system", "assistant", "result"]
    assert session.last_residue_discarded == 2


async def test_residue_guard_is_inert_when_the_sdk_shape_is_unfamiliar(
    settings: Settings,
) -> None:
    """The residue guard must DEGRADE on an unfamiliar SDK, never raise.

    It reaches through private internals (`client._query`,
    `query._message_receive`, `receive_nowait`) deliberately -- there is no
    public way to see that buffer. A future SDK release may rename or
    restructure any of them, so every step is probed and anything unexpected
    yields `None`, making the guard a no-op.

    This is the trade, stated plainly: a guard that raised `AttributeError` on
    the next turn would be strictly WORSE than the misattribution it defends
    against. Degrading loses the pre-drain; raising loses the session. RECHECK
    ON ANY SDK UPGRADE -- this test passing does not mean the guard still
    WORKS, only that it still fails safely.
    """

    class OpaqueClient(FakeClient):
        def __init__(self, turns: list[list[object]]) -> None:
            super().__init__(turns)
            self._calls = 0

        async def receive_response(self):
            self._calls += 1
            if self._calls == 1:
                yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
                raise RuntimeError("boom")
            for msg in self.turns[0]:
                yield msg

    client = OpaqueClient([_normal_turn()])
    assert not hasattr(client, "_query")
    session = make_session(settings, client)
    await session.open()

    with pytest.raises(RuntimeError, match="boom"):
        [e async for e in session.send("one")]

    [e async for e in session.send("two")]
    assert session.last_turn.outcome.result == "done"
    assert session.last_residue_discarded == 0


async def test_concurrent_send_raises_session_busy(settings: Settings) -> None:
    # Measured (spike S3): the SDK does NOT raise on a concurrent query -- it
    # queues silently and turns can be misattributed. The lock is ours.
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            started.set()
            await release.wait()
            for msg in _normal_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    async def first() -> None:
        [e async for e in session.send("one")]

    task = asyncio.create_task(first())
    await started.wait()
    with pytest.raises(SessionBusy):
        [e async for e in session.send("two")]
    release.set()
    await task


async def test_status_is_running_during_a_turn(settings: Settings) -> None:
    seen: list[str] = []
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    async for _ in session.send("hi"):
        seen.append(session.status)
    assert "running" in seen
    assert session.status == "idle"


async def test_close_disconnects_and_blocks_further_sends(settings: Settings) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    await session.close()
    assert client.disconnected is True
    assert session.status == "closed"
    with pytest.raises(SessionClosed):
        [e async for e in session.send("hi")]


async def test_close_is_idempotent(settings: Settings) -> None:
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    await session.close()
    await session.close()
    assert session.status == "closed"


# -- fix round 1 (Task 5 review), Important 3: DELETE racing a running turn --
#
# registry.py's reaper never force-closes a "running" session, but
# SessionRegistry.close() (driven by an explicit DELETE) has no such guard
# and calls AgentSession.close() unconditionally -- including mid-turn.
# Racing disconnect() against an actively draining turn was never measured.
# Chosen behaviour: close() interrupts the running turn (the ALREADY-measured
# S2 path) and waits for it to actually end before disconnecting, instead of
# tearing the connection down out from under it. The in-flight caller must
# see a normal completed turn (interrupted=True), not a crash.


async def test_close_interrupts_and_waits_for_an_in_flight_turn(
    settings: Settings,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            started.set()
            await release.wait()
            for msg in _interrupted_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    async def run_turn() -> list[dict]:
        return [e async for e in session.send("count to a million")]

    turn_task = asyncio.create_task(run_turn())
    await started.wait()
    assert session.status == "running"

    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0)  # let close() observe "running" and call interrupt()
    assert client.interrupts == 1
    # close() must not have disconnected yet -- it is waiting on the same
    # lock send() holds for the whole turn.
    assert client.disconnected is False

    release.set()  # let the interrupted turn actually finish draining

    # The in-flight caller gets a normal result, not an unhandled exception.
    events = await asyncio.wait_for(turn_task, timeout=1.0)
    assert [e["type"] for e in events] == ["system", "result"]
    assert session.last_turn.interrupted is True

    await asyncio.wait_for(close_task, timeout=1.0)
    assert client.disconnected is True
    assert session.status == "closed"


async def test_close_on_an_idle_session_does_not_call_interrupt(
    settings: Settings,
) -> None:
    # No turn running -- close() must behave exactly as before: no spurious
    # interrupt() call, disconnect happens immediately.
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    await session.close()
    assert client.interrupts == 0
    assert client.disconnected is True


# -- fix round 2 (Task 5 re-review), Important: close() vs an ABANDONED turn -
#
# Round 1's fix correctly handles an ACTIVELY-DRIVEN turn (some task still
# advancing send()'s generator) -- proven by the test above. It does NOT
# handle an ABANDONED one: a caller that advanced send() partway and then
# simply stopped driving it (no aclose(), no cancellation) -- exactly what a
# disconnected SSE consumer (Task 6) leaves behind. Nothing then ever resumes
# the generator, so its `finally` never runs and `self._lock` is never
# released by waiting on it alone: `async with self._lock:` hangs forever.
# Worse, the abandoned generator's own `asyncio.timeout(self._limits.
# timeout_s)` scope is still armed (its `__aexit__` never runs either, since
# the frame never resumes to reach it) -- a dangling `call_at` callback that
# will call `.cancel()` on whichever task originally advanced the generator,
# whenever its deadline arrives, regardless of what that task is doing by
# then. If that task later also happens to be the one awaiting close()'s lock
# (as in a direct, single-task repro), the delivered CancelledError lands in
# close()'s lock-wait instead of the generator -- a BaseException `except
# Exception` cannot catch.


async def test_close_finalizes_an_abandoned_turn_instead_of_hanging(
    settings: Settings,
) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    # Short enough that the abandoned generator's own dangling timeout scope
    # is armed and expiring right around when close() runs below -- this is
    # the exact shape that used to surface as a leaked CancelledError rather
    # than a clean hang, when close() and the abandoned advance share a task.
    session._limits.timeout_s = 0.5

    gen = session.send("hello")
    await gen.__anext__()  # consume exactly one message, then abandon it --
    # no aclose(), no cancellation.
    assert session.status == "running"

    # Must complete well within the wait_for bound, not hang, and must not
    # raise CancelledError (which would propagate straight through
    # wait_for/pytest as an unhandled exception, failing this test).
    await asyncio.wait_for(session.close(), timeout=1.0)

    assert session.status == "closed"
    assert client.disconnected is True
    # Reclaimable: a second close() is still a safe, idempotent no-op.
    await session.close()


# -- fix round 3 (Task 5 re-review), Important: a losing SessionBusy caller --
# -- can silently steal `_active_gen` -----------------------------------------
#
# Round 2's wrapper stashed `_active_gen` EAGERLY, at send() call time, for
# EVERY call -- including one that is about to lose to SessionBusy (that
# check is lazy, inside `_send_impl`, and only fires on first advance). A's
# turn is running (possibly abandoned); a concurrent B correctly gets
# SessionBusy, but as a side effect overwrites `_active_gen` with B's own,
# already-exhausted generator. close() then aclose()s B's spent generator --
# a silent no-op -- believes it finalized the abandoned turn, and falls
# through to `async with self._lock:`, which A's REAL generator still holds
# forever. The exact hang class round 2 exists to eliminate, reintroduced by
# the fix's own bookkeeping -- and potentially worse: if A's task has since
# exited, its dangling timeout's `.cancel()` targets a task that no longer
# exists (a no-op), so nothing ever fires and close() hangs INDEFINITELY,
# not just for up to timeout_s.
#
# Fix: only the turn that actually WINS `self._lock` may ever become
# `_active_gen`. Publish it from inside `_send_impl`, immediately after
# `async with self._lock:` succeeds, instead of from the eager wrapper -- a
# losing call raises SessionBusy before ever reaching that line, so it can
# never touch the stash.


async def test_close_reclaims_the_session_despite_a_losing_send_in_between(
    settings: Settings,
) -> None:
    """The CONSEQUENCE of the eager stash above: close() hangs forever.

    With `_active_gen` published eagerly, close() would `aclose()` B's spent
    generator (a silent no-op), believe it had finalized the abandoned turn,
    and then wait on the lock A's real generator still holds. This asserts
    close() still finds A's generator and completes.
    """
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.5

    gen_a = session.send("first")
    await gen_a.__anext__()  # A's turn is running -- then abandoned.
    assert session.status == "running"

    # B: correctly rejected. Must NOT steal `_active_gen` from A on the way.
    with pytest.raises(SessionBusy):
        [e async for e in session.send("second")]

    # close() must still be able to find and force-finalize A's real,
    # abandoned generator -- not hang on a lock only A's generator holds.
    await asyncio.wait_for(session.close(), timeout=1.0)

    assert session.status == "closed"
    assert client.disconnected is True


async def test_a_losing_send_does_not_modify_active_gen(settings: Settings) -> None:
    """The MECHANISM behind the section above, asserted directly.

    Only the turn that actually wins `self._lock` may become `_active_gen`. A
    losing `SessionBusy` caller raises inside `_send_impl` before reaching the
    publish line, so it can never overwrite the running turn's generator.
    """
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    gen_a = session.send("first")
    await gen_a.__anext__()
    assert session._active_gen is gen_a

    with pytest.raises(SessionBusy):
        [e async for e in session.send("second")]

    # Untouched by the losing call -- still A's real, running generator.
    assert session._active_gen is gen_a


async def test_active_gen_is_cleared_after_a_normal_turn(settings: Settings) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    [e async for e in session.send("hi")]
    assert session._active_gen is None


# -- fix round 4 (Task 5 re-review), Critical: close()'s RuntimeError branch --
# -- was an UNBOUNDED hang ----------------------------------------------------
#
# Rounds 2/3 read a RuntimeError from `_active_gen.aclose()` as proof of "this
# is the ACTIVELY DRIVEN case, so that task's own timeout_s bound will end it"
# and fell straight through to `async with self._lock:`. That inference is
# false. RuntimeError proves only that an advance is in flight AT THAT INSTANT
# -- not that anyone will keep driving the generator afterwards. The failing
# sequence is exactly the SSE consumer this effort exists to protect:
#
#   1. A consumer is parked inside gen.__anext__(), so the generator IS
#      running and aclose() does raise RuntimeError.
#   2. close() swallows it and parks on the lock.
#   3. That advance returns, the consumer takes the event and ABANDONS the
#      generator -- no aclose(), no cancel -- and its task exits.
#   4. Nothing will ever resume the generator, so its `finally` never runs and
#      the lock is never released. The turn's own asyncio.timeout() cannot
#      save it either: its dangling call_at cancels the task that FIRST
#      advanced it, and that task is already gone, so .cancel() is a no-op.
#
# Measured against the round-3 code: with timeout_s=0.05 close() was still
# hung 1.03s later (20x its own bound), status == "running", the lock held and
# the interrupt stamp leaked. Blast radius: SessionRegistry.close() holds the
# registry-wide `_lock` across `await session.close()`, so one DELETE in this
# window deadlocks create()/reap_once()/close_all() -- the whole registry --
# and the orphaned session stays "running" so the reaper skips it forever.
#
# Fix: close() no longer swallows the RuntimeError. It re-checks and RETRIES
# aclose() while the session lock is still held, bounded by timeout_s, and the
# final lock acquisition is itself bounded -- so every path out of close() is.


async def test_close_is_bounded_when_a_turn_is_abandoned_after_an_advance(
    settings: Settings,
) -> None:
    """The unbounded hang this whole retry loop exists to remove.

    A `RuntimeError` from `_active_gen.aclose()` proves only that an advance is
    in flight AT THAT INSTANT -- NOT that anyone will keep driving the
    generator. Reading it as "this is the actively-driven case, so that task's
    own timeout_s will end it", swallowing it and falling through to a bare
    `async with self._lock:` is the shape this reproduces, and it hangs
    forever: the consumer takes its event, abandons the generator and exits, so
    nothing ever runs the turn's `finally`, and the turn's own dangling
    `asyncio.timeout` cancels a task that is already gone.

    Measured against that shape: with `timeout_s=0.05`, `close()` was still
    hung 1.03s later (20x its own bound), `status == "running"`, the lock held
    and the interrupt stamp leaked. A randomised 400-round interleaving fuzz
    hung in 7% of rounds. Blast radius at the time: `SessionRegistry.close()`
    held the registry-wide lock across `await session.close()`, so one DELETE
    in this window deadlocked create()/reap_once()/close_all(), and the
    orphaned session stayed "running", which the reaper skips forever.

    After the fix: the repro closes in ~30ms end to end, and 2500 randomised
    rounds produced 0 violations with a 77ms worst case.

    The final assertions are not incidental -- a bounded close that leaked the
    lock, the stamp or `_active_gen` would be a different defect wearing this
    test's name.
    """
    gate = asyncio.Event()

    class GatedClient(FakeClient):
        async def receive_response(self):
            # Park here so an advance is genuinely in flight -- and so
            # aclose() genuinely raises RuntimeError -- when close() runs.
            await gate.wait()
            for msg in _normal_turn():
                yield msg

    client = GatedClient()
    session = make_session(settings, client)
    await session.open()
    # **0.5s, not the 0.05 this test used to carry, and the difference is what
    # made it flaky.** `timeout_s` bounds the TURN as well as close()'s retry
    # budget, and the setup below has to complete inside it -- so a scheduling
    # stall longer than the bound expired the turn before the first assertion
    # and produced `assert 'idle' == 'running'`. Observed once in a full CI run
    # with Docker builds and two other suites competing for the machine.
    #
    # The value is still far below anything a real turn would use, so a
    # regression that hung close() is still caught by the `wait_for` at the end
    # -- what changed is that a slow machine no longer looks like a defect.
    session._limits.timeout_s = 0.5

    gen = session.send("hello")
    got: list[dict] = []

    async def consumer() -> None:
        # Parks inside __anext__ until the gate opens, then takes the event
        # and abandons the generator entirely. This task then exits, which is
        # what makes the turn's own dangling timeout a no-op.
        got.append(await gen.__anext__())

    consumer_task = asyncio.create_task(consumer())
    # **Wait for the STATE, never for a duration.** `await asyncio.sleep(0.005)`
    # is a guess that the consumer has reached the gate by then; under load it
    # is a guess that fails. Every wait in this test is now on the condition it
    # actually needs.
    await _until(lambda: session.status == "running", what="the turn to start")

    close_task = asyncio.create_task(session.close())
    # close() calls interrupt() and then aclose(), which raises RuntimeError
    # because the consumer is parked mid-advance. The interrupt is the
    # observable that it has got that far.
    await _until(lambda: client.interrupts == 1, what="close() to interrupt")
    assert client.disconnected is False, (
        "close() disconnected while the generator was still parked; it should "
        "be retrying aclose() until the consumer abandons it"
    )

    gate.set()
    await consumer_task
    assert [e["type"] for e in got] == ["system"]

    # Must be bounded. Against the round-3 code this hung indefinitely, so any
    # finite ceiling proves the point; this one is generous on purpose, because
    # the failure being caught is "never returns" and not "returned slowly".
    await asyncio.wait_for(close_task, timeout=5.0)

    assert session.status == "closed"
    assert client.disconnected is True
    assert session._lock.locked() is False
    assert session._interrupt_for_turn is None  # Task 2: stamp never leaks
    assert session._active_gen is None
    await session.close()  # still idempotent


async def test_close_does_not_starve_a_genuinely_driven_turn(
    settings: Settings,
) -> None:
    """The other half of the retry loop: it must not force-close a live turn.

    Retrying `aclose()` fixes the abandoned case, and the risk in fixing it is
    over-reach. A consumer that keeps driving must still receive its whole
    turn, and `close()` must return AFTER it, not before. On a single-threaded
    loop such a consumer is never observed outside `__anext__`, so `aclose()`
    keeps raising `RuntimeError` and the turn drains normally.

    A consumer caught in a gap BETWEEN advances does get force-closed. That is
    deliberate and it is what DELETE means; `GeneratorExit` reaches it as an
    ordinary end-of-iteration, not an error.
    """
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            await release.wait()
            for msg in _interrupted_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    async def run_turn() -> list[dict]:
        return [e async for e in session.send("count to a million")]

    turn_task = asyncio.create_task(run_turn())
    await asyncio.sleep(0)
    assert session.status == "running"

    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0.02)  # several retry ticks while the turn is driven
    assert client.disconnected is False

    release.set()
    events = await asyncio.wait_for(turn_task, timeout=1.0)
    assert [e["type"] for e in events] == ["system", "result"]
    assert session.last_turn.interrupted is True

    await asyncio.wait_for(close_task, timeout=1.0)
    assert session.status == "closed"
    assert client.disconnected is True


# -- fix round 4, Secondary: send() only checked `status` BEFORE the lock -----
#
# `_send_impl` checked `status == "closed"` only before acquiring the lock,
# while close() re-checks INSIDE it. A send() whose first advance lands while
# the lock is free but some closer is already queued on it (asyncio.Lock is
# FIFO-fair, so an unlocked lock with a live waiter still suspends the next
# acquirer) passes BOTH pre-lock guards, queues behind that closer, and
# acquires the lock only after the session was closed and disconnected -- then
# runs a full turn against a dead client and resurrects `status` from "closed"
# to "running"/"idle", breaking Task 2's terminal-status invariant. Reproduced
# against rounds 1-3 with close() itself as the queued closer (`queries ==
# ["A", "B"]`, `disconnected is True`, final `status == "running"`).
#
# Round 4's retry loop means close() itself no longer PARKS on the lock in
# this precise window (it force-finalizes the live turn first, and only then
# acquires -- with no suspension point between observing the lock free and
# taking it). The window is closed at the guard instead of by accident of
# close()'s current shape, so the queued closer here is written explicitly:
# what is being pinned is `_send_impl`'s own invariant -- a turn must never
# start on a session that was closed while it was queued -- for whatever ends
# up ahead of it on that lock.


async def test_a_send_that_wins_the_lock_after_close_is_rejected(
    settings: Settings,
) -> None:
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            await release.wait()
            for msg in _normal_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    async def run_turn() -> list[dict]:
        return [e async for e in session.send("A")]

    turn_task = asyncio.create_task(run_turn())
    await asyncio.sleep(0)
    assert session.status == "running"

    closed = asyncio.Event()

    async def closer() -> None:
        # Queues on the lock A holds, and closes the session the moment it
        # gets it. Stands in for anything that closes under the lock.
        await session._lock.acquire()
        try:
            session.status = "closed"
            await session._client.disconnect()
        finally:
            session._lock.release()
            closed.set()

    closer_task = asyncio.create_task(closer())
    await asyncio.sleep(0)  # let it become a waiter on the lock

    async def losing_turn() -> None:
        gen = session.send("B")
        # Advance in the exact window: A has released the lock and set
        # `status` back to "idle", but the closer -- woken, still queued -- has
        # not resumed. Both pre-lock guards pass; the acquire queues behind it.
        while session._lock.locked():
            await asyncio.sleep(0)
        with pytest.raises(SessionClosed):
            [e async for e in gen]

    losing_task = asyncio.create_task(losing_turn())
    await asyncio.sleep(0)

    release.set()
    await asyncio.wait_for(turn_task, timeout=1.0)
    await asyncio.wait_for(closer_task, timeout=1.0)
    await asyncio.wait_for(losing_task, timeout=1.0)

    # B never ran a turn against the disconnected client, and never
    # resurrected the terminal status.
    assert client.queries == ["A"]
    assert session.status == "closed"
    assert client.disconnected is True


# -- fix round 5 (Task 5 re-review), Important: the interrupt was OUTSIDE ------
# -- close()'s deadline, and unguarded ----------------------------------------
#
# Round 4 bounded the aclose() retry loop and the lock acquisition, and then
# claimed "EVERY path out of this method is bounded". It was not: `deadline`
# was computed BEFORE `await self.interrupt()`, and that call had no bound and
# no `except`. The SDK bounds a control request at its OWN 60s
# (`_internal/query.py`, `timeout: float = 60.0`, `anyio.fail_after`) and then
# raises a plain `Exception("Control request timeout: interrupt")`.
# `RunOptions.timeout_s` is caller-supplied with `ge=1`, so `timeout_s=1`
# against a 60s interrupt bound is ordinary usage.
#
# Measured against the round-4 code, with the control timeout scaled to 0.4s
# and `timeout_s=0.05`, driving the real SessionRegistry:
#
#   turn abandoned; status='running' lock=True
#     [during DELETE #1] create=BLOCKED reap_once=BLOCKED close_all=BLOCKED
#   DELETE #1: 500 Exception(Control request timeout: interrupt) in 402ms
#              -- advertised bound was 0.05s
#   ... #2, #3 identical ...
#   AFTER: reclaimed=0 status='running' registered=True disconnected=False
#          lock=True interrupt_calls=3
#
# i.e. 8x the advertised bound, the whole registry stalled for the duration,
# and -- because interrupt() RAISES before `_finalize_live_turn` is ever
# reached, bypassing the entire round-4 machinery -- a PERMANENT cap-slot and
# subprocess leak that every retry reproduces, since reap_once() skips
# `status == "running"` by design.
#
# Fix: try `aclose()` FIRST. An abandoned turn is finalized outright and needs
# no control request at all, so the leak case never touches the wedged
# channel. Only a turn that is genuinely being advanced gets the interrupt,
# and that call is now bounded by a share of the same deadline and can never
# be fatal.


class _WedgedControlClient(FakeClient):
    """A CLI that answers conversation messages but NEVER control requests.

    Mirrors the SDK's own behaviour on a wedged control channel: block for the
    control timeout, then raise a plain `Exception`.
    """

    control_timeout_s = 0.4

    async def interrupt(self) -> None:
        self.interrupts += 1
        await asyncio.sleep(self.control_timeout_s)
        raise Exception("Control request timeout: interrupt")


async def test_close_reclaims_an_abandoned_turn_without_a_control_request(
    settings: Settings,
) -> None:
    """Why `aclose()` is tried BEFORE `interrupt()`, and not the other way.

    The permanent-leak scenario: an abandoned SSE consumer plus a CLI that
    never answers control requests. Interrupting first, on that CLI, RAISED
    before the turn-finalizing machinery was reached at all, bypassing it.
    Measured through the real `SessionRegistry` (control timeout 0.4s,
    `timeout_s=0.05`): three DELETEs in a row 500'd at ~402ms each -- 8x the
    advertised bound -- each stalling create(), reap_once() AND close_all() for
    its whole duration, and afterwards `reclaimed=0 status='running'
    registered=True disconnected=False`: a PERMANENT cap-slot and subprocess
    leak, because the reaper skips "running" by design and every retry repeats
    the same wait and the same failure.

    Trying `aclose()` first removes the control request from this path
    entirely. An abandoned turn has no in-flight caller left to give a defined
    ending to, so nothing is owed an interrupt, and `disconnect()` (S5) stops
    the subprocess regardless. `interrupts == 0` is the whole point of this
    test: the wedged channel is never touched.
    """
    client = _WedgedControlClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.5

    gen = session.send("hello")
    await gen.__anext__()  # advance once, then abandon
    assert session.status == "running"

    t0 = time.monotonic()
    await asyncio.wait_for(session.close(), timeout=1.0)
    elapsed = time.monotonic() - t0

    # Nowhere near the control timeout: the wedged channel is never used.
    assert elapsed < _WedgedControlClient.control_timeout_s
    assert client.interrupts == 0
    assert session.status == "closed"
    assert client.disconnected is True
    assert session._lock.locked() is False
    assert session._interrupt_for_turn is None


async def test_close_is_bounded_when_the_control_channel_is_wedged(
    settings: Settings,
) -> None:
    """The actively-driven case, where the interrupt genuinely IS issued.

    A turn being advanced still deserves the measured S2 ending rather than a
    forced abort, so `close()` does interrupt it -- but that call must be
    bounded by `close()`'s own deadline and must never be fatal.

    The SDK bounds control requests by its OWN 60s and then raises a plain
    `Exception`, while `RunOptions.timeout_s` is caller-supplied with `ge=1`,
    so `timeout_s=1` against a 60s control bound is ordinary usage. An earlier
    version computed the deadline before that await and neither bounded nor
    caught it, which made its own "every path is bounded" claim false.
    `_interrupt_until` now takes half the remaining budget and swallows every
    failure mode: neither the SDK's timeout nor ours says anything about
    whether the session can be closed, and `disconnect()` (S5) works without
    the control channel.
    """

    class Gated(_WedgedControlClient):
        control_timeout_s = 5.0

        async def receive_response(self):
            await asyncio.Event().wait()  # parks forever
            yield None

    client = Gated()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.1

    async def run_turn() -> None:
        with contextlib.suppress(BaseException):
            [e async for e in session.send("hi")]

    turn_task = asyncio.create_task(run_turn())
    await asyncio.sleep(0.01)
    assert session.status == "running"

    t0 = time.monotonic()
    await asyncio.wait_for(session.close(), timeout=2.0)
    elapsed = time.monotonic() - t0

    assert client.interrupts == 1  # it WAS asked to stop (S2), just bounded
    assert elapsed < Gated.control_timeout_s  # ... and not for 5 seconds
    assert session.status == "closed"
    assert client.disconnected is True

    turn_task.cancel()
    with contextlib.suppress(BaseException):
        await turn_task


async def test_close_leaves_the_session_terminal_when_cancelled(
    settings: Settings,
) -> None:
    """A cancellation `close()` did not ask for, that is still partly its own.

    An abandoned turn's dangling `asyncio.timeout` cancels whichever task made
    that turn's FIRST advance, wherever that task happens to be by then --
    including inside `close()`'s own retry sleep. Measured:
    `close(): RAISED CancelledError in 125ms, status='idle'
    disconnected=False`.

    It is NOT distinguishable from a genuine caller cancellation (both are just
    `Task.cancel()`), so it must still propagate -- but it must never leave the
    session connected and unreclaimable. The handler therefore disconnects and
    marks the session terminal before re-raising.

    BEST EFFORT, not a guarantee: that handler wraps its own `disconnect()` in
    `suppress(Exception)`, so a cancellation landing AND the disconnect then
    failing still leaks, non-terminal, until a retried DELETE arrives. Nothing
    pins that residual case -- see the report's unpinned list.
    """
    gate = asyncio.Event()

    class GatedClient(FakeClient):
        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
            await gate.wait()
            yield _result()

    client = GatedClient()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.15

    gen = session.send("hi")
    outcome: dict[str, object] = {}

    async def task_c() -> None:
        # C makes the FIRST advance, so the turn's timeout targets C.
        await gen.__anext__()
        await asyncio.sleep(0.02)  # let B take over driving
        try:
            await session.close()
            outcome["r"] = "returned"
        except BaseException as exc:  # noqa: BLE001
            outcome["r"] = type(exc).__name__

    async def task_b() -> None:
        await asyncio.sleep(0.01)
        with contextlib.suppress(BaseException):
            await gen.__anext__()  # parks inside the advance

    ct = asyncio.create_task(task_c())
    bt = asyncio.create_task(task_b())
    await asyncio.wait([ct, bt], timeout=2.0)
    for t in (ct, bt):
        t.cancel()
    await asyncio.gather(ct, bt, return_exceptions=True)

    # Whether close() returned or was cancelled, the session must be terminal.
    assert session.status == "closed"
    assert client.disconnected is True


async def test_close_does_not_report_success_when_disconnect_fails(
    settings: Settings,
) -> None:
    """`status = "closed"` must be assigned AFTER `disconnect()` returns.

    Assigning it first made a FAILED disconnect look terminal, so the retry
    `registry.py` documents -- and `api.py`'s `delete_session` relies on --
    became a silent no-op that answered 204 while the subprocess was still
    alive. Measured: `DELETE #2 -> 204 with disconnect_calls=1
    client.disconnected=False`.

    This is the test that kills the obvious simplification of `_closing`
    ("just hoist the assignment so `status` can carry the closing state").
    Leaving the session non-terminal is what makes a retried DELETE genuinely
    retry, and it is why `_closing` has to be a separate one-way latch --
    see `test_a_turn_cannot_start_while_close_is_disconnecting`.
    """

    class FlakyDisconnect(FakeClient):
        async def disconnect(self) -> None:
            self.disconnect_calls = getattr(self, "disconnect_calls", 0) + 1
            if self.disconnect_calls == 1:
                raise OSError("subprocess kill failed")
            self.disconnected = True

    client = FlakyDisconnect([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    with pytest.raises(OSError, match="subprocess kill failed"):
        await session.close()
    # NOT terminal: the subprocess is still alive, so nothing may claim it is
    # gone -- and the retry must actually retry.
    assert session.status != "closed"

    await session.close()
    assert client.disconnect_calls == 2
    assert client.disconnected is True
    assert session.status == "closed"


async def test_close_disconnects_even_if_the_turn_teardown_fails(
    settings: Settings,
) -> None:
    """A failure to tear down a turn must never stop close() disconnecting.

    `gen.aclose()` runs the turn's WHOLE unwind, including the SDK generator's
    own `aclose()`, so a teardown failure -- an `OSError` from a transport that
    is already gone, say -- surfaces there. Catching only `RuntimeError` let it
    propagate before `status` was set and before `disconnect()`: measured,
    `close() RAISED OSError(transport already gone) BEFORE disconnecting;
    status='idle' disconnected=False`, making DELETE #1 a 500 with the client
    still connected.

    The turn is over either way -- that unwind releases the session lock and
    runs the `finally` on its way out -- and `disconnect()` (S5) stops the
    subprocess regardless, so the honest move is to log and carry on.
    """

    class BadTeardown(FakeClient):
        async def receive_response(self):
            try:
                for msg in _normal_turn():
                    yield msg
            finally:
                raise OSError("transport already gone")

    client = BadTeardown()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.2

    gen = session.send("hi")
    await gen.__anext__()  # advance once, then abandon

    await asyncio.wait_for(session.close(), timeout=1.0)
    assert session.status == "closed"
    assert client.disconnected is True


async def test_set_model_and_permission_mode_delegate(settings: Settings) -> None:
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    await session.set_model("claude-opus-5")
    await session.set_permission_mode("acceptEdits")
    assert client.model == "claude-opus-5"
    assert client.permission_mode == "acceptEdits"


async def test_context_usage_passthrough(settings: Settings) -> None:
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    usage = await session.context_usage()
    assert usage["categories"][0]["name"] == "Messages"


# -- fix round 1, Critical 2: a hung turn must not hang forever --------------
#
# `self._limits` was assigned in __init__ and never read again -- nothing
# bounded a turn's duration. Combined with registry.py's reaper policy (never
# force-close a "running" session), a single hung turn per session, up to
# `max_sessions` of them, would permanently exhaust the service's ability to
# create new sessions. `send()` now wraps the drain in
# `asyncio.timeout(self._limits.timeout_s)`, mirroring runner.py's
# `Run.events()`, and raises the same `RunTimeout` on expiry.


async def test_a_turn_that_never_produces_a_result_is_terminated_by_timeout(
    settings: Settings,
) -> None:
    class HangingClient(FakeClient):
        async def receive_response(self):
            await asyncio.Event().wait()  # never released
            yield  # pragma: no cover - unreachable; keeps this a generator

    client = HangingClient()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.05  # keep the test fast

    with pytest.raises(RunTimeout):
        [e async for e in session.send("hang forever")]

    # The session is not wedged: it's back to idle, not stuck "running" --
    # this is exactly what makes it reclaimable by registry.py's reaper,
    # which otherwise skips any session with status == "running" forever.
    assert session.status == "idle"
    assert session.last_turn.outcome is None
    assert session.last_turn.timed_out is True
    # Distinguished from an interrupt: nobody called interrupt() here.
    assert session.last_turn.interrupted is False
    # Residue guard still engages like any other abnormal end.
    assert session._residue_suspected is True


async def test_an_interrupted_turn_is_not_labelled_as_timed_out(
    settings: Settings,
) -> None:
    # The two flags are independent signals, not inferred from one another:
    # a normal interrupt (turn draining well within timeout_s, stopped
    # deliberately) must report interrupted=True, timed_out=False -- the
    # mirror image of the hang case above.
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            started.set()
            await release.wait()
            for msg in _interrupted_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    task = asyncio.create_task(
        _drain(session, "count to a million")
    )
    await started.wait()
    await session.interrupt()
    release.set()
    await task

    assert session.last_turn.interrupted is True
    assert session.last_turn.timed_out is False


async def _drain(session: AgentSession, prompt: str) -> list[dict]:
    return [e async for e in session.send(prompt)]


# --- Task 6, fix round 1: interrupting a turn abandoned MID-DRAIN ----------


class _ParkedClient(FakeClient):
    """First turn sends one message then parks inside `receive_response()`
    forever; later turns replay `turns` normally.

    Parking is what lets a test cancel a drain at the exact point a real
    socket hangup cancels it: inside `stream.__anext__()`, with the SDK
    generator suspended awaiting the next message -- not at a `yield` between
    messages, which is a materially different unwind.
    """

    def __init__(self, later_turns: list[list[object]] | None = None) -> None:
        super().__init__(later_turns or [])
        self.parked = asyncio.Event()
        self._has_parked = False

    async def receive_response(self):
        if not self._has_parked:
            self._has_parked = True
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
            self.parked.set()
            await asyncio.Event().wait()  # never released
            yield _result()  # pragma: no cover - unreachable
            return
        async for message in super().receive_response():
            yield message


async def _abandon_mid_drain(session: AgentSession, client: _ParkedClient) -> None:
    """Run a turn and cancel it while it is parked inside `__anext__()`."""

    async def drain() -> None:
        async for _ in session.send("hi"):
            pass

    task = asyncio.create_task(drain())
    await client.parked.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_interrupt_reaches_the_sdk_after_a_turn_abandoned_mid_drain(
    settings: Settings,
) -> None:
    """Task 6 fix round 1. THE case the SSE endpoint creates.

    When an SSE consumer on a real socket hangs up, the cancellation lands
    INSIDE `stream.__anext__()`, so `_send_impl` unwinds through its own
    `except BaseException`/`finally` and `status` is already back to `"idle"`
    by the time anything downstream gets to react. A version of `interrupt()`
    that keyed solely off `status == "running"` therefore returned at its
    first line and never sent the control request -- while the CLI subprocess
    was still producing the rest of that turn.

    That is not cosmetic: those still-in-flight messages are NOT covered by
    `_discard_residue()` (which can only drop what is already buffered when
    the next turn starts), so they arrive during the NEXT turn's drain and a
    stray `ResultMessage` among them ends it early -- one caller's turn
    attributed to another.
    """
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()

    await _abandon_mid_drain(session, client)

    # The turn already unwound on its own: this is the interleaving where
    # `status == "running"` is no longer true when the cleanup runs.
    assert session.status == "idle"
    assert session._residue_suspected is True
    assert client.interrupts == 0  # nothing has asked the SDK to stop yet

    await session.interrupt()
    assert client.interrupts == 1


async def test_interrupt_after_an_abandoned_turn_fires_at_most_once(
    settings: Settings,
) -> None:
    """The abandoned-turn condition is consumed, not latched: a second
    interrupt has nothing left to stop and must not spray control requests at
    an idle session."""
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)

    await session.interrupt()
    await session.interrupt()
    assert client.interrupts == 1


async def test_interrupt_does_not_fire_for_a_complete_but_resultless_turn(
    settings: Settings,
) -> None:
    """The discrimination that stops this from being "interrupt whenever
    `_residue_suspected`".

    `_residue_suspected` is set for BOTH a drain abandoned mid-turn AND a
    drain that ended normally without ever seeing a `ResultMessage`. Only the
    first means the subprocess is still producing. The second has already
    finished; asking the SDK to stop it is exactly the "interrupt nothing"
    no-op Task 2 ruled out, and could only mislabel a later turn.
    """
    client = FakeClient([[SystemMessage(subtype="init", data={"session_id": "s"})]])
    session = make_session(settings, client)
    await session.open()

    assert [e async for e in session.send("hi")]
    assert session._residue_suspected is True  # the buffer guard still arms

    await session.interrupt()
    assert client.interrupts == 0


async def test_a_new_turn_clears_the_abandoned_turn_condition(
    settings: Settings,
) -> None:
    """A fresh turn owns the connection now. Interrupting after it started
    must act on THAT turn (the running path), never fire a second, stale
    control request on behalf of the turn before it."""
    client = _ParkedClient(later_turns=[_normal_turn()])
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)

    # A second turn runs to completion and clears the condition.
    assert [e async for e in session.send("again")]

    await session.interrupt()
    assert client.interrupts == 0


async def test_interrupt_never_touches_a_closed_session(settings: Settings) -> None:
    """`close()` -> `disconnect()` already stops the subprocess (S5). Sending
    a control request down a disconnected client afterwards can only raise."""
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)

    await session.close()
    assert session.status == "closed"
    before = client.interrupts

    await session.interrupt()
    assert client.interrupts == before


async def test_interrupt_then_aclose_labels_the_turn_as_interrupted(
    settings: Settings,
) -> None:
    """What the SSE cleanup's interrupt-before-aclose order actually buys.

    This is the stalled-WRITE disconnect: the consumer is holding an event and
    the turn is parked at its own `yield`, so `status == "running"` and the
    turn can still be stamped. Interrupting first records an honest
    `TurnResult`.
    """
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()

    gen = session.send("hi")
    assert (await anext(gen))["type"] == "system"
    assert session.status == "running"  # parked at its yield, lock held

    await session.interrupt()  # what api.py's close_stream() does first
    await gen.aclose()  # ...and only then force-ends the turn

    assert client.interrupts == 1
    assert session.last_turn.interrupted is True


async def test_aclose_before_interrupt_still_reaches_the_sdk_but_mislabels(
    settings: Settings,
) -> None:
    """The reverse order, documented rather than assumed.

    Since `interrupt()` gained the abandoned-turn fallback, closing first no
    longer LOSES the control request -- so the ordering is not load-bearing for
    "does the subprocess get stopped". What it loses is the label: the turn is
    recorded before the interrupt is issued, so a turn we deliberately stopped
    is reported as a plain failure. That is the whole cost, and it is why
    api.py keeps the interrupt first.
    """
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()

    gen = session.send("hi")
    assert (await anext(gen))["type"] == "system"

    await gen.aclose()
    await session.interrupt()

    assert client.interrupts == 1  # the fallback still stops the subprocess
    assert session.last_turn.interrupted is False  # ...but the turn is mislabelled


async def test_interrupt_then_aclose_leaves_nothing_further_to_interrupt(
    settings: Settings,
) -> None:
    """Task 6, fix round 2. The cleanup must not RE-ARM its own condition.

    `close_stream()` on the stalled-write path does interrupt-then-`aclose()`.
    The `aclose()` throws `GeneratorExit` through `_send_impl`'s `except
    BaseException`, which is also where `_turn_abandoned` is recorded -- so the
    turn we just successfully interrupted re-armed the flag on its way out, and
    the next caller to reach `interrupt()` issued a SECOND control request for
    a turn that was already stopped.

    That falsifies the "at most once per abandoned turn" property, and it is
    exactly the spurious fire Task 2's no-op ruling exists to prevent: the HTTP
    layer reports "interrupted nothing" as a 200 with a body, so a stale flag
    would make that body lie. Unreachable while the only callers are
    `close_stream()` and `_interrupt_until()`, but Task 7 adds
    `POST /v1/sessions/{sid}/interrupt`.

    The sibling test `..._fires_at_most_once` drives only the CANCEL path,
    where nothing was interrupted before the unwind -- which is precisely why
    it did not catch this.
    """
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()

    gen = session.send("hi")
    assert (await anext(gen))["type"] == "system"

    await session.interrupt()  # close_stream() step 1: the turn is running
    await gen.aclose()  # close_stream() step 2: force-end it

    assert client.interrupts == 1
    assert session.status == "idle"
    # The turn was interrupted and then torn down. Nothing is still producing
    # on its behalf, so nothing is owed another control request.
    assert session._turn_abandoned is False

    await session.interrupt()  # e.g. Task 7's endpoint, or any later caller
    assert client.interrupts == 1


# --- Task 7: interrupt() reports whether it actually fired -----------------
#
# `POST /v1/sessions/{sid}/interrupt` returns 200 with a body saying what
# happened. The endpoint cannot DERIVE that from anything it can see: the
# obvious `status == "running"` inference is wrong in exactly the case the
# abandoned-turn branch exists for -- an idle session whose subprocess is still
# producing, where a real control request DOES go out. So `interrupt()` reports
# it. The return value is the ONLY thing that distinguishes the two "idle"
# outcomes below, and it is what stops that body from lying.


async def test_interrupt_returns_true_when_it_stops_a_running_turn(
    settings: Settings,
) -> None:
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()

    gen = session.send("hi")
    assert (await anext(gen))["type"] == "system"
    assert session.status == "running"

    assert await session.interrupt() is True
    assert client.interrupts == 1
    await gen.aclose()


async def test_interrupt_returns_false_when_there_is_nothing_to_interrupt(
    settings: Settings,
) -> None:
    """The no-op Task 2 ruled must not raise. It must also not claim success."""
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    assert await session.interrupt() is False
    assert client.interrupts == 0


async def test_interrupt_returns_true_for_an_abandoned_turn_on_an_idle_session(
    settings: Settings,
) -> None:
    """THE case that forces this return value to exist.

    `status` is `"idle"` here and the turn is over, yet the CLI subprocess is
    still producing and a genuine control request goes out. An HTTP layer
    inferring "did anything happen" from `status` would report `interrupted:
    false` for a request that really did fire. The second call is the mirror
    image: same `"idle"` status, no control request, and it must say so.
    """
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)
    assert session.status == "idle"

    assert await session.interrupt() is True
    assert client.interrupts == 1

    assert session.status == "idle"  # unchanged -- indistinguishable from above
    assert await session.interrupt() is False
    assert client.interrupts == 1


async def test_interrupt_returns_false_on_a_closed_session(
    settings: Settings,
) -> None:
    client = _ParkedClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)
    await session.close()

    assert await session.interrupt() is False


# --- Task 7 fix round 1: the setters refuse a closed session ---------------


async def test_set_model_on_a_closed_session_raises_session_closed(
    settings: Settings,
) -> None:
    """`SessionClosed`, not a control request at a disconnected client.

    Without this the SDK raises `CLIConnectionError`, which `to_problem` maps
    to 502 "Agent process failed" -- reporting a deliberate close as an agent
    crash, and disagreeing with the 409 `send()` already raises for the exact
    same condition.
    """
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    await session.close()

    with pytest.raises(SessionClosed):
        await session.set_model("claude-opus-5")
    assert client.model is None


async def test_set_permission_mode_on_a_closed_session_raises_session_closed(
    settings: Settings,
) -> None:
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    await session.close()

    with pytest.raises(SessionClosed):
        await session.set_permission_mode("plan")
    assert client.permission_mode is None


async def test_the_setters_still_work_on_a_live_session(settings: Settings) -> None:
    """The guard keys off `closed` only -- measured working mid-session in
    spike S4, and it must stay that way."""
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()

    await session.set_model("claude-opus-5")
    await session.set_permission_mode("plan")
    assert client.model == "claude-opus-5"
    assert client.permission_mode == "plan"


# --- what `interrupted` on a completed turn actually means -----------------
# `_send_impl` labels a finished turn with
# `interrupted=bool(interrupt_requested and aborted)`. Both conjuncts are
# load-bearing and only the FIRST was pinned: deleting `and aborted` left the
# whole suite green. The test below is the missing half.
#
# `interrupt_requested` alone answers "did anyone ask this turn to stop", which
# is NOT the question `RunResponse.interrupted` promises to answer. It promises
# "was this turn stopped BY that request", and the difference is exactly the
# race the interrupt design exists for: a caller asks to stop a turn that is
# already finishing, the request loses, and the turn ends normally --
# `terminal_reason="completed"`, `is_error=False`, a real `result`. Reporting
# `interrupted=true` for that would tell a client its stop took effect when the
# agent in fact ran to completion, and would do it on the response that also
# carries the successful result.
#
# `aborted` is what closes the gap: it is the MEASURED shape of a genuinely
# stopped turn (spike S2, `terminal_reason` in ABORTED_TERMINAL_REASONS).
# Neither conjunct is sufficient alone -- an aborted turn nobody asked to stop
# is a crash, and a requested stop that did not land is this test.


async def test_a_requested_interrupt_that_loses_the_race_is_not_reported(
    settings: Settings,
) -> None:
    """A genuine interrupt request mid-drain, on a turn that then COMPLETES.

    The stamp is set (so `interrupt_requested` is True and the control request
    really went out) but the turn ends in the normal shape, so `interrupted`
    must be False. Deleting `and aborted` from `_send_impl` flips this to True
    and fails here -- which is the point of the test.
    """
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("go")
    await gen.__anext__()  # init consumed; the turn is now genuinely running
    assert session.status == "running"

    # A real interrupt request, stamped against THIS turn, delivered to the SDK.
    assert await session.interrupt() is True
    assert client.interrupts == 1

    # ...but the turn wins the race and finishes normally anyway.
    rest = [event async for event in gen]
    assert [e["type"] for e in rest] == ["assistant", "result"]

    turn = session.last_turn
    assert turn.outcome is not None
    assert turn.outcome.terminal_reason == "completed"
    assert turn.outcome.is_error is False
    assert turn.outcome.result == "done"
    assert turn.interrupted is False, (
        "a stop request that did not actually stop the turn must not be "
        "reported as an interrupt -- the turn completed normally"
    )


async def test_an_interrupt_that_does_land_is_still_reported(
    settings: Settings,
) -> None:
    """The other side of the conjunction, so the test above cannot be
    'satisfied' by hard-coding False: same stamp, but the turn comes back in
    the measured aborted shape, and then `interrupted` MUST be True."""
    client = FakeClient([_interrupted_turn()])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("go")
    await gen.__anext__()
    assert await session.interrupt() is True
    [event async for event in gen]

    turn = session.last_turn
    assert turn.outcome.terminal_reason == "aborted_streaming"
    assert turn.interrupted is True


# --- the SDK generator is finalized when a turn is abandoned ---------------


class _FinalizeRecordingClient(FakeClient):
    """Records when `receive_response()`'s own generator is finalized.

    The plain `FakeClient` cannot see this: its `receive_response` has no
    `finally`, so whether the generator was closed or merely dropped is
    invisible. That is why removing `aclosing()` from `_send_impl` left the
    whole suite green.
    """

    def __init__(self, turns) -> None:  # noqa: ANN001
        super().__init__(turns)
        self.finalized: list[str] = []

    async def receive_response(self):
        turn = self.turns[self._turn_index]
        self._turn_index += 1
        try:
            for msg in turn:
                yield msg
        finally:
            self.finalized.append("closed")


async def test_abandoning_a_turn_finalizes_the_sdk_generator(
    settings: Settings,
) -> None:
    """Pins `aclosing(self._client.receive_response())` in `_send_impl`.

    `async for` does NOT close its iterator when the loop is left via
    `GeneratorExit` or a raised exception -- PEP 533 was deferred -- so without
    the `aclosing()` wrapper the SDK's own generator is merely DROPPED when a
    consumer abandons a turn. It is then finalized only by CPython's async-gen
    hooks, which schedule `aclose()` as a task on the event loop at a
    non-deterministic later moment. `runner.py` has the identical construct and
    it IS pinned (test_runner.py::
    test_underlying_query_stream_is_closed_when_events_is_abandoned); this is
    the session-path equivalent, and it was missing.

    The shape being protected is the real one: an SSE consumer disconnecting
    mid-turn, which `api.py`'s `close_stream()` turns into exactly this
    `aclose()` on the turn generator.

    The assertion deliberately runs IMMEDIATELY after `gen.aclose()` returns,
    with no intervening await. That is what makes it discriminating: the
    guarantee `aclosing()` provides is that finalization happens
    SYNCHRONOUSLY within the unwind, not merely eventually. Without it the list
    is still empty at this point (the GC-scheduled aclose task has not run),
    so the test fails -- confirmed by deleting the wrapper.
    """
    client = _FinalizeRecordingClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("go")
    await gen.__anext__()  # consume only init, then walk away
    assert client.finalized == []  # still mid-turn

    await gen.aclose()  # the consumer disappears (SSE disconnect shape)

    assert client.finalized == ["closed"], (
        "aclosing() must finalize the SDK's receive_response() generator "
        "during the abandoned turn's unwind, not leave it to the GC"
    )
    # And the turn is properly recorded as having ended abnormally.
    assert session.last_turn.outcome is None
    assert session.status == "idle"


async def test_a_normally_drained_turn_also_finalizes_the_sdk_generator(
    settings: Settings,
) -> None:
    """The uninteresting path, asserted so the test above is not the only
    thing keeping the wrapper honest: a fully drained turn exhausts the
    generator, which finalizes it too."""
    client = _FinalizeRecordingClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    [event async for event in session.send("go")]

    assert client.finalized == ["closed"]
    assert session.last_turn.outcome is not None


# --- follow-up item 1: interrupt()'s abandoned-turn branch raced a new turn --
#
# Branch 2 issued its control request with NO lock held and no turn running, so
# a turn that STARTED during that await was killed by the PREVIOUS turn's
# in-flight control request. Measured against the round-5 code with the client
# below (which models the SDK honestly: a control request that lands aborts
# whatever turn is draining, spike S2's shape):
#
#   entered=('idle', 1) exited=('idle', 2) raised=None
#   outcome=RunOutcome(is_error=True, terminal_reason='aborted_streaming',
#                      subtype='error_during_execution', ...) interrupted=False
#
# -- a turn deliberately stopped by the service and reported to its caller as a
# plain failure. It cannot even be labelled honestly: branch 2 writes no stamp,
# by design (the turn it was raised for is already over).
#
# Reachable from `POST /v1/sessions/{sid}/interrupt` AND from `close_stream()`'s
# cleanup on an ordinary SSE hangup, so a disconnect-and-retry client hits it
# without ever touching the interrupt endpoint.
#
# Fix: branch 2 holds the session lock across its control request, so the new
# turn loses the ordinary way -- SessionBusy, i.e. 409 -- instead of being
# aborted. Both bounds on that lock are pinned by the tests after this one.


class _AbortingControlClient(FakeClient):
    """A control request that lands ABORTS whatever turn is draining (S2).

    The plain `FakeClient` records `interrupts` and nothing else, so it cannot
    show this defect at all: the whole point is what the control request does
    to a turn that was not its target.
    """

    def __init__(self) -> None:
        super().__init__([])
        self.control_gate = asyncio.Event()  # closed == a slow control channel
        self.abort = asyncio.Event()
        self.turn_started = asyncio.Event()
        self.parked = asyncio.Event()
        self._parked_once = False

    async def interrupt(self) -> None:
        self.interrupts += 1
        await self.control_gate.wait()
        self.abort.set()

    async def receive_response(self):
        if not self._parked_once:
            self._parked_once = True
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
            self.parked.set()
            await asyncio.Event().wait()  # the consumer is cancelled here
            return
        self.turn_started.set()
        yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
        await self.abort.wait()
        yield _result(
            subtype="error_during_execution",
            is_error=True,
            terminal_reason="aborted_streaming",
            result=None,
        )


async def test_a_stale_interrupt_rejects_a_new_turn_instead_of_killing_it(
    settings: Settings,
) -> None:
    """Why `interrupt()`'s abandoned-turn branch holds the session lock.

    It used to issue its control request with no lock held and no turn
    running, and that is a real race, not a theoretical one: a turn STARTED
    during that await is killed by the PREVIOUS turn's in-flight control
    request. Measured against a client that models the SDK honestly (a landed
    interrupt aborts whatever turn is draining, spike S2): `interrupt()`
    entered at `status='idle', _turn_seq=1` and the new turn came back
    `terminal_reason='aborted_streaming', is_error=True, interrupted=False` --
    deliberately stopped by the service and reported to its caller as a plain
    failure. Worse, this branch writes no stamp, so it could not even be
    labelled honestly.

    Reachable from `POST /v1/sessions/{sid}/interrupt` AND from
    `close_stream()`'s cleanup on an ordinary SSE hangup, so a
    disconnect-and-retry client hits it without ever touching the interrupt
    endpoint.

    Holding the lock makes the new turn lose the ORDINARY way -- a 409
    `SessionBusy`, the same answer any concurrent turn gets -- instead of being
    aborted mid-flight. `client.queries == ["hi"]` is the assertion that
    matters: the new turn never reached the SDK, so nothing could abort it.

    Two bounds stop this cure becoming the disease it replaced (a wedged
    control channel awaited under a lock): the lock is taken only if it can be
    had WITHOUT waiting, and the request is bounded by
    `_STALE_INTERRUPT_BUDGET_S` -- see
    `test_close_does_not_wait_for_a_courtesy_interrupt` for the third,
    independent bound.
    """
    client = _AbortingControlClient()
    session = make_session(settings, client)
    await session.open()

    # Turn 1 is abandoned mid-drain: `_turn_abandoned` set, `status` idle.
    await _abandon_mid_drain(session, client)
    assert session.status == "idle"
    assert session._turn_abandoned is True

    interrupt_task = asyncio.create_task(session.interrupt())
    await asyncio.sleep(0.01)  # parked inside the (slow) control request
    assert client.interrupts == 1

    # A brand new turn arrives DURING that await. Bounded, because against the
    # round-5 code it does not raise at all -- it runs, and then dies when the
    # old turn's control request lands on it.
    with pytest.raises(SessionBusy):
        await asyncio.wait_for(_drain(session, "two"), timeout=1.0)

    client.control_gate.set()
    assert await interrupt_task is True

    # The new turn never started, so it cannot have been aborted by the old
    # turn's control request -- which is the whole defect.
    assert client.queries == ["hi"]
    assert session._turn_seq == 1
    assert client.turn_started.is_set() is False
    # ...and the session is immediately usable again: the lock was held for
    # the control request only, not left behind.
    assert session._lock.locked() is False


async def test_a_stale_interrupt_gives_up_rather_than_queueing_behind_a_turn(
    settings: Settings,
) -> None:
    """The bound that stops the cure being fix round 4's disease.

    If a turn already owns the connection there is nothing for branch 2 to do
    -- `_send_impl` clears `_turn_abandoned` when it starts, precisely because
    interrupting on the old turn's behalf could only kill the new one -- so the
    branch must give up IMMEDIATELY rather than wait for the lock. A bare
    `async with self._lock` here would park behind a whole turn, and
    `close_stream()` awaits this call.
    """
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            await release.wait()
            for msg in _normal_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    turn_task = asyncio.create_task(_drain(session, "one"))
    await asyncio.sleep(0)
    assert session._lock.locked() is True
    # Both armed by hand, AFTER the turn took the lock: a real turn clears
    # `_turn_abandoned` on its way in (that is the other half of this defence),
    # and `status` is forced back so the abandoned-turn branch is the one under
    # test rather than the running-turn branch. What is being pinned is that
    # branch 2 never waits for a lock somebody else holds.
    session._turn_abandoned = True
    session.status = "idle"

    t0 = time.monotonic()
    assert await session.interrupt() is False
    assert time.monotonic() - t0 < 0.05  # it did not wait for the turn
    assert client.interrupts == 0

    release.set()
    await asyncio.wait_for(turn_task, timeout=1.0)


async def test_a_stale_interrupt_does_not_hold_the_lock_past_the_turn_budget(
    settings: Settings,
) -> None:
    """A wedged control channel must not wedge the session.

    Branch 2 holds the session lock across its control request, so an
    unanswered one would otherwise make every later turn 409 for as long as the
    SDK's own 60s control bound.

    `timeout_s` is left at the SERVICE DEFAULT here, deliberately (fix round
    6). The first version of this test set it to 0.05 and asserted only "not
    permanent", which proved the bound existed while hiding its MAGNITUDE --
    and the magnitude was the defect: the budget was `timeout_s` itself, so at
    the default this branch held the session lock for up to
    `min(600s, the SDK's 60s control bound)`. Pinning it at the default is what
    makes a regression in magnitude fail rather than pass quietly.
    """
    client = _NeverAnsweringControlClient([_normal_turn()])
    # No turn is abandoned here (the flag below is armed by hand), so the
    # conversation side should replay normally rather than park -- that is what
    # the last assertion in this test needs.
    client._has_parked = True
    session = make_session(settings, client)
    await session.open()
    assert session._limits.timeout_s == 600  # the service default, untouched
    session._turn_abandoned = True

    t0 = time.monotonic()
    with pytest.raises(InterruptTimeout):
        await session.interrupt()
    elapsed = time.monotonic() - t0

    # Bounded by its OWN constant, and nowhere near the turn budget.
    assert elapsed < _STALE_INTERRUPT_BUDGET_S + 0.5
    assert elapsed < session._limits.timeout_s / 10
    assert session._lock.locked() is False
    assert session._courtesy_interrupt is False
    # The session still works: the next turn is not blocked behind the dead
    # control request.
    events = [e async for e in session.send("still fine")]
    assert [e["type"] for e in events] == ["system", "assistant", "result"]


async def test_close_does_not_wait_for_a_courtesy_interrupt(
    settings: Settings,
) -> None:
    """`close()` must not queue behind branch 2's lock -- at the DEFAULT
    `timeout_s`.

    `SessionRegistry.close()` holds the registry-wide lock across `await
    session.close()`, so whatever `close()` waits for, the whole registry waits
    for. The first version of this test set `timeout_s = 0.05` and asserted
    `elapsed < 0.5`: true, and useless, because the real budget was `timeout_s`
    and the default is 600. At the default, with a control channel that never
    answers, that version of `close()` blocked for the SDK's whole control
    bound (measured through the real registry: DELETE 1.960s,
    create/reap_once/close_all 1.944s each, with the control bound modelled at
    2s and the real one at 60s).

    The lock exists to stop `close()` disconnecting out from under a RUNNING
    TURN. A courtesy interrupt is not a turn, so `close()` reads
    `_courtesy_interrupt` and goes straight to the disconnect-without-the-lock
    path it already had for the give-up case.
    """
    client = _NeverAnsweringControlClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)
    assert session._limits.timeout_s == 600  # the service default, untouched

    interrupt_task = asyncio.create_task(session.interrupt())
    await asyncio.sleep(0.01)  # branch 2 holds the lock, parked on the channel
    assert session._lock.locked() is True
    assert session._courtesy_interrupt is True

    t0 = time.monotonic()
    await asyncio.wait_for(session.close(), timeout=5.0)
    elapsed = time.monotonic() - t0

    # Not "eventually" -- immediately. Anything above a few milliseconds here
    # is a wait the registry-wide lock is also serving.
    assert elapsed < 0.2
    assert session.status == "closed"
    assert client.disconnected is True

    # The stale interrupt still ends on its own bound rather than outliving
    # the session, and takes the lock with it.
    with pytest.raises(Exception):  # noqa: B017 - InterruptTimeout or a dead client
        await asyncio.wait_for(interrupt_task, timeout=_STALE_INTERRUPT_BUDGET_S + 1.0)
    assert session._lock.locked() is False
    assert session._courtesy_interrupt is False


async def test_a_courtesy_interrupt_does_not_stall_the_registry(
    settings: Settings,
) -> None:
    """The same defect where it actually hurts: through the real registry, at
    the default `timeout_s`.

    Every registry operation runs under one registry-wide lock, and
    `close()`/`close_all()`/`reap_once()` hold it across `await
    session.close()`. So a `close()` that waits on a courtesy interrupt stalls
    `create()` and the reaper too -- for a session that is merely `"idle"`,
    which is exactly the state `registry.py`'s skip-if-running guard was never
    written for. Measured against the first version of the branch-2 lock, with
    the SDK's control bound modelled at 2s:

        registry.close (DELETE) : 1.960s
        registry.reap_once      : 1.944s
        registry.create         : 1.944s
        registry.close_all      : 1.944s

    Real-world that is `min(timeout_s, the SDK's 60s control bound)`, and
    `timeout_s` -- 600s by default -- if the SDK's bound ever fails to fire.
    """
    from agent_service.registry import SessionRegistry

    client = _NeverAnsweringControlClient()
    session = make_session(settings, client)
    registry = SessionRegistry(settings, session_factory=lambda *a, **k: session)
    sid = await registry.create(RunOptions(), None)
    await _abandon_mid_drain(session, client)

    interrupt_task = asyncio.create_task(session.interrupt())
    await asyncio.sleep(0.01)  # the control request is in flight, lock held
    assert session.status == "idle"  # the reaper's skip guard does NOT apply
    assert session._lock.locked() is True

    delete = asyncio.create_task(registry.close(sid))
    await asyncio.sleep(0)  # let the DELETE take the registry-wide lock

    t0 = time.monotonic()
    await asyncio.wait_for(registry.reap_once(), timeout=5.0)
    reap_ms = (time.monotonic() - t0) * 1000
    await asyncio.wait_for(delete, timeout=5.0)
    delete_ms = (time.monotonic() - t0) * 1000

    assert reap_ms < 200, f"reap_once() blocked for {reap_ms:.0f}ms"
    assert delete_ms < 200, f"the DELETE blocked for {delete_ms:.0f}ms"
    assert client.disconnected is True

    interrupt_task.cancel()
    with contextlib.suppress(BaseException):
        await interrupt_task


# --- follow-up item 2: a stalled write straddling the final `result` frame ---
#
# The turn is recorded when its ResultMessage is CONSUMED, not after the drain
# resumes one final time. A consumer whose write of the `result` frame never
# completes leaves the drain suspended at that `yield` forever, and the
# cleanup's `aclose()` unwinds it through `except BaseException` -- which used
# to overwrite the completed turn. Measured against the round-5 code:
#
#   outcome=None interrupted=True turns=0 cost=0.0 interrupts=1
#
# for a turn with a real result and a real cost. The cost self-heals on the
# next turn (`total_cost_usd` is assigned from the SDK's cumulative value, S6);
# `turns` stayed permanently short by one.


async def test_a_stalled_write_on_the_result_frame_still_records_the_turn(
    settings: Settings,
) -> None:
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("hi")
    seen = [await gen.__anext__() for _ in range(3)]
    assert [e["type"] for e in seen] == ["system", "assistant", "result"]
    # The write of that `result` frame never completes and the consumer goes
    # away; api.py's close_stream() force-ends the turn.
    await gen.aclose()

    turn = session.last_turn
    assert turn.outcome is not None, "the ResultMessage was consumed"
    assert turn.outcome.result == "done"
    assert turn.interrupted is False
    assert turn.timed_out is False
    assert session.turns == 1
    assert session.total_cost_usd == pytest.approx(0.05)
    # Nothing is still producing on this turn's behalf, so nothing is owed a
    # control request -- the straddle used to arm one.
    assert session._turn_abandoned is False
    assert session._residue_suspected is False


async def test_a_recorded_turn_survives_a_timeout_on_the_final_frame(
    settings: Settings,
) -> None:
    """The other way a recorded turn can still end badly: the drain's own
    deadline expires AFTER the ResultMessage was consumed. The reader gets its
    `RunTimeout` -- it really did run out of time -- but the turn did not: its
    result is in, so the record must stand rather than being overwritten with
    `outcome=None, timed_out=True`.

    The stream here keeps waiting after its result instead of ending, which is
    not the pinned SDK's shape (`receive_response` returns on ResultMessage,
    S1). That is the point: this pins the handler's behaviour for a stream that
    does not, rather than resting on someone else's generator ending.
    """

    class ResultThenParks(FakeClient):
        async def receive_response(self):
            for msg in _normal_turn():
                yield msg
            await asyncio.Event().wait()  # never produces anything more

    client = ResultThenParks()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.5

    gen = session.send("hi")
    with pytest.raises(RunTimeout):
        [e async for e in gen]

    turn = session.last_turn
    assert turn.outcome is not None and turn.outcome.result == "done"
    assert session.turns == 1
    assert session._turn_abandoned is False


async def test_turns_counts_only_turns_that_reached_a_result(
    settings: Settings,
) -> None:
    """The fold-in. `turns` used to be incremented in the postscript and
    nowhere else, so a drain that ended WITHOUT a ResultMessage counted while a
    turn that raised did not -- and the straddle above lost a turn that
    genuinely completed. One meaning now: turns that reached a result, which is
    what `_turn_seq`'s comment has always claimed `turns` means."""

    class Resultless(FakeClient):
        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "s"})

    class Raiser(FakeClient):
        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "s"})
            raise RuntimeError("boom")

    resultless = make_session(settings, Resultless([]))
    await resultless.open()
    [e async for e in resultless.send("hi")]
    assert resultless.turns == 0
    assert resultless.last_turn.outcome is None  # recorded, just empty

    raiser = make_session(settings, Raiser([]))
    await raiser.open()
    with pytest.raises(RuntimeError):
        [e async for e in raiser.send("hi")]
    assert raiser.turns == 0


# --- follow-up item 4: the turn teardown was a third unbounded wait ---------


async def test_close_is_bounded_when_the_turn_teardown_never_completes(
    settings: Settings,
) -> None:
    """`await gen.aclose()` had no bound, so `close()`'s "every wait is bounded
    by one timeout_s deadline" claim -- which `registry.py` rests its
    registry-wide lock on -- held only by accident of the pinned SDK's teardown
    having no await on its unwind path. Made true by construction instead.

    The consumer task is created and awaited to completion FIRST, and that is
    load-bearing. The turn's own dangling `asyncio.timeout` cancels whichever
    task made the FIRST advance, so if `close()` runs in that same task it
    rescues itself and the missing bound never shows -- measured: this test
    passes against the round-5 code when close() shares the consumer's task.
    Once that task has exited, `.cancel()` is a no-op and nothing else is
    coming; against the round-5 code `close()` then never returns.
    """

    class StuckTeardown(FakeClient):
        async def receive_response(self):
            try:
                for msg in _normal_turn():
                    yield msg
            finally:
                await asyncio.Event().wait()  # the unwind never finishes

    client = StuckTeardown()
    session = make_session(settings, client)
    await session.open()
    session._limits.timeout_s = 0.1

    gen = session.send("hi")

    async def consumer() -> None:
        await gen.__anext__()  # advance once, then abandon -- and exit

    await asyncio.create_task(consumer())
    assert session.status == "running"

    t0 = time.monotonic()
    await asyncio.wait_for(session.close(), timeout=2.0)
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0
    assert session.status == "closed"
    assert client.disconnected is True


# --- fix round 6: the courtesy interrupt's two bounds --------------------------


class _NeverAnsweringControlClient(_ParkedClient):
    """A CLI whose control channel accepts requests and never answers.

    `_ParkedClient` for the conversation side, so `_abandon_mid_drain` can set
    up the abandoned turn these tests need in the way a real SSE hangup does.

    Distinct from `_WedgedControlClient`, which gives up after 0.4s of its own:
    the point of these tests is what happens when NOTHING but this service's
    own bound ends the wait, which is also the case `_STALE_INTERRUPT_BUDGET_S`
    exists for (the SDK's 60s bound is far longer than anything a registry
    operation can afford to wait behind).
    """

    async def interrupt(self) -> None:
        self.interrupts += 1
        await asyncio.Event().wait()


async def test_acquire_lock_now_gives_up_when_a_waiter_is_already_queued(
    settings: Settings,
) -> None:
    """The state `self._lock.locked()` alone gets wrong.

    `asyncio.Lock` is FIFO-fair: `release()` clears `_locked` and wakes the
    first waiter, but that waiter does not resume until it is scheduled, so
    there is a real window where the lock reads UNLOCKED and `acquire()` will
    nonetheless suspend -- behind that waiter, i.e. behind a whole turn. That
    is why `_acquire_lock_now` bounds the acquisition at zero instead of
    checking `locked()` and awaiting.

    Mutation-verified: replacing the body with `if self._lock.locked(): return
    False` + a bare `await self._lock.acquire()` leaves the rest of the suite
    green and hangs here (the `wait_for` below is what turns that hang into a
    failure). Confirmed against CPython 3.13's `asyncio/locks.py`, whose
    `acquire()` fast path requires BOTH `not self._locked` AND every queued
    waiter cancelled.
    """
    session = make_session(settings, FakeClient([]))
    await session.open()

    await session._lock.acquire()
    waiter = asyncio.create_task(session._lock.acquire())
    await asyncio.sleep(0)  # the waiter is now queued on the lock
    session._lock.release()  # ...and the lock reads unlocked while it sleeps
    assert session._lock.locked() is False

    got = await asyncio.wait_for(session._acquire_lock_now(), timeout=1.0)
    assert got is False, (
        "an unlocked lock with a live waiter must be treated as unavailable -- "
        "acquiring it means queueing behind that waiter"
    )

    await asyncio.wait_for(waiter, timeout=1.0)
    session._lock.release()


async def test_the_abandoned_turn_branch_gives_up_rather_than_queueing(
    settings: Settings,
) -> None:
    """The same window, through `interrupt()` itself: no control request goes
    out, and nothing waits."""
    session = make_session(settings, FakeClient([]))
    await session.open()
    session._turn_abandoned = True

    await session._lock.acquire()
    waiter = asyncio.create_task(session._lock.acquire())
    await asyncio.sleep(0)
    session._lock.release()

    assert await asyncio.wait_for(session.interrupt(), timeout=1.0) is False
    assert session._client.interrupts == 0
    # Not consumed either: nothing was asked to stop, so the condition stands.
    assert session._turn_abandoned is True

    await asyncio.wait_for(waiter, timeout=1.0)
    session._lock.release()


async def test_an_unanswered_courtesy_interrupt_is_a_504_with_a_detail(
    settings: Settings,
) -> None:
    """What the caller is told when the bound bites.

    A bare `TimeoutError` reached `errors.to_problem`'s 500 fallthrough as
    `{'title': 'Internal server error', 'detail': ''}` -- `str(TimeoutError())`
    is `''` -- which is strictly less than the SDK's own
    `Exception("Control request timeout: interrupt")` said before this branch
    was bounded at all. A time-budget overrun is a 504 everywhere else here
    (`RunTimeout`; `SessionOpenTimeout` is commented "Same bucket").
    """
    from agent_service.errors import to_problem

    client = _NeverAnsweringControlClient()
    session = make_session(settings, client)
    await session.open()
    session._turn_abandoned = True

    with pytest.raises(InterruptTimeout) as caught:
        await session.interrupt()

    problem = to_problem(caught.value)
    assert problem.status == 504
    assert problem.title == "Interrupt was not answered in time"
    assert str(_STALE_INTERRUPT_BUDGET_S) in problem.detail
    assert problem.detail  # the thing the 500 fallthrough lost


# --- fix round 7: close() commits before it can prove the session is gone ----
#
# `status = "closed"` is assigned only AFTER a successful `disconnect()`, so
# that a FAILED disconnect leaves the session non-terminal and a retried DELETE
# genuinely retries (pinned by
# test_close_does_not_report_success_when_disconnect_fails, which is also what
# kills the obvious "hoist the assignment" fix). While `close()` is suspended
# inside `disconnect()` the session therefore still reads `"idle"` -- and fix
# round 6 WIDENED that window by letting `close()` skip the lock when a
# courtesy interrupt holds it, so the lock can fall free mid-disconnect.
# Measured against round 6: `queries == ['hi', 'second turn']`, `turns=1` -- a
# whole turn ran against a session being torn down, putting `disconnect()`
# against a draining turn, which `registry.py` records as unmeasured.


class _GatedDisconnectClient(_NeverAnsweringControlClient):
    """A control channel that answers on demand, and a disconnect that
    SUSPENDS -- as the real `ClaudeSDKClient.disconnect()` does."""

    def __init__(self) -> None:
        super().__init__(later_turns=[_normal_turn()])
        self.control_gate = asyncio.Event()
        self.disconnect_gate = asyncio.Event()
        self.disconnect_entered = asyncio.Event()
        self.usage_calls = 0

    async def get_context_usage(self):
        self.usage_calls += 1
        return {"categories": [{"name": "Messages", "tokens": 7}]}

    async def interrupt(self) -> None:
        self.interrupts += 1
        await self.control_gate.wait()

    async def disconnect(self) -> None:
        self.disconnect_entered.set()
        await self.disconnect_gate.wait()
        self.disconnected = True


async def test_a_turn_cannot_start_while_close_is_disconnecting(
    settings: Settings,
) -> None:
    """Why `_closing` exists at all, and why `status` cannot replace it.

    `status = "closed"` is assigned only AFTER `disconnect()` returns, so a
    FAILED disconnect stays retryable (see
    `test_close_does_not_report_success_when_disconnect_fails`, which kills the
    obvious "just hoist the assignment" fix). That leaves a real window --
    `close()` suspended inside `disconnect()` with `status` still `"idle"` --
    which was WIDENED once `close()` began skipping the lock for a courtesy
    interrupt, because the lock can then fall free mid-disconnect.

    Measured in that window before `_closing` existed: a whole turn ran to
    completion against a session being torn down (`queries == ['hi', 'second
    turn']`, `turns=1`), putting `disconnect()` against a draining turn --
    behaviour `registry.py` explicitly records as unmeasured.

    This pins the BEHAVIOUR rather than either guard. `_send_impl` checks
    `_closing` twice, pre-lock and in-lock, and neither check is individually
    test-killable: deleting `or self._closing` from either one alone leaves the
    suite green, because a first advance can only suspend between them by
    queueing behind `close()` itself, which implies `_closing` is already set.
    Removing BOTH is what this test catches. Do not chase the halves
    separately; see CP-006
    """
    client = _GatedDisconnectClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)

    interrupt_task = asyncio.create_task(session.interrupt())
    await asyncio.sleep(0.01)
    assert session._courtesy_interrupt is True
    assert session._lock.locked() is True

    close_task = asyncio.create_task(session.close())
    await asyncio.wait_for(client.disconnect_entered.wait(), timeout=1.0)
    # The window: close() skipped the lock and is inside disconnect(), and
    # `status` is deliberately NOT terminal yet.
    assert session.status == "idle"

    client.control_gate.set()  # the courtesy interrupt finishes...
    await asyncio.sleep(0.01)  # ...and hands back the lock
    assert session._lock.locked() is False

    with pytest.raises(SessionClosed):
        [e async for e in session.send("second turn")]
    # Likewise for the other two ways in.
    with pytest.raises(SessionClosed):
        await session.set_model("claude-opus-5")
    assert await session.interrupt() is False

    client.disconnect_gate.set()
    await asyncio.wait_for(close_task, timeout=1.0)
    await asyncio.wait_for(interrupt_task, timeout=1.0)

    assert client.queries == ["hi"]  # the second turn never reached the SDK
    assert session.turns == 0
    assert session.status == "closed"


async def test_a_failed_close_still_refuses_new_turns(settings: Settings) -> None:
    """`_closing` is a ONE-WAY latch, and this is the consequence worth stating.

    A failed `disconnect()` leaves the session non-terminal and registered so
    the DELETE can be retried -- but that is a retry of the CLOSE, not a
    resumption of the session. The subprocess may be in any state, and the
    operator has already said to tear it down, so new turns get the same 409
    they would get after a successful close rather than running against a
    client whose teardown failed halfway.
    """

    class FlakyDisconnect(FakeClient):
        async def disconnect(self) -> None:
            raise OSError("subprocess kill failed")

    client = FlakyDisconnect([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    with pytest.raises(OSError, match="subprocess kill failed"):
        await session.close()
    assert session.status != "closed"  # still retryable, as round 5 requires

    with pytest.raises(SessionClosed):
        [e async for e in session.send("hi")]
    assert client.queries == []


# -- mutation pins ------------------------------------------------------------
#
# Rounds 2 and 3 of Plan 2 were BOTH published-at-the-wrong-moment defects
# (`_active_gen` stashed eagerly, then stashed outside the lock), so the
# publication points of `_courtesy_interrupt` get the same treatment here
# rather than being left to inspection.


async def test_the_courtesy_flag_is_not_published_when_the_lock_is_unavailable(
    settings: Settings,
) -> None:
    """Publishing `_courtesy_interrupt` BEFORE `_acquire_lock_now()` latches it
    forever whenever the lock is unavailable -- and nothing ever clears it,
    because the `finally` that would is never entered. Every later `close()`
    then skips the lock, INCLUDING for a genuinely running turn: the exact
    "close() disconnects out from under a draining turn" this module has
    refused to do since fix round 1.
    """
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            await release.wait()
            for msg in _normal_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    # A turn owns the lock; a courtesy interrupt therefore cannot have it.
    turn_task = asyncio.create_task(_drain(session, "one"))
    await asyncio.sleep(0)
    assert session._lock.locked() is True
    session._turn_abandoned = True
    session.status = "idle"  # force branch 2 rather than the running branch

    assert await session.interrupt() is False
    assert session._courtesy_interrupt is False, (
        "the flag must be published only after the lock is actually held -- "
        "publishing it first latches it forever on this path"
    )

    # ...and the consequence, asserted rather than argued: close() still waits
    # for the turn instead of disconnecting out from under it.
    session.status = "running"
    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0.02)
    assert client.disconnected is False

    release.set()
    await asyncio.wait_for(turn_task, timeout=1.0)
    await asyncio.wait_for(close_task, timeout=1.0)
    assert client.disconnected is True


async def test_the_courtesy_flag_never_outlives_the_lock_it_describes(
    settings: Settings,
) -> None:
    """`_courtesy_interrupt` is cleared BEFORE `release()`, in the same
    `finally`, with no suspension point between them -- so no other task can
    ever observe "flag set, lock free". That pairing is what lets `close()`
    read the flag and conclude the lock is held by a courtesy interrupt rather
    than by a turn; clearing it after the release (or across an await) breaks
    that inference and `close()` would skip the lock for a REAL turn.

    A watcher samples the pair on every event-loop tick for the whole life of
    the interrupt, which is the only way to catch a window that exists between
    two adjacent statements.
    """
    client = _NeverAnsweringControlClient()
    session = make_session(settings, client)
    await session.open()
    session._turn_abandoned = True

    bad: list[tuple[bool, bool]] = []
    stop = asyncio.Event()

    async def watcher() -> None:
        while not stop.is_set():
            pair = (session._courtesy_interrupt, session._lock.locked())
            if pair == (True, False):
                bad.append(pair)
            await asyncio.sleep(0)

    watch = asyncio.create_task(watcher())
    with pytest.raises(InterruptTimeout):
        await session.interrupt()
    stop.set()
    await watch

    assert bad == [], "observed `_courtesy_interrupt` set while the lock was free"
    assert session._courtesy_interrupt is False
    assert session._lock.locked() is False


async def test_close_takes_the_lock_when_no_courtesy_interrupt_holds_it(
    settings: Settings,
) -> None:
    """`close()` skips the lock ONLY for a courtesy interrupt.

    Deleting the `_courtesy_interrupt` condition (`if True:`) survives every
    other test in this file, because the cases they build either have no lock
    holder by then or keep `_finalize_live_turn` busy until the deadline. This
    builds the case that distinguishes them: the lock held by something that is
    NOT a courtesy interrupt and NOT the live turn's generator, where
    `_finalize_live_turn` returns immediately and only the lock acquisition
    stands between `close()` and `disconnect()`.
    """
    client = FakeClient([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    await session._lock.acquire()  # stands in for any non-courtesy holder
    assert session._courtesy_interrupt is False

    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0.02)
    assert client.disconnected is False, (
        "close() must wait for a lock it cannot prove is held by a courtesy "
        "interrupt"
    )

    session._lock.release()
    await asyncio.wait_for(close_task, timeout=1.0)
    assert client.disconnected is True
    assert session.status == "closed"


async def test_the_courtesy_budget_is_about_a_second(settings: Settings) -> None:
    """The MAGNITUDE, pinned against literals rather than against the constant.

    Every other assertion about this budget reads `_STALE_INTERRUPT_BUDGET_S`
    or `timeout_s / 10`, so raising the constant to 10.0 keeps them all green
    while a session spends ten seconds refusing turns -- and, before `close()`
    stopped waiting for it, spent ten seconds of registry-wide lock with it.
    The value is a judgement about how long a healthy control round-trip takes
    (milliseconds), so it is pinned as such.
    """
    assert 0.5 <= _STALE_INTERRUPT_BUDGET_S <= 2.0

    client = _NeverAnsweringControlClient()
    session = make_session(settings, client)
    await session.open()
    session._turn_abandoned = True

    t0 = time.monotonic()
    with pytest.raises(InterruptTimeout):
        await session.interrupt()
    assert time.monotonic() - t0 < 2.5


# --- fix round 8: context_usage() was the one hole in the `_closing` latch ---
#
# `_closing`'s own comment claims the session "takes no new work of any kind"
# once close() has committed. `context_usage()` had NEITHER guard the setters
# have, so it ran a live control request down a client being torn down --
# exactly what `set_model`'s docstring exists to prevent -- and reported an
# "idle" session that answered PATCH and POST with 409 in the same instant.
# Measured over real ASGI against 97929a5:
#
#   GET 200 status='idle' usage={'categories': [...]} control_requests=1
#     | PATCH 409 'Session closed' | POST 409 'Session closed'
#
# It returns None rather than raising, because a READ of a session being torn
# down is a legitimate question with a true answer; see the method's docstring.


async def test_context_usage_asks_nothing_of_a_session_being_torn_down(
    settings: Settings,
) -> None:
    client = _GatedDisconnectClient()
    session = make_session(settings, client)
    await session.open()
    await _abandon_mid_drain(session, client)

    interrupt_task = asyncio.create_task(session.interrupt())
    await asyncio.sleep(0.01)
    close_task = asyncio.create_task(session.close())
    await asyncio.wait_for(client.disconnect_entered.wait(), timeout=1.0)

    # The window: close() has committed, `status` is deliberately not terminal
    # yet, and the client is mid-disconnect.
    assert session._closing is True
    assert session.status == "idle"

    try:
        assert await session.context_usage() is None
        assert client.usage_calls == 0
    finally:
        # In a `finally` so a FAILING assertion still ends the teardown: both
        # tasks are parked on these gates, and leaving them parked turns a
        # clean failure into a hung test (observed against 97929a5, where this
        # test correctly fails -- exit 124 rather than a reported assertion).
        client.control_gate.set()
        client.disconnect_gate.set()
        await asyncio.wait_for(close_task, timeout=1.0)
        await asyncio.wait_for(interrupt_task, timeout=1.0)

    # ...and afterwards, for the same reason.
    assert await session.context_usage() is None
    assert client.usage_calls == 0


async def test_context_usage_still_asks_a_live_session(settings: Settings) -> None:
    """The guard keys off teardown only. A live session -- including one whose
    control channel is wedged, which is what the route's declared 502 is for --
    must still be asked."""
    client = _GatedDisconnectClient()
    session = make_session(settings, client)
    await session.open()

    usage = await session.context_usage()
    assert usage["categories"][0]["name"] == "Messages"
    assert client.usage_calls == 1


# --- follow-up items 12, 13, 14: what the session knows and would not say ---
#
# Item 14 -- per-turn cost -- is a DELTA against the running total, computed
# where both numbers are in hand. `total_cost_usd` itself is untouched: it is
# cumulative for the whole connection (measured, S6) and the code assigns
# rather than sums, which stays true.


async def test_a_turn_records_its_own_cost_as_a_delta(settings: Settings) -> None:
    """Item 14. Three turns off ONE connection, cumulative as the SDK reports
    it (S6: three real turns came back 0.0926565, 0.100344, 0.10803255).

    The first turn's delta is the whole cumulative value, because the running
    total starts at 0.0 -- there is no earlier turn to difference against.
    """
    turns = []
    for total in (0.05, 0.08, 0.15):
        turn = _normal_turn()
        turn[-1] = _result(total_cost_usd=total)
        turns.append(turn)

    session = make_session(settings, FakeClient(turns))
    await session.open()

    [e async for e in session.send("one")]
    assert session.total_cost_usd == pytest.approx(0.05)
    assert session.last_turn.turn_cost_usd == pytest.approx(0.05)

    [e async for e in session.send("two")]
    assert session.total_cost_usd == pytest.approx(0.08)
    assert session.last_turn.turn_cost_usd == pytest.approx(0.03)

    [e async for e in session.send("three")]
    assert session.total_cost_usd == pytest.approx(0.15)
    assert session.last_turn.turn_cost_usd == pytest.approx(0.07)


async def test_an_unpriced_turn_leaves_the_session_running_total_where_it_was(
    settings: Settings,
) -> None:
    """A DECISION, not an accident of the arithmetic.

    `SessionRecord.total_cost_usd` stays a plain `float` while the per-turn
    fields became nullable, because it is an aggregate: in a session that
    priced some turns and not others, `null` would throw away the cost that IS
    known. So an unpriced turn contributes nothing and the running total keeps
    its previous value -- the field is documented as a floor, and this is the
    second measured reason it is one (the first being an interrupted turn).

    The per-turn answer is still `null`, never `0.0`.
    """
    priced = _normal_turn()
    priced[-1] = _result(total_cost_usd=0.05)

    session = make_session(settings, FakeClient([priced, _unpriced_turn()]))
    await session.open()
    [e async for e in session.send("one")]
    assert session.total_cost_usd == 0.05

    [e async for e in session.send("two")]
    # The floor is unchanged -- NOT reset, NOT advanced by a meaningless zero.
    assert session.total_cost_usd == 0.05
    assert session.last_turn is not None
    # And the turn itself says "nobody can say" rather than "free".
    assert session.last_turn.turn_cost_usd is None
    assert session.last_turn.outcome is not None
    assert session.last_turn.outcome.total_cost_usd is None
    # The empty shape is still reported, for whoever has to diagnose it.
    assert session.last_turn.outcome.model_usage == {}


async def test_the_delta_is_taken_before_the_running_total_is_updated(
    settings: Settings,
) -> None:
    """The specific way to get item 14 wrong: read `self.total_cost_usd` AFTER
    assigning the new cumulative value, which makes every delta 0.0.

    A single-turn test cannot fail on that, because the running total starts
    at 0.0 and the first turn's delta equals its cumulative value either way.
    The SECOND turn is what discriminates, so this test exists as its named
    guard.
    """
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.05)
    turn_two = _normal_turn()
    turn_two[-1] = _result(total_cost_usd=0.09)

    session = make_session(settings, FakeClient([turn_one, turn_two]))
    await session.open()
    [e async for e in session.send("one")]
    [e async for e in session.send("two")]

    assert session.last_turn.turn_cost_usd == pytest.approx(0.04)


async def test_a_turn_the_sdk_priced_the_same_is_a_zero_delta_not_unknown(
    settings: Settings,
) -> None:
    """`turn_cost_usd == 0.0` and `turn_cost_usd is None` are different
    answers: "this turn cost nothing" versus "nobody can say". A ResultMessage
    whose cumulative total is unchanged from the previous turn is the first,
    and must not collapse into the second."""
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.05)
    turn_two = _normal_turn()
    turn_two[-1] = _result(total_cost_usd=0.05)

    session = make_session(settings, FakeClient([turn_one, turn_two]))
    await session.open()
    [e async for e in session.send("one")]
    [e async for e in session.send("two")]

    assert session.last_turn.turn_cost_usd is not None
    assert session.last_turn.turn_cost_usd == pytest.approx(0.0)


async def test_a_turn_the_sdk_priced_at_zero_is_free_not_unknown(
    settings: Settings,
) -> None:
    """The `is not None` guard on the SDK's own price, pinned (review pin 1).

    Relaxing `if outcome.total_cost_usd is not None` to a truthiness test
    survived the whole suite: `total_cost_usd == 0.0` is a realistic
    ResultMessage value, and under that mutant the turn reports
    `turn_cost_usd: null` -- "nobody can say" -- for a turn the SDK
    explicitly priced at nothing. That is precisely the distinction item 14
    exists to draw, inverted.

    `..._priced_the_same_is_a_zero_delta_not_unknown` above does NOT cover
    this: it produces a zero DELTA from two non-zero cumulative figures, so
    `outcome.total_cost_usd` is truthy on both of its turns and the guard is
    never exercised. This one produces a zero SOURCE.
    """
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.0)
    turn_two = _normal_turn()
    turn_two[-1] = _result(total_cost_usd=0.0)

    session = make_session(settings, FakeClient([turn_one, turn_two]))
    await session.open()

    [e async for e in session.send("one")]
    assert session.last_turn.turn_cost_usd is not None
    assert session.last_turn.turn_cost_usd == pytest.approx(0.0)
    assert session.total_cost_usd == pytest.approx(0.0)

    # And again on a later turn, where the running total is no longer the
    # 0.0 it was initialised to -- it has been ASSIGNED 0.0 by turn one, and
    # the guard must still hold.
    [e async for e in session.send("two")]
    assert session.last_turn.turn_cost_usd is not None
    assert session.last_turn.turn_cost_usd == pytest.approx(0.0)


# --- the interrupted turn is unattributed, not free -------------------------
# Measured live (CP-070): an
# aborted turn comes back with `usage` all-zero, `iterations: []`, `model_usage`
# still holding the connection's totals from EARLIER COMPLETED turns, and
# `total_cost_usd` unmoved -- while the CLI ran ~8s of streamed inference. The
# cost is LOST, not deferred: the next completed turn's delta is exactly its own
# usage priced. So the honest report is `null`, not `0.0`.


async def test_an_interrupted_turn_reports_no_cost_rather_than_zero(
    settings: Settings,
) -> None:
    """The defect. A turn that was interrupted and whose cumulative did not
    move reported `turn_cost_usd: 0.0` -- item 14's "this turn was free" -- for
    a turn measured to consume real tokens.

    Kills the mutant that deletes the `aborted and delta == 0.0` guard
    entirely, which is what the code did before.
    """
    first = _normal_turn()
    first[-1] = _result(total_cost_usd=0.05)
    aborted = _interrupted_turn()
    aborted[-1] = _result(
        subtype="error_during_execution",
        is_error=True,
        terminal_reason="aborted_streaming",
        result=None,
        total_cost_usd=0.05,  # unmoved, exactly as measured
    )

    client = FakeClient([first, aborted])
    session = make_session(settings, client)
    await session.open()

    [e async for e in session.send("one")]
    assert session.last_turn.turn_cost_usd == pytest.approx(0.05)

    gen = session.send("two")
    assert await gen.__anext__()  # the init message; the turn is now running
    await session.interrupt()
    async for _ in gen:
        pass

    assert session.last_turn.interrupted is True
    assert session.last_turn.turn_cost_usd is None
    # The running total is untouched by this change: still ASSIGNED the SDK's
    # cumulative figure (S6), never summed, and the turn still counted.
    assert session.total_cost_usd == pytest.approx(0.05)
    assert session.turns == 2


async def test_an_aborted_turn_nobody_asked_to_stop_also_reports_no_cost(
    settings: Settings,
) -> None:
    """The guard keys off the ABORTED shape, not off our interrupt stamp.

    Kills the mutant that writes `if interrupt_requested and delta == 0.0`:
    an aborted turn nobody asked to stop is a crash, and its cost is exactly as
    unattributed as an interrupt's. `interrupted` stays False -- that
    distinction is a different field's job and must not move.
    """
    first = _normal_turn()
    first[-1] = _result(total_cost_usd=0.05)
    crashed = _interrupted_turn()
    crashed[-1] = _result(
        subtype="error_during_execution",
        is_error=True,
        terminal_reason="aborted_tools",
        result=None,
        total_cost_usd=0.05,
    )

    session = make_session(settings, FakeClient([first, crashed]))
    await session.open()
    [e async for e in session.send("one")]
    [e async for e in session.send("two")]

    assert session.last_turn.interrupted is False
    assert session.last_turn.turn_cost_usd is None


async def test_an_aborted_turn_whose_cumulative_did_move_still_reports_the_delta(
    settings: Settings,
) -> None:
    """The `delta == 0.0` conjunct, pinned.

    Kills the mutant that writes a bare `if aborted:`. An aborted turn CAN
    carry a real price -- the SDK moved its cumulative figure, so that much of
    the turn is attributed and must be reported rather than thrown away as
    "nobody can say".

    The complementary mutant -- a bare `if delta == 0.0:`, dropping `aborted`
    -- is killed by test_a_turn_the_sdk_priced_the_same_is_a_zero_delta_not_
    unknown above, where two COMPLETED turns priced the same must still report
    a genuine 0.0.
    """
    first = _normal_turn()
    first[-1] = _result(total_cost_usd=0.05)
    aborted = _interrupted_turn()
    aborted[-1] = _result(
        subtype="error_during_execution",
        is_error=True,
        terminal_reason="aborted_streaming",
        result=None,
        total_cost_usd=0.09,
    )

    session = make_session(settings, FakeClient([first, aborted]))
    await session.open()
    [e async for e in session.send("one")]
    [e async for e in session.send("two")]

    assert session.last_turn.turn_cost_usd == pytest.approx(0.04)
    assert session.total_cost_usd == pytest.approx(0.09)


async def test_a_limit_stopped_turn_is_not_treated_as_an_aborted_one(
    settings: Settings,
) -> None:
    """The guard is scoped to the MEASURED aborted set, not to "anything that
    did not complete".

    Kills the mutant that widens the condition to
    `outcome.terminal_reason != "completed"`, which survived the first
    mutation round. A guardrail stop is a DIFFERENT shape: measured live, the
    budget stop moved the cumulative and grew `model_usage` like any ordinary
    turn, so its zero delta -- when it has one -- means what a zero delta
    always meant. Swallowing it as `null` would throw away a real answer, and
    would do so for `max_turns` stops too.
    """
    first = _normal_turn()
    first[-1] = _result(total_cost_usd=0.05)
    capped = _normal_turn()
    capped[-1] = _result(
        subtype="error_max_budget_usd",
        is_error=True,
        terminal_reason="budget_exhausted",
        result=None,
        total_cost_usd=0.05,
    )

    session = make_session(settings, FakeClient([first, capped]))
    await session.open()
    [e async for e in session.send("one")]
    [e async for e in session.send("two")]

    assert session.last_turn.outcome.limit_hit == "budget"
    assert session.last_turn.turn_cost_usd is not None
    assert session.last_turn.turn_cost_usd == pytest.approx(0.0)


async def test_a_turn_with_no_result_message_reports_no_cost_at_all(
    settings: Settings,
) -> None:
    """A drain that ends without a ResultMessage has no outcome, so there is
    no cumulative value to difference and nothing honest to report. `None`,
    not 0.0 -- 0.0 would claim the turn was free."""

    class NoResultClient(FakeClient):
        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})

    session = make_session(settings, NoResultClient())
    await session.open()
    [e async for e in session.send("one")]

    assert session.last_turn.outcome is None
    assert session.last_turn.turn_cost_usd is None


async def test_a_result_message_without_a_price_reports_no_cost(
    settings: Settings,
) -> None:
    """`ResultMessage.total_cost_usd` is optional. A turn that reached a result
    but carried no price is still "nobody can say", and the running total must
    not move.

    **`None` rather than `0.0` since 2026-08-09**: the session starts unpriced,
    and a turn that reported no price leaves it unpriced. `0.0` would be a claim
    that a turn ran for free, which is the shape AS-17a rejects.
    """
    turn = _normal_turn()
    turn[-1] = _result(total_cost_usd=None)

    session = make_session(settings, FakeClient([turn]))
    await session.open()
    [e async for e in session.send("one")]

    assert session.last_turn.outcome is not None
    assert session.last_turn.turn_cost_usd is None
    assert session.total_cost_usd is None


async def test_a_timed_out_turn_reports_no_cost(settings: Settings) -> None:
    class HangingClient(FakeClient):
        async def receive_response(self):
            await asyncio.Event().wait()
            yield  # pragma: no cover - unreachable; keeps this a generator

    session = make_session(settings, HangingClient())
    await session.open()
    session._limits.timeout_s = 0.5

    with pytest.raises(RunTimeout):
        [e async for e in session.send("hang forever")]

    assert session.last_turn.timed_out is True
    assert session.last_turn.turn_cost_usd is None


async def test_the_residue_count_describes_the_current_turn_not_an_older_one(
    settings: Settings,
) -> None:
    """Item 12's second half. `last_residue_discarded` was only ever WRITTEN
    inside the `if self._residue_suspected:` branch, so once an abnormal turn
    left a count behind, every subsequent normal turn kept reporting it -- a
    stale number describing a turn two turns ago, on a field whose whole
    purpose is observability.

    Turn 1 is abandoned mid-drain, leaving two messages queued. Turn 2
    pre-drains them and reports 2. Turn 3 is entirely ordinary and must report
    0.
    """
    turn_one = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="one")], model="claude-sonnet-5"),
        _result(result="TURN ONE"),
    ]
    client = SharedStreamClient([turn_one, _normal_turn(), _normal_turn()])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("one")
    await gen.__anext__()
    await gen.aclose()

    [e async for e in session.send("two")]
    assert session.last_residue_discarded == 2

    [e async for e in session.send("three")]
    assert session.last_residue_discarded == 0


async def test_the_residue_count_is_reset_even_when_the_turn_then_fails(
    settings: Settings,
) -> None:
    """The reset happens at the TOP of the turn, before anything can go wrong,
    so a turn that raises still describes itself rather than its predecessor.
    A reset on the success path only would leave the stale value standing for
    exactly the abnormal turns this field is about."""
    turn_one = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="one")], model="claude-sonnet-5"),
        _result(result="TURN ONE"),
    ]
    client = SharedStreamClient([turn_one, _normal_turn(), []])
    session = make_session(settings, client)
    await session.open()

    gen = session.send("one")
    await gen.__anext__()
    await gen.aclose()

    [e async for e in session.send("two")]
    assert session.last_residue_discarded == 2

    # Turn 3: nothing queued (so nothing to discard), and it dies mid-drain.
    class Boom(Exception):
        pass

    async def exploding_receive():
        yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
        raise Boom("mid-drain failure")

    client.receive_response = exploding_receive  # type: ignore[method-assign]
    with pytest.raises(Boom):
        [e async for e in session.send("three")]

    assert session.last_residue_discarded == 0


class _ResidueThenParkClient(SharedStreamClient):
    """Turn 1 leaves residue; turn 2 pre-drains it and then parks mid-drain.

    Parking inside `receive_response()` is what holds the session lock open
    for a concurrent caller to lose to, with a KNOWN non-zero
    `last_residue_discarded` already recorded against the running turn.
    """

    def __init__(self, turns: list[list[object]]) -> None:
        super().__init__(turns)
        self.parked = asyncio.Event()
        self._responses = 0

    async def receive_response(self):
        self._responses += 1
        park_here = self._responses == 2
        while True:
            msg = self.receive.receive_nowait()
            yield msg
            if park_here:
                self.parked.set()
                await asyncio.Event().wait()  # never released
            if isinstance(msg, ResultMessage):
                return


async def test_a_rejected_concurrent_turn_does_not_wipe_the_running_turns_count(
    settings: Settings,
) -> None:
    """The "inside the lock" half of the reset's placement (review pin 2).

    Moving `self.last_residue_discarded = 0` above the `SessionBusy` check
    survived the whole suite -- and under that mutant a caller REJECTED with
    409 wipes the count belonging to the turn that is still running. The
    field would then describe a turn that never started, on a session whose
    real turn had just discarded two messages.

    `..._is_reset_even_when_the_turn_then_fails` pins the other half (before
    the first await); nothing pinned this one. The reset must happen only
    after this call has won the lock, i.e. only for a turn that is actually
    about to run.
    """
    turn_one = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        AssistantMessage(content=[TextBlock(text="one")], model="claude-sonnet-5"),
        _result(result="TURN ONE"),
    ]
    client = _ResidueThenParkClient([turn_one, _normal_turn(), _normal_turn()])
    session = make_session(settings, client)
    await session.open()

    # Turn 1: abandoned mid-drain, leaving two messages on the shared buffer.
    gen = session.send("one")
    await gen.__anext__()
    await gen.aclose()

    # Turn 2: pre-drains those two, then parks -- holding the session lock.
    async def drain() -> None:
        async for _ in session.send("two"):
            pass

    task = asyncio.create_task(drain())
    await asyncio.wait_for(client.parked.wait(), timeout=1.0)
    try:
        assert session.status == "running"
        assert session.last_residue_discarded == 2

        # Turn 3 loses the ordinary way. It must change nothing.
        with pytest.raises(SessionBusy):
            [e async for e in session.send("three")]

        assert session.last_residue_discarded == 2
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_a_session_reports_the_model_and_permission_mode_it_resolved(
    settings: Settings,
) -> None:
    """Item 13. The RESOLVED values -- what `build_options` actually handed the
    SDK -- not the request's nulls. An omitted `model` falls back to
    `settings.default_model`, and reporting `None` there would say "no model"
    for a session that certainly has one."""
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: FakeClient([])
    )
    assert session.model == settings.default_model
    assert session.permission_mode == settings.default_permission_mode

    overridden = AgentSession(
        RunOptions(model="claude-opus-5", permission_mode="plan"),
        settings,
        client_factory=lambda _opts: FakeClient([]),
    )
    assert overridden.model == "claude-opus-5"
    assert overridden.permission_mode == "plan"


async def test_setting_the_model_updates_what_the_session_reports(
    settings: Settings,
) -> None:
    """Item 13's actual complaint: PATCH writes and nothing reads back."""
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()

    await session.set_model("claude-opus-5")
    assert session.model == "claude-opus-5"
    assert client.model == "claude-opus-5"

    await session.set_permission_mode("acceptEdits")
    assert session.permission_mode == "acceptEdits"
    assert client.permission_mode == "acceptEdits"


async def test_a_failed_set_model_does_not_update_the_echo(
    settings: Settings,
) -> None:
    """The echo reports what the SDK took, not what was asked for -- so it is
    written AFTER the control request returns. Writing it before the await
    would have this session advertise a model that never reached the agent."""

    class RefusingClient(FakeClient):
        async def set_model(self, model=None) -> None:  # noqa: ANN001, ARG002
            raise RuntimeError("control request failed")

    session = make_session(settings, RefusingClient())
    await session.open()
    before = session.model

    with pytest.raises(RuntimeError):
        await session.set_model("claude-opus-5")

    assert session.model == before


# --- AgentSession.kill(): the force-kill phase, against a REAL session --------
#
# close_all()'s aggregate bound is proven in tests/test_registry.py, but every
# session there is a FAKE whose kill() sets a flag -- so the method that
# actually prevents the leaked subprocess was proven only against a stub. Five
# mutations survived the whole suite; the four below are the sessions.py half.
# Each test names the mutation it kills:
#
#   * make kill() a bare `return`            -> _disconnects_the_client_now
#   * delete `self._closing = True`          -> _refuses_new_work_before_the_disconnect_returns
#   * assign `status` BEFORE `disconnect()`  -> that same test (the in-window
#                                               assertion) and _a_failed_kill_stays_retryable
#   * (idempotence, not a mutation)          -> _is_a_no_op_on_an_already_closed_session


class _GatedKillClient(FakeClient):
    """A `disconnect()` that SUSPENDS, as the real `ClaudeSDKClient`'s does.

    The window it opens is the whole point: `kill()` is inside `disconnect()`,
    `status` is deliberately still `"idle"`, and only `_closing` stands between
    a caller and a turn started against a session being torn down.
    """

    def __init__(self) -> None:
        super().__init__([_normal_turn()])
        self.disconnect_gate = asyncio.Event()
        self.disconnect_entered = asyncio.Event()

    async def disconnect(self) -> None:
        self.disconnect_entered.set()
        await self.disconnect_gate.wait()
        await super().disconnect()


async def test_kill_disconnects_the_client_now(settings: Settings) -> None:
    """The one thing kill() is FOR. disconnect() was measured (S5) to kill the
    CLI subprocess; a kill() that does not reach it leaves that subprocess
    outliving the container, which is the failure close_all()'s whole phase 2
    exists to prevent."""
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()

    await session.kill()

    assert client.disconnects == 1, "kill() never reached the SDK"
    assert session.status == "closed"
    assert session._closing is True


async def test_kill_does_not_wait_for_the_running_turn(settings: Settings) -> None:
    """What separates kill() from close(): no turn, no lock, no courtesy.

    close() ends the live turn and takes the lock first, and every one of those
    is a WAIT. kill() is called precisely because there is no time left to
    wait, so it must disconnect while a turn still holds the lock.
    """
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            await release.wait()
            for msg in _normal_turn():
                yield msg

    client = SlowClient()
    session = make_session(settings, client)
    await session.open()

    turn_task = asyncio.create_task(_drain(session, "one"))
    await asyncio.sleep(0)
    assert session._lock.locked() is True
    assert session.status == "running"

    # Bounded: on the correct code it returns immediately; a kill() that waited
    # for the turn would hang here until `release` is set, which never happens
    # before the assertion below.
    await asyncio.wait_for(session.kill(), timeout=1.0)

    assert client.disconnects == 1
    assert session.status == "closed"

    release.set()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(turn_task, timeout=1.0)


async def test_kill_refuses_new_work_before_the_disconnect_returns(
    settings: Settings,
) -> None:
    """`_closing` is latched FIRST, and `status` is assigned LAST.

    Two assertions in one window, because the window only exists if both hold:

      * `status` is still `"idle"` while kill() is suspended inside
        `disconnect()` -- assigning `"closed"` up front would claim a teardown
        that has not happened, exactly as `close()` refuses to (see
        `test_close_does_not_report_success_when_disconnect_fails`).
      * ...which means `status` CANNOT be what keeps a turn out during it.
        `_closing` is. Without the latch a whole turn runs against a session
        being torn down, putting `disconnect()` against a draining turn --
        behaviour registry.py records as unmeasured.
    """
    client = _GatedKillClient()
    session = make_session(settings, client)
    await session.open()

    kill_task = asyncio.create_task(session.kill())
    await asyncio.wait_for(client.disconnect_entered.wait(), timeout=1.0)

    assert session.status == "idle", "kill() claimed a teardown it had not done"
    assert session._closing is True

    with pytest.raises(SessionClosed):
        [e async for e in session.send("during the kill")]
    with pytest.raises(SessionClosed):
        await session.set_model("claude-opus-5")
    assert await session.context_usage() is None

    client.disconnect_gate.set()
    await asyncio.wait_for(kill_task, timeout=1.0)

    assert client.queries == [], "a turn reached the SDK during the kill"
    assert session.turns == 0
    assert session.status == "closed"


async def test_a_failed_kill_stays_retryable(settings: Settings) -> None:
    """`status = "closed"` only after `disconnect()` RETURNS -- the same rule
    close() follows. A kill whose disconnect raises must leave the session
    non-terminal and honestly still-connected, not advertising a teardown that
    did not happen. `_closing` still latches: the operator has given up on this
    session either way."""

    class FlakyDisconnect(FakeClient):
        async def disconnect(self) -> None:
            raise OSError("subprocess kill failed")

    client = FlakyDisconnect([_normal_turn()])
    session = make_session(settings, client)
    await session.open()

    with pytest.raises(OSError, match="subprocess kill failed"):
        await session.kill()

    assert session.status != "closed"
    assert session._closing is True
    with pytest.raises(SessionClosed):
        [e async for e in session.send("hi")]


async def test_kill_is_a_no_op_on_an_already_closed_session(
    settings: Settings,
) -> None:
    """close_all() offers kill() to everything it did not close cleanly, and
    "cleanly" is decided by a task result -- so a session that closed a moment
    later can still be handed to kill(). Pushing a second `disconnect()` down an
    already-disconnected client is exactly the unmeasured SDK behaviour this
    module avoids everywhere else."""
    client = FakeClient([])
    session = make_session(settings, client)
    await session.open()
    await session.close()
    assert client.disconnects == 1

    await session.kill()

    assert client.disconnects == 1, "kill() disconnected an already-closed client"
    assert session.status == "closed"


async def test_a_session_with_no_turns_has_no_cost(settings: Settings) -> None:
    """**Measured by Agent Studio across the two builds, and this side agreed.**

    This build reported `0.0` for a zero-turn session while the Codex build
    reported `null` for the same state, and nothing published told a client
    which convention it was reading -- so a client summing spend could not tell
    *free so far* from *this build cannot price at all*.

    `null` is the honest value under AS-17a: a cost becomes KNOWN when a turn
    reports one. **It needs no new capability field**, which is the part worth
    keeping: `turns` sits in the same response, so `turns: 0` with `null` means
    "nothing has run" and `turns: 3` with `null` means "this build does not
    price".
    """
    session = make_session(settings, FakeClient([]))

    assert session.turns == 0
    assert session.total_cost_usd is None


async def test_the_first_priced_turn_is_the_whole_cumulative(settings: Settings) -> None:
    """The delta arithmetic still works from an unpriced start.

    `turn_cost_usd` is `cumulative - the session's running total`, and that
    total is now `None` before the first priced turn rather than `0.0`. The
    first turn's delta must therefore be the whole cumulative, not a TypeError
    and not `None`.
    """
    turn = _normal_turn()
    turn[-1] = _result(total_cost_usd=0.05)

    session = make_session(settings, FakeClient([turn]))
    await session.open()
    [e async for e in session.send("one")]

    assert session.total_cost_usd == 0.05
    assert session.last_turn.turn_cost_usd == 0.05
