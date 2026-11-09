"""A caller-chosen `run_id`, and a stream turn that outlives its reader. CX-71.

The HTTP half runs a real uvicorn on loopback for the disconnect cases: an
in-process transport drains a response to its end, so it cannot drop a reader
mid-turn, which is the whole thing under test.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import SessionRegistry
from agent_service.sessions import TurnOutcome
from agent_spec.openapi.schemas import RunOptions
from agent_spec.runs import RUN_ID_IN_USE_TITLE


class _SlowSession:
    """A session whose turn takes `delay` seconds, and says how it ended."""

    sdk_session_id = "11111111-2222-3333-4444-555555555555"

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.ended: list[str] = []

    async def open(self, options, resume=None) -> None:  # noqa: ANN001, ARG002
        return None

    async def send(self, prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG002
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            # Where the real session sends CX-54's interrupt.
            self.ended.append("cancelled")
            raise
        self.ended.append("completed")
        return TurnOutcome(status="completed", duration_ms=1, final_response="ok")

    async def interrupt(self) -> bool:
        return False

    def context(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _Recorder:
    """The run ids that `start_run` and `finish_run` were handed."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []

    def start_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        self.started.append(run_id)

    def append_event(self, run_id, event) -> None:  # noqa: ANN001, ARG002
        return None

    def finish_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        self.finished.append(run_id)

    def session_opened(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None

    def session_closed(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(tmp_path, delay: float = 0.0):  # noqa: ANN001, ANN202
    settings = Settings(
        require_credentials=False,
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=tmp_path / "home",
    )
    recorder = _Recorder()
    made: list[_SlowSession] = []

    def factory(options, subdir):  # noqa: ANN001, ANN202, ARG001
        made.append(_SlowSession(delay))
        return made[-1]

    registry = SessionRegistry(settings, session_factory=factory, recorder=recorder)
    return create_app(settings, registry), registry, recorder, made


# --- the id: claimed, refused when used, given back when refused early -------


def test_the_run_is_recorded_under_the_callers_id(tmp_path) -> None:  # noqa: ANN001
    app, _registry, recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        r = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi", "run_id": "relay-1"})
        assert r.status_code == 200, r.text
    assert recorder.started == ["relay-1"]
    assert recorder.finished == ["relay-1"]


def test_without_an_id_the_service_still_makes_one(tmp_path) -> None:  # noqa: ANN001
    app, _registry, recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        assert c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}).status_code == 200
    assert len(recorder.started) == 1 and recorder.started[0]


@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_used_id_is_409_with_the_platform_title(tmp_path, route) -> None:  # noqa: ANN001
    app, _registry, recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        body = {"prompt": "hi", "run_id": "once"}
        assert c.post(f"/v1/sessions/{sid}/messages", json=body).status_code == 200
        r = c.post(f"/v1/sessions/{sid}/{route}", json=body)
    # A real status on the stream route too: it is refused before the 200.
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == RUN_ID_IN_USE_TITLE
    assert r.json()["type"].endswith("/run-id-in-use")
    assert recorder.started == ["once"], "the refused turn must not start"


def test_an_id_stays_used_when_its_turn_fails(tmp_path) -> None:  # noqa: ANN001
    """A turn that started may have changed files, so its id is spent."""
    app, registry, _recorder, made = _app(tmp_path)

    async def broken(prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG001
        raise RuntimeError("the agent broke")

    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        made[-1].send = broken
        body = {"prompt": "hi", "run_id": "spent"}
        assert c.post(f"/v1/sessions/{sid}/messages", json=body).status_code == 500
        r = c.post(f"/v1/sessions/{sid}/messages", json=body)
    assert r.status_code == 409
    assert r.json()["title"] == RUN_ID_IN_USE_TITLE
    assert r.json()["type"].endswith("/run-id-in-use")


@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_busy_refusal_wins_and_does_not_spend_the_id(tmp_path, route) -> None:  # noqa: ANN001
    """The session is resolved first, so a busy session is still `Session
    busy` -- and the id named no turn, so the same send succeeds later."""
    app, registry, recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        body = {"prompt": "hi", "run_id": "retry-me"}
        lock = registry.get(sid).turn_lock
        c.portal.call(lock.acquire)
        try:
            r = c.post(f"/v1/sessions/{sid}/{route}", json=body)
        finally:
            lock.release()
        assert r.status_code == 409
        assert r.json()["title"] == "Session busy"
        assert c.post(f"/v1/sessions/{sid}/messages", json=body).status_code == 200
    assert recorder.started == ["retry-me"]


def test_an_unknown_session_is_404_and_does_not_spend_the_id(tmp_path) -> None:  # noqa: ANN001
    app, _registry, _recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        body = {"prompt": "hi", "run_id": "first"}
        assert c.post("/v1/sessions/nope/messages", json=body).status_code == 404
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        assert c.post(f"/v1/sessions/{sid}/messages", json=body).status_code == 200


def test_a_malformed_id_is_422(tmp_path) -> None:  # noqa: ANN001
    app, _registry, _recorder, _made = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        r = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi", "run_id": "a b"})
    assert r.status_code == 422


# --- a reader that goes ---------------------------------------------------------


class _Server:
    """The app on a real loopback socket, in a thread."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> int:
        self.thread.start()
        while not self.server.started:
            assert self.thread.is_alive(), "the server did not start"
            time.sleep(0.02)
        return self.server.servers[0].sockets[0].getsockname()[1]

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.server.should_exit = True
        self.thread.join(10)


def _post_and_drop(port: int, path: str, body: dict, hold: float) -> None:
    """Send a request, then close the socket before the turn can end."""
    data = json.dumps(body).encode()
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(
            f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(data)}\r\n\r\n".encode() + data
        )
        time.sleep(hold)


def _wait_for(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _session(port: int) -> str:
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/sessions", data=b"{}",
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as r:  # noqa: S310 - loopback only
        return json.load(r)["session_id"]


def test_continue_lets_a_stream_turn_outlive_its_reader(tmp_path) -> None:  # noqa: ANN001
    app, registry, recorder, made = _app(tmp_path, delay=1.0)
    with _Server(app) as port:
        sid = _session(port)
        _post_and_drop(
            port, f"/v1/sessions/{sid}/messages/stream",
            {"prompt": "hi", "run_id": "outlives", "on_disconnect": "continue"},
            hold=0.3,
        )
        # Still under way after the reader went, and the session still busy.
        assert made[-1].ended == []
        assert registry.get(sid).turn_lock.locked()
        assert _wait_for(lambda: made[-1].ended == ["completed"])
        assert _wait_for(lambda: not registry.get(sid).turn_lock.locked())
    assert recorder.finished == ["outlives"]


def test_by_default_a_reader_that_goes_still_stops_the_turn(tmp_path) -> None:  # noqa: ANN001
    """CX-54, unchanged: without `continue` the turn is cancelled, which is
    where the real session sends its interrupt."""
    app, registry, _recorder, made = _app(tmp_path, delay=1.0)
    with _Server(app) as port:
        sid = _session(port)
        _post_and_drop(
            port, f"/v1/sessions/{sid}/messages/stream", {"prompt": "hi"}, hold=0.3
        )
        assert _wait_for(lambda: made[-1].ended == ["cancelled"])
        assert _wait_for(lambda: not registry.get(sid).turn_lock.locked())


def test_the_non_stream_route_runs_on_whatever_on_disconnect_says(tmp_path) -> None:  # noqa: ANN001
    """It reads the whole turn inside the request, so the field changes
    nothing there: measured on 2026-10-23 and pinned here."""
    app, registry, recorder, made = _app(tmp_path, delay=1.0)
    with _Server(app) as port:
        sid = _session(port)
        _post_and_drop(
            port, f"/v1/sessions/{sid}/messages",
            {"prompt": "hi", "run_id": "plain", "on_disconnect": "interrupt"},
            hold=0.3,
        )
        assert _wait_for(lambda: made[-1].ended == ["completed"])
    assert recorder.finished == ["plain"]


@pytest.mark.anyio
async def test_the_registry_uses_a_given_id_and_mints_one_otherwise(tmp_path) -> None:  # noqa: ANN001
    recorder = _Recorder()
    registry = SessionRegistry(
        Settings(require_credentials=False, require_mounts=False, workspace_dir=tmp_path),
        session_factory=lambda options, subdir: _SlowSession(0.0),
        recorder=recorder,
    )
    sid = await registry.create(RunOptions())
    await registry.send(sid, "a", RunOptions(), run_id="given")
    await registry.send(sid, "b", RunOptions())
    assert recorder.started[0] == "given"
    assert recorder.started[1] and recorder.started[1] != "given"
