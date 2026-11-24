"""The seam between a Codex turn and the platform's `runs` row.

**This module is the whole of what persistence costs a second implementation**,
and that is the point of Plan 9 having moved the rest. Everything below the seam
-- the ORM, the queue, the repository, the reads, the boot gate, the lifecycle
-- is `agent_spec.db`, shared and already tested. What cannot be shared is the
mapping from *this* SDK's turn outcome into the shape the schema stores, because
that shape is the specification's and the outcome is Codex's.

## The direction

    a Codex TurnOutcome  ->  to_run_outcome()  ->  RunOutcome  ->  a `runs` row
    ^^^^^^^^^^^^^^^^^^^      ^^^^^^^^^^^^^^^^      ==========
    this SDK's               this module           the platform's

`impl/claude-python/src/agent_service/runner.py::build_outcome` is the same
function against the other SDK. Neither is shareable; everything they feed is.

## Four fields Codex cannot fill, and why they are `None` rather than absent

`RunOutcome` carries seventeen fields because the `runs` table does. Four of
them have no Codex counterpart at all:

| Field | Why |
|---|---|
| `total_cost_usd` | **Measured on a real completed turn, 2026-08-08**: Codex reports no monetary figure anywhere. This is why `sessions.total_cost_usd` became nullable in revision `d3f9a0c15e27` -- `0.0` would read as *free* for the life of every session |
| `model_usage` | cumulative-per-connection in the Claude build; Codex has no such figure and deriving one from `usage` would give it a scope it does not have |
| `permission_denials` | Codex governs by sandbox, not by a per-tool decision log |
| `duration_api_ms`, `api_error_status` | Plan 9 §1 named these as the SDK-specific residue *"another build simply leaves NULL"*. This is that build |

**`None` is not the same as absent**, which is why they are written out rather
than defaulted silently: a reader of a `runs` row must be able to tell "this
build cannot say" from "nobody has looked yet", and the column being nullable is
what carries that.
"""

from __future__ import annotations

from typing import Any

from agent_spec.db.outcome import RunOutcome


def to_run_outcome(outcome: Any, sdk_session_id: str | None) -> RunOutcome:
    """A Codex `TurnOutcome` as the platform's stored shape.

    Mirrors `api._summary()` deliberately: that function renders the same
    outcome as a `RunResponse` for the wire, and this one renders it for the
    database. **They must agree**, because the tables store what `/v1` returns
    (Plan 9 §1) -- so any field read differently here than there is a row that
    contradicts the response the caller already got.
    """
    status = outcome.status
    return RunOutcome(
        session_id=sdk_session_id,
        result=outcome.final_response,
        # `status` is set only by `turn/completed`, so a failed turn is one that
        # reached an end and said so -- not one that never arrived.
        is_error=status == "failed",
        subtype=status,
        # Codex has no separate stop reason; `status` is the whole answer, and
        # duplicating it here would invent a second field that cannot disagree.
        stop_reason=None,
        terminal_reason=outcome.error,
        limit_hit=None,
        num_turns=None,
        duration_ms=outcome.duration_ms,
        usage=outcome.usage,
        # The four Codex cannot fill. See the module docstring.
        total_cost_usd=None,
        model_usage=None,
        permission_denials=None,
        duration_api_ms=None,
        errors=None,
        api_error_status=None,
    )
