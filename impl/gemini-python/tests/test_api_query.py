"""The one-shot routes. **Free**, against the fake agent.

**The two things worth pinning** are that a query consumes no session slot —
which is published, so it is a promise — and that `/v1/query/stream` reports
*every* failure in-band, including one that produces no events at all. A client
that checks only the status code there will read a failed turn as a successful
one, which is the whole reason the session route commits late instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_spec.openapi.examples import flat

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


def test_a_query_runs_a_turn_and_returns_it(client: TestClient) -> None:
    body = client.post("/v1/query", json={"prompt": "say hello"}).json()
    assert body["result"] == "hello world"
    assert body["outcome_recorded"] is True
    assert body["sdk_session_id"], "a one-shot still reports the agent's id"
    assert body["total_cost_usd"] is None


def test_a_query_consumes_no_session_slot(tmp_path: Path) -> None:
    """Published as `query_consumes_a_session_slot: false`, so it is a promise.

    The cap is set to 1 and then filled: a query must still run. If this ever
    fails, a caller who sized `max_sessions` for its sessions would find queries
    eating them.
    """
    with TestClient(create_app(_settings(tmp_path, max_sessions=1))) as client:
        assert flat(client.get("/v1/deployment").json())["query_consumes_a_session_slot"] is False
        assert client.post("/v1/sessions", json={}).status_code == 201
        assert client.post("/v1/sessions", json={}).status_code == 429, "cap is full"
        assert client.post("/v1/query", json={"prompt": "hi"}).status_code == 200


def test_a_query_never_appears_in_the_session_list(client: TestClient) -> None:
    """It has no continuity to offer, so listing it would invite a resume."""
    client.post("/v1/query", json={"prompt": "hi"})
    assert client.get("/v1/sessions").json()["sessions"] == []


def test_a_query_still_gets_its_own_policy(client: TestClient, tmp_path: Path) -> None:
    """**A one-shot turn is not a turn with a smaller boundary.**

    The directory is removed afterwards, so this asserts the policy existed
    while the turn ran rather than looking for the file after.
    """
    body = client.post("/v1/query",
                       json={"prompt": "tools please",
                             "options": {"allowed_tools": ["read_file"]}}).json()
    assert body["outcome_recorded"] is True
    # Nothing left behind: no ephemeral home survives the request.
    leftovers = [p for p in (tmp_path / "home").glob("query-*")]
    assert leftovers == [], "an ephemeral session leaked its directory"


def test_the_stream_ends_with_done(client: TestClient) -> None:
    response = client.post("/v1/query/stream", json={"prompt": "say hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _frames(response.text)
    assert frames[-1][0] == "done"
    assert frames[-1][1]["result"] == "hello world"


def test_every_failure_is_in_band_even_with_no_events(client: TestClient) -> None:
    """**The defining property of this route.**

    The agent exits 41 having written nothing at all. The session stream would
    answer 500 because it waits for a first event; this one has already
    committed a 200, so the only place left to report is the body.

    A client that checks the status here and stops has just treated a credential
    failure as a successful turn.
    """
    response = client.post("/v1/query/stream", json={"prompt": "exit:41"})
    assert response.status_code == 200, "it committed before it knew"
    frames = _frames(response.text)
    assert [name for name, _ in frames] == ["error"]
    assert frames[0][1]["exit_code"] == 41
    assert "done" not in [name for name, _ in frames]


def test_the_two_stream_routes_differ_on_the_same_failure(client: TestClient) -> None:
    """The asymmetry, asserted side by side rather than described.

    Same agent, same failure: one is a status code, the other is a frame. This
    is the single most likely thing for a client to get wrong.
    """
    session_id = client.post("/v1/sessions", json={}).json()["session_id"]
    session_stream = client.post(f"/v1/sessions/{session_id}/messages/stream",
                                 json={"prompt": "exit:41"})
    one_shot = client.post("/v1/query/stream", json={"prompt": "exit:41"})
    assert session_stream.status_code == 500
    assert one_shot.status_code == 200
    assert _frames(one_shot.text)[0][0] == "error"
