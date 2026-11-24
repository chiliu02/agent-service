"""A turn the VENDOR refused, on every surface that reports one (`PI-61`).

**The defect this pins was found by a consumer, not by a suite**, and every
suite here passed while it was live. That is the shape worth remembering: the
turn was correct, the HTTP call was correct, and one boolean answered a
different question from the one its own description asks.

`--mode json` exits `0` whatever happened -- the agent's own `stopReason` check
lives inside its `mode === "text"` branch -- so the refusal is recorded ONLY in
the final `turn_end` message. Four surfaces have to agree about it: the turn
response, the stream's `done` frame, the session record fetched later, and the
stored row.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))

#: What the caller sends to get a refused turn out of the double. The text after
#: the colon becomes the agent's `errorMessage`, which is where a real vendor
#: puts its status.
REFUSED = "refused:429 rate_limit_error: too many requests"


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


def test_a_refused_turn_is_an_error_although_an_outcome_arrived(
    client: TestClient,
) -> None:
    """**The two fields answer different questions, and here they diverge.**

    An envelope DID arrive -- that is what `outcome_recorded` says and it is
    true. The agent also said the turn failed, which is what `is_error` is for.
    Deriving the second from the first is what made four refused turns read as
    four turns with nothing to say.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": REFUSED}).json()

    assert body["outcome_recorded"] is True, "the agent did hand us a result"
    assert body["is_error"] is True, "and it said that result was a failure"
    assert body["stop_kind"] == "error"
    assert body["interrupted"] is False


def test_the_vendors_status_is_on_the_response_without_asking_for_raw(
    client: TestClient,
) -> None:
    """**It was reachable only through `raw` before**, which a session opts into.

    `stop_reason` is the agent's own word and `terminal_reason` its own text;
    both are passed through untranslated, and the second is where a rate limit
    actually says so.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": REFUSED}).json()

    assert body["stop_reason"] == "error"
    assert "429" in (body["terminal_reason"] or "")
    assert body["result"] == "", "a refused turn produced no text, and says so"


def test_a_turn_that_merely_had_nothing_to_say_is_still_not_an_error(
    client: TestClient,
) -> None:
    """The other half of the rule, and the reason this is not `result == ""`.

    A successful turn says `stopReason: "stop"`. Inferring failure from an empty
    answer would report every quiet turn as a crash -- which is exactly what the
    `result` field's own description forbids.
    """
    session_id = _open(client)
    body = client.post(f"/v1/sessions/{session_id}/messages",
                       json={"prompt": "say hello"}).json()

    assert body["is_error"] is False
    assert body["stop_kind"] == "end_turn"
    assert body["stop_reason"] == "stop"
    assert body["terminal_reason"] is None


def test_the_session_record_agrees_with_the_response_the_caller_held(
    client: TestClient,
) -> None:
    """**A record fetched later that disagreed would be the worse defect.**

    The status code is long gone by then, possibly to a different caller, so
    `last_turn` is the only thing left saying how the turn ended.
    """
    session_id = _open(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"prompt": REFUSED})

    last = client.get(f"/v1/sessions/{session_id}").json()["last_turn"]
    assert last["is_error"] is True
    assert last["stop_kind"] == "error"
    assert last["outcome_recorded"] is True, "an outcome still arrived"
    assert last["timed_out"] is False and last["interrupted"] is False


def test_the_streamed_done_frame_says_the_same_thing(client: TestClient) -> None:
    """Both turn routes shape their answer through one function, and this proves
    it rather than assuming it: a client that streams must not learn less than
    one that waits."""
    session_id = _open(client)
    with client.stream("POST", f"/v1/sessions/{session_id}/messages/stream",
                       json={"prompt": REFUSED}) as stream:
        frames = [line for line in stream.iter_lines() if line.startswith("data:")]

    done = json.loads(frames[-1].removeprefix("data:").strip())
    assert done["is_error"] is True
    assert done["stop_kind"] == "error"
    assert done["stop_reason"] == "error"


def test_the_query_route_reports_it_too(client: TestClient) -> None:
    """`/v1/query` is the stateless route and shares nothing with the session
    store, so it is the one surface a session-level fix could miss."""
    body = client.post("/v1/query", json={"prompt": REFUSED}).json()
    assert body["is_error"] is True
    assert body["stop_kind"] == "error"
