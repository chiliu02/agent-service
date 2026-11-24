"""`transcript_path`: which file in the store holds a conversation (`PI-72`).

**Free: the fake agent, no key, no model.** The fake writes its session file
where the real agent does, flat under `--session-dir` and named
`<timestamp>_<id>.jsonl`, so the rule is exercised against the real layout.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def client(tmp_path: Path, store: Path) -> TestClient:
    settings = Settings(
        workspace_dir=tmp_path / "workspace",
        agent_dir_root=tmp_path / "agent-dirs",
        session_store=store,
        pi_binary=FAKE,
        require_credentials=False,
    )
    with TestClient(create_app(settings)) as running:
        yield running


def _open(client: TestClient, **body) -> str:
    response = client.post("/v1/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _turn(client: TestClient, sid: str, prompt: str = "one") -> dict:
    response = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
    assert response.status_code == 200, response.text
    return response.json()


def _done(text: str) -> dict:
    for block in reversed(text.strip().split("\n\n")):
        lines = block.splitlines()
        if "event: done" in lines:
            return json.loads(next(l for l in lines if l.startswith("data: "))[6:])
    raise AssertionError(f"no done frame in {text!r}")


def _assert_names_the_file(store: Path, path: str, sid: str, sdk_id: str) -> None:
    relative = PurePosixPath(path)
    assert not relative.is_absolute() and ".." not in relative.parts
    assert relative.parts[0] == sid
    assert relative.name.endswith(f"_{sdk_id}.jsonl")
    assert (store / relative).is_file()


def test_a_turn_reports_the_file_that_holds_the_conversation(
    client: TestClient, store: Path
) -> None:
    sid = _open(client)
    body = _turn(client, sid)
    path = body["transcript_path"]
    _assert_names_the_file(store, path, sid, body["sdk_session_id"])

    # The later turn appends to the same file, so the answer does not move.
    assert _turn(client, sid, "two")["transcript_path"] == path
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] == path
    listed = client.get("/v1/sessions").json()["sessions"]
    assert [s["transcript_path"] for s in listed if s["session_id"] == sid] == [path]


def test_a_streamed_turn_reports_it_in_done(client: TestClient, store: Path) -> None:
    sid = _open(client)
    response = client.post(f"/v1/sessions/{sid}/messages/stream",
                           json={"prompt": "one"})
    assert response.status_code == 200
    done = _done(response.text)
    _assert_names_the_file(store, done["transcript_path"], sid,
                           done["sdk_session_id"])


def test_null_before_the_first_turn(client: TestClient) -> None:
    sid = _open(client)
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None


def test_null_before_the_first_turn_with_a_supplied_id(
    client: TestClient, store: Path
) -> None:
    """The id is known at creation and the file is not (`PI-14`)."""
    supplied = str(uuid.uuid4())
    sid = _open(client, sdk_session_id=supplied)
    record = client.get(f"/v1/sessions/{sid}").json()
    assert record["sdk_session_id"] == supplied
    assert record["transcript_path"] is None
    _assert_names_the_file(store, _turn(client, sid)["transcript_path"], sid,
                           supplied)


def test_null_for_a_one_shot_run(client: TestClient, store: Path) -> None:
    """Its directory is removed when the turn ends, so there is nothing to name."""
    buffered = client.post("/v1/query", json={"prompt": "one"})
    assert buffered.status_code == 200, buffered.text
    assert buffered.json()["transcript_path"] is None

    streamed = client.post("/v1/query/stream", json={"prompt": "one"})
    assert _done(streamed.text)["transcript_path"] is None
    assert not list(store.glob("query-*"))


def test_a_resumed_session_reports_its_own_copy(
    client: TestClient, store: Path
) -> None:
    """**The copy holds the whole conversation, under the original name** (`PI-52`).

    Before its first turn it already holds the source's history; its turns then
    go into that same file. The source keeps reporting its own file.
    """
    first = _open(client)
    source_body = _turn(client, first)
    issued = source_body["sdk_session_id"]
    source_path = source_body["transcript_path"]

    resumed = _open(client, options={"resume": issued})
    before = client.get(f"/v1/sessions/{resumed}").json()["transcript_path"]
    _assert_names_the_file(store, before, resumed, issued)
    assert PurePosixPath(before).name == PurePosixPath(source_path).name

    after = _turn(client, resumed, "and now")["transcript_path"]
    assert after == before
    assert len(list((store / resumed).glob("*.jsonl"))) == 1, (
        "a resumed turn must not start a second file"
    )
    assert client.get(f"/v1/sessions/{first}").json()["transcript_path"] == source_path


def test_a_directory_with_two_matches_is_null(client: TestClient, store: Path) -> None:
    """Null when the build cannot name ONE file, never a guess between two."""
    supplied = str(uuid.uuid4())
    sid = _open(client, sdk_session_id=supplied)
    (store / sid / f"2026-01-01T00-00-00_{supplied}.jsonl").write_text("{}\n")
    (store / sid / f"2026-01-02T00-00-00_{supplied}.jsonl").write_text("{}\n")
    assert client.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None
