"""`options.resume`, which this build accepted and applied to nothing (GP-70).

**Free: the fake agent, no key, no model.** That is not a shortcut here, it is
the right instrument — the defect was that the field never reached an argv, so
what has to be pinned is the argv and the file the session opens holding. What
the agent then does with a transcript is GP-11's measurement and is not
re-litigated per turn.

**The three cases the old code got wrong**, each its own test below: an id that
resolves is resumed, an id that does not is refused rather than answered with a
fresh conversation, and both of those still hold once the session that issued the
id is gone -- which is the case that made the field useless, because the idle
sweep reaches every session eventually.
"""

from __future__ import annotations

import sys
import uuid
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


def _turn(client: TestClient, sid: str, prompt: str = "one") -> str:
    """One turn, returning the SDK id it issued."""
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
    assert body.status_code == 200, body.text
    return body.json()["sdk_session_id"]


def test_an_id_this_build_never_issued_is_refused(client: TestClient) -> None:
    """**A 404, never a 201** (GP-70).

    This is the whole defect in one assertion: it answered `201` and opened a
    conversation with no history, so a caller that asked to continue one was
    handed another and told nothing.
    """
    response = client.post(
        "/v1/sessions", json={"options": {"resume": str(uuid.uuid4())}}
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("/resume-target-not-found")
    # The detail names what to send instead. A refusal that does not is a
    # refusal the caller has to guess their way out of.
    assert "sdk session id" in response.json()["detail"].lower()


def test_resuming_opens_the_session_holding_the_conversation(
    client: TestClient, tmp_path: Path
) -> None:
    """The copy is taken at CREATE, so turn 1 takes turn 2's branch (GP-70)."""
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)

    second = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    )
    assert second.status_code == 201
    resumed = second.json()["session_id"]

    from agent_service.registry import Registry  # noqa: PLC0415

    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    session = registry.get(resumed)
    assert session.resumed_from == issued
    # **Its own copy, not the other session's file.** Two sessions writing one
    # transcript is a conversation each of them corrupts.
    assert session.transcript.exists()
    assert session.transcript != registry.get(first).transcript
    assert session.has_transcript, "turn 1 here must resume rather than name"


def test_the_first_turn_of_a_resumed_session_passes_session_file(
    client: TestClient,
) -> None:
    """**The argv is the assertion** (GP-11, GP-70).

    `--session-file` resumes and `--session-id` names; the old code sent the
    second on this path, which is why nothing was continued.
    """
    seen: list[list[str]] = []
    from agent_service import cli as cli_mod  # noqa: PLC0415

    original = cli_mod.CliRunner.argv

    def spy(self, prompt, **kwargs):
        argv = original(self, prompt, **kwargs)
        seen.append(argv)
        return argv

    cli_mod.CliRunner.argv = spy  # type: ignore[method-assign]
    try:
        first = client.post("/v1/sessions", json={}).json()["session_id"]
        issued = _turn(client, first)
        resumed = client.post(
            "/v1/sessions", json={"options": {"resume": issued}}
        ).json()["session_id"]
        _turn(client, resumed, "and now")
    finally:
        cli_mod.CliRunner.argv = original  # type: ignore[method-assign]

    opening, continuing = seen[0], seen[-1]
    assert "--session-id" in opening, "a fresh conversation is NAMED"
    assert "--session-file" in continuing, "a resumed one is LOADED"
    assert "--session-id" not in continuing, "the two are mutually exclusive"


def test_any_id_the_session_issued_resolves_not_only_the_newest(
    client: TestClient,
) -> None:
    """GP-35, now actually reachable.

    The caller most likely to resume is the one whose connection dropped, and it
    is holding an id from several turns ago.
    """
    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    ids = [_turn(client, sid, prompt) for prompt in ("one", "two", "three")]
    assert len(set(ids)) == 3, "this build mints a new id per turn (GP-34)"

    for issued in ids:
        response = client.post("/v1/sessions", json={"options": {"resume": issued}})
        assert response.status_code == 201, f"{issued} did not resolve"


def test_a_conversation_survives_the_session_that_issued_it(
    client: TestClient,
) -> None:
    """**The case the in-memory map could never serve** (GP-70).

    `DELETE` drops the session and keeps the transcript, deliberately. Before
    the index existed, the only route from an id to that file went through the
    session -- so the file outlived every way of reaching it.
    """
    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, sid)
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404

    response = client.post("/v1/sessions", json={"options": {"resume": issued}})
    assert response.status_code == 201, "the transcript is still on disk"


def test_the_index_outlives_the_process(tmp_path: Path) -> None:
    """**On disk, so a restart does not lose it** (GP-70).

    The registry is memory and the store is the volume. A second app over the
    same store is the same thing a container replacement is, minus the container.
    """
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as first:
        sid = first.post("/v1/sessions", json={}).json()["session_id"]
        issued = _turn(first, sid)

    with TestClient(create_app(_settings(tmp_path))) as second:
        assert second.get(f"/v1/sessions/{sid}").status_code == 404, "memory is gone"
        response = second.post("/v1/sessions", json={"options": {"resume": issued}})
        assert response.status_code == 201, "the store is not"


def test_a_one_shot_query_is_never_indexed(client: TestClient) -> None:
    """Nothing resumes from `/v1/query`, and its transcript is not kept.

    Indexing one would promise continuity the route does not have -- and point
    an id at a file under an agent home that is deleted as the request ends.
    """
    body = client.post("/v1/query", json={"prompt": "say hello"})
    assert body.status_code == 200
    issued = body.json()["sdk_session_id"]
    assert issued, "the id is reported even though it resumes nothing (GP-34)"

    response = client.post("/v1/sessions", json={"options": {"resume": issued}})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "..", "a/b", "a\\b", "", " "],
)
def test_an_id_shaped_like_a_path_never_reaches_the_filesystem(
    client: TestClient, hostile: str
) -> None:
    """The one route where a caller's string names a file (GP-70).

    Refused as *no such conversation* rather than as a validation error: it is
    not an id this build issued, which is the same answer any other unknown id
    gets, and saying more would confirm the shape of the store.
    """
    response = client.post("/v1/sessions", json={"options": {"resume": hostile}})
    # `""` is refused by the model itself -- an empty resume is not an omission.
    assert response.status_code in (404, 422), hostile


def test_a_resumed_session_does_not_take_over_the_id_it_resumed(
    client: TestClient, tmp_path: Path
) -> None:
    """**The turn-scoped id spares this build the Pi build's trade-off** (GP-70).

    There a resumed session answers to the id it was given, so one id names two
    conversations and the index has to choose. Here the agent mints a new id
    every turn (GP-34), so the resumed session indexes ITS id against its own
    transcript and the id that was resumed keeps pointing at the conversation it
    came from. Both stay resumable, independently.
    """
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)

    resumed = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    ).json()["session_id"]
    later = _turn(client, resumed, "and now")
    assert later != issued, "this build mints a new id per turn (GP-34)"

    index = tmp_path / "store" / "by-id"
    assert (index / issued).read_text(encoding="utf-8") == f"{first}.jsonl"
    assert (index / later).read_text(encoding="utf-8") == f"{resumed}.jsonl"

    # And both still resolve, which is the property the Pi build cannot offer.
    for id_ in (issued, later):
        assert client.post(
            "/v1/sessions", json={"options": {"resume": id_}}
        ).status_code == 201

