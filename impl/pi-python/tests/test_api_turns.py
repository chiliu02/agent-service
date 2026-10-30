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

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_dir_root": tmp_path / "agent-dirs",
        "session_store": tmp_path / "sessions",
        "pi_binary": FAKE,
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
    """The answer is reassembled from `delta` chunks (`PI-35`).

    There is no terminal non-delta message, so a client waiting for one waits
    forever — the service does the reassembly instead.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": "say hello"}).json()
    assert body["result"] == "ok"
    assert body["outcome_recorded"] is True
    assert body["is_error"] is False
    # Normalised, not the agent's own names: the enum is closed and has no
    # `tool` member, so tool events are `assistant` with `subtype` naming them.
    kinds = [e["type"] for e in body["events"]]
    assert kinds[0] == "system", "the init event maps to system"
    assert set(kinds) <= {"system", "assistant", "user", "result", "stream_event",
                          "rate_limit", "unknown"}
    assert body["total_cost_usd"] is not None, "cost is real here (PI-17)"


def test_the_turn_is_recorded_on_the_session(client: TestClient) -> None:
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"prompt": "hi"})
    record = client.get(f"/v1/sessions/{session_id}").json()
    assert record["turns"] == 1
    assert record["sdk_session_id"], "the agent's id was not recorded"
    assert record["last_turn"]["outcome_recorded"] is True





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
    """`PI-15` and `PI-11`: the wall clock is the only exit and it is enforced.

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
    """AS-34: a build that HAS a count must not answer null beside it.

    The raw block is `turn_end`'s own usage object and the named counts are the
    specification's spelling of it, so the two must agree field for field
    (`PI-33`).
    """
    sid = _open(client)
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}).json()
    raw, counts = body["usage"], body["token_usage"]
    assert counts["input_tokens"] == raw["input"]
    assert counts["output_tokens"] == raw["output"]
    assert counts["cache_read_tokens"] == raw["cacheRead"]
    assert counts["cache_write_tokens"] == raw["cacheWrite"]
    # Disjoint here, unlike the Gemini build (`PI-33`).
    assert raw["input"] + raw["output"] == raw["totalTokens"]


def test_include_raw_false_drops_the_payload_from_the_response(
    client: TestClient,
) -> None:
    """. The field was accepted and read by nothing until 2026-09-03.

    **Both directions**, because the honest failure here is the generous one: a
    caller asking for smaller events got the agent's whole payload anyway, and
    nothing about that looks wrong until the transcript is measured.
    """
    sid = client.post("/v1/sessions", json={"options": {"include_raw": False}}).json()[
        "session_id"
    ]
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "say hello"}).json()
    assert body["events"], "the turn produced no events to check"
    assert all(event["raw"] is None for event in body["events"])

    loud = client.post("/v1/sessions", json={"options": {"include_raw": True}}).json()[
        "session_id"
    ]
    kept = client.post(f"/v1/sessions/{loud}/messages", json={"prompt": "say hello"}).json()
    assert any(event["raw"] for event in kept["events"])


# --- the two facts that INVERT against the Gemini build ----------------------


def test_the_second_turn_resumes_and_keeps_the_SAME_conversation_id(
    client: TestClient,
) -> None:
    """`PI-13`: measured across two processes on three providers.

    On the Gemini build the agent mints a new id every turn and this test
    asserts the opposite there. Publishing `sdk_session_id_scope` is what lets a
    client tell which it is talking to.
    """
    sid = _open(client)
    first = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"}).json()
    second = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "two"}).json()
    assert first["sdk_session_id"] == second["sdk_session_id"]


def test_the_conversation_id_is_recorded_once_not_once_per_turn(
    client: TestClient,
) -> None:
    """`PI-13`: a stable id must not accumulate duplicates in the session."""
    sid = _open(client)
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"})
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "two"})
    session = client.app.state.registry.get(sid)
    assert len(session.sdk_session_ids) == 1


def test_a_turn_reports_its_cost_and_the_session_accumulates_it(
    client: TestClient,
) -> None:
    """`PI-17`: real USD, which two of the four builds cannot report at all."""
    sid = _open(client)
    first = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"}).json()
    assert first["turn_cost_usd"] == pytest.approx(0.000758)
    second = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "two"}).json()
    assert second["total_cost_usd"] == pytest.approx(0.000758 * 2)


def test_the_named_token_counts_use_this_agents_keys(client: TestClient) -> None:
    """`PI-33`: `input` excludes the cached half here, and both cache counters are real."""
    sid = _open(client)
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"}).json()
    counts = body["token_usage"]
    assert counts["input_tokens"] == 548
    assert counts["output_tokens"] == 42
    assert counts["cache_read_tokens"] == 0
    assert counts["cache_write_tokens"] == 0
