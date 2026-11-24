"""The seam between running an agent and recording what it did.

`runner.py` and `sessions.py` call a `RunRecorder`. Nothing in this package
implements one that touches a database -- plan-03 Task 4 supplies that. Until
then `NULL_RECORDER` is the default everywhere, which is also the shipped
configuration whenever `AGENT_SERVICE_DATABASE_URL` is unset.

Both drivers depend on this protocol, never on SQLAlchemy. If a later task finds
itself importing a database module into `runner.py` or `sessions.py`, the seam is
in the wrong place.

## Every method is synchronous, and that is the design

Not an oversight, and not a thing to "fix" when the real implementation lands.
Three separate reasons, any one of which is sufficient:

1. **plan-03's global constraint** -- no database round trip on the SSE path,
   ever. An `async def` here would put an await point between `normalize()` and
   the `yield` that hands the frame to the consumer, which is exactly the stall
   the constraint forbids. A synchronous signature makes it structurally
   impossible instead of a rule someone has to remember.
2. **`_send_impl`'s cancellation semantics.** A new await point inside that
   drain loop is a new place for a `CancelledError` to land, in the one function
   whose `recorded` / `_turn_abandoned` / `except BaseException` interplay is
   documented as the hardest thing in this codebase. Adding suspension points
   there to support persistence would be trading a working invariant for a
   feature.
3. **`registry.create()` has no suspension point by design** -- its comment at
   the insert states that both statements are synchronous so no cancellation can
   land between "open() succeeded" and "registered". A session-level recorder
   call there must not reintroduce one.

The real implementation therefore enqueues and returns. Its I/O happens in a
background writer (plan-03 Task 3).

## Implementations MUST NOT raise

Load-bearing, and easy to get wrong. A recorder that raises inside
`_send_impl`'s drain lands in its `except BaseException` branch, which would
overwrite `last_turn` with `outcome=None`, re-arm `_turn_abandoned`, and fire a
control request at a turn that had actually succeeded -- persistence corrupting
the accounting of the thing it exists to observe. Swallow and log internally.
`NullRecorder` satisfies this trivially.

The same applies to `finish_run`, which is called from that function's `finally`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported lazily: `runner` imports THIS module at runtime for
    # `NULL_RECORDER`, so a runtime import back would be a cycle. `errors.py`
    # documents what that failure looks like when it is not avoided.
    from agent_spec.db.outcome import RunOutcome


class RunRecorder(Protocol):
    """Where a run's history goes. See the module docstring for the specification.

    `run_id` is minted by the caller, not returned from here, so a run has an
    identity even with no recorder attached and so implementations stay pure
    sinks.
    """

    def session_opened(
        self,
        sid: str,
        *,
        title: str | None,
        model: str | None,
        permission_mode: str | None,
        at: float,
    ) -> None:
        """A session was created and registered.

        NOT WIRED YET. `registry.py` mints `sid` and is where this belongs, but
        it is not in plan-03 Task 1's file list; Task 4 wires it alongside the
        database recorder. Declared now so the protocol does not change shape
        under an implementation later.

        The design's `sessions.options JSONB` column has no argument here
        on purpose: "the resolved options" is a `ClaudeAgentOptions` dataclass
        that can hold callables, which `to_jsonable` renders as
        `{"_unserializable": ...}`. What to store is a decision for Task 2's
        schema work, not something to guess at here.
        """
        ...

    def session_closed(self, sid: str, *, status: str, at: float) -> None:
        """A session was closed and removed. NOT WIRED YET -- see above."""
        ...

    def start_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        prompt: str,
        at: float,
    ) -> None:
        """A run or turn began.

        TWO identifiers, and they are not interchangeable:

        * `sid` is the service-side session id `registry.py` mints -- the
          STORED KEY (plan-03 Task 2), and the only one a client has ever seen.
          `None` for a one-shot `POST /v1/query`, which is never registered.
        * `session_id` is the SDK's, `None` until the first `SystemMessage` of
          the first turn arrives, so on a session's opening turn it is genuinely
          unknown here and `finish_run` carries the resolved value.
        """
        ...

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """One normalized `AgentEvent`, already in wire shape.

        The hot path -- called once per SDK message, for every run. Must not
        block and must not raise.
        """
        ...

    def finish_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        outcome: RunOutcome | None,
        turn_cost_usd: float | None,
        interrupted: bool,
        timed_out: bool,
        at: float,
    ) -> None:
        """A run or turn ended, however it ended.

        `outcome is None` means the run never consumed its own `ResultMessage` --
        a crash, an abandoned consumer, or a timeout. That is a real and distinct
        state, not an error to paper over; `runner.Run` documents callers MUST
        handle it separately from a clean finish.

        `turn_cost_usd` follows `RunResponse.turn_cost_usd`'s meaning exactly:
        `None` is "nobody can say", never `0.0`. An interrupted turn is
        measurably not free, merely unattributed -- see
        `runner.unattributed_abort`.
        """
        ...


class NullRecorder:
    """Records nothing. The default, and the no-database configuration.

    Not a test double -- this is what ships until a database is configured, so
    it must stay exactly as cheap as it looks.
    """

    __slots__ = ()

    def session_opened(
        self,
        sid: str,
        *,
        title: str | None,
        model: str | None,
        permission_mode: str | None,
        at: float,
    ) -> None:
        return None

    def session_closed(self, sid: str, *, status: str, at: float) -> None:
        return None

    def start_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        prompt: str,
        at: float,
    ) -> None:
        return None

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        return None

    def finish_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        outcome: RunOutcome | None,
        turn_cost_usd: float | None,
        interrupted: bool,
        timed_out: bool,
        at: float,
    ) -> None:
        return None


# One shared instance. Stateless and immutable, so there is no reason for every
# Run and AgentSession to allocate its own.
NULL_RECORDER: RunRecorder = NullRecorder()
