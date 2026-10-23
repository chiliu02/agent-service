"""What a turn produced, normalised — the shape a `runs` row is written from.

**Its own module since 2026-08-08, and the move is the point.** It lived in
`runner.py`, which imports `claude_agent_sdk`, so the shape every stored turn is
written from was defined inside an SDK-coupled module. Nothing in the class was
ever SDK-typed — seventeen fields of `str`, `int`, `bool`, `dict` and `list` —
but its *address* said otherwise, and that is what stopped the persistence layer
from being shared between implementations.

## It is the specification's shape, not this SDK's

Read the fields against `agent_spec.openapi.schemas.RunResponse` and they line up, which
is not a coincidence: **the tables store what `/v1` returns** (Plan 9 §1,
AS-30). Three fields have no `RunResponse` counterpart —
`duration_api_ms`, `errors`, `api_error_status` — and those are precisely the
"SDK-specific residue" Plan 9 §1 named, the ones *"another build simply leaves
NULL"*. They are diagnostic detail a stored row wants and a streaming caller
does not.

## Where the SDK stops

    a ResultMessage  ->  runner.build_outcome()  ->  RunOutcome  ->  a row
    ^^^^^^^^^^^^^^^      ^^^^^^^^^^^^^^^^^^^^^^      ============
    the SDK's            THIS build's mapping        the seam

Everything left of the seam is one implementation's business. Everything right
of it is the platform's, because the schema is. A second implementation writes
its own `build_outcome` equivalent against its own SDK and shares everything
downstream — which is the whole reason this file exists separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RunOutcome:
    session_id: str | None = None
    result: str | None = None
    is_error: bool = False
    subtype: str | None = None
    stop_reason: str | None = None
    terminal_reason: str | None = None
    limit_hit: str | None = None
    num_turns: int | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None
    permission_denials: list[Any] | None = field(default=None)
    # Read by `result_fields` all along, but originally not carried here, so
    # plan-03's `runs` columns for them stayed NULL. Added at the END with
    # defaults: `RunOutcome` is constructed by keyword in `build_outcome` and
    # by position in tests, so appending is the only safe direction.
    #
    # NOT surfaced on `RunResponse`. plan-03's global constraints forbid
    # changing the SSE wire format, and these are diagnostic detail a stored
    # row wants far more than a streaming caller does.
    duration_api_ms: int | None = None
    errors: Any | None = None
    api_error_status: int | None = None
