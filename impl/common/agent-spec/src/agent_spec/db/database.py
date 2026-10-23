"""`RunRecorder` backed by the queue writer.

A pure translation layer: protocol call in, queue item out. It holds no state
and does no IO, so the only way it can fail is by raising -- which the recorder
specification forbids absolutely, because a raise here lands in `_send_impl`'s
`except BaseException` and mislabels a turn that actually succeeded.

`QueueWriter.enqueue` already swallows everything. This module stays free of
logic for the same reason: the less that happens between the drain loop and the
deque, the less there is to go wrong on the hot path.
"""

from __future__ import annotations

from typing import Any

from agent_spec.db.items import (
    EventAppended,
    RunFinished,
    RunStarted,
    SessionClosed,
    SessionOpened,
)
from agent_spec.db.writer import QueueWriter


class DatabaseRecorder:
    """Satisfies `recorder.RunRecorder`. Structural, not by inheritance."""

    __slots__ = ("_writer", "_agent_id")

    def __init__(self, writer: QueueWriter, agent_id: str | None = None) -> None:
        self._writer = writer
        # A PROCESS CONSTANT, held here rather than passed per session.
        #
        # This is what makes Studio's acceptance clause 4 -- "never settable by
        # a caller" -- structural instead of checked. `session_opened` takes no
        # `agent_id` parameter, so there is no argument for a request value to
        # reach, and a future route that wanted to supply one would have to
        # change this protocol to do it. A validation rule can be forgotten; a
        # missing parameter cannot.
        self._agent_id = agent_id

    def session_opened(
        self,
        sid: str,
        *,
        title: str | None,
        model: str | None,
        permission_mode: str | None,
        at: float,
    ) -> None:
        self._writer.enqueue(
            SessionOpened(sid, title, model, permission_mode, at, self._agent_id)
        )

    def session_closed(self, sid: str, *, status: str, at: float) -> None:
        self._writer.enqueue(SessionClosed(sid, status, at))

    def start_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        prompt: str,
        at: float,
    ) -> None:
        self._writer.enqueue(RunStarted(run_id, sid, session_id, prompt, at))

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._writer.enqueue(EventAppended(run_id, event))

    def finish_run(
        self,
        run_id: str,
        *,
        sid: str | None,
        session_id: str | None,
        outcome: Any | None,
        turn_cost_usd: float | None,
        interrupted: bool,
        timed_out: bool,
        at: float,
    ) -> None:
        self._writer.enqueue(
            RunFinished(
                run_id, sid, session_id, outcome, turn_cost_usd, interrupted, timed_out, at
            )
        )
