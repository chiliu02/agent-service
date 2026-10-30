"""Caller-chosen run ids, and the state of a stored run.

**Imports no database code**, so a build with history off can use all of it.
The stored-run half of the uniqueness check is the caller's: it holds the
database session, and `agent_spec.db.queries.run_exists` is the query.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Literal

#: The title of the `409` that refuses a used `run_id`. Every build sends this
#: one AND the type below, because two builds tell their 409s apart by title
#: and two by type.
RUN_ID_IN_USE_TITLE = "Run id in use"

#: Its `type`, under the base every build already names its problems with.
RUN_ID_IN_USE_TYPE = "https://agent-service.invalid/problems/run-id-in-use"

RunState = Literal["running", "ended", "lost"]

#: When this process started, on the clock that `start_run` stamps runs with.
#: Set at import, which is at boot for every build: the API module imports it.
BOOTED_AT = time.time()


class RunIdInUse(RuntimeError):
    """A caller-chosen `run_id` that names a turn already started."""

    def __init__(self, run_id: str) -> None:
        super().__init__(
            f"run_id {run_id!r} is already in use. An id names one turn, once: "
            "choose a new id for a new turn"
        )
        self.run_id = run_id


class RunIdLedger:
    """The caller-chosen run ids that this process has started a turn under.

    **Claim before the turn starts, release only if it did not.** A refusal
    that comes before the agent is reached -- an unknown or busy session --
    gives the id back, so the caller can send the same turn again. Once a turn
    has started, its id stays claimed whatever the turn then does.

    Synchronous on purpose: no await lies between the check and the add, so two
    requests with one id cannot both pass.

    It grows by one string per caller-chosen id for the life of the process.
    That is the price of refusing a reused id with history off, where nothing
    else remembers it.
    """

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, run_id: str) -> None:
        if run_id in self._claimed:
            raise RunIdInUse(run_id)
        self._claimed.add(run_id)

    def release(self, run_id: str) -> None:
        self._claimed.discard(run_id)

    def __contains__(self, run_id: object) -> bool:
        return run_id in self._claimed


def run_state(started_at: datetime | float, finished_at: datetime | float | None) -> RunState:
    """`ended` once finished; else `running`, unless it predates this process.

    A run with no finish that started before this process booted was cut off
    by a restart, and nothing will ever finish it: that is `lost`. A run that
    started after the boot is taken to be this process's own, still under way.
    """
    if finished_at is not None:
        return "ended"
    started = started_at.timestamp() if isinstance(started_at, datetime) else started_at
    return "lost" if started < BOOTED_AT else "running"
