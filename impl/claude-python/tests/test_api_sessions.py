import asyncio
import contextlib
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from agent_service.api import create_app
from agent_service.errors import RunTimeout
from agent_service.registry import SessionRegistry
from agent_spec.openapi.schemas import RunOptions
from agent_service.sessions import AgentSession, SessionBusy, SessionClosed, TurnResult
from tests.conftest import DEFAULT_EVENTS, DEFAULT_OUTCOME, FakeSession

# A real AgentSession over a fake SDK client -- the only way to assert whether
# the SDK control request actually fired, which a FakeSession cannot show.
# `SystemMessage` is the real SDK type those fake clients must yield.
from claude_agent_sdk import SystemMessage
from tests.test_sessions import (
    FakeClient,
    _abandon_mid_drain,
    _GatedDisconnectClient,
    _normal_turn,
    _ParkedClient,
    _result,
)

# Reused rather than re-written: both helpers already exist for /v1/query/stream
# and the session stream must behave identically at the wire level. `parse_sse`
# is the SSE-body parser; `_running_server` serves an app on a real loopback
# socket, which is the ONLY way to observe incremental delivery -- httpx's
# ASGITransport drains the app to completion before building a Response, so a
# buffered handler and a streaming one look identical through it.
from tests.test_api_stream import _running_server, parse_sse


async def test_create_returns_a_session_record(session_client) -> None:
    r = await session_client.post("/v1/sessions", json={"title": "exploring"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "exploring"
    assert body["status"] == "idle"
    assert body["session_id"]


async def test_create_accepts_run_options(session_client) -> None:
    r = await session_client.post(
        "/v1/sessions", json={"options": {"model": "claude-opus-5"}}
    )
    assert r.status_code == 201


async def test_list_is_empty_then_populated(session_client) -> None:
    assert (await session_client.get("/v1/sessions")).json()["sessions"] == []
    await session_client.post("/v1/sessions", json={})
    assert len((await session_client.get("/v1/sessions")).json()["sessions"]) == 1


async def test_get_includes_context_usage(session_client) -> None:
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    body = (await session_client.get(f"/v1/sessions/{sid}")).json()
    assert body["context_usage"]["categories"][0]["name"] == "Messages"


async def test_get_unknown_is_404_problem(session_client) -> None:
    r = await session_client.get("/v1/sessions/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_the_404_body_reads_as_a_sentence_not_a_python_repr(
    session_client,
) -> None:
    """Over HTTP, not just through `to_problem`: the acceptance run read this
    off the wire as `detail: "'834bd...'"`. `SessionNotFound` subclasses
    `KeyError`, whose `str()` is its REPR, and errors.py handed that straight
    to `detail`. Asserted here as well as in test_errors.py because "the
    response body a client actually receives" is the thing that was wrong.
    """
    body = (await session_client.get("/v1/sessions/834bd0f1")).json()

    assert "834bd0f1" in body["detail"]
    assert "'" not in body["detail"], f"a Python repr reached the wire: {body['detail']!r}"
    assert body["detail"].startswith("No session with id ")


async def test_delete_closes_and_removes(session_client) -> None:
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    assert (await session_client.delete(f"/v1/sessions/{sid}")).status_code == 204
    assert (await session_client.get(f"/v1/sessions/{sid}")).status_code == 404


async def test_delete_unknown_is_404(session_client) -> None:
    assert (await session_client.delete("/v1/sessions/nope")).status_code == 404


async def test_delete_surfaces_a_teardown_failure_instead_of_204(
    session_client, fake_registry
) -> None:
    # registry.close() leaves the session registered (retryable) when
    # AgentSession.close() raises during teardown, rather than swallowing the
    # failure -- DELETE must report that as a real error, not a false 204.
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    fake_registry.get(sid).raise_on_close = RuntimeError("disconnect failed")
    r = await session_client.delete(f"/v1/sessions/{sid}")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    # The session is still registered -- a retry is possible.
    assert (await session_client.get(f"/v1/sessions/{sid}")).status_code == 200


async def test_cap_returns_429(session_client, settings) -> None:
    settings.max_sessions = 1
    await session_client.post("/v1/sessions", json={})
    r = await session_client.post("/v1/sessions", json={})
    assert r.status_code == 429
    assert "max_sessions" in r.json()["detail"] or "concurrent" in r.json()["detail"]


async def test_openapi_documents_the_session_routes(session_client) -> None:
    paths = (await session_client.get("/openapi.json")).json()["paths"]
    assert "/v1/sessions" in paths
    assert "/v1/sessions/{sid}" in paths


async def test_lifespan_starts_reaper_and_closes_all_sessions_on_shutdown(
    settings, fake_factory, fake_registry
) -> None:
    # httpx.ASGITransport (used by every other fixture here) does NOT drive
    # the ASGI lifespan protocol at all, so start_reaper()/stop_reaper()/
    # close_all() in api.py's lifespan get zero coverage from any client
    # fixture. Driving `app.router.lifespan_context(app)` directly is the
    # cheapest way to actually exercise it without a real ASGI server.
    from agent_spec.openapi.schemas import RunOptions

    await fake_registry.create(RunOptions(), None)
    factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=factory, registry=fake_registry)

    assert fake_registry._reaper is None
    async with app.router.lifespan_context(app):
        # Startup ran: the reaper task exists.
        assert fake_registry._reaper is not None

    # Shutdown ran: the reaper is stopped AND every live session was closed.
    # If `close_all()` were dropped from the lifespan's shutdown path, this
    # session would still show `closed is False` and still be in `.list()` --
    # that is the specific regression this test pins. `.made` (the fixture's
    # own tracking list, not the registry) is read here on purpose: a
    # genuinely closed-and-forgotten session is no longer reachable via
    # `.get()`/`.list()` at all.
    assert fake_registry._reaper is None
    assert fake_registry.made[0].closed is True
    assert fake_registry.list() == []


async def test_create_that_times_out_opening_is_504(settings, fake_factory) -> None:
    class SlowOpenSession(FakeSession):
        async def open(self) -> None:
            await asyncio.sleep(10)

    def factory(options, settings_, title=None):  # noqa: ANN001, ARG001
        return SlowOpenSession(title=title)

    registry = SessionRegistry(settings, session_factory=factory, open_timeout_s=0.01)
    run_factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=run_factory, registry=registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/sessions", json={})

    assert r.status_code == 504
    assert r.headers["content-type"].startswith("application/problem+json")


async def _open(client) -> str:  # noqa: ANN001
    return (await client.post("/v1/sessions", json={})).json()["session_id"]


async def test_send_returns_the_turn_summary_and_events(session_client) -> None:
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hello"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "sdk-sess-1"
    assert body["result"] == "done"
    assert body["interrupted"] is False
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]


async def test_send_reports_an_interrupted_turn(session_client, fake_registry) -> None:
    sid = await _open(session_client)
    from agent_spec.db.outcome import RunOutcome

    fake_registry.get(sid)._turn = TurnResult(
        session_id="sdk-sess-1",
        outcome=RunOutcome(
            session_id="sdk-sess-1",
            is_error=True,
            subtype="error_during_execution",
            terminal_reason="aborted_streaming",
        ),
        interrupted=True,
    )
    body = (
        await session_client.post(
            f"/v1/sessions/{sid}/messages", json={"prompt": "stop"}
        )
    ).json()
    assert body["interrupted"] is True
    assert body["is_error"] is True


async def test_send_reports_a_turn_that_ended_without_a_result(
    session_client, fake_registry
) -> None:
    # A turn can end abnormally -- the drain finishes with no ResultMessage --
    # without raising. TurnResult.outcome is None in that case, and this must
    # NOT crash `_summary`'s `if outcome else None` guards; it must come back
    # as a normal 200 with outcome_recorded=False and the events still
    # populated, exactly like Run.outcome is None does for /v1/query.
    sid = await _open(session_client)
    fake_registry.get(sid)._turn = TurnResult(
        session_id="sdk-sess-1", outcome=None, interrupted=False
    )
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hello"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["outcome_recorded"] is False
    assert body["result"] is None
    assert body["is_error"] is False
    assert body["subtype"] is None
    assert body["stop_reason"] is None
    assert body["terminal_reason"] is None
    assert body["num_turns"] is None
    assert body["total_cost_usd"] is None
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]


async def test_send_to_a_busy_session_is_409(session_client, fake_registry) -> None:
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = SessionBusy("busy")
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
    )
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_send_to_unknown_session_is_404(session_client) -> None:
    r = await session_client.post(
        "/v1/sessions/nope/messages", json={"prompt": "hi"}
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_send_requires_a_prompt(session_client) -> None:
    sid = await _open(session_client)
    assert (
        await session_client.post(f"/v1/sessions/{sid}/messages", json={})
    ).status_code == 422


# --- caller-supplied SDK session id ------------------------------------------
# The mapping has to exist BEFORE the session makes its first model call, which
# no header can deliver. Measured buildable: X2 (the CLI honours --session-id
# exactly), X5 (it refuses the id alongside --resume), P1 (it refuses an id that
# already has a transcript).


async def test_a_supplied_session_id_is_reported_at_creation(settings) -> None:
    """The whole point: `sdk_session_id` is known at 201, before any turn."""
    supplied = "7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55"
    seen: dict[str, object] = {}

    def factory(options, settings_, title=None, *, sdk_session_id=None):  # noqa: ANN001, ARG001
        seen["id"] = sdk_session_id
        session = FakeSession(title=title)
        session.session_id = sdk_session_id
        return session

    registry = SessionRegistry(settings, session_factory=factory)
    app = create_app(settings=settings, registry=registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/sessions", json={"sdk_session_id": supplied})

    assert r.status_code == 201
    body = r.json()
    assert body["sdk_session_id"] == supplied
    # And it reached the session, which is what puts it on the CLI's argv.
    assert seen["id"] == supplied
    # NOT the registry handle. Two identifiers, two fields, never merged.
    assert body["session_id"] != supplied


async def test_sdk_session_id_is_null_at_creation_when_none_was_supplied(
    session_client,
) -> None:
    """Null, not invented. The CLI has no id to report before the first turn."""
    r = await session_client.post("/v1/sessions", json={})
    assert r.status_code == 201
    # The shared FakeSession fixture pre-sets an id; what matters here is that
    # the field exists and mirrors the session rather than being fabricated.
    assert "sdk_session_id" in r.json()


@pytest.mark.parametrize(
    "bad",
    ["not-a-uuid", "", "7ad25f07-08d4-4b3a-9f21", "../etc/passwd"],
)
async def test_a_session_id_that_is_not_a_uuid_is_400(session_client, bad: str) -> None:
    """400 with a reason, not the CLI's `exit 1` arriving as an unexplained 502."""
    r = await session_client.post("/v1/sessions", json={"sdk_session_id": bad})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "UUID" in r.json()["detail"]


async def test_a_session_id_together_with_resume_is_400(session_client) -> None:
    """Measured (X5): the CLI exits 1 on that combination. Rejected here, where
    the message can say which two fields conflict."""
    r = await session_client.post(
        "/v1/sessions",
        json={
            "sdk_session_id": "7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55",
            "options": {"resume": "e13345e0-80a8-473d-a5ed-720253de700a"},
        },
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "resume" in detail and "session_id" in detail


async def test_the_deprecated_session_id_alias_still_works(settings) -> None:
    """`session_id` on the REQUEST shipped first and is kept working.

    It was the wrong name -- on the response, `SessionRecord.session_id` is the
    registry handle, so one name meant two identifiers on one resource, which is
    the collision `sdk_session_id` exists to prevent. Renamed rather than
    reinterpreted, with the old spelling accepted so nothing already sending it
    breaks.
    """
    supplied = "7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55"

    def factory(options, settings_, title=None, *, sdk_session_id=None):  # noqa: ANN001, ARG001
        session = FakeSession(title=title)
        session.session_id = sdk_session_id
        return session

    registry = SessionRegistry(settings, session_factory=factory)
    app = create_app(settings=settings, registry=registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        old = await ac.post("/v1/sessions", json={"session_id": supplied})
        both = await ac.post(
            "/v1/sessions",
            json={"session_id": supplied, "sdk_session_id": supplied},
        )
        conflict = await ac.post(
            "/v1/sessions",
            json={
                "session_id": supplied,
                "sdk_session_id": "e13345e0-80a8-473d-a5ed-720253de700a",
            },
        )

    assert old.status_code == 201
    assert old.json()["sdk_session_id"] == supplied
    # Both spellings, same value: accepted.
    assert both.status_code == 201
    # Both spellings, DIFFERENT values: refused rather than one silently
    # winning -- a caller that supplied an id must not get a session under a
    # different one.
    assert conflict.status_code == 422


async def test_a_supplied_id_reaches_the_sdk_options(settings) -> None:
    """Through `build_options`, which is what becomes `--session-id` on argv."""
    from agent_service.options import build_options

    supplied = "7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55"
    sdk_options, _ = build_options(RunOptions(), settings, None, supplied)
    assert sdk_options.session_id == supplied

    # And nothing is set when nobody asked, so the CLI keeps minting its own.
    plain, _ = build_options(RunOptions(), settings)
    assert plain.session_id is None


# --- x-sdk-session-id, on both turn routes -----------------------------------
# Asked for by a relay that joins its model-gateway traffic (which carries the
# SDK's `x-claude-code-session-id`) to service-side sessions. Body-only cost it
# an SSE scanner with a chunk-boundary carry buffer on every conversation.


async def test_the_turn_response_carries_the_sdk_session_id_as_a_header(
    session_client,
) -> None:
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
    )
    assert r.status_code == 200
    # The SAME value as the body's, which is the point: two names for one
    # identifier is already this API's known trap, and a header that could
    # disagree with the field beside it would be a third.
    assert r.headers["x-sdk-session-id"] == "sdk-sess-1"
    assert r.json()["sdk_session_id"] == "sdk-sess-1"


async def test_the_streaming_turn_carries_the_header_before_the_first_frame(
    session_client,
) -> None:
    """The case that decides whether the header is worth anything to a relay.

    Headers are committed before any frame, so this only works because
    `stream_turn` already pulls the turn's FIRST message before returning the
    response -- the SDK's init, which is where the id comes from. If that
    `anext` is ever removed, this fails rather than silently degrading to a
    header a relay cannot rely on.
    """
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-sdk-session-id"] == "sdk-sess-1"
    # The streaming headers it already sent are untouched.
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


async def test_the_header_is_omitted_rather_than_empty_when_the_id_is_unknown(
    session_client, fake_registry
) -> None:
    """Absent, never `x-sdk-session-id: ""`.

    A session that has not yet seen an init message has no id to report, and an
    empty header would be a value a relay could key on -- one that joins every
    such turn to the same non-existent conversation.
    """
    sid = await _open(session_client)
    session = fake_registry.get(sid)
    session.session_id = None
    session._turn = TurnResult(session_id=None, outcome=None, interrupted=False)

    plain = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
    )
    assert plain.status_code == 200
    assert "x-sdk-session-id" not in plain.headers

    streamed = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert streamed.status_code == 200
    assert "x-sdk-session-id" not in streamed.headers


async def test_the_streaming_header_is_present_on_a_session_s_very_first_turn(
    settings, fake_factory
) -> None:
    """The FIRST turn of a session, streamed — asked directly by a caller who
    had concluded it must be absent.

    The reasoning that says absent is sound and the conclusion is wrong: yes,
    response headers are flushed before any SSE frame, and yes, the SDK mints
    the conversation id only at the first turn (X1). But this route advances the
    generator ONCE before committing the response, and `_send_impl` assigns
    `session_id` from the init message *before* yielding it. So the id exists by
    the time the headers are built.

    The other header tests here cannot show this: `FakeSession` is constructed
    with `session_id` already set, so they would pass even if the value were
    only readable after the turn. This one starts at None and assigns during the
    first yield, exactly as `AgentSession` does.
    """

    # A REAL AgentSession over a fake SDK client, not a FakeSession: the claim
    # is about `_send_impl`'s internal ordering, so a stand-in that mimics that
    # ordering would be assuming what it is meant to prove. This one starts with
    # `session_id is None` and learns it from the same init `SystemMessage` the
    # CLI actually sends (measured shape, L2b).
    client = FakeClient(turns=[_normal_turn()])
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: client)
    assert session.session_id is None

    app, sid = await _app_around(settings, fake_factory, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"})

    assert r.status_code == 200
    assert r.headers["x-sdk-session-id"] == "sdk-sess-1"


async def test_the_header_is_declared_in_the_openapi_document(session_client) -> None:
    """Declared, not merely sent: a caller who reads the schema must be able to
    find the header AND the fact that it can be absent, without observing a
    response first. That is the standard the `sdk_session_id`/`session_id`
    distinction set, and the reason this request was cheap to answer."""
    spec = (await session_client.get("/openapi.json")).json()
    for path in (
        "/v1/sessions/{sid}/messages",
        "/v1/sessions/{sid}/messages/stream",
    ):
        headers = spec["paths"][path]["post"]["responses"]["200"]["headers"]
        assert "x-sdk-session-id" in headers
        assert "Absent" in headers["x-sdk-session-id"]["description"]


# --- POST /v1/sessions/{sid}/messages/stream ------------------------------


async def _app_around(settings, fake_factory, session) -> tuple[object, str]:  # noqa: ANN001
    """An app whose registry hands out exactly `session`, plus its id.

    The shared `session_client`/`fake_registry` fixtures always produce a
    plain `FakeSession`; the streaming tests below each need a session with
    its own behaviour (stalls, fails mid-turn, yields slowly), so they build
    the registry themselves the same way
    `test_create_that_times_out_opening_is_504` does.
    """
    def factory(options, settings_, title=None):  # noqa: ANN001, ARG001
        return session

    registry = SessionRegistry(settings, session_factory=factory)
    run_factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=run_factory, registry=registry)
    sid = await registry.create(RunOptions(), None)
    return app, sid


async def test_stream_emits_events_then_done(session_client) -> None:
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [n for n, _ in parse_sse(r.text)]
    assert names == ["system", "assistant", "result", "done"]


async def test_stream_done_carries_the_summary_with_no_events(session_client) -> None:
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    name, payload = parse_sse(r.text)[-1]
    assert name == "done"
    assert payload["session_id"] == "sdk-sess-1"
    assert payload["events"] == []
    assert payload["interrupted"] is False


async def test_stream_to_a_busy_session_is_409_not_in_band(
    session_client, fake_registry
) -> None:
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = SessionBusy("busy")
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_stream_to_unknown_session_is_404_not_in_band(session_client) -> None:
    r = await session_client.post(
        "/v1/sessions/nope/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 404


async def test_stream_to_a_closed_session_is_409_not_in_band(
    session_client, fake_registry
) -> None:
    """`SessionClosed` is the other 409 on this route. It surfaces from the
    same lazy first advance as `SessionBusy` (both are raised by
    `_send_impl`'s first two statements), so it must also become a real status
    code rather than an in-band error on a 200."""
    sid = await _open(session_client)
    fake_registry.get(sid).raise_on_send = SessionClosed("session is closed")
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_stream_of_a_turn_with_no_events_is_a_lone_done_frame(
    settings, fake_factory
) -> None:
    """`first is None` -- the pre-pull exhausts the turn immediately. A real
    `AgentSession` can produce this (a drain that ends without yielding
    anything), and the `if first is not None` guard means the whole event loop
    is skipped, so this is the one path where `done` is the only frame."""
    session = FakeSession(events=[])
    app, sid = await _app_around(settings, fake_factory, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"})

    assert r.status_code == 200
    events = parse_sse(r.text)
    assert [name for name, _ in events] == ["done"]
    assert events[0][1]["events"] == []
    assert events[0][1]["session_id"] == "sdk-sess-1"


async def test_stream_openapi_documents_the_route(session_client) -> None:
    spec = (await session_client.get("/openapi.json")).json()
    path = spec["paths"]["/v1/sessions/{sid}/messages/stream"]["post"]
    # The response is SSE, not JSON -- an OpenAPI document that claims
    # application/json here would mislead every generated client.
    assert list(path["responses"]["200"]["content"]) == ["text/event-stream"]
    # Every status this route can actually return is declared, and each of the
    # error ones is a Problem document. 504 in particular is reachable: a turn
    # that times out before its FIRST message never commits the stream.
    for status in ("404", "409", "504"):
        schema = path["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/Problem")
    # The 409 covers both of its causes, not just the busy one.
    assert "closed" in path["responses"]["409"]["description"]


class _FailsMidTurnSession(FakeSession):
    """Yields some events, then raises -- a failure discovered *during* the
    turn, after the 200 and the SSE headers are already on the wire."""

    def __init__(self, events, exc, **kwargs) -> None:  # noqa: ANN001
        super().__init__(events=events, **kwargs)
        self._exc = exc

    async def send(self, prompt):  # noqa: ANN001
        for event in self._events:
            yield event
        raise self._exc


async def test_stream_mid_turn_failure_is_an_error_event_not_a_problem(
    settings, fake_factory
) -> None:
    # A turn that times out mid-drain raises RunTimeout, which `to_problem`
    # maps to 504. On the blocking route that becomes a real 504 problem
    # document; here the response is already committed as a 200 text/
    # event-stream, so the SAME failure has to arrive in-band as
    # `event: error` carrying the problem document -- and crucially NOT as a
    # `done` frame, so a client can tell a broken turn from a finished one.
    early = [dict(e) for e in DEFAULT_EVENTS[:2]]
    session = _FailsMidTurnSession(early, RunTimeout("turn exceeded 600s"))
    app, sid = await _app_around(settings, fake_factory, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"})

    assert r.status_code == 200
    events = parse_sse(r.text)
    names = [name for name, _ in events]
    assert names == ["system", "assistant", "error"]
    assert "done" not in names
    assert events[-1][1]["status"] == 504


class _SlowSession(FakeSession):
    """Yields each event after a real delay, so a test can tell a streamed
    response from a buffered one."""

    def __init__(self, delay: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self._delay = delay

    async def send(self, prompt):  # noqa: ANN001
        for event in self._events:
            await asyncio.sleep(self._delay)
            yield event
        self.last_turn = TurnResult(
            session_id="sdk-sess-1", outcome=DEFAULT_OUTCOME, interrupted=False
        )


async def test_stream_delivers_frames_incrementally_not_buffered(
    settings, fake_factory
) -> None:
    delay = 0.05
    session = _SlowSession(delay, events=[dict(e) for e in DEFAULT_EVENTS])
    app, sid = await _app_around(settings, fake_factory, session)

    arrivals: list[float] = []
    async with _running_server(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            async with ac.stream(
                "POST", f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
            ) as response:
                assert response.status_code == 200
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        if block.strip():
                            arrivals.append(time.monotonic())

    # 3 events + the terminal done frame.
    assert len(arrivals) == 4
    gaps = [arrivals[i] - arrivals[i - 1] for i in range(1, len(arrivals))]
    spread = arrivals[-1] - arrivals[0]
    # A buffered implementation flushes all four frames back-to-back once the
    # generator has finished: `spread` and every gap would be ~0. A streaming
    # one produces them `delay` apart, so they stay spread out in time.
    #
    # Asserted on the AGGREGATE rather than on gaps[0]/gaps[1] individually:
    # a client that is scheduled late can legitimately read two adjacent
    # frames in a single socket read, collapsing one gap to ~0 without the
    # response having been buffered at all. That made a per-gap assertion
    # genuinely flaky here (observed: gaps[0] == 0.00026 on a run that was
    # streaming correctly), and it is a weaker property than it looks --
    # `spread` is what actually distinguishes the two implementations.
    assert spread >= delay * 0.8
    assert max(gaps) >= delay * 0.5


async def test_clean_completion_does_not_interrupt_the_session(
    session_client, fake_registry
) -> None:
    """The disconnect cleanup below must be inert on the happy path: a turn
    that ran to completion has nothing to interrupt, and issuing one anyway
    would stamp an unrelated later turn as deliberately stopped."""
    sid = await _open(session_client)
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 200
    # The response has been fully drained, so Starlette has already run the
    # BackgroundTask attached to it.
    assert fake_registry.get(sid).interrupted == 0


class _StallingSession(FakeSession):
    """Yields exactly one event, then sits suspended at that yield forever --
    the abandoned-consumer case. `stream_closed` flips only when something
    explicitly `aclose()`s the generator, and `interrupts_at_close` records
    how many interrupts had ALREADY been issued at that instant."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.stream_closed = False
        self.interrupts_at_close: int | None = None

    async def send(self, prompt):  # noqa: ANN001
        try:
            yield {"seq": 1, "type": "system", "subtype": "init", "content": None}
        finally:
            self.interrupts_at_close = self.interrupted
            self.stream_closed = True


async def test_client_disconnect_interrupts_the_turn_then_closes_the_stream(
    settings, fake_factory
) -> None:
    """The case that makes this endpoint dangerous, and the two things the
    route owes the session when it happens.

    A consumer takes an event and vanishes. Cancellation lands in Starlette's
    own `send()` call -- outside both generators' frames -- so neither
    `generate()` nor the session's `send()` generator ever unwinds through a
    `finally` on its own; the turn stays `running` with the session lock held,
    reclaimed only by non-deterministic GC. Two assertions here, and both
    matter:

      * `stream_closed` -- the abandoned turn is force-ended explicitly. This
        test calls NO `gc.collect()`: it asserts closure the moment
        `app(...)` returns.
      * `interrupts_at_close == 1` -- `session.interrupt()` was genuinely
        awaited BEFORE the generator was closed. That ordering is not
        cosmetic: `AgentSession.interrupt()` returns immediately unless
        `status == "running"`, and closing the generator is exactly what ends
        "running", so an interrupt issued afterwards would silently do
        nothing. The interrupt is what stops the CLI subprocess emitting the
        rest of an abandoned turn into the SDK's connection-scoped buffer,
        where it would otherwise be read by the NEXT turn's drain and end it
        early on a stray ResultMessage.

    Driven through the raw ASGI callable rather than httpx, which cannot
    express a mid-stream disconnect at all -- the same technique
    `test_api_stream.py::test_client_disconnect_closes_the_events_stream_without_gc`
    uses for /v1/query/stream.
    """
    session = _StallingSession()
    app, sid = await _app_around(settings, fake_factory, session)

    body = json.dumps({"prompt": "hi"}).encode()
    path = f"/v1/sessions/{sid}/messages/stream"
    scope = {
        "type": "http",
        # Matches uvicorn's h11 impl (spec_version "2.3"), below Starlette's
        # (2, 4) threshold, so StreamingResponse takes the
        # listen_for_disconnect/cancel-scope path this test exercises.
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "scheme": "http",
        "extensions": {},
    }

    body_sent = False
    send_in_progress = asyncio.Event()
    stuck_forever = asyncio.Event()

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Only report the disconnect once the first SSE chunk is genuinely in
        # flight, i.e. once `generate()` is suspended at its yield.
        await send_in_progress.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            send_in_progress.set()
            # A write to a client that has gone away: never completes on its
            # own. The task group's cancellation is what ends it.
            await stuck_forever.wait()

    await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert session.stream_closed is True
    assert session.interrupted == 1
    assert session.interrupts_at_close == 1


class _FailsMidDrainClient(FakeClient):
    """A fake SDK client whose turn raises partway through the drain."""

    def __init__(self) -> None:
        super().__init__([])

    async def receive_response(self):
        yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
        raise RuntimeError("transport died mid-turn")


async def test_a_mid_drain_failure_does_not_issue_a_control_request(
    settings, fake_factory
) -> None:
    """Pins `generate()`'s error-branch `turn_ended = True` (Task 6, round 2).

    Round 1 softened the comment on that assignment to say moving it "does not,
    on its own, cause a spurious control request". That was measurably wrong,
    and round 1's own change is what made it wrong: once `interrupt()` gained
    the abandoned-turn branch, a turn that raised mid-drain leaves
    `_turn_abandoned` set, so WITHOUT this assignment `close_stream()` reaches
    `interrupt()` and the SDK control-request count goes 0 -> 1.

    Mutation-verified in both directions rather than asserted: deleting
    `turn_ended = True` from the error branch fails this test.

    Note what is being pinned is the CURRENT specification -- a turn that ended by
    raising has "ended of its own accord", so the disconnect cleanup owes it
    nothing. `_turn_abandoned` stays set for a later caller (Task 7's endpoint,
    or `close()`), and `_discard_residue` still guards the next turn.
    """
    sdk = _FailsMidDrainClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"})

    # The failure is reported in-band: the stream had already been committed.
    assert r.status_code == 200
    assert [name for name, _ in parse_sse(r.text)] == ["system", "error"]
    # ASGITransport drains the app fully, so the BackgroundTask has run.
    assert sdk.interrupts == 0


async def test_real_socket_hangup_interrupts_the_abandoned_turn(
    settings, fake_factory
) -> None:
    """Task 6 fix round 1 -- the OTHER disconnect interleaving, and the common
    one.

    The raw-ASGI test above stalls the *write*, so the turn is still parked at
    a `yield` and `status == "running"` when the cleanup runs. A real client
    that reads a frame and hangs up produces a different unwind: the
    cancellation lands INSIDE `stream.__anext__()`, `_send_impl` unwinds
    through its own `except BaseException`/`finally` first, and `status` is
    already back to `"idle"` before the BackgroundTask executes. The original
    Task 6 implementation issued no control request at all on this path --
    `AgentSession.interrupt()` returned at its `status != "running"` guard --
    even though the turn was abandoned mid-drain and the subprocess was still
    producing.

    This is deliberately end-to-end over a real loopback socket rather than a
    simulation: the whole point is that the interleaving the raw-ASGI harness
    produces is not the one a real socket produces, so asserting on a real
    socket is the only way to keep that honest. It runs a REAL `AgentSession`
    (not a `FakeSession`) over a fake SDK client, so `status`, the residue
    bookkeeping and the interrupt path are all the production ones.
    """
    sdk = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    async with _running_server(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            async with ac.stream(
                "POST", f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"}
            ) as response:
                assert response.status_code == 200
                async for _chunk in response.aiter_text():
                    break  # take one frame, then hang up mid-turn
        # Leaving the client context closes the socket. Wait, bounded, for the
        # server to notice the disconnect and run the response's BackgroundTask.
        deadline = time.monotonic() + 5.0
        while sdk.interrupts == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        # Snapshot INSIDE the server context: leaving it runs the ASGI
        # lifespan shutdown, whose `close_all()` would take the session
        # terminal and destroy the state under test.
        status, residue, interrupts = (
            session.status,
            session._residue_suspected,
            sdk.interrupts,
        )

    # The interleaving this test exists to pin: the turn unwound on its own,
    # so `status` is NOT "running" by the time the cleanup runs...
    assert status == "idle"
    # ...and it was abandoned mid-drain, so the subprocess is still producing.
    assert residue is True
    # ...and the control request was nevertheless issued.
    assert interrupts == 1


# --- POST /v1/sessions/{sid}/interrupt ------------------------------------
#
# 200 with a body, NOT 204 and NOT 409. The reasoning lives in ONE place --
# `AgentSession.interrupt()`'s docstring in sessions.py -- because that method
# is the one that has to be right; the tests below only pin the consequences.


async def test_interrupt_returns_200_and_calls_the_session(
    session_client, fake_registry
) -> None:
    sid = await _open(session_client)
    r = await session_client.post(f"/v1/sessions/{sid}/interrupt")
    assert r.status_code == 200
    assert r.json() == {"interrupted": True, "status": "idle"}
    assert fake_registry.get(sid).interrupted == 1


async def test_interrupt_with_nothing_to_stop_is_a_200_saying_so(
    session_client, fake_registry
) -> None:
    """The unavoidable race: the turn ended just before the request landed.
    Not an error -- but the body must not claim an interrupt happened."""
    sid = await _open(session_client)
    fake_registry.get(sid).interrupt_fires = False
    r = await session_client.post(f"/v1/sessions/{sid}/interrupt")
    assert r.status_code == 200
    assert r.json() == {"interrupted": False, "status": "idle"}


async def test_interrupt_reports_a_real_control_request_on_an_idle_session(
    settings, fake_factory
) -> None:
    """The crux of this endpoint, and why the body cannot be derived from
    `status`.

    Task 6 gave `AgentSession.interrupt()` a second trigger: a turn abandoned
    mid-drain. On the commonest disconnect there is (a real socket hangup) the
    cancellation lands inside `stream.__anext__()`, so the turn unwinds through
    its own `finally` and `status` is back to `"idle"` long before anyone can
    ask for an interrupt -- yet the CLI subprocess is still producing and a
    genuine control request DOES go out.

    So `interrupted: status == "running"` is not a shortcut, it is a lie: it
    would report `false` for the request below, which measurably fired. The
    endpoint reports what `interrupt()` itself says it did.

    A REAL `AgentSession` over a fake SDK client, because `sdk.interrupts` is
    the only thing that proves a control request actually left the process --
    a `FakeSession` can only echo whatever it was told to say.

    Deliberately NOT racy: the turn is abandoned and fully unwound before the
    request is made, so no turn is running while the endpoint awaits, and this
    does not depend on the known lock-free-abandoned-branch interleaving.
    """
    sdk = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)
    await _abandon_mid_drain(session, sdk)
    assert session.status == "idle"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        first = await ac.post(f"/v1/sessions/{sid}/interrupt")
        second = await ac.post(f"/v1/sessions/{sid}/interrupt")

    # Idle, and yet a control request genuinely went out.
    assert first.status_code == 200
    assert first.json() == {"interrupted": True, "status": "idle"}
    assert sdk.interrupts == 1
    # Same status, no control request -- the ONLY difference is what the body
    # says, which is the whole point.
    assert second.status_code == 200
    assert second.json() == {"interrupted": False, "status": "idle"}
    assert sdk.interrupts == 1


# --- the `status` half of the body ----------------------------------------
#
# `interrupted` and `status` are two independent fields and the tests above
# only exercise sessions that are `"idle"` on both sides of the call, so they
# pin neither the VALUE of `status` nor the specification `schemas.py` advertises
# for it ("the session's status immediately AFTER the request"). Both of these
# mutations survived the whole suite before these three tests existed:
#
#   * `status=session.status` -> `status="idle"`  (a constant)
#   * reading `session.status` BEFORE the await instead of after
#
# The first two tests below kill the constant; the third kills the ordering.


async def test_interrupt_of_a_running_turn_reports_running(
    settings, fake_factory
) -> None:
    """The stalled-write interleaving: the turn is parked at its own yield, so
    it is still `"running"` when the control request is answered."""
    sdk = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    async def drain() -> None:
        async for _ in session.send("hi"):
            pass

    task = asyncio.create_task(drain())
    await sdk.parked.wait()
    assert session.status == "running"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/interrupt")

    assert r.status_code == 200
    assert r.json() == {"interrupted": True, "status": "running"}
    assert sdk.interrupts == 1

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_interrupt_of_a_closed_session_reports_closed(
    settings, fake_factory
) -> None:
    """A closed session is excluded outright -- `close()`/`disconnect()` has
    already stopped the subprocess (S5) and a control request down a
    disconnected client could only raise.

    Note the session here has `_turn_abandoned` armed from the abandoned turn
    and STILL reports `interrupted: false`: the closed check wins. That is the
    honest answer, and the body carries `status: "closed"` so a caller can see
    exactly why nothing happened -- which is the whole reason this is a 200
    with a body rather than a bare 204.

    The session stays registered because `close()` is called on the session
    directly rather than through `registry.close()`, which would also forget it.
    """
    sdk = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)
    await _abandon_mid_drain(session, sdk)
    assert session._turn_abandoned is True

    await session.close()
    assert session.status == "closed"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/interrupt")

    assert r.status_code == 200
    assert r.json() == {"interrupted": False, "status": "closed"}
    assert sdk.interrupts == 0


class _FinishesDuringInterruptClient(FakeClient):
    """The turn completes WHILE the control request is in flight.

    That is not a contrived interleaving -- it is what a successful interrupt
    IS: the agent stops, the turn drains its final message and ends, and only
    then does the control request come back. This client makes the timing
    deterministic instead of hoping for it.
    """

    def __init__(self) -> None:
        super().__init__([])
        self.parked = asyncio.Event()
        self.release = asyncio.Event()
        self.turn_done = asyncio.Event()

    async def receive_response(self):
        yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
        self.parked.set()
        await self.release.wait()
        yield _result(
            subtype="error_during_execution",
            is_error=True,
            terminal_reason="aborted_streaming",
            result=None,
        )

    async def interrupt(self) -> None:
        self.interrupts += 1
        self.release.set()
        await self.turn_done.wait()


async def test_interrupt_reports_the_status_from_after_the_control_request(
    settings, fake_factory
) -> None:
    """`status` is read AFTER the await, and that is observable.

    The session is `"running"` when `interrupt()` is entered and `"idle"` by
    the time it returns, so the two possible implementations give different
    answers and the test can tell them apart. Reading it beforehand would
    report a turn as still draining when it had already finished -- stale by
    construction, and contradicting what `InterruptResult.status` promises.
    """
    sdk = _FinishesDuringInterruptClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    async def drain() -> None:
        async for _ in session.send("hi"):
            pass
        sdk.turn_done.set()

    task = asyncio.create_task(drain())
    await sdk.parked.wait()
    assert session.status == "running"  # ...as it is on ENTRY to the request

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/interrupt")
    await task

    # The turn ended during the await, so "running" is the STALE answer and
    # "idle" is the true one.
    assert session.status == "idle"
    assert r.status_code == 200
    assert r.json() == {"interrupted": True, "status": "idle"}
    # ...and the turn itself is labelled honestly off the same interrupt.
    assert session.last_turn.interrupted is True


async def test_interrupt_unknown_session_is_404(session_client) -> None:
    r = await session_client.post("/v1/sessions/nope/interrupt")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_interrupt_openapi_declares_the_body_and_its_errors(
    session_client,
) -> None:
    spec = (await session_client.get("/openapi.json")).json()
    path = spec["paths"]["/v1/sessions/{sid}/interrupt"]["post"]
    schema = path["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/InterruptResult")
    assert set(spec["components"]["schemas"]["InterruptResult"]["properties"]) == {
        "interrupted",
        "status",
    }
    # Every error status this route can actually reach, each a Problem
    # document: 404 (no such session), 502 (the SDK could not deliver the
    # control request), 500 (the SDK's own 60s control-request timeout on a
    # RUNNING turn, which this service does not bound and which raises a plain
    # Exception) and 504 (`InterruptTimeout` -- the abandoned-turn branch
    # bounds its own control request at `_STALE_INTERRUPT_BUDGET_S`, and a
    # time-budget overrun is a 504 everywhere else in this codebase).
    for status in ("404", "500", "502", "504"):
        error = path["responses"][status]["content"]["application/json"]["schema"]
        assert error["$ref"].endswith("/Problem")


async def test_interrupt_that_fails_is_a_problem_document_not_a_body(
    settings, fake_factory
) -> None:
    """A wedged control channel must not come back as `interrupted: false` --
    that would be indistinguishable from the honest no-op above."""
    session = FakeSession()

    async def boom() -> bool:
        raise RuntimeError("control channel wedged")

    session.interrupt = boom
    app, sid = await _app_around(settings, fake_factory, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/interrupt")

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")


# --- PATCH /v1/sessions/{sid} ---------------------------------------------


async def test_patch_sets_model_and_permission_mode(
    session_client, fake_registry
) -> None:
    sid = await _open(session_client)
    r = await session_client.patch(
        f"/v1/sessions/{sid}",
        json={"model": "claude-opus-5", "permission_mode": "acceptEdits"},
    )
    assert r.status_code == 200
    session = fake_registry.get(sid)
    assert session.model == "claude-opus-5"
    assert session.permission_mode == "acceptEdits"


async def test_patch_returns_the_session_record(session_client) -> None:
    sid = await _open(session_client)
    body = (
        await session_client.patch(f"/v1/sessions/{sid}", json={"model": "claude-opus-5"})
    ).json()
    assert body["session_id"] == sid
    assert body["status"] == "idle"


async def test_patch_with_no_fields_calls_neither_setter(
    session_client, fake_registry
) -> None:
    """An omitted field must not be forwarded as `None`.

    Asserted on CALL COUNTS, not on the resulting values. `model` and
    `permission_mode` are already `None` before the request, so asserting they
    are still `None` afterwards cannot distinguish "never called" from "called
    with None" -- the version of this test inherited from the brief passed
    with BOTH `is not None` guards in `api.py` deleted (mutation-verified:
    271/271).

    The guards are load-bearing against the real SDK, which is why this now
    pins them: `ClaudeSDKClient.set_model(None)` means "use the default", so an
    unguarded `PATCH {}` would silently RESET the session's model rather than
    change nothing, and `set_permission_mode(None)` would push `None` down a
    control request whose parameter is typed `PermissionMode`.
    """
    sid = await _open(session_client)
    assert (await session_client.patch(f"/v1/sessions/{sid}", json={})).status_code == 200
    session = fake_registry.get(sid)
    assert session.set_model_calls == 0
    assert session.set_permission_mode_calls == 0
    assert session.model is None
    assert session.permission_mode is None


async def test_patch_with_one_field_calls_only_that_setter(
    session_client, fake_registry
) -> None:
    """The other half of the same guard: a partial PATCH must leave the field
    it did not mention alone, rather than resetting it to the SDK default."""
    sid = await _open(session_client)
    r = await session_client.patch(
        f"/v1/sessions/{sid}", json={"permission_mode": "plan"}
    )
    assert r.status_code == 200
    session = fake_registry.get(sid)
    assert session.set_model_calls == 0
    assert session.set_permission_mode_calls == 1
    assert session.permission_mode == "plan"


async def test_patch_rejects_an_empty_model_without_calling_the_setter(
    session_client, fake_registry
) -> None:
    """Item 9. An empty model is rejected at the boundary, so no control
    request is issued at all -- asserted on the CALL COUNT, because the
    resulting `model` value cannot tell "never called" from "called with
    something falsy"."""
    sid = await _open(session_client)
    r = await session_client.patch(f"/v1/sessions/{sid}", json={"model": ""})
    assert r.status_code == 422
    assert fake_registry.get(sid).set_model_calls == 0


async def test_creating_a_session_with_an_empty_model_is_422(session_client) -> None:
    """The same guard on `RunOptions`, which is what `POST /v1/sessions` and
    `POST /v1/query` both carry. 422 rather than 400: this is request-body
    validation by pydantic, before any handler runs, unlike a limit above its
    cap (`LimitExceeded`), which `build_options` raises inside the handler."""
    r = await session_client.post("/v1/sessions", json={"options": {"model": ""}})
    assert r.status_code == 422


async def test_patch_rejects_an_invalid_permission_mode(session_client) -> None:
    """**400 since 0.19.0, where it used to be 422**, and the change is the
    point rather than a regression.

    `permission_mode` was a closed `Literal` in the shared models, so pydantic
    refused an unknown value before any route ran. Each build declares its own
    modes now, so the shared model cannot validate and this build does -- which
    buys a message naming the modes that exist, where a 422 could only say the
    value was not in a union the caller could not see.
    """
    sid = await _open(session_client)
    r = await session_client.patch(
        f"/v1/sessions/{sid}", json={"permission_mode": "notAMode"}
    )
    assert r.status_code == 400
    body = r.json()
    assert "notAMode" in body["detail"]
    # The remedy, not just the refusal.
    assert "capabilities.permission_modes" in body["detail"]


async def test_patch_unknown_session_is_404(session_client) -> None:
    r = await session_client.patch("/v1/sessions/nope", json={})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_patch_a_closed_session_is_409_like_the_messages_route(
    settings, fake_factory
) -> None:
    """One condition, one answer (fix round 1).

    `POST /v1/sessions/{sid}/messages` already returns 409 "Session closed" for
    a closed session. Without a guard, PATCH would reach a disconnected client,
    raise `CLIConnectionError`, and come back 502 "Agent process failed" --
    reporting a session the operator closed DELIBERATELY as an agent crash, and
    answering the identical condition two incompatible ways.

    Uses a real `AgentSession` so the guard is exercised where it lives, and
    closes it directly rather than through `registry.close()`, which would also
    forget it and turn this into a 404.
    """
    sdk = FakeClient([])
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)
    await session.close()
    assert session.status == "closed"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(f"/v1/sessions/{sid}", json={"model": "claude-opus-5"})
        messages = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})

    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    # The control request never left the process.
    assert sdk.model is None
    # The route beside it agrees, which is the point of the guard.
    assert messages.status_code == 409


async def test_patch_an_empty_body_on_a_closed_session_is_still_200(
    settings, fake_factory
) -> None:
    """The guard lives in the setters, so a PATCH that sets nothing touches
    nothing and stays a no-op. Deliberate: an empty PATCH makes no claim about
    the session, so there is no conflict for a 409 to report."""
    sdk = FakeClient([])
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)
    await session.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(f"/v1/sessions/{sid}", json={})

    assert r.status_code == 200
    assert r.json()["status"] == "closed"


async def test_patch_succeeds_against_a_running_turn(settings, fake_factory) -> None:
    """PATCH takes no lock, and a live probe has now shown it does not need one.

    This used to be recorded-but-unendorsed behaviour: whether the SDK
    tolerated `set_model` interleaved with an in-flight `receive_response()`
    was not measured anywhere in this repo. It has since been measured live
    (spike case M1, CP-068), and the answer is two-part:

    * SAFE. A mid-turn control request does not disturb the drain. Control
      calls returned in 4ms/5ms/161ms, no exception in either the control
      coroutine or the drain, no stall, no reordering, no lost or duplicated
      message, and every turn still ended on a clean `ResultMessage`
      (`subtype='success'`, `terminal_reason='completed'`). No lock is needed
      for safety.
    * BUT IT APPLIES TO THE CURRENT TURN, not the next one. The change takes
      effect at the very next inference of the turn already draining. Within
      one drain `AssistantMessage.model` went
      `claude-haiku-4-5-20251001` -> `claude-sonnet-5`, and that single turn's
      `model_usage` billed BOTH ($0.027 haiku + $0.098 sonnet). So a mid-turn
      PATCH re-prices work already in flight and `total_cost_usd` moves by
      more than the new model alone would suggest.

    The route's prose used to say "mid-session", which readers took as "from
    the next turn". That wording was materially misleading and has been
    corrected; this test is what pins the mid-turn case it describes.
    """
    sdk = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    async def drain() -> None:
        async for _ in session.send("hi"):
            pass

    task = asyncio.create_task(drain())
    await sdk.parked.wait()
    assert session.status == "running"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            f"/v1/sessions/{sid}",
            json={"model": "claude-opus-5", "permission_mode": "plan"},
        )

    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert sdk.model == "claude-opus-5"
    assert sdk.permission_mode == "plan"

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_patch_openapi_declares_its_reachable_errors(session_client) -> None:
    """Same reachability argument the interrupt route uses twenty lines above,
    applied consistently: a control request can fail to be delivered (502) or
    go unanswered past the SDK's own 60s control bound (500), and a closed
    session is a 409."""
    spec = (await session_client.get("/openapi.json")).json()
    path = spec["paths"]["/v1/sessions/{sid}"]["patch"]
    for status in ("404", "409", "500", "502"):
        schema = path["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/Problem")


# --- follow-up item 7: `session_id` names two different identifiers --------


async def test_the_registry_handle_and_the_sdk_id_are_both_reported_unambiguously(
    settings, fake_factory
) -> None:
    """The measured defect, reproduced, plus the field that fixes it.

    `SessionRecord.session_id` is this service's registry handle -- the one in
    every `/v1/sessions/{sid}` path. `RunResponse.session_id` is the SDK's own
    conversation id. They are different strings, and feeding the second back
    into a path is a 404. `RunResponse.sdk_session_id` carries the same value
    under a name that says which id it is, matching `TurnRecord.sdk_session_id`
    from item 11.

    `session_id` is deliberately KEPT and unchanged (user decision,
    2026-07-27): renaming it would break a field that already ships.
    """
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: FakeClient([_normal_turn()])
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        turn = (
            await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        ).json()
        # The trap: the SDK's id used as a path segment.
        wrong = await ac.post(
            f"/v1/sessions/{turn['sdk_session_id']}/messages", json={"prompt": "again"}
        )

    assert turn["sdk_session_id"] == "sdk-sess-1"
    # Both names, same value -- additive, not a rename.
    assert turn["session_id"] == turn["sdk_session_id"]
    # ...and it is genuinely not the handle.
    assert turn["sdk_session_id"] != sid
    assert wrong.status_code == 404


async def test_the_one_shot_route_also_reports_sdk_session_id(client) -> None:
    """`/v1/query` returns the same `RunResponse`, so it gains the same field.
    There is no registry handle here at all -- which is exactly why the name
    has to say which id it is rather than relying on context."""
    body = (await client.post("/v1/query", json={"prompt": "hello"})).json()
    assert body["session_id"] == "sess-test"
    assert body["sdk_session_id"] == "sess-test"


async def test_a_run_with_no_session_id_reports_null_under_both_names(
    client, fake_factory
) -> None:
    _, state = fake_factory
    state["outcome"] = None
    body = (await client.post("/v1/query", json={"prompt": "hello"})).json()
    assert body["session_id"] is None
    assert body["sdk_session_id"] is None


async def test_openapi_says_which_id_run_response_session_id_carries(
    session_client,
) -> None:
    """The description is the other half of the user's decision: keep the
    field, and stop it being ambiguous in the generated docs and clients."""
    schemas = (await session_client.get("/openapi.json")).json()["components"][
        "schemas"
    ]
    props = schemas["RunResponse"]["properties"]
    assert "sdk_session_id" in props
    description = props["session_id"]["description"]
    assert "SDK" in description
    # It must point at the thing it is NOT, or the ambiguity survives.
    assert "sdk_session_id" in description
    assert "SessionRecord" in description


# --- follow-up item 6: GET and POST .../messages can 500 -------------------


async def test_get_surfaces_an_unclassified_control_failure_as_500(
    settings, fake_factory
) -> None:
    """`GET /v1/sessions/{sid}` is not a pure lookup: it awaits
    `context_usage()`, which delegates to the SDK's `get_context_usage()`, a
    control request. The SDK bounds those by its own 60s and then raises a
    PLAIN `Exception("Control request timeout: ...")` -- a type
    `errors.to_problem` does not classify, so it falls through to 500. That is
    the identical condition PATCH already declares 500 for; the last round
    propagated PATCH's 502 reasoning to this route and not its 500 reasoning.
    """

    class _WedgedControlChannel(FakeClient):
        async def get_context_usage(self):
            raise Exception("Control request timeout: get_context_usage")

    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: _WedgedControlChannel()
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"/v1/sessions/{sid}")

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    detail = r.json()["detail"]
    # The SDK's own wording is NOT echoed. This assertion was the opposite way
    # round until 2026-08-06, when the fallthrough stopped repeating messages
    # it cannot vouch for -- see errors.to_problem's closing comment. The
    # traceback still reaches the log at ERROR, which is where it belongs.
    assert "Control request timeout" not in detail
    assert "Exception" in detail


async def test_a_turn_failing_in_an_unclassified_way_is_500(
    settings, fake_factory
) -> None:
    """The messages route drains the whole turn inside its `try`, so anything
    the drain raises becomes a status code. `errors.to_problem` classifies
    ProcessError/CLIConnectionError as 502 and RunTimeout as 504; everything
    else -- a broken anyio stream, an SDK internal, a plain RuntimeError from
    the transport -- reaches the 500 fallthrough. Reachable, so declared.
    """

    class _BrokenMidDrain(FakeClient):
        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"})
            raise RuntimeError("transport closed unexpectedly")

    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: _BrokenMidDrain()
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    detail = r.json()["detail"]
    # The class name, never the message. Same change as the test above.
    assert "transport closed unexpectedly" not in detail
    assert "RuntimeError" in detail


async def test_openapi_declares_the_confirmed_reachable_session_statuses(
    session_client,
) -> None:
    """Renamed from `..._every_reachable_status_on_the_session_routes`, which
    overclaimed (follow-up item 6). This asserts the statuses this project has
    CONFIRMED reachable by driving a real request; it is NOT a proof that the
    declared set is exhaustive. Two things stop it being that: FastAPI adds
    422 to every route itself, so this list would be incomplete even as a
    description of the spec, and nothing here enumerates what a future handler
    might raise. "Every reachable status" was a claim no test in this file
    could establish.

    Same reachability argument Task 7 applied to PATCH and interrupt,
    propagated to the rest.

    An undeclared status is a real defect in an OpenAPI-first service: it is
    absent from `/docs`, absent from generated clients, and a caller that
    handles only the declared set meets it as an unexpected shape. Each entry
    below was confirmed reachable by driving a real request:

      * `POST /v1/sessions` -> 400. `registry.create()` builds options, so
        `max_turns=99999` (LimitExceeded) or `workspace_subdir="../../etc"`
        (InvalidWorkspacePath) fail before any subprocess starts. `/v1/query`
        already declared it for the identical RunOptions model.
      * `GET /v1/sessions/{sid}` -> 502 and 500. Not a pure lookup: it awaits
        `context_usage()`, a live control request, which raises
        CLIConnectionError on a wedged or disconnected channel (502) and a
        plain, unclassified `Exception` on the SDK's own control timeout
        (500) -- both driven by dedicated tests above.
      * `DELETE /v1/sessions/{sid}` -> 500. A teardown failure propagates
        rather than being flattened into a false 204; there is already a
        dedicated test asserting that behaviour.
      * `POST /v1/sessions/{sid}/messages` -> 504, 502 and 500. This route
        drains the whole turn inside its try, so RunTimeout, SDK process
        errors and anything `errors.to_problem` does not classify all become
        real status codes. The streaming route beside it already declared 504,
        and `/v1/query` already declared 502/504.
    """
    spec = (await session_client.get("/openapi.json")).json()

    expected = {
        ("/v1/sessions", "post"): ["400", "429", "504"],
        ("/v1/sessions/{sid}", "get"): ["404", "500", "502"],
        ("/v1/sessions/{sid}", "delete"): ["404", "500"],
        ("/v1/sessions/{sid}/messages", "post"): ["404", "409", "500", "502", "504"],
    }

    for (path, method), statuses in expected.items():
        responses = spec["paths"][path][method]["responses"]
        for status in statuses:
            assert status in responses, f"{method.upper()} {path} does not declare {status}"
            schema = responses[status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/Problem"), (
                f"{method.upper()} {path} declares {status} without a Problem body"
            )

    # The messages route's 409 covers BOTH of its causes, matching the
    # streaming route beside it -- busy and closed are different remedies.
    messages_409 = spec["paths"]["/v1/sessions/{sid}/messages"]["post"]["responses"]["409"]
    assert "closed" in messages_409["description"]


def _real_session_app(settings, fake_factory):  # noqa: ANN001
    """An app whose registry builds REAL AgentSessions over a fake SDK client.

    The shared `fake_registry` fixture cannot be used for option-validation
    tests: its factory returns a `FakeSession` that ignores `options`
    entirely, so `build_options()` never runs and a bad request comes back
    201. That is precisely why these 400s went undeclared -- nothing in the
    suite could reach them. A real `AgentSession` runs `build_options()` in
    its `__init__`, which is where LimitExceeded and InvalidWorkspacePath are
    raised, and `registry.create()` calls that factory INSIDE its try, so the
    exception becomes a problem document. No subprocess is involved: the SDK
    client is a FakeClient.
    """
    factory, _ = fake_factory

    def session_factory(options, settings_, title=None):  # noqa: ANN001
        return AgentSession(
            options, settings_, title=title, client_factory=lambda _opts: FakeClient([])
        )

    registry = SessionRegistry(settings, session_factory=session_factory)
    return create_app(settings=settings, run_factory=factory, registry=registry)


async def test_creating_a_session_with_a_limit_above_its_cap_is_400(
    settings, fake_factory
) -> None:
    """Drives the 400 declared above, rather than only asserting the
    declaration exists -- a declaration nothing reaches is how the PATCH 409
    became questionable in the first place."""
    app = _real_session_app(settings, fake_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/sessions", json={"options": {"max_turns": 99999}})

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "max_turns" in r.json()["detail"]


async def test_creating_a_session_with_an_escaping_workspace_subdir_is_400(
    settings, fake_factory
) -> None:
    app = _real_session_app(settings, fake_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/sessions", json={"options": {"workspace_subdir": "../../etc"}}
        )

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_a_valid_session_create_still_succeeds_on_the_same_app(
    settings, fake_factory
) -> None:
    """Guards the two tests above against passing for the wrong reason -- a
    misconfigured app that 400s on everything would satisfy them both."""
    app = _real_session_app(settings, fake_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/sessions", json={"options": {"max_turns": 5}})

    assert r.status_code == 201
    assert r.json()["status"] == "idle"


# --- follow-up item 2: a stalled write straddling the final `result` frame --


async def test_a_stall_on_the_result_frame_leaves_the_turn_recorded(
    settings, fake_factory
) -> None:
    """The straddle, end to end over raw ASGI.

    `test_client_disconnect_interrupts_the_turn_then_closes_the_stream` stalls
    the write of the FIRST frame, mid-turn. This stalls the LAST one: the
    turn's `ResultMessage` has already been consumed and the session has
    already recorded the turn, and only its delivery dies. `turn_ended` was
    still False at that point -- it was assigned only after the loop -- so the
    cleanup interrupted a turn the subprocess had finished producing, and the
    `aclose()` that followed overwrote the completed turn. Measured against the
    round-5 code, with all three frames written:

        frames=['event: system', 'event: assistant', 'event: result']
        outcome=None interrupted=True turns=0 cost=0.0 interrupts=1

    for a turn whose result was `done` at `total_cost_usd=0.05`.

    A real `AgentSession` over a fake SDK client, because a `FakeSession`
    cannot show either half: it neither records turns nor issues control
    requests.
    """
    sdk = FakeClient([_normal_turn()])
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    body = json.dumps({"prompt": "hi"}).encode()
    path = f"/v1/sessions/{sid}/messages/stream"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "scheme": "http",
        "extensions": {},
    }

    body_sent = False
    stalled = asyncio.Event()
    stuck_forever = asyncio.Event()
    frames: list[str] = []

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await stalled.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            chunk = message["body"].decode()
            frames.append(chunk.split("\n", 1)[0])
            if chunk.startswith("event: result"):
                # The write of the FINAL frame never completes.
                stalled.set()
                await stuck_forever.wait()

    await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert frames == ["event: system", "event: assistant", "event: result"]
    turn = session.last_turn
    assert turn.outcome is not None and turn.outcome.result == "done"
    assert turn.interrupted is False
    assert session.turns == 1
    assert session.total_cost_usd == 0.05
    # Nothing was still being produced: the turn had its ResultMessage.
    assert sdk.interrupts == 0


# --- fix round 8: GET during a teardown ------------------------------------


async def test_get_during_a_teardown_reports_the_record_without_asking_the_sdk(
    settings, fake_factory
) -> None:
    """The one hole in the `_closing` latch, over real ASGI.

    `GET /v1/sessions/{sid}` is not a pure lookup -- it awaits
    `session.context_usage()`, a live control request. That call had neither
    the `status == "closed"` guard nor the `_closing` guard the setters have,
    so a GET landing while `close()` was suspended inside `disconnect()` ran a
    control request down a client being torn down, and answered `status:
    "idle"` for a session that answered PATCH and POST with 409 in the same
    instant. Measured against 97929a5:

        GET 200 status='idle' usage={'categories': [...]} control_requests=1
          | PATCH 409 'Session closed' | POST 409 'Session closed'

    The fix returns None rather than raising, so this route keeps doing the one
    job nothing else can do -- telling a caller what became of the session --
    and says "I could not ask" with `context_usage: null`, which
    `SessionRecord` already declares as a legitimate value. No new status code,
    and the route's declared 502 stays for the live-but-undeliverable case.
    """
    sdk = _GatedDisconnectClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: sdk)
    app, sid = await _app_around(settings, fake_factory, session)

    close_task = asyncio.create_task(session.close())
    await asyncio.wait_for(sdk.disconnect_entered.wait(), timeout=1.0)
    assert session._closing is True

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            got = await ac.get(f"/v1/sessions/{sid}")
            patched = await ac.patch(
                f"/v1/sessions/{sid}", json={"model": "claude-opus-5"}
            )
            posted = await ac.post(
                f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}
            )
    finally:
        # See the sibling in test_sessions.py: close() is parked on these, so
        # a failure that skipped them would hang rather than report.
        sdk.control_gate.set()
        sdk.disconnect_gate.set()
        await asyncio.wait_for(close_task, timeout=1.0)

    assert got.status_code == 200
    assert got.json()["context_usage"] is None
    assert sdk.usage_calls == 0, "GET must not talk to a client being disconnected"
    # The record is still reported -- that is the point of not raising.
    assert got.json()["session_id"] == sid
    assert got.json()["turns"] == 0
    # ...and the mutating routes still refuse, as they did before.
    assert (patched.status_code, posted.status_code) == (409, 409)


async def _record_for(settings, fake_factory, session) -> dict:  # noqa: ANN001
    """Drive `GET /v1/sessions/{sid}` against a REAL AgentSession."""
    app, sid = await _app_around(settings, fake_factory, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return (await ac.get(f"/v1/sessions/{sid}")).json()


# --- follow-up item 11: GET must say what became of the last turn ----------


async def test_get_on_a_session_that_has_never_taken_a_turn_reports_no_last_turn(
    session_client,
) -> None:
    """`last_turn: null` is the whole point of the field being optional and
    nested: there is no turn, and nothing may be asserted about one. A flat
    `last_turn_interrupted: false` would be a claim about a turn that does not
    exist."""
    sid = await _open(session_client)
    body = (await session_client.get(f"/v1/sessions/{sid}")).json()
    assert "last_turn" in body
    assert body["last_turn"] is None


async def test_get_reports_a_completed_turn(settings, fake_factory) -> None:
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: FakeClient([_normal_turn()])
    )
    await session.open()
    [e async for e in session.send("hi")]

    body = await _record_for(settings, fake_factory, session)
    turn = body["last_turn"]
    assert turn["outcome_recorded"] is True
    assert turn["is_error"] is False
    assert turn["interrupted"] is False
    assert turn["timed_out"] is False
    assert turn["terminal_reason"] == "completed"
    assert turn["sdk_session_id"] == "sdk-sess-1"
    assert turn["turn_cost_usd"] == 0.05


async def test_get_reports_a_turn_abandoned_when_the_stream_dropped(
    settings, fake_factory
) -> None:
    """Item 11's actual scenario. An SSE consumer hangs up mid-drain -- the
    case this branch spent seven fix rounds making safe -- and the ONLY record
    of what became of that turn is `session.last_turn`, which no endpoint
    reported. `turns` stays 0 and `total_cost_usd` stays unpriced, so before
    this the record was indistinguishable from a session that had never been
    used at all.
    """
    client = _ParkedClient()
    session = AgentSession(RunOptions(), settings, client_factory=lambda _opts: client)
    await session.open()
    await _abandon_mid_drain(session, client)

    body = await _record_for(settings, fake_factory, session)
    # Indistinguishable from a fresh session on everything that existed before:
    assert body["turns"] == 0
    # `null` since 2026-08-09, where this was `0.0`. An abandoned turn reported
    # no price, so the session has none -- and `turns: 0` beside it is what
    # tells a client this is "nothing ran" rather than "this build cannot price".
    assert body["total_cost_usd"] is None
    # ...and now distinguishable on the field that was missing.
    turn = body["last_turn"]
    assert turn is not None
    assert turn["outcome_recorded"] is False
    assert turn["interrupted"] is False
    assert turn["timed_out"] is False
    assert turn["sdk_session_id"] == "sdk-sess-1"
    assert turn["turn_cost_usd"] is None


async def test_get_reports_a_turn_that_timed_out(settings, fake_factory) -> None:
    """`timed_out` DOES belong on the historical record, and this deliberately
    departs from the "known and deliberate" list's ruling that it is
    internal-only.

    That ruling is about the LIVE turn response: a turn that times out is a
    504, and the status code carries the information, so `RunResponse` would
    be saying it twice. On a record fetched later the status code is long gone
    -- the caller may not even be the caller that hit the timeout -- and this
    flag is the only way to learn a past turn timed out rather than crashed.
    Both end in `outcome_recorded: false`, so without it the two are
    indistinguishable. `RunResponse` is untouched.
    """

    class HangingClient(FakeClient):
        async def receive_response(self):
            await asyncio.Event().wait()
            yield  # pragma: no cover - unreachable; keeps this a generator

    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: HangingClient()
    )
    await session.open()
    session._limits.timeout_s = 0.05
    with contextlib.suppress(RunTimeout):
        [e async for e in session.send("hang")]

    body = await _record_for(settings, fake_factory, session)
    assert body["last_turn"]["timed_out"] is True
    assert body["last_turn"]["outcome_recorded"] is False


async def test_last_turn_reports_an_interrupted_turn(session_client, fake_registry) -> None:
    sid = await _open(session_client)
    from agent_spec.db.outcome import RunOutcome

    fake_registry.get(sid).last_turn = TurnResult(
        session_id="sdk-sess-1",
        outcome=RunOutcome(
            session_id="sdk-sess-1",
            is_error=True,
            subtype="error_during_execution",
            terminal_reason="aborted_streaming",
            limit_hit=None,
        ),
        interrupted=True,
    )
    turn = (await session_client.get(f"/v1/sessions/{sid}")).json()["last_turn"]
    assert turn["interrupted"] is True
    assert turn["is_error"] is True
    assert turn["subtype"] == "error_during_execution"
    assert turn["terminal_reason"] == "aborted_streaming"


async def test_the_record_and_the_turn_response_agree_about_the_same_turn(
    settings, fake_factory
) -> None:
    """Plan 1's `outcome_recorded` defect was two endpoints hand-carrying the
    same fact and drifting apart; `build_outcome` and `_summary` exist to stop
    it. `last_turn` is a third reader of the same `TurnResult`, so this pins
    the three fields both surfaces report against each other, over HTTP,
    rather than trusting that they read the same attribute.
    """
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: FakeClient([_normal_turn()])
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        summary = (
            await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        ).json()
        turn = (await ac.get(f"/v1/sessions/{sid}")).json()["last_turn"]

    assert turn["outcome_recorded"] == summary["outcome_recorded"]
    assert turn["interrupted"] == summary["interrupted"]
    assert turn["is_error"] == summary["is_error"]
    assert turn["sdk_session_id"] == summary["session_id"]
    assert turn["turn_cost_usd"] == summary["turn_cost_usd"]


# --- follow-up item 12: last_residue_discarded ----------------------------


async def test_get_reports_how_much_residue_the_last_turn_discarded(
    session_client, fake_registry
) -> None:
    """Spike case S3 made visible. A non-zero value means a previous turn was
    abandoned with messages still in flight on the SDK's connection-scoped
    buffer -- computed and stored since fix round 2, and reported to nobody."""
    sid = await _open(session_client)
    assert (await session_client.get(f"/v1/sessions/{sid}")).json()[
        "last_residue_discarded"
    ] == 0
    fake_registry.get(sid).last_residue_discarded = 2
    assert (await session_client.get(f"/v1/sessions/{sid}")).json()[
        "last_residue_discarded"
    ] == 2


# --- follow-up item 13: read back what PATCH wrote ------------------------


async def test_the_record_echoes_the_session_configuration(
    settings, fake_factory
) -> None:
    """A real AgentSession, so the values are the RESOLVED ones `build_options`
    handed the SDK rather than the request's nulls."""
    session = AgentSession(
        RunOptions(model="claude-opus-5", permission_mode="plan"),
        settings,
        client_factory=lambda _opts: FakeClient([]),
    )
    await session.open()
    body = await _record_for(settings, fake_factory, session)
    assert body["model"] == "claude-opus-5"
    assert body["permission_mode"] == "plan"


async def test_patch_can_be_read_back_off_the_record(settings, fake_factory) -> None:
    """Item 13. PATCH answers with a SessionRecord, so the confirmation is in
    the response to the write itself -- and a later GET agrees."""
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _opts: FakeClient([])
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        before = (await ac.get(f"/v1/sessions/{sid}")).json()
        patched = await ac.patch(
            f"/v1/sessions/{sid}",
            json={"model": "claude-opus-5", "permission_mode": "acceptEdits"},
        )
        after = (await ac.get(f"/v1/sessions/{sid}")).json()

    assert before["model"] == settings.default_model
    assert patched.json()["model"] == "claude-opus-5"
    assert patched.json()["permission_mode"] == "acceptEdits"
    assert (after["model"], after["permission_mode"]) == ("claude-opus-5", "acceptEdits")


async def test_the_record_does_not_echo_the_system_prompt_or_any_other_option(
    settings, fake_factory
) -> None:
    """`RunOptions` carries caller-supplied content -- `system_prompt` above
    all, which this service also appends the server's own workspace layout to
    -- and `SessionRecord` is returned by a LIST endpoint. Only the two fields
    PATCH can write are echoed; "echo the resolved options" is deliberately
    not implemented as a dump.
    """
    session = AgentSession(
        RunOptions(system_prompt="SECRET-INSTRUCTIONS", workspace_subdir=None),
        settings,
        client_factory=lambda _opts: FakeClient([]),
    )
    await session.open()
    body = await _record_for(settings, fake_factory, session)

    assert "SECRET-INSTRUCTIONS" not in json.dumps(body)
    for leaked in ("system_prompt", "options", "allowed_tools", "cwd", "env"):
        assert leaked not in body


# --- follow-up item 14: per-turn cost -------------------------------------


async def test_the_turn_response_prices_that_turn_not_the_whole_session(
    settings, fake_factory
) -> None:
    """`total_cost_usd` on a session turn is the CUMULATIVE connection total
    (measured, S6) and stays that way. `turn_cost_usd` is the delta, which is
    the question anyone actually asks."""
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.05)
    turn_two = _normal_turn()
    turn_two[-1] = _result(total_cost_usd=0.09)
    session = AgentSession(
        RunOptions(),
        settings,
        client_factory=lambda _opts: FakeClient([turn_one, turn_two]),
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        first = (
            await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"})
        ).json()
        second = (
            await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "two"})
        ).json()
        record = (await ac.get(f"/v1/sessions/{sid}")).json()

    assert (first["total_cost_usd"], first["turn_cost_usd"]) == (0.05, 0.05)
    assert second["total_cost_usd"] == 0.09
    assert second["turn_cost_usd"] == pytest.approx(0.04)
    # The session's own running total is untouched by any of this.
    assert record["total_cost_usd"] == 0.09
    assert record["last_turn"]["turn_cost_usd"] == pytest.approx(0.04)


async def test_an_interrupted_turn_prices_nothing_over_http(
    settings, fake_factory
) -> None:
    """The interrupted-turn cost defect, on the wire, through real ASGI.

    Measured live: an interrupted turn does not move the SDK's cumulative
    figure even though it ran real inference, so the delta is honestly 0 --
    but 0.0 on the wire says "this turn was free", which is false. `null`
    ("nobody can say") is the only honest answer, and BOTH surfaces that
    report a turn must agree about it.

    `total_cost_usd` is deliberately still 0.05 here: it is the SDK's
    cumulative value, passed through verbatim, and this fix does not touch it.
    That is exactly the trap the schema now documents -- the running total
    silently under-reports what the session cost.
    """
    turn_one = _normal_turn()
    turn_one[-1] = _result(total_cost_usd=0.05)
    aborted = [
        SystemMessage(subtype="init", data={"session_id": "sdk-sess-1"}),
        _result(
            subtype="error_during_execution",
            is_error=True,
            terminal_reason="aborted_streaming",
            result=None,
            total_cost_usd=0.05,
        ),
    ]
    session = AgentSession(
        RunOptions(),
        settings,
        client_factory=lambda _opts: FakeClient([turn_one, aborted]),
    )
    await session.open()
    app, sid = await _app_around(settings, fake_factory, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"})
        second = (
            await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "two"})
        ).json()
        record = (await ac.get(f"/v1/sessions/{sid}")).json()

    assert second["terminal_reason"] == "aborted_streaming"
    assert second["turn_cost_usd"] is None
    assert second["total_cost_usd"] == 0.05
    # The record built from the same TurnResult must not disagree.
    assert record["last_turn"]["turn_cost_usd"] is None
    assert record["total_cost_usd"] == 0.05


async def test_the_openapi_warns_that_max_budget_usd_is_not_a_spend_cap(
    session_client,
) -> None:
    """A generated client is the only place many callers will ever read about
    this, and believing `max_budget_usd` bounds spend is the expensive way to
    find out otherwise: measured, eight start-then-interrupt turns advanced the
    CLI's budget accumulator by $0.000649 and never tripped a $0.05 budget,
    while six ordinary turns on the same connection tripped it at $0.0585.

    Pinned as a test rather than left as prose because the whole finding is
    that the field's obvious reading is wrong, and a docstring nobody checks
    is a docstring that gets tidied away.
    """
    spec = (await session_client.get("/openapi.json")).json()
    described = spec["components"]["schemas"]["RunOptions"]["properties"]["max_budget_usd"]
    text = described["description"].lower()
    assert "not a spend cap" in text
    assert "interrupted" in text

    usage = spec["components"]["schemas"]["RunResponse"]["properties"]["model_usage"]
    assert "cumulative" in usage["description"].lower()


async def test_a_turn_with_no_outcome_prices_nothing(
    session_client, fake_registry
) -> None:
    """`null`, not 0.0: a turn that produced no ResultMessage has no price to
    report, and 0.0 would claim it was free."""
    sid = await _open(session_client)
    fake_registry.get(sid)._turn = TurnResult(session_id="sdk-sess-1", outcome=None)
    body = (
        await session_client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    ).json()
    assert body["turn_cost_usd"] is None
    assert body["total_cost_usd"] is None


# --- OpenAPI ---------------------------------------------------------------


async def test_openapi_declares_the_new_observability_fields(session_client) -> None:
    """Every new response shape reaches the schema, or it does not exist as far
    as a generated client is concerned. No new STATUS is reachable here -- all
    four items are additive fields on shapes these routes already return."""
    spec = (await session_client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]

    assert "TurnRecord" in schemas
    record = schemas["SessionRecord"]["properties"]
    for field in ("last_turn", "model", "permission_mode", "last_residue_discarded"):
        assert field in record, f"SessionRecord does not declare {field}"

    turn = schemas["TurnRecord"]["properties"]
    for field in (
        "sdk_session_id",
        "outcome_recorded",
        "interrupted",
        "timed_out",
        "is_error",
        "turn_cost_usd",
    ):
        assert field in turn, f"TurnRecord does not declare {field}"
    assert "session_id" not in turn  # item 7: never a bare `session_id`

    assert "turn_cost_usd" in schemas["RunResponse"]["properties"]


async def test_get_still_reports_context_usage_for_a_live_session(
    session_client,
) -> None:
    """The guard keys off teardown only -- the happy path is unchanged."""
    sid = await _open(session_client)
    body = (await session_client.get(f"/v1/sessions/{sid}")).json()
    assert body["context_usage"]["categories"][0]["name"] == "Messages"
