"""The agent's memory, kept in a store past the session home (GP-76). **Free.**

The agent writes memory into the session's own `HOME`, which closing the session
deletes (GP-39). These pin the three things the store has to get right: a later
session reads what an earlier one wrote, a session never writes back a stale
copy of a file it did not change, and a deletion never erases a newer write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service import memory
from agent_service.api import create_app
from agent_service.config import AGENT_HOME_SOURCE, Settings

FAKE = (sys.executable, str(Path(__file__).parent / "fake_cli_agent.py"))


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "home",
        "transcript_store": tmp_path / "transcripts",
        "memory_store": tmp_path / "memory",
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


def _turn(client: TestClient, sid: str, prompt: str) -> dict:
    return client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt}).json()


# --- end to end, through the routes and the fake agent ----------------------


def test_a_later_session_reads_what_an_earlier_one_remembered(
    client: TestClient, tmp_path: Path
) -> None:
    """The point of the store: the first session's home is gone, its memory
    is not."""
    first = _open(client)
    _turn(client, first, "remember: the build port is 4321")
    client.delete(f"/v1/sessions/{first}")

    body = _turn(client, _open(client), "recall")

    assert "the build port is 4321" in body["result"]
    assert (tmp_path / "memory" / "workspace" / "MEMORY.md").is_file()


def test_a_one_shot_turn_reads_and_keeps_memory_too(client: TestClient) -> None:
    """`/v1/query` is not a turn with a smaller boundary, and it is not one with
    a smaller memory either."""
    client.post("/v1/query", json={"prompt": "remember: from a one-shot"})
    assert "from a one-shot" in _turn(client, _open(client), "recall")["result"]


def test_a_streamed_turn_reads_and_keeps_memory_too(client: TestClient) -> None:
    """The third route that starts a turn. It passes the same runner seam."""
    sid = _open(client)
    with client.stream("POST", f"/v1/sessions/{sid}/messages/stream",
                       json={"prompt": "remember: from a stream"}) as response:
        b"".join(response.iter_bytes())
    assert "from a stream" in _turn(client, _open(client), "recall")["result"]


def test_a_failed_turn_does_not_undo_an_earlier_write(client: TestClient) -> None:
    """`finish` is reached on every ending; a failed turn changed nothing, so
    it pushes nothing and the store keeps what the turn before it wrote."""
    sid = _open(client)
    _turn(client, sid, "remember: kept")
    _turn(client, sid, "exit:1")
    assert "kept" in _turn(client, _open(client), "recall")["result"]


def test_a_forgotten_memory_is_gone_for_the_next_session(client: TestClient) -> None:
    sid = _open(client)
    _turn(client, sid, "remember: short-lived")
    _turn(client, sid, "forget")
    assert "(none)" in _turn(client, _open(client), "recall")["result"]


def test_no_store_means_memory_lasts_the_session(tmp_path: Path) -> None:
    """`memory_store=None` is the behaviour before GP-76, and nothing is written
    outside the home."""
    settings = _settings(tmp_path, memory_store=None)
    with TestClient(create_app(settings)) as running:
        first = _open(running)
        _turn(running, first, "remember: gone")
        assert "gone" in _turn(running, first, "recall")["result"]
        assert "(none)" in _turn(running, _open(running), "recall")["result"]
    assert not (tmp_path / "memory").exists()


# --- pull and push, directly ------------------------------------------------


def test_push_sends_only_what_the_turn_changed(tmp_path: Path) -> None:
    """A pulls, B rewrites a file and pushes, A pushes without having touched
    that file: B's version must survive."""
    store, a_home, b_home = tmp_path / "store", tmp_path / "a", tmp_path / "b"
    store.mkdir()
    (store / "MEMORY.md").write_text("v1")

    a_snap = memory.pull(store, a_home)
    b_snap = memory.pull(store, b_home)
    (b_home / "MEMORY.md").write_text("v2 from b")
    memory.push(b_home, store, b_snap)
    (a_home / "notes.md").write_text("only in a")
    memory.push(a_home, store, a_snap)

    assert (store / "MEMORY.md").read_text() == "v2 from b"
    assert (store / "notes.md").read_text() == "only in a"


def test_a_deletion_never_erases_a_newer_write(tmp_path: Path) -> None:
    store, a_home, b_home = tmp_path / "store", tmp_path / "a", tmp_path / "b"
    store.mkdir()
    (store / "MEMORY.md").write_text("v1")
    (store / "old.md").write_text("old")

    a_snap = memory.pull(store, a_home)
    b_snap = memory.pull(store, b_home)
    (b_home / "MEMORY.md").write_text("v2 from b")
    memory.push(b_home, store, b_snap)
    (a_home / "MEMORY.md").unlink()
    (a_home / "old.md").unlink()
    memory.push(a_home, store, a_snap)

    assert (store / "MEMORY.md").read_text() == "v2 from b", "the newer write is kept"
    assert not (store / "old.md").exists(), "an unchanged file is deleted"


def test_pull_replaces_the_home_folder(tmp_path: Path) -> None:
    """A file left in the home by an earlier turn, and since deleted from the
    store by another session, is not resurrected by the next push."""
    store, home = tmp_path / "store", tmp_path / "home"
    store.mkdir()
    home.mkdir()
    (home / "stale.md").write_text("deleted elsewhere")
    memory.push(home, store, memory.pull(store, home))
    assert not (store / "stale.md").exists()


def test_the_project_slug_is_the_agents(tmp_path: Path) -> None:
    """The agent's own `slugify` of the basename (GP-76)."""
    assert memory.project_slug(Path("/workspace")) == "workspace"
    assert memory.project_slug(Path("/w/My Repo.v2")) == "my-repo-v2"
    assert memory.project_slug(Path("/w/---")) == "project"
    assert memory.home_folder(tmp_path, Path("/workspace")) == (
        tmp_path / ".gemini" / "tmp" / "workspace" / "memory"
    )


def test_the_published_field_names_the_store_variable() -> None:
    assert AGENT_HOME_SOURCE["memory"] == {
        "kept": True,
        "in_home": False,
        "variable": "AGENT_SERVICE_MEMORY_STORE",
        "default_path": "/var/lib/agent-service/memory",
    }
