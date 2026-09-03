"""The seam between a Gemini turn and the platform's `runs` row.

**This module is the whole of what persistence costs a third implementation.**
Everything below the seam -- the ORM, the queue, the repository, the reads, the
revision check, the lifecycle -- is `agent_spec.db`, shared and already tested.
What cannot be shared is the mapping from *this* agent's turn into the shape the
schema stores, because that shape is the specification's and the turn is Gemini's.

    a TurnResult  ->  to_run_outcome()  ->  RunOutcome  ->  a `runs` row
    ^^^^^^^^^^^^      ^^^^^^^^^^^^^^^^      ==========
    this agent's      this module           the platform's

The Codex build's `persistence.py` and the Claude build's `runner.build_outcome`
are the same function against their own agents. **Seventy-odd lines is the whole
cost, and that is the measurement Plan 9 wanted**: the third build did not need
the layer changed, only this file written.

## Six fields this agent cannot fill, and why they are `None` rather than absent

`RunOutcome` carries seventeen fields because the `runs` table does.

| Field | Why |
|---|---|
| `total_cost_usd` | **The agent reports tokens and latency and no monetary figure at all** (GP-16). `0.0` would read as *free*, which is why `sessions.total_cost_usd` is nullable |
| `permission_denials` | the boundary here is a generated policy file the agent loads (GP-19), and a denied tool is REMOVED from the model's context rather than refused (GP-20) -- so there is no denial event to log, and an empty list would claim there were none |
| `duration_api_ms` | the stats block times the whole turn, not the API call inside it |
| `errors`, `api_error_status` | a failed turn is an exit code and a text envelope (GP-06, GP-09), never a structured HTTP status |
| `limit_hit` | exit 53 is documented as the turn limit and was never reproduced (GP-06), so this build will not claim to have detected one |

**`None` is not the same as absent**, which is why they are written out rather
than defaulted silently: a reader of a `runs` row must be able to tell "this
build cannot say" from "nobody has looked yet", and the column being nullable is
what carries that.

## What this build CAN fill that the others cannot

`model_usage` is real here and it is **per turn, not cumulative** (GP-16) --
the opposite of the Claude build, where the figure accumulates over a
connection. So summing these rows across a session is correct here and would
double-count there. The Codex build has no such figure at all.
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
    stats: dict[str, Any] = getattr(result, "stats", None) or {}
    return RunOutcome(
        # **The AGENT's id for THIS turn** (GP-34). On a resumed session it is a
        # new value every turn, so a reader groups by the service-side `sid` and
        # never by this.
        session_id=sdk_session_id,
        result=result.assistant_text,
        # **A refusal exits 0 and says `"success"`** (GP-18), so this cannot be
        # derived from the text: a turn that declined to do the work is not an
        # error, and only the envelope's own status may say otherwise.
        is_error=str(stats.get("status", "")) == "error",
        subtype=stats.get("status") or None,
        # The agent has no separate stop reason; the envelope's status is the
        # whole answer, and duplicating it would invent a second field that
        # cannot disagree with the first.
        stop_reason=None,
        terminal_reason=None,
        num_turns=None,
        duration_ms=stats.get("duration_ms"),
        # Passed through UNCHANGED, including `tool_calls`, which undercounts:
        # it reported 0 on a turn carrying a tool_use and a tool_result (GP-43).
        # Correcting it here would put a number in the row that the agent never
        # said and that `/v1` does not return.
        usage=stats or None,
        model_usage=dict(stats.get("models") or {}) or None,
        # The six this agent cannot fill. See the module docstring.
        total_cost_usd=None,
        limit_hit=None,
        permission_denials=None,
        duration_api_ms=None,
        errors=None,
        api_error_status=None,
    )
