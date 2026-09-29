"""FastAPI application.

This module must NEVER import claude_agent_sdk. Everything agent-related comes
through `runner.create_run`, which is injectable so tests never make API calls.

It must also NEVER gain `from __future__ import annotations`: PEP 563
stringifies the `Annotated` aliases defined inside `create_app`, which gives a
422 on every route and a PydanticUserError from /openapi.json.
See CP-034
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated, Any, get_args

from fastapi import Body, Depends, FastAPI
from fastapi import Path as PathParam
from fastapi import Query as FastQuery
from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from agent_service.config import (
    ALWAYS_DISALLOWED_TOOLS,
    CREDENTIAL_ENV_VARS,
    PROVIDER_SELECTOR_ENV_VARS,
    Settings,
    credentials_configured,
    get_settings,
    verify_auth,
    verify_credentials,
    verify_mounts,
)
from agent_service.auth import install_auth
from agent_service.options import check_permission_mode, session_modes
from agent_service.errors import (
    UNCLASSIFIED_TITLE,
    PersistenceDisabled,
    RunNotFound,
    to_problem,
)
from agent_spec.db.recorder import NULL_RECORDER, RunRecorder
from agent_service.registry import SessionNotFound, SessionRegistry
from agent_service.runner import (
    OutcomeSource,
    Run,
    RunFactory,
    create_run,
    sdk_name,
    sdk_version,
)
from agent_spec.openapi.examples import attach_capabilities_example
from agent_spec.openapi.preboot import attach_preboot

from agent_service.spec import specification
from fastapi.exceptions import RequestValidationError
from agent_spec.openapi.ordering import enforce_canonical_order
from agent_spec.openapi.validation import (
    PROBLEM_MEDIA_TYPE,
    declare_validation_problem,
    validation_problem,
)
from agent_spec.openapi.stop_kind import derive_stop_kind
from agent_spec.openapi.run_options_schema import (
    effective_run_options_schema,
)
from agent_spec.openapi.schemas import (
    RunOptions,
    AgentEvent,
    Deployment,
    ContextUsage,
    EffortLevel,
    Health,
    Impl,
    InterruptResult,
    PermissionMode,
    Problem,
    QueryRequest,
    RunResponse,
    Sdk,
    SessionCreate,
    SessionList,
    SessionRecord,
    SessionUpdate,
    SettingSource,
    Spec,
    StoredRun,
    TokenUsage,
    TranscriptPage,
    TurnRecord,
    TurnRequest,
)
from agent_service.versions import (
    DOCUMENT_VERSION,
    IMPLEMENTATION_NAME,
    IMPLEMENTATION_VERSION,
)

_log = logging.getLogger(__name__)

PERMISSION_MODES = list(get_args(PermissionMode))
EFFORT_LEVELS = list(get_args(EffortLevel))
SETTING_SOURCES = list(get_args(SettingSource))

# The SDK's conversation id, repeated as a RESPONSE HEADER on the two turn
# endpoints. Body-only was costing a relay an SSE body scanner with a
# chunk-boundary carry buffer, on the hot path of every conversation, to recover
# one string it needs to join its own records to the model traffic the container
# produces (CP-134, request 2). A header is
# the same information where a relay already looks.
#
# `x-sdk-session-id`, matching the `sdk_session_id` FIELD, never a bare
# `x-session-id`: `SessionRecord.session_id` is a different identifier and
# feeding this value back into `/v1/sessions/{}` is a 404 (measured). One name
# per identifier, on every surface.
#
# PRESENT WHEN KNOWN, and a caller must tolerate its absence. The value is
# captured from the turn's init message (sessions.py), so it is unavailable
# only on the first turn of a session that dies before producing one -- from the
# second turn onward it is cached on the session and always sent. It is NOT on
# `/v1/query/stream`, which commits its 200 before the first message arrives and
# therefore cannot carry it; `/v1/sessions/{sid}/messages/stream` can, because
# it already pulls the first message before committing the response.
SDK_SESSION_HEADER = "x-sdk-session-id"

# Declared in the OpenAPI document, not merely sent. A caller who reads the
# schema is meant to find both the header and the one caveat that matters --
# that it can be absent -- without having to observe a response first.
_SDK_SESSION_HEADER_SPEC = {
    SDK_SESSION_HEADER: {
        "description": (
            "The SDK's own conversation id for this turn -- the same value as "
            "`sdk_session_id` in the body, and the id the CLI sends as "
            "`x-claude-code-session-id` when it calls the model API. It is NOT "
            "a `/v1/sessions/{session_id}` path handle.\n\n"
            "**Present on a session's first turn too, streaming included.** "
            "Absent only when no id was ever seen -- a turn that produced no "
            "message at all. Treat it as optional."
        ),
        "schema": {"type": "string"},
    }
}


def _token_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """The SDK's `usage` mapped to the specification's named counts (0.19.0).

    **Four of the five, and the fifth is `null` for a measured reason.** This SDK
    reports `cache_creation_input_tokens` and `cache_read_input_tokens` -- both
    halves of the cache pair -- and does not separate reasoning tokens from
    `output_tokens`. So `reasoning_output_tokens` is `null` here, which means *not
    reported*, not *none were generated*. The Codex build is the mirror image: it
    has reasoning tokens and no cache-write counter.

    **`None` in, all-null out.** An absent `usage` means the SDK reported nothing,
    which is exactly what a `TokenUsage` of nulls says -- so the object is still
    present, and a consumer never has to tell "no counts" from "no object".

    **`.get`, not `[...]`.** These keys come from the SDK verbatim; a rename
    upstream must degrade to `null` rather than raise inside a response builder
    that also serves the streaming routes.
    """
    if not usage:
        return TokenUsage()

    def _int(key: str) -> int | None:
        value = usage.get(key)
        return value if isinstance(value, int) else None

    return TokenUsage(
        input_tokens=_int("input_tokens"),
        output_tokens=_int("output_tokens"),
        cache_read_tokens=_int("cache_read_input_tokens"),
        cache_write_tokens=_int("cache_creation_input_tokens"),
        # Not separated by this SDK. `null` is the honest answer.
        reasoning_output_tokens=None,
    )


def _summary(
    source: OutcomeSource, events: list[AgentEvent], interrupted: bool = False
) -> RunResponse:
    """Build the response from anything carrying `session_id` and `outcome`.

    Both `Run` (one-shot) and `TurnResult` (a session turn) satisfy
    `OutcomeSource`, so the two surfaces cannot drift -- which is exactly what
    forced `outcome_recorded` to be hand-carried between endpoints in Plan 1.
    See CP-035
    """
    outcome = source.outcome
    return RunResponse(
        session_id=source.session_id,
        # The SAME value under a name that says which id it is. Additive, never
        # a rename. Filled from one attribute so the two cannot drift apart.
        sdk_session_id=source.session_id,
        outcome_recorded=outcome is not None,
        result=outcome.result if outcome else None,
        is_error=bool(outcome.is_error) if outcome else False,
        interrupted=interrupted,
        # 0.19.0, and the same shape as `token_usage` beside `usage`: the
        # closed word a client branches on, with the SDK's three verbatim
        # strings still below it. Derived in `agent_spec` rather than here so
        # both builds cannot answer differently -- this passes facts, not a
        # decision. CP-142
        stop_kind=derive_stop_kind(
            outcome_recorded=outcome is not None,
            is_error=bool(outcome.is_error) if outcome else False,
            interrupted=interrupted,
            limit_hit=outcome.limit_hit if outcome else None,
            raw=(outcome.stop_reason or outcome.subtype) if outcome else None,
        ),
        subtype=outcome.subtype if outcome else None,
        stop_reason=outcome.stop_reason if outcome else None,
        terminal_reason=outcome.terminal_reason if outcome else None,
        limit_hit=outcome.limit_hit if outcome else None,
        num_turns=outcome.num_turns if outcome else None,
        total_cost_usd=outcome.total_cost_usd if outcome else None,
        duration_ms=outcome.duration_ms if outcome else None,
        usage=outcome.usage if outcome else None,
        # 0.19.0. The specification's own spelling beside the pass-through, so a
        # consumer reads one shape whichever build answered.
        token_usage=_token_usage(outcome.usage if outcome else None),
        model_usage=outcome.model_usage if outcome else None,
        permission_denials=outcome.permission_denials if outcome else None,
        # Off the SAME protocol as everything else rather than passed in per
        # route -- hand-carrying is what made `outcome_recorded` drift.
        turn_cost_usd=source.turn_cost_usd,
        events=events,
    )


def _turn_record(turn) -> TurnRecord | None:  # noqa: ANN001
    """Render `AgentSession.last_turn` for `SessionRecord`.

    None in, None out -- a session that has never taken a turn reports
    `last_turn: null`.

    Reads the very same `TurnResult` that `_summary` reads, so the two surfaces
    cannot disagree about a turn. Pinned over HTTP anyway by
    tests/test_api_sessions.py::test_the_record_and_the_turn_response_agree_
    about_the_same_turn -- "they read the same attribute" is the kind of claim
    this project has had disproved by execution before.
    """
    if turn is None:
        return None
    outcome = turn.outcome
    return TurnRecord(
        sdk_session_id=turn.session_id,
        outcome_recorded=outcome is not None,
        interrupted=bool(turn.interrupted),
        timed_out=bool(turn.timed_out),
        is_error=bool(outcome.is_error) if outcome else False,
        # A stored turn knows one thing the live response does not -- that it
        # timed out -- so this is the surface where `stop_kind` is most worth
        # having: the 504 that said so is long gone by the time anyone reads a
        # record. CP-142
        stop_kind=derive_stop_kind(
            outcome_recorded=outcome is not None,
            is_error=bool(outcome.is_error) if outcome else False,
            interrupted=bool(turn.interrupted),
            timed_out=bool(turn.timed_out),
            limit_hit=outcome.limit_hit if outcome else None,
            raw=(outcome.stop_reason or outcome.subtype) if outcome else None,
        ),
        subtype=outcome.subtype if outcome else None,
        stop_reason=outcome.stop_reason if outcome else None,
        terminal_reason=outcome.terminal_reason if outcome else None,
        limit_hit=outcome.limit_hit if outcome else None,
        num_turns=outcome.num_turns if outcome else None,
        duration_ms=outcome.duration_ms if outcome else None,
        turn_cost_usd=turn.turn_cost_usd,
    )


def _record(
    sid: str,
    session,  # noqa: ANN001
    usage: dict | None = None,
    agent_id: str | None = None,
) -> SessionRecord:
    return SessionRecord(
        session_id=sid,
        # A PROCESS CONSTANT, threaded from `Settings` at each call site
        # rather than read off `session`. Nothing per-session carries it and
        # nothing should: a value stored on the session could be written by
        # whatever created the session, which is exactly the assertion this
        # field must not be. Provenance comes from the environment or not at
        # all.
        agent_id=agent_id,
        # Known at creation only when the caller supplied it; otherwise null
        # until the first turn's init message, because the CLI does not mint an
        # id before then (X1). Read off the session, which is the same attribute
        # every turn reports, so the record and the turn cannot disagree.
        sdk_session_id=getattr(session, "session_id", None),
        title=session.title,
        status=session.status,
        created_at=session.created_at,
        last_used_at=session.last_used_at,
        turns=session.turns,
        total_cost_usd=session.total_cost_usd,
        # The two options PATCH can write, and ONLY those -- see
        # `AgentSession.__init__` for why the rest is not echoed.
        model=session.model,
        permission_mode=session.permission_mode,
        last_residue_discarded=session.last_residue_discarded,
        # On EVERY route that builds a record, not just GET: PATCH answers with
        # a SessionRecord too, and a record whose contents depended on which
        # verb produced it would be a second `outcome_recorded`.
        last_turn=_turn_record(session.last_turn),
        context_usage=ContextUsage(**usage) if usage else None,
    )


def _sse(name: str, payload: dict) -> str:
    """One Server-Sent Event frame: `event:` name plus a single `data:` line.

    Shared by both streaming routes -- they were each carrying a verbatim copy
    of this, which is exactly how two wire formats drift apart.
    """
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Statuses a CLASSIFIED failure is worth a WARNING for. NOT "anything >= 500":
# that would sweep in 504, which is a time budget this service set expiring --
# see `_problem`. Spelled as a set so the exclusion is a decision on the page
# rather than an accident of a comparison operator.
_WARN_STATUSES = frozenset({500, 502})


def _problem(exc: BaseException, route: str, sid: str | None = None) -> Problem:
    """Turn `exc` into its problem document AND leave a log record behind it.

    WHY THIS EXISTS. Every `except Exception` in this module used to answer
    with `to_problem(exc)` and log NOTHING. An exception `to_problem` cannot
    classify therefore became a 500 with no traceback, no ERROR line, no
    record of any kind: the acceptance run hit exactly that -- a transient 500
    from `GET /v1/sessions/{sid}` whose retry succeeded -- and `docker compose
    logs` had not one line about it. The symptom was reportable; the cause was
    not recoverable at all. In a service whose stated purpose is making the
    agent loop observable, that is the hole.

    WHERE THE LINE IS DRAWN, and why:

    * UNCLASSIFIED (`errors.UNCLASSIFIED_TITLE`, `to_problem`'s fallthrough)
      -- ERROR, WITH `exc_info`. This branch means "we do not know what this
      is": the type is not in errors.py's table, so the traceback is the ONLY
      thing that can identify it. This is the case the defect was.
    * CLASSIFIED FAULT, `_WARN_STATUSES` (502 from a dead or garbled agent
      process, 500 from a missing CLI binary) -- WARNING, no traceback. The
      service or its subprocess is genuinely at fault and an operator wants to
      see it, but errors.py already NAMED the condition, so a traceback adds
      volume and not information. WARNING keeps ERROR meaning "unidentified".
    * EVERY 4xx (404 unknown session, 409 busy/closed, 429 at the cap, 400 bad
      options) -- NOT LOGGED. These are ordinary API answers, decided by what
      the client asked for, and they are already visible in the access log
      with their status. Logging them at ERROR would put a fault-level line on
      the single most common thing a polling client does, and an operator who
      learns to scroll past ERROR is worse off than one with no log at all.
    * 504 -- NOT LOGGED, on that same side, and this is the one placement
      worth arguing. `RunTimeout`, `SessionOpenTimeout` and `InterruptTimeout`
      all mean a budget THIS SERVICE SET expired. That is the budget working
      as configured, it is fully described by the problem document the client
      already has, and on a service where turn budgets are deliberately short
      it is the failure a client provokes most often. Nothing here is
      unexplained, so nothing here is a fault.

    WHAT IS LOGGED. The route, the session id where the route has one, and the
    exception CLASS NAME -- never `str(exc)`, never the prompt, never options,
    never anything from the request body. The traceback on the ERROR branch
    carries the exception's own message (that is the point of it) but no local
    variables: `logging.Formatter.formatException` is `traceback` output, not
    a frame dump. Pinned by tests/test_api_logging.py.
    """
    problem = to_problem(exc)
    where = f"{route} session={sid}" if sid is not None else route
    if problem.title == UNCLASSIFIED_TITLE:
        _log.error(
            "%s: unclassified failure (%s) -- answering %d; "
            "this exception type is not in errors.to_problem's table",
            where,
            type(exc).__name__,
            problem.status,
            exc_info=exc,
        )
    elif problem.status in _WARN_STATUSES:
        _log.warning("%s: %s (%s) -- answering %d", where, problem.title,
                     type(exc).__name__, problem.status)
    return problem


def _problem_response(exc: BaseException, route: str, sid: str | None = None) -> JSONResponse:
    problem = _problem(exc, route, sid)
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(),
        media_type="application/problem+json",
    )


def create_app(
    settings: Settings | None = None,
    run_factory: RunFactory | None = None,
    registry: SessionRegistry | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    # IMPORTED LAZILY, and only when a URL is configured. With persistence off
    # this branch is never taken, `agent_service.db` never enters sys.modules,
    # and SQLAlchemy is never imported -- pinned by
    # test_no_database_url_imports_no_database_code.
    persistence = None
    recorder: RunRecorder = NULL_RECORDER
    if resolved_settings.database_url:
        from agent_spec.db.wiring import Persistence

        # A.2 is injected because it is the one SDK-shaped part of persistence:
        # `PostgresSessionStore` satisfies the Claude SDK's `SessionStore`
        # protocol so the CLI can resume from it. A build whose SDK has no such
        # seam passes nothing and loses only that mirror.
        from agent_service.db.session_store import PostgresSessionStore

        persistence = Persistence(
            resolved_settings.database_url,
            resolved_settings.agent_id,
            session_store_factory=PostgresSessionStore,
        )
        recorder = persistence.recorder

    resolved_factory: RunFactory = run_factory or partial(create_run, recorder=recorder)
    resolved_registry = registry or SessionRegistry(
        resolved_settings,
        recorder=recorder,
        session_store=persistence.session_store if persistence else None,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # BEFORE start_reaper(), and OUTSIDE the `try`. Raising here aborts
        # startup, which uvicorn turns into `sys.exit(STARTUP_FAILURE)`, so a
        # container restarts rather than serving requests it cannot fulfil.
        # Outside the `try` because nothing has started yet, so the `finally`
        # would only add noise to the one message an operator needs to read.
        # See CP-036
        verify_credentials(app.state.settings)
        # Beside verify_credentials and for the same reasons: boot-only, raises
        # to abort startup, outside the `try`. AFTER the credential check
        # because a missing key is the more common mistake and should be the
        # first thing an operator is told.
        verify_mounts(app.state.settings)
        # Third, and last of the pure-settings gates. After the other two
        # because a missing credential or mount is the more common mistake
        # and should be the first thing an operator is told.
        verify_auth(app.state.settings)
        if not app.state.settings.auth_token:
            # ONCE, at boot, at WARNING. The posture is also published on
            # /healthz and /v1/capabilities, but a log line is what an
            # operator reads when a container comes up and it is the only
            # channel that reaches somebody who never calls the API.
            _log.warning(
                "no AGENT_SERVICE_AUTH_TOKEN is set: /v1 is served to "
                "anyone who can reach this port, and the agent has Bash. "
                "Intended for a loopback single-operator deployment; see "
                "docs/security-posture.md before exposing it further."
            )
        # After verify_credentials, so a service that is about to exit 3 does
        # not spawn a drain task first; before the reaper, so nothing can
        # produce rows before there is anything draining them.
        if app.state.persistence is not None:
            # THE SCHEMA-REVISION GATE, and it runs BEFORE start(): a container
            # that is about to refuse must not have opened a drain task, and a
            # single wrong-schema write is exactly what the gate exists to
            # prevent. Raising here aborts startup the same way the other two
            # gates do -- exit 3, one message.
            #
            # Boot-only, always. A database that breaks or recovers while the
            # service is running is still reported through `/healthz`
            # (`database_usable`) and still takes nothing down. Refuse at boot
            # what should never have started; report at runtime what may
            # recover. See db/revision.py.
            await app.state.persistence.verify_revision()
            app.state.persistence.start()
        app.state.registry.start_reaper()
        try:
            yield
        finally:
            await app.state.registry.stop_reaper()
            await app.state.registry.close_all()
            # LAST, and after close_all(). Closing the sessions is what
            # produces the final `session_closed` rows, so draining before it
            # would record every session as still open. Bounded by its own
            # timeout -- see `wiring.DRAIN_TIMEOUT_S`.
            if app.state.persistence is not None:
                await app.state.persistence.aclose()

    app = FastAPI(
        title="Agent Service",
        # THE DOCUMENT'S VERSION, NOT THIS BUILD'S -- changed in 0.12.0 by
        # Plan 8 step 5. Until 0.11.0 this had to match `pyproject.toml`, which
        # was correct while one implementation was the only one there could be.
        # It now carries what `spec/VERSION` says, so a second
        # implementation in another language serves the SAME document while
        # being an obviously different build; this build's own version is in
        # `/v1/capabilities` under `implementation`. See
        # `agent_service/versions.py`.
        version=DOCUMENT_VERSION,
        lifespan=lifespan,
        summary="HTTP access to the Claude Agent SDK.",
        description=(
            "Runs the Claude Agent SDK behind an OpenAPI interface. Every SDK "
            "message is returned normalized so the agent loop is observable."
        ),
    )

    # Installed here rather than as a route dependency: a Depends() must be
    # remembered on every route, and forgetting one produces an
    # unauthenticated endpoint that looks exactly like its neighbours. This
    # matches on the `/v1` prefix, so a route added later is covered by
    # having been added at all. No-op when no token is configured -- the
    # middleware is not installed, so the documented single-operator
    # deployment keeps the exact code path it always had.
    install_auth(app, resolved_settings.auth_token)
    app.state.settings = resolved_settings
    app.state.run_factory = resolved_factory
    app.state.registry = resolved_registry
    app.state.persistence = persistence

    def get_current_settings() -> Settings:
        return app.state.settings

    def get_run_factory() -> RunFactory:
        return app.state.run_factory

    def get_registry() -> SessionRegistry:
        return app.state.registry

    SettingsDep = Annotated[Settings, Depends(get_current_settings)]
    FactoryDep = Annotated[RunFactory, Depends(get_run_factory)]
    RegistryDep = Annotated[SessionRegistry, Depends(get_registry)]

    @app.get("/healthz", response_model=Health, tags=["meta"])
    async def healthz(config: SettingsDep) -> Health:
        """Live report, never a gate. See `Health`'s field descriptions.

        `status` stays `"ok"` while `database_usable` is `false`, and that is a
        decision rather than an oversight. The container healthcheck is
        `curl -fsS /healthz`, so it reads the status CODE: making a broken
        database non-200 would have compose restart a service whose agent side
        is working, repeatedly, for as long as the database is down. Persistence
        is optional by construction -- `RunRecorder` may never raise, the writer
        discards rather than failing turns -- and the health of an optional
        subsystem must not be able to take down the required one.

        The probe is bounded (`HEALTH_PROBE_TIMEOUT_S`) for the same reason: a
        database that hangs rather than refusing would otherwise hang this route
        past the healthcheck's own 5s timeout and produce the restart loop
        anyway, by a slower route.
        """
        persistence = app.state.persistence
        return Health(
            status="ok",
            credentials_configured=credentials_configured(),
            auth_required=bool(config.auth_token),
            workspace_dir=str(config.workspace_dir),
            database_configured=persistence is not None,
            database_usable=(
                await persistence.usable() if persistence is not None else None
            ),
        )

    def _capabilities_payload(config) -> Deployment:
        """The payload, so the route and the published example share one source.

        Extracted so the document can carry this build's REAL answer as its
        `/v1/capabilities` example. Two copies would drift, and the example is
        the copy nobody would notice going stale.
        """
        return Deployment.from_flat(
            # The join, added in 0.12.0: what this build promises, and what it
            # is. `info.version` in the OpenAPI document answers only the
            # first of those now, which is why the second is here.
            spec=Spec(document_version=DOCUMENT_VERSION),
            impl=Impl(name=IMPLEMENTATION_NAME, version=IMPLEMENTATION_VERSION),
            # Both, on purpose. `sdk_version` is deprecated in 0.7.0 and
            # still emitted -- it is in four published documents, and
            # AS-23 treats removing a field as the breaking kind of change.
            # One source, read once, so the two cannot disagree.
            #
            # THIS IS NOW THE MINORITY PRECEDENT, and the contrast is worth
            # keeping visible. 0.14.0 renamed `specification` to `spec` above and
            # did NOT keep the old name: it removed a required field outright,
            # which is the AS-23 change this comment describes avoiding. That
            # was a deliberate call taken with notice, not a change of policy
            # -- `sdk_version` still stands here precisely because deprecating
            # in place is the cheaper option whenever it is available.
            sdk=Sdk(name=sdk_name(), version=sdk_version()),
            sdk_version=sdk_version(),
            # Declared by this build rather than taken from a shared
            # union. See CP-143
            permission_modes=session_modes(),
            effort_levels=EFFORT_LEVELS,
            setting_sources=SETTING_SOURCES,
            default_model=config.default_model,
            default_allowed_tools=list(config.default_allowed_tools),
            always_disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
            # **Two maps since 2026-09-03**, and this build is why the split
            # was needed: the comment below used to apologise for one figure
            # sitting among six that mean something else.
            accepts_limits={
                "default_max_turns": float(config.default_max_turns),
                "max_allowed_turns": float(config.max_allowed_turns),
                "default_max_budget_usd": config.default_max_budget_usd,
                "max_allowed_budget_usd": config.max_allowed_budget_usd,
                "default_request_timeout_s": float(config.default_request_timeout_s),
                "max_allowed_timeout_s": float(config.max_allowed_timeout_s),
            },
            behaviour_limits={
                # 0.19.0, and it was asked for by a consumer that needed to know
                # how long an unmatched session record survives before the
                # reaper takes it -- a lost `201` is reconciled by listing
                # sessions, and a reconciliation window longer than this looks
                # for a record that has been closed and forgotten.
                #
                # **It bounds how long the service KEEPS something**, which is
                # why it is here and not above: every figure in `accepts.limits`
                # bounds a request instead.
                "session_idle_ttl_s": float(config.session_idle_ttl_s),
            },
            # **"cumulative", and it is the trap this field exists for**
            # (CP-003): `model_usage` accumulates over the CONNECTION here while
            # `usage` is per turn, so summing it across a session multiplies the
            # real figure by roughly the turn count. Note what this does NOT
            # cover -- `turn_cost_usd` is already differenced by this service
            # (CP-032), so one response carries per-turn money beside cumulative
            # tokens. The Gemini build reports "per_turn" and the Codex build
            # reports no such figure at all.
            model_usage_scope="cumulative",
            # TRUE, and the only build of the three for which it is: the SDK
            # prices a turn. `turn_cost_usd` is still null for an aborted turn,
            # which is why the fields stay nullable -- this says the build CAN
            # price, not that every turn is priced (CP-062).
            reports_cost_usd=True,
            workspace_dir=str(config.workspace_dir),
            reference_dirs=[str(p) for p in config.reference_dirs],
            permission_enforcement=config.permission_enforcement,
            # THE LISTS THE BOOT GATE ITSELF CONSULTS, exported rather than
            # restated -- `credentials_configured()` reads these same two
            # constants, so what is published here cannot drift from what is
            # checked. Kept apart because a selector is not a credential; see
            # config.py and the field descriptions.
            credential_sources=list(CREDENTIAL_ENV_VARS),
            provider_selectors=list(PROVIDER_SELECTOR_ENV_VARS),
            max_sessions=config.max_sessions,
            require_credentials=config.require_credentials,
            auth_required=bool(config.auth_token),
            allow_mcp_servers=config.allow_mcp_servers,
            # TRUE: the Claude CLI takes `--session-id`, so a caller-supplied id
            # is adopted and returned on the 201 before any model call (AS-13).
            # **"conversation", and the caveat is in the shared description.**
            # The SDK's id is stable across ordinary turns here -- a client may
            # key on it -- though it can move under an explicit fork or resume.
            # The Gemini build reports "turn" and means something else entirely.
            sdk_session_id_scope="conversation",
            # **MEASURED ON THE WIRE, not read from anyone's documentation**
            # (CP-003, X4): through a local proxy standing in for the model
            # endpoint, the CLI sent this header on four consecutive
            # `POST /v1/messages` calls carrying the same id it reports on
            # `init` and `result`, byte for byte. That equality is the whole
            # reason a gateway can attribute model spend to a session, and it is
            # why this build can publish a header name rather than a guess.
            llm_correlation={
                "header": "x-claude-code-session-id",
                "measured": True,
            },
            allow_supplied_sdk_session_id=True,
            # AS-32 (0.19.0). Both FALSE here, and both are facts about this
            # SDK rather than choices:
            #
            # The conversation id arrives with the first turn's init message, so
            # by the time a one-shot response could carry a header the response
            # is already committed -- `sdk_session_id` is in the body instead.
            query_reports_sdk_session_id=False,
            # `/v1/query` runs the SDK directly rather than through the session
            # registry, so it neither reserves nor competes for `max_sessions`,
            # and no 429 is reachable on that route.
            query_consumes_a_session_slot=False,
            # **Empty unless an operator turns MCP off**, and that is the whole
            # list on this build: the Claude Agent SDK covers every `RunOptions`
            # field, so the only thing that can be refused here is a thing a
            # deployment chose to forbid.
            #
            # Computed from `allow_mcp_servers` rather than written beside it, so
            # the published list and `options.py`'s `McpServersNotAllowedError`
            # cannot disagree -- the drift AS-32 exists to prevent is exactly a
            # capability that says one thing while the code does another.
            unsupported_options=(
                [] if config.allow_mcp_servers else [{"field": "mcp_servers"}]
            ),
            # **All three transports and any header**, which is what the Claude
            # Agent SDK's own `McpServerConfig` union carries. Published rather
            # than assumed because the Codex build has two transports and one
            # header, and a client sending an `sse` server must learn that from
            # a value rather than from a 400.
            # **BOTH TRUE, and that is the warning rather than the boast.**
            # This build's `Bash` is unconfined -- the container and its mount
            # split are the only boundary, which the README says in its opening
            # paragraph. Nothing inside the container stops a command reaching
            # the network or writing outside the workspace.
            #
            # The Codex build reports `network_access: false` because its agent
            # runs under bubblewrap. Publishing the pair is what lets a client
            # tell them apart instead of discovering it from an Agent that works
            # on one image and not the other.
            sandbox={"network_access": True, "confines_writes_to_workspace": False},
            # `server_name_pattern` is NULL, and that is a statement about this
            # service rather than about the SDK: nothing here refuses a server
            # name. The Gemini build publishes a pattern because its agent
            # cannot address a name containing an underscore at all.
            mcp={
                "transports": ["stdio", "sse", "http"],
                "http_headers": "any",
                "server_name_pattern": None,
            },
            # All four read out of the bundled CLI rather than stopwatched
            # (CP-149). The 60 s is on the POST alone, the idle figure is the
            # `sse`/`http` one because `stdio` is the more generous of the two
            # and the published value never is, and the hard cap is 1e8
            # milliseconds to the second. **They are BEHAVIOUR**: a timer to
            # design a server around, not a shape a caller may express.
            mcp_tool_call={
                "request_timeout_s": 60,
                "idle_timeout_s": 300,
                "total_timeout_s": 100000,
                "progress_resets_idle": True,
            },
            strict_mcp_config=config.default_strict_mcp_config,
            require_mounts=config.require_mounts,
        )


    @app.get(
        "/v1/schemas/run-options",
        tags=["meta"],
        summary="Run options schema",
        description=(
            "**`deployment.accepts`, rendered as JSON Schema 2020-12** -- the "
            "published `RunOptions` narrowed by what THIS deployment accepts, so "
            "a client can validate a request instead of branching on a "
            "capability payload.\n\n"
            "One fact in two shapes, and a conformance clause asserts they "
            "agree. It is deployment-specific by nature: two containers of one "
            "image answer differently, which is why it is served rather than "
            "frozen into a document.\n\n"
            "Self-contained -- every `$ref` resolves inside `$defs`, so a "
            "validator needs no network."
        ),
        response_class=JSONResponse,
        responses={200: {"content": {"application/schema+json": {}}}},
    )
    async def run_options_schema(config: SettingsDep) -> JSONResponse:
        return JSONResponse(
            effective_run_options_schema(
                RunOptions.model_json_schema(),
                _capabilities_payload(config).accepts.model_dump(),
                impl=IMPLEMENTATION_NAME,
            ),
            media_type="application/schema+json",
        )

    @app.get("/v1/deployment", response_model=Deployment, tags=["meta"])
    async def deployment(config: SettingsDep) -> Deployment:
        return _capabilities_payload(config)

    @app.post(
        "/v1/query",
        response_model=RunResponse,
        tags=["query"],
        summary="Run the agent to completion and return the full message stream",
        responses={
            400: {"model": Problem, "description": "Invalid options or a limit above its cap"},
            502: {"model": Problem, "description": "The agent process failed"},
            504: {"model": Problem, "description": "The run exceeded its time budget"},
        },
    )
    async def run_query(
        config: SettingsDep,
        factory: FactoryDep,
        request: Annotated[QueryRequest, Body()],
    ) -> RunResponse | JSONResponse:
        try:
            run = factory(request, config)
            events = [AgentEvent(**event) async for event in run.events()]
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _problem_response(exc, "POST /v1/query")

        return _summary(run, events)

    @app.post(
        "/v1/query/stream",
        tags=["query"],
        summary="Run the agent, streaming each SDK message as it arrives",
        description=(
            "Server-Sent Events. Each `data:` line is one `AgentEvent` and the "
            "`event:` name is its type (system, assistant, user, result, "
            "stream_event, rate_limit). A terminal `event: done` carries the "
            "`RunResponse` summary with an empty `events` list, since the events "
            "were already streamed. A failure mid-stream arrives as `event: error` "
            "carrying a `Problem` document."
        ),
        response_class=StreamingResponse,
        responses={
            200: {"content": {"text/event-stream": {}}},
            400: {"model": Problem, "description": "Invalid options or a limit above its cap"},
        },
    )
    async def run_query_stream(
        config: SettingsDep,
        factory: FactoryDep,
        request: Annotated[QueryRequest, Body()],
    ):
        # NO return type annotation: FastAPI would infer a response_model from
        # it, and `StreamingResponse | JSONResponse` is not a valid Pydantic
        # field type -- annotating it breaks route registration entirely, at
        # app-creation time rather than request time.
        try:
            # Building options is pure request validation and happens here,
            # synchronously, BEFORE the response is committed -- so it can
            # still become a real status code. Once run.events() is being
            # iterated the 200 and SSE headers are on the wire, and everything
            # after that stays in-band as `event: error`.
            run = factory(request, config)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _problem_response(exc, "POST /v1/query/stream")

        stream = run.events()

        async def close_stream() -> None:
            # This wrapper is LOAD-BEARING, not decoration. A bound `.aclose`
            # is a builtin method, so Starlette's `is_async_callable()` returns
            # False, dispatches it to a threadpool, and the coroutine is
            # created and discarded WITHOUT EVER BEING AWAITED -- leaving the
            # generator to asyncgen-GC, the exact non-determinism this exists
            # to remove.
            # See CP-037
            await stream.aclose()

        async def generate() -> AsyncIterator[str]:
            try:
                async for event in stream:
                    yield _sse(event.get("type", "unknown"), event)
            except Exception as exc:  # noqa: BLE001 - reported in-band
                # Logged on the SAME terms as a status-code failure: an
                # unclassified one is no more diagnosable for having been
                # delivered in-band, and the client's SSE body is not the
                # operator's log.
                yield _sse(
                    "error", _problem(exc, "POST /v1/query/stream").model_dump()
                )
                return

            summary = _summary(run, [])
            yield _sse("done", summary.model_dump())

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            # Starlette NEVER calls aclose() on `generate()` when the client
            # disconnects while it is suspended at a yield: the cancellation
            # lands in Starlette's own `send()`, outside both generators'
            # frames, so neither unwinds through a `finally`. Left alone,
            # `stream` -- and the Claude Code subprocess it owns -- is
            # reclaimed only by the cyclic GC. This task runs unconditionally
            # once the response is done, disconnect path included. Inert on
            # normal completion (aclose() on an exhausted generator is a no-op).
            background=BackgroundTask(close_stream),
        )

    @app.post(
        "/v1/sessions",
        response_model=SessionRecord,
        status_code=201,
        tags=["sessions"],
        summary="Open a multi-turn session",
        description=(
            "Returns the registry handle as `session_id`.\n\n"
            "**`sdk_session_id` on the response is populated at creation only "
            "when you supply `session_id` in the request.** Otherwise it is null "
            "until the first turn: the CLI does not mint its conversation id "
            "before then (measured). Supply one when you need the mapping to "
            "exist before the session makes its first model call."
        ),
        responses={
            # Reachable: `registry.create()` calls `build_options()`, so a bad
            # `options` payload raises before any subprocess starts (confirmed
            # by driving both requests).
            400: {
                "model": Problem,
                "description": (
                    "Invalid options, a limit above its cap, or a `session_id` "
                    "that is not a UUID or was sent together with `options.resume`"
                ),
            },
            429: {"model": Problem, "description": "max_sessions reached"},
            504: {"model": Problem, "description": "The session did not open in time"},
        },
    )
    async def create_session(
        sessions: RegistryDep,
        config: SettingsDep,
        body: Annotated[SessionCreate, Body()],
    ):
        try:
            # `session_id` is passed straight through. `registry.create()`
            # validates it -- before it reserves a slot, and before any
            # subprocess starts -- so a bad id is a 400 naming the problem
            # rather than the CLI's `exit 1` arriving as a 502 that names
            # nothing. Validating HERE instead would enforce it for this route
            # only, and this module has no business knowing the CLI's rules
            # about session ids.
            sid = await sessions.create(body.options, body.title, body.sdk_session_id)
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "POST /v1/sessions")
        return _record(sid, sessions.get(sid), agent_id=config.agent_id)

    @app.get("/v1/sessions", response_model=SessionList, tags=["sessions"])
    async def list_sessions(sessions: RegistryDep, config: SettingsDep):
        return SessionList(
            sessions=[
                _record(sid, s, agent_id=config.agent_id)
                for sid, s in sessions.list()
            ]
        )

    @app.get(
        "/v1/sessions/{sid}",
        response_model=SessionRecord,
        tags=["sessions"],
        responses={
            404: {"model": Problem, "description": "No such session"},
            # NOT a pure lookup: this route awaits `session.context_usage()`, a
            # live CONTROL REQUEST. 502 is CLIConnectionError from a wedged or
            # disconnected client; 500 is the SDK's own 60s control timeout,
            # which raises a PLAIN Exception that errors.py cannot classify.
            # Both confirmed by driving real requests. Driven by
            # test_get_surfaces_an_unclassified_control_failure_as_500.
            # See CP-038
            500: {
                "model": Problem,
                "description": (
                    "The context-usage control request failed in a way the service does "
                    "not classify -- including the SDK's own 60s control timeout"
                ),
            },
            502: {
                "model": Problem,
                "description": "The context-usage control request could not be delivered",
            },
        },
    )
    async def get_session(
        sessions: RegistryDep, config: SettingsDep, sid: Annotated[str, PathParam()]
    ):
        try:
            session = sessions.get(sid)
            usage = await session.context_usage()
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "GET /v1/sessions/{sid}", sid)
        return _record(sid, session, usage, agent_id=config.agent_id)

    @app.delete(
        "/v1/sessions/{sid}",
        status_code=204,
        tags=["sessions"],
        summary="Close a session and free its subprocess",
        responses={
            404: {"model": Problem, "description": "No such session"},
            # A teardown failure is deliberately NOT flattened into the 204;
            # `registry.close()` lets it propagate and errors.py falls through
            # to 500. Pinned by tests/test_api_sessions.py's close-raises case.
            500: {
                "model": Problem,
                "description": "The session could not be torn down; the subprocess may still be alive",
            },
        },
    )
    async def delete_session(sessions: RegistryDep, sid: Annotated[str, PathParam()]):
        try:
            # A failed teardown leaves the session registered and retryable,
            # and propagates here as a real problem document -- never a 204
            # that would falsely report the subprocess as gone.
            await sessions.close(sid)
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "DELETE /v1/sessions/{sid}", sid)
        return None

    def _require_persistence():  # noqa: ANN202
        """The persistence stack, or a 404 explaining that history is off.

        Every history route starts here so the "no database" answer is decided
        once. Raising rather than returning None keeps the routes readable and
        routes the message through `to_problem` like every other failure.
        """
        if app.state.persistence is None:
            raise PersistenceDisabled
        return app.state.persistence

    def _queries():  # noqa: ANN202
        """Import the read module ONLY once persistence is known to exist.

        A top-level `from agent_spec.db import queries` would defeat the
        whole lazy-import arrangement -- `test_no_database_url_imports_no_
        database_code` catches it, and did catch it while this route was being
        written.
        """
        from agent_spec.db import queries

        return queries

    @app.get(
        "/v1/sessions/{sid}/transcript",
        response_model=TranscriptPage,
        tags=["history"],
        summary="Read a session's stored transcript",
        description=(
            "Oldest first, paginated. Reads STORED rows -- unlike "
            "`GET /v1/sessions/{sid}`, this issues no control request to the "
            "agent and cannot fail because the CLI is wedged.\n\n"
            "404 with `type: .../persistence-disabled` means the service has no "
            "database configured; 404 with the ordinary title means no such "
            "session was ever recorded."
        ),
        responses={
            404: {
                "model": Problem,
                "description": "No such recorded session, or history is not enabled",
            }
        },
    )
    async def get_transcript(
        sid: Annotated[str, PathParam()],
        limit: Annotated[int, FastQuery(ge=1, le=1000)] = 200,
        after: Annotated[int | None, FastQuery()] = None,
    ):
        try:
            persistence = _require_persistence()
            async with persistence.sessionmaker() as db:
                # An explicit existence check, so an unknown id is a 404 rather
                # than an empty page. "No events yet" and "no such session" are
                # different answers and a client acts differently on each.
                q = _queries()
                if not await q.session_exists(db, sid):
                    raise SessionNotFound(sid)
                page = await q.transcript(db, sid, limit=limit, after=after)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _problem_response(exc, "GET /v1/sessions/{sid}/transcript", sid)
        return TranscriptPage(session_id=sid, events=page.events, next_after=page.next_after)

    @app.get(
        "/v1/runs/{run_id}",
        response_model=StoredRun,
        tags=["history"],
        summary="Read one stored run or turn",
        responses={
            404: {
                "model": Problem,
                "description": "No such recorded run, or history is not enabled",
            }
        },
    )
    async def get_run(run_id: Annotated[str, PathParam()]):
        try:
            persistence = _require_persistence()
            async with persistence.sessionmaker() as db:
                row = await _queries().run(db, run_id)
            if row is None:
                raise RunNotFound(run_id)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _problem_response(exc, "GET /v1/runs/{run_id}")
        return StoredRun(**row)

    @app.post(
        "/v1/sessions/{sid}/messages",
        response_model=RunResponse,
        tags=["sessions"],
        summary="Send one turn and wait for it to complete",
        responses={
            200: {"headers": _SDK_SESSION_HEADER_SPEC},
            404: {"model": Problem, "description": "No such session"},
            409: {
                "model": Problem,
                "description": "A turn is already running, or the session is closed",
            },
            # This route drains the WHOLE turn inside its try, so every failure
            # the drain can raise is still uncommitted and becomes a real
            # status code -- unlike the streaming route below, where only
            # failures up to the first message can. All confirmed by driving
            # real requests: 504 is RunTimeout, 502 is a ProcessError/
            # CLIConnectionError/CLIJSONDecodeError, and 500 is `to_problem`'s
            # fallthrough for everything else (driven by
            # test_a_turn_failing_in_an_unclassified_way_is_500).
            # See CP-039
            500: {
                "model": Problem,
                "description": (
                    "The turn failed in a way the service does not classify"
                ),
            },
            502: {"model": Problem, "description": "The agent process failed"},
            504: {"model": Problem, "description": "The turn exceeded its time budget"},
        },
    )
    async def send_turn(
        sessions: RegistryDep,
        sid: Annotated[str, PathParam()],
        body: Annotated[TurnRequest, Body()],
        response: Response,
    ):
        try:
            session = sessions.get(sid)
            events = [AgentEvent(**e) async for e in session.send(body.prompt)]
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "POST /v1/sessions/{sid}/messages", sid)
        turn = session.last_turn
        summary = _summary(turn, events, interrupted=bool(turn and turn.interrupted))
        # Read off the SUMMARY, not off `session.session_id`, so the header and
        # the body's `sdk_session_id` are the same value by construction and
        # cannot disagree about the turn just taken. Omitted rather than sent
        # empty when unknown -- see SDK_SESSION_HEADER. Headers set here reach
        # the client only on this success path; the error path above returns a
        # JSONResponse of its own, which is correct, since there is no turn to
        # name.
        if summary.sdk_session_id:
            response.headers[SDK_SESSION_HEADER] = summary.sdk_session_id
        return summary

    @app.post(
        "/v1/sessions/{sid}/messages/stream",
        tags=["sessions"],
        summary="Send one turn, streaming each message as it arrives",
        description=(
            "Server-Sent Events. Each `data:` line is one `AgentEvent`; the "
            "`event:` name is its type. A terminal `event: done` carries the "
            "turn summary with an empty `events` list.\n\n"
            "**Errors.** This route resolves the session and takes its turn "
            "*before* committing the response, so anything that goes wrong up "
            "to and including the turn's FIRST message is a real problem "
            "document with a real status code -- 404, 409, or 504 if the turn "
            "times out before producing anything. Only a failure from the "
            "second message onwards arrives in-band, as `event: error` "
            "carrying the same `Problem` body; no `done` frame follows it, so "
            "`done` vs. `error` is how a client tells a finished turn from a "
            "broken one.\n\n"
            "Note this differs from `/v1/query/stream`, which commits its 200 "
            "before the first message and therefore reports even a "
            "zero-message failure in-band.\n\n"
            "**`x-sdk-session-id`** is sent on the response, so a relay does "
            "not have to scan the body for it. It is available here precisely "
            "because this route reads the turn's first message before "
            "committing the response; `/v1/query/stream` cannot carry it."
        ),
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {"text/event-stream": {}},
                "headers": _SDK_SESSION_HEADER_SPEC,
            },
            404: {"model": Problem, "description": "No such session"},
            409: {
                "model": Problem,
                "description": "A turn is already running, or the session is closed",
            },
            504: {
                "model": Problem,
                "description": "The turn exceeded its time budget before its first message",
            },
        },
    )
    async def stream_turn(
        sessions: RegistryDep,
        sid: Annotated[str, PathParam()],
        body: Annotated[TurnRequest, Body()],
    ):
        # No return type annotation -- same reason as `run_query_stream` above.
        try:
            session = sessions.get(sid)
            stream = session.send(body.prompt)
            # `send()` is an async GENERATOR: nothing in its body runs until
            # first advanced, so its `SessionBusy`/`SessionClosed` raises do
            # NOT happen at the call above -- a `try` around a bare `send()`
            # catches nothing. Advancing once here forces them to surface while
            # a real 404/409/504 is still available. The deliberate cost:
            # response headers are withheld until the turn's first message,
            # which for a real session is the SDK's prompt init message.
            first = await anext(stream, None)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _problem_response(
                exc, "POST /v1/sessions/{sid}/messages/stream", sid
            )

        # Whether the turn reached an end of its own accord. False means the
        # consumer walked away mid-turn; `close_stream()` reads this to decide
        # whether to interrupt.
        #
        # ALL THREE assignments are load-bearing -- deleting the one in the
        # `except` branch, or the one after the loop, each takes the SDK
        # control-request count from 0 to 1. Pinned by
        # test_a_mid_drain_failure_does_not_issue_a_control_request and
        # test_clean_completion_does_not_interrupt_the_session. This comment
        # has been wrong in BOTH directions before, so it cites the tests
        # rather than re-arguing. CP-040
        turn_ended = False

        def _frame(event: dict) -> str:
            nonlocal turn_ended
            if event.get("type") == "result":
                # Set when the frame is BUILT, not after it is written: if THIS
                # write never completes, the assignment after the loop never
                # runs and `close_stream()` would interrupt a turn whose
                # ResultMessage was already consumed (measured: `interrupts ==
                # 1` on a turn that completed with a real result).
                #
                # Keying off "a result frame was built" depends on the SDK
                # ending a turn at its FIRST ResultMessage (S1) -- a stream
                # carrying on past one would leave this set for the rest of the
                # turn. RECHECK ON ANY SDK UPGRADE, same caveat as
                # `AgentSession._record_turn`.
                turn_ended = True
            return _sse(event.get("type", "unknown"), event)

        async def generate() -> AsyncIterator[str]:
            nonlocal turn_ended
            try:
                if first is not None:
                    yield _frame(first)
                    async for event in stream:
                        yield _frame(event)
            except Exception as exc:  # noqa: BLE001 - reported in-band
                # The 200 and SSE headers are on the wire, so this cannot
                # become a status code. The stream ends WITHOUT a `done` frame,
                # which is the whole signal: `done` means the turn completed,
                # `error` (or neither) means it did not.
                turn_ended = True
                yield _sse(
                    "error",
                    _problem(
                        exc, "POST /v1/sessions/{sid}/messages/stream", sid
                    ).model_dump(),
                )
                return
            turn_ended = True
            turn = session.last_turn
            summary = _summary(turn, [], interrupted=bool(turn and turn.interrupted))
            yield _sse("done", summary.model_dump())

        async def close_stream() -> None:
            # Runs unconditionally once Starlette is finished with this
            # response, INCLUDING the client-disconnect path. Two steps, and
            # their ORDER is load-bearing.
            # See CP-040
            #
            # 1. INTERRUPT, only if the turn did not end on its own. This is a
            #    CORRECTNESS step, not a latency or cost optimisation: a
            #    consumer that walks away leaves the subprocess still producing
            #    that turn, and only the SDK can stop it. Messages still in
            #    flight are NOT coverable by `_discard_residue` -- they land
            #    during the NEXT turn's drain and a stray ResultMessage among
            #    them ends it early, attributing one caller's turn to another.
            #    `AgentSession.interrupt()` covers both disconnect
            #    interleavings (status "running" from a stalled write, and
            #    "idle" from a real socket hangup); keying only off "running"
            #    made this a no-op on the common path.
            #
            #    BEFORE the aclose() because interrupting a genuinely-running
            #    turn is what makes `AgentSession` STAMP it, so the TurnResult
            #    says `interrupted=True` rather than recording a plain failure.
            #    Pinned by test_interrupt_then_aclose_labels_the_turn_as_
            #    interrupted and its reverse-order counterpart. This is the
            #    OPPOSITE order to `AgentSession.close()`, deliberately: close()
            #    goes on to disconnect() (S5), so nothing is owed an interrupt
            #    there, whereas here the session SURVIVES and takes further
            #    turns. Failure is logged and swallowed -- a wedged control
            #    channel must not stop the force-close below, and nothing here
            #    holds the registry lock.
            #
            # 2. ACLOSE, always, from a `finally`. Starlette never calls
            #    aclose() on a body_iterator, and a disconnect lands outside
            #    both generators' frames, so neither unwinds. Left alone the
            #    abandoned turn keeps the session lock and EVERY LATER TURN
            #    409s until the cyclic GC reclaims it. This is also the only
            #    thing that makes `AgentSession.close()`'s abandoned-turn
            #    handling reachable in the common case. The `async def` wrapper
            #    is load-bearing for the same reason as run_query_stream's.
            try:
                if not turn_ended:
                    await session.interrupt()
            except Exception:  # noqa: BLE001 - never blocks the force-close
                _log.warning(
                    "stream_turn: interrupting the abandoned turn on session %s "
                    "failed; force-ending it anyway",
                    sid,
                    exc_info=True,
                )
            finally:
                await stream.aclose()

        # THE HEADER IS AVAILABLE HERE, and this is the only reason it can be
        # sent on a streaming route at all: `anext` above already pulled the
        # turn's first message -- the SDK's init -- and that is exactly what
        # `_send_impl` reads `session_id` from. So the value exists before this
        # response is committed, without buffering anything or delaying a frame.
        # (From the second turn onward it is cached on the session and would be
        # known even without that first advance.)
        #
        # `/v1/query/stream` deliberately has no counterpart: it commits its 200
        # before the first message by design, so there is nothing to read.
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        if session.session_id:
            headers[SDK_SESSION_HEADER] = session.session_id

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers=headers,
            background=BackgroundTask(close_stream),
        )

    @app.post(
        "/v1/sessions/{sid}/interrupt",
        response_model=InterruptResult,
        tags=["sessions"],
        summary="Ask a running turn to stop",
        description=(
            "Returns immediately, and returns 200 whether or not there was "
            "anything to stop -- `interrupted` says which. Asking to stop a "
            "turn that has already finished is not an error: that race is "
            "unavoidable for any client.\n\n"
            "`interrupted: false` is NOT implied by `status`, and neither "
            "field can be derived from the other -- see `InterruptResult`.\n\n"
            "The turn currently draining will end with `is_error: true` and "
            "`subtype: 'error_during_execution'` -- the SDK reports an "
            "interrupted turn identically to a failed one -- but its summary "
            "will carry `interrupted: true`, which is the only reliable way "
            "to tell the two apart."
        ),
        responses={
            404: {"model": Problem, "description": "No such session"},
            500: {
                "model": Problem,
                "description": (
                    "The control request failed in a way the service does not "
                    "classify -- including the SDK's own 60s control timeout on a "
                    "running turn, which this service does not bound"
                ),
            },
            502: {
                "model": Problem,
                "description": "The control request could not be delivered",
            },
            504: {
                "model": Problem,
                "description": "The agent did not answer the control request in time",
            },
        },
    )
    async def interrupt_session(
        sessions: RegistryDep, sid: Annotated[str, PathParam()]
    ):
        try:
            session = sessions.get(sid)
            # `interrupted` is the RETURN VALUE, never inferred from
            # `session.status` -- an abandoned turn is "idle" and still fires.
            # A failure to DELIVER is a third outcome and becomes a problem
            # document, never `interrupted: false`.
            fired = await session.interrupt()
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "POST /v1/sessions/{sid}/interrupt", sid)
        # `status` read AFTER the await, deliberately: the turn can end while
        # the control request is in flight (that IS a successful interrupt), so
        # reading it beforehand would report a finished turn as still draining.
        # Pinned by test_interrupt_reports_the_status_from_after_the_control_request.
        return InterruptResult(interrupted=fired, status=session.status)

    @app.patch(
        "/v1/sessions/{sid}",
        response_model=SessionRecord,
        tags=["sessions"],
        summary="Change the model or permission mode",
        description=(
            "Both fields are optional and an omitted field is left unchanged, "
            "so an empty body is a valid no-op. An omitted field is NOT "
            "forwarded as null: the SDK reads a null model as 'use the "
            "default', so doing that would silently reset it. Every other "
            "option is fixed for the session's lifetime.\n\n"
            "**A change takes effect immediately, including on a turn that is "
            "already in flight.** This is measured, not assumed: it applies at "
            "the very next inference of the turn currently draining, not from "
            "the next turn, so a mid-turn model change re-prices the remainder "
            "of that turn and its `model_usage` reports both models. It is "
            "safe -- the in-flight turn is not disturbed and still ends "
            "normally -- but expect `total_cost_usd` to move by more than the "
            "new model alone would suggest."
        ),
        responses={
            404: {"model": Problem, "description": "No such session"},
            # RARE but genuinely reachable, and the obvious reading is that it
            # is not: it needs a session CLOSED yet still REGISTERED, which no
            # ordinary teardown path leaves behind. The CANCELLATION path does
            # -- `AgentSession.close()`'s `except CancelledError` disconnects,
            # sets status "closed" and re-raises, so `registry.close()` skips
            # its removal. Pinned from both ends by
            # test_patch_a_closed_session_is_409_like_the_messages_route and
            # test_patch_openapi_declares_its_reachable_errors; do not drop
            # either. CP-042
            409: {"model": Problem, "description": "The session is closed"},
            500: {
                "model": Problem,
                "description": "The agent did not answer the control request in time",
            },
            502: {
                "model": Problem,
                "description": "The control request could not be delivered",
            },
        },
    )
    async def update_session(
        sessions: RegistryDep,
        config: SettingsDep,
        sid: Annotated[str, PathParam()],
        body: Annotated[SessionUpdate, Body()],
    ):
        try:
            session = sessions.get(sid)
            # LOAD-BEARING, not defensive: the SDK reads `set_model(None)` as
            # "use the default", so forwarding an omitted field would turn
            # `PATCH {}` from a no-op into a silent RESET. Pinned by
            # test_patch_with_no_fields_calls_neither_setter, which asserts on
            # call COUNTS -- values cannot tell "never called" from "called
            # with None".
            if body.model is not None:
                await session.set_model(body.model)
            if body.permission_mode is not None:
                # The same guard the create path has, and it is needed for
                # the same reason: `permission_mode` stopped being a closed
                # `Literal` in 0.19.0, so pydantic no longer refuses an
                # unknown value and this route would otherwise hand it to
                # the SDK. A 400 replaces what used to be a 422 -- both
                # refuse, and only one of them can say which modes exist.
                # See CP-143
                check_permission_mode(body.permission_mode)
                await session.set_permission_mode(body.permission_mode)
        except Exception as exc:  # noqa: BLE001
            return _problem_response(exc, "PATCH /v1/sessions/{sid}", sid)
        # No `context_usage` here: unlike GET, this route has not fetched it,
        # and `_record` leaves the field null rather than inventing one.
        return _record(sid, session, agent_id=config.agent_id)

    # **The document's `paths` in one canonical order, shared by all three
    # builds and by the core.** FastAPI writes them in route-registration order,
    # so without this the JSON key order is whichever order the decorators
    # happened to run in -- and nothing catches it: `freeze` hashes each
    # document against its own copy, the core is a set intersection, and AS-24's
    # check is a dict comparison, which ignores key order. AS-31 makes these
    # documents isomorphic; this is what makes it visible.
    # **This build's own answer, in its own document** -- an OpenAPI document
    # describes the SHAPE of `/v1/capabilities` and says nothing about the
    # values, so three documents look identical while the three builds are not.
    # Built from DEFAULT settings, never the live ones: AS-24 requires the
    # service to serve exactly its published document, and an example carrying
    # a deployment's port or cap would break that for every deployment.
# **`model_construct()`, NOT `Settings()`, and this is the whole
    # deployment-invariance requirement.** `Settings()` reads the environment,
    # so the example would carry whatever the machine generating the document
    # happened to have set -- measured: the test suite exports
    # AGENT_SERVICE_REQUIRE_MOUNTS=false session-wide, which made the app's
    # document disagree with the published one and broke AS-24. This reads the
    # DECLARED DEFAULTS and nothing else.
    attach_capabilities_example(
        app, _capabilities_payload(Settings.model_construct()).model_dump(mode="json")
    )

    # **One 422 across all three builds, and it names the fields without echoing
    # the values.** Registered with the declaration below rather than separately:
    # either alone recreates the defect the consumer reported -- a build
    # answering with a shape its own document does not describe.
    @app.exception_handler(RequestValidationError)
    async def _validation_problem(  # noqa: ANN202
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = validation_problem(exc.errors())
        return JSONResponse(
            status_code=422,
            content=problem.model_dump(mode="json"),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    enforce_canonical_order(app)
    declare_validation_problem(app)

    # **This build's pre-boot answer, in this build's own document.** The same
    # argument as the capabilities example above, for the surface that is not
    # HTTP at all: a consumer holds the published documents as a build-time
    # dependency and pulls an image at runtime, so facts needed BEFORE a
    # container exists -- which credential variable, which CA variable, which
    # database revision -- were reachable from nothing it was told to depend on.
    #
    # Attached here rather than in the dump script because AS-24 is byte
    # equality: a component the generator added would make every running service
    # disagree with its own published document.
    attach_preboot(app, specification())

    return app
