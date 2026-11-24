"""`transcript_path` on `RunResponse` and `SessionRecord` (CP-160).

Free: the transcript is created in a temporary home by the test, as the CLI
would write it, and the agent is faked.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock
from httpx import ASGITransport, AsyncClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import SessionRegistry
from agent_service.sessions import AgentSession
from agent_service.transcript import TranscriptLocator
from agent_spec.openapi.schemas import RunOptions
from tests.conftest import FakeRun
from tests.test_api_stream import parse_sse
from tests.test_sessions import FakeClient, _result

SDK_ID = "e79dcff9-1c2b-4d5e-8f90-123456789abc"
SLUG = "-var-lib-agent-harness-workspace"
EXPECTED = f"{SLUG}/{SDK_ID}.jsonl"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def settings(tmp_path: Path, home: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws", require_credentials=False, agent_home=home
    )


def _write_transcript(home: Path, slug: str = SLUG, sdk_id: str = SDK_ID) -> Path:
    path = home / "projects" / slug / f"{sdk_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"user"}\n', encoding="utf-8")
    return path


# --- the locator ------------------------------------------------------------


def test_the_path_is_relative_to_the_store_with_forward_slashes(settings, home) -> None:
    _write_transcript(home)
    assert TranscriptLocator(settings).locate(SDK_ID) == EXPECTED


def test_no_id_is_null(settings) -> None:
    assert TranscriptLocator(settings).locate(None) is None


def test_no_file_is_null_and_does_not_raise(settings) -> None:
    # The store does not even exist.
    assert TranscriptLocator(settings).locate(SDK_ID) is None


def test_an_id_that_is_not_a_uuid_is_not_looked_up(settings, home) -> None:
    _write_transcript(home, sdk_id="not-a-uuid")
    locator = TranscriptLocator(settings)
    assert locator.locate("not-a-uuid") is None
    assert locator.locate("*") is None


def test_two_candidates_are_null(settings, home) -> None:
    _write_transcript(home)
    _write_transcript(home, slug="-workspace")
    assert TranscriptLocator(settings).locate(SDK_ID) is None


def test_written_elsewhere_is_null_even_when_a_file_exists(settings, home) -> None:
    _write_transcript(home)
    assert TranscriptLocator(settings).locate(SDK_ID, written_elsewhere=True) is None


def test_a_cached_path_whose_file_is_gone_is_null(settings, home) -> None:
    locator = TranscriptLocator(settings)
    path = _write_transcript(home)
    assert locator.locate(SDK_ID) == EXPECTED
    path.unlink()
    assert locator.locate(SDK_ID) is None


def test_no_home_configured_means_the_cli_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_transcript(tmp_path / ".claude")
    settings = Settings(workspace_dir=tmp_path / "ws", require_credentials=False)
    assert TranscriptLocator(settings).locate(SDK_ID) == EXPECTED


# --- one-shot /v1/query -----------------------------------------------------


@pytest.fixture
async def query_client(settings, fake_factory):
    factory, state = fake_factory
    state["outcome"] = dataclasses.replace(state["outcome"], session_id=SDK_ID)

    def run_factory(req, settings_):  # noqa: ANN001, ARG001
        return FakeRun(state["events"], state["outcome"])

    app = create_app(settings=settings, run_factory=run_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_a_query_reports_the_file_it_wrote(query_client, home) -> None:
    _write_transcript(home)
    r = await query_client.post("/v1/query", json={"prompt": "hi"})
    assert r.status_code == 200
    assert r.json()["transcript_path"] == EXPECTED


async def test_a_streamed_query_reports_it_on_done(query_client, home) -> None:
    _write_transcript(home)
    r = await query_client.post("/v1/query/stream", json={"prompt": "hi"})
    done = [payload for name, payload in parse_sse(r.text) if name == "done"]
    assert done[0]["transcript_path"] == EXPECTED


async def test_a_query_whose_file_is_not_found_reports_null(query_client) -> None:
    r = await query_client.post("/v1/query", json={"prompt": "hi"})
    assert r.status_code == 200
    assert r.json()["transcript_path"] is None


# --- sessions ---------------------------------------------------------------


def _turn() -> list[object]:
    return [
        SystemMessage(subtype="init", data={"session_id": SDK_ID}),
        AssistantMessage(content=[TextBlock(text="hello")], model="claude-sonnet-5"),
        _result(session_id=SDK_ID),
    ]


async def _client_around(settings, fake_factory, session):  # noqa: ANN001, ANN202
    def factory(options, settings_, title=None):  # noqa: ANN001, ARG001
        return session

    registry = SessionRegistry(settings, session_factory=factory)
    run_factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=run_factory, registry=registry)
    sid = await registry.create(RunOptions(), None)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), sid


def _listed(listing: dict, sid: str) -> dict:
    return next(s for s in listing["sessions"] if s["session_id"] == sid)


async def test_a_session_reports_null_before_its_first_turn_and_the_file_after(
    settings, fake_factory, home
) -> None:
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _o: FakeClient(turns=[_turn(), _turn()])
    )
    ac, sid = await _client_around(settings, fake_factory, session)
    async with ac:
        before = _listed((await ac.get("/v1/sessions")).json(), sid)
        assert before["transcript_path"] is None

        # The CLI writes the file during the turn; the fake writes it first.
        _write_transcript(home)
        turn = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        assert turn.json()["transcript_path"] == EXPECTED

        streamed = await ac.post(
            f"/v1/sessions/{sid}/messages/stream", json={"prompt": "again"}
        )
        done = [p for name, p in parse_sse(streamed.text) if name == "done"]
        assert done[0]["transcript_path"] == EXPECTED

        after = _listed((await ac.get("/v1/sessions")).json(), sid)
        assert after["transcript_path"] == EXPECTED


async def test_a_session_whose_file_is_not_found_reports_null(
    settings, fake_factory
) -> None:
    session = AgentSession(
        RunOptions(), settings, client_factory=lambda _o: FakeClient(turns=[_turn()])
    )
    ac, sid = await _client_around(settings, fake_factory, session)
    async with ac:
        turn = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        assert turn.json()["transcript_path"] is None
        assert _listed((await ac.get("/v1/sessions")).json(), sid)["transcript_path"] is None


async def test_a_session_resumed_through_the_store_reports_null_on_every_turn(
    settings, fake_factory, home
) -> None:
    """CP-153: the SDK runs such a session in a temporary config directory, so
    the file under the home, even when one exists, lacks those turns."""
    _write_transcript(home)
    session = AgentSession(
        RunOptions(resume=SDK_ID),
        settings,
        client_factory=lambda _o: FakeClient(turns=[_turn(), _turn()]),
        session_store=object(),
    )
    ac, sid = await _client_around(settings, fake_factory, session)
    async with ac:
        for prompt in ("one", "two"):
            turn = await ac.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
            assert turn.status_code == 200
            assert turn.json()["transcript_path"] is None
        assert _listed((await ac.get("/v1/sessions")).json(), sid)["transcript_path"] is None


def test_a_resume_without_a_store_or_a_store_without_a_resume_is_not_elsewhere(
    settings,
) -> None:
    def make(options: RunOptions, store: object | None) -> AgentSession:
        return AgentSession(
            options, settings, client_factory=lambda _o: FakeClient(), session_store=store
        )

    assert make(RunOptions(resume=SDK_ID), None).transcript_elsewhere is False
    assert make(RunOptions(), object()).transcript_elsewhere is False
    assert make(RunOptions(resume=SDK_ID), object()).transcript_elsewhere is True
