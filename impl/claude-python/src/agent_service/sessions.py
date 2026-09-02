"""One multi-turn session: a long-lived ClaudeSDKClient plus its lifecycle.

Built on measured SDK behaviour (CP-067 cases S1-S6, CP-068 M1), not
on assumptions. The four facts that shape this module:

  * receive_response() drains exactly one turn and ends on ResultMessage (S1).
  * An interrupted turn is reported identically to a genuine failure (S2), so
    the session records its own interrupt request and labels the turn itself.
  * A concurrent query() does NOT raise; it queues silently and turns can be
    misattributed between callers. The lock is ours to enforce (S3).
  * total_cost_usd is cumulative for the connection, not per-turn (S6) -- the
    running total is assigned, never summed.

Plus one read from the SDK source: there is exactly one connection-scoped
anyio message stream per Query, so an abandoned turn's unread messages are
still there for the next turn to mistake for its own (see `_discard_residue`).

Every wait in this module is bounded. Full reasoning, the measurements behind
it and the shapes that were tried and failed:
CP-007 and the per-method
sections below it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from dataclasses import dataclass
from typing import Any, Protocol

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)

from agent_service.config import Settings
from agent_service.errors import RunTimeout
from agent_service.options import build_options
from agent_spec.db.recorder import NULL_RECORDER, RunRecorder
from agent_spec.db.outcome import RunOutcome
from agent_service.runner import (
    ABORTED_TERMINAL_REASONS,
    build_outcome,
    unattributed_abort,
)
from agent_spec.openapi.schemas import RunOptions
from agent_service.serialization import normalize, result_fields

_log = logging.getLogger(__name__)

# The measured terminal_reason for a turn stopped mid-stream (S2). Necessary
# but NOT sufficient evidence of an interrupt -- pair it with our own stamp.
# DEFINED IN runner.py and imported above, beside `unattributed_abort`, which
# both this module and the one-shot path apply: sessions.py already imports from
# runner.py, so the constant had to move that way rather than the reverse (a
# cycle). The import keeps `agent_service.sessions.ABORTED_TERMINAL_REASONS`
# resolving, so nothing that referred to it here had to change.

# Hard ceiling on the residue pre-drain (`_discard_residue`). Unreachable in
# practice -- the SDK's buffer is max_buffer_size=100 -- so this exists to make
# the loop bounded by construction, not by someone else's constructor argument.
_RESIDUE_DISCARD_LIMIT = 1000

# Retry interval for `close()`'s repeated `aclose()` attempts. The loop is
# bounded by close()'s deadline, not by this constant; on Windows the effective
# tick is ~15.5ms regardless (platform timer granularity).
# See CP-007
_ACLOSE_RETRY_INTERVAL_S = 0.005

# How long `interrupt()`'s abandoned-turn branch may hold the session lock
# waiting for its control request. A DEDICATED constant, deliberately NOT
# `self._limits.timeout_s`: borrowing the turn budget turned one ordinary SSE
# hangup into a registry-wide stall (measured 1.944s at the default timeout_s,
# and up to 600-1800s if the SDK's own 60s control bound failed to fire).
#
# Giving up is safe because the SDK writes the control request to the transport
# BEFORE awaiting the answer, so what is abandoned is the ACKNOWLEDGEMENT, not
# the interrupt -- which is why this raises `InterruptTimeout` rather than
# returning quietly. It leaks exactly one entry each in the SDK's
# `pending_control_responses`/`pending_control_results` per abandoned wait.
# RECHECK ON ANY SDK UPGRADE. Two earlier justifications for this were
# disproved by execution; both are recorded, with the measurements, at
# CP-007
_STALE_INTERRUPT_BUDGET_S = 1.0


class SessionBusy(RuntimeError):
    """A turn is already running on this session."""


class InterruptTimeout(RuntimeError):
    """An interrupt control request was not answered within its budget.

    Typed rather than the bare `TimeoutError` `asyncio.timeout` raises: a bare
    one has `str() == ''` and reaches `to_problem`'s 500 fallthrough with an
    empty detail, and a time-budget overrun is a 504 everywhere else here.
    See CP-008
    """


class SessionClosed(RuntimeError):
    """The session has been closed and cannot accept further turns."""


@dataclass(slots=True)
class TurnResult:
    """Satisfies runner.OutcomeSource so `_summary` works unchanged."""

    session_id: str | None = None
    outcome: RunOutcome | None = None
    interrupted: bool = False
    timed_out: bool = False
    # What THIS turn cost, unlike `outcome.total_cost_usd`, which is the
    # connection's running total (S6). None means "nobody can say", NEVER 0.0
    # -- which now also covers an ABORTED turn whose cumulative did not move,
    # because such a turn was measurably not free, merely unattributed.
    # Differenced once, in `_record_turn`.
    # See CP-009
    turn_cost_usd: float | None = None


class ClientFactory(Protocol):
    def __call__(self, options: ClaudeAgentOptions) -> Any: ...


def _default_client_factory(options: ClaudeAgentOptions) -> ClaudeSDKClient:
    return ClaudeSDKClient(options=options)


class AgentSession:
    """One conversation. Not safe to iterate `send()` concurrently -- that is
    what the lock prevents, and why a second caller gets SessionBusy."""

    def __init__(
        self,
        options: RunOptions,
        settings: Settings,
        *,
        title: str | None = None,
        client_factory: ClientFactory | None = None,
        recorder: RunRecorder | None = None,
        session_store: Any | None = None,
        sdk_session_id: str | None = None,
    ) -> None:
        self._recorder = recorder or NULL_RECORDER
        # A.2 is wired for SESSIONS only, not for one-shot `/v1/query`. A
        # one-shot run has no conversation to continue, which is the whole
        # purpose of the store; plan-03 Task 7 resumes from it.
        sdk_options, self._limits = build_options(
            options, settings, session_store, sdk_session_id
        )
        self._client = (client_factory or _default_client_factory)(sdk_options)
        self._include_raw = (
            settings.include_raw_events if options.include_raw is None else options.include_raw
        )
        self._lock = asyncio.Lock()
        # An interrupt is recorded against the SPECIFIC turn it was raised
        # against, never as a bare boolean -- a bare flag outlives its turn.
        # `_turn_seq` counts turns STARTED (the public `turns` counts turns
        # that reached a result), so it is a stable identity for the turn in
        # flight. See CP-010
        self._turn_seq = 0
        self._interrupt_for_turn: int | None = None
        # A turn ended without consuming its own ResultMessage: the next turn
        # must pre-drain the connection-scoped buffer first.
        self._residue_suspected = False
        # NARROWER than `_residue_suspected`, and that is the whole point: a
        # turn ended ABNORMALLY (cancelled, abandoned, force-closed, timed out
        # mid-drain), so the CLI subprocess is STILL PRODUCING it and can still
        # be told to stop. Read and consumed by `interrupt()`.
        self._turn_abandoned = False
        # Latched ONCE by `close()` when it commits to teardown, before any
        # await; never cleared. `status` CANNOT carry this -- it is still
        # "idle" while close() is suspended inside `disconnect()`, and a turn
        # measurably started and completed in that window. Read by
        # `_send_impl`, `interrupt()`'s courtesy branch, both setters and
        # `context_usage()`: once close() has committed, this session takes no
        # new work of any kind.
        # See CP-010
        self._closing = False
        # True only while `interrupt()`'s abandoned-turn branch holds
        # `self._lock` across its control request. A courtesy interrupt is not
        # a turn, so `close()` reads this and refuses to wait for it. Written
        # and cleared inside that lock, so it can never outlive it.
        self._courtesy_interrupt = False

        self.title = title
        # The RESOLVED configuration, echoed by `SessionRecord`. Read off
        # `sdk_options`, not `options`: `build_options` is where a null model
        # becomes `settings.default_model`. Kept in step by the setters, which
        # write only AFTER their control request returns. ONLY these two -- see
        # CP-010
        self.model: str | None = sdk_options.model
        self.permission_mode: str | None = sdk_options.permission_mode
        # KNOWN AT CONSTRUCTION when the caller supplied one, otherwise None
        # until the first turn's init message -- the CLI does not mint an id
        # before then (measured, X1), which is why a caller that needs the
        # mapping up front has to supply it.
        self.session_id: str | None = sdk_session_id
        # The SERVICE-side id, assigned by `registry.py` after `open()`
        # succeeds -- this object cannot know it at construction time because
        # the registry mints it only once the session is real. Stays None for a
        # session built directly in a test, which is why every read of it
        # tolerates None. Distinct from `session_id` above, which is the SDK's.
        self.sid: str | None = None
        self.status: str = "closed"
        self.created_at = time.time()
        self.last_used_at = self.created_at
        self.turns = 0
        #: **`None`, not `0.0`, and Agent Studio is why** (2026-08-09). A session
        #: with no turns used to report `0.0` here while the Codex build reported
        #: `null` for the same state, and nothing published let a client tell
        #: which convention it was reading -- so a client summing spend could not
        #: tell *free so far* from *this build cannot price*.
        #:
        #: **`None` is the honest value and it needs no new capability field.**
        #: AS-17a's rule is that `null` means NOT KNOWN, and the cost of a
        #: session becomes known when a turn reports one. What disambiguates the
        #: two builds is already in the same response: `turns: 0` with `null` is
        #: *nothing has run yet*; `turns: 3` with `null` is *this build does not
        #: price*. Studio pointed out that `turns` sits right there.
        self.total_cost_usd: float | None = None
        self.last_turn: TurnResult | None = None
        # How many stale messages the last pre-drain discarded. Observability
        # only; non-zero means a previous turn was abandoned with messages
        # still in flight. RESET at the top of every turn, so it describes the
        # current turn rather than the last abnormal one.
        self.last_residue_discarded = 0
        # The generator behind the turn currently holding `self._lock`, or None
        # between turns. Published from INSIDE `_send_impl`, after it wins the
        # lock -- publishing eagerly from `send()` let a losing `SessionBusy`
        # caller overwrite it. Read only by `close()`.
        # See CP-017
        self._active_gen: AsyncIterator[dict[str, Any]] | None = None

    # -- lifecycle --------------------------------------------------------
    async def open(self) -> None:
        await self._client.connect()
        self.status = "idle"
        self.last_used_at = time.time()

    async def close(self) -> None:
        """Idempotent. disconnect() reliably kills the subprocess (S5).

        Never disconnects out from under a running turn: racing `disconnect()`
        against an actively draining turn has never been measured, so every
        turn is given a defined way to end first.

        A live turn is either ACTIVELY DRIVEN or ABANDONED -- and that is not a
        stable property, so nothing here commits to a wait on one observation.
        `_active_gen.aclose()` is tried FIRST because it finalizes an abandoned
        turn deterministically; `interrupt()` follows only once a failed
        `aclose()` proves a turn is genuinely advancing. **That order is
        load-bearing** -- interrupting first made a wedged control channel a
        permanent cap-slot and subprocess leak.

        **Every wait is bounded by ONE `timeout_s` deadline taken at entry**,
        including the final lock acquisition, which gives up and disconnects
        WITHOUT the lock rather than deadlocking the registry. `disconnect()`
        is the one deliberate exception, and `status = "closed"` is assigned
        only after it RETURNS, so a failed disconnect stays retryable.

        The measurements, the shapes that were tried and failed, and the
        precise limits of the `CancelledError` handler below:
        CP-011
        """
        if self.status == "closed":
            return
        # Committed: no new turn, control request or setter may start. Set
        # BEFORE the first await, so there is no window between committing and
        # announcing it. `status` cannot express this -- see `_closing` above.
        self._closing = True
        # ONE deadline for every wait below, so the total is bounded by
        # timeout_s rather than each step being bounded separately.
        deadline = time.monotonic() + self._limits.timeout_s
        held = False
        try:
            if self.status == "running":
                await self._finalize_live_turn(deadline)
            if self._courtesy_interrupt and self.status != "running":
                # The lock is held by a courtesy interrupt, not by a turn. The
                # lock exists to stop close() disconnecting out from under a
                # RUNNING TURN, and there is none here -- so take the
                # disconnect-without-the-lock path immediately rather than
                # after a turn's worth of waiting (measured: waiting stalled
                # the whole registry for 1.944s off one SSE hangup).
                #
                # What stops `_send_impl` slipping in behind us is `_closing`,
                # NOT `status` -- see the correction at
                # CP-011
                held = False
            else:
                held = await self._acquire_lock_until(deadline)
            if self.status == "closed":
                return
            await self._client.disconnect()
            self.status = "closed"
        except asyncio.CancelledError:
            # A stray cancellation from an abandoned turn's dangling timeout can
            # land on any await above, and is indistinguishable from a caller
            # cancelling us -- so re-raise, but try not to leave the session
            # connected and unreclaimable. BEST EFFORT, not a guarantee: if the
            # disconnect below also fails, the session is left non-terminal and
            # still connected until a retried DELETE arrives.
            # See CP-011
            with suppress(Exception):
                await self._client.disconnect()
                self.status = "closed"
            raise
        finally:
            if held:
                self._lock.release()

    async def kill(self) -> None:
        """Last resort: disconnect NOW. No turn, no lock, no courtesy.

        NOT a substitute for `close()`, and not reachable from the HTTP API.
        The one caller is `SessionRegistry.close_all()`, after a session has
        already failed to close inside the shutdown budget -- where the choice
        is no longer "clean or dirty teardown" but "dirty teardown or a
        subprocess that outlives the container".

        Everything `close()` does that this skips is a WAIT, and this is called
        precisely because there is none left. **`kill()` is unbounded on
        purpose** -- `disconnect()` is not a wait that can be shortened, so the
        caller bounds it instead.

        Two invariants it does keep: `_closing` is latched first, so nothing
        can start behind it; and `status` is assigned only after `disconnect()`
        RETURNS, so a failed kill leaves the session honestly still-connected
        rather than claiming a teardown that did not happen.

        See CP-012
        """
        if self.status == "closed":
            return
        self._closing = True
        await self._client.disconnect()
        self.status = "closed"

    async def _finalize_live_turn(self, deadline: float) -> None:
        """End the turn holding `self._lock`, or give up at `deadline`.

        Returns as soon as the lock is free or the live generator is gone -- it
        does NOT itself take the lock. See `close()` and
        CP-013
        """
        interrupted = False
        while True:
            gen = self._active_gen
            if gen is None or not self._lock.locked():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                # Bounded like every other wait here. The unwind is synchronous
                # with the PINNED SDK, so this bound should never bite -- it is
                # here so "every wait is bounded by one timeout_s deadline" (a
                # claim registry.py rests its registry-wide lock on) is true by
                # construction rather than by accident of someone else's
                # teardown code. RECHECK ON ANY SDK UPGRADE: it turns a
                # regression there into a slow close(), not a wedged registry.
                # It does NOT cost the turn its unwind (measured).
                # See CP-013
                async with asyncio.timeout(remaining):
                    await gen.aclose()
                return
            except TimeoutError:
                # Same verdict as the teardown failure below: the turn could
                # not be ended cleanly, and that must never stop close() from
                # disconnecting -- disconnect() (S5) stops the subprocess
                # regardless.
                _log.warning(
                    "close(): tearing down the live turn did not complete "
                    "within %.3fs; disconnecting anyway",
                    remaining,
                )
                return
            except RuntimeError:
                # An advance is in flight AT THIS INSTANT. That is ALL this
                # proves -- it is an observation, not a verdict, and treating
                # it as one was an unbounded hang. Re-check and retry.
                pass
            except Exception:
                # `aclose()` runs the turn's WHOLE unwind, so a teardown failure
                # surfaces here. The turn is over either way (that unwind
                # releases the lock and runs the `finally`), and a failure to
                # tear down a turn must never stop close() from disconnecting --
                # it used to propagate, making DELETE #1 a 500 with the client
                # still connected.
                _log.warning(
                    "close(): tearing down the live turn failed; "
                    "disconnecting anyway",
                    exc_info=True,
                )
                return
            if not self._lock.locked():
                return
            if not interrupted:
                # A genuinely-advancing turn, and only now do we know that.
                # Ask the SDK to stop it (the measured S2 path) so its caller
                # gets the interrupted shape rather than a forced abort --
                # once per close(), bounded, and never fatal.
                interrupted = True
                await self._interrupt_until(deadline)
                continue
            if time.monotonic() >= deadline:
                return
            await asyncio.sleep(_ACLOSE_RETRY_INTERVAL_S)

    async def _interrupt_until(self, deadline: float) -> None:
        """Ask the SDK to stop the running turn. Bounded, and never fatal.

        Takes HALF the remaining budget: the interrupt is a courtesy to the
        turn's caller, while ending the turn and taking the lock is what
        `close()` is FOR, so a wedged control channel must not consume the whole
        deadline. Every failure is swallowed deliberately -- neither the SDK's
        own 60s control timeout nor this bound says anything about whether the
        session can be closed, and letting either propagate is what made a
        wedged CLI a permanent leak.
        See CP-014
        """
        budget = (deadline - time.monotonic()) / 2
        if budget <= 0:
            return
        try:
            async with asyncio.timeout(budget):
                await self.interrupt()
        except TimeoutError:
            _log.warning(
                "close(): interrupt() did not answer within %.3fs; "
                "force-ending the turn instead",
                budget,
            )
        except Exception:
            _log.warning(
                "close(): interrupt() failed; force-ending the turn instead",
                exc_info=True,
            )

    async def _acquire_lock_until(self, deadline: float) -> bool:
        """Acquire `self._lock`, or give up at `deadline`. True if acquired.

        The caller must release it iff this returned True.

        Bounded rather than awaited bare because a bare await genuinely can be
        unbounded: the turn holding the lock may be abandoned, and even an
        UNLOCKED lock suspends the acquirer when a non-cancelled waiter is
        already queued (asyncio.Lock is FIFO-fair). No cancellation THIS METHOD
        creates escapes it -- one aimed at the calling task from outside still
        propagates -- and the lock is never leaked by giving up.
        See CP-015
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            async with asyncio.timeout(remaining):
                await self._lock.acquire()
        except TimeoutError:
            return False
        return True

    async def _acquire_lock_now(self) -> bool:
        """Take `self._lock` iff it can be had WITHOUT waiting. True if taken.

        The caller must release it iff this returned True.

        `self._lock.locked()` alone is NOT this test: an unlocked lock still
        suspends the next acquirer when a waiter is already queued (FIFO
        fairness), so `if not locked: await acquire()` can park for a whole
        turn. `asyncio.timeout(0)` is EXACT here, not approximate -- either the
        lock was free and we hold it, or we were cancelled inside `acquire()`
        and that becomes `TimeoutError`.
        See CP-015
        """
        try:
            async with asyncio.timeout(0):
                await self._lock.acquire()
        except TimeoutError:
            return False
        return True

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_used_at

    # -- residue guard ----------------------------------------------------
    def _sdk_message_buffer(self) -> Any | None:
        """The SDK's connection-scoped message buffer, or None.

        There is exactly ONE anyio message stream per Query, shared by every
        `receive_response()` call. Only conversation messages land on it --
        control frames are filtered out before the send -- so discarding from
        it cannot disturb interrupt/set_model/get_context_usage.

        Reaches through private internals deliberately AND defensively: a guard
        that raised `AttributeError` on the next turn would be strictly worse
        than the misattribution it defends against, so every step is probed and
        anything unexpected yields None. RECHECK ON ANY SDK UPGRADE.
        See CP-016
        """
        query = getattr(self._client, "_query", None)
        if query is None:
            return None
        buffer = getattr(query, "_message_receive", None)
        if buffer is None or not callable(getattr(buffer, "receive_nowait", None)):
            return None
        return buffer

    def _discard_residue(self) -> int:
        """Drop whatever is already queued on the SDK's buffer. Returns a count.

        MUST STAY NON-BLOCKING -- a blocking read here would hang the next turn
        forever, which is far worse than the defect it fixes. `receive_nowait()`
        is synchronous and raises (not waits) on empty/closed; there is no
        `await` in this function at all, and the loop is capped regardless.

        Safe by construction: only ever runs at the top of `send()`, BEFORE
        `query()` is written, so nothing queued can belong to the turn about to
        start. It CANNOT cover messages still in flight from the subprocess --
        those need `interrupt()`.
        See CP-016
        """
        buffer = self._sdk_message_buffer()
        if buffer is None:
            return 0
        discarded = 0
        while discarded < _RESIDUE_DISCARD_LIMIT:
            try:
                buffer.receive_nowait()
            except Exception:
                break
            discarded += 1
        return discarded

    # -- one turn ---------------------------------------------------------
    def send(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Drain one turn. Returns an async generator; NOTHING in it runs until
        first advanced -- the `SessionBusy`/`SessionClosed` raises are
        `_send_impl`'s body, so a `try` around a bare `send()` catches nothing.

        A thin wrapper whose only job is the one-element box: an async
        generator cannot reference itself, so this is how `_send_impl` gets a
        handle to publish as `_active_gen`. Filled BEFORE the generator is
        returned, so it is always populated by the time anyone can advance it.
        See CP-017
        """
        box: list[AsyncIterator[dict[str, Any]]] = []
        gen = self._send_impl(prompt, box)
        box.append(gen)
        return gen

    async def _send_impl(
        self, prompt: str, box: list[AsyncIterator[dict[str, Any]]]
    ) -> AsyncIterator[dict[str, Any]]:
        # Paired with the in-lock check below; NEITHER is individually
        # test-killable, by design. Do not chase them separately -- see
        # test_a_turn_cannot_start_while_close_is_disconnecting, which pins the
        # behaviour and explains why.
        if self.status == "closed" or self._closing:
            raise SessionClosed("session is closed")
        if self._lock.locked():
            raise SessionBusy("a turn is already running on this session")

        async with self._lock:
            # Re-check INSIDE the lock. Without this, a first advance that
            # queues behind a woken `close()` (FIFO-fair) acquires only once the
            # session is closed and the client disconnected, then runs a full
            # turn against a dead client and resurrects `status` from "closed"
            # -- reproduced. `_closing` is the half that holds while `close()`
            # is suspended inside `disconnect()`, where `status` is still
            # "idle" by design.
            if self.status == "closed" or self._closing:
                raise SessionClosed("session is closed")
            # Publish `_active_gen` HERE, after winning the lock -- NOT eagerly
            # from `send()`. A losing `SessionBusy` caller raises before
            # reaching this line, so only the turn that actually holds the lock
            # can ever become `_active_gen`. Publishing eagerly let a loser's
            # spent generator overwrite it, so `close()` aclose()d a no-op,
            # believed the turn finalized, and hung forever on the real one.
            # See CP-017
            self._active_gen = box[0]
            self.status = "running"
            self._turn_seq += 1
            turn_id = self._turn_seq
            # This turn now owns the connection, so any PREVIOUS turn's
            # abandoned-mid-drain condition is spent -- interrupting on its
            # behalf from here on could only kill THIS turn. Cleared inside the
            # lock, before the first await.
            self._turn_abandoned = False
            seq = 0
            outcome: RunOutcome | None = None
            # This turn's own ResultMessage has been consumed AND recorded.
            # Once it has, the turn is OVER: everything after is teardown, and
            # no teardown may overwrite the record of a turn that finished.
            recorded = False
            # Persistence identity for THIS turn. Minted inside the lock beside
            # `turn_id`, which is the in-process identity -- they are different
            # things and both are needed: `turn_id` keys the interrupt stamp,
            # `run_id` keys stored rows and must be unique across restarts.
            run_id = uuid.uuid4().hex
            timed_out = False
            self._recorder.start_run(
                run_id,
                sid=self.sid,
                session_id=self.session_id,
                prompt=prompt,
                at=time.time(),
            )

            # Reset per turn, inside the lock and before the first await, so a
            # turn that then fails still describes itself rather than its
            # predecessor. Writing it only in the branch below left every later
            # turn reporting a stale count from two turns ago.
            self.last_residue_discarded = 0

            if self._residue_suspected:
                # The previous turn left messages -- its ResultMessage included
                # -- on the connection-scoped buffer, and this turn's drain
                # would otherwise report them as its own. Discarded here,
                # BEFORE query() is written, where nothing queued can possibly
                # belong to us.
                self._residue_suspected = False
                self.last_residue_discarded = self._discard_residue()

            try:
                async with asyncio.timeout(self._limits.timeout_s):
                    await self._client.query(prompt)
                    # `async for` does NOT close its iterator when the loop is
                    # abandoned via GeneratorExit or a raised exception (PEP 533
                    # was deferred), so without this an SSE disconnect mid-turn
                    # leaves this wrapper to non-deterministic GC. Bounds the
                    # LOCAL generator only -- unlike runner.py's Run.events() it
                    # does NOT tear down the CLI subprocess (the session owns
                    # that until close()/disconnect(), S5), so it does not stop
                    # the CLI producing the rest of an abandoned turn into the
                    # connection-scoped buffer. That residue is the next turn's
                    # `_discard_residue()`.
                    async with aclosing(self._client.receive_response()) as stream:
                        async for message in stream:
                            seq += 1
                            if isinstance(message, SystemMessage):
                                reported = (message.data or {}).get("session_id")
                                if self.session_id is None:
                                    # init arrives on EVERY turn (S1/S3) -- take
                                    # the first one we ever see and never
                                    # overwrite it.
                                    self.session_id = reported
                                elif reported and reported != self.session_id:
                                    # NEVER overwritten -- callers have the old
                                    # value and a silently-changing identifier
                                    # is worse than a stale one. But it is no
                                    # longer SILENT: this fires when the CLI
                                    # disagrees with the id this session
                                    # reports, which is the only way to notice
                                    # either a mid-connection change (open,
                                    # unmeasured) or a supplied id the CLI did
                                    # not honour. A relay joining on this value
                                    # would otherwise attribute traffic to a
                                    # conversation nobody can find.
                                    _log.warning(
                                        "session %s: the CLI reported SDK session id %s "
                                        "on this turn, but this session reports %s and "
                                        "keeps it; downstream joins on the reported id "
                                        "will not match",
                                        self.sid,
                                        reported,
                                        self.session_id,
                                    )
                            if isinstance(message, ResultMessage):
                                fields = result_fields(message)
                                self.session_id = self.session_id or fields.get("session_id")
                                outcome = build_outcome(fields, self.session_id)
                                # Recorded HERE, BEFORE the yield that hands it
                                # to the consumer. A postscript after the drain
                                # resumes can be skipped; this cannot.
                                self._record_turn(
                                    outcome,
                                    interrupt_requested=self._interrupt_for_turn == turn_id,
                                )
                                recorded = True
                            event = normalize(message, seq, self._include_raw)
                            # BEFORE the yield, for the same reason
                            # `_record_turn` above is: a consumer that never
                            # resumes this generator skips anything written
                            # after the yield. Synchronous and non-blocking by
                            # the recorder specification, so this adds no suspension
                            # point to the drain -- see recorder.py, which
                            # explains why that matters HERE in particular.
                            self._recorder.append_event(run_id, event)
                            yield event
            except TimeoutError as exc:
                # This bound is what makes registry.py's "never force-close a
                # running session" policy safe: without it a turn that never
                # reaches a ResultMessage hangs forever and its cap slot is
                # never reclaimable. Re-raised as `RunTimeout` -- the SAME type
                # the one-shot /v1/query path raises, so callers handle both
                # uniformly and `to_problem` maps it to 504.
                #
                # Skipped once the turn has been RECORDED: the deadline can
                # expire while the drain sits at its final `yield` waiting for a
                # stalled consumer, and such a turn did not time out -- its
                # reader did. RunTimeout still reaches that reader; what must
                # not happen is a completed turn being overwritten.
                timed_out = True
                if not recorded:
                    self.last_turn = TurnResult(
                        session_id=self.session_id,
                        outcome=None,
                        interrupted=self._interrupt_for_turn == turn_id,
                        timed_out=True,
                    )
                    self._turn_abandoned = self._interrupt_for_turn != turn_id
                # `_turn_abandoned` is keyed to the interrupt STAMP: a turn
                # already interrupted has been told to stop, and re-arming would
                # aim a second control request at a turn that no longer exists.
                # A RECORDED turn is owed nothing either.
                raise RunTimeout(f"turn exceeded {self._limits.timeout_s}s") from exc
            except BaseException:
                # A mid-drain failure -- including an abandoned/cancelled
                # consumer -- must not leave `last_turn` pointing at the
                # PREVIOUS turn's result, which would read as a stale success.
                #
                # UNLESS the turn was already RECORDED. Running this
                # unconditionally mislabelled COMPLETED turns: the consumer
                # takes the `result` frame, its write never completes, and the
                # cleanup's `aclose()` arrives here as a GeneratorExit --
                # measured overwriting a turn with a real result and
                # `total_cost_usd=0.42` as `outcome=None, interrupted=True,
                # turns=0, cost=0.0`. What died was the DELIVERY of the last
                # frame, which is the consumer's business, not the turn's.
                if not recorded:
                    self.last_turn = TurnResult(
                        session_id=self.session_id,
                        outcome=None,
                        interrupted=self._interrupt_for_turn == turn_id,
                    )
                    self._turn_abandoned = self._interrupt_for_turn != turn_id
                # The turn was cut short (a real SSE hangup lands its
                # CancelledError right here, inside the drain), so the
                # subprocess is still producing it. `_residue_suspected` in the
                # `finally` is NOT a substitute -- it is also set for a turn
                # that ended normally without a ResultMessage, where there is
                # nothing left running to interrupt.
                #
                # Keyed to the interrupt STAMP, not to whether the control
                # request succeeded: api.py's `close_stream()` does
                # interrupt-then-`aclose()`, and that `aclose()` arrives HERE as
                # a GeneratorExit, so an unconditional re-arm fired a second,
                # pointless control request at a turn already stopped
                # (measured). The conservative direction costs a missed
                # courtesy; the other aims a control request at a turn that no
                # longer exists.
                # See CP-017
                raise
            finally:
                # Read BEFORE the stamp is cleared on the next line, or every
                # turn would be recorded as uninterrupted.
                was_interrupted = self._interrupt_for_turn == turn_id
                # `finally` is the ONLY placement that cannot be skipped: a
                # postscript is skipped by `raise`, which left the stamp set for
                # the NEXT turn to consume. The invariant is that no turn may
                # ever begin with an interrupt recorded during a previous turn.
                self._interrupt_for_turn = None
                # `outcome is None` is exactly "never consumed its own
                # ResultMessage", and covers both exits: a drain abandoned
                # before the result, and a stream that ended without one.
                self._residue_suspected = outcome is None
                self.status = "closed" if self.status == "closed" else "idle"
                self.last_used_at = time.time()
                # This turn is no longer the live one, however it ended --
                # including via `close()`'s own `aclose()` unwinding through
                # this exact `finally`.
                self._active_gen = None
                # LAST in the finally, so a recorder that misbehaves despite the
                # specification cannot leave the invariants above half-applied.
                #
                # Reads LOCALS, not `self.last_turn`: on the "drain ended with
                # no ResultMessage" path `last_turn` is not assigned until after
                # this block, so it would still be the PREVIOUS turn's result --
                # exactly the stale-success confusion that path exists to avoid.
                # `turn_cost_usd` is therefore taken only when `recorded`, where
                # `_record_turn` has already differenced it against the
                # connection's running total (S6).
                self._recorder.finish_run(
                    run_id,
                    sid=self.sid,
                    session_id=self.session_id,
                    outcome=outcome if recorded else None,
                    turn_cost_usd=(
                        self.last_turn.turn_cost_usd
                        if recorded and self.last_turn is not None
                        else None
                    ),
                    interrupted=was_interrupted,
                    timed_out=timed_out,
                    at=time.time(),
                )

            if not recorded:
                # The drain ended of its own accord but WITHOUT a ResultMessage.
                # `last_turn` is still assigned (leaving the previous turn's
                # result standing would read as a stale success), but `turns` is
                # NOT incremented: it means exactly one thing, turns that
                # reached a ResultMessage, and must not depend on how the
                # consumer behaved after the result arrived.
                self.last_turn = TurnResult(session_id=self.session_id, outcome=None)

    def _record_turn(self, outcome: RunOutcome, *, interrupt_requested: bool) -> None:
        """Record a turn that reached its own ResultMessage. NEVER awaits.

        Called from inside the drain, at the instant the ResultMessage is
        consumed and BEFORE it is yielded. Being synchronous is what makes it
        unskippable; a postscript after the drain resumes is skippable, and was
        measured recording a turn with a real result and `total_cost_usd=0.42`
        as `outcome=None, interrupted=True, turns=0, cost=0.0`.

        Two deliberate consequences: an interrupt landing AFTER the
        ResultMessage no longer labels the turn (it cannot have caused an abort
        the SDK already reported), and this counts once per ResultMessage
        CONSUMED rather than once per `send()` -- the same thing only because
        `receive_response()` ends at the first one (S1). RECHECK ON ANY SDK
        UPGRADE. See CP-018
        """
        aborted = outcome.terminal_reason in ABORTED_TERMINAL_REASONS
        # ORDERED, not merely adjacent: differenced against the running total
        # BEFORE the assignment at the bottom of this method, or every delta is
        # 0.0. Guard: test_the_delta_is_taken_before_the_running_total_is_updated
        #
        # None, never 0.0, when the ResultMessage carries no price -- 0.0 would
        # claim the turn was free.
        cumulative = (
            float(outcome.total_cost_usd) if outcome.total_cost_usd is not None else None
        )
        # `or 0.0` because the session now starts UNPRICED rather than at zero:
        # the first priced turn's delta is the whole cumulative, which is what
        # subtracting a baseline of nothing means.
        delta = None if cumulative is None else cumulative - (self.total_cost_usd or 0.0)
        if unattributed_abort(outcome, delta):
            # MEASURED, not inferred: an ABORTED turn whose cumulative did not
            # move was not free -- its cost went UNATTRIBUTED. On such a turn the
            # SDK reports `usage` all-zero with `iterations: []`, leaves
            # `model_usage` at the connection's running total from EARLIER
            # COMPLETED turns (absent entirely if no turn has completed yet), and
            # does not advance `total_cost_usd` -- while the CLI demonstrably did
            # inference: 8s of streamed output per turn, and later turns then pay
            # cache-READ on a prefix nothing is ever recorded as having created.
            # The cost is LOST, not deferred: the next completed turn's delta is
            # exactly its own `usage` priced, to seven decimal places.
            #
            # So `0.0` -- item 14's "this turn was free" -- is the one answer that
            # is certainly wrong, and `None` ("nobody can say") is the honest one.
            # NARROW BY CONSTRUCTION: only the aborted shape with a zero delta is
            # touched. A completed turn the SDK priced the same as its
            # predecessor is still a genuine 0.0 (pinned by
            # test_a_turn_the_sdk_priced_the_same_is_a_zero_delta_not_unknown),
            # the delta arithmetic above is unchanged, and the assignment below
            # still ASSIGNS the cumulative rather than summing it (S6).
            #
            # `max_budget_usd` is enforced against this same unmoved figure
            # inside the CLI, so it is blind to these turns -- measured, and NOT
            # fixable here. See CP-088 and
            # CP-018
            delta = None
        self.last_turn = TurnResult(
            session_id=self.session_id,
            outcome=outcome,
            # BOTH conjuncts are load-bearing: a stop request that lost the
            # race to a turn that then completed normally must report False
            # (`aborted` is the measured S2 shape), and an aborted turn nobody
            # asked to stop is a crash, not an interrupt.
            interrupted=bool(interrupt_requested and aborted),
            turn_cost_usd=delta,
        )
        self.turns += 1
        if cumulative is not None:
            # ASSIGN, never sum (S6) -- summing double-counts on every turn.
            self.total_cost_usd = cumulative

    # -- controls ---------------------------------------------------------
    async def interrupt(self) -> bool:
        """Stamp the running turn as deliberately stopped, then ask the SDK.

        Returns whether a control request was actually ISSUED -- which nothing
        outside this method can reconstruct, because an abandoned turn leaves
        `status == "idle"` and still fires one.

        Three branches, and the invariants each one rests on:

        * **No turn running** -- no-op, never an error. The turn ending as the
          caller asks to stop it is a race no client can avoid.
        * **`status == "running"`** -- stamp BEFORE the await, with no
          suspension point between the check and the stamp, so the stamp cannot
          outlive its turn. `_closing` is deliberately not checked: `close()`
          reaches this branch itself.
        * **A turn abandoned mid-drain** -- still `"idle"`, subprocess still
          working. Holds the lock (issuing it unlocked was measured killing a
          turn that started during the await), but only via `_acquire_lock_now`
          so it can never wait, and bounded by `_STALE_INTERRUPT_BUDGET_S`.
          `_turn_abandoned` is CONSUMED here, so this fires at most once.

        Why each of those is the way it is, the alternatives rejected, and the
        interleaving that hid the third branch for so long:
        CP-019
        """
        if self.status == "running":
            self._interrupt_for_turn = self._turn_seq
            await self._client.interrupt()
            self.last_used_at = time.time()
            return True
        # `_closing` is checked here but NOT in branch 1: close() reaches
        # branch 1 itself and must still be able to give a genuinely-advancing
        # turn the S2 ending. This conjunct is DEFENSIVELY UNREACHABLE and
        # deliberately kept -- no test can kill it, do not try.
        # CP-006
        if not self._turn_abandoned or self.status == "closed" or self._closing:
            return False
        if not await self._acquire_lock_now():
            return False
        try:
            # Re-checked under the lock. DELIBERATE BELT-AND-BRACES: no test can
            # reach it today (nothing awaits between the checks above and the
            # acquisition), and it stays for the day someone adds an await
            # there -- a one-line, harmless-looking change.
            # CP-006
            if self.status == "closed" or not self._turn_abandoned:
                return False
            self._turn_abandoned = False
            # Published INSIDE the lock, cleared in the finally that releases
            # it, so the two can never disagree. Read by `close()`, which
            # refuses to wait for a lock held only by this.
            self._courtesy_interrupt = True
            try:
                async with asyncio.timeout(_STALE_INTERRUPT_BUDGET_S):
                    await self._client.interrupt()
            except TimeoutError as exc:
                raise InterruptTimeout(
                    "the agent did not answer the interrupt control request "
                    f"within {_STALE_INTERRUPT_BUDGET_S}s"
                ) from exc
            self.last_used_at = time.time()
            return True
        finally:
            self._courtesy_interrupt = False
            self._lock.release()

    async def set_model(self, model: str) -> None:
        """Change the model. `SessionClosed` if the session is over.

        **TAKES EFFECT ON THE TURN ALREADY IN FLIGHT**, at the very next
        inference -- measured (M1), not "from the next turn". A mid-turn change
        re-prices the remainder of that turn and its `model_usage` bills both
        models. No lock: the same probe showed a mid-turn control request does
        not disturb the drain. **RECHECK ON ANY SDK UPGRADE** (n=1, Windows).

        Raises on a closed session rather than no-op'ing, unlike `interrupt()`:
        a mutation that silently did nothing would read as success on a PATCH.
        `_closing` is checked alongside `status` because `status` is still
        "idle" while `close()` is suspended inside `disconnect()`.

        See CP-020
        """
        if self.status == "closed" or self._closing:
            raise SessionClosed("session is closed")
        await self._client.set_model(model)
        # AFTER the await, deliberately: this is the read-back
        # `SessionRecord.model` reports, so it must say what the SDK actually
        # TOOK. A control request that raises leaves the session advertising
        # the model it still has, not the one that never arrived.
        self.model = model
        self.last_used_at = time.time()

    async def set_permission_mode(self, mode: str) -> None:
        """Change the permission mode. Same closed-session guard as
        `set_model`, and the same measured mid-turn behaviour -- it applies to
        the turn already draining. It also injects a
        `SystemMessage(subtype='status')` into the message stream (M1)."""
        if self.status == "closed" or self._closing:
            raise SessionClosed("session is closed")
        await self._client.set_permission_mode(mode)
        # After the await, for the reason `set_model` gives.
        self.permission_mode = mode
        self.last_used_at = time.time()

    async def context_usage(self) -> dict[str, Any] | None:
        """Ask the SDK how much context this session has used, or None.

        None means "not asked", and is RETURNED, not raised -- the opposite of
        the setters above. This is a READ, the rest of the record it feeds is
        still true during teardown, and "I could not ask" already has a wire
        representation, since `SessionRecord.context_usage` is nullable. GET
        stays 200.

        The route's declared 502 is untouched and still reachable: a LIVE
        session whose control channel cannot deliver is a different condition.

        See CP-021
        """
        if self.status == "closed" or self._closing:
            return None
        usage = await self._client.get_context_usage()
        return usage if isinstance(usage, dict) else {"categories": []}
