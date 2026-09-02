"""Turns over HTTP, driven against the fake agent. **Free.**

**This is the first place the whole stack runs together** — route, registry,
policy and runner — so the assertions are about the seams between them rather
than about any one part: does the transcript get kept, does the second turn
resume from it, does an id get recorded for every turn.
"""

from __future__ import annotations

import sys
import time
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


def _open(client: TestClient) -> str:
    return client.post("/v1/sessions", json={}).json()["session_id"]


def test_a_turn_returns_the_answer_and_its_events(client: TestClient) -> None:
    """The answer is reassembled from `delta` chunks (GP-15).

    There is no terminal non-delta message, so a client waiting for one waits
    forever — the service does the reassembly instead.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": "say hello"}).json()
    assert body["result"] == "hello world"
    assert body["outcome_recorded"] is True
    assert body["is_error"] is False
    # Normalised, not the agent's own names: the enum is closed and has no
    # `tool` member, so tool events are `assistant` with `subtype` naming them.
    kinds = [e["type"] for e in body["events"]]
    assert kinds[0] == "system", "the init event maps to system"
    assert set(kinds) <= {"system", "assistant", "user", "result", "stream_event",
                          "rate_limit", "unknown"}
    assert body["total_cost_usd"] is None, "0.0 would read as free (GP-16)"


def test_the_turn_is_recorded_on_the_session(client: TestClient) -> None:
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"prompt": "hi"})
    record = client.get(f"/v1/sessions/{session_id}").json()
    assert record["turns"] == 1
    assert record["sdk_session_id"], "the agent's id was not recorded"
    assert record["last_turn"]["outcome_recorded"] is True


def test_the_transcript_is_kept_where_the_agent_cannot_reach_it(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-10: the agent deletes its own transcript on the first resume.

    So the copy taken after every turn is the whole durability mechanism, and
    without it a second turn would have nothing to resume from.
    """
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"prompt": "hi"})
    assert (tmp_path / "store" / f"{session_id}.jsonl").is_file()


def test_the_second_turn_resumes_and_gets_a_NEW_agent_id(client: TestClient) -> None:
    """GP-11 and GP-34 together, which is the shape a client must understand.

    `--session-file` loads a transcript rather than adopting an identity, so the
    agent's id changes every turn. The service's own `session_id` does not.
    """
    session_id = _open(client)
    first = client.post(f"/v1/sessions/{session_id}/messages",
                        json={"prompt": "one"}).json()
    second = client.post(f"/v1/sessions/{session_id}/messages",
                         json={"prompt": "two"}).json()
    assert first["sdk_session_id"] != second["sdk_session_id"]
    assert client.get(f"/v1/sessions/{session_id}").json()["turns"] == 2


def test_every_agent_id_is_remembered_not_just_the_last(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-35: `options.resume` accepts any id this session has issued.

    The caller most likely to resume is the one whose connection dropped, and it
    is holding an old id. Keeping only the newest would refuse exactly them.
    """
    from agent_service.registry import Registry  # noqa: PLC0415 - see below

    session_id = _open(client)
    ids = []
    for prompt in ("one", "two", "three"):
        ids.append(client.post(f"/v1/sessions/{session_id}/messages",
                               json={"prompt": prompt}).json()["sdk_session_id"])
    # Reaching into the app's registry rather than through a route, because no
    # route exposes the history and inventing one to make a test pass would be
    # the wrong order of operations.
    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    session = registry.get(session_id)
    assert session.sdk_session_ids == ids
    for issued in ids:
        assert registry.find_by_sdk_id(issued) is session


def test_a_turn_on_an_unknown_session_is_a_404(client: TestClient) -> None:
    response = client.post("/v1/sessions/nope/messages", json={"prompt": "hi"})
    assert response.status_code == 404
    assert response.json()["type"].endswith("/session-not-found")


def test_a_second_concurrent_turn_is_409_and_never_a_queue(
    client: TestClient, tmp_path: Path
) -> None:
    """Two callers would otherwise receive each other's turns.

    The lock is taken directly here: provoking a real race through the test
    client would test the client's threading rather than this rule.
    """
    from agent_service.registry import Registry  # noqa: PLC0415

    session_id = _open(client)
    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    session = registry.get(session_id)

    import anyio

    async def hold_and_call() -> int:
        async with session.lock:
            return client.post(f"/v1/sessions/{session_id}/messages",
                               json={"prompt": "hi"}).status_code

    assert anyio.run(hold_and_call) == 409


def test_a_turn_that_never_ends_is_a_504_not_a_200_with_a_flag(tmp_path: Path) -> None:
    """GP-18 and GP-02: the wall clock is the only exit and it is enforced.

    A 200 carrying `timed_out: true` would let a client treat a killed turn as a
    completed one, which on this target is a routine occurrence rather than an
    edge case.
    """
    with TestClient(create_app(_settings(tmp_path, turn_timeout_s=1))) as client:
        session_id = _open(client)
        response = client.post(f"/v1/sessions/{session_id}/messages",
                               json={"prompt": "hang"})
        assert response.status_code == 504
        assert response.json()["type"].endswith("/turn-timeout")
        assert client.get(f"/v1/sessions/{session_id}").json()["last_turn"]["timed_out"] is True


def test_a_session_can_be_READ_while_a_turn_is_running(tmp_path: Path) -> None:
    """**The only status ever exercised was `idle`, and that hid a 500.**

    This build wrote `status = "busy"`, which is not a member of the shared
    `SessionStatus` enum, so every read of a session mid-turn failed validation:
    the record route, the listing, AND interrupt -- which is only ever called
    during a turn and was therefore broken outright in the shipped image.

    Nothing caught it because the fake agent finishes before anything can look
    and the one interrupt test interrupted nothing. So this test's whole job is
    to look while the turn is still going.
    """
    import threading  # noqa: PLC0415

    with TestClient(create_app(_settings(tmp_path, turn_timeout_s=5))) as client:
        session_id = _open(client)
        turn = threading.Thread(
            target=lambda: client.post(f"/v1/sessions/{session_id}/messages",
                                       json={"prompt": "hang"}),
            daemon=True,
        )
        turn.start()

        registry = client.app.state.registry  # type: ignore[attr-defined]
        session = registry.get(session_id)
        for _ in range(200):
            if session.status != "idle":
                break
            time.sleep(0.05)
        # Deliberately NOT `== "running"` here: this only has to establish that
        # a turn is in flight. Pinning the spelling at this line would fail the
        # test before it reaches the routes, and it is the ROUTES that returned
        # 500 -- a test that reports "wrong label" for a broken interrupt has
        # described the wrong defect.
        assert session.status != "idle", "the turn never started"

        # Each of the three routes that read a session, mid-turn.
        record = client.get(f"/v1/sessions/{session_id}")
        assert record.status_code == 200, record.text
        assert record.json()["status"] == "running"
        assert client.get("/v1/sessions").status_code == 200

        stopped = client.post(f"/v1/sessions/{session_id}/interrupt")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["interrupted"] is True

        turn.join(timeout=30)


def test_interrupting_nothing_is_200_with_a_body(client: TestClient) -> None:
    """Never 204 and never 409.

    A turn can finish between a client deciding to stop it and the request
    arriving; that race is unavoidable, so "nothing to stop" is reported in the
    body rather than as an error.
    """
    session_id = _open(client)
    response = client.post(f"/v1/sessions/{session_id}/interrupt")
    assert response.status_code == 200
    assert response.json() == {"interrupted": False, "status": "idle"}


def test_the_named_counts_reach_the_wire_and_agree_with_the_raw_block(
    client: TestClient,
) -> None:
    """AS-34 over HTTP, free: a count the build reports is never published null.

    The live conformance suite already has this clause, and it costs a real turn
    against a real model -- so it had never run against this build, which
    published five nulls on every turn for its whole life (GP-60). This is the
    same assertion at the seam the defect actually lived in, driven against the
    fake agent, which is why the fake now emits the counts a real turn emits.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": "say hello"}).json()

    named, raw = body["token_usage"], body["usage"]
    assert named["input_tokens"] == raw["input_tokens"]
    assert named["output_tokens"] == raw["output_tokens"]
    assert named["cache_read_tokens"] == raw["cached"]
    # Not zero: this agent has no cache-write counter and its reasoning count is
    # dropped by the conversion into the result event (GP-60).
    assert named["cache_write_tokens"] is None
    assert named["reasoning_output_tokens"] is None
