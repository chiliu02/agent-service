"""`options.resume`, which this build accepted and applied to nothing (`PI-52`).

**Free: the fake agent, no key, no model.** That is the right instrument rather
than a shortcut -- the defect was that the field never reached an argv, so what
has to be pinned is the argv and the directory the session opens holding.

**What the agent does with a session directory was measured against the real
binary**, keylessly, and is not re-litigated per turn: with `--session-dir`
given, the agent stores flat in that directory rather than under its
`--<cwd>--` default layout; `--session <id>` loads an existing conversation and
echoes its original header; `--session-id <id>` LOADS one too and only creates
when it is missing; and passing both is `Error: --session-id cannot be combined
with --session`. `PI-52` carries those.
"""

from __future__ import annotations

import sys
import uuid
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


def _turn(client: TestClient, sid: str, prompt: str = "one") -> str:
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
    assert body.status_code == 200, body.text
    return body.json()["sdk_session_id"]


def _spy_argv(monkeypatch) -> list[list[str]]:
    """Every argv the runner builds, in order. **The argv is the assertion.**"""
    seen: list[list[str]] = []
    from agent_service import pi as pi_mod

    original = pi_mod.PiRunner.argv

    def spy(self, prompt, *, sdk_session_id, resume):
        argv = original(self, prompt, sdk_session_id=sdk_session_id, resume=resume)
        seen.append(argv)
        return argv

    monkeypatch.setattr(pi_mod.PiRunner, "argv", spy)
    return seen


def test_an_id_this_build_never_issued_is_refused(client: TestClient) -> None:
    """**A 404, never a 201** (`PI-52`).

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


def test_the_first_turn_of_a_resumed_session_loads_rather_than_names(
    client: TestClient, monkeypatch
) -> None:
    """`--session` LOADS and `--session-id` NAMES-or-loads (`PI-14`, `PI-52`).

    The old code sent `--session-id <a fresh uuid>` here, which creates, and
    against a session directory of its own -- so nothing could have been
    continued by either flag.
    """
    seen = _spy_argv(monkeypatch)

    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)
    resumed = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    ).json()["session_id"]
    _turn(client, resumed, "and now")

    opening, continuing = seen[0], seen[-1]
    assert "--session-id" in opening, "a fresh conversation is NAMED"
    assert "--session" in continuing
    assert continuing[continuing.index("--session") + 1] == issued
    assert "--session-id" not in continuing, "the agent refuses the pair outright"


def test_a_resumed_session_gets_its_own_copy_of_the_conversation(
    client: TestClient,
) -> None:
    """**A copy, not a shared directory** (`PI-52`).

    Two sessions writing one session directory interleave into a file each of
    them then reads back as its own history.
    """
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)
    resumed = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    ).json()["session_id"]

    from agent_service.registry import Registry  # noqa: PLC0415

    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    source = registry.get(first)
    session = registry.get(resumed)
    assert session.resumed_from == issued
    assert session.sdk_session_ids == [issued]
    assert session.session_dir != source.session_dir
    copied = {p.name for p in session.session_dir.glob("*.jsonl")}
    assert copied and copied == {p.name for p in source.session_dir.glob("*.jsonl")}


def test_a_conversation_survives_the_session_that_issued_it(
    client: TestClient,
) -> None:
    """**The case the in-memory map could never serve** (`PI-52`).

    `DELETE` drops the session and keeps the conversation, deliberately. Before
    the index existed, the only route from an id to that directory went through
    the session -- so the files outlived every way of reaching them.
    """
    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, sid)
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404

    response = client.post("/v1/sessions", json={"options": {"resume": issued}})
    assert response.status_code == 201, "the conversation is still on disk"


def test_the_index_outlives_the_process(tmp_path: Path) -> None:
    """**On disk, so a restart does not lose it** (`PI-52`).

    A second app over the same store is what a container replacement is, minus
    the container.
    """
    with TestClient(create_app(_settings(tmp_path))) as first:
        sid = first.post("/v1/sessions", json={}).json()["session_id"]
        issued = _turn(first, sid)

    with TestClient(create_app(_settings(tmp_path))) as second:
        assert second.get(f"/v1/sessions/{sid}").status_code == 404, "memory is gone"
        response = second.post("/v1/sessions", json={"options": {"resume": issued}})
        assert response.status_code == 201, "the store is not"


def test_a_supplied_id_still_NAMES_rather_than_resuming(
    client: TestClient, monkeypatch
) -> None:
    """**The case `resumed_from` exists to keep separate** (`PI-14`, `PI-52`).

    A session holding an id and no turns is either a caller-supplied id, which
    must be named, or a resume, which must be loaded. Keying on the id alone
    would silently turn every supplied id into a resume of a conversation that
    does not exist yet.
    """
    seen = _spy_argv(monkeypatch)
    supplied = str(uuid.uuid4())
    sid = client.post(
        "/v1/sessions", json={"sdk_session_id": supplied}
    ).json()["session_id"]
    _turn(client, sid)

    argv = seen[-1]
    assert "--session-id" in argv
    assert argv[argv.index("--session-id") + 1] == supplied
    assert "--session" not in argv


def test_resuming_into_a_different_working_directory_is_refused(
    client: TestClient, tmp_path: Path
) -> None:
    """**The agent resolves a conversation against its cwd** (`PI-52`).

    Refused at creation, naming both directories, rather than left to become the
    agent's own *no session found* one turn later -- same status, but a detail a
    caller can act on.
    """
    (tmp_path / "workspace" / "sub").mkdir(parents=True, exist_ok=True)
    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, sid)

    response = client.post("/v1/sessions", json={
        "options": {"resume": issued, "working_directory": "sub"},
    })
    assert response.status_code == 404
    assert response.json()["type"].endswith("/resume-target-not-found")
    assert "working_directory" in response.json()["detail"]


def test_a_one_shot_query_is_never_indexed(client: TestClient) -> None:
    """Nothing resumes from `/v1/query`, so nothing points at its directory."""
    body = client.post("/v1/query", json={"prompt": "say hello"})
    assert body.status_code == 200
    issued = body.json()["sdk_session_id"]
    assert issued, "the id is reported even though it resumes nothing"

    response = client.post("/v1/sessions", json={"options": {"resume": issued}})
    assert response.status_code == 404


def test_a_supplied_id_together_with_resume_is_still_400(client: TestClient) -> None:
    """Unchanged by the wiring, and it must stay that way (AS-14).

    Naming a new conversation and continuing an old one are two different
    conversations in one session; the agent refuses the equivalent pair of flags
    outright, and this refuses it before a turn is taken.
    """
    response = client.post("/v1/sessions", json={
        "sdk_session_id": str(uuid.uuid4()),
        "options": {"resume": str(uuid.uuid4())},
    })
    assert response.status_code == 400


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "..", "a/b", "a\\b"])
def test_an_id_shaped_like_a_path_never_reaches_the_filesystem(
    client: TestClient, hostile: str
) -> None:
    """The one route where a caller's string names a file (`PI-52`)."""
    response = client.post("/v1/sessions", json={"options": {"resume": hostile}})
    assert response.status_code == 404, hostile


def test_a_resumed_session_reports_the_id_it_was_given(client: TestClient) -> None:
    """**The decision, pinned: a resume KEEPS its id** (`PI-53`, `PI-52`).

    The agent's own answer to branching is `--fork`, which mints a new id so two
    branches never share one. This build does not fork: the id is stable across
    turns here (`PI-13`) and a client may key on it, so handing back a different
    id than the one asked for would break the one property that makes keying
    worth doing.

    The cost is recorded rather than hidden: after a resume TWO sessions answer
    to one id, and this test is what says that is intended.
    """
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)
    resumed = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    ).json()["session_id"]
    again = _turn(client, resumed, "and now")

    assert again == issued, "a resume must answer to the id it was given"
    from agent_service.registry import Registry  # noqa: PLC0415

    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    assert issued in registry.get(first).sdk_session_ids
    assert issued in registry.get(resumed).sdk_session_ids


def test_the_index_re_points_to_the_branch_with_the_most_history(
    client: TestClient, tmp_path: Path
) -> None:
    """**The consequence of keeping the id** (`PI-52`).

    One id, two directories. The marker names the copy that has just taken a
    turn -- which holds the original history plus that turn -- so a later resume
    continues the longer branch rather than the shorter one. The earlier
    directory survives on disk and is no longer reachable by that id.
    """
    import json  # noqa: PLC0415

    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = _turn(client, first)

    marker = tmp_path / "sessions" / "by-id" / issued
    assert json.loads(marker.read_text(encoding="utf-8"))["session"] == first

    resumed = client.post(
        "/v1/sessions", json={"options": {"resume": issued}}
    ).json()["session_id"]
    _turn(client, resumed, "and now")

    assert json.loads(marker.read_text(encoding="utf-8"))["session"] == resumed

