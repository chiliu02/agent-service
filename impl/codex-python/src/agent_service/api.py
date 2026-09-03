"""FastAPI application — the meta routes.

**`/healthz` and `/v1/capabilities` only, for now.** The turn and session routes
come next; this exists so the specification's conformance suite can be pointed
at this build *today* rather than after everything is written. A build that
cannot be measured until it is finished is a build whose first measurement is
also its first surprise.

## It imports its models from `agent_spec`, not from here

Those pydantic models generate the published document, and AS-24 requires every
implementation to serve the **same** one. Sharing them is what makes that
achievable rather than aspirational (CX-46).

## The duplication is real and is being left visible

Most of this file will look like `impl/claude-python/src/agent_service/api.py`,
because both are determined by the same specification. **That is evidence for
extracting the API layer to `impl/common/`, and the extraction is deliberately
not being done from one copy.** `api.py` there needs seven implementation
modules and only two are SDK-coupled, so the plug point is small — but a shared
framework designed against a single implementation is shaped like that
implementation. Two real copies first, then extract.
"""

import contextlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator

from agent_spec.openapi.examples import attach_capabilities_example
from agent_spec.openapi.preboot import attach_preboot

from agent_service.spec import specification
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
from fastapi import Body, FastAPI, Path as PathParam, Query as FastQuery, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_service.auth import install_auth
from agent_service.config import (
    ALWAYS_DISALLOWED_TOOLS,
    CREDENTIAL_ENV_VARS,
    DEFAULT_ALLOWED_TOOLS,
    PROVIDER_SELECTOR_ENV_VARS,
    Settings,
    credentials_configured,
    process_capacity_warning,
    process_limit,
    verify_auth,
    verify_credentials,
    verify_mounts,
)
from agent_service.errors import (
    UNCLASSIFIED_TITLE,
    PersistenceDisabled,
    RunNotFound,
    to_problem,
)
from agent_service.options import (
    HONOURED_EFFORT_LEVELS,
    MCP_HTTP_HEADERS,
    MCP_TRANSPORTS,
    REFUSED_OPTIONS,
    SUPPORTED_SETTING_SOURCES,
    session_modes,
)
from agent_service.registry import SessionEntry, SessionNotFound, SessionRegistry
from agent_service.versions import (
    DOCUMENT_VERSION,
    IMPLEMENTATION_NAME,
    IMPLEMENTATION_VERSION,
)

_log = logging.getLogger(__name__)

#: AS-7. The SDK's own conversation id, on the response as well as in the body,
#: so a relay does not have to parse the payload to route on it.
#:
#: **Always present here**, which the Claude build cannot promise: Codex assigns
#: the thread id at `thread_start()`, so it is known before the first turn
#: rather than arriving with it. It is still declared as optional in the
#: document, because a caller must not be made to depend on which
#: implementation it is talking to.
SDK_SESSION_HEADER = "x-sdk-session-id"

_SDK_SESSION_HEADER_SPEC = {
    SDK_SESSION_HEADER: {
        "description": (
            "The SDK's own conversation id for this turn -- the same value as "
            "`sdk_session_id` in the body. It is NOT a `/v1/sessions/{sid}` "
            "path handle.\n\n"
            "Treat it as optional: this implementation always sends it, but the "
            "specification permits an implementation whose id is unknown until "
            "the first turn to omit it."
        ),
        "schema": {"type": "string"},
    }
}

#: Statuses a CLASSIFIED failure is logged at WARNING for. Deliberately not
#: ">= 500": that would sweep in 504, which is a budget this service set
#: expiring rather than a fault.
_WARN_STATUSES = frozenset({500, 502})


def _sdk_version() -> str:
    """The Codex SDK's version, read from the installed package."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("openai-codex")
    except PackageNotFoundError:  # pragma: no cover - only outside an install
        return "unknown"


def _token_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """Codex's `TokenUsageBreakdown` mapped to the specification's named counts.

    **Four of the five, and the missing one is the expensive half of the cache
    pair.** Codex delivers `inputTokens`, `outputTokens`, `cachedInputTokens`,
    `reasoningOutputTokens` and `totalTokens` on `thread/tokenUsage/updated`; it
    has **no cache-WRITE counter**. So `cache_write_tokens` is `null` here, and
    that is the consumer-visible consequence worth naming: on this build a cache
    write -- typically billed at a premium -- is a charge this API cannot show
    you. `null` rather than `0` is what makes the gap visible instead of free.

    The Claude build is the mirror image: it has both cache counters and does not
    separate reasoning tokens.

    **`totalTokens` is deliberately not carried.** It is derivable from the parts
    on any build that reports them, and a field that is sometimes a sum and
    sometimes a differently-scoped total is worse than no field.

    **Two things here were wrong from the day this shipped until 2026-08-09, and
    the second is why the first went unnoticed** -- (CX-13):

    * It read **camelCase** keys, under a docstring asserting *"these are the
      SDK's own spellings"*. They are **snake_case**: `input_tokens`,
      `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens`.
    * It read them from the **top level**. `usage` is a dump of the SDK's token
      usage object, which is `{"last": …, "total": …, "model_context_window":
      …}` -- the counts are one level down, and `total` is CUMULATIVE for the
      thread while `last` is this turn.

    So every real turn published five nulls while the numbers sat beside them in
    the raw `usage` pass-through. **`.get` degrading to `null` rather than
    raising is what hid it**: the intent was to survive an upstream rename, and
    the effect was that a wrong key was indistinguishable from an absent one --
    `null` here means *this build cannot report that*, which is precisely the
    ambiguity AS-17a rejects, and this build could.

    **`last`, not `total`.** `TokenUsage` is documented as scope THIS RUN, and
    `total` is the thread's running sum -- reporting it would inflate every turn
    after the first by the whole conversation.

    **No fallback to the top level if `last` is missing**, deliberately. A
    silent second chance is what this function already had; the shape is pinned
    by `test_api_meta.py` against the verbatim payload measured from a real turn,
    and by a live conformance clause that fails when a count present in `usage`
    is `null` in `token_usage`.
    """
    counts = (usage or {}).get("last")
    if not isinstance(counts, dict):
        return TokenUsage()

    def _int(key: str) -> int | None:
        value = counts.get(key)
        return value if isinstance(value, int) else None

    return TokenUsage(
        input_tokens=_int("input_tokens"),
        output_tokens=_int("output_tokens"),
        cache_read_tokens=_int("cached_input_tokens"),
        # No counter exists. See the docstring: not zero, unknown.
        cache_write_tokens=None,
        reasoning_output_tokens=_int("reasoning_output_tokens"),
    )


def _summary(sid_value: str | None, outcome, events: list[AgentEvent]) -> RunResponse:  # noqa: ANN001
    """`TurnOutcome` -> the specification's `RunResponse`.

    One function for both turn surfaces, so `/v1/query` and a session turn
    cannot drift about what a turn produced -- the drift that forced
    `outcome_recorded` to be hand-carried between endpoints in the Claude build.
    """
    return RunResponse(
        session_id=sid_value,
        # The SAME value under the name that says which id it is. Filled from
        # one argument so the two cannot disagree.
        sdk_session_id=sid_value,
        # `status` is set only by `turn/completed`, so this is exactly "did the
        # turn reach an end of its own accord".
        outcome_recorded=outcome.status is not None,
        result=outcome.final_response,
        is_error=outcome.status == "failed",
        # **Read off the SDK's own terminal status, never inferred.** Codex has
        # a first-class `interrupted` status, so this build never has to tell an
        # interrupted turn from a failed one by inspecting an error string --
        # which is what the Claude build's `interrupted` flag exists to do.
        interrupted=outcome.status == "interrupted",
        # 0.19.0. Derived in `agent_spec` so both builds cannot answer
        # differently: this passes facts and the specification decides the
        # word. `subtype` is the raw input because it IS this SDK's ending --
        # `completed` maps to `end_turn`, and anything else falls through to
        # `other` rather than being guessed at here. (CX-48)
        stop_kind=derive_stop_kind(
            outcome_recorded=outcome.status is not None,
            is_error=outcome.status == "failed",
            interrupted=outcome.status == "interrupted",
            timed_out=bool(outcome.timed_out),
            raw=outcome.status,
        ),
        subtype=outcome.status,
        stop_reason=None,
        terminal_reason=outcome.error,
        limit_hit=None,
        num_turns=None,
        # AS-17: null, never 0. Codex reports no money at all -- measured over
        # the whole package -- and `0.0` would read as *free*.
        total_cost_usd=None,
        turn_cost_usd=None,
        duration_ms=outcome.duration_ms,
        usage=outcome.usage,
        # 0.19.0. The specification's spelling beside the verbatim pass-through.
        token_usage=_token_usage(outcome.usage),
        # Cumulative-per-connection in the Claude build; Codex has no such
        # figure and inventing one from `usage` would give it a scope it does
        # not have.
        model_usage=None,
        permission_denials=None,
        events=events,
    )


def _turn_record(outcome, sdk_session_id: str | None = None) -> TurnRecord | None:  # noqa: ANN001
    """`SessionEntry.last_turn` rendered for a `SessionRecord`.

    Reads the very same `TurnOutcome` that `_summary` reads, so a session's
    record and the turn response cannot disagree about the same turn.

    **`sdk_session_id` is a parameter because a `TurnOutcome` does not carry
    one**, and hardcoding `None` here was a defect until 2026-08-09 -- found by
    the first paid conformance run this build ever had. **AS-16 says the record
    and the turn agree about the SDK id**, and this one reported the thread id
    on the record and `null` on the turn beside it.

    It is the same shape as the `token_usage` defect in (CX-13),
    one field along: `null` means NOT KNOWN, and this build knows -- the thread
    id exists from `thread_start()`, before any turn. A turn cannot belong to a
    different conversation than the session it ran in, so there is nothing to
    read off the outcome; the session's id IS the turn's id.
    """
    if outcome is None:
        return None
    return TurnRecord(
        sdk_session_id=sdk_session_id,
        outcome_recorded=outcome.status is not None,
        interrupted=outcome.status == "interrupted",
        # **Read off the outcome since 2026-08-08**, when this build started
        # bounding turns. It was hardcoded `False` with a comment saying nothing
        # bounded a turn yet -- true when written, and a lie the moment the
        # deadline landed.
        #
        # This field is why the deadline had to carry its partial outcome at all:
        # a `SessionRecord` fetched later has no status code, so `timed_out` is
        # the only thing separating a timeout from every other
        # `outcome_recorded: false` ending.
        timed_out=outcome.timed_out,
        is_error=outcome.status == "failed",
        # Same derivation as the live response, and this is the surface it is
        # worth most on: the 504 that announced a timeout is long gone by the
        # time anyone reads a stored record. (CX-48)
        stop_kind=derive_stop_kind(
            outcome_recorded=outcome.status is not None,
            is_error=outcome.status == "failed",
            interrupted=outcome.status == "interrupted",
            timed_out=bool(outcome.timed_out),
            raw=outcome.status,
        ),
        subtype=outcome.status,
        stop_reason=None,
        terminal_reason=outcome.error,
        limit_hit=None,
        num_turns=None,
        duration_ms=outcome.duration_ms,
        turn_cost_usd=None,
    )


def _record(sid: str, entry: SessionEntry, agent_id: str | None = None) -> SessionRecord:
    record = SessionRecord(
        session_id=sid,
        # A PROCESS constant threaded from settings, never read off the session:
        # a value stored per-session could be written by whatever created it,
        # which is exactly the assertion this field must not be.
        agent_id=agent_id,
        # **Never null on this build.** Codex assigns the thread id at
        # `thread_start()`, so the specification's "null until the first turn"
        # allowance is never needed here. See (CX-15).
        sdk_session_id=entry.session.sdk_session_id,
        title=entry.title,
        status=entry.status,
        created_at=entry.created_at,
        last_used_at=entry.last_used_at,
        turns=entry.turns,
        total_cost_usd=entry.total_cost_usd,
        model=entry.model,
        permission_mode=entry.permission_mode,
        last_residue_discarded=0,
        # On EVERY route that builds a record, not just GET -- a record whose
        # contents depended on which verb produced it would be a second
        # `outcome_recorded`.
        # The SAME value the record publishes above, threaded through rather
        # than looked up again -- AS-16 is that these two agree, so they must
        # come from one read.
        last_turn=_turn_record(entry.last_turn, entry.session.sdk_session_id),
        # Codex exposes no context-window control request, so this stays null
        # rather than being invented. `GET /v1/sessions/{sid}` therefore issues
        # no live request here and cannot fail because the agent is wedged --
        # the opposite of the Claude build, where that route is the one that
        # talks to the subprocess.
        context_usage=None,
    )
    return record


def _sse(name: str, payload: dict) -> str:
    """One Server-Sent Event frame. Shared by both streaming routes, so the two
    wire formats cannot drift apart."""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app(
    settings: Settings | None = None, registry: SessionRegistry | None = None
) -> FastAPI:
    resolved = settings or Settings.from_env()

    # PERSISTENCE, OPTIONAL, and the import is inside the branch on purpose.
    # With no `AGENT_SERVICE_DATABASE_URL` this process never imports
    # SQLAlchemy at all -- plan-03's global constraint, and the reason
    # `agent_spec.db.__init__` resolves its names lazily.
    #
    # **No `session_store_factory`.** That is A.2, the SDK's own transcript
    # mirror, and it exists so the Claude CLI can resume from the database.
    # Codex has thread items and no such seam, so this build passes nothing and
    # loses only that mirror -- A.1, which is what
    # `/v1/sessions/{sid}/transcript` actually reads, is the platform's and is
    # unaffected.
    persistence = None
    if resolved.database_url:
        from agent_spec.db.wiring import Persistence

        persistence = Persistence(resolved.database_url, resolved.agent_id)

    sessions = registry or SessionRegistry(
        resolved, recorder=persistence.recorder if persistence else None
    )

    def _problem(exc: BaseException, route: str, sid: str | None = None) -> Problem:
        """The problem document, and a log record behind it where one is owed.

        **Every 4xx is deliberately not logged.** They are ordinary API answers
        decided by what the caller asked for, already visible in the access log
        with their status; logging them at fault level would put an ERROR on the
        most common thing a polling client does. 504 sits on that same side: a
        budget this service set expiring is the budget working.

        What is logged is the route, the session id, and the exception CLASS
        NAME -- never `str(exc)`, never the prompt, never the request body.
        """
        problem = to_problem(exc)
        where = f"{route} session={sid}" if sid is not None else route
        if problem.title == UNCLASSIFIED_TITLE:
            # The only branch with a traceback, because this is the branch that
            # means "we do not know what this is" -- the type is not in
            # errors.py's table, so the traceback is all that can identify it.
            _log.error(
                "%s: unclassified failure (%s) -- answering %d",
                where, type(exc).__name__, problem.status, exc_info=exc,
            )
        elif problem.status in _WARN_STATUSES:
            _log.warning("%s: %s (%s) -- answering %d", where, problem.title,
                         type(exc).__name__, problem.status)
        return problem

    def _fail(exc: BaseException, route: str, sid: str | None = None) -> JSONResponse:
        problem = _problem(exc, route, sid)
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # AS-2. Raising here aborts startup, which uvicorn turns into
        # sys.exit(3) -- so a misconfigured container exits rather than serving
        # requests it cannot fulfil. Outside any try/except on purpose: nothing
        # has started yet, so a `finally` would only add noise to the one
        # message an operator needs to read.
        verify_credentials(resolved)
        # The second gate, and the order matters only for which message an
        # operator sees first when both are wrong. Credentials first because a
        # container with neither is almost always a container with no `.env` at
        # all, and that is the more useful thing to be told.
        verify_mounts(resolved)
        # The third, and it refuses a variable rather than a missing one: this
        # build publishes `auth_required` and enforces nothing behind it.
        verify_auth(resolved)
        # The fourth gate, and the only one that needs a connection -- which is
        # why it is here rather than in `config.py` beside the other three.
        # Refuses in EITHER direction: an image behind the database writes rows
        # missing a column the fleet relies on, and an image ahead fails on
        # first use anyway. AS-30's enforcement, and Studio's ask.
        if persistence is not None:
            await persistence.verify_revision()
            persistence.start()
        # **Not a gate, deliberately** (CX-19). `max_sessions` and the
        # container's `pids_limit` are set independently, so a deployment can
        # advertise a cap it cannot carry -- and that is recoverable without a
        # restart and already answered by a named 503, which is the platform's
        # own line between reporting and refusing. Silent on a host with no
        # limit to read.
        if (warning := process_capacity_warning(resolved, process_limit())) is not None:
            _log.warning("%s", warning)
        sessions.start_reaper()
        try:
            yield
        finally:
            # Both, and in this order: a reaper still running while sessions are
            # being torn down would race the shutdown for the same entries.
            await sessions.stop_reaper()
            await sessions.close_all()
            # AFTER close_all(), because the `session_closed` rows it produces
            # are enqueued during it -- draining first would lose the last thing
            # every session did.
            if persistence is not None:
                await persistence.aclose()

    app = FastAPI(
        lifespan=lifespan,
        title="Agent Service",
        # THE DOCUMENT'S VERSION, not this build's. Every implementation
        # satisfying a given specification reports the same value here, which is
        # the whole point of the two streams being separate.
        version=DOCUMENT_VERSION,
        description=(
            "HTTP access to the OpenAI Codex SDK. One implementation of the "
            "agent-service specification."
        ),
    )
    app.state.settings = resolved

    # **Installed here, before any route is declared, and by prefix rather than
    # per-route.** A `Depends(...)` has to be remembered on every route and the
    # failure mode of forgetting is an unauthenticated endpoint that looks like
    # all the others; matching `/v1` means a route added tomorrow is covered by
    # having been added at all. With no token configured nothing is installed --
    # see `auth.install_auth`.
    install_auth(app, resolved.auth_token)

    @app.get("/healthz", response_model=Health, tags=["meta"])
    async def healthz() -> Health:
        return Health(
            status="ok",
            credentials_configured=credentials_configured(),
            workspace_dir=str(resolved.workspace_dir),
            auth_required=bool(resolved.auth_token),
            database_configured=bool(resolved.database_url),
            # `null` ONLY when unconfigured. Once a URL is set this is a real
            # probe against a real table -- `SELECT 1` would pass an unmigrated
            # schema, which is the likeliest first state of any deployment.
            # "Not configured" and "configured and broken" are different
            # answers and the specification keeps them apart.
            database_usable=(await persistence.usable() if persistence else None),
        )

    def _capabilities_payload(resolved) -> Deployment:
        """The payload, so the route and the published example share one source.

        Extracted so the document can carry this build's REAL answer as its
        `/v1/capabilities` example. Two copies would drift, and the example is
        the copy nobody would notice going stale.
        """
        return Deployment.from_flat(
            spec=Spec(document_version=DOCUMENT_VERSION),
            impl=Impl(name=IMPLEMENTATION_NAME, version=IMPLEMENTATION_VERSION),
            sdk=Sdk(name="openai-codex", version=_sdk_version()),
            sdk_version=_sdk_version(),
            # Read from the shared models, not restated: these ARE the
            # specification's vocabularies, and a build that published its own
            # copy could drift from the document it serves.
            # Declared by this build, not taken from a shared union (CX-49).
            permission_modes=session_modes(),
            # **What this build delivers EXACTLY, not the whole vocabulary**
            # (CX-53). `max` has no equivalent and is still honoured by mapping
            # to `xhigh` -- but publishing it said "available" and quietly gave
            # one step less, which a client optimising for reasoning could not
            # see. Read from the mapping table so the two cannot drift.
            effort_levels=list(HONOURED_EFFORT_LEVELS),
            # **What this build can HONOUR, not the specification's whole
            # vocabulary**, which is what it published until 2026-08-09 while
            # honouring none of it. Agent Studio asked the question directly and
            # the answer is measured: Codex reads `AGENTS.md` from the thread's
            # cwd, and `project_doc_max_bytes=0` suppresses it -- so `project`
            # is selectable, `user` is unconditional, and `local` has no
            # equivalent. `options.py` has the table.
            setting_sources=list(SUPPORTED_SETTING_SOURCES),
            default_model=resolved.default_model,
            default_allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
            always_disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
            # **Only the limits this build ENFORCES, which is why the turns and
            # budget pairs are absent** (2026-08-08). `limits` is a free-form
            # `dict[str, float]`, so an implementation publishes what it has --
            # and a figure published here is a promise about behaviour, not a
            # configuration dump. This build applied none of the four while
            # publishing all four; (CX-10) is the
            # write-up, and `options.py` has the per-option argument.
            #
            # A caller that sets `max_turns` or `max_budget_usd` is told so by
            # `unsupported` on the turn response rather than left to infer it
            # from an absent key -- absence here is the standing fact, that
            # field is the per-request answer.
            #
            # `session_idle_ttl_s` joined in 0.19.0, and it is the one figure here
            # that bounds how long the SERVICE keeps something rather than what a
            # request may ask for. It is published because a consumer
            # reconciling a lost `201` by listing sessions needs to know how long
            # an unmatched record survives the idle reaper.
            accepts_limits={
                "default_request_timeout_s": float(resolved.default_request_timeout_s),
                "max_allowed_timeout_s": float(resolved.max_allowed_timeout_s),
            },
            behaviour_limits={
                # 0.19.0: how long an unmatched session record survives before
                # the idle reaper takes it. A consumer reconciling a lost 201 by
                # listing sessions needs this to size its window. **Enforced by
                # this service rather than asked for by a caller**, which is the
                # line the two maps are split along.
                "session_idle_ttl_s": float(resolved.session_idle_ttl_s),
            },
            # **"not_reported", which is a third value because neither of the
            # other two is right here.** This build sends `model_usage: None` on
            # every turn and every session -- the SDK has no per-model figure and
            # deriving one from `usage` would give it a scope it does not have.
            # *Sum it* and *difference it* are both wrong instructions for a key
            # that is never there; *skip it* is the correct one.
            model_usage_scope="not_reported",
            # FALSE, and measured on a real completed turn (CX-12, CX-29): there
            # is no monetary figure anywhere in this SDK, so `total_cost_usd` and
            # `turn_cost_usd` are null on every session and every turn,
            # permanently and by nature rather than by configuration. `0.0` reads
            # as *free*, which was defended here once and was wrong.
            reports_cost_usd=False,
            workspace_dir=str(resolved.workspace_dir),
            reference_dirs=[str(p) for p in resolved.reference_dirs],
            credential_sources=list(CREDENTIAL_ENV_VARS),
            provider_selectors=list(PROVIDER_SELECTOR_ENV_VARS),
            max_sessions=resolved.max_sessions,
            require_credentials=resolved.require_credentials,
            auth_required=bool(resolved.auth_token),
            # **TRUE since 2026-08-09**, and it was `false` because this build
            # could configure an MCP server and not let the agent call one --
            # (CX-06) The approval policy in `approvals.py`
            # is what closed that, so the field can finally mean what it says.
            #
            # An operator still turns it off, exactly as on the Claude build:
            # a stdio server is a subprocess that starts with the session and
            # appears in no turn's events, which is an attribution question
            # rather than a capability one.
            allow_mcp_servers=resolved.allow_mcp_servers,
            # FALSE, and measured rather than assumed: `AsyncCodex.thread_start()`
            # takes no id parameter -- Codex mints a UUIDv7 itself and offers no
            # override. This build answers 400 rather than adopting the field and
            # returning a different id, which would break the mapping silently.
            #
            # It still REPORTS an `sdk_session_id`, and reports it at creation
            # rather than after the first turn. The flag is about who chooses the
            # value, not about whether there is one.
            # **"conversation".** Codex mints the thread id at
            # `thread_start()`, so it exists before the first turn and does not
            # move as turns are taken -- which is why the `201` already carries
            # it where the Claude build reports null.
            sdk_session_id_scope="conversation",
            # **MEASURED THROUGH THE APP-SERVER, in the container** (CX-50): a
            # sink standing where the model endpoint would be captured
            # `thread-id` carrying the exact string this service reports as
            # `sdk_session_id`. Two other headers carry it too and `thread-id`
            # is the one published, for the reason the entry gives -- it names
            # what the id IS here, where `x-client-request-id` names a request
            # and may stop agreeing.
            #
            # It was `measured: false` for a day on purpose: the CLI front end
            # sends the same headers, and inferring the equality from a
            # different `originator` is the one thing this field exists not to
            # do (CX-20).
            llm_correlation={"header": "thread-id", "measured": True},
            allow_supplied_sdk_session_id=False,
            # AS-32 (0.19.0). Both TRUE here, and both are the mirror of the
            # Claude build -- which is exactly why they are published rather
            # than left to a document diff.
            #
            # The thread id exists from `thread_start()`, so a one-shot response
            # can carry the header: a relay reads it instead of scanning a body.
            query_reports_sdk_session_id=True,
            # `/v1/query` here opens a REAL throwaway session, so it reserves a
            # slot and can answer 429 -- which the Claude build's one-shot never
            # does, because it drives the SDK without the registry.
            query_consumes_a_session_slot=True,
            # **Read from `options.py`, not written here**, so the standing list
            # and the 400 `Registry.create` raises come from one place. A
            # capability that says one thing while the code does another is the
            # exact failure AS-32 exists to prevent, and a hand-kept copy is how
            # it would happen.
            #
            # `mcp_servers` is in it, which is what makes `allow_mcp_servers:
            # false` above enforceable rather than advisory: before 0.19.0 this
            # build published `false` and then accepted the field anyway.
            # **Measured, not read off a default** (CX-09)
            # the egress section). `read_only` and `workspace_write` both block
            # the agent's shell from opening a socket, while the container
            # itself returns HTTP:200 -- the control that makes those two rows
            # mean anything. `sandbox_workspace_write.network_access` would
            # switch it on and this build leaves it alone.
            sandbox={"network_access": False, "confines_writes_to_workspace": True},
            unsupported_options=list(REFUSED_OPTIONS),
            # **Two transports and one header**, measured rather than assumed:
            # `codex mcp add --url` is streamable HTTP with no SSE form, and
            # authentication is a `bearer_token_env_var` rather than arbitrary
            # headers. `options.mcp_overrides` refuses the rest with a 400
            # naming the reason, and this is where a client reads it first.
            # `server_name_pattern` is NULL: nothing here refuses a server name,
            # which is a statement about this service's own check rather than a
            # promise that the SDK accepts every name.
            mcp={
                "transports": list(MCP_TRANSPORTS),
                "http_headers": MCP_HTTP_HEADERS,
                "server_name_pattern": None,
            },
            # **All four NULL, and that is "no bound" rather than "not looked"**
            # (CX-60). `tool_timeout_sec` resolves to null on a server this build
            # writes and the binary carries no tool-call timeout message at all
            # -- the only MCP timeout it can emit names the handshake. With no
            # timer, `progress_resets_idle` has nothing to answer about.
            mcp_tool_call={
                "request_timeout_s": None,
                "idle_timeout_s": None,
                "total_timeout_s": None,
                "progress_resets_idle": None,
            },
            strict_mcp_config=True,
            require_mounts=resolved.require_mounts,
            # Codex enforces by SANDBOX rather than by an in-process hook, and
            # the specification's vocabulary has no member for that. `none` is
            # the honest answer: no in-process write-confinement is wired up,
            # which is exactly what the value means. The sandbox is reported
            # per-request through `permission_mode` instead.
            permission_enforcement="none",
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
    async def run_options_schema() -> JSONResponse:
        return JSONResponse(
            effective_run_options_schema(
                RunOptions.model_json_schema(),
                _capabilities_payload(resolved).accepts.model_dump(),
                impl=IMPLEMENTATION_NAME,
            ),
            media_type="application/schema+json",
        )

    @app.get("/v1/deployment", response_model=Deployment, tags=["meta"])
    async def deployment() -> Deployment:
        return _capabilities_payload(resolved)

    # --- sessions ---------------------------------------------------------

    @app.post(
        "/v1/sessions",
        response_model=SessionRecord,
        status_code=201,
        tags=["sessions"],
        summary="Open a multi-turn session",
        description=(
            "Returns the registry handle as `session_id`.\n\n"
            "**`sdk_session_id` is always populated on this build**, because "
            "Codex assigns its thread id when the thread is created rather than "
            "at the first turn. The specification permits null there; this "
            "implementation never needs it.\n\n"
            "**A caller-supplied `sdk_session_id` is refused with 400.** The "
            "Codex SDK mints the id itself and offers no way to set one, so "
            "accepting the field would mean returning a different id than was "
            "asked for -- silently breaking the mapping the field exists to "
            "provide."
        ),
        responses={
            400: {
                "model": Problem,
                "description": (
                    "Invalid options, a limit above its cap, or a supplied "
                    "`sdk_session_id`, which this implementation cannot honour"
                ),
            },
            429: {"model": Problem, "description": "max_sessions reached"},
            # **AS-33, and it arrived from a measurement rather than a review.**
            # `max_sessions` is a number this service enforces; the container's
            # `pids_limit` is the thing underneath it, and the two are set
            # independently. Measured: ~30 pids per session, so `pids_limit: 512`
            # carries about 16 sessions whatever the cap says -- and the create
            # past that answered `500 "Unhandled error"` until it was classified.
            503: {
                "model": Problem,
                "description": (
                    "The container cannot start another agent process -- it is "
                    "at its pid limit, which is a lower ceiling than "
                    "`max_sessions` on a deployment that raised the cap. "
                    "Retryable: closing a session clears it"
                ),
            },
            504: {"model": Problem, "description": "The session did not open in time"},
        },
    )
    async def create_session(body: Annotated[SessionCreate, Body()]):
        try:
            sid = await sessions.create(body.options, body.title, body.sdk_session_id)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "POST /v1/sessions")
        return _record(sid, sessions.get(sid), agent_id=resolved.agent_id)

    @app.get("/v1/sessions", response_model=SessionList, tags=["sessions"])
    async def list_sessions() -> SessionList:
        return SessionList(
            sessions=[
                _record(sid, entry, agent_id=resolved.agent_id)
                for sid, entry in sessions.list()
            ]
        )

    @app.get(
        "/v1/sessions/{sid}",
        response_model=SessionRecord,
        tags=["sessions"],
        summary="Read one session",
        description=(
            "**A pure lookup on this build.** Codex exposes no context-window "
            "control request, so `context_usage` is null and this route issues "
            "nothing to the agent -- it cannot fail because the runtime is "
            "wedged."
        ),
        responses={404: {"model": Problem, "description": "No such session"}},
    )
    async def get_session(sid: Annotated[str, PathParam()]):
        try:
            entry = sessions.get(sid)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "GET /v1/sessions/{sid}", sid)
        return _record(sid, entry, agent_id=resolved.agent_id)

    @app.delete(
        "/v1/sessions/{sid}",
        status_code=204,
        tags=["sessions"],
        summary="Close a session and free its app-server",
        responses={
            404: {"model": Problem, "description": "No such session"},
            500: {
                "model": Problem,
                "description": (
                    "The session could not be torn down; the app-server may "
                    "still be running"
                ),
            },
        },
    )
    async def delete_session(sid: Annotated[str, PathParam()]):
        try:
            # A failed teardown leaves the session registered and retryable
            # rather than answering 204, which would report a subprocess as gone
            # while it is still alive.
            await sessions.close(sid)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "DELETE /v1/sessions/{sid}", sid)
        return None

    @app.patch(
        "/v1/sessions/{sid}",
        response_model=SessionRecord,
        tags=["sessions"],
        summary="Change the model or permission mode",
        description=(
            "Both fields are optional and an omitted field is left unchanged, "
            "so an empty body is a valid no-op.\n\n"
            "**The change applies from the NEXT turn, not to a turn already in "
            "flight.** Codex takes model, sandbox and approval mode as "
            "arguments to each turn rather than as connection state, so there "
            "is no control request and nothing to disturb mid-turn. This "
            "differs from an implementation that mutates a live connection, "
            "where a change lands at the very next inference."
        ),
        responses={404: {"model": Problem, "description": "No such session"}},
    )
    async def update_session(
        sid: Annotated[str, PathParam()], body: Annotated[SessionUpdate, Body()]
    ):
        try:
            entry = sessions.get(sid)
            # An omitted field must not be forwarded as null -- that would turn
            # `PATCH {}` from a no-op into a silent reset.
            if body.model is not None:
                entry.model = body.model
            if body.permission_mode is not None:
                entry.permission_mode = body.permission_mode
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "PATCH /v1/sessions/{sid}", sid)
        return _record(sid, entry, agent_id=resolved.agent_id)

    @app.post(
        "/v1/sessions/{sid}/interrupt",
        response_model=InterruptResult,
        tags=["sessions"],
        summary="Ask a running turn to stop",
        description=(
            "Returns 200 whether or not there was anything to stop -- "
            "`interrupted` says which. Asking to stop a turn that has already "
            "finished is not an error: that race is unavoidable for any client."
        ),
        responses={
            404: {"model": Problem, "description": "No such session"},
            # This route DOES reach the app-server -- `TurnHandle.interrupt()`
            # is a control message over the transport -- so unlike GET and
            # PATCH on this build, a wedged or dead runtime is reachable here.
            # 502 is `TransportClosedError`, 500 anything else the SDK raises.
            # Added 2026-08-08; both were reachable and undeclared.
            #
            # NO 503: an interrupt is a control message and never a model call,
            # so `ServerBusyError` has no path to it.
            500: {
                "model": Problem,
                "description": (
                    "The interrupt failed in a way this service does not "
                    "classify further"
                ),
            },
            502: {
                "model": Problem,
                "description": "The agent runtime could not be reached",
            },
        },
    )
    async def interrupt_session(sid: Annotated[str, PathParam()]):
        try:
            # `interrupted` is the RETURN VALUE, never inferred from status. A
            # failure to DELIVER is a third outcome and becomes a problem
            # document, never `interrupted: false`.
            fired = await sessions.interrupt(sid)
            entry = sessions.get(sid)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "POST /v1/sessions/{sid}/interrupt", sid)
        # Status read AFTER the interrupt: the turn can end while the request is
        # in flight, and that IS a successful interrupt.
        return InterruptResult(interrupted=fired, status=entry.status)

    # --- turns ------------------------------------------------------------

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
            # 500 and 503 added 2026-08-08, and they were REACHABLE AND
            # UNDECLARED -- `errors.py` maps `CodexError` to 500 and
            # `ServerBusyError`/`RetryLimitExceededError` to 503, both of which
            # a turn can raise, and neither of which appeared in this document.
            #
            # 503 is the one worth spelling out: it was declared by NEITHER
            # implementation, so comparing the two documents could not find it.
            # A client without a 503 branch reads "the upstream is busy, retry
            # later" as a failed turn -- the one condition where retrying is
            # exactly right. See (CX-24).
            500: {
                "model": Problem,
                "description": (
                    "The agent runtime failed in a way this service does not "
                    "classify further"
                ),
            },
            503: {
                "model": Problem,
                "description": (
                    "The upstream model API is busy and the SDK's own retries "
                    "were exhausted. The request itself was fine -- retry later"
                ),
            },
            504: {
                "model": Problem,
                "description": (
                    "The turn outlived its `timeout_s` budget. The turn was "
                    "interrupted; retry with a longer budget, up to "
                    "`limits.max_allowed_timeout_s`"
                ),
            },
            502: {"model": Problem, "description": "The agent runtime failed"},
        },
    )
    async def send_turn(
        sid: Annotated[str, PathParam()],
        body: Annotated[TurnRequest, Body()],
        response: Response,
    ):
        try:
            entry = sessions.get(sid)
            outcome = await sessions.send(sid, body.prompt, entry.options)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "POST /v1/sessions/{sid}/messages", sid)
        events = [AgentEvent(**e) for e in outcome.events]
        summary = _summary(entry.session.sdk_session_id, outcome, events)
        # Read off the SUMMARY, not off the session, so the header and the
        # body's `sdk_session_id` are the same value by construction.
        if summary.sdk_session_id:
            response.headers[SDK_SESSION_HEADER] = summary.sdk_session_id
        return summary

    @app.post(
        "/v1/sessions/{sid}/messages/stream",
        tags=["sessions"],
        summary="Send one turn, streaming each event as it arrives",
        description=(
            "Server-Sent Events. Each `data:` line is one `AgentEvent`; the "
            "`event:` name is its type. A terminal `event: done` carries the "
            "turn summary with an empty `events` list.\n\n"
            "**Errors.** The session is resolved before the response is "
            "committed, so a 404 or a 409 is a real status code with a problem "
            "document. A failure once streaming has begun arrives in-band as "
            "`event: error` carrying the same `Problem` body, with no `done` "
            "frame after it -- so `done` versus `error` is how a client tells a "
            "finished turn from a broken one."
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
        },
    )
    async def stream_turn(
        sid: Annotated[str, PathParam()], body: Annotated[TurnRequest, Body()]
    ):
        # **Resolved BEFORE the response is committed**, which is what keeps a
        # 404 and a 409 real status codes rather than in-band frames. This build
        # can check both synchronously -- the registry knows whether the session
        # exists and whether its turn lock is held -- so unlike an
        # implementation that must advance a generator to find out, nothing has
        # to be pulled from the agent first.
        try:
            entry = sessions.check_available(sid)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "POST /v1/sessions/{sid}/messages/stream", sid)

        sdk_id = entry.session.sdk_session_id

        async def generate() -> AsyncIterator[str]:
            try:
                outcome = await sessions.send(sid, body.prompt, entry.options)
            except Exception as exc:  # noqa: BLE001 - in-band, see the description
                problem = _problem(exc, "POST /v1/sessions/{sid}/messages/stream", sid)
                yield _sse("error", problem.model_dump())
                return
            for event in outcome.events:
                yield _sse(str(event.get("type", "unknown")), event)
            # `events` deliberately empty on the terminal frame: they have all
            # been sent already and repeating them would double the payload.
            yield _sse("done", _summary(sdk_id, outcome, []).model_dump())

        headers = {SDK_SESSION_HEADER: sdk_id} if sdk_id else None
        return StreamingResponse(
            generate(), media_type="text/event-stream", headers=headers
        )

    # --- one-shot ---------------------------------------------------------

    @app.post(
        "/v1/query",
        response_model=RunResponse,
        tags=["query"],
        summary="Run one prompt in a throwaway session",
        description=(
            "Opens a session, takes one turn, and closes it. Use "
            "`/v1/sessions` when the conversation continues."
        ),
        responses={
            200: {"headers": _SDK_SESSION_HEADER_SPEC},
            400: {"model": Problem, "description": "Invalid options"},
            429: {"model": Problem, "description": "max_sessions reached"},
            # Same pair as the session turn route, and reachable for the same
            # reason: this route takes a real turn. See that route's comment.
            500: {
                "model": Problem,
                "description": (
                    "The agent runtime failed in a way this service does not "
                    "classify further"
                ),
            },
            503: {
                "model": Problem,
                "description": (
                    "The upstream model API is busy and the SDK's own retries "
                    "were exhausted. The request itself was fine -- retry later"
                ),
            },
            504: {
                "model": Problem,
                "description": (
                    "The turn outlived its `timeout_s` budget. The turn was "
                    "interrupted; retry with a longer budget, up to "
                    "`limits.max_allowed_timeout_s`"
                ),
            },
            502: {"model": Problem, "description": "The agent runtime failed"},
        },
    )
    async def run_query(body: Annotated[QueryRequest, Body()], response: Response):
        sid = None
        try:
            sid = await sessions.create(body.options)
            sdk_id = sessions.get(sid).session.sdk_session_id
            outcome = await sessions.send(sid, body.prompt, body.options)
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "POST /v1/query")
        finally:
            # **In a `finally`, so a failed turn still frees its app-server.**
            # A one-shot that leaked a session on every error would fill the cap
            # with conversations nothing can reach -- and since `session_id` is
            # never returned to the caller here, nothing could close them.
            if sid is not None:
                with contextlib.suppress(Exception):
                    await sessions.close(sid)
        events = [AgentEvent(**e) for e in outcome.events]
        summary = _summary(sdk_id, outcome, events)
        if summary.sdk_session_id:
            response.headers[SDK_SESSION_HEADER] = summary.sdk_session_id
        return summary

    @app.post(
        "/v1/query/stream",
        tags=["query"],
        summary="Run one prompt in a throwaway session, streaming",
        description=(
            "Server-Sent Events, same frames as the session streaming route.\n\n"
            "**No `x-sdk-session-id` header.** The 200 is committed before the "
            "session exists, so there is no id to send yet; it is in every "
            "frame's body instead."
        ),
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def run_query_stream(body: Annotated[QueryRequest, Body()]):
        async def generate() -> AsyncIterator[str]:
            sid = None
            try:
                sid = await sessions.create(body.options)
                sdk_id = sessions.get(sid).session.sdk_session_id
                outcome = await sessions.send(sid, body.prompt, body.options)
            except Exception as exc:  # noqa: BLE001 - the 200 is already committed
                problem = _problem(exc, "POST /v1/query/stream")
                yield _sse("error", problem.model_dump())
                return
            finally:
                if sid is not None:
                    with contextlib.suppress(Exception):
                        await sessions.close(sid)
            for event in outcome.events:
                yield _sse(str(event.get("type", "unknown")), event)
            yield _sse("done", _summary(sdk_id, outcome, []).model_dump())

        return StreamingResponse(generate(), media_type="text/event-stream")

    # --- history ----------------------------------------------------------
    #
    # **Both routes exist and both refuse**, which is the point: a route that is
    # absent is indistinguishable from a route that is broken, and the
    # specification distinguishes "history is off" from "no such session" by the
    # problem `type`. Registering them is what makes the first answer available
    # at all -- without them these would be the framework's ordinary 404.

    @app.get(
        "/v1/sessions/{sid}/transcript",
        response_model=TranscriptPage,
        tags=["history"],
        summary="Read a session's stored transcript",
        description=(
            "**Not available on this build**: no database is wired up yet, so "
            "this always answers 404 with "
            "`type: .../persistence-disabled`. That is a different 404 from "
            "'no such session', and a console reads the type to say 'history "
            "is off' rather than 'empty'."
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
            if persistence is None:
                raise PersistenceDisabled()
            from agent_spec.db import queries

            async with persistence.sessionmaker() as db:
                # An explicit existence check, so an unknown id is a 404 rather
                # than an empty page. "No events yet" and "no such session" are
                # different answers and a client acts differently on each.
                if not await queries.session_exists(db, sid):
                    raise SessionNotFound(sid)
                page = await queries.transcript(db, sid, limit=limit, after=after)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _fail(exc, "GET /v1/sessions/{sid}/transcript", sid)
        return TranscriptPage(
            session_id=sid, events=page.events, next_after=page.next_after
        )

    @app.get(
        "/v1/runs/{run_id}",
        response_model=StoredRun,
        tags=["history"],
        summary="Read one stored run or turn",
        description="**Not available on this build** -- see the transcript route.",
        responses={
            404: {
                "model": Problem,
                "description": "No such recorded run, or history is not enabled",
            }
        },
    )
    async def get_run(run_id: Annotated[str, PathParam()]):
        try:
            if persistence is None:
                raise PersistenceDisabled()
            from agent_spec.db import queries

            async with persistence.sessionmaker() as db:
                row = await queries.run(db, run_id)
            if row is None:
                raise RunNotFound(run_id)
        except Exception as exc:  # noqa: BLE001 - mapped to a problem document
            return _fail(exc, "GET /v1/runs/{run_id}")
        return StoredRun(**row)

    # --- AS-21: EVERY error is a problem document -------------------------
    #
    # Three handlers, not one, and that is the point. Wiring only our own
    # exceptions leaves the clause false for the errors a FRAMEWORK produces --
    # a 404 for an unknown path, a 422 from request validation -- which is
    # exactly how this build failed the conformance suite on 2026-08-08.

    def _problem_response(problem, status: int | None = None) -> JSONResponse:
        return JSONResponse(
            status_code=status or problem.status,
            content=problem.model_dump(),
            # The whole clause is this header. A correct body with
            # `application/json` still fails AS-21.
            media_type="application/problem+json",
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_problem(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """404s and any `raise HTTPException` -- the framework's own errors."""
        return _problem_response(
            Problem(
                type="about:blank",
                title=str(exc.detail) if exc.detail else "HTTP error",
                status=exc.status_code,
                detail=None,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_problem(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """422 from a malformed body, **naming the fields and echoing no values.**

        This build refused to echo the framework's errors at all, which was right
        about `input` and wrong about `loc`: withholding the field name left a
        caller diffing their own request against the document. It was also
        answering with a shape its own document did not describe (CX-61).
        """
        problem = validation_problem(exc.errors())
        return JSONResponse(
            status_code=422,
            content=problem.model_dump(mode="json"),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def _unhandled_problem(_request: Request, exc: Exception) -> JSONResponse:
        """Everything else, including the SDK's own -- see `errors.to_problem`."""
        return _problem_response(to_problem(exc))

    # **The document's `paths` in one canonical order, shared by all three
    # builds and by the core.** FastAPI writes them in route-registration order,
    # so without this the JSON key order is whichever order the decorators
    # happened to run in -- and nothing catches it: `freeze` hashes each
    # document against its own copy, the core is a set intersection, and AS-24's
    # check is a dict comparison, which ignores key order. AS-31 makes these
    # documents isomorphic; this is what makes it visible.
    # **This build's own answer, in its own document.** An OpenAPI document
    # describes the SHAPE of `/v1/capabilities` and says nothing about the
    # values, so three documents look identical while the three builds are not.
    # Built from DEFAULT settings, never the live ones: AS-24 requires the
    # service to serve exactly its published document.
# **`model_construct()`, NOT `Settings()`, and this is the whole
    # deployment-invariance requirement.** `Settings()` reads the environment,
    # so the example would carry whatever the machine generating the document
    # happened to have set -- measured: the test suite exports
    # AGENT_SERVICE_REQUIRE_MOUNTS=false session-wide, which made the app's
    # document disagree with the published one and broke AS-24. This reads the
    # DECLARED DEFAULTS and nothing else.
    attach_capabilities_example(
        app, _capabilities_payload(Settings()).model_dump(mode="json")
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
