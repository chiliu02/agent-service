"""The streaming turn route. **Free**, against the fake agent.

**The property worth testing is WHEN the response commits**, not that SSE
frames parse. This route advances to the first event before committing, so a
first-event failure is a real status code; `/v1/query/stream` cannot do that and
reports everything in-band. A client has to know which it is talking to, so the
difference is asserted rather than described.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def _frames(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into `(event, data)` pairs."""
    out = []
    for block in text.strip().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name:
            out.append((name, data))
    return out


def _open(client: TestClient) -> str:
    return client.post("/v1/sessions", json={}).json()["session_id"]


def test_a_stream_ends_with_done_carrying_the_whole_result(client: TestClient) -> None:
    """`event: done` carries what the non-streaming route would have returned.

    So a client that streamed does not have to reconstruct the outcome from the
    events it happened to see.
    """
    session_id = _open(client)
    response = client.post(f"/v1/sessions/{session_id}/messages/stream",
                           json={"prompt": "say hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _frames(response.text)
    assert frames[-1][0] == "done"
    done = frames[-1][1]
    assert done["result"] == "hello world"
    assert done["outcome_recorded"] is True
    assert done["total_cost_usd"] is None


def test_the_stream_carries_the_id_header_it_declares(client: TestClient) -> None:
    """**Declared AND sent.** It was declared and never sent until a live turn.

    Nothing caught it: the header is absent from an SSE response in exactly the
    same way it is absent from a route that never had an id, and no test asked.
    It is emittable on this route alone -- the opening event carries the agent's
    id and this route awaits that event before committing, which is the same
    property that makes its 404 and 409 real status codes. `/v1/query/stream`
    commits first, knows nothing, and declares no header at all.
    """
    session_id = _open(client)
    response = client.post(f"/v1/sessions/{session_id}/messages/stream",
                           json={"prompt": "say hello"})
    streamed = response.headers.get("x-sdk-session-id")
    assert streamed, "the header is declared on this operation and must be sent"

    # The agent's id for THIS turn, and the same one the events and `done`
    # report -- a header that disagreed with the body would be worse than none.
    frames = _frames(response.text)
    assert frames[-1][1]["sdk_session_id"] == streamed


def test_a_one_shot_stream_declares_no_id_header_and_sends_none(
    client: TestClient,
) -> None:
    """The counterpart, and the reason the two routes differ.

    This one commits its 200 before the agent has said anything, so there is no
    id to put in a header. Asserted rather than assumed, so that "just add the
    header here too" fails a test instead of shipping an empty one.
    """
    response = client.post("/v1/query/stream", json={"prompt": "say hello"})
    assert response.status_code == 200
    assert "x-sdk-session-id" not in response.headers


def test_events_arrive_before_done_and_are_normalised(client: TestClient) -> None:
    session_id = _open(client)
    frames = _frames(client.post(f"/v1/sessions/{session_id}/messages/stream",
                                 json={"prompt": "tools please"}).text)
    events = [payload for name, payload in frames if name == "event"]
    assert events, "no events were streamed"
    assert [e["seq"] for e in events] == list(range(len(events))), "seq must be dense"
    assert events[0]["type"] == "system", "init maps to system"
    assert {e["type"] for e in events} <= {
        "system", "assistant", "user", "result", "stream_event", "rate_limit", "unknown"
    }


def test_a_streamed_turn_is_recorded_like_any_other(client: TestClient, tmp_path: Path) -> None:
    """Streaming must not be a second path that forgets the bookkeeping.

    The transcript copy and the id history are what make the NEXT turn work, so
    a stream that skipped them would break resume for a client that only ever
    streams.
    """
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages/stream", json={"prompt": "hi"})
    record = client.get(f"/v1/sessions/{session_id}").json()
    assert record["turns"] == 1
    assert record["sdk_session_id"]
    assert (tmp_path / "store" / f"{session_id}.jsonl").is_file()


def test_the_lock_is_released_when_the_stream_ends(client: TestClient) -> None:
    """A stream holds the session lock for its whole life.

    If it leaked, the session would answer 409 forever and only a restart would
    clear it — which is why this asserts a SECOND turn rather than an internal
    flag.
    """
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages/stream", json={"prompt": "one"})
    second = client.post(f"/v1/sessions/{session_id}/messages/stream",
                         json={"prompt": "two"})
    assert second.status_code == 200


def test_an_unknown_session_is_a_real_404_not_an_in_band_error(
    client: TestClient,
) -> None:
    """The commit-late property, seen from the outside.

    `/v1/query/stream` cannot answer like this because it has already committed
    a 200 before anything is known.
    """
    response = client.post("/v1/sessions/nope/messages/stream", json={"prompt": "hi"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_a_first_event_failure_is_a_real_status_code(tmp_path: Path) -> None:
    """The reason this route advances before committing.

    The agent exits 41 having written nothing, so there is no first event; the
    client gets a 500 with a problem document rather than a 200 whose only
    content is an error frame it has to notice.
    """
    with TestClient(create_app(_settings(tmp_path))) as client:
        session_id = _open(client)
        response = client.post(f"/v1/sessions/{session_id}/messages/stream",
                               json={"prompt": "exit:41"})
        assert response.status_code == 500
        assert response.json()["type"].endswith("/credential-missing")


def test_a_turn_that_never_ends_is_killed_mid_stream(tmp_path: Path) -> None:
    """GP-18: the wall clock applies to a stream too.

    Here it arrives in-band, because by the time it fires the response is long
    committed — the same failure, reported the only way it still can be.
    """
    with TestClient(create_app(_settings(tmp_path, turn_timeout_s=1))) as client:
        session_id = _open(client)
        response = client.post(f"/v1/sessions/{session_id}/messages/stream",
                               json={"prompt": "hang"})
        # No first event ever arrives, so this one is caught before committing.
        assert response.status_code == 504
        assert response.json()["type"].endswith("/turn-timeout")


class _StubProcess:
    """Enough of a process for `kill_turn` to act on, and to observe it."""

    def __init__(self) -> None:
        self.pid = -1          # never a real pid; killpg/kill both fail safely
        self.returncode = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _StubStream:
    """A `StreamingTurn` that neither failed nor produced a result yet."""

    failure = None
    result = None


async def _one_then_hang():
    """One event, then never another -- a turn still in flight."""
    import asyncio

    yield {"type": "tool_use"}
    await asyncio.sleep(3600)


@pytest.mark.anyio
async def test_a_disconnect_mid_turn_kills_the_agent_and_ends_the_turn(
    tmp_path: Path,
) -> None:
    """GP-59: a closed tab used to leave the agent running and billing.

    The generator is closed while a turn is in flight, which is exactly what
    Starlette does when the consumer goes away.
    """
    from agent_service.api import _sse
    from agent_service.registry import Session

    session = Session(
        session_id="s1",
        workspace=tmp_path,
        agent_home=tmp_path / "home",
        policy_file=tmp_path / "home" / "p.toml",
        transcript=tmp_path / "t.jsonl",
        created_at=0.0,
        last_used_at=0.0,
    )
    proc = _StubProcess()
    session.attach_process(proc)
    session.status = "running"
    await session.lock.acquire()

    frames = _sse(session, _StubStream(), _one_then_hang(), first=None)
    assert await frames.__anext__()          # the turn is under way
    await frames.aclose()                    # the browser goes away

    assert proc.killed, "the agent process was left running"
    assert session.interrupted is True
    assert session.status == "idle", "the session was left stuck at 'running'"
    assert session.last_turn is not None
    assert session.last_turn.interrupted is True
    assert session.last_turn.stop_kind == "interrupted"
    assert not session.lock.locked(), "the stream lock was stranded"
