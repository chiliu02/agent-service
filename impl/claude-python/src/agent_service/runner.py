"""Drive one agent run and normalize its message stream.

One Run object per HTTP request: no state is shared between concurrent runs.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Protocol

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage, query

from agent_service.config import Settings
from agent_service.errors import RunTimeout
from agent_service.options import ResolvedLimits, build_options
from agent_spec.db.outcome import RunOutcome
from agent_spec.db.recorder import NULL_RECORDER, RunRecorder
from agent_spec.openapi.schemas import QueryRequest
from agent_service.serialization import normalize, result_fields

# ResultMessage.terminal_reason / subtype values that mean a guardrail stopped
# the run rather than the agent finishing. MEASURED, not guessed -- the budget
# markers were originally guessed as "max_budget"/"error_max_budget"/
# "budget_exceeded" and all three are wrong. `budget_exhausted` rests on a
# SINGLE live observation and is documented nowhere in the SDK, so a rename
# would silently regress budget stops to `limit_hit: null` -- indistinguishable
# from a clean finish. RECHECK ON ANY SDK UPGRADE.
# See CP-028
_LIMIT_MARKERS: dict[str, str] = {
    "max_turns": "turns",
    "error_max_turns": "turns",
    "budget_exhausted": "budget",
    "error_max_budget_usd": "budget",
}

# The measured terminal_reason for a turn stopped mid-stream (S2). Necessary but
# NOT sufficient evidence of a deliberate interrupt -- `sessions.py` pairs it
# with its own stamp before labelling a turn `interrupted`.
#
# Lives HERE, beside `RunOutcome` and `_LIMIT_MARKERS`, rather than in
# sessions.py where it was first written: `unattributed_abort` below is shared
# by both surfaces that build a `RunResponse`, and sessions.py already imports
# from this module (the reverse would be a cycle). Re-exported from sessions.py
# so the old import path still resolves.
ABORTED_TERMINAL_REASONS = frozenset({"aborted_streaming", "aborted_tools"})


def detect_limit(fields: dict[str, Any]) -> str | None:
    for key in ("terminal_reason", "subtype", "stop_reason"):
        value = fields.get(key)
        if isinstance(value, str) and value in _LIMIT_MARKERS:
            return _LIMIT_MARKERS[value]
    return None


def _usage_is_all_zero(usage: Any) -> bool:
    """True when `usage` is a real dict whose every token count is zero.

    `None` is NOT this. A missing `usage` means the SDK said nothing, which is
    already covered elsewhere; this is specifically the shape where the SDK
    filled the structure in and every number in it is zero.
    """
    if not isinstance(usage, dict):
        return False
    counts = [v for k, v in usage.items() if "token" in k.lower() and isinstance(v, (int, float))]
    return bool(counts) and all(v == 0 for v in counts)


def unpriced_turn(fields: dict[str, Any]) -> bool:
    """Did the SDK report a SUCCESSFUL turn it attributed nothing to?

    MEASURED (`spike/probe_gateway_cost.py`, case C2): a turn that completed
    normally -- `subtype: "success"`, a real answer returned -- reported
    `total_cost_usd: 0`, `usage` with every token count zero, and `model_usage`
    empty. The same prompt run directly (C1) reported $0.027395 and real counts,
    and with `ANTHROPIC_BASE_URL` merely pointed at the real host (C3) reported
    $0.005131 -- so the override is NOT the trigger and the cause remains
    unestablished.

    THE CAUSE DOES NOT MATTER HERE, and that is the point of detecting the shape
    rather than the configuration. A successful turn that consumed zero input
    tokens, produced zero output tokens and billed no model did not happen: the
    reply exists. So the numbers are missing, not zero, and `0.0` is the one
    answer that is certainly wrong.

    Deliberately NARROW -- every conjunct is required, so an ordinary turn can
    never be caught by it. Same principle as `unattributed_abort` above, which
    covers the aborted shape; this covers the successful one.
    """
    if fields.get("subtype") != "success" or fields.get("is_error"):
        return False
    if (fields.get("total_cost_usd") or 0) != 0:
        return False
    return _usage_is_all_zero(fields.get("usage")) and not fields.get("model_usage")


def build_outcome(fields: dict[str, Any], session_id: str | None) -> RunOutcome:
    """Build a RunOutcome from `result_fields(message)` plus the caller's
    idea of the session id.

    Shared by `Run.events()` (one-shot) and `AgentSession.send()` (a session
    turn) so the ~15-field construction cannot drift between the two -- the
    drift that forced `outcome_recorded` to be hand-carried in Plan 1.

    ONE value is not passed through verbatim: `total_cost_usd` becomes `None`
    when `unpriced_turn` recognises a successful turn the SDK attributed nothing
    to. Applied HERE, in the single place both surfaces build an outcome, so the
    stored row, the session's running total and every `RunResponse` agree. The
    zero is not preserved anywhere -- a caller cannot act on a number that is
    certainly wrong, and `usage` / `model_usage` still carry the empty shape for
    anyone diagnosing it.
    """
    if unpriced_turn(fields):
        fields = {**fields, "total_cost_usd": None}
    return RunOutcome(
        session_id=session_id,
        result=fields.get("result"),
        is_error=bool(fields.get("is_error")),
        subtype=fields.get("subtype"),
        stop_reason=fields.get("stop_reason"),
        terminal_reason=fields.get("terminal_reason"),
        limit_hit=detect_limit(fields),
        num_turns=fields.get("num_turns"),
        total_cost_usd=fields.get("total_cost_usd"),
        duration_ms=fields.get("duration_ms"),
        usage=fields.get("usage"),
        model_usage=fields.get("model_usage"),
        permission_denials=fields.get("permission_denials"),
        duration_api_ms=fields.get("duration_api_ms"),
        errors=fields.get("errors"),
        api_error_status=fields.get("api_error_status"),
    )


def unattributed_abort(outcome: RunOutcome, price: float | None) -> bool:
    """Is `price` a zero that means "unattributed" rather than "free"?

    ONE definition, used by BOTH surfaces that build a `RunResponse`: a session
    turn (`AgentSession._record_turn`, where `price` is the delta against the
    connection's running total) and a one-shot run (`Run.turn_cost_usd`, where
    the connection lasts exactly one run so `price` IS the cumulative figure).
    Shared for the same reason `OutcomeSource` is: `RunResponse.turn_cost_usd`
    documents one meaning for four routes, and two copies of this rule would
    drift the way `outcome_recorded` did in Plan 1.

    MEASURED (`spike/probe_interrupt_cost.py`): an aborted turn reports `usage`
    all-zero with `iterations: []`, leaves `model_usage` untouched, and does not
    move `total_cost_usd` -- while the CLI demonstrably ran inference. So a zero
    here is the SDK declining to attribute the work, not a free turn, and the
    caller must be told `null` ("nobody can say") rather than `0.0` ("free").

    EXACT `== 0.0` is correct, not sloppy: on the session path both operands come
    from the same JSON number decoded to the same float when the price does not
    move, so the difference is exactly `0.0` (and `-0.0 == 0.0` holds); on the
    one-shot path it is a single decoded value compared against zero. A tolerance
    would instead have to guess how small a real price can be, and the failure it
    would guard against -- a one-ULP drift reporting a nonsense micro-cost
    instead of `null` -- is strictly less wrong than the 0.0 this replaces.
    See CP-018
    """
    return price == 0.0 and outcome.terminal_reason in ABORTED_TERMINAL_REASONS


async def _as_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Wrap a plain prompt as the SDK's single-message streaming format.

    The SDK raises ValueError from a plain string prompt whenever
    `options.can_use_tool` is set (confirmed live). Nothing sets it by default
    any more, so this is not currently load-bearing -- it stays unconditional
    so the path is uniform, and the dict shape is exactly what the SDK builds
    internally for a string prompt, so behaviour is unchanged either way.
    IF THIS IS EVER REMOVED, first confirm nothing sets `can_use_tool`.
    See CP-030
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


class Run:
    """A single agent run. Iterate `events()` exactly once.

    `outcome` stays `None` if the message stream ends without ever producing a
    `ResultMessage` (CLI crash, early exit, client disconnect). Callers MUST
    handle that as distinct from a normal or limit-hit finish.
    """

    def __init__(
        self,
        prompt: str,
        options: ClaudeAgentOptions,
        limits: ResolvedLimits,
        include_raw: bool,
        recorder: RunRecorder | None = None,
    ) -> None:
        self._prompt = prompt
        self._options = options
        self._limits = limits
        self._include_raw = include_raw
        self._consumed = False
        self.session_id: str | None = None
        self.outcome: RunOutcome | None = None
        self._recorder = recorder or NULL_RECORDER
        # Minted here, not returned by the recorder, so a run has an identity
        # even with persistence off -- which is the default configuration.
        self.run_id = uuid.uuid4().hex

    @property
    def turn_cost_usd(self) -> float | None:
        """What this run cost.

        A property, not a stored field: a one-shot `query()` owns its
        connection for exactly one run, so the SDK's cumulative
        `total_cost_usd` IS this run's cost. They only differ on a SESSION,
        where the connection spans many turns (S6) -- see
        `AgentSession._record_turn`, which has to difference them.

        The one thing both surfaces DO share is `unattributed_abort`: an aborted
        run priced at 0.0 is the SDK declining to attribute real work, and
        `RunResponse.turn_cost_usd` promises `null` for that on every route it
        serves -- not just the two session routes. `/v1/query` cannot be
        interrupted (there is no endpoint) so this is not reachable by a caller
        today; it is here so the field's documented meaning is true everywhere
        rather than on half the routes.
        See CP-032
        """
        if self.outcome is None:
            return None
        price = self.outcome.total_cost_usd
        return None if unattributed_abort(self.outcome, price) else price

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self._consumed:
            raise RuntimeError("Run.events() may only be iterated once")
        self._consumed = True
        seq = 0
        timed_out = False
        # `sid=None`: a one-shot run is never registered, so it has no
        # service-side session id and gets no `sessions` row. See
        # `db.models.Session`.
        self._recorder.start_run(
            self.run_id, sid=None, session_id=None, prompt=self._prompt, at=time.time()
        )
        try:
            async with asyncio.timeout(self._limits.timeout_s):
                # `async for` does NOT close its iterator when the loop body
                # raises or is abandoned via GeneratorExit (PEP 533 was
                # deferred) -- the SDK's own _internal/client.py carries the
                # same warning. Without `aclosing`, a disconnected SSE consumer
                # leaves the `query()` generator AND THE CLAUDE CODE SUBPROCESS
                # IT OWNS to non-deterministic GC, burning the caller's budget
                # in the background.
                async with aclosing(
                    query(prompt=_as_stream(self._prompt), options=self._options)
                ) as stream:
                    async for message in stream:
                        seq += 1
                        if isinstance(message, SystemMessage) and self.session_id is None:
                            self.session_id = (message.data or {}).get("session_id")
                        if isinstance(message, ResultMessage):
                            fields = result_fields(message)
                            self.session_id = self.session_id or fields.get("session_id")
                            self.outcome = build_outcome(fields, self.session_id)
                        event = normalize(message, seq, self._include_raw)
                        # BEFORE the yield, not after. Same reasoning as
                        # `_send_impl`'s `_record_turn` placement: a consumer
                        # that never resumes this generator skips anything
                        # written after the yield, so the last event of every
                        # abandoned run would be the one lost -- and an
                        # abandoned run is exactly the case worth having a
                        # record of. Costs nothing to do first because the call
                        # is synchronous and non-blocking by specification.
                        #
                        # NOTE this inverts the "(a) response then (b) queue, in
                        # that order" wording in CP-114; the order
                        # there was stated for a design where the enqueue could
                        # block, which this seam forbids.
                        self._recorder.append_event(self.run_id, event)
                        yield event
        except TimeoutError as exc:
            timed_out = True
            raise RunTimeout(
                f"run exceeded {self._limits.timeout_s}s"
            ) from exc
        finally:
            # `finally`, so a run that crashed, timed out, or was abandoned
            # mid-stream is still recorded as ended. `outcome` stays None on
            # every one of those paths, which is the distinction `Run` already
            # documents callers must handle.
            self._recorder.finish_run(
                self.run_id,
                sid=None,
                session_id=self.session_id,
                outcome=self.outcome,
                turn_cost_usd=self.turn_cost_usd,
                # A one-shot run has no interrupt endpoint -- see
                # `turn_cost_usd`, which makes the same point about
                # `unattributed_abort` being unreachable here today.
                interrupted=False,
                timed_out=timed_out,
                at=time.time(),
            )


class RunFactory(Protocol):
    def __call__(self, req: QueryRequest, settings: Settings) -> Run: ...


def create_run(
    req: QueryRequest, settings: Settings, recorder: RunRecorder | None = None
) -> Run:
    # `recorder` is keyword-optional so this still satisfies `RunFactory`, which
    # api.py calls as `factory(request, config)`. Nothing passes it until
    # plan-03 Task 4 constructs a real recorder at startup.
    options, limits = build_options(req.options, settings)
    include_raw = (
        settings.include_raw_events if req.options.include_raw is None else req.options.include_raw
    )
    return Run(req.prompt, options, limits, include_raw, recorder)


def sdk_version() -> str:
    """Installed claude-agent-sdk version.

    Lives here rather than in api.py so that the boundary rule -- api.py never
    imports claude_agent_sdk -- holds without exception.
    """
    import claude_agent_sdk

    return getattr(claude_agent_sdk, "__version__", "unknown")


#: The distribution this build wraps, published as `Capabilities.sdk.name`.
#: A CONSTANT and not a lookup: it names the module imported directly above,
#: so deriving it at runtime would only add a way for the two to disagree.
#: A Codex or Gemini implementation is a different service with a different
#: value here -- see CP-141.
SDK_NAME = "claude-agent-sdk"


def sdk_name() -> str:
    """Which agent SDK this build wraps. See `SDK_NAME`."""
    return SDK_NAME


class OutcomeSource(Protocol):
    """What `_summary` needs to build a response.

    Both `Run` (one-shot) and `TurnResult` (a session turn) satisfy this, so
    the two endpoints share one summary builder instead of drifting apart --
    the drift that forced `outcome_recorded` to be hand-carried in Plan 1.
    """

    session_id: str | None
    outcome: "RunOutcome | None"
    # What the single run/turn cost, unlike `outcome.total_cost_usd`, whose
    # scope depends on the endpoint. On the protocol so `_summary` can report
    # it without knowing which surface it is summarising.
    turn_cost_usd: float | None
