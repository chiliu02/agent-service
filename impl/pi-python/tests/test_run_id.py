"""A caller's `run_id`, and a turn that outlives its reader (`PI-67`). **Free.**

**The disconnect tests need a real socket.** `TestClient` drains a response to
its end before handing it back, so a reader that goes away cannot be expressed
through it. These start uvicorn on loopback, send the request on a raw socket
and close it mid-turn -- which is exactly what a relay that restarts does.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import urllib.request

import pytest
import uvicorn
from fastapi.testclient import TestClient

import agent_service.api as api
from agent_service.api import _run_turn, create_app
from agent_service.config import Settings
from agent_service.registry import Registry
from test_persistence import Capturing

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_dir_root": tmp_path / "agent-dirs",
        "session_store": tmp_path / "sessions",
        "pi_binary": FAKE,
        "require_credentials": False,
    }
    settings = Settings(**{**base, **kwargs})
    # Made here as well as by the lifespan, for the tests that skip it.
    for path in (settings.workspace_dir, settings.agent_dir_root, settings.session_store):
        path.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Capturing:
    """What every app built after this records into, with no database."""
    capturing = Capturing()
    monkeypatch.setattr(api, "NULL_RECORDER", capturing)
    return capturing


@pytest.fixture
def client(tmp_path: Path, recorder: Capturing) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def _open(client: TestClient) -> str:
    return client.post("/v1/sessions", json={}).json()["session_id"]


# --- the id is the caller's --------------------------------------------------

@pytest.mark.anyio
async def test_a_turn_is_recorded_under_the_callers_run_id(tmp_path: Path) -> None:
    recorder = Capturing()
    settings = _settings(tmp_path)
    session = Registry(settings, recorder).create()
    await _run_turn(settings, session, "say hello", recorder, run_id="relay-1")
    assert recorder.started[0]["run_id"] == "relay-1"
    assert recorder.finished[0]["run_id"] == "relay-1"
    assert {rid for rid, _ in recorder.events} == {"relay-1"}


def test_a_streamed_turn_is_recorded_under_the_callers_run_id(
    client: TestClient, recorder: Capturing,
) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages/stream",
                           json={"prompt": "hi", "run_id": "relay-2"})
    assert response.status_code == 200
    assert recorder.started[0]["run_id"] == "relay-2"
    assert recorder.finished[0]["run_id"] == "relay-2"


def test_without_a_run_id_the_service_still_makes_one(
    client: TestClient, recorder: Capturing,
) -> None:
    sid = _open(client)
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    assert recorder.started[0]["run_id"]


# --- an id names one turn, once ----------------------------------------------

@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_used_run_id_is_a_409_before_the_turn_starts(
    client: TestClient, recorder: Capturing, route: str,
) -> None:
    """On the stream route too it is a STATUS CODE, never an in-band frame."""
    sid = _open(client)
    first = client.post(f"/v1/sessions/{sid}/{route}",
                        json={"prompt": "hi", "run_id": "once"})
    assert first.status_code == 200
    again = client.post(f"/v1/sessions/{sid}/{route}",
                        json={"prompt": "hi", "run_id": "once"})
    assert again.status_code == 409
    assert again.json()["title"] == "Run id in use"
    assert again.json()["type"].endswith("/run-id-in-use")
    assert len(recorder.started) == 1, "the refused turn was started"


def test_an_id_is_used_across_sessions_and_across_routes(client: TestClient) -> None:
    one, two = _open(client), _open(client)
    assert client.post(f"/v1/sessions/{one}/messages",
                       json={"prompt": "hi", "run_id": "x"}).status_code == 200
    again = client.post(f"/v1/sessions/{two}/messages/stream",
                        json={"prompt": "hi", "run_id": "x"})
    assert again.status_code == 409


def test_an_id_used_by_a_failed_turn_stays_used(client: TestClient) -> None:
    """The agent was reached, so the turn happened, however it ended."""
    sid = _open(client)
    failed = client.post(f"/v1/sessions/{sid}/messages",
                         json={"prompt": "fail:boom", "run_id": "f"})
    assert failed.status_code == 502
    again = client.post(f"/v1/sessions/{sid}/messages",
                        json={"prompt": "hi", "run_id": "f"})
    assert again.json()["title"] == "Run id in use"


def test_a_malformed_run_id_is_a_422(client: TestClient) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages",
                           json={"prompt": "hi", "run_id": "has a space"})
    assert response.status_code == 422


@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_busy_refusal_gives_the_id_back(client: TestClient, route: str) -> None:
    """No turn started under the id, so the caller may send the same turn again."""
    sid = _open(client)
    session = client.app.state.registry.get(sid)
    # On the app's own loop: the lock belongs to it.
    client.portal.call(session.lock.acquire)
    busy = client.post(f"/v1/sessions/{sid}/{route}",
                       json={"prompt": "hi", "run_id": "b"})
    assert busy.status_code == 409
    assert busy.json()["title"] == "A turn is already running"
    client.portal.call(_release, session.lock)
    again = client.post(f"/v1/sessions/{sid}/{route}",
                        json={"prompt": "hi", "run_id": "b"})
    assert again.status_code == 200


async def _release(lock) -> None:  # noqa: ANN001
    lock.release()


# --- a turn that outlives its reader -----------------------------------------

@contextmanager
def _served(app) -> Iterator[int]:  # noqa: ANN001
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "no server"
        time.sleep(0.02)
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _stream_then_hang_up(port: int, sid: str, body: dict) -> bytes:
    """Send a stream request, read until a frame arrives, then close the socket."""
    data = json.dumps(body).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
        conn.sendall(
            f"POST /v1/sessions/{sid}/messages/stream HTTP/1.1\r\nHost: t\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n"
            .encode() + data
        )
        received = b""
        while b"event: event" not in received:
            chunk = conn.recv(4096)
            assert chunk, "the stream closed before its first frame"
            received += chunk
    return received


def _post(port: int, path: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def _wait_idle(session, seconds: float = 20.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + seconds
    while session.lock.locked() or session.status != "idle":
        assert time.monotonic() < deadline, "the turn never ended"
        time.sleep(0.05)


def test_continue_runs_the_turn_to_its_end_with_no_reader(
    tmp_path: Path, recorder: Capturing,
) -> None:
    app = create_app(_settings(tmp_path))
    with _served(app) as port:
        sid = _post(port, "/v1/sessions", {})[1]["session_id"]
        session = app.state.registry.get(sid)
        head = _stream_then_hang_up(port, sid, {
            "prompt": "slow:2", "run_id": "relay-c", "on_disconnect": "continue"})
        assert head.startswith(b"HTTP/1.1 200")
        # The reader is gone and the agent is still working.
        assert session.lock.locked(), "the turn ended with its reader"
        _wait_idle(session)

        assert session.turns == 1, "the turn did not complete"
        assert session.last_turn is not None
        assert session.last_turn.interrupted is False
        assert recorder.finished[0]["run_id"] == "relay-c"
        assert recorder.finished[0]["interrupted"] is False
        assert recorder.finished[0]["outcome"] is not None
        # The session takes the next turn: nothing was stranded.
        assert _post(port, f"/v1/sessions/{sid}/messages", {"prompt": "hi"})[0] == 200


def test_the_default_still_interrupts_when_the_reader_goes(
    tmp_path: Path, recorder: Capturing,
) -> None:
    """`PI-38` is unchanged: no `on_disconnect` means the turn is killed."""
    app = create_app(_settings(tmp_path))
    with _served(app) as port:
        sid = _post(port, "/v1/sessions", {})[1]["session_id"]
        session = app.state.registry.get(sid)
        _stream_then_hang_up(port, sid, {"prompt": "slow:30", "run_id": "relay-d"})
        _wait_idle(session, seconds=10)

        assert session.turns == 0
        assert session.last_turn is not None
        assert session.last_turn.interrupted is True
        assert recorder.finished[0]["run_id"] == "relay-d"
        assert recorder.finished[0]["interrupted"] is True


def test_the_non_stream_route_accepts_on_disconnect(client: TestClient) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages",
                           json={"prompt": "hi", "on_disconnect": "continue"})
    assert response.status_code == 200


def test_both_turn_routes_declare_the_run_id_conflict(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for route in ("/v1/sessions/{sid}/messages", "/v1/sessions/{sid}/messages/stream"):
        assert "run_id" in paths[route]["post"]["responses"]["409"]["description"]
