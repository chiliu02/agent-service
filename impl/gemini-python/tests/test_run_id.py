"""A caller's `run_id`, and a stream turn that outlives its reader (GP-79).

**Free: no agent, no key, no database.** `fake_cli_agent.py` stands in for the
CLI; its `slow:<s>` prompt is a turn still under way when the reader goes.

**The disconnect tests run a real server on a loopback socket.** `TestClient`
drives the app in-process and cannot close a connection under it, so it can
never show what a reader going away does.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

import agent_service.api as api
from agent_service.api import create_app
from agent_service.config import Settings

FAKE = (sys.executable, str(Path(__file__).parent / "fake_cli_agent.py"))


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "home",
        "transcript_store": tmp_path / "store",
        "gemini_binary": FAKE,
        "require_credentials": False,
    }
    return Settings(**{**base, **kwargs})


class _Recorder:
    """A `RunRecorder` that keeps the run ids it was handed."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.events: list[str] = []
        self.finished: list[dict[str, Any]] = []

    def session_opened(self, sid: str, **kw: Any) -> None: ...

    def session_closed(self, sid: str, **kw: Any) -> None: ...

    def start_run(self, run_id: str, **kw: Any) -> None:
        self.started.append(run_id)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self.events.append(run_id)

    def finish_run(self, run_id: str, **kw: Any) -> None:
        self.finished.append({"run_id": run_id, **kw})


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Stands in for the recorder an app without a database is given."""
    capturing = _Recorder()
    monkeypatch.setattr(api, "NULL_RECORDER", capturing)
    return capturing


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def _open(client: TestClient) -> str:
    return client.post("/v1/sessions", json={}).json()["session_id"]


# --- the id itself --------------------------------------------------------

@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_reused_run_id_is_a_real_409_before_the_turn(
    client: TestClient, route: str
) -> None:
    sid = _open(client)
    first = client.post(f"/v1/sessions/{sid}/{route}",
                        json={"prompt": "hi", "run_id": "turn-1"})
    assert first.status_code == 200
    again = client.post(f"/v1/sessions/{sid}/{route}",
                        json={"prompt": "hi", "run_id": "turn-1"})
    assert again.status_code == 409
    body = again.json()
    assert body["title"] == "Run id in use"
    assert body["type"].endswith("/run-id-in-use")
    assert again.headers["content-type"].startswith("application/problem+json")


def test_an_id_is_used_across_sessions_and_routes(client: TestClient) -> None:
    """An id names one turn, whichever session or route it came through."""
    one, two = _open(client), _open(client)
    assert client.post(f"/v1/sessions/{one}/messages",
                       json={"prompt": "hi", "run_id": "shared"}).status_code == 200
    refused = client.post(f"/v1/sessions/{two}/messages/stream",
                          json={"prompt": "hi", "run_id": "shared"})
    assert refused.status_code == 409
    assert refused.json()["title"] == "Run id in use"


def test_a_failed_turn_keeps_its_id(client: TestClient) -> None:
    """Claimed when the turn starts, and kept whatever the turn then does."""
    sid = _open(client)
    failed = client.post(f"/v1/sessions/{sid}/messages",
                         json={"prompt": "exit:1", "run_id": "doomed"})
    assert failed.status_code == 502
    again = client.post(f"/v1/sessions/{sid}/messages",
                        json={"prompt": "hi", "run_id": "doomed"})
    assert again.status_code == 409
    assert again.json()["title"] == "Run id in use"


@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_a_busy_session_refuses_first_and_leaves_the_id_unclaimed(
    client: TestClient, route: str
) -> None:
    """The busy check comes first, so the same turn can be sent again later."""
    sid = _open(client)
    session = client.app.state.registry.get(sid)
    client.portal.call(session.lock.acquire)
    try:
        busy = client.post(f"/v1/sessions/{sid}/{route}",
                           json={"prompt": "hi", "run_id": "retry-me"})
    finally:
        session.lock.release()
    assert busy.status_code == 409
    assert busy.json()["title"] == "A turn is already running"
    assert client.post(f"/v1/sessions/{sid}/{route}",
                       json={"prompt": "hi", "run_id": "retry-me"}).status_code == 200


def test_an_unknown_session_is_404_and_leaves_the_id_unclaimed(
    client: TestClient,
) -> None:
    missing = client.post("/v1/sessions/nope/messages",
                          json={"prompt": "hi", "run_id": "later"})
    assert missing.status_code == 404
    sid = _open(client)
    assert client.post(f"/v1/sessions/{sid}/messages",
                       json={"prompt": "hi", "run_id": "later"}).status_code == 200


def test_a_malformed_run_id_is_a_422(client: TestClient) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages",
                           json={"prompt": "hi", "run_id": "has a space"})
    assert response.status_code == 422


@pytest.mark.parametrize("route", ["messages", "messages/stream"])
def test_the_turn_is_recorded_under_the_callers_id(
    recorder: _Recorder, tmp_path: Path, route: str
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        sid = _open(client)
        assert client.post(f"/v1/sessions/{sid}/{route}",
                           json={"prompt": "hi", "run_id": "mine"}).status_code == 200
    assert recorder.started == ["mine"]
    assert set(recorder.events) == {"mine"}
    assert [f["run_id"] for f in recorder.finished] == ["mine"]


def test_without_an_id_the_service_still_makes_one(
    recorder: _Recorder, client: TestClient
) -> None:
    sid = _open(client)
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    assert len(set(recorder.started)) == 2


def test_the_non_stream_route_accepts_on_disconnect(client: TestClient) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages",
                           json={"prompt": "hi", "on_disconnect": "continue"})
    assert response.status_code == 200


def test_a_continue_stream_that_is_read_ends_as_any_other(client: TestClient) -> None:
    """With a reader present, `continue` changes nothing a reader can see."""
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages/stream",
                           json={"prompt": "hi", "on_disconnect": "continue"})
    assert response.status_code == 200
    names = [line[len("event: "):] for line in response.text.splitlines()
             if line.startswith("event: ")]
    assert names[-1] == "done"
    assert names.count("event") >= 2
    session = client.app.state.registry.get(sid)
    assert not session.lock.locked()
    assert session.turns == 1


# --- a reader that goes ---------------------------------------------------

class _Server:
    """The app on a real loopback socket, in a thread of its own."""

    def __init__(self, app: Any) -> None:
        self.app = app
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning",
        ))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            assert self.thread.is_alive(), "the server did not start"
            assert time.monotonic() < deadline, "the server did not start in time"
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        import urllib.error
        import urllib.request

        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def read_first_frame_then_leave(self, path: str, body: Any) -> str:
        """Send a stream request, read until its first event, and hang up."""
        payload = json.dumps(body).encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=15) as s:
            s.sendall(
                f"POST {path} HTTP/1.1\r\nHost: test\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
            )
            seen = b""
            while b"event: event" not in seen:
                chunk = s.recv(65536)
                assert chunk, f"the server closed first: {seen!r}"
                seen += chunk
        return seen.decode("utf-8", "replace")

    def wait_idle(self, sid: str, within: float = 20) -> dict[str, Any]:
        deadline = time.monotonic() + within
        while True:
            status, body = self.request("GET", f"/v1/sessions/{sid}")
            assert status == 200, body
            if body["status"] == "idle":
                return body
            assert time.monotonic() < deadline, f"still {body['status']}"
            time.sleep(0.1)


def test_a_continue_turn_runs_to_its_end_after_its_reader_goes(
    recorder: _Recorder, tmp_path: Path
) -> None:
    app = create_app(_settings(tmp_path))
    with _Server(app) as server:
        _, created = server.request("POST", "/v1/sessions", {})
        sid = created["session_id"]
        head = server.read_first_frame_then_leave(
            f"/v1/sessions/{sid}/messages/stream",
            {"prompt": "slow:2", "run_id": "unread", "on_disconnect": "continue"},
        )
        assert head.startswith("HTTP/1.1 200")
        # The reader is gone and the agent is still in its pause.
        status, body = server.request("GET", f"/v1/sessions/{sid}")
        assert body["status"] == "running"
        refused, problem = server.request(
            "POST", f"/v1/sessions/{sid}/messages", {"prompt": "hi"})
        assert refused == 409, "a second turn got in while the first still ran"
        assert problem["title"] == "A turn is already running"

        record = server.wait_idle(sid)
    assert record["turns"] == 1, "the turn did not complete"
    assert record["last_turn"]["interrupted"] is False
    assert record["last_turn"]["outcome_recorded"] is True
    assert recorder.started == ["unread"]
    finished = recorder.finished[-1]
    assert finished["run_id"] == "unread"
    assert finished["interrupted"] is False
    assert finished["outcome"] is not None, "the turn's result was not recorded"
    # The events after the reader left were recorded too, not only the first.
    assert recorder.events.count("unread") >= 4


def test_by_default_a_reader_going_still_kills_the_turn(tmp_path: Path) -> None:
    """GP-59 unchanged: `interrupt` is the default and it still interrupts."""
    app = create_app(_settings(tmp_path))
    with _Server(app) as server:
        _, created = server.request("POST", "/v1/sessions", {})
        sid = created["session_id"]
        server.read_first_frame_then_leave(
            f"/v1/sessions/{sid}/messages/stream", {"prompt": "slow:2"})
        record = server.wait_idle(sid)
    assert record["turns"] == 0, "the turn ran on with nobody reading it"
    assert record["last_turn"]["interrupted"] is True


def test_an_unread_turn_still_stops_on_an_interrupt(
    recorder: _Recorder, tmp_path: Path
) -> None:
    app = create_app(_settings(tmp_path))
    with _Server(app) as server:
        _, created = server.request("POST", "/v1/sessions", {})
        sid = created["session_id"]
        server.read_first_frame_then_leave(
            f"/v1/sessions/{sid}/messages/stream",
            {"prompt": "slow:30", "run_id": "stop-me", "on_disconnect": "continue"},
        )
        status, stopped = server.request("POST", f"/v1/sessions/{sid}/interrupt")
        assert status == 200 and stopped["interrupted"] is True
        record = server.wait_idle(sid, within=15)
    assert record["turns"] == 0
    assert record["last_turn"]["interrupted"] is True
    assert recorder.finished[-1]["run_id"] == "stop-me"
    assert recorder.finished[-1]["interrupted"] is True


def test_a_stop_ends_an_unread_turn_and_records_it(
    recorder: _Recorder, tmp_path: Path
) -> None:
    """Shutdown cancels the turn rather than leaving its task pending."""
    app = create_app(_settings(tmp_path))
    with _Server(app) as server:
        _, created = server.request("POST", "/v1/sessions", {})
        sid = created["session_id"]
        server.read_first_frame_then_leave(
            f"/v1/sessions/{sid}/messages/stream",
            {"prompt": "slow:30", "run_id": "at-stop", "on_disconnect": "continue"},
        )
        started = time.monotonic()
    assert time.monotonic() - started < 15, "the stop waited for the turn"
    assert recorder.finished[-1]["run_id"] == "at-stop"
    assert recorder.finished[-1]["interrupted"] is True
