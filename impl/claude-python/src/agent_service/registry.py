"""The live session collection: cap, lookup, idle reaping, shutdown.

Each entry owns a CLI subprocess, so the cap is a real resource bound. The
reaper can rely on AgentSession.close() because disconnect() was measured to
kill the subprocess deterministically (spike S5) -- but only at a CLEAN TURN
BOUNDARY. What disconnect() does against an actively draining turn has never
been measured, which is why this reaper SKIPS any session whose
`status == "running"` rather than force-closing it, and why force-closing a
busy session from here was rejected outright. The turn is bounded at its
source instead (`sessions.py`'s `send()`), so a hung turn returns to "idle"
and becomes reclaimable on the next tick.

CONCURRENCY MODEL. One asyncio.Lock (`_lock`) guards every mutation of
`_sessions` plus a `_reserved` counter, and it is held ONLY for synchronous
bookkeeping -- the cap check+reserve, the lookup, the stale/pending scans.
It is NEVER held across an await:

  * NOT across `AgentSession.open()`. Holding it there let one slow subprocess
    spawn block close()/reap_once() on every OTHER session, destroying the one
    mechanism an operator has to shed load while something is wedged.
  * NOT across `await session.close()` either. That close is bounded by
    `timeout_s` (600s default, 1800s cap), not by `disconnect()`, and the
    registry waited with it -- measured with a wedged real session and a
    HEALTHY control channel: `reap_once` and `create` both still blocked at a
    5s probe bound off one DELETE. Post-change: both 0.000s, while the DELETE
    still waits its own full close, which is correct.

`create()` reserves a cap slot before opening, so the cap stays watertight
while `open()` is in flight, and reconciles afterwards with BARE SYNCHRONOUS
statements -- no second lock acquisition, because a task cancelled awaiting a
contended one leaked both the reservation and an already-opened, unregistered
session that nothing could reach to close.

All three teardown paths -- `close()`, `reap_once()`, `close_all()` -- remove a
session from `_sessions` only AFTER `AgentSession.close()` has returned, so a
failing disconnect() never costs the registry its only handle on a live
subprocess. They differ only in what they do with the failure: raise it
(DELETE answers a problem document), retry next tick, or log it. Removal is
`pop(sid, None)` everywhere and only a pop that actually removed something may
claim the teardown.

Every measurement, the shapes that were tried and failed, and two claims here
that were once stated too strongly and had to be corrected:
CP-022
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any, Protocol

from agent_service.config import Settings
from agent_service.options import validate_sdk_session_id
from agent_spec.db.recorder import NULL_RECORDER, RunRecorder
from agent_spec.openapi.schemas import RunOptions
from agent_service.sessions import AgentSession

_log = logging.getLogger(__name__)

# See the module docstring's `open()` bullet for the reasoning behind 30s.
_DEFAULT_OPEN_TIMEOUT_S = 30.0

# --- close_all()'s aggregate budget, split ---------------------------------
#
# The budget itself is `Settings.shutdown_budget_s` (60s), because
# compose.yaml's `stop_grace_period` is derived from it. These two split it:
#
#   phase 1, CLEAN CLOSES: budget - reserve
#   phase 2, FORCE KILLS:  reserve
#
# The reserve exists because a kill that has no time left is not a kill. It is
# a FRACTION with a ceiling so the split still works for the sub-second budgets
# the tests use: at 60s the reserve is 5s (the ceiling), at 1s it is 0.25s.
_KILL_RESERVE_FRACTION = 0.25
_MAX_KILL_RESERVE_S = 5.0

# How long a close that overran its slice is given to ACKNOWLEDGE its
# cancellation before it is abandoned. Charged against phase 1's deadline, so
# it can only shorten to zero -- never extend the total.
_CANCEL_GRACE_S = 0.5


class SessionNotFound(KeyError):
    """No live session with that id."""


class SessionLimitReached(RuntimeError):
    """max_sessions reached; close one before creating another."""


class SessionOpenTimeout(RuntimeError):
    """AgentSession.open() did not complete within open_timeout_s.

    The reservation it held against the cap has already been released by the
    time this is raised -- the slot is not leaked.
    """


class SessionFactory(Protocol):
    # `sdk_session_id` is KEYWORD-ONLY and optional, and `create()` passes it
    # only when a caller actually supplied one. A three-argument factory --
    # which is what every test in this repo writes -- therefore keeps working
    # untouched; only a factory used with a caller-supplied id has to accept it.
    def __call__(
        self,
        options: RunOptions,
        settings: Settings,
        title: str | None = None,
        *,
        sdk_session_id: str | None = None,
    ) -> Any: ...


def _default_session_factory(
    options: RunOptions,
    settings: Settings,
    title: str | None = None,
    *,
    sdk_session_id: str | None = None,
) -> AgentSession:
    return AgentSession(options, settings, title=title, sdk_session_id=sdk_session_id)


class SessionRegistry:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: SessionFactory | None = None,
        open_timeout_s: float = _DEFAULT_OPEN_TIMEOUT_S,
        recorder: RunRecorder | None = None,
        session_store: Any | None = None,
    ) -> None:
        self._settings = settings
        self._recorder = recorder or NULL_RECORDER
        self._session_store = session_store
        # The DEFAULT factory closes over the recorder rather than taking it as
        # a `SessionFactory` argument. Widening that protocol would break every
        # test factory that implements its three-argument shape, and a custom
        # factory legitimately wants no recorder -- it is building a session for
        # a test, not for a caller.
        self._factory = session_factory or self._build_session
        self._open_timeout_s = open_timeout_s
        self._sessions: dict[str, Any] = {}
        # Slots "spoken for" by a create() whose open() is still in flight --
        # counted against the cap but not yet in `_sessions`. See the module
        # docstring.
        self._reserved = 0
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None
        # Strong references to close()/kill() tasks that close_all() cancelled
        # and gave up waiting for. Held only so the garbage collector cannot
        # destroy a still-pending task and turn a bounded shutdown into a
        # "Task was destroyed but it is pending!" on the way out; discarded
        # again as soon as each one finishes.
        self._abandoned: set[asyncio.Task[Any]] = set()

    def _build_session(
        self,
        options: RunOptions,
        settings: Settings,
        title: str | None = None,
        *,
        sdk_session_id: str | None = None,
    ) -> AgentSession:
        return AgentSession(
            options,
            settings,
            title=title,
            recorder=self._recorder,
            session_store=self._session_store,
            sdk_session_id=sdk_session_id,
        )

    async def create(
        self,
        options: RunOptions,
        title: str | None,
        sdk_session_id: str | None = None,
    ) -> str:
        # FIRST, before the cap check and before a slot is reserved: a request
        # that cannot produce a session must not consume capacity, however
        # briefly.
        #
        # HERE rather than in the route, so it is enforced by the thing that
        # creates sessions rather than by one caller of it -- the same place
        # `build_options`' own `LimitExceeded` / `InvalidWorkspacePath` become
        # a 400, and one validation pattern instead of two.
        if sdk_session_id is not None:
            validate_sdk_session_id(sdk_session_id, options.resume)

        async with self._lock:
            if len(self._sessions) + self._reserved >= self._settings.max_sessions:
                raise SessionLimitReached(
                    f"at most {self._settings.max_sessions} concurrent sessions; "
                    "close one before creating another"
                )
            self._reserved += 1

        # Deliberately UNLOCKED: open() spawns a CLI subprocess and is not
        # measured to be fast or reliably bounded. The factory call is INSIDE
        # this try because a reservation must be released on ANY failure before
        # the insert, including the factory itself raising on bad options.
        try:
            # Passed ONLY when supplied, so a three-argument factory (every
            # test factory in this repo) is called exactly as before. See
            # `SessionFactory`.
            session = (
                self._factory(options, self._settings, title)
                if sdk_session_id is None
                else self._factory(
                    options, self._settings, title, sdk_session_id=sdk_session_id
                )
            )
            async with asyncio.timeout(self._open_timeout_s):
                await session.open()
        except TimeoutError as exc:
            # BARE SYNCHRONOUS, no `async with self._lock`. Reproduced against
            # the real registry: a task cancelled while awaiting a CONTENDED
            # second acquisition here never decremented `_reserved` -- a
            # permanent capacity leak. With no await there is no suspension
            # point for that cancellation to land on. Correctness never needed
            # the lock for an int decrement; only the check+increment did.
            # CP-023
            self._reserved -= 1
            raise SessionOpenTimeout(
                f"session.open() did not complete within {self._open_timeout_s}s"
            ) from exc
        except BaseException:
            # Same reasoning; catches CancelledError (a BaseException), so this
            # IS the release path for a create() cancelled inside open().
            self._reserved -= 1
            raise

        # Same reasoning again: both statements below are synchronous, so once
        # open() has returned there is no window for a cancellation to land
        # between "open() succeeded" and "registered and reservation released".
        # The earlier shape left `_reserved` incremented AND an opened session
        # unregistered -- unreachable, so nothing could ever close it.
        sid = uuid.uuid4().hex
        self._reserved -= 1
        # The session learns its own id here, and only here: it cannot know it
        # at construction because this is where the id is minted. `_send_impl`
        # reads it to attribute each turn to a `sessions` row.
        session.sid = sid
        self._sessions[sid] = session
        # STILL SYNCHRONOUS, deliberately. The comment above explains that
        # nothing between "open() succeeded" and "registered" may suspend, or a
        # cancellation lands there and leaks an opened-but-unreachable session.
        # `RunRecorder` is a synchronous protocol precisely so observability can
        # be added here without reintroducing that window.
        self._recorder.session_opened(
            sid,
            title=getattr(session, "title", None),
            model=getattr(session, "model", None),
            permission_mode=getattr(session, "permission_mode", None),
            at=time.time(),
        )
        return sid

    def get(self, sid: str) -> Any:
        try:
            return self._sessions[sid]
        except KeyError as exc:
            raise SessionNotFound(sid) from exc

    def list(self) -> list[tuple[str, Any]]:
        return list(self._sessions.items())

    async def close(self, sid: str) -> None:
        """Close a session and forget it.

        Looks the session up (does NOT remove it) before awaiting close(), and
        removes it only once close() has succeeded. A failing close therefore
        leaves the session registered and retryable (AgentSession.close() is
        idempotent) rather than dropping the registry's only handle on a
        subprocess that is still connected -- measured, with a session whose
        close() always raises, as `still_registered=False, disconnected=False`
        under the older pop-first shape.

        Deliberately NO "is a turn running" guard, unlike reap_once():
        AgentSession.close() interrupts an in-flight turn and waits for it to
        end before disconnecting, so an explicit DELETE genuinely tears the
        session down rather than leaving a busy session un-reclaimable by any
        means.

        `_lock` is held only for the lookup; `session.close()` runs UNLOCKED,
        and the removal is a synchronous `pop(sid, None)`. SessionNotFound is
        decided at LOOKUP time, before the close begins; a concurrent reap that
        popped first does not make this DELETE a failure -- it is the same
        teardown, observed by two callers.
        See CP-024
        """
        async with self._lock:
            try:
                session = self._sessions[sid]
            except KeyError as exc:
                raise SessionNotFound(sid) from exc
        await session.close()
        self._sessions.pop(sid, None)
        self._recorder.session_closed(
            sid, status=getattr(session, "status", "closed"), at=time.time()
        )

    async def close_all(self, budget_s: float | None = None) -> None:
        """Close every session within ONE aggregate budget. Best effort inside it.

        One session at a time, most-recently-created first, each removed only
        once its `close()` has returned -- rather than snapshotting and
        clearing `_sessions` up front, which would silently orphan whatever the
        sweep had not reached when a shutdown timeout cancels it.

        "One failure" means one `Exception`. A `BaseException` -- cancellation
        above all -- propagates and ABORTS the sweep, leaving later sessions
        never attempted (measured). Recorded rather than fixed: widening the
        catch would swallow the shutdown cancellation telling this to stop.

        A session whose close() RAISES stays registered even though nobody will
        retry it here, so `list()` afterwards names every session NOT KNOWN to
        have shut down cleanly. That is a weaker claim than "still connected" --
        see the correction in the notes.

        Each session is attempted exactly ONCE per call: the loop tracks what
        it has tried rather than relying on the pop to make progress, so it
        terminates even when every close() fails, and still picks up a session
        inserted mid-sweep by an in-flight `create()`.

        Closes run sequentially but NOT under `_lock`, so a slow close no
        longer blocks a concurrent create()/reap_once()/DELETE.

        THE BUDGET (`Settings.shutdown_budget_s`, 60s). This runs from the ASGI
        lifespan, so its total IS the shutdown, and Docker SIGKILLs at
        `stop_grace_period` whether or not it has finished. It used to be
        bounded only by N x each session's own `timeout_s` -- 8 x 600s = 80
        minutes worst case, and 47.3s measured at the per-session cost a
        container actually showed -- so the grace period could only ever be a
        guess. Now every wait below is charged against one deadline taken at
        entry, in two phases:

          1. CLEAN CLOSES, until `budget - reserve`. Each close gets a FAIR
             SHARE of what is left: `remaining / sessions still to attempt`.
             Fair-share rather than a fixed per-session slice, because a
             per-session bound is exactly what `timeout_s` already is -- and
             the whole defect is that N of them do not add up to anything. It
             also means one wedged session cannot eat the budget and cost the
             healthy ones their clean teardown; a close that returns early
             hands its unused time to the rest.
          2. FORCE KILLS, with the reserve. Anything not closed cleanly -- ran
             out of time, raised, or was never reached -- is offered
             `session.kill()` if it has one (AgentSession does: disconnect
             NOW, no turn, no lock). The alternative to killing is a
             subprocess that outlives the container, which is the failure this
             whole path exists to prevent. Sessions with no kill() are simply
             reported.

        A killed session is NOT deregistered: a kill is not a clean close, so
        `list()` keeps meaning "not known to have shut down cleanly" and the
        summary can name it. Only a `close()` that RETURNED removes a session,
        exactly as before.

        Each close runs in its own task rather than being awaited directly, so
        a close whose CANCELLATION also hangs cannot overrun the budget: it is
        cancelled, given `_CANCEL_GRACE_S` (charged against phase 1's own
        deadline), then abandoned. A cancellation from OUR caller still ABORTS
        the sweep as before -- it cancels the in-flight close and propagates.

        Says what it did, always, in one line: Task 4 measured this logging
        NOTHING on a successful shutdown, which made a clean sweep and a sweep
        that never ran indistinguishable in a container's logs.

        See CP-025
        """
        budget = self._settings.shutdown_budget_s if budget_s is None else budget_s
        started = time.monotonic()
        deadline = started + budget
        reserve = min(_MAX_KILL_RESERVE_S, budget * _KILL_RESERVE_FRACTION)
        clean_deadline = deadline - reserve

        attempted: set[str] = set()
        failed: list[str] = []
        unfinished: list[str] = []
        closed: list[str] = []
        budget_hit = False
        while True:
            async with self._lock:
                pending = [sid for sid in self._sessions if sid not in attempted]
            if not pending:
                break
            remaining = clean_deadline - time.monotonic()
            if remaining <= 0:
                # Out of clean-close time; whatever is left goes to phase 2.
                budget_hit = True
                break
            sid = pending[-1]  # LIFO, as the old popitem() was
            attempted.add(sid)
            # No suspension point between the scan above and this get, so the
            # session cannot have vanished. Belt-and-braces for the day someone
            # adds one; not individually test-killable.
            session = self._sessions.get(sid)
            if session is None:
                continue
            outcome = await self._close_within(
                sid, session, remaining / len(pending), clean_deadline
            )
            if outcome == "closed":
                self._sessions.pop(sid, None)
                closed.append(sid)
            elif outcome == "failed":
                failed.append(sid)
            else:
                unfinished.append(sid)
                budget_hit = True

        async with self._lock:
            unreached = [sid for sid in self._sessions if sid not in attempted]
        if unreached:
            budget_hit = True
        killed, unkilled = await self._kill_all(
            [*unfinished, *failed, *unreached], deadline
        )

        elapsed = time.monotonic() - started
        summary = (
            "close_all: swept %d session(s) in %.3fs of a %.1fs budget: "
            "%d closed cleanly, %d killed, %d neither%s"
        )
        args = (
            len(closed) + len(failed) + len(unfinished) + len(unreached),
            elapsed,
            budget,
            len(closed),
            len(killed),
            len(unkilled),
            " (shutdown budget hit)" if budget_hit else "",
        )
        if unkilled or budget_hit:
            _log.error(summary, *args)
        else:
            _log.info(summary, *args)

        # Unchanged, and deliberately separate from the line above: this one
        # NAMES what nobody will retry. `killed` sessions are excluded because
        # their subprocess is not merely "maybe" gone -- kill() returned.
        still_registered = [
            sid for sid in failed if sid in self._sessions and sid not in killed
        ]
        if still_registered:
            _log.error(
                "close_all: %d of %d session(s) failed to close and are "
                "still registered; their subprocesses may still be alive: %s",
                len(still_registered),
                len(attempted),
                ", ".join(still_registered),
            )

    async def _close_within(
        self, sid: str, session: Any, slice_s: float, clean_deadline: float
    ) -> str:
        """One bounded close attempt. Returns "closed" | "failed" | "unfinished".

        Only `close_all()` uses this; `close()` and `reap_once()` still await
        the session's own `timeout_s` bound, which is correct for them -- the
        DELETE caller asked for that close, and the reaper retries next tick.
        Neither is racing a SIGKILL.
        """
        task = asyncio.create_task(session.close())
        try:
            done, _ = await asyncio.wait({task}, timeout=slice_s)
        except BaseException:
            # Our caller cancelled us (or worse). Documented behaviour: the
            # sweep ABORTS. Take the in-flight close down with it rather than
            # detaching it -- nothing would ever observe it again.
            task.cancel()
            raise
        if not done:
            task.cancel()
            # Charged against phase 1's deadline: at the deadline this is 0 and
            # the task is abandoned immediately. It can never extend the total.
            grace = min(_CANCEL_GRACE_S, max(0.0, clean_deadline - time.monotonic()))
            if grace > 0:
                try:
                    await asyncio.wait({task}, timeout=grace)
                except BaseException:
                    task.cancel()
                    raise
            if not task.done():
                self._abandoned.add(task)
                task.add_done_callback(self._abandoned.discard)
            _log.warning(
                "close_all: session %s did not close within its %.3fs share of "
                "the shutdown budget; cancelled it and will try to kill it",
                sid,
                slice_s,
            )
            return "unfinished"
        try:
            task.result()
        except Exception:
            _log.exception("close_all: failed to close session %s", sid)
            return "failed"
        return "closed"

    async def _kill_all(
        self, sids: list[str], deadline: float
    ) -> tuple[list[str], list[str]]:
        """Last resort: kill the subprocess of everything still standing.

        Returns (killed, not killed). Runs the kills CONCURRENTLY -- unlike the
        closes, which are sequential so that fair-share means something. A kill
        neither waits on a turn nor takes the session lock, so there is nothing
        to serialise, and the reserve is small enough that doing them one at a
        time would mean only the first one happened.

        `kill()` is optional: a session object without one (the HTTP-level
        fakes, anything the SDK grows later) is reported as not killed rather
        than crashing the last few milliseconds of shutdown.

        EVERY sid handed in comes back in exactly one of the two lists. Both
        the no-kill() case and the vanished-session case are reported rather
        than dropped, because `close_all()`'s summary counts the sids it PASSED
        here in `swept`: silently discarding one made `swept N` exceed
        `closed + killed + neither`, in the one line billed as saying what the
        sweep did, always.
        """
        targets: list[tuple[str, Any]] = []
        skipped: list[str] = []
        for sid in dict.fromkeys(sids):  # de-duplicated, order preserved
            session = self._sessions.get(sid)
            if session is None:
                # Popped concurrently: a DELETE landed during the sweep and its
                # own close() deregistered the session. There is nothing left to
                # kill -- and nothing here can tell that from a session that
                # vanished for some other reason -- so the honest report is "THIS
                # sweep did not kill it", not "it was killed".
                skipped.append(sid)
                continue
            kill = getattr(session, "kill", None)
            if kill is None:
                skipped.append(sid)
                continue
            targets.append((sid, kill))
        if not targets:
            return [], skipped
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return [], [*skipped, *(sid for sid, _ in targets)]

        tasks: dict[asyncio.Task[Any], str] = {
            asyncio.create_task(kill()): sid for sid, kill in targets
        }
        try:
            done, still_running = await asyncio.wait(set(tasks), timeout=remaining)
        except BaseException:
            for task in tasks:
                task.cancel()
            raise
        killed: list[str] = []
        not_killed: list[str] = list(skipped)
        for task in still_running:
            task.cancel()
            self._abandoned.add(task)
            task.add_done_callback(self._abandoned.discard)
            not_killed.append(tasks[task])
        for task in done:
            try:
                task.result()
            except Exception:
                not_killed.append(tasks[task])
                _log.exception("close_all: failed to kill session %s", tasks[task])
            else:
                killed.append(tasks[task])
        return killed, not_killed

    async def reap_once(self) -> int:
        """Close every idle-beyond-TTL session. Returns how many it CLOSED.

        Counts sessions actually torn down AND deregistered, not attempted --
        `len(stale)` reported a full sweep on a tick where every close() failed,
        making the reaper's one number least truthful exactly when something
        was wrong. `closed += 1` is additionally guarded on this sweep's own
        `pop` actually removing something, because a concurrent DELETE inside
        the same close() can claim the teardown first (measured: one
        deregistration reported twice).

        A session whose close() raises stays registered and is retried next
        tick. THE COST, stated precisely: `AgentSession.close()` latches
        `_closing` before its first await and never clears it, so that session
        is a TOMBSTONE -- visible in list()/GET, still holding a cap slot, but
        refusing every PATCH and message with 409 until a later tick succeeds
        (measured; retries succeeded on the third tick). Identical to what a
        failed DELETE already leaves behind, hence accepted rather than
        special-cased.

        Skips `status == "running"` (module docstring). Both the skip and the
        staleness are RE-CHECKED immediately before each close, synchronously:
        the closes run unlocked, so a turn can start -- or a session be freshly
        used -- while this sweep is parked inside an earlier one's close().
        See CP-026
        """
        ttl = self._settings.session_idle_ttl_s
        closed = 0
        async with self._lock:
            stale = [
                sid
                for sid, s in self._sessions.items()
                if s.status != "running" and s.idle_seconds > ttl
            ]
        for sid in stale:
            session = self._sessions.get(sid)
            if (
                session is None  # a concurrent DELETE/close_all got it first
                or session.status == "running"  # a turn started mid-sweep
                or session.idle_seconds <= ttl  # used mid-sweep: fresh again
            ):
                continue
            try:
                await session.close()
            except Exception:
                _log.exception("reaper: failed to close idle session %s", sid)
                continue
            if self._sessions.pop(sid, None) is not None:
                closed += 1
        return closed

    def start_reaper(self) -> None:
        if self._reaper is not None:
            return

        async def loop() -> None:
            while True:
                await asyncio.sleep(self._settings.session_reaper_interval_s)
                try:
                    # Say what the sweep did. Until this line nothing read the
                    # count -- measured: a reaper that closed two sessions
                    # emitted ZERO log records. A quiet tick stays quiet; a
                    # tick that FAILED to close something is already loud, via
                    # reap_once()'s per-session exception log.
                    closed = await self.reap_once()
                    if closed:
                        _log.info(
                            "reaper: closed %d idle session(s) past the %ss TTL",
                            closed,
                            self._settings.session_idle_ttl_s,
                        )
                except Exception:
                    _log.exception("reaper: reap_once() failed")

        self._reaper = asyncio.create_task(loop())

    async def stop_reaper(self) -> None:
        if self._reaper is None:
            return
        self._reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reaper
        self._reaper = None
