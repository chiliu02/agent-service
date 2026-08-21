"""The live session collection: the cap, the lookup, idle reaping, shutdown.

Each entry owns a `codex app-server` subprocess, so the cap is a real resource
bound rather than a policy. This is the layer `sessions.py` deliberately does
not hold -- one `CodexSession` owns one conversation; this owns the set of them
and everything the specification's `SessionRecord` reports about one.

## The split is different from the Claude build's, on purpose

There, `AgentSession` carries both the SDK conversation *and* the service-side
bookkeeping -- title, turn count, status, running cost -- and the result is a
995-line module. Here the bookkeeping lives in `SessionEntry` below and
`CodexSession` stays a pure SDK adapter. **That is the better split and it is
worth stating why**: everything in `SessionEntry` is determined by the
SPECIFICATION and would be identical in a third implementation, while everything
in `CodexSession` is determined by the SDK. The line between them is exactly the
line `impl/common/` would be cut along.

## Concurrency

One `asyncio.Lock` guards every mutation of `_entries` and the `_reserved`
counter, and it is held **only for synchronous bookkeeping** -- the cap
check-and-reserve, the lookup, the stale scan. It is never held across an
`await`, because holding it across `open()` would let one slow app-server spawn
block `close()` and the reaper for every other session, destroying the one lever
an operator has while something is wedged. The Claude build measured that
directly; this build inherits the conclusion rather than the code.

`create()` reserves a slot **before** opening so the cap stays watertight while
`open()` is in flight, and reconciles afterwards with bare synchronous
statements -- never a second `await` on a contended lock, which is how a
cancelled task leaks both the reservation and an opened-but-unregistered session
that nothing can reach to close.

Teardown removes an entry only **after** `CodexSession.close()` returns, so a
failing close never costs the registry its only handle on a live subprocess.

## Shutdown is bounded, and the bound is where compose's number comes from

`close_all()` runs from the ASGI lifespan, so its total *is* the shutdown and
Docker SIGKILLs at `stop_grace_period` regardless. It spends one aggregate
budget -- `Settings.shutdown_budget_s` -- rather than N per-session bounds that
add up to nothing, which is what makes that compose number arithmetic instead
of a guess (CX-38).

## A turn is exclusive, and that is enforced here

`SessionEntry.turn_lock` is what makes a concurrent turn a 409 rather than two
turns interleaving on one thread. The specification requires it (ST-9) and the
SDK does not provide it: `AsyncThread.turn()` would happily start a second.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_service.config import Settings, base_url as config_base_url
from agent_service.options import (
    McpServersNotAllowed,
    setting_source_overrides,
    UnsupportedOptions,
    resolve_timeout,
    unsupported,
)
from agent_service.sessions import CodexSession, RunTimeout, TurnOutcome

_log = logging.getLogger(__name__)

#: How long `CodexSession.open()` is given. The app-server unpacks 65 files on
#: first start (measured 0.53s warm), so this is generous by two orders of
#: magnitude -- it exists to bound a hang, not to police normal starts.
_DEFAULT_OPEN_TIMEOUT_S = 30.0

#: How often the reaper wakes. Not a precision instrument: a session is reaped
#: somewhere between `idle_ttl` and `idle_ttl + this`.
_REAP_INTERVAL_S = 30.0


class SessionNotFound(KeyError):
    """No live session with that id."""


class SessionLimitReached(RuntimeError):
    """`max_sessions` reached; close one before creating another."""


class SessionOpenTimeout(RuntimeError):
    """`CodexSession.open()` did not finish in time.

    The cap reservation it held is already released when this is raised -- the
    slot is not leaked.
    """


class SessionBusy(RuntimeError):
    """A turn is already running on this session."""


class SessionClosed(RuntimeError):
    """The session has been torn down and cannot take another turn."""


class SdkSessionIdUnsupported(RuntimeError):
    """This implementation cannot adopt a caller-supplied SDK session id.

    **Not a defect and not a temporary gap.** `AsyncCodex.thread_start()` takes
    no id -- Codex mints its own UUIDv7 and there is no parameter to override it
    (checked against the installed SDK, 2026-08-08). The specification's AS-13
    was written from the Claude CLI, which accepts one.

    Refusing is the honest answer. Accepting and returning a DIFFERENT id would
    break the exact guarantee AS-13 exists to provide -- that the caller's id
    identifies the conversation before the first model call -- and would do it
    silently, which is worse than a 400 that says so.
    """


@dataclass(slots=True)
class SessionEntry:
    """One registered session: the SDK conversation plus what the record needs.

    **Everything here is the specification's, not the SDK's.** `SessionRecord`
    is assembled from these fields and from nothing else, which is what keeps
    `api.py` free of Codex vocabulary.
    """

    session: CodexSession
    options: Any
    title: str | None = None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    turns: int = 0
    closed: bool = False
    last_turn: TurnOutcome | None = None

    #: The two options PATCH may change. Held here rather than pushed into the
    #: SDK because `AsyncThread.turn()` takes `model`, `sandbox` and
    #: `approval_mode` **per turn** -- so a change needs no control request and
    #: applies from the next turn. See `api.py`'s PATCH route: this is a real
    #: behavioural difference from the Claude build, where the change lands
    #: mid-turn.
    model: str | None = None
    permission_mode: str | None = None

    #: Exclusive for the duration of a turn. See the module docstring.
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def status(self) -> str:
        """`closed` | `running` | `idle` -- the specification's `SessionStatus`.

        Derived, never stored, so it cannot disagree with the lock that actually
        governs the turn. `locked()` is the truth about whether a turn is in
        flight; a stored flag would be one `finally` away from lying.
        """
        if self.closed:
            return "closed"
        return "running" if self.turn_lock.locked() else "idle"

    @property
    def total_cost_usd(self) -> float | None:
        """**Always `None`. Codex cannot price a turn, and `0.0` says it did.**

        Corrected 2026-08-08. This returned `0.0` on the reading that AS-17a
        makes the field a non-nullable float and *a floor, not a total*, so a
        session whose every turn went unpriced reads `0.0`.

        **That reading was one version out of date.** 0.16.0 made
        `SessionRecord.total_cost_usd` nullable for exactly this case, and its
        published description says so: *"null means this build cannot price a
        turn at all, which is not the same as 0.0. Some agent SDKs report token
        usage and no monetary figure; such an implementation reports null here
        for every session rather than a 0.0 that would read as free."* This is
        that implementation, and (CX-12) said the opposite
        until today.

        The difference is not cosmetic and it does not stay inside this process:
        the shared `sessions.total_cost_usd` column became nullable in revision
        `d3f9a0c15e27` so that a row from this build can record *unpriced*
        rather than *free*. A property returning `0.0` would have filled it with
        zeros the moment this build persists, which is the thing that change was
        made to prevent.

        **Still `Always`, and still not a measurement**: Codex reports no
        monetary figure anywhere in its package. If it ever does, this becomes a
        real value and the field was always shaped to carry one.
        """
        return None


class SessionRegistry:
    """The live sessions, the cap, and the reaper."""

    def __init__(
        self,
        settings: Settings,
        *,
        open_timeout_s: float = _DEFAULT_OPEN_TIMEOUT_S,
        session_factory: Any | None = None,
        recorder: Any | None = None,
    ) -> None:
        self._settings = settings
        self._open_timeout_s = open_timeout_s
        # **Never `None` in use.** `NULL_RECORDER` is the no-database path, and
        # it is a real object rather than a `if self._recorder:` at every call
        # site -- the branch that gets forgotten is the branch that silently
        # stops recording.
        if recorder is None:
            from agent_spec.db.recorder import NULL_RECORDER

            recorder = NULL_RECORDER
        self._recorder = recorder
        self._factory = session_factory or self._default_factory
        self._entries: dict[str, SessionEntry] = {}
        self._reserved = 0
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None
        # Closes that `close_all()` gave up waiting for. Held only so the
        # garbage collector cannot destroy a still-pending task; discarded as
        # soon as each one finishes.
        self._abandoned: set[asyncio.Task] = set()

    def _default_factory(self, options: Any, workspace_subdir: str | None) -> CodexSession:
        cwd = self._settings.workspace_dir
        if workspace_subdir:
            cwd = cwd / workspace_subdir
        return CodexSession(
            cwd=str(cwd),
            codex_home=str(self._settings.codex_home),
            # **Read per session, not once at import.** The value cannot change
            # under a running container -- nothing reloads it -- but reading it
            # here is what lets a test set the variable without a reimport, and
            # it costs one dict lookup per session creation.
            base_url=config_base_url(),
        )

    # --- creation ----------------------------------------------------------

    async def create(
        self,
        options: Any,
        title: str | None = None,
        sdk_session_id: str | None = None,
    ) -> str:
        """Open a session and register it. Returns the service-side handle.

        **The refusals come first**, before the cap is touched and before any
        subprocess starts: a request this build cannot honour must not consume a
        slot or spawn a process on its way to a 400.

        **This is the one chokepoint for options on this build**, which is why
        the check lives here rather than in each route. `/v1/sessions`,
        `/v1/query` and `/v1/query/stream` all arrive through it, and the two
        turn routes reuse the options the session was created with -- so an
        option refused here cannot reach a turn by another path.
        """
        refused = unsupported(options)
        if refused:
            raise UnsupportedOptions(refused)

        # **The deployment's answer, checked before the SDK's.** `mcp_servers`
        # is a supported field on this build now, so it is not in
        # `unsupported()` -- but an operator can still forbid it, and that
        # refusal has to happen here rather than being discovered as an agent
        # with none of the tools its caller configured.
        if getattr(options, "mcp_servers", None) and not self._settings.allow_mcp_servers:
            raise McpServersNotAllowed(sorted(options.mcp_servers))

        # Before the cap and before the spawn, like every other refusal here:
        # `setting_sources` is honoured now, but only for the members this build
        # has an equivalent for, and `local` is not one.
        setting_source_overrides(options)

        if sdk_session_id is not None:
            raise SdkSessionIdUnsupported(
                "This implementation cannot adopt a caller-supplied SDK session "
                "id: the Codex SDK mints the thread id itself and offers no way "
                "to set it. Omit sdk_session_id and read the id this service "
                "assigns from the 201 -- it is known at creation here, so the "
                "mapping still exists before the first model call."
            )

        async with self._lock:
            cap = self._settings.max_sessions
            if len(self._entries) + self._reserved >= cap:
                raise SessionLimitReached(
                    f"{len(self._entries) + self._reserved} of {cap} sessions are "
                    f"open; close one before creating another"
                )
            self._reserved += 1

        session = self._factory(options, getattr(options, "workspace_subdir", None))
        try:
            async with asyncio.timeout(self._open_timeout_s):
                await session.open(options, resume=getattr(options, "resume", None))
        except TimeoutError as exc:
            # Release BEFORE raising, and close what may have half-opened. A
            # reservation released only on the success path is a slot lost for
            # the process's lifetime.
            self._reserved -= 1
            with contextlib.suppress(Exception):
                await session.close()
            raise SessionOpenTimeout(
                f"the session did not open within {self._open_timeout_s:g}s"
            ) from exc
        except BaseException:
            self._reserved -= 1
            with contextlib.suppress(Exception):
                await session.close()
            raise

        sid = str(uuid.uuid4())
        entry = SessionEntry(
            session=session,
            options=options,
            title=title,
            model=getattr(options, "model", None) or self._settings.default_model,
            permission_mode=(
                getattr(options, "permission_mode", None)
                or self._settings.default_permission_mode
            ),
        )
        # Bare synchronous reconciliation -- NOT a second `async with self._lock`.
        # A task cancelled while awaiting a contended lock here would leak both
        # the reservation and an opened, unregistered session that nothing could
        # reach to close. Dict assignment and an integer decrement cannot yield,
        # so no lock is needed to keep them consistent with each other.
        self._entries[sid] = entry
        self._reserved -= 1
        # AFTER the entry is registered, so a row can never describe a session
        # this registry cannot reach. Enqueued, not written -- `session_opened`
        # returns without a database round trip, which is what keeps the create
        # path off the database's latency. Measured on the Claude build: the
        # 201 lands 0.25-0.38s before the transcript route answers 200, and a
        # console that opens a session and immediately fetches history will see
        # that window.
        self._recorder.session_opened(
            sid,
            title=title,
            model=entry.model,
            permission_mode=entry.permission_mode,
            at=entry.created_at,
        )
        return sid

    # --- lookup ------------------------------------------------------------

    def get(self, sid: str) -> SessionEntry:
        try:
            return self._entries[sid]
        except KeyError:
            raise SessionNotFound(sid) from None

    def list(self) -> list[tuple[str, SessionEntry]]:
        return list(self._entries.items())

    def check_available(self, sid: str) -> SessionEntry:
        """The entry, or the exception that says why it cannot take a turn.

        **Exists so the streaming route can answer 404 and 409 with real status
        codes.** That route must decide before it commits a 200, and the only
        alternative -- starting a turn to see whether one can be started -- is
        the opposite of a check.
        """
        entry = self.get(sid)
        if entry.closed:
            raise SessionClosed(f"session {sid} is closed; open a new one")
        if entry.turn_lock.locked():
            raise SessionBusy(
                f"a turn is already running on session {sid}; wait for it or interrupt it"
            )
        return entry

    # --- turns -------------------------------------------------------------

    async def send(self, sid: str, prompt: str, options: Any) -> TurnOutcome:
        """Take one turn on a session, exclusively.

        **`locked()` is checked rather than awaited.** A second turn must be
        refused with a 409, not queued behind the first -- a caller that gets a
        200 after an unbounded wait cannot tell that from a slow agent, and the
        specification makes concurrency the caller's error to fix.
        """
        entry = self.check_available(sid)
        async with entry.turn_lock:
            # Re-checked INSIDE the lock: `locked()` above and the acquisition
            # here are two steps, and a DELETE can land between them.
            if entry.closed:
                raise SessionClosed(f"session {sid} is closed; open a new one")
            entry.last_used_at = time.time()
            # A run id per turn, minted here because the recorder needs one
            # before the turn starts -- events arrive against it while the turn
            # is still running.
            run_id = str(uuid.uuid4())
            started = time.time()
            # `session_id` is the SDK's, and unlike the Claude build it is
            # already known: Codex mints the thread id at `thread_start()`
            # rather than on the first turn. So this build never has to leave it
            # None here and let `finish_run` carry the resolved value.
            self._recorder.start_run(
                run_id,
                sid=sid,
                session_id=entry.session.sdk_session_id,
                prompt=prompt,
                at=started,
            )
            outcome = None
            try:
                # **Resolved per turn, not per session**, because `timeout_s` is a
                # request option: two turns on one conversation may legitimately
                # carry different budgets. `resolve_timeout` refuses a value above
                # the deployment's cap with a 400 rather than clamping it -- a
                # silently shortened deadline produces a 504 the caller cannot
                # explain.
                outcome = await entry.session.send(
                    prompt,
                    self._turn_options(entry, options),
                    timeout_s=resolve_timeout(
                        getattr(options, "timeout_s", None), self._settings
                    ),
                )
            except RunTimeout as exc:
                # **The partial outcome is adopted, not discarded.** Without this
                # the `finally` below would record `outcome=None` and
                # `entry.last_turn` would keep pointing at the PREVIOUS turn --
                # so a timed-out turn would be invisible on the session record
                # and the turn before it would be reported as the last one.
                outcome = exc.outcome
                raise
            finally:
                # Counted and stamped even on failure. A turn that broke still
                # happened, and a `last_used_at` that only moves on success
                # makes the reaper collect a session whose turn is failing
                # repeatedly -- the one it should leave alone longest.
                entry.turns += 1
                entry.last_used_at = time.time()
                # **In the `finally`, and it must never raise.** A turn that
                # broke still happened; a recorder that threw here would turn a
                # failed turn into a failed request and lose the row besides.
                # `RunRecorder`'s contract is the opposite of
                # `SessionStore.append`'s, which MUST raise -- they look alike
                # and behave oppositely, which is why both say so out loud.
                from agent_service.persistence import to_run_outcome

                self._recorder.finish_run(
                    run_id,
                    sid=sid,
                    session_id=entry.session.sdk_session_id,
                    outcome=(
                        to_run_outcome(outcome, entry.session.sdk_session_id)
                        if outcome is not None
                        else None
                    ),
                    # Codex prices nothing, so there is no per-turn figure
                    # either. `None` means "nobody can say", never 0.0.
                    turn_cost_usd=None,
                    interrupted=bool(outcome is not None and outcome.status == "interrupted"),
                    # Read off the outcome since 2026-08-08, when this build
                    # started bounding turns. It was hardcoded `False` while
                    # nothing could time out, which was true then and is a lie
                    # now -- and a stored run is where the 504 has already gone.
                    timed_out=bool(outcome is not None and outcome.timed_out),
                    at=time.time(),
                )
                # **In the `finally`, so a timed-out turn is the session's last
                # turn.** It used to sit after the `try`, which is unreachable on
                # any exception -- see the `except RunTimeout` above. Guarded on
                # `None` so a turn that produced nothing at all does not erase
                # the record of the one before it.
                if outcome is not None:
                    entry.last_turn = outcome
            return outcome

    def _turn_options(self, entry: SessionEntry, options: Any) -> Any:
        """Fold the session's PATCHable state into this turn's options.

        PATCH writes `entry.model` / `entry.permission_mode`; the SDK takes both
        per turn. Per-request options still win -- a caller that names a model on
        the turn means that turn.
        """
        if options is None:
            return entry.options
        if getattr(options, "model", None) is None and entry.model is not None:
            options = options.model_copy(update={"model": entry.model})
        if (
            getattr(options, "permission_mode", None) is None
            and entry.permission_mode is not None
        ):
            options = options.model_copy(update={"permission_mode": entry.permission_mode})
        return options

    async def interrupt(self, sid: str) -> bool:
        """Ask a running turn to stop. `False` when there was nothing to stop."""
        return await self.get(sid).session.interrupt()

    # --- teardown ----------------------------------------------------------

    async def close(self, sid: str) -> None:
        """Close one session. Raises if the teardown fails.

        **A failed teardown leaves the session registered**, so the caller can
        retry and the registry keeps its handle on a possibly-live subprocess.
        Answering 204 on a close that did not happen would report a subprocess
        as gone while it is still running.
        """
        entry = self.get(sid)
        entry.closed = True
        await entry.session.close()
        self._entries.pop(sid, None)
        # AFTER the close succeeded, so the row cannot say a subprocess is gone
        # while it is still running -- the same reason the entry is only popped
        # here. `status` on the record is derived, so this is what makes a
        # CLOSED session distinguishable from one that vanished.
        self._recorder.session_closed(sid, status="closed", at=time.time())

    async def reap_once(self) -> int:
        """Close sessions idle beyond the TTL. Returns how many went.

        **Skips anything running.** What a close does to an actively draining
        turn is not measured here, and the reaper is not the place to find out;
        a hung turn ends up idle and becomes reclaimable on a later tick.
        """
        ttl = self._settings.session_idle_ttl_s
        if ttl <= 0:
            return 0
        cutoff = time.time() - ttl
        async with self._lock:
            stale = [
                sid
                for sid, e in self._entries.items()
                if e.last_used_at < cutoff and e.status == "idle"
            ]
        reaped = 0
        for sid in stale:
            try:
                await self.close(sid)
            except Exception:  # noqa: BLE001 - retried on the next tick
                _log.warning("reaper could not close session %s; will retry", sid)
            else:
                reaped += 1
        return reaped

    async def close_all(self, budget_s: float | None = None) -> None:
        """Shutdown, within ONE aggregate budget. Best effort inside it.

        **The budget is the point** (CX-38). This runs from the ASGI lifespan,
        so its total IS the shutdown, and Docker SIGKILLs at
        `stop_grace_period` whether or not it has finished. It used to be
        bounded by nothing at all: N sequential closes, each bounded only by
        the SDK's own ~3s, so 16 sessions could spend 48s inside a 60s grace
        period that also had to cover a 30s request drain. Every wait below is
        charged against one deadline taken at entry, and
        `Settings.shutdown_budget_s` is what compose's number is derived from.

        **Each close gets a FAIR SHARE of what is left** -- `remaining / still
        to attempt` -- rather than a fixed slice. A close that returns early
        hands its unused time to the rest, and one wedged session cannot eat
        the budget and cost the healthy ones their clean teardown.

        **Cancelling a close does not stop it, and that is worth knowing before
        reading the numbers.** `AsyncCodexClient.close()` is `asyncio.to_thread`
        around a synchronous close, so cancelling the *wait* abandons the
        result and leaves the thread running. There is nothing to kill it with:
        the SDK exposes no handle on the subprocess, and its own close already
        ends in `proc.kill()` on any failure -- which is why this has no force-
        kill phase where the Claude build has one. An abandoned close is
        reported, not retried.

        One `Exception` does not stop the sweep. A `BaseException` --
        cancellation above all -- propagates and ABORTS it, because widening
        that catch would swallow the shutdown telling this to stop.

        **Only a close that RETURNED deregisters a session**, so `list()`
        afterwards names everything not known to have shut down cleanly, and
        the summary can say so. It used to pop on failure, which made a failed
        teardown indistinguishable from a successful one a moment later.

        Says what it did, always, in one line: a clean sweep and a sweep that
        never ran must not look identical in a container's logs.
        """
        budget = self._settings.shutdown_budget_s if budget_s is None else budget_s
        started = time.monotonic()
        deadline = started + budget

        attempted: set[str] = set()
        closed: list[str] = []
        failed: list[str] = []
        unfinished: list[str] = []
        while True:
            pending = [sid for sid in self._entries if sid not in attempted]
            if not pending:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sid = pending[-1]  # LIFO: the newest session is the likeliest busy
            attempted.add(sid)
            outcome = await self._close_within(sid, remaining / len(pending))
            if outcome == "closed":
                closed.append(sid)
            elif outcome == "failed":
                failed.append(sid)
            else:
                unfinished.append(sid)

        unreached = [sid for sid in self._entries if sid not in attempted]
        elapsed = time.monotonic() - started
        # `swept` counts every sid this call touched or should have: a summary
        # whose parts do not add up to its total is worse than no summary.
        summary = (
            "close_all: swept %d session(s) in %.3fs of a %.1fs budget: "
            "%d closed cleanly, %d failed, %d abandoned, %d never reached"
        )
        args = (
            len(closed) + len(failed) + len(unfinished) + len(unreached),
            elapsed,
            budget,
            len(closed),
            len(failed),
            len(unfinished),
            len(unreached),
        )
        if failed or unfinished or unreached:
            # Named, because nothing will retry them and their app-server
            # subprocesses may still be alive when the container is killed.
            _log.error(
                summary + "; still registered: %s",
                *args,
                ", ".join([*failed, *unfinished, *unreached]),
            )
        else:
            _log.info(summary, *args)

    async def _close_within(self, sid: str, slice_s: float) -> str:
        """One bounded close attempt. `"closed"` | `"failed"` | `"unfinished"`.

        **Only `close_all()` uses this.** `close()` and `reap_once()` await the
        SDK's own bound, which is right for them: the DELETE caller asked for
        that close and the reaper retries on the next tick. Neither is racing a
        SIGKILL.
        """
        task = asyncio.create_task(self.close(sid))
        try:
            done, _ = await asyncio.wait({task}, timeout=slice_s)
        except BaseException:
            # Our caller cancelled us. The sweep aborts; take the in-flight
            # close down with it rather than detaching a task nothing will
            # ever observe again.
            task.cancel()
            raise
        if not done:
            # **Cancelled and abandoned in the same breath, with no grace
            # period for the acknowledgement** -- which is where this differs
            # from the Claude build and the reason is the SDK. The close is
            # `asyncio.to_thread` around a synchronous one, so cancelling ends
            # the *task* at once and leaves the thread running whatever
            # happens: waiting for it to acknowledge buys nothing and spends
            # budget the sessions after it need.
            task.cancel()
            # A strong reference until it finishes, or the garbage collector
            # destroys a pending task and turns a bounded shutdown into "Task
            # was destroyed but it is pending!" on the way out.
            self._abandoned.add(task)
            task.add_done_callback(self._abandoned.discard)
            _log.warning(
                "close_all: session %s did not close within its %.3fs share of "
                "the shutdown budget; abandoned it",
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

    # --- the reaper task ---------------------------------------------------

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop())

    async def stop_reaper(self) -> None:
        task, self._reaper = self._reaper, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(_REAP_INTERVAL_S)
            try:
                await self.reap_once()
            except Exception:  # noqa: BLE001 - a reaper that dies stops reaping
                _log.exception("reap tick failed; the loop continues")
