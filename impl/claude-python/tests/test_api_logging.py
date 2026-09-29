"""What the HTTP layer says in the log when a request fails.

WHY THIS FILE EXISTS. The final acceptance run hit a transient 500 on
`GET /v1/sessions/{sid}` straight after an interrupted turn; an identical
retry returned 200. `docker compose logs` contained NOTHING about it -- no
traceback, no ERROR, not a line. Every `except Exception` in api.py answered
with `to_problem(exc)` and logged nothing at all, so an exception errors.py
cannot classify became an anonymous 500 and vanished. The run could report the
symptom and had no way to reach the cause.

These tests pin BOTH sides of the line api.py's `_problem` draws:

* the unclassified fallthrough MUST log ERROR *with* a traceback, and
* an expected, classified outcome (404 / 409 / 429 / 504) MUST NOT.

Both directions are load-bearing. A fix that logged everything at ERROR would
put a fault-level line on the most ordinary thing a client does, and an
operator who learns to scroll past ERROR is no better off than one with no log.
"""

import logging

import pytest
from claude_agent_sdk import ProcessError

from agent_service.errors import RunTimeout
from agent_service.sessions import SessionBusy
from tests.conftest import DEFAULT_EVENTS

API_LOGGER = "agent_service.api"


async def _open(session_client) -> str:  # noqa: ANN001
    return (await session_client.post("/v1/sessions", json={})).json()["session_id"]


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name == API_LOGGER and r.levelno == level
    ]


# --- the unclassified case: ERROR, with a traceback ------------------------


async def test_an_unclassified_get_failure_logs_error_with_a_traceback(
    session_client, fake_registry, caplog: pytest.LogCaptureFixture
) -> None:
    """THE DEFECT, at the exact route that showed it.

    `GET /v1/sessions/{sid}` is not a pure lookup -- it awaits
    `context_usage()`, a live control request. A failure errors.py has no
    branch for becomes `to_problem`'s fallthrough 500. Before this fix that
    500 left no record anywhere.
    """
    sid = await _open(session_client)

    async def _wedged():
        raise RuntimeError("control channel went away")

    fake_registry.get(sid).context_usage = _wedged

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.get(f"/v1/sessions/{sid}")

    assert r.status_code == 500
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1, caplog.text
    record = errors[0]

    # The traceback. Without `exc_info` the record says a failure happened and
    # still cannot say what it was -- which is the defect, one level quieter.
    assert record.exc_info is not None, "no exc_info: the traceback is the whole point"
    assert "RuntimeError" in caplog.text
    assert "control channel went away" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text

    # Enough context to act on: which route, and which session.
    message = record.getMessage()
    assert "GET /v1/sessions/{sid}" in message
    assert sid in message
    assert "unclassified" in message


async def test_an_unclassified_failure_on_a_route_with_no_session_still_logs(
    client, fake_factory, caplog: pytest.LogCaptureFixture
) -> None:
    """`POST /v1/query` has no session id. The route alone is still logged --
    a nameless traceback would be the same hole in a smaller form."""
    _factory, state = fake_factory
    state["raise"] = RuntimeError("options blew up in a new way")

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await client.post("/v1/query", json={"prompt": "hi"})

    assert r.status_code == 500
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1, caplog.text
    assert errors[0].exc_info is not None
    assert "POST /v1/query" in errors[0].getMessage()
    # No session on this route, so no session clause invented for it.
    assert "session=" not in errors[0].getMessage()


async def test_an_unclassified_failure_reported_in_band_is_logged_too(
    session_client, fake_registry, caplog: pytest.LogCaptureFixture
) -> None:
    """Once the SSE 200 is on the wire a failure can only be delivered in-band
    as `event: error`. That makes it LESS diagnosable, not more: the client
    gets a problem document and the operator's log gets nothing. Same logging
    terms as a status-code failure.
    """
    sid = await _open(session_client)

    async def _breaks_after_first(_prompt):
        yield DEFAULT_EVENTS[0]
        raise RuntimeError("transport closed mid-stream")

    fake_registry.get(sid).send = _breaks_after_first

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.post(
            f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
        )

    assert r.status_code == 200
    assert "event: error" in r.text
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1, caplog.text
    assert errors[0].exc_info is not None
    assert "transport closed mid-stream" in caplog.text
    assert sid in errors[0].getMessage()


# --- the classified cases: NOT an error ------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(SessionBusy("a turn is already running"), id="409-busy"),
        pytest.param(RunTimeout("the turn exceeded its budget"), id="504-timeout"),
    ],
)
async def test_a_classified_client_visible_outcome_is_not_logged_as_a_fault(
    session_client, fake_registry, caplog: pytest.LogCaptureFixture, exc
) -> None:
    """409 and 504 are ordinary API answers. errors.py has already NAMED the
    condition and the client has already been told; nothing is owed to the
    log. Logging these at ERROR (or WARNING) is how an ERROR line stops
    meaning anything."""
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = exc

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.post(
            f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
        )

    assert r.status_code in (409, 504)
    assert _records(caplog, logging.ERROR) == [], caplog.text
    assert _records(caplog, logging.WARNING) == [], caplog.text


async def test_an_unknown_session_is_not_logged_as_a_fault(
    session_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A 404 for a session that has been closed or reaped is the single most
    ordinary thing a polling client does."""
    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.get("/v1/sessions/nope")

    assert r.status_code == 404
    assert _records(caplog, logging.ERROR) == [], caplog.text
    assert _records(caplog, logging.WARNING) == [], caplog.text


async def test_a_classified_502_is_a_warning_and_not_an_error(
    session_client, fake_registry, caplog: pytest.LogCaptureFixture
) -> None:
    """A dead agent process IS the service's fault and an operator wants to
    see it -- but errors.py named it, so there is nothing a traceback would
    add. WARNING keeps ERROR meaning `we do not know what this is`."""
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = ProcessError("agent died", exit_code=1)

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.post(
            f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
        )

    assert r.status_code == 502
    assert _records(caplog, logging.ERROR) == [], caplog.text
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1, caplog.text
    assert warnings[0].exc_info is None, "a named condition does not need a traceback"
    assert "Agent process failed" in warnings[0].getMessage()


# --- what must never reach the log ----------------------------------------


async def test_the_failure_log_carries_no_prompt_and_no_credential(
    session_client, fake_registry, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The ERROR branch widens what this service logs, so it is pinned from
    the other side too: the route, the session id and the exception type --
    never the prompt, never the request body, never a credential. The
    traceback carries the exception's own message (that is its purpose) and no
    frame locals: `logging.Formatter.formatException` is traceback output, not
    a variable dump.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-do-not-log-me")
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = RuntimeError("transport closed")

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        r = await session_client.post(
            f"/v1/sessions/{sid}/messages",
            json={"prompt": "PROMPT-CANARY-do-not-log-me"},
        )

    assert r.status_code == 500
    assert _records(caplog, logging.ERROR), "the unclassified failure must be logged"
    assert "PROMPT-CANARY" not in caplog.text
    assert "sk-ant-" not in caplog.text
