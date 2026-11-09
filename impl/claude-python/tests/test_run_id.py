"""A caller-chosen `run_id`, and `on_disconnect`. CP-155, CP-156.

The disconnect tests drive a REAL `AgentSession` behind a slow fake client and a
real loopback socket. Both halves matter: `ASGITransport` cannot observe a
disconnect at all, and a fake session would not hold the `asyncio.timeout`
across its yields that decides which task may drain the turn.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time

from httpx import ASGITransport, AsyncClient

from agent_service.api import create_app
from agent_service.registry import SessionRegistry
from agent_service.sessions import AgentSession, SessionBusy
from agent_spec.openapi.schemas import RunOptions
from tests.test_api_stream import _running_server
from tests.test_recorder import RecordingRecorder, _turn
from tests.test_sessions import FakeClient

#: Seconds between the slow client's messages. A turn is three of them.
STEP = 0.4


class SlowClient(FakeClient):
    """Replays canned turns with a pause before each message."""

    def __init__(self, turns: list[list[object]]) -> None:
        super().__init__(turns)
        self.delivered = 0

    async def receive_response(self):
        turn = self.turns[self._turn_index]
        self._turn_index += 1
        for msg in turn:
            await asyncio.sleep(STEP)
            self.delivered += 1
            yield msg


def _real_registry(settings, recorder, clients):  # noqa: ANN001, ANN202
    def factory(options, settings_, title=None):  # noqa: ANN001
        client = SlowClient([_turn(), _turn()])
        clients.append(client)
        return AgentSession(
            options, settings_, title=title,
            client_factory=lambda _o: client, recorder=recorder,
        )

    return SessionRegistry(settings, session_factory=factory)


def _post_then_drop(port: int, path: str, body: dict, hold: float) -> None:
    """Send a request on a raw socket and close it after `hold` seconds."""
    data = json.dumps(body).encode()
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(
        f"POST {path} HTTP/1.1\r\nHost: t\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(data)}\r\n\r\n".encode() + data
    )
    time.sleep(hold)
    s.close()


async def _until_idle(ac: AsyncClient, sid: str, budget: float = 5.0) -> str:
    deadline = time.monotonic() + budget
    while True:
        status = (await ac.get(f"/v1/sessions/{sid}")).json()["status"]
        if status != "running" or time.monotonic() > deadline:
            return status
        await asyncio.sleep(0.05)


# -- the id ------------------------------------------------------------------


async def test_a_session_turn_is_recorded_under_the_callers_id(settings) -> None:  # noqa: ANN001
    recorder = RecordingRecorder()
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _o: FakeClient([_turn()]),
        recorder=recorder,
    )
    await session.open()

    events = [e async for e in session.send("p", run_id="relay-1")]

    assert recorder.starts[0]["run_id"] == "relay-1"
    assert recorder.finishes[0]["run_id"] == "relay-1"
    assert {run_id for run_id, _ in recorder.events} == {"relay-1"}
    assert len(events) == 3


async def test_a_used_run_id_is_refused_with_its_own_title(session_client) -> None:  # noqa: ANN001
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    body = {"prompt": "hi", "run_id": "relay-1"}

    assert (await session_client.post(f"/v1/sessions/{sid}/messages", json=body)).status_code == 200
    again = await session_client.post(f"/v1/sessions/{sid}/messages", json=body)
    streamed = await session_client.post(f"/v1/sessions/{sid}/messages/stream", json=body)

    for r in (again, streamed):
        assert r.status_code == 409
        assert r.json()["title"] == "Run id in use"
        assert r.json()["type"].endswith("/run-id-in-use")


async def test_a_busy_refusal_gives_the_id_back(session_client, fake_registry) -> None:  # noqa: ANN001
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    body = {"prompt": "hi", "run_id": "relay-2"}
    fake_registry.made[0].raise_on_send = SessionBusy("a turn is already running")

    busy = await session_client.post(f"/v1/sessions/{sid}/messages", json=body)
    fake_registry.made[0].raise_on_send = None
    retried = await session_client.post(f"/v1/sessions/{sid}/messages", json=body)

    assert busy.status_code == 409
    assert busy.json()["title"] == "Session busy"
    assert retried.status_code == 200


async def test_a_refusal_never_releases_an_id_another_turn_holds(
    settings, fake_factory  # noqa: ANN001
) -> None:
    """The busy check comes before the claim, so a busy session refused with
    an id that ANOTHER turn holds must leave that id held."""
    recorder, clients = RecordingRecorder(), []
    factory, _ = fake_factory
    app = create_app(
        settings=settings, run_factory=factory,
        registry=_real_registry(settings, recorder, clients),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        a = (await ac.post("/v1/sessions", json={})).json()["session_id"]
        b = (await ac.post("/v1/sessions", json={})).json()["session_id"]
        first = asyncio.create_task(
            ac.post(f"/v1/sessions/{a}/messages", json={"prompt": "x", "run_id": "held"})
        )
        while not clients[0].queries:
            await asyncio.sleep(0.01)
        second = asyncio.create_task(
            ac.post(f"/v1/sessions/{b}/messages", json={"prompt": "y"})
        )
        while not clients[1].queries:
            await asyncio.sleep(0.01)
        refused = await ac.post(
            f"/v1/sessions/{b}/messages", json={"prompt": "z", "run_id": "held"}
        )
        await first
        await second
        reused = await ac.post(
            f"/v1/sessions/{b}/messages", json={"prompt": "z", "run_id": "held"}
        )

    assert refused.json()["title"] == "Session busy"
    assert reused.status_code == 409
    assert reused.json()["title"] == "Run id in use"


async def test_a_malformed_run_id_is_422(session_client) -> None:  # noqa: ANN001
    sid = (await session_client.post("/v1/sessions", json={})).json()["session_id"]
    r = await session_client.post(
        f"/v1/sessions/{sid}/messages", json={"prompt": "hi", "run_id": "has space"}
    )
    assert r.status_code == 422


# -- on_disconnect -----------------------------------------------------------


async def _drop_mid_turn(settings, fake_factory, body: dict):  # noqa: ANN001, ANN202
    recorder, clients = RecordingRecorder(), []
    factory, _ = fake_factory
    app = create_app(
        settings=settings, run_factory=factory,
        registry=_real_registry(settings, recorder, clients),
    )
    async with _running_server(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            sid = (await ac.post("/v1/sessions", json={})).json()["session_id"]
            # Past the first message, before the result: mid-turn.
            await asyncio.to_thread(
                _post_then_drop, port, f"/v1/sessions/{sid}/messages/stream",
                body, STEP * 1.6,
            )
            status = await _until_idle(ac, sid)
            follow_up = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "next"})
    return recorder, clients[0], status, follow_up


async def test_continue_runs_the_turn_to_its_end_without_a_reader(
    settings, fake_factory  # noqa: ANN001
) -> None:
    recorder, client, status, follow_up = await _drop_mid_turn(
        settings, fake_factory,
        {"prompt": "hi", "run_id": "relay-3", "on_disconnect": "continue"},
    )

    assert client.interrupts == 0
    assert status == "idle"
    first = recorder.finishes[0]
    assert first["run_id"] == "relay-3"
    assert first["interrupted"] is False
    assert first["outcome"] is not None
    # The next turn is its own, not the tail of the abandoned one.
    assert follow_up.status_code == 200
    assert follow_up.json()["is_error"] is False


async def test_the_default_still_interrupts_when_the_reader_goes(
    settings, fake_factory  # noqa: ANN001
) -> None:
    recorder, client, _, _ = await _drop_mid_turn(
        settings, fake_factory, {"prompt": "hi", "run_id": "relay-4"}
    )

    assert client.interrupts == 1
    assert recorder.finishes[0]["run_id"] == "relay-4"
    assert recorder.finishes[0]["outcome"] is None


async def test_continue_with_a_reader_streams_every_frame(
    settings, fake_factory  # noqa: ANN001
) -> None:
    recorder, clients = RecordingRecorder(), []
    factory, _ = fake_factory
    app = create_app(
        settings=settings, run_factory=factory,
        registry=_real_registry(settings, recorder, clients),
    )
    async with _running_server(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            sid = (await ac.post("/v1/sessions", json={})).json()["session_id"]
            r = await ac.post(
                f"/v1/sessions/{sid}/messages/stream",
                json={"prompt": "hi", "on_disconnect": "continue"},
            )

    names = [line[7:] for line in r.text.splitlines() if line.startswith("event: ")]
    assert names == ["system", "assistant", "result", "done"]
    assert clients[0].interrupts == 0
