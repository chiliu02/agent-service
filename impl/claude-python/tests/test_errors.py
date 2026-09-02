from claude_agent_sdk import CLIJSONDecodeError, CLINotFoundError, ProcessError

from agent_service.errors import RunTimeout, to_problem
from agent_service.options import InvalidWorkspacePath, LimitExceeded


def test_limit_exceeded_is_400_and_names_the_field() -> None:
    problem = to_problem(LimitExceeded("max_turns", 9999, 200))
    assert problem.status == 400
    assert "max_turns" in problem.detail


def test_invalid_workspace_path_is_400() -> None:
    assert to_problem(InvalidWorkspacePath("nope")).status == 400


def test_cli_not_found_is_500() -> None:
    assert to_problem(CLINotFoundError("missing")).status == 500


def test_process_error_is_502() -> None:
    assert to_problem(ProcessError("boom", exit_code=1)).status == 502


def test_json_decode_error_is_502() -> None:
    assert to_problem(CLIJSONDecodeError("bad", ValueError("x"))).status == 502


def test_timeout_is_504() -> None:
    assert to_problem(RunTimeout("too slow")).status == 504


def test_unknown_exception_is_500() -> None:
    problem = to_problem(RuntimeError("unexpected"))
    assert problem.status == 500
    assert problem.title


def test_session_not_found_is_404() -> None:
    from agent_service.registry import SessionNotFound

    assert to_problem(SessionNotFound("s")).status == 404


def test_session_not_found_detail_is_a_sentence_naming_the_id() -> None:
    """`SessionNotFound` subclasses `KeyError`, and `KeyError.__str__` returns
    `repr(args[0])` -- NOT the message. `detail=str(exc)` therefore put a
    PYTHON REPR on the wire: the acceptance run's 404 read
    `detail: "'834bd...'"`, stray single quotes and all.

    Two things are pinned, and both were broken. The detail must carry the id
    WITHOUT the repr quoting, and it must be a sentence -- an id on its own
    tells a client nothing about what it is being shown or why.
    """
    from agent_service.registry import SessionNotFound

    problem = to_problem(SessionNotFound("834bd0f1"))

    assert problem.status == 404
    assert "834bd0f1" in problem.detail
    assert "'" not in problem.detail, f"a Python repr reached the wire: {problem.detail!r}"
    assert problem.detail != "834bd0f1", "the bare id is not a sentence"
    assert problem.detail.startswith("No session with id ")


def test_no_problem_detail_carries_a_python_repr() -> None:
    """The same `KeyError.__str__` trap applies to ANY exception deriving from
    KeyError, which is why `_detail` is applied at every `detail=` site and not
    only at the one 404 that first hit it.

    `RunNotFound` is the case still exercised from this end: it is a KeyError
    subclass, it is classified, and its detail interpolates the id. A bare
    `KeyError` no longer reaches a `_detail` call at all -- the fallthrough
    stopped formatting exceptions on 2026-08-06 -- so the guard is asserted
    where it is still load-bearing rather than through a path that no longer
    exists.
    """
    from agent_service.errors import RunNotFound

    problem = to_problem(RunNotFound("some-missing-key"))

    assert problem.status == 404
    assert "some-missing-key" in problem.detail
    assert "'" not in problem.detail, f"a Python repr reached the wire: {problem.detail!r}"


def test_the_fallthrough_500_never_echoes_the_exception_message() -> None:
    """An exception this service does not classify is one whose message it has
    never read, on an API with no authentication.

    The concrete leak this was written for, measured 2026-08-06: a service
    pointed at a database with no tables answered
    `GET /v1/sessions/{sid}/transcript` with the failing SQL, the schema and a
    bound parameter in `detail`. Nothing about that was SQLAlchemy-specific --
    every unclassified exception went out the same way.

    The class NAME is kept deliberately: `api.py` already logs the class name
    and never `str(exc)`, so this is that same line applied to the response
    body, and it is what lets a bug report be matched to the ERROR line holding
    the traceback.
    """
    secret = "relation \"sessions\" does not exist [SQL: SELECT sessions.id]"

    problem = to_problem(RuntimeError(secret))

    assert problem.status == 500
    assert secret not in problem.detail
    assert "sessions" not in problem.detail
    assert "RuntimeError" in problem.detail

    # A subclass carrying a message in an attribute rather than args must not
    # find a way through either -- nothing is formatted from the exception but
    # its type.
    class _Chatty(RuntimeError):
        def __str__(self) -> str:
            return secret

    assert secret not in to_problem(_Chatty()).detail


def test_the_unclassified_title_is_the_one_the_api_logs_on() -> None:
    """api.py decides "we do not know what this is" -- the ONE case it logs at
    ERROR with a traceback -- by comparing the problem's title against
    `UNCLASSIFIED_TITLE`. If the fallthrough stopped using that constant the
    check would silently never fire again and the 500 would go back to being
    invisible, which is precisely the defect. Pinned from this end so the two
    modules cannot drift apart in silence.
    """
    from agent_service.errors import UNCLASSIFIED_TITLE

    assert to_problem(RuntimeError("who knows")).title == UNCLASSIFIED_TITLE
    # And a classified one does NOT wear it, or the check would fire on
    # everything and ERROR would stop meaning anything.
    assert to_problem(RunTimeout("too slow")).title != UNCLASSIFIED_TITLE


def test_session_limit_is_429() -> None:
    from agent_service.registry import SessionLimitReached

    assert to_problem(SessionLimitReached("full")).status == 429


def test_session_open_timeout_is_504() -> None:
    from agent_service.registry import SessionOpenTimeout

    assert to_problem(SessionOpenTimeout("slow")).status == 504


def test_session_busy_is_409() -> None:
    from agent_service.sessions import SessionBusy

    assert to_problem(SessionBusy("busy")).status == 409


def test_session_closed_is_409() -> None:
    from agent_service.sessions import SessionClosed

    assert to_problem(SessionClosed("closed")).status == 409


def test_the_two_409s_are_distinguished_by_title() -> None:
    """`SessionBusy` and `SessionClosed` share status 409, so `title` is the
    ONLY thing telling them apart -- and it was unpinned: changing
    `SessionClosed`'s title to "Session busy" left the whole suite green.

    The two mean opposite things to a client. "Session busy" is transient and
    the remedy is to retry the same session shortly; "Session closed" is
    terminal and retrying can only 409 (or 404) forever -- the remedy is to
    open a new session. A client that switches on `title` (the only field that
    carries the distinction, since `status` and `type` are identical) would
    silently retry-forever against a dead session if these ever collapsed.
    """
    from agent_service.sessions import SessionBusy, SessionClosed

    busy = to_problem(SessionBusy("a turn is already running on this session"))
    closed = to_problem(SessionClosed("session is closed"))

    assert busy.status == closed.status == 409
    assert busy.title == "Session busy"
    assert closed.title == "Session closed"
    assert busy.title != closed.title


def test_each_module_imports_standalone_in_a_fresh_interpreter() -> None:
    """`errors` <-> `registry`/`sessions` is a genuine import cycle.

    It is broken by importing those two INSIDE `to_problem()`. Before that fix
    the imports sat at the bottom of `errors.py`, which works only when
    `errors` happens to be imported first -- which the test suite always did.
    Entered from the other side, `import agent_service.registry` (or
    `.sessions`) as the first `agent_service` import raised `ImportError:
    cannot import name ... from partially initialized module`.

    A subprocess per module is the point: nothing else can reproduce a genuinely
    fresh `sys.modules`, and importing them in-process here would prove nothing
    because pytest has already imported half the package. `-I` isolates the
    interpreter from user site-packages and env-var config so the check is
    about the import graph and nothing else.
    """
    import subprocess
    import sys

    for module in ("agent_service.registry", "agent_service.sessions",
                   "agent_service.errors", "agent_service.api"):
        proc = subprocess.run(
            [sys.executable, "-I", "-c", f"import {module}"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"`import {module}` failed in a fresh interpreter -- the import "
            f"cycle is back:\n{proc.stderr}"
        )
