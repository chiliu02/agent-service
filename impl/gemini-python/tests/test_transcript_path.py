"""`transcript_path`: which file in the store is a session's conversation (GP-84).

**Free: the fake agent, no key, no model.** What is pinned is the NAME this
build reports and that the file exists where it says, relative to the store.
That a `--session-file` turn writes the loaded history into its new transcript
is GP-78's live measurement and is not re-litigated here; the fake writes a
fixed transcript per turn.
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "workspace",
        agent_home_root=tmp_path / "home",
        transcript_store=tmp_path / "store",
        gemini_binary=FAKE,
        require_credentials=False,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def _open(client: TestClient, **options) -> str:
    body = client.post("/v1/sessions", json={"options": options} if options else {})
    assert body.status_code == 201, body.text
    return body.json()["session_id"]


def _turn(client: TestClient, sid: str, prompt: str = "one") -> dict:
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
    assert body.status_code == 200, body.text
    return body.json()


def _done(text: str) -> dict:
    """The `done` frame's payload from an SSE body."""
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        if "event: done" in lines:
            data = next(l for l in lines if l.startswith("data: "))
            return json.loads(data[len("data: "):])
    raise AssertionError(f"no done frame in {text!r}")


def test_null_before_the_first_turn(client: TestClient) -> None:
    """Nothing has been copied yet, so there is no file to name."""
    sid = _open(client)
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None
    listed = client.get("/v1/sessions").json()["sessions"]
    assert [s["transcript_path"] for s in listed] == [None]


def test_reported_after_a_turn_relative_to_the_store(
    client: TestClient, tmp_path: Path
) -> None:
    """Keyed by the SERVICE session id, and the same on every surface."""
    sid = _open(client)
    first = _turn(client, sid)
    assert first["transcript_path"] == f"{sid}.jsonl"
    assert (tmp_path / "store" / first["transcript_path"]).is_file()

    # A second turn continues the SAME file; it is never a second one.
    assert _turn(client, sid, "two")["transcript_path"] == f"{sid}.jsonl"
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] == f"{sid}.jsonl"
    listed = client.get("/v1/sessions").json()["sessions"]
    assert [s["transcript_path"] for s in listed] == [f"{sid}.jsonl"]


def test_a_streamed_turn_reports_it_on_done(client: TestClient) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages/stream",
                           json={"prompt": "one"})
    assert response.status_code == 200
    assert _done(response.text)["transcript_path"] == f"{sid}.jsonl"


def test_a_resumed_session_names_its_own_copy_from_creation(
    client: TestClient, tmp_path: Path
) -> None:
    """**The resume case**: a new file holding everything, not the old one.

    The copy is taken at create (GP-70), so the path is reported before the
    resumed session's first turn, and every later turn continues that file.
    The conversation it came from keeps its own file, untouched.
    """
    first = _open(client)
    issued = _turn(client, first)["sdk_session_id"]
    before = (tmp_path / "store" / f"{first}.jsonl").read_bytes()

    resumed = _open(client, resume=issued)
    assert resumed != first
    detail = client.get(f"/v1/sessions/{resumed}").json()
    assert detail["transcript_path"] == f"{resumed}.jsonl"
    assert (tmp_path / "store" / f"{resumed}.jsonl").read_bytes() == before

    assert _turn(client, resumed, "and now")["transcript_path"] == f"{resumed}.jsonl"
    assert (tmp_path / "store" / f"{first}.jsonl").read_bytes() == before


def test_a_failed_first_turn_leaves_it_null(client: TestClient) -> None:
    """A turn that kept nothing has written nothing to name."""
    sid = _open(client)
    assert client.post(f"/v1/sessions/{sid}/messages",
                       json={"prompt": "exit:1"}).status_code == 502
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None


@pytest.mark.parametrize("route", ["/v1/query", "/v1/query/stream"])
def test_a_one_shot_query_is_null(client: TestClient, route: str) -> None:
    """Its transcript is under a home deleted as the request ends, never in
    the store, so there is no file to point a caller at."""
    response = client.post(route, json={"prompt": "say hello"})
    assert response.status_code == 200
    body = response.json() if route == "/v1/query" else _done(response.text)
    assert "transcript_path" in body
    assert body["transcript_path"] is None
