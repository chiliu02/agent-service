"""The seam between a Pi turn and the platform's `runs` row.

**This module is the whole of what persistence costs a fourth implementation.**
Everything below the seam -- the ORM, the queue, the repository, the reads, the
revision check, the lifecycle -- is `agent_spec.db`, shared and already tested.
What cannot be shared is the mapping from *this* agent's turn into the shape the
schema stores, because that shape is the specification's and the turn is Pi's.

    a TurnResult  ->  to_run_outcome()  ->  RunOutcome  ->  a `runs` row
    ^^^^^^^^^^^^      ^^^^^^^^^^^^^^^^      ==========
    this agent's      this module           the platform's

## What this build CAN fill that two of the others cannot

`total_cost_usd` is **real here** (`PI-17`) -- in USD, from the agent's own
per-model pricing, on every provider. Of the four builds only the Claude one has
also been able to fill it, and it fills it from a figure that accumulates over a
connection; this one sums the run's own model calls, so the row is that turn's
spend and nothing else.

`model_usage` is **per turn, not cumulative** (`PI-16`), checked rather than
assumed. Summing these rows across a session is correct here and would
double-count on the Claude build.

## Five fields this agent cannot fill, and why they are `None` rather than absent

| Field | Why |
|---|---|
| `permission_denials` | there is no denial EVENT to log. A tool absent from `--tools` is never offered to the model, so nothing is refused at run time -- and an empty list would claim there were none (`PI-24`) |
| `duration_api_ms` | the stream times nothing; wall clock for the whole invocation is all there is |
| `errors`, `api_error_status` | a failed turn is exit 1 and a line of text, never a structured HTTP status (`PI-15`) |
| `limit_hit` | nothing caps the agent's own loop, so no limit exists to hit (`PI-26`) |

**`None` is not the same as absent**, which is why they are written out rather
than defaulted silently: a reader of a `runs` row must be able to tell "this
build cannot say" from "nobody has looked yet", and the column being nullable is
what carries that.
"""

from __future__ import annotations

from typing import Any

from agent_spec.db.outcome import RunOutcome


def to_run_outcome(result: Any, sdk_session_id: str | None) -> RunOutcome:
    """A `TurnResult` as the platform's stored shape.

    **Mirrors `api._turn_response()` deliberately**: that function renders the
    same turn as a `RunResponse` for the wire and this one renders it for the
    database, and they must agree -- a field read differently here than there is
    a row that contradicts the response the caller already got.
    """
    usage: dict[str, Any] = getattr(result, "usage", None) or {}
    return RunOutcome(
        # **The conversation's id, not the turn's** (`PI-13`). It survives a
        # resume, so grouping rows by it is meaningful here where it is wrong on
        # the Gemini build.
        session_id=sdk_session_id,
        result=result.assistant_text,
        # **The agent's own `stopReason`, and the exit code beside it**
        # (`PI-61`). The exit code alone was wrong here: under `--mode json` it
        # is 0 whatever happened, so a turn the vendor refused was stored as a
        # success. A turn that merely declined to do the work still is not an
        # error -- the agent says `stop` for that.
        is_error=result.agent_reported_failure or bool(getattr(result, "exit_code", 0)),
        subtype=None,
        stop_reason=result.stop_reason,
        # **The agent's own `errorMessage`** (`PI-61`), which is where the
        # VENDOR's status text is on a refused turn. Null on every other ending.
        terminal_reason=result.error_detail,
        # **The agent's own loop count, and the field means what it says here**
        # (`PI-26`): one invocation is one HTTP turn and several model calls, so
        # this is how many the agent took.
        num_turns=len(getattr(result, "turn_usages", []) or []) or None,
        duration_ms=None,
        usage=usage or None,
        model_usage=result.models_used or None,
        # **Real, and summed across the run's model calls** (`PI-17`).
        total_cost_usd=result.total_cost_usd,
        # The five this agent cannot fill. See the module docstring.
        limit_hit=None,
        permission_denials=None,
        duration_api_ms=None,
        errors=None,
        api_error_status=None,
    )
