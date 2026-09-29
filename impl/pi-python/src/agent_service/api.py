"""The HTTP surface. `create_app(settings)` builds it; `main.py` runs it.

**The document is the contract and it is shared, not copied** — every model here
comes from `agent_spec`, because AS-24 requires each implementation to serve the
same document and two hand-maintained copies cannot stay byte-identical.

**What exists so far:** `/healthz` and `/v1/capabilities`. The session and turn
routes follow; this file grows rather than being replaced.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from agent_spec.openapi.run_options_schema import (
    effective_run_options_schema,
)
from agent_spec.openapi.schemas import (
    RunOptions,
    AgentEvent,
    Deployment,
    Health,
    InterruptResult,
    Problem,
    QueryRequest,
    RunResponse,
    SessionCreate,
    SessionList,
    SessionRecord,
    SessionUpdate,
    StoredRun,
    TokenUsage,
    TranscriptPage,
    TurnRequest,
)
from agent_spec.db.recorder import NULL_RECORDER
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
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from agent_service.auth import install_auth
from agent_service.capabilities import (
    DEFAULT_PERMISSION_MODE,
    PERMISSION_MODES,
    UNSUPPORTED_OPTIONS,
    build_capabilities,
    reference_capabilities,
)
from agent_service.pi import (
    PiError,
    PiRunner,
    CredentialMissing,
    ResumeTargetMissing,
    StreamingTurn,
    TurnResult,
    TurnTimeout,
)
from agent_service.config import Settings, check_boot, credentials_configured
from agent_service.persistence import to_run_outcome
from agent_service.mcp import (
    McpServersNotAllowed,
    McpUnsupported,
    StrictModeRequired,
)
from agent_service.mcp import validate as validate_mcp
from agent_service.registry import (
    InvalidWorkspacePath,
    ProviderNotFronted,
    Registry,
    RegistryFull,
    Session,
    UnknownSession,
    check_provider,
)
from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_NAME

#: RFC 7807, which every error on this surface is. **Branch on `type` and
#: `status`, never on `title` or `detail`** -- those are prose and prose changes.
PROBLEM_BASE = "https://agent-service.invalid/problems"

#: **Every status a route can produce is DECLARED, and absence means
#: unreachable.** AS-31 requires the published documents to be structurally
#: identical across builds, so these are not decoration: an undeclared 404 makes
#: this build's document differ from the others' and narrows the shared core for
#: everyone. The Codex build states the same rule from its own side.
_P = {"model": Problem}
_NOT_FOUND = {404: _P}
_SESSION_ERRORS = {404: _P, 500: _P, 502: _P}
_TURN_ERRORS = {404: _P, 409: _P, 500: _P, 502: _P, 503: _P, 504: _P}
_CREATE_ERRORS = {400: _P, 429: _P, 503: _P, 504: _P}
# **No 429 here.** `query_consumes_a_session_slot` is false, so a query cannot
# hit the cap -- and AS-32 checks the document against the capability.
_QUERY_ERRORS = {400: _P, 500: _P, 502: _P, 503: _P, 504: _P}

#: The agent's own conversation id, echoed as a header so a proxy or relay can
#: recover it without parsing a body or scanning an SSE stream. **It is STABLE
#: across turns on this build** (`PI-13`), so it identifies the conversation and
#: a relay may key on it -- which is not true of every build.

#: The modes this build honours, from the same table capabilities publishes,
#: so a refusal here can never disagree with what was advertised.
_PERMISSION_MODE_IDS = frozenset(m.id for m in PERMISSION_MODES)

#: **From the same table capabilities publishes**, so what is advertised as
#: refused is what is actually refused. A published refusal that does not happen
#: is the defect the Codex build shipped twice, and AS-32 exists to catch it.
#:
#: **Every entry EXCEPT the value-scoped ones**, carried here as
#: `(field, types)`. An entry carrying `values` refuses particular values and
#: honours the rest, so refusing the field here would 400 the value that works
#: -- `strict_mcp_config: true` is what this build actually does. Such an entry
#: is enforced by the code that owns the condition (the owning route for that
#: one), which also answers with the problem `type` naming what failed rather
#: than the generic one: the field is supported and the VALUE is not.
#:
#: **`types` is carried rather than dropped** (`PI-20`). It narrows an entry to
#: some shapes of one field, which is what `system_prompt` needs: the string
#: form is honoured and the Claude preset object is not, so the field cannot be
#: refused outright and the refusal cannot be dropped either.
_REFUSED_FIELDS = tuple(
    sorted((o.field, tuple(o.types or ())) for o in UNSUPPORTED_OPTIONS
           if o.values is None)
)


def _json_type(value: Any) -> str:
    """The JSON type name of a sent value, as `UnsupportedOption.types` spells it."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "object"


def _refused_option(options: Any) -> tuple[str, tuple[str, ...]] | None:
    """The first published-unsupported field a caller actually sent, if any.

    **`exclude_unset`, so an absent field is not a request.** A client that
    serialises its whole options object with nulls has asked for nothing, and
    refusing it would make the model unusable rather than honest.

    **`types` narrows an entry to some SHAPES of one field**, which is what
    `system_prompt` needs here (`PI-20`): the string form is honoured and the
    Claude preset object has no equivalent. The published algorithm is
    `field matches && (types is null || types contains jsonTypeOf(v))`, and this
    is the half of it that runs -- an entry carrying `values` is enforced by the
    code that owns the condition, which is why it is skipped above.
    """
    if options is None:
        return None
    sent = options.model_dump(exclude_unset=True)
    for field, types in _REFUSED_FIELDS:
        value = sent.get(field)
        if value in (None, [], {}, ()):
            continue
        if types and _json_type(value) not in types:
            continue
        return field, types
    return None


def _mcp_request(options: Any, settings: Settings) -> Any:
    """The servers for a request, refused per SERVER or per deployment.

    **`strict_mcp_config: false` is refused here rather than by the generic
    reader** (`PI-45`), because the entry is value-scoped: the field is
    supported and one value is not, so the refusal names what actually failed.
    """
    servers = getattr(options, "mcp_servers", None) or None
    if getattr(options, "strict_mcp_config", None) is False:
        raise StrictModeRequired(
            "this build cannot run non-strict. It points the agent at its own "
            "MCP config with `--mcp-config`, so the adapter's six-file "
            "precedence chain -- two of whose paths are inside the caller's "
            "mounted workspace -- never runs. `accepts.strict_mcp_config` is "
            "true. Send the servers you want in `mcp_servers` instead."
        )
    if servers is not None and settings.mcp_adapter_path is None:
        raise McpServersNotAllowed(
            "this deployment accepts no MCP servers: its image carries no MCP "
            "adapter, published as `behaviour.allow_mcp_servers: false`. MCP on "
            "this agent is a separate extension rather than a built-in, so an "
            "image without it has no route to offer."
        )
    validate_mcp(servers)
    return servers


def _mcp_refused(error: Exception) -> JSONResponse:
    """One shape for all three MCP refusals, so a client branches on `type`."""
    if isinstance(error, McpServersNotAllowed):
        return problem(400, "mcp-servers-not-allowed",
                       "This deployment does not accept MCP servers", str(error))
    if isinstance(error, StrictModeRequired):
        return problem(400, "strict-mcp-config-required",
                       "This build cannot run with strict_mcp_config false",
                       str(error))
    return problem(400, "mcp-server-unsupported",
                   "This build cannot use that MCP server", str(error))


def _ephemeral(registry: Registry, options: Any, servers: Any = None) -> Session:
    """The `/v1/query` session, built the same way on both query routes.

    One place, because the two routes drifted once already: an option applied on
    the buffered route and not on the streaming one is invisible until someone
    compares two transcripts.
    """
    return registry.ephemeral(
        model=getattr(options, "model", None),
        permission_mode=(
            getattr(options, "permission_mode", None) or DEFAULT_PERMISSION_MODE
        ),
        allowed_tools=tuple(getattr(options, "allowed_tools", None) or ()) or None,
        disallowed_tools=tuple(getattr(options, "disallowed_tools", None) or ()),
        system_prompt=_system_prompt(options),
        include_raw=getattr(options, "include_raw", None) is not False,
        working_directory=getattr(options, "working_directory", None),
        mcp_servers=servers,
    )


def _system_prompt(options: Any) -> str | None:
    """`RunOptions.system_prompt`, when it is a form this build can honour.

    **It REPLACES the agent's own prompt, it does not append to it** (`PI-20`).
    That is the agent's semantics, not a choice made here: `--system-prompt`
    stands in for the built-in prompt entirely, so a caller sending three words
    gets an agent with three words of framing. The Codex build's
    `base_instructions` behaves the same way and is documented the same way.

    **Pi also has `--append-system-prompt`**, which is the preset object's
    keep-and-add semantics, and this build does not wire it: the object names a
    preset belonging to another agent, so there is nothing to keep. It is the
    obvious second version of this field.

    **A dict never reaches here** -- the preset object is refused by
    `_refused_option` before a session exists -- so the isinstance guard is what
    keeps that true rather than a second policy.
    """
    prompt = getattr(options, "system_prompt", None)
    return prompt if isinstance(prompt, str) and prompt else None


def _unsupported(refusal: tuple[str, tuple[str, ...]]) -> JSONResponse:
    field, types = refusal
    # **The shape is named when the entry is narrowed to one**, because the
    # remedy differs: a whole-field refusal means omit the field, and a
    # type-scoped one means send the other form (`PI-20`).
    shape = f" in its {'/'.join(types)} form" if types else ""
    return problem(
        400, "unsupported-options",
        f"This build does not support {field!r}{shape}",
        f"capabilities.unsupported_options names {field!r}"
        + (f" with types={list(types)}" if types else "")
        + ". It is refused rather than accepted and ignored: an option that is "
        "taken and never applied is indistinguishable from one that worked.",
    )

SDK_SESSION_HEADER = "x-sdk-session-id"
_ID_HEADER = {
    200: {"headers": {SDK_SESSION_HEADER: {
        "schema": {"type": "string"},
        # **AS-8 requires the first-turn case to be STATED**, and it is a
        # documentation clause checked as documentation: a consumer once wrote
        # an SSE scanner to live without a header that was always there, because
        # nothing said so. The words are the deliverable.
        "description": (
            "The agent's own conversation id for this turn, echoed so a proxy "
            "or relay can recover it without parsing a body or scanning an SSE "
            "stream. **Present on the first turn**, including on the streaming "
            "route: this build gives the agent an id when it starts the turn, "
            "so there is no turn whose id is not yet known. It is absent only "
            "when a turn produced no id at all. **It identifies the TURN, not "
            "the conversation** -- on a resumed session this build's agent "
            "mints a new id every turn, so route on it but never key on it."
        ),
    }}}
}


def create_app(settings: Settings) -> FastAPI:
    """Build the app. **Does not check the boot gates** -- the lifespan does.

    Keeping them out of here is what lets a test build an app cheaply and what
    lets `/openapi.json` be generated offline, with no credential and no
    database, which is how the published document is produced.
    """

    # **IMPORTED LAZILY, and only when a URL is configured.** With persistence
    # off this branch is never taken, `agent_spec.db.wiring` never enters
    # sys.modules, and SQLAlchemy is never imported at all -- pinned by a
    # fresh-interpreter test, because an in-process check passes as soon as any
    # other test has imported it.
    persistence = None
    recorder: Any = NULL_RECORDER
    if settings.database_url:
        from agent_spec.db.wiring import Persistence

        # **No `session_store_factory`, and that is a real difference rather
        # than an omission.** That argument exists so the Claude SDK can RESUME
        # from Postgres. This agent resumes from a `--session-file` on disk
        # (`PI-11`) and has no such seam, so the database is a record here and
        # never a source: losing it costs history, never continuity.
        persistence = Persistence(settings.database_url, settings.agent_id)
        recorder = persistence.recorder

    registry = Registry(settings, recorder)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # **Exit 3 on a misconfiguration, not a crash and not a first-turn
        # failure.** An orchestrator can tell the difference, and every refusal
        # names its own remedy.
        #
        # The mechanism is uvicorn's, not ours: raising here aborts startup and
        # uvicorn turns that into `sys.exit(3)`. Verified in the image rather
        # than assumed, and the conformance suite asserts the same number
        # against every implementation, so it is a shared guarantee rather than
        # a coincidence this build relies on.
        check_boot(settings)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        settings.agent_dir_root.mkdir(parents=True, exist_ok=True)
        settings.session_store.mkdir(parents=True, exist_ok=True)
        if persistence is not None:
            # **A fourth boot gate, and it fails the same way as the other
            # three.** A database at the wrong migration is a configuration
            # error, so it aborts startup with exit 3 rather than surfacing as a
            # write failure on some later turn.
            #
            # Boot-only, always. A database that breaks or recovers WHILE the
            # service runs is reported through `/healthz` and takes nothing
            # down -- refuse at boot what should never have started, report at
            # runtime what may recover.
            await persistence.verify_revision()
            persistence.start()
        try:
            yield
        finally:
            # After everything else: the queue drains here, bounded by its own
            # timeout, and a slow database must not hold up a container stop.
            if persistence is not None:
                await persistence.aclose()

    app = FastAPI(
        title="agent-service",
        # **The DOCUMENT's version, not this build's** -- since 0.12.0 the two
        # are separate streams. A client reads `capabilities.impl.version` to
        # learn which build it is talking to.
        version=DOCUMENT_VERSION,
        summary=f"HTTP access to Gemini CLI headless ({IMPLEMENTATION_NAME}).",
        lifespan=lifespan,
    )
    # Exposed on the app rather than closed over only, so a test can inspect
    # what no route reveals -- every id a session has answered to -- without
    # a route being invented to make a test pass.
    app.state.registry = registry
    #: Exposed for the same reason as the registry: a test can build the argv a
    #: turn WOULD use without taking one, which is how the MCP allow list is
    #: asserted for free.
    app.state.settings = settings
    #: `None` when no database is configured, which is what the fresh-interpreter
    #: test asserts on: it must be possible to prove from OUTSIDE that the lazy
    #: import never happened.
    app.state.persistence = persistence

    # **Installed before any route is declared, and by PREFIX rather than per
    # route.** A `Depends(...)` has to be remembered on every route and the
    # failure mode of forgetting is an unauthenticated endpoint that looks like
    # the others. With no token configured nothing is installed at all, so the
    # open deployment is the same code path rather than an equivalent one.
    install_auth(app, settings.auth_token)

    @app.get("/healthz", response_model=Health, tags=["meta"])
    async def healthz() -> Health:
        """Liveness, plus a LIVE report on the credential.

        Credentials that disappear after boot do not stop a running service, so
        this is read now rather than remembered from startup.
        """
        return Health(
            status="ok",
            credentials_configured=credentials_configured(),
            workspace_dir=str(settings.workspace_dir),
            # **Read from the setting, never hardcoded.** Publishing `false`
            # from a service that checks a token -- or `true` from one that does
            # not -- is the defect `auth_enforced` exists to make visible.
            auth_required=settings.auth_token is not None,
            # Persistence is optional here exactly as on the other builds
            # answer, which is what makes a stale id resolvable at all.
            database_configured=persistence is not None,
            # **null, not false, when none is configured.** `false` says a
            # database was checked and found unusable; null is reserved for
            # nothing to check. The probe is bounded by the wiring's own
            # timeout, because THIS ROUTE IS THE CONTAINER'S HEALTHCHECK: an
            # unbounded probe against a hanging database would fail the
            # healthcheck and restart a service whose agent side is fine.
            database_usable=(await persistence.usable()
                             if persistence is not None else None),
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
                build_capabilities(settings).accepts.model_dump(),
                impl=IMPLEMENTATION_NAME,
            ),
            media_type="application/schema+json",
        )

    @app.get(
        "/v1/deployment",
        response_model=Deployment,
        tags=["meta"],
        responses={
            200: {
                # **THE EXAMPLE IS THIS BUILD'S ACTUAL ANSWER**, not an
                # illustration. Without it the document describes the SHAPE of
                # the payload and says nothing about its values, so a consumer
                # holding every build's document still cannot see how the builds
                # differ without starting each one.
                #
                # Built from this build's DEFAULTS, never from the running
                # settings: AS-24 requires the service to serve exactly the
                # published document, and an example carrying a live port or
                # cap would break that for every deployment that changed one.
                "description": (
                    "This build's capabilities. **The example is real** -- every "
                    "field in it except the deployment-dependent ones "
                    "(`workspace_dir`, `limits`, `max_sessions`, "
                    "`require_credentials`, `require_mounts`, `auth_required`, "
                    "`allow_mcp_servers`, `default_model`, `reference_dirs`) is "
                    "what a live instance returns, and a test pins that so it "
                    "cannot drift. Those exceptions show this build's defaults; "
                    "read the endpoint for an instance's own. **Three version "
                    "strings read `x.y.z` and are not defaults but placeholders** "
                    "-- `impl.version`, `sdk.version` and `sdk_version` move "
                    "whenever this build does, and this document is frozen at a "
                    "release, so a real value here would stop matching the "
                    "service it describes. Read them from the endpoint, or from "
                    "the image before it runs."
                ),
            }
        },
    )
    async def deployment() -> Deployment:
        """Every difference a client must act on (AS-32).

        Read this instead of branching on the image tag. If you find yourself
        diffing two documents, that is a defect on this side.
        """
        return build_capabilities(settings)

    # --- one-shot -----------------------------------------------------------

    @app.post("/v1/query", response_model=RunResponse, tags=["query"],
              responses={**_QUERY_ERRORS, **_ID_HEADER})
    async def run_query(body: QueryRequest, response: Response) -> Any:
        """Run one turn to completion with no session.

        **Consumes no session slot**, which is published rather than assumed:
        `capabilities.query_consumes_a_session_slot` is `false`. It gets its own
        HOME and its own policy all the same — a one-shot turn is not a turn with
        a smaller boundary.
        """
        options = body.options
        refused = _refused_option(options)
        if refused:
            return _unsupported(refused)
        try:
            servers = _mcp_request(options, settings)
        except (McpUnsupported, McpServersNotAllowed, StrictModeRequired) as refused:
            return _mcp_refused(refused)
        try:
            check_provider(getattr(options, "model", None), settings,
                           settings.provider_gateways)
        except ProviderNotFronted as unfronted:
            return problem(400, "provider-not-fronted",
                           "No gateway is configured for that provider",
                           str(unfronted))
        try:
            session = _ephemeral(registry, options, servers)
        except InvalidWorkspacePath as bad:
            return problem(400, "invalid-working-directory",
                           "working_directory is not a directory under the "
                           "workspace root", str(bad))
        try:
            outcome = await _run_turn(settings, session, body.prompt, recorder)
        finally:
            registry.discard(session)
        _stamp_id(response, outcome)
        return outcome

    @app.post("/v1/query/stream", tags=["query"])
    async def run_query_stream(body: QueryRequest) -> Any:
        """The same, as Server-Sent Events.

        **This route commits EARLY, and that is the whole difference from
        `/v1/sessions/{id}/messages/stream`.** The 200 is written before the
        first message exists, so **every** failure — including one that produces
        no events at all — arrives in-band as `event: error` rather than as a
        status code. A client that only checks the status here will read a
        failed turn as a successful one.

        It cannot be otherwise: there is no session to 404 on and no lock to 409
        on, so there is nothing to learn before committing that would be worth
        waiting for.
        """
        options = body.options
        refused = _refused_option(options)
        if refused:
            return _unsupported(refused)
        try:
            servers = _mcp_request(options, settings)
        except (McpUnsupported, McpServersNotAllowed, StrictModeRequired) as refused:
            return _mcp_refused(refused)
        try:
            check_provider(getattr(options, "model", None), settings,
                           settings.provider_gateways)
        except ProviderNotFronted as unfronted:
            return problem(400, "provider-not-fronted",
                           "No gateway is configured for that provider",
                           str(unfronted))
        try:
            session = _ephemeral(registry, options, servers)
        except InvalidWorkspacePath as bad:
            return problem(400, "invalid-working-directory",
                           "working_directory is not a directory under the "
                           "workspace root", str(bad))
        recording = _Recording(recorder, session)
        recording.started(session, body.prompt)
        stream = StreamingTurn(
            _runner_for(settings, session), body.prompt,
            timeout=settings.turn_timeout_s,
            sdk_session_id=(session.sdk_session_id or str(uuid.uuid4())),
            cwd=session.cwd,
            process_sink=session.attach_process,
        )
        return StreamingResponse(
            _sse_oneshot(registry, session, stream, recording),
            media_type="text/event-stream",
        )

    # --- sessions -----------------------------------------------------------

    @app.post("/v1/sessions", response_model=SessionRecord, status_code=201,
              tags=["sessions"], responses=_CREATE_ERRORS)
    async def create_session(body: SessionCreate) -> Any:
        """Open a session. **A supplied `sdk_session_id` is HONOURED** (`PI-14`).

        `--session-id` is echoed back verbatim in the opening event, so a caller
        may name the conversation rather than reading back an id this service
        minted. Two of the other three builds refuse this; publishing
        `allow_supplied_sdk_session_id: true` is what lets a client tell.
        """
        # `session_id` on the request is DEPRECATED in the document and reading
        # it as an attribute emits a warning, so it is read from the dump. The
        # deprecated spelling is accepted as an alias for the current one.
        provided = body.model_dump(exclude_unset=True)
        # **Key PRESENCE, not truthiness**, and the difference is a clause. `""`
        # is falsy, so an `or` chain here treated an empty supplied id as *no id
        # supplied* and answered 201 — which is exactly one of AS-14's three
        # parametrised cases, and it passed the other two.
        supplied_id = (provided["sdk_session_id"] if "sdk_session_id" in provided
                       else provided.get("session_id") if "session_id" in provided
                       else None)
        options = body.options
        if supplied_id is not None:
            # **AS-14, and this build had to learn it the way the clause
            # intends** (`PI-39`): adopting a caller's id is a privilege that
            # comes with two obligations, and the container tier failed four
            # clauses until both were met.
            try:
                uuid.UUID(str(supplied_id))
            except (ValueError, AttributeError, TypeError):
                return problem(
                    400, "invalid-sdk-session-id",
                    "A supplied session id must be a UUID",
                    f"{supplied_id!r} is not a UUID. This build adopts a "
                    "caller-supplied conversation id verbatim -- "
                    "`allow_supplied_sdk_session_id` is true -- so the id it is "
                    "given is the id it will report and resume from, and an "
                    "unparseable one would be adopted rather than corrected.",
                )
            if getattr(options, "resume", None):
                return problem(
                    400, "sdk-session-id-conflicts-with-resume",
                    "A supplied session id cannot be combined with `resume`",
                    "`sdk_session_id` NAMES a new conversation and "
                    "`options.resume` CONTINUES an existing one, so sending "
                    "both asks for two different conversations in one session. "
                    "The agent refuses the equivalent pair of flags outright; "
                    "this refuses it before a turn is taken.",
                )
        refused = _refused_option(options)
        if refused:
            return _unsupported(refused)
        mode = getattr(options, "permission_mode", None) or DEFAULT_PERMISSION_MODE
        if mode not in _PERMISSION_MODE_IDS:
            return problem(
                400, "unknown-permission-mode", "No such permission mode",
                f"{mode!r} is not a mode this build honours. Read "
                f"capabilities.permission_modes: {sorted(_PERMISSION_MODE_IDS)}. "
                "Forwarding an unknown value would hand the agent a flag it "
                "would reject at the first turn instead of now.",
            )
        try:
            servers = _mcp_request(options, settings)
        except (McpUnsupported, McpServersNotAllowed, StrictModeRequired) as refused:
            return _mcp_refused(refused)
        try:
            check_provider(getattr(options, "model", None), settings,
                           settings.provider_gateways)
        except ProviderNotFronted as unfronted:
            return problem(400, "provider-not-fronted",
                           "No gateway is configured for that provider",
                           str(unfronted))
        try:
            session = registry.create(
                title=body.title,
                model=getattr(options, "model", None),
                permission_mode=mode,
                allowed_tools=tuple(getattr(options, "allowed_tools", None) or ())
                or None,
                disallowed_tools=tuple(
                    getattr(options, "disallowed_tools", None) or ()
                ),
                system_prompt=_system_prompt(options),
                include_raw=getattr(options, "include_raw", None) is not False,
                working_directory=getattr(options, "working_directory", None),
                sdk_session_id=supplied_id,
                mcp_servers=servers,
            )
        except InvalidWorkspacePath as bad:
            # 400: the caller named a directory that is not under the workspace
            # root, or does not exist. **Refused rather than ignored** (`PI-30`):
            # this build accepted the field and started every session at the
            # root regardless.
            return problem(400, "invalid-working-directory",
                           "working_directory is not a directory under the "
                           "workspace root", str(bad))
        except RegistryFull as full:
            return problem(429, "max-sessions-reached", "Too many open sessions",
                           str(full))
        return session.record()

    @app.get("/v1/sessions", response_model=SessionList, tags=["sessions"])
    async def list_sessions() -> SessionList:
        """**Answered from our own store, never from the agent** (`PI-09`).

        `--list-sessions` hides sessions that are still resumable and lists ones
        about to be deleted, so it cannot answer this route truthfully.
        """
        return SessionList(sessions=[s.record() for s in registry.list()])

    @app.get("/v1/sessions/{sid}", response_model=SessionRecord,
             tags=["sessions"], responses=_NOT_FOUND)
    async def get_session(sid: str) -> Any:
        try:
            return registry.get(sid).record()
        except UnknownSession:
            return _unknown(sid)

    # `response_class=Response`, because a 204 must not declare a body -- and
    # this route still answers 404 with a problem document, which is a Response
    # returned directly rather than a declared model.
    @app.delete("/v1/sessions/{sid}", status_code=204,
                response_class=Response, tags=["sessions"],
                responses={404: _P, 500: _P})
    async def delete_session(sid: str) -> Response:
        """Close a session. **The transcript survives**, so a resume still works."""
        try:
            registry.close(sid)
        except UnknownSession:
            return _unknown(sid)
        return Response(status_code=204)

    @app.patch("/v1/sessions/{sid}", response_model=SessionRecord,
               tags=["sessions"], responses=_NOT_FOUND)
    async def update_session(sid: str, body: SessionUpdate) -> Any:
        """Change the model or the permission mode mid-session.

        **Omitted fields are never forwarded.** Both are passed to the agent per
        turn — `-m` and `--approval-mode` — so writing a null would mean sending
        the flag with nothing behind it, which is not the same as leaving it
        alone.

        **The read-back is what a caller gets**, so it can see what was actually
        taken rather than what it asked for.
        """
        try:
            session = registry.get(sid)
        except UnknownSession:
            return _unknown(sid)
        supplied = body.model_dump(exclude_unset=True)
        if supplied.get("model") is not None:
            session.model = supplied["model"]
        if supplied.get("permission_mode") is not None:
            session.permission_mode = supplied["permission_mode"]
        return session.record()

    # --- persistence ---------------------------------------------------------
    #
    # **These exist and refuse, rather than not existing.** Every implementation
    # serves the same document (AS-24, AS-31), so a build without a database
    # answers them with a 404 carrying a DISTINCT type -- `persistence-disabled`
    # -- which is a different 404 from "no such session". A client can tell the
    # two apart, which it could not if the route were simply absent.

    def _queries():  # noqa: ANN202
        """Import the read module ONLY once persistence is known to exist.

        A top-level import would defeat the whole lazy arrangement and pull
        SQLAlchemy into every no-database deployment.
        """
        from agent_spec.db import queries

        return queries

    @app.get("/v1/sessions/{sid}/transcript", response_model=TranscriptPage,
             tags=["history"], responses=_NOT_FOUND)
    async def get_transcript(
        sid: str,
        limit: int = Query(200, ge=1, le=1000),
        after: int | None = None,
    ) -> Any:
        """A session's recorded events, oldest first.

        **Reads STORED rows and asks the agent nothing.** Every turn is its own
        process here (`PI-11`), so once a turn has ended there is nothing left to
        ask — this route is the only way to see what happened after the fact,
        and without a database there is no way at all.
        """
        if persistence is None:
            return _persistence_disabled("transcript")
        q = _queries()
        async with persistence.sessionmaker() as db:
            # An explicit existence check, so an unknown id is a 404 rather than
            # an empty page. "No events yet" and "no such session" are different
            # answers and a client acts differently on each.
            if not await q.session_exists(db, sid):
                return _unknown(sid)
            page = await q.transcript(db, sid, limit=limit, after=after)
        return TranscriptPage(session_id=sid, events=page.events,
                              next_after=page.next_after)

    @app.get("/v1/runs/{run_id}", response_model=StoredRun, tags=["history"],
             responses=_NOT_FOUND)
    async def get_run(run_id: str) -> Any:
        """One recorded turn, by the id this service minted for it.

        **`run_id` is neither of the session ids.** It identifies a single turn,
        it is returned by nothing on the live path today, and it is discoverable
        from a transcript row — which is why an unknown one is a plain 404.
        """
        if persistence is None:
            return _persistence_disabled("run")
        q = _queries()
        async with persistence.sessionmaker() as db:
            stored = await q.run(db, run_id)
        if stored is None:
            return problem(
                404, "run-not-found", "No such run",
                f"{run_id} is not a recorded run. A run id identifies one TURN, "
                "and is not a session id of either kind.",
            )
        return StoredRun(**stored)

    # --- turns --------------------------------------------------------------

    @app.post("/v1/sessions/{sid}/messages", response_model=RunResponse,
              tags=["sessions"], responses={**_TURN_ERRORS, **_ID_HEADER})
    async def send_turn(sid: str, body: TurnRequest, response: Response) -> Any:
        """One turn, run to completion.

        **A 409 and never a queue** if a turn is already running: the two callers
        would otherwise receive each other's turns. **A 504 and never a 200 with
        a flag** if the wall clock runs out — the timeout is enforced by killing
        the process, which is the only way to end a turn on this interface
        (`PI-11`) -- the RPC one has a real `abort`.
        """
        try:
            session = registry.get(sid)
        except UnknownSession:
            return _unknown(sid)
        if session.lock.locked():
            return problem(
                409, "session-busy", "A turn is already running",
                "This session is mid-turn. A second concurrent turn is refused "
                "rather than queued, because two callers would otherwise "
                "receive each other's turns.",
            )
        async with session.lock:
            outcome = await _run_turn(settings, session, body.prompt, recorder)
        _stamp_id(response, outcome)
        return outcome

    @app.post("/v1/sessions/{sid}/messages/stream", tags=["sessions"],
              responses={404: _P, 409: _P, **_ID_HEADER})
    async def stream_turn(sid: str, body: TurnRequest) -> Any:
        """One turn, as Server-Sent Events.

        **This route commits LATE, and `/v1/query/stream` commits early.** The
        difference is deliberate and a client must know it: here the first event
        is awaited before the response is committed, so `404`, `409` and a
        first-event failure are real status codes. Only failures from the second
        event onward arrive in-band as `event: error`.

        A healthy stream always ends with `event: done` carrying the same
        `RunResponse` the non-streaming route would have returned.
        """
        try:
            session = registry.get(sid)
        except UnknownSession:
            return _unknown(sid)
        if session.lock.locked():
            return problem(
                409, "session-busy", "A turn is already running",
                "This session is mid-turn. A second concurrent turn is refused "
                "rather than queued.",
            )
        await session.lock.acquire()
        try:
            resuming = bool(session.sdk_session_ids) and session.turns > 0
            session.status = "running"
            session.interrupted = False
            recording = _Recording(recorder, session)
            recording.started(session, body.prompt)
            stream = StreamingTurn(
                _runner_for(settings, session), body.prompt,
                timeout=settings.turn_timeout_s,
                resume=session.sdk_session_id if resuming else None,
                sdk_session_id=(None if resuming
                                else (session.sdk_session_id or str(uuid.uuid4()))),
                cwd=session.cwd,
                process_sink=session.attach_process,
            )
            iterator = stream.__aiter__()
            # **Advance to the first event before committing.** That is what
            # makes a first-event failure a real status code here.
            try:
                first = await anext(iterator)
            except StopAsyncIteration:
                first = None
            if first is None and stream.failure is not None:
                timed_out = isinstance(stream.failure, TurnTimeout)
                session.finish(interrupted=False, timed_out=timed_out)
                # This path returns a STATUS CODE rather than a stream, so
                # `_sse` never runs and would never close the run.
                recording.finished(session, None, interrupted=False,
                                   timed_out=timed_out)
                session.lock.release()
                return _failure_response(stream.failure)
        except BaseException:
            session.lock.release()
            raise
        return StreamingResponse(
            _sse(session, stream, iterator, first, recording),
            media_type="text/event-stream",
            # **The id comes from the event already in hand.** This route
            # declared the header and, until a live turn was driven through it,
            # never sent one -- the exact declared-but-never-written defect this
            # build keeps finding in itself. It is emittable here and only here:
            # the opening event carries the agent's id (`PI-21`) and this route has
            # awaited it before committing, which is the same property that makes
            # its 404 and 409 real status codes. `/v1/query/stream` commits
            # first, knows nothing, and therefore declares no header at all.
            headers=_stream_id_header(first),
        )

    @app.post("/v1/sessions/{sid}/interrupt", response_model=InterruptResult,
              tags=["sessions"], responses=_SESSION_ERRORS)
    async def interrupt_session(sid: str) -> Any:
        """Stop a running turn. **Always 200 with a body**, never 204 or 409.

        A turn can finish between a client deciding to stop it and the request
        arriving, and that race is unavoidable, so "there was nothing to stop"
        is reported in the body rather than as an error.

        **Interrupt here is a kill.** Neither interface registers a cancel verb
        (`PI-11`), so this is abrupt: expect no final event beyond what already
        reached you.
        """
        try:
            session = registry.get(sid)
        except UnknownSession:
            return _unknown(sid)
        return InterruptResult(interrupted=session.kill_turn(), status=session.status)

    # **The document's `paths` in one canonical order, shared by all three
    # builds and by the core.** FastAPI writes them in route-registration order,
    # so without this the JSON key order is whichever order the decorators
    # happened to run in -- and nothing catches it: `freeze` hashes each
    # document against its own copy, the core is a set intersection, and AS-24's
    # check is a dict comparison, which ignores key order. AS-31 makes these
    # documents isomorphic; this is what makes it visible.

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
    # **The build's own answer, in its own document.** Re-applied after
    # FastAPI's generation because that ends in an `exclude_none` encode which
    # would drop every null -- and a null here is a build saying "not measured".
    attach_capabilities_example(app, reference_capabilities().model_dump(mode="json"))

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


def _runner_for(settings: Settings, session: Session) -> PiRunner:
    """One place that builds a runner, so the two turn paths cannot differ.

    **Everything the agent is told is assembled here**, which is the seam a live
    turn caught on another build: an option written at provisioning and read by
    nothing passes both halves' unit tests and applies to no turn.
    """
    return PiRunner(
        binary=settings.pi_binary,
        workspace=session.cwd or session.workspace,
        agent_dir=session.agent_dir,
        session_dir=session.session_dir,
        # **Provider and model travel together** (`PI-10`): a bare id is
        # ambiguous across a thirty-provider catalogue.
        provider=session.provider,
        model=session.model,
        allowed_tools=session.allowed_tools,
        disallowed_tools=session.disallowed_tools,
        system_prompt=session.system_prompt,
        # **Deployment-wide, not per request** (`PI-44`): a caller cannot choose
        # its own gateway, which is the whole point of one.
        provider_gateways=settings.provider_gateways,
        mcp_adapter_path=settings.mcp_adapter_path,
        mcp_servers=session.mcp_servers,
    )


def _failure_response(failure: PiError) -> JSONResponse:
    """One mapping from a failed turn to a status, shared by both turn routes."""
    if isinstance(failure, TurnTimeout):
        return problem(504, "turn-timeout", "The turn exceeded its wall clock",
                       f"{failure.detail} A timeout is mandatory on this target: "
                       "turns can fail to terminate and no cancel verb exists, so "
                       "the process was killed.")
    if isinstance(failure, ResumeTargetMissing):
        return problem(404, "resume-target-not-found",
                       "The conversation could not be resumed", failure.detail)
    if isinstance(failure, CredentialMissing):
        return problem(500, "credential-missing",
                       "The agent has no usable credential", failure.detail)
    return problem(502, "agent-failed", "The agent did not complete the turn",
                   failure.detail)


def _frame(name: str, payload: Any) -> bytes:
    """One SSE frame. `data` is always one line of JSON."""
    body = payload if isinstance(payload, str) else json.dumps(
        payload, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)
    )
    return f"event: {name}\ndata: {body}\n\n".encode()


def _abandoned(session: Session, recording: _Recording | None) -> None:
    """The consumer went away mid-turn. **Kill the agent; never wait for it.**

    **This is a leak fix, and the leak cost money** (`PI-38`). A browser closing a
    tab, sleeping a laptop or dropping wifi closes the SSE generator, which
    raises `GeneratorExit` at its `yield`. `StreamingTurn` kills the process only
    in its wall-clock branch, and that branch is abandoned along with the
    generator -- so nothing killed it, nothing called `finish`, and an agent
    subprocess kept talking to the model on the caller's key with no reader.

    **Killed rather than resumed, and that is the whole design decision.** The
    console is a development tool; a turn nobody is listening to is finished
    work only in the sense that it is billed. Surviving a disconnect would mean
    replacing the interrupt that keeps one turn's output out of the next, which
    buys a dev tool nothing.

    **The SESSION is deliberately left alone** -- not closed, not deleted. A
    disconnect is not a statement that the user is done, and a reload inside
    `session_idle_ttl_s` should find its conversation. The idle reaper already
    reclaims what is genuinely abandoned, and it sweeps on every operation.
    """
    session.kill_turn()
    session.finish(interrupted=True, timed_out=False)
    if recording is not None:
        recording.finished(session, None, interrupted=True, timed_out=False)


async def _sse(session: Session, stream: StreamingTurn, iterator: Any,
               first: dict[str, Any] | None, recording: _Recording | None = None):
    """The frames, from the first event to `done`.

    **A late failure can only arrive in-band**, because the response was
    committed the moment the first event was written -- which is exactly the
    difference this route has from `/v1/query/stream`.
    """
    seq = 0
    #: Whether the TURN reached an end and was accounted for -- not whether the
    #: client received every frame. Set before the final `yield`, so a
    #: disconnect on that last frame does not re-mark a finished turn as
    #: interrupted.
    ended = False
    try:
        for event in ([first] if first is not None else []):
            frame = _agent_event(seq, event).model_dump()
            wire = frame if session.include_raw else {**frame, "raw": None}
            if recording is not None:
                # **Recorded as it is streamed, not collected and written at the
                # end.** A client that disconnects mid-turn, or a turn killed by
                # the wall clock, still leaves the events that did happen.
                recording.event(frame)
            yield _frame("event", wire)
            seq += 1
        async for event in iterator:
            frame = _agent_event(seq, event).model_dump()
            wire = frame if session.include_raw else {**frame, "raw": None}
            if recording is not None:
                recording.event(frame)
            yield _frame("event", wire)
            seq += 1

        if stream.failure is not None:
            timed_out = isinstance(stream.failure, TurnTimeout)
            session.finish(interrupted=session.interrupted, timed_out=timed_out)
            if recording is not None:
                recording.finished(session, None, interrupted=session.interrupted,
                                   timed_out=timed_out)
            ended = True
            yield _frame("error", {"detail": stream.failure.detail,
                                   "exit_code": stream.failure.exit_code})
            return
        result = stream.result
        if result is not None:
            # **Appended only when it is NEW** (`PI-13`), as on the buffered
            # path: the id is the conversation's here, so a resumed turn reports
            # the one it was given.
            if result.sdk_session_id not in session.sdk_session_ids:
                session.sdk_session_ids.append(result.sdk_session_id)
            session.turns += 1
        session.finish(interrupted=False, timed_out=False,
                       cost=result.total_cost_usd if result else None)
        if recording is not None:
            recording.finished(session, result, interrupted=False, timed_out=False)
        ended = True
        yield _frame("done", _turn_response(session, result, interrupted=False).model_dump())
    finally:
        # **The disconnect path** (`PI-38`). `GeneratorExit` lands on a `yield`
        # above when the consumer goes away, and every branch that reached an
        # end has already set `ended` -- so this is reached only by a turn
        # nobody is listening to any more.
        if not ended:
            _abandoned(session, recording)
        # **Released here and nowhere else**: the lock is held across the whole
        # stream, so a client that disconnects mid-turn must not strand it.
        session.lock.release()


async def _sse_oneshot(registry: Registry, session: Session, stream: StreamingTurn,
                       recording: _Recording | None = None):
    """Frames for a one-shot stream. **Everything in-band, including a failure.**

    The response was committed before anything was known, so there is no status
    code left to use — which is exactly why the session route advances to its
    first event first and this one cannot.
    """
    seq = 0
    try:
        async for event in stream:
            frame = _agent_event(seq, event).model_dump()
            wire = frame if session.include_raw else {**frame, "raw": None}
            if recording is not None:
                recording.event(frame)
            yield _frame("event", wire)
            seq += 1
        if stream.failure is not None:
            if recording is not None:
                recording.finished(session, None, interrupted=False,
                                   timed_out=isinstance(stream.failure, TurnTimeout))
            yield _frame("error", {"detail": stream.failure.detail,
                                   "exit_code": stream.failure.exit_code})
            return
        session.turns = 1
        if stream.result is not None:
            session.sdk_session_ids.append(stream.result.sdk_session_id or "")
        if recording is not None:
            recording.finished(session, stream.result, interrupted=False,
                               timed_out=False)
        yield _frame("done", _turn_response(
            session, stream.result, interrupted=False).model_dump())
    finally:
        # **Killed BEFORE the directory goes** (`PI-38`): discarding a directory out
        # from under a live agent leaves it writing into a path that no longer
        # exists, and leaves the process itself running either way.
        session.kill_turn()
        # The directory goes whatever happened, including a disconnect: nothing
        # will ever resume from a one-shot run.
        registry.discard(session)


def _agent_event(seq: int, event: dict[str, Any], *, include_raw: bool = True) -> AgentEvent:
    return AgentEvent(seq=seq, type=_event_type(event), subtype=_subtype(event),
                      content=_content_of(event),
                      # **`include_raw` is honoured here and nowhere else was**
                      # The recorded copy keeps the payload whatever the
                      # caller asked for: history is the operator's, and a
                      # response-shaping option must not delete it from storage.
                      raw=event if include_raw else None)


class _Recording:
    """One turn's rows, so the four turn paths cannot record differently.

    **A run is recorded even when nothing is listening.** With no database the
    recorder is `NULL_RECORDER`, every call below is a no-op, and `run_id` is
    still minted — which is what lets the id exist in a log line whether or not
    anything stored it.

    The two ids are not interchangeable and both are written:

    * `sid` is THIS SERVICE's session id, the stored key, and `None` for a
      one-shot query, which is never registered.
    * `session_id` is the AGENT's, unknown until its opening event and **a new
      value only when the caller supplied one** (`PI-14`), which is why it is
      passed again at the end rather than assumed from the start.
    """

    __slots__ = ("_recorder", "run_id", "_sid")

    def __init__(self, recorder: Any, session: Session) -> None:
        self._recorder = recorder
        self.run_id = str(uuid.uuid4())
        self._sid = session.session_id if session.registered else None

    def started(self, session: Session, prompt: str) -> None:
        self._recorder.start_run(self.run_id, sid=self._sid,
                                 session_id=session.sdk_session_id,
                                 prompt=prompt, at=time.time())

    def event(self, event: dict[str, Any]) -> None:
        self._recorder.append_event(self.run_id, event)

    def events(self, result: TurnResult | None) -> None:
        """Every event of a turn that arrived in one piece.

        The non-streaming path has them all at the end; the streaming path
        records them as they arrive and does not call this.
        """
        for index, raw in enumerate(result.events if result else []):
            self.event(_agent_event(index, raw).model_dump())

    def finished(self, session: Session, result: TurnResult | None, *,
                 interrupted: bool, timed_out: bool) -> None:
        self._recorder.finish_run(
            self.run_id, sid=self._sid, session_id=session.sdk_session_id,
            outcome=(to_run_outcome(result, session.sdk_session_id)
                     if result is not None else None),
            # **A real figure when the turn produced one** (`PI-17`). An
            # interrupted turn is killed before any `turn_end`, so there is
            # nothing to price and `None` is the honest answer -- never 0.0,
            # which would read as free.
            turn_cost_usd=(result.total_cost_usd if result is not None else None),
            interrupted=interrupted, timed_out=timed_out, at=time.time(),
        )


async def _run_turn(settings: Settings, session: Session, prompt: str,
                    recorder: Any = NULL_RECORDER) -> Any:
    """Drive one agent invocation and shape the result.

    **The first turn names an id; every later turn resumes by it** (`PI-13`,
    `PI-14`). `--session` and `--session-id` cannot be combined, so which one is
    passed is decided by whether this session has spoken before.
    """
    runner = _runner_for(settings, session)
    resuming = bool(session.sdk_session_ids) and session.turns > 0
    session.status = "running"
    session.interrupted = False
    recording = _Recording(recorder, session)
    recording.started(session, prompt)
    try:
        result = await runner.run(
            prompt,
            timeout=settings.turn_timeout_s,
            resume=session.sdk_session_id if resuming else None,
            sdk_session_id=(None if resuming
                            else (session.sdk_session_id or str(uuid.uuid4()))),
            cwd=session.cwd,
            process_sink=session.attach_process,
        )
    except TurnTimeout as expired:
        session.finish(interrupted=False, timed_out=True)
        # **`outcome=None` is a real state, not a gap**: the turn reached an end
        # and produced no envelope, which a reader must be able to tell from a
        # turn that finished badly.
        recording.finished(session, None, interrupted=False, timed_out=True)
        return problem(
            504, "turn-timeout", "The turn exceeded its wall clock",
            f"{expired.detail} A timeout is mandatory on this target rather "
            "than defensive: turns can fail to terminate and no cancel verb "
            "exists, so the process was killed.",
        )
    except ResumeTargetMissing as missing:
        session.finish(interrupted=False, timed_out=False)
        # **`outcome=None` is a real state, not a gap**: the turn reached an end
        # and produced no envelope, which a reader must be able to tell from a
        # turn that finished badly.
        recording.finished(session, None, interrupted=False, timed_out=False)
        return problem(404, "resume-target-not-found",
                       "The conversation could not be resumed", missing.detail)
    except CredentialMissing as denied:
        session.finish(interrupted=False, timed_out=False)
        # **`outcome=None` is a real state, not a gap**: the turn reached an end
        # and produced no envelope, which a reader must be able to tell from a
        # turn that finished badly.
        recording.finished(session, None, interrupted=False, timed_out=False)
        return problem(500, "credential-missing",
                       "The agent has no usable credential", denied.detail)
    except PiError as failed:
        # **An interrupt lands here**, because killing the process is how it is
        # done: the run fails rather than returning. `interrupted` is the
        # discriminator, not the status.
        if session.interrupted:
            session.finish(interrupted=True, timed_out=False)
            recording.finished(session, None, interrupted=True, timed_out=False)
            return _turn_response(session, None, interrupted=True)
        session.finish(interrupted=False, timed_out=False)
        recording.finished(session, None, interrupted=False, timed_out=False)
        return problem(502, "agent-failed", "The agent did not complete the turn",
                       failed.detail)

    # **Appended only when it is NEW** (`PI-13`). The id is the conversation's
    # here, so a resumed turn reports the same one it was given -- appending
    # unconditionally would fill the list with duplicates and make
    # `find_by_sdk_id` scan a history of one value repeated.
    if result.sdk_session_id and result.sdk_session_id not in session.sdk_session_ids:
        session.sdk_session_ids.append(result.sdk_session_id)
    session.turns += 1
    session.finish(interrupted=False, timed_out=False,
                   cost=result.total_cost_usd)
    # AFTER the id is appended, so `session.sdk_session_id` is this turn's.
    recording.events(result)
    recording.finished(session, result, interrupted=False, timed_out=False)
    return _turn_response(session, result, interrupted=False)


def _token_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """A `turn_end` usage object mapped to the specification's named counts.

    **Four of the five, and the cache pair is why this build fills more than the
    Gemini one** (`PI-33`). Pi reports `cacheRead` and `cacheWrite` separately,
    so both are real numbers here rather than one conflated figure.

    **`input` EXCLUDES the cached half here** (`PI-33`), where the same sum
    double-counts on the Gemini build. Pi's `input` and `cacheRead` are disjoint
    and `totalTokens` is their sum with `output` -- checked against a measured
    payload, because a consumer aggregating across builds must know which
    convention it has.

    **`reasoning` is present only on some providers** (`PI-34`): openai and
    google carry it on every turn, anthropic only when the model actually
    thought. That is a divergence INSIDE one build, which no other build has,
    and it is why this reads the key rather than assuming it.

    **`.get` degrading to `null`, not raising**: this runs inside a response
    builder that also serves the streaming route, so an upstream rename must
    cost a count rather than fail a turn. The cost is that a wrong key looks
    exactly like an absent one, so the mapping is pinned by a test against a
    measured payload rather than trusted.
    """
    if not usage:
        return TokenUsage()

    def _int(key: str) -> int | None:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return TokenUsage(
        input_tokens=_int("input"),
        output_tokens=_int("output"),
        cache_read_tokens=_int("cacheRead"),
        cache_write_tokens=_int("cacheWrite"),
        reasoning_output_tokens=_int("reasoning"),
    )


def _turn_response(session: Session, result: TurnResult | None, *,
                   interrupted: bool) -> RunResponse:
    """Shape a `RunResponse`. **`total_cost_usd` is REAL here** (`PI-17`)."""
    outcome_recorded = result is not None
    events = [
        AgentEvent(seq=index, type=_event_type(event), subtype=_subtype(event),
                   content=_content_of(event),
                   raw=event if session.include_raw else None)
        for index, event in enumerate(result.events if result else [])
    ]
    return RunResponse(
        # **The conversation's id, stable across turns** (`PI-13`), so a client
        # may key on it here where the Gemini build forbids it.
        session_id=session.sdk_session_id,
        sdk_session_id=session.sdk_session_id,
        outcome_recorded=outcome_recorded,
        result=(result.assistant_text if result else ""),
        is_error=not outcome_recorded,
        interrupted=interrupted,
        stop_kind=derive_stop_kind(
            outcome_recorded=outcome_recorded,
            is_error=not outcome_recorded,
            interrupted=interrupted,
        ),
        num_turns=session.turns,
        # The session's running total and this turn's own figure. Both real,
        # both USD, and the first is the sum of the second over the session.
        total_cost_usd=session.total_cost_usd,
        turn_cost_usd=(result.total_cost_usd if result else None),
        # **Zero, and it is an absence rather than a measurement** (`PI-37`).
        # Pi times nothing: its events carry timestamps but no turn duration,
        # and wall clock measured out here would include process spawn, which is
        # this service's cost and not the model's.
        duration_ms=0,
        usage=(result.usage if result else None),
        token_usage=_token_usage(result.usage if result else None),
        # **Per turn, not cumulative** (`PI-16`), the opposite of the Claude
        # build: summing these across turns is correct here.
        model_usage=(result.models_used if result else None),
        events=events,
    )


#: Pi's own event names mapped onto the vocabulary the specification closes
#: (`PI-35`). **`tool_execution_*` becomes `assistant`**, which is the
#: established answer rather than a shortcut: the enum has no `tool` member
#: because the Claude SDK delivers tool use *inside* assistant messages, and two
#: other builds reached the same place independently. Inventing a member would
#: change a closed enum in the shared document for one build's convenience.
#:
#: **A consumer that wants the distinction reads `subtype`**, which is exactly
#: what it is for, and `raw` carries the whole payload for anything this mapping
#: did not anticipate.
#:
#: **`agent_end` is the result frame and `agent_settled` is not**, which is the
#: opposite of what the names suggest: `agent_end` carries the finished message
#: list and `agent_settled` is a bare marker after it.
_EVENT_TYPES: dict[str, str] = {
    "session": "system",
    "agent_start": "system",
    "agent_settled": "system",
    "turn_start": "system",
    "queue_update": "system",
    "session_info_changed": "system",
    "compaction_start": "system",
    "compaction_end": "system",
    "message_update": "assistant",
    "tool_execution_start": "assistant",
    "tool_execution_update": "assistant",
    "tool_execution_end": "assistant",
    "turn_end": "assistant",
    "agent_end": "result",
}


def _event_type(event: dict[str, Any]) -> str:
    """Normalised type. **Never a value outside the closed set.**"""
    raw = str(event.get("type", ""))
    if raw in {"message_start", "message_end"}:
        # Pi puts the speaker in `message.role`, and the enum has a member for
        # each; a message with neither is `unknown` rather than a guess.
        role = str((event.get("message") or {}).get("role", ""))
        return role if role in {"assistant", "user"} else "unknown"
    return _EVENT_TYPES.get(raw, "unknown")


def _subtype(event: dict[str, Any]) -> str | None:
    """What `type` had to drop: the tool's name, or the agent's own event name."""
    raw = str(event.get("type", ""))
    if raw.startswith("tool_execution") and event.get("toolName"):
        return f"{raw}:{event['toolName']}"
    if raw == "message_update":
        # The delta kind -- `text_delta`, `thinking_delta`, `toolcall_delta` --
        # which is the only thing separating one update frame from another.
        inner = (event.get("assistantMessageEvent") or {}).get("type")
        return f"{raw}:{inner}" if inner else raw
    return raw or None


def _content_of(event: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Content BLOCKS, which is the shape the specification uses.

    **Pi already speaks in blocks** (`PI-35`), which is why this mapping is
    thinner than the other builds': a `turn_end` message carries a list of
    `{"type": "text"|"thinking", ...}` objects to pass through rather than a
    bare string to convert.

    **A tool result carries real text here** (`PI-36`), unlike the Gemini target
    where every work tool reports an empty output. Pi's `tool_execution_end`
    carries the tool's own content list -- measured: `"Successfully wrote to
    hello.txt"` -- so a client rendering tool output gets something.
    """
    kind = event.get("type")
    if kind in {"message_start", "message_end", "turn_end"}:
        content = (event.get("message") or {}).get("content")
        return content if isinstance(content, list) and content else None
    if kind == "message_update":
        inner = event.get("assistantMessageEvent") or {}
        if inner.get("type") == "text_delta":
            return [{"type": "text", "text": str(inner.get("delta", ""))}]
        return None
    if kind == "tool_execution_start":
        return [{
            "type": "tool_use",
            "name": event.get("toolName"),
            "id": event.get("toolCallId"),
            "input": event.get("args"),
        }]
    if kind == "tool_execution_end":
        return [{
            "type": "tool_result",
            "tool_use_id": event.get("toolCallId"),
            "status": "error" if event.get("isError") else "ok",
            "content": (event.get("result") or {}).get("content"),
        }]
    return None


def _stamp_id(response: Response, outcome: Any) -> None:
    """Echo the agent's id as a header, when there is one.

    **Absent rather than empty** when a turn produced no id at all: a header
    carrying `""` is a value a client could act on, and there is nothing to act
    on. Declared AND set -- a header nothing writes is the shape of a capability
    nothing enforces, which is a defect this repository keeps finding.

    **It identifies the CONVERSATION** (`PI-13`), measured across two
    processes on three providers: a resumed session answers to the same id. A
    relay may key on it here, where on the Gemini build it may only route.
    """
    sdk_id = getattr(outcome, "sdk_session_id", None)
    if sdk_id:
        response.headers[SDK_SESSION_HEADER] = sdk_id


def _stream_id_header(first: dict[str, Any] | None) -> dict[str, str]:
    """The same header for a stream, taken from the opening event.

    **Absent rather than empty**, on the same reasoning as `_stamp_id`. A turn
    that failed before its first event has no id and gets no header, and a client
    reading the stream still learns the id from the `session` event itself -- the
    header is a convenience for a relay that routes without parsing the body.

    **The opening event is `session` and its field is `id`** (`PI-21`), not the
    `session_id` a differently-shaped agent reports. It arrives before the first
    model call, so this header is present on every stream that started at all.
    """
    sdk_id = (first or {}).get("id")
    return {SDK_SESSION_HEADER: str(sdk_id)} if sdk_id else {}


def _persistence_disabled(what: str) -> JSONResponse:
    """A 404 that says WHY, so it is not read as "no such session".

    **The route exists and refuses**, rather than being absent: every
    implementation serves the same document (AS-24, AS-31), so a build without a
    database answers with a DISTINCT `type` a client can branch on. An absent
    route would be indistinguishable from a missing session.
    """
    return problem(
        404, "persistence-disabled", f"No stored {what}",
        "This deployment has no database configured -- set "
        "AGENT_SERVICE_DATABASE_URL to record anything -- so there is no stored "
        "history to read. This is a DIFFERENT 404 from an unknown session: "
        "branch on `type`, not on the status.",
    )


def _unknown(session_id: str) -> JSONResponse:
    return problem(
        404, "session-not-found", "No such session",
        f"{session_id} is not an open session on this instance. Note that a "
        "turn's sdk_session_id is the AGENT's conversation id and is not a "
        "path handle: feeding one here is a 404.",
    )


def problem(status: int, kind: str, title: str, detail: str) -> JSONResponse:
    """An RFC 7807 response with a named `type`.

    **A distinct `type` per meaning**, because two errors sharing a status and
    meaning different things cannot be told apart by a client otherwise.
    """
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}/{kind}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    return JSONResponse(
        status_code=status, content=body, media_type="application/problem+json"
    )
