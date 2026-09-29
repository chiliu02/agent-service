"""Exceptions -> RFC 7807 problem documents.

**SDK-coupled, and therefore never shareable.** This is one of the two modules
`impl/common/` must not hold — it names Codex's exception hierarchy, and the
Claude build's equivalent names a different one entirely. The *shape* it
produces is the specification's; the mapping is not.

## AS-21

> Errors are RFC 7807 documents with `content-type: application/problem+json`.

That is a clause about **every** error, including the ones a framework produces
on its own — a 404 for an unknown path, a 422 from request validation. Wiring it
for handled exceptions only is the easy half and leaves the clause false, which
is how `codex-python` failed the conformance suite on 2026-08-08.

## What is deliberately NOT here

**No `detail` from the exception's own message by default.** A JSON-RPC error
from the app-server can carry a path, a command line or a model's text, and this
service is unauthenticated by default. The class name is safe; the message is
not, so it is used only where the class is one this module chose.
"""

from __future__ import annotations

from agent_spec.openapi.schemas import Problem
from openai_codex import (
    CodexError,
    InvalidParamsError,
    InvalidRequestError,
    RetryLimitExceededError,
    ServerBusyError,
    TransportClosedError,
)

#: The title used when nothing matched. **Distinctive on purpose**: it is what
#: an operator greps for, and its presence in a log means this table has a gap
#: rather than that the service misbehaved.
UNCLASSIFIED_TITLE = "Unhandled error"

#: Exception -> (status, title). Ordered most-specific first, because
#: `RetryLimitExceededError` is a `ServerBusyError` and the first match wins.
_TABLE: tuple[tuple[type[BaseException], int, str], ...] = (
    # The caller asked for something the app-server rejected -- a bad thread id,
    # a malformed parameter. Their fault, so 4xx.
    (InvalidParamsError, 400, "Invalid request"),
    (InvalidRequestError, 400, "Invalid request"),
    # Retries already happened inside the SDK and still failed. 503 with a
    # meaning: try later, the request itself was fine.
    (RetryLimitExceededError, 503, "Upstream busy"),
    (ServerBusyError, 503, "Upstream busy"),
    # The app-server subprocess died. NOT the caller's fault and NOT retryable
    # by them at this instant -- the session is gone.
    (TransportClosedError, 502, "Agent runtime unavailable"),
    # Anything else the SDK defines.
    (CodexError, 500, "Agent runtime error"),
)


#: The problem `type`s this service sets. Telling two 404s apart -- "history
#: is off" from "no such session" -- is the first place where the difference
#: changes what a caller should do, and a client should not have to string-match
#: on prose to find it. The URIs are the specification's, verbatim.
PERSISTENCE_DISABLED_TYPE = "https://agent-service.invalid/problems/persistence-disabled"

#: **A status code plus prose means matching a sentence, and the sentence is the
#: part that is allowed to change** (CX-43).
#:
#: `POST /v1/sessions` can answer 400 for several reasons on this build -- a
#: limit above its cap, an option it cannot honour, request validation -- and
#: this is the one a caller acts on differently: it means *stop supplying the
#: id*, not *fix the value*.
SDK_SESSION_ID_UNSUPPORTED_TYPE = (
    "https://agent-service.invalid/problems/sdk-session-id-unsupported"
)

#: The same argument applied to the refusal 0.19.0 added. A caller reads
#: `capabilities.unsupported_options` and never needs this -- but a caller that
#: did not read it gets one machine-readable answer instead of a sentence.
UNSUPPORTED_OPTIONS_TYPE = "https://agent-service.invalid/problems/unsupported-options"

#: The third, and it came from a measurement rather than a request
#: (CX-18). Destroy `CODEX_HOME` and a
#: resume that worked a minute earlier answers 400 `InvalidRequestError` -- the
#: right status, and indistinguishable from a malformed body.
#:
#: **"The conversation is gone" is acted on differently from "your request is
#: wrong":** the first says stop retrying this id and start a new session, the
#: second says fix the body. Same argument Agent Studio made for the supplied-id
#: refusal, applied to a refusal nobody asked about.
RESUME_TARGET_NOT_FOUND_TYPE = (
    "https://agent-service.invalid/problems/resume-target-not-found"
)

#: The container is out of process slots. Distinct from `max_sessions`, which is
#: a number this service enforces -- this is the thing underneath it running out,
#: and the two are configured independently. See `SessionCapacityExhausted`.
SESSION_CAPACITY_TYPE = (
    "https://agent-service.invalid/problems/session-capacity-exhausted"
)


class PersistenceDisabled(RuntimeError):
    """A history route was called on a service with no database configured."""


class RunNotFound(KeyError):
    """No stored run with that id."""


def _service_problem(exc: BaseException) -> Problem | None:
    """The service's OWN exceptions -- the half of this module that is not
    SDK-coupled and would survive an extraction to `impl/common/`.

    **Imported inside the function on purpose.** `registry` imports `sessions`,
    and a module-level import here would close the cycle
    `errors -> registry -> sessions`. By the time any exception reaches this
    function every module involved is fully initialized, so deferring costs
    nothing and keeps each module importable standalone.
    """
    from agent_service.options import (
        InvalidWorkspacePath,
        LimitExceeded,
        PermissionModeUnsupported,
        McpServersNotAllowed,
        McpUnsupported,
        SettingSourceUnsupported,
        UnsupportedOptions,
    )
    from agent_service.registry import (
        SdkSessionIdUnsupported,
        SessionBusy,
        SessionClosed,
        SessionLimitReached,
        SessionNotFound,
        SessionOpenTimeout,
    )
    from agent_service.sessions import (
        ResumeTargetNotFound,
        RunTimeout,
        SessionCapacityExhausted,
    )

    # **BEFORE `SessionOpenTimeout` and before anything matching `TimeoutError`
    # generically.** `RunTimeout` is a `TimeoutError`, deliberately, so a branch
    # ordered after a broader timeout check would never be reached -- the same
    # first-match-wins hazard `_TABLE` documents for `RetryLimitExceededError`.
    if isinstance(exc, RunTimeout):
        # 504, matching the Claude build: the turn budget this service set
        # expired. NOT a 500 -- nothing failed, a deadline passed, and the
        # distinction is what tells a caller to retry with a longer `timeout_s`
        # rather than to report a broken service.
        return Problem(title="Run timed out", status=504, detail=_detail(exc))
    if isinstance(exc, SessionCapacityExhausted):
        # 503, not 429: a 429 says the CALLER asked for too much, which is what
        # `max_sessions` means. This says the deployment is out of room, it is
        # nobody's fault, and closing a session clears it.
        return Problem(type=SESSION_CAPACITY_TYPE,
                       title="No capacity to start another session", status=503,
                       detail=_detail(exc))
    if isinstance(exc, ResumeTargetNotFound):
        return Problem(type=RESUME_TARGET_NOT_FOUND_TYPE,
                       title="No such conversation to resume", status=400,
                       detail=_detail(exc))
    if isinstance(exc, PermissionModeUnsupported):
        # Same URI as every other "you sent something this build cannot
        # honour": the caller's remedy is in the request, and
        # `capabilities.permission_modes` names what to send instead.
        return Problem(type=UNSUPPORTED_OPTIONS_TYPE,
                       title="Requested options are not supported", status=400,
                       detail=_detail(exc))
    if isinstance(exc, (McpServersNotAllowed, McpUnsupported, SettingSourceUnsupported)):
        # **The same URI as `UnsupportedOptions` and the Claude build's MCP
        # refusal**, because it is the same condition to a client: you sent
        # something this deployment cannot honour, and the remedy is in the
        # request. The `detail` says which server and why.
        return Problem(type=UNSUPPORTED_OPTIONS_TYPE,
                       title="Requested options are not supported", status=400,
                       detail=_detail(exc))
    if isinstance(exc, UnsupportedOptions):
        # 400, and the same reasoning as `SdkSessionIdUnsupported` below: the
        # ROUTE is implemented, particular fields are not, and the caller fixes
        # it by omitting them. The message names them, and
        # `capabilities.unsupported_options` names them before the request.
        return Problem(type=UNSUPPORTED_OPTIONS_TYPE,
                       title="Requested options are not supported", status=400,
                       detail=_detail(exc))
    if isinstance(exc, InvalidWorkspacePath):
        # 400: `working_directory` did not name a directory under the workspace
        # root. **Refused rather than concatenated** (CX-64) -- the message names
        # the field and says what is wrong with the value, because the caller is
        # the only one who can fix it.
        return Problem(title="working_directory is not a directory under the "
                             "workspace root",
                       status=400, detail=_detail(exc))
    if isinstance(exc, LimitExceeded):
        # 400: the request asked for more than this deployment allows, and the
        # remedy is in the caller's hands. The message names the capability field
        # to read rather than the number alone.
        return Problem(title="Requested limit exceeds this deployment's cap",
                       status=400, detail=_detail(exc))
    if isinstance(exc, PersistenceDisabled):
        return Problem(
            type=PERSISTENCE_DISABLED_TYPE,
            title="History is not available",
            status=404,
            detail=(
                "This service has no database configured, so no run or session "
                "history is stored. Set AGENT_SERVICE_DATABASE_URL to enable it."
            ),
        )
    if isinstance(exc, SdkSessionIdUnsupported):
        # 400, not 501. The ROUTE is implemented; it is this one field that
        # cannot be honoured, and the caller fixes it by omitting the field --
        # which is a request problem, not a missing feature.
        return Problem(type=SDK_SESSION_ID_UNSUPPORTED_TYPE,
                       title="Supplied SDK session id is not supported", status=400,
                       detail=_detail(exc))
    if isinstance(exc, SessionNotFound):
        # A SENTENCE, not the bare id: `SessionNotFound(sid)` alone would render
        # as `detail: "834bd..."`, which tells a client nothing about what the
        # id it is being shown means.
        return Problem(
            title="Session not found",
            status=404,
            detail=f"No session with id {_detail(exc)}; it may have been closed or reaped",
        )
    if isinstance(exc, RunNotFound):
        return Problem(title="Run not found", status=404,
                       detail=f"No stored run with id {_detail(exc)}")
    if isinstance(exc, SessionLimitReached):
        return Problem(title="Too many sessions", status=429, detail=_detail(exc))
    if isinstance(exc, SessionOpenTimeout):
        # A time budget THIS SERVICE set expiring, not a failure to open --
        # 504 rather than 502, the same bucket a turn timeout falls in.
        return Problem(title="Session failed to open in time", status=504, detail=_detail(exc))
    if isinstance(exc, SessionBusy):
        return Problem(title="Session busy", status=409, detail=_detail(exc))
    if isinstance(exc, SessionClosed):
        # Same status as SessionBusy, deliberately. `title` is therefore the
        # ONLY thing separating "retry shortly" from "open a new session" -- two
        # conditions with opposite remedies.
        return Problem(title="Session closed", status=409, detail=_detail(exc))
    return None


def _detail(exc: BaseException) -> str:
    """The message of an exception THIS MODULE'S OWN CODE raised.

    Safe precisely because the type was matched first: every caller above names
    a class this service defines and whose message it wrote. The SDK's messages
    get no such treatment -- see the module docstring.
    """
    return str(exc) or type(exc).__name__


def to_problem(exc: BaseException) -> Problem:
    """An RFC 7807 document for any exception. Never raises, never leaks.

    An unmatched exception becomes a 500 titled `UNCLASSIFIED_TITLE` rather than
    propagating: a handler that raises while reporting an error turns one
    failure into two, and the caller gets neither.
    """
    service = _service_problem(exc)
    if service is not None:
        return service
    for kind, status, title in _TABLE:
        if isinstance(exc, kind):
            return Problem(
                type="about:blank",
                title=title,
                status=status,
                # The class name only. See the module docstring: the message may
                # carry a path, a command line or model output.
                detail=type(exc).__name__,
            )
    return Problem(
        type="about:blank",
        title=UNCLASSIFIED_TITLE,
        status=500,
        detail=type(exc).__name__,
    )
