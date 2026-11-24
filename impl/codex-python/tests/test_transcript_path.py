"""`transcript_path`: the rollout of a session, relative to `<home>/sessions`. CX-75.

Free: the sessions are fakes, and the rollout is a file the test writes into a
per-test `CODEX_HOME`, under the name Codex gives it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent_service import registry as registry_module
from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import SessionRegistry
from agent_service.sessions import RunTimeout, TurnOutcome
from agent_service.transcripts import find_rollout

THREAD = "01a1eec8-fee6-7332-9a2a-4fed0b87c2fa"
REL = f"2026/11/19/rollout-2026-11-19T00-11-52-{THREAD}.jsonl"


def _write_rollout(home, rel: str = REL):  # noqa: ANN001, ANN202
    path = home / "sessions" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"session_meta"}\n', encoding="utf-8")
    return path


# --- the rule -------------------------------------------------------------------


def test_one_rollout_is_reported_relative_with_forward_slashes(tmp_path) -> None:  # noqa: ANN001
    _write_rollout(tmp_path)
    assert find_rollout(tmp_path, THREAD) == REL


def test_no_rollout_is_null(tmp_path) -> None:  # noqa: ANN001
    assert find_rollout(tmp_path, THREAD) is None
    assert find_rollout(tmp_path / "missing", THREAD) is None


def test_two_rollouts_for_one_thread_is_null(tmp_path) -> None:  # noqa: ANN001
    _write_rollout(tmp_path)
    _write_rollout(tmp_path, f"2026/11/20/rollout-2026-11-20T09-00-00-{THREAD}.jsonl")
    assert find_rollout(tmp_path, THREAD) is None


def test_another_threads_rollout_is_not_matched(tmp_path) -> None:  # noqa: ANN001
    _write_rollout(tmp_path, "2026/11/19/rollout-2026-11-19T00-11-53-01a1eec8-0000-7000-8000-000000000000.jsonl")
    assert find_rollout(tmp_path, THREAD) is None


def test_the_reported_path_must_name_the_same_file(tmp_path) -> None:  # noqa: ANN001
    path = _write_rollout(tmp_path)
    assert find_rollout(tmp_path, THREAD, str(path)) == REL
    # The verbatim form Codex reports after a resume, on Windows.
    assert find_rollout(tmp_path, THREAD, "\\\\?\\" + str(path.resolve())) == REL
    assert find_rollout(tmp_path, THREAD, str(tmp_path / "elsewhere.jsonl")) is None


def test_an_id_that_is_not_uuid_shaped_is_null_and_never_globbed(tmp_path) -> None:  # noqa: ANN001
    _write_rollout(tmp_path)
    assert find_rollout(tmp_path, "*") is None
    assert find_rollout(tmp_path, None) is None
    assert find_rollout(None, THREAD) is None


# --- the routes -----------------------------------------------------------------


class _Session:
    """A session whose turn writes the rollout when `writes` is true."""

    sdk_session_id = THREAD

    def __init__(self, home, writes: bool) -> None:  # noqa: ANN001
        self.home = home
        self.writes = writes
        self.reported_rollout: str | None = None

    async def open(self, options, resume=None) -> None:  # noqa: ANN001, ARG002
        return None

    async def send(self, prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG002
        if self.writes:
            self.reported_rollout = str(_write_rollout(self.home))
        return TurnOutcome(status="completed", duration_ms=1, final_response="ok")

    async def interrupt(self) -> bool:
        return False

    def context(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _app(tmp_path, writes: bool = True):  # noqa: ANN001, ANN202
    home = tmp_path / "home"
    settings = Settings(
        require_credentials=False,
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=home,
    )
    made: list[_Session] = []

    def factory(options, subdir):  # noqa: ANN001, ANN202, ARG001
        made.append(_Session(home, writes))
        return made[-1]

    registry = SessionRegistry(settings, session_factory=factory)
    return create_app(settings, registry), registry, made, home


def test_null_before_the_first_turn_and_reported_after_it(tmp_path) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path)
    with TestClient(app) as c:
        created = c.post("/v1/sessions", json={})
        assert created.status_code == 201, created.text
        assert created.json()["transcript_path"] is None
        sid = created.json()["session_id"]
        assert c.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None

        turn = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        assert turn.status_code == 200, turn.text
        assert turn.json()["transcript_path"] == REL
        assert c.get(f"/v1/sessions/{sid}").json()["transcript_path"] == REL
        listed = c.get("/v1/sessions").json()["sessions"]
        assert [s["transcript_path"] for s in listed] == [REL]


def test_null_when_the_turn_wrote_no_rollout(tmp_path) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path, writes=False)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        turn = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        assert turn.status_code == 200, turn.text
        assert turn.json()["transcript_path"] is None
        assert c.get(f"/v1/sessions/{sid}").json()["transcript_path"] is None


def test_the_streamed_turns_done_frame_carries_it(tmp_path) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        r = c.post(f"/v1/sessions/{sid}/messages/stream", json={"prompt": "hi"})
    done = _done_frame(r.text)
    assert done["transcript_path"] == REL


@pytest.mark.parametrize("route", ["/v1/query", "/v1/query/stream"])
def test_a_one_shot_reports_it(tmp_path, route) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path)
    with TestClient(app) as c:
        r = c.post(route, json={"prompt": "hi"})
    assert r.status_code == 200, r.text
    body = _done_frame(r.text) if route.endswith("stream") else r.json()
    assert body["transcript_path"] == REL


def test_a_resumed_session_reports_it_before_its_first_turn(tmp_path) -> None:  # noqa: ANN001
    """The rollout of a resumed thread already exists, and a resume keeps
    writing to it, so the record names it from the 201."""
    app, _registry, _made, home = _app(tmp_path, writes=False)
    _write_rollout(home)
    with TestClient(app) as c:
        created = c.post("/v1/sessions", json={"options": {"resume": THREAD}})
        assert created.status_code == 201, created.text
        assert created.json()["transcript_path"] == REL


def test_a_timed_out_turn_still_finds_it(tmp_path) -> None:  # noqa: ANN001
    app, registry, made, home = _app(tmp_path)

    async def slow(prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG001
        _write_rollout(home)
        raise RunTimeout("turn exceeded 1s", TurnOutcome(timed_out=True))

    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        made[-1].send = slow
        assert c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}).status_code == 504
        assert c.get(f"/v1/sessions/{sid}").json()["transcript_path"] == REL


def test_once_found_a_listing_never_searches_again(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path)
    calls: list[str] = []

    def counting(*args):  # noqa: ANN002, ANN202
        calls.append("glob")
        return find_rollout(*args)

    monkeypatch.setattr(registry_module, "find_rollout", counting)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        found = len(calls)
        for _ in range(3):
            assert c.get("/v1/sessions").json()["sessions"][0]["transcript_path"] == REL
        c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "again"})
    assert len(calls) == found


def test_a_broken_lookup_is_null_not_an_error(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, _registry, _made, _home = _app(tmp_path)

    def broken(*args):  # noqa: ANN002, ANN202
        raise OSError("the store is unreadable")

    monkeypatch.setattr(registry_module, "find_rollout", broken)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        turn = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    assert turn.status_code == 200, turn.text
    assert turn.json()["transcript_path"] is None


def _done_frame(text: str) -> dict:
    frames = [f for f in text.split("\n\n") if f.startswith("event: done")]
    assert frames, text
    return json.loads(frames[-1].split("data: ", 1)[1])
