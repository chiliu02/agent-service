"""Map exceptions to RFC 7807 problem documents.

Note what is NOT an error here: a ResultMessage with is_error=True is a
successful run whose agent reported failure. It returns 200 with is_error in the
body. Conflating the two makes agent-level failure indistinguishable from
transport failure.
"""

from __future__ import annotations

from claude_agent_sdk import (
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
)

from agent_service.options import (
    InvalidSessionId,
    InvalidWorkspacePath,
    LimitExceeded,
    PermissionModeUnsupported,
    McpServersNotAllowedError,
)
from agent_spec.openapi.schemas import Problem

#: **A problem `type` a client can branch on instead of matching a sentence**,
#: which is Agent Studio's argument for wanting one and is the better statement
#: of why: a status code plus prose means matching prose, and the prose is the
#: part that is allowed to change.
#:
#: This build reaches it by one route only -- an operator forbidding MCP -- but
#: the URI names the *condition*, not the field or the build. The Codex build
#: sets the same one for the six options it cannot honour, and both publish the
#: names in `capabilities.unsupported_options` so the refusal is readable before
#: it is hit.
UNSUPPORTED_OPTIONS_TYPE = "https://agent-service.invalid/problems/unsupported-options"


class RunTimeout(Exception):
    """The run exceeded its wall-clock budget."""


class RunNotFound(KeyError):
    """No stored run with that id.

    A KeyError subclass to match `SessionNotFound`, so `_detail`'s
    KeyError-repr handling applies to it too -- without that, the detail of
    every 404 here would carry stray quotes around the id.
    """


class PersistenceDisabled(Exception):
    """A history route was called on a service with no database configured.

    A 404, because the resource genuinely does not exist here -- but with a
    DISTINCT `type` and title from "no such session", because the two need
    different actions from a client. "Session not found" means try another id;
    this means the operator never turned history on, and no id will work.
    Answering with an empty list instead would be worse than either: it reads
    as "this session had no events".
    """


# The title `to_problem` puts on the ONE branch that means "this service does
# not know what this exception is" -- its fallthrough. Named, and read from
# here by api.py, so that "unclassified" is decided in exactly one place
# instead of api.py re-walking the isinstance chain below and drifting from it.
# api.py logs this case, and ONLY this case, at ERROR with a traceback.
UNCLASSIFIED_TITLE = "Internal server error"


def _detail(exc: BaseException) -> str:
    """`str(exc)`, except for `KeyError`, whose `str()` is its REPR.

    `KeyError.__str__` returns `repr(args[0])`, NOT the message: `SessionNotFound`
    subclasses KeyError, so `str(SessionNotFound("834bd..."))` is `"'834bd...'"`
    -- stray single quotes and all -- and that repr went out as the `detail` of
    every 404 from `GET /v1/sessions/{sid}`. Anything else deriving from
    KeyError reads the same way, which is why this is applied at EVERY
    `detail=` site rather than only the 404.
    Pinned by tests/test_errors.py::test_no_problem_detail_carries_a_python_repr.

    It is no longer reachable from the fallthrough 500, which stopped echoing
    exception messages entirely -- see the comment at the end of `to_problem`.
    That removes one caller, not the rule: every branch above still formats an
    exception this service chose to classify.
    """
    if isinstance(exc, KeyError):
        return ", ".join(str(arg) for arg in exc.args)
    return str(exc)


def to_problem(exc: BaseException) -> Problem:
    # Imported INSIDE the function, not at module scope. `registry.py` ->
    # `sessions.py` -> `runner.py` all import `RunTimeout` from this module, so
    # this module and those two form an import cycle. Importing them at the
    # bottom of this file (where these lines used to live, after `RunTimeout`
    # is defined) is not enough: it only works when `errors` happens to be
    # imported FIRST. Entered from the other side -- `import
    # agent_service.registry` or `import agent_service.sessions` as the first
    # `agent_service` import in a fresh interpreter -- `registry` begins
    # executing, reaches `from agent_service.sessions import AgentSession`,
    # `sessions` reaches `from agent_service.errors import RunTimeout`, and
    # this module then tried to import names back out of the still-executing
    # `registry`/`sessions`, raising `ImportError: cannot import name ... from
    # partially initialized module`. The test suite masked it by importing
    # `errors`/`registry` before `sessions` in every path.
    #
    # Deferring to call time breaks the cycle outright: by the time any
    # exception reaches this function, every module involved is fully
    # initialized. Both `import agent_service.registry` and `import
    # agent_service.sessions` now succeed in a fresh interpreter (pinned by
    # tests/test_errors.py::test_each_module_imports_standalone_in_a_fresh_interpreter).
    from agent_service.registry import SessionLimitReached, SessionNotFound, SessionOpenTimeout
    from agent_service.sessions import InterruptTimeout, SessionBusy, SessionClosed

    if isinstance(exc, PermissionModeUnsupported):
        # The caller's remedy is in the request, and
        # `capabilities.permission_modes` names what to send instead.
        return Problem(
            title="Requested options are not supported",
            status=400,
            detail=str(exc),
        )
    if isinstance(exc, LimitExceeded):
        return Problem(
            title="Requested limit exceeds the maximum allowed",
            status=400,
            detail=f"{exc.field}={exc.value} exceeds the maximum allowed value of {exc.cap}",
        )
    if isinstance(exc, InvalidWorkspacePath):
        return Problem(title="Invalid workspace path", status=400, detail=_detail(exc))
    if isinstance(exc, InvalidSessionId):
        return Problem(title="Invalid session id", status=400, detail=_detail(exc))
    if isinstance(exc, McpServersNotAllowedError):
        return Problem(
            # **The same URI the Codex build sets for the same condition**, and
            # that is the point of having one: "you sent an option this
            # deployment cannot honour" is one thing to a client, whichever
            # build answers and whichever field it was. `mcp_servers` appears in
            # `capabilities.unsupported_options` in exactly this state, so the
            # 400 and the capability name the same fact.
            type=UNSUPPORTED_OPTIONS_TYPE,
            title="MCP servers are not allowed",
            status=400,
            detail=_detail(exc),
        )
    if isinstance(exc, RunTimeout):
        return Problem(title="Run timed out", status=504, detail=_detail(exc))
    if isinstance(exc, PersistenceDisabled):
        return Problem(
            # The one place in this module that sets a non-default `type`.
            # Distinguishing by title alone would make a client string-match on
            # prose; this route is the first where telling two 404s apart
            # changes what the caller should do.
            type="https://agent-service.invalid/problems/persistence-disabled",
            title="History is not available",
            status=404,
            detail=(
                "This service has no database configured, so no run or session "
                "history is stored. Set AGENT_SERVICE_DATABASE_URL to enable it."
            ),
        )
    if isinstance(exc, CLINotFoundError):
        return Problem(
            title="Agent CLI not available",
            status=500,
            detail=f"The bundled Claude Code binary could not be started: {_detail(exc)}",
        )
    if isinstance(exc, CLIJSONDecodeError):
        return Problem(
            title="Malformed message from the agent process", status=502, detail=_detail(exc)
        )
    if isinstance(exc, (ProcessError, CLIConnectionError)):
        return Problem(title="Agent process failed", status=502, detail=_detail(exc))
    if isinstance(exc, SessionNotFound):
        # A SENTENCE, not the bare id. `registry.get()` raises
        # `SessionNotFound(sid)` and nothing else, so `_detail` yields the id
        # alone -- which read as `detail: "'834bd...'"` before `_detail`
        # existed and would read as `detail: "834bd..."` after it, neither of
        # which tells a client what the id it is being shown means. Pinned by
        # tests/test_errors.py::test_session_not_found_detail_is_a_sentence_naming_the_id.
        return Problem(
            title="Session not found",
            status=404,
            detail=f"No session with id {_detail(exc)}; it may have been closed or reaped",
        )
    if isinstance(exc, RunNotFound):
        return Problem(
            title="Run not found",
            status=404,
            detail=f"No stored run with id {_detail(exc)}",
        )
    if isinstance(exc, SessionLimitReached):
        return Problem(title="Too many sessions", status=429, detail=_detail(exc))
    if isinstance(exc, SessionOpenTimeout):
        # Same bucket as RunTimeout: the operation exceeded a time budget
        # (registry.py's open_timeout_s) rather than failing outright.
        return Problem(title="Session failed to open in time", status=504, detail=_detail(exc))
    if isinstance(exc, InterruptTimeout):
        # Third member of that same bucket: a control request the session
        # bounded ITSELF (sessions.py's _STALE_INTERRUPT_BUDGET_S), as opposed
        # to one that could not be delivered at all -- that is the 502 above.
        # Typed rather than left as the bare `TimeoutError` `asyncio.timeout`
        # raises, which fell through to the 500 at the bottom with an EMPTY
        # detail (`str(TimeoutError())` is `''`), losing the only diagnostic
        # the response carried, and answered a time-budget overrun with a
        # status this module gives to nothing else of the kind.
        return Problem(title="Interrupt was not answered in time", status=504, detail=_detail(exc))
    if isinstance(exc, SessionBusy):
        return Problem(title="Session busy", status=409, detail=_detail(exc))
    if isinstance(exc, SessionClosed):
        # Same status as SessionBusy above, deliberately: both are 409. `title`
        # is therefore the ONLY thing distinguishing "a turn is already
        # running, retry shortly" from "this session is over, open a new one"
        # -- two conditions with opposite client remedies. Pinned by
        # tests/test_errors.py::test_the_two_409s_are_distinguished_by_title.
        return Problem(title="Session closed", status=409, detail=_detail(exc))
    # THE FALLTHROUGH: nothing above matched, so this service does not know
    # what this exception is. `UNCLASSIFIED_TITLE` is how api.py recognises
    # that -- and it is the only case api.py logs at ERROR with a traceback.
    #
    # IT DOES NOT ECHO `str(exc)`, and that is the whole point of this branch
    # being different from every branch above it. Each of those names a type
    # this service chose to classify, so its message was read and judged before
    # being handed to a client. Here, by construction, the type is unknown --
    # so the message is unknown, and an unknown message cannot be judged safe.
    #
    # MEASURED, 2026-08-06, which is why this changed: a service pointed at a
    # database with no tables answered `GET /v1/sessions/{sid}/transcript` with
    #
    #   500 {"detail": "(sqlalchemy...ProgrammingError) <class
    #    'asyncpg.exceptions.UndefinedTableError'>: relation \"sessions\" does
    #    not exist\n[SQL: SELECT sessions.id FROM sessions WHERE
    #    sessions.id = $1::VARCHAR]\n[parameters: ('7d177d9b...',)]"}
    #
    # -- the query, the schema and a parameter value, on an API with no
    # authentication at all. Nothing about that was specific to SQLAlchemy;
    # ANY unclassified exception's message went out the same way, and the next
    # one to arrive is by definition one nobody has looked at.
    #
    # The class NAME stays, and only the name. api.py's `_problem` already
    # draws exactly this line for the log -- "the exception CLASS NAME --
    # never `str(exc)`" -- so this is that existing rule applied to the
    # response body rather than a new judgement. It is what lets an operator
    # match a report against the ERROR line that carries the full traceback,
    # and it is the one thing a caller can usefully quote under specification C-4.
    return Problem(
        title=UNCLASSIFIED_TITLE,
        status=500,
        detail=(
            f"An unhandled {type(exc).__name__} reached the API boundary. Its "
            "message and traceback are in this service's log, at ERROR, and are "
            "deliberately not repeated here: an exception this service does not "
            "classify is one whose message it cannot vouch for."
        ),
    )
