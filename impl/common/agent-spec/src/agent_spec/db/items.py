"""What travels on the queue between a turn and the database.

Its own module rather than living in `writer.py`, because `writer` imports
`repository` (to apply a batch) and `repository` needs these types (to know what
it is applying). Defining them in either one makes those two modules import each
other -- the cycle `errors.py` documents at length after it bit this codebase
once already.

Plain dataclasses, no SQLAlchemy: `writer.enqueue()` runs on the SSE hot path
and must not touch the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SessionOpened:
    sid: str
    title: str | None
    model: str | None
    permission_mode: str | None
    at: float
    # The container's `AGENT_ID`, filled by `DatabaseRecorder` from a process
    # constant -- never from the caller, which is what makes it provenance
    # rather than an assertion. Last, with a default, so nothing that
    # constructs this positionally has to change.
    agent_id: str | None = None


@dataclass(slots=True)
class SessionClosed:
    sid: str
    status: str
    at: float


@dataclass(slots=True)
class RunStarted:
    run_id: str
    # The service-side sid, or None for a one-shot run. Also None for a session
    # turn until plan-03 Task 4 gives `AgentSession` its sid -- see
    # `models.Run.session_id`.
    sid: str | None
    sdk_session_id: str | None
    prompt: str
    at: float


@dataclass(slots=True)
class RunFinished:
    run_id: str
    # The service-side sid, needed to roll this turn up into its session's
    # counters. None for a one-shot run, which has no `sessions` row.
    sid: str | None
    sdk_session_id: str | None
    # **TYPED since 2026-08-08, and the reason it was not is gone.** It read
    # `outcome: Any | None`, explained as keeping this module free of "an import
    # back into the drivers" -- true when `RunOutcome` lived in `runner.py`,
    # which imports the SDK. It now lives in `agent_spec.db.outcome`, which
    # imports nothing but the standard library.
    #
    # The annotation is not cosmetic. `repository.py` reads FIFTEEN attributes
    # off this field, so `Any` made the persistence layer structurally coupled
    # to one SDK's outcome object while declaring no such thing -- which is
    # exactly what would stop the layer being shared between implementations.
    #
    # `None` means the run never consumed its own `ResultMessage`: a real state,
    # not an error to paper over.
    outcome: RunOutcome | None
    turn_cost_usd: float | None
    interrupted: bool
    timed_out: bool
    at: float


@dataclass(slots=True)
class EventAppended:
    run_id: str
    event: dict[str, Any]

    @property
    def droppable(self) -> bool:
        """Sacrificed first when the queue is under pressure.

        Token deltas: the assistant message that follows carries the same text,
        so dropping these loses granularity, not content.
        """
        return self.event.get("type") == "stream_event"


Item = SessionOpened | SessionClosed | RunStarted | RunFinished | EventAppended
