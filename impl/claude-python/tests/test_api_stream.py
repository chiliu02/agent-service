import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from httpx import ASGITransport, AsyncClient

from agent_service.api import create_app
from agent_service.errors import RunTimeout
from agent_service.options import InvalidWorkspacePath, LimitExceeded
from agent_service.runner import Run
from tests.conftest import DEFAULT_EVENTS, DEFAULT_OUTCOME


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event_name, payload) pairs."""
    out: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        name, payload = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
        if name is not None:
            out.append((name, payload or {}))
    return out


async def test_stream_emits_one_event_per_message_then_done(client) -> None:
    response = await client.post("/v1/query/stream", json={"prompt": "hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["system", "assistant", "result", "done"]
    assert events[1][1]["content"][0]["name"] == "Read"


async def test_done_event_carries_the_run_summary(client) -> None:
    response = await client.post("/v1/query/stream", json={"prompt": "hello"})
    name, payload = parse_sse(response.text)[-1]
    assert name == "done"
    assert payload["session_id"] == "sess-test"
    assert payload["result"] == "done"
    assert payload["events"] == []  # summary only; events were already streamed
    assert payload["outcome_recorded"] is True


async def test_done_event_reports_outcome_recorded_false_when_no_outcome(
    client, fake_factory
) -> None:
    _, state = fake_factory
    state["outcome"] = None
    response = await client.post("/v1/query/stream", json={"prompt": "hello"})
    name, payload = parse_sse(response.text)[-1]
    assert name == "done"
    assert payload["outcome_recorded"] is False


class _FailsAfterSomeEventsRun(Run):
    """Raises from within events() itself, optionally after yielding some real
    events first -- i.e. a failure discovered during iteration, after the
    factory has already returned successfully and (for a real request) the
    200 and SSE headers are already on the wire. This is the case the
    in-band `event: error` design exists for, and it is what actually
    happens in production: RunTimeout and SDK errors are raised by
    `Run.events()`, never by `create_run`/the factory (I3 review finding --
    see api.py's `run_query_stream`, which now hoists the factory() call
    above the stream so pure request-validation errors like LimitExceeded and
    InvalidWorkspacePath, which genuinely are raised by the factory, become a
    real 400 instead)."""

    def __init__(self, events: list[dict], exc: Exception) -> None:
        self._events = events
        self._exc = exc
        self.session_id = None
        self.outcome = None

    async def events(self) -> AsyncIterator[dict]:  # type: ignore[override]
        for event in self._events:
            yield event
        raise self._exc


async def test_mid_stream_failure_emits_an_error_event(settings) -> None:
    """RunTimeout raised the moment events() starts (zero events yielded
    first) must still arrive in-band as `event: error` on a 200 -- not as a
    504 problem document. It is only pure request validation (LimitExceeded,
    InvalidWorkspacePath), raised by the factory before iteration ever
    starts, that gets to become a real status code; see the two
    `..._on_stream_route_is_400_problem` tests below for that case."""

    def factory(req, cfg):
        return _FailsAfterSomeEventsRun([], RunTimeout("exceeded 600s"))

    app = create_app(settings=settings, run_factory=factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/v1/query/stream", json={"prompt": "hi"})

    # The stream has already begun, so the HTTP status is 200; the failure
    # is reported in-band.
    assert response.status_code == 200
    name, payload = parse_sse(response.text)[-1]
    assert name == "error"
    assert payload["status"] == 504


async def test_limit_exceeded_on_stream_route_is_400_problem(client, fake_factory) -> None:
    """I3: LimitExceeded is pure request validation, raised synchronously by
    the factory before the response is committed -- it must be a real 400,
    exactly like /v1/query, not an in-band `event: error` on a 200."""
    _, state = fake_factory
    state["raise"] = LimitExceeded("max_turns", 9999, 200)
    try:
        response = await client.post("/v1/query/stream", json={"prompt": "hi"})
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert "max_turns" in body["detail"]
    finally:
        state["raise"] = None


async def test_invalid_workspace_subdir_on_stream_route_is_400_problem(
    client, fake_factory
) -> None:
    """Same as above for InvalidWorkspacePath -- also raised by the factory
    (build_options -> resolve_workspace) before any byte is streamed."""
    _, state = fake_factory
    state["raise"] = InvalidWorkspacePath("'../escape' resolves outside the workspace root")
    try:
        response = await client.post(
            "/v1/query/stream",
            json={"prompt": "hi", "options": {"workspace_subdir": "../escape"}},
        )
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
    finally:
        state["raise"] = None


class _SlowRun(Run):
    """Yields events with a real delay between them, so a test can observe
    whether the HTTP layer forwards each frame as it is produced (streamed)
    or only after the generator finishes (buffered)."""

    def __init__(self, events: list[dict], outcome, delay: float) -> None:
        self._events = events
        self._outcome = outcome
        self._delay = delay
        self.session_id = outcome.session_id if outcome else None
        self.outcome = None

    async def events(self) -> AsyncIterator[dict]:  # type: ignore[override]
        for event in self._events:
            await asyncio.sleep(self._delay)
            yield event
        self.outcome = self._outcome


_SERVER_STARTUP_TIMEOUT = 5.0
_SERVER_SHUTDOWN_TIMEOUT = 5.0


@asynccontextmanager
async def _running_server(app) -> AsyncIterator[int]:
    """Serve `app` on a real loopback socket and yield the bound port.

    httpx's `ASGITransport` cannot be used to observe streaming: it calls
    `await self.app(scope, receive, send)` to full completion and only then
    builds the `Response` from the collected body parts (see
    `httpx._transports.asgi.ASGITransport.handle_async_request`). A fully
    buffered handler and a genuinely streaming one are indistinguishable
    through that transport, since it never lets the client see anything
    before the ASGI app has finished. A real socket, driven by uvicorn, does
    not have this problem: each `send()` call is written to the socket as it
    happens, matching production behaviour.
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        # #28 (final review): if uvicorn ever fails during startup, it
        # sys.exits() inside `task` and `server.started` is never set --
        # without a timeout this loop spins forever and the test HANGS
        # instead of failing. Bound it, and if the server task has already
        # died, surface its real exception instead of a bare TimeoutError.
        async def _wait_until_started() -> None:
            while not server.started:
                await asyncio.sleep(0.005)

        try:
            await asyncio.wait_for(_wait_until_started(), timeout=_SERVER_STARTUP_TIMEOUT)
        except TimeoutError:
            if task.done():
                task.result()  # re-raises whatever actually killed the server
            raise
        port = server.servers[0].sockets[0].getsockname()[1]
        yield port
    finally:
        server.should_exit = True
        # Same reasoning as above: a `task` that never notices should_exit
        # (or is wedged some other way) must fail this test, not hang it.
        await asyncio.wait_for(task, timeout=_SERVER_SHUTDOWN_TIMEOUT)


async def test_stream_delivers_frames_incrementally_not_buffered(settings) -> None:
    """Proves the defining property of this endpoint: a client reading the
    response as it arrives sees frames spread out over time, with each event
    arriving shortly after the fake run produces it -- not all four frames
    delivered back-to-back once the generator has fully finished."""
    delay = 0.03
    fresh_events = [dict(e) for e in DEFAULT_EVENTS]  # never mutate the shared dicts
    outcome = dataclasses.replace(DEFAULT_OUTCOME)

    def factory(req, cfg):
        return _SlowRun(fresh_events, outcome, delay)

    app = create_app(settings=settings, run_factory=factory)

    arrival_times: list[float] = []
    async with _running_server(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            async with ac.stream(
                "POST", "/v1/query/stream", json={"prompt": "hello"}
            ) as response:
                assert response.status_code == 200
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        if block.strip():
                            arrival_times.append(time.monotonic())

    # 3 events (system, assistant, result) + the terminal done frame.
    assert len(arrival_times) == 4

    # A buffered implementation would flush all 4 frames back-to-back in one
    # burst once the generator finished, so every gap would be ~0. A
    # streaming implementation instead pauses for `delay` between each of the
    # 3 events (no extra sleep before the final `done` frame), so the first
    # two gaps should each be a meaningful fraction of `delay`.
    gaps = [arrival_times[i] - arrival_times[i - 1] for i in range(1, len(arrival_times))]
    assert gaps[0] >= delay * 0.5  # assistant arrives well after system
    assert gaps[1] >= delay * 0.5  # result arrives well after assistant

    # The first and last frame are genuinely spread apart in time, not
    # delivered as one blob once the generator completes.
    assert arrival_times[-1] - arrival_times[0] >= delay


async def test_failure_after_events_already_streamed_emits_error_not_done(
    settings,
) -> None:
    early_events = [
        {"seq": 1, "type": "system", "subtype": "init", "content": None},
        {
            "seq": 2,
            "type": "assistant",
            "subtype": None,
            "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
        },
    ]

    def factory(req, cfg):
        return _FailsAfterSomeEventsRun(early_events, RunTimeout("exceeded 600s"))

    app = create_app(settings=settings, run_factory=factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/v1/query/stream", json={"prompt": "hi"})

    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == ["system", "assistant", "error"]
    assert "done" not in names
    assert events[-1][1]["status"] == 504


async def test_openapi_documents_the_stream_route(client) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert "/v1/query/stream" in spec["paths"]


# --- I1 (final review): client-disconnect teardown ------------------------


async def test_aclose_on_an_already_exhausted_async_generator_is_a_no_op() -> None:
    """Documents the guarantee the I1 fix relies on: attaching
    `background=BackgroundTask(stream.aclose)` to *every* response -- not
    only the ones that get disconnected -- is safe because closing an async
    generator that has already run to completion (StopAsyncIteration already
    raised) does nothing: no exception, no re-entry into the generator body.
    This is what makes the fix inert on the normal-completion path."""

    async def gen():
        yield 1

    g = gen()
    assert [x async for x in g] == [1]
    await g.aclose()  # already exhausted; must be a no-op
    await g.aclose()  # calling it again must also be a no-op


class _StallingRun(Run):
    """Yields exactly one event, then sits suspended at that yield forever --
    standing in for the SDK subprocess still being mid-run when the client
    goes away. `closed` flips to True only when this generator's `finally`
    actually runs, i.e. only when something explicitly (a)closes it."""

    def __init__(self) -> None:
        self.session_id = None
        self.outcome = None
        self.closed = False

    async def events(self) -> AsyncIterator[dict]:  # type: ignore[override]
        try:
            yield {"seq": 1, "type": "system", "subtype": "init", "content": None}
        finally:
            self.closed = True


async def test_client_disconnect_closes_the_events_stream_without_gc(settings) -> None:
    """The realistic stalled-client case the reviewer measured: cancellation
    arrives while `generate()` (and the `Run.events()` stream it drives) is
    suspended at its `yield` -- i.e. between producing a chunk and Starlette
    actually writing it to the socket -- not while raising out of an
    in-flight await inside the generator itself. That distinction matters: it
    means the disconnect is delivered while Starlette's own `send()` call is
    in flight, outside of both generators' frames, so neither ever unwinds
    through a `finally` on its own -- only the explicit `background=
    BackgroundTask(stream.aclose)` closes it deterministically.

    httpx's `ASGITransport` cannot observe or inject this at all: it drains
    the app to completion before ever building a `Response`, so there is no
    way to simulate a disconnect mid-stream through it (see
    `_running_server`'s docstring above for the same limitation applied to
    buffering). This drives the raw ASGI callable directly instead.

    Critically, this asserts closure immediately after `app(...)` returns --
    with NO `gc.collect()` call anywhere in this test. Pre-fix, closure only
    ever happened via the cyclic GC finding the reference cycle (confirmed
    manually during this review: without the `background=` argument, this
    assertion fails after `app(...)` returns and only starts passing once a
    `gc.collect()` is inserted before it).
    """
    run_holder: dict[str, _StallingRun] = {}

    def factory(req, cfg):
        run = _StallingRun()
        run_holder["run"] = run
        return run

    app = create_app(settings=settings, run_factory=factory)

    body = json.dumps({"prompt": "hi"}).encode()
    scope = {
        "type": "http",
        # matches uvicorn's h11 protocol impl exactly (asgi.spec_version
        # "2.3") -- below Starlette's (2, 4) threshold, so StreamingResponse
        # takes the listen_for_disconnect/cancel-scope path this test
        # exercises, not the newer try/except-OSError shortcut.
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/v1/query/stream",
        "raw_path": b"/v1/query/stream",
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
        # The disconnect listener's second (and later) call: only report the
        # disconnect once the first SSE chunk is actually in flight to the
        # (about-to-vanish) client -- i.e. once `generate()` is genuinely
        # suspended at its yield, not mid-factory-call or mid-first-await.
        await send_in_progress.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            send_in_progress.set()
            # Simulate a write to a client that has gone away: this await
            # never completes on its own. The task group's cancellation
            # (triggered by the disconnect above) is what ends it.
            await stuck_forever.wait()

    await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert run_holder["run"].closed is True
