"""`context_usage`, read after every turn and on resume (`PI-65`).

**Free: the fake agent answers the RPC commands**, shaped as the probe measured
them against the real one. What the real agent puts in `tokens` is the probe's
to measure and `PI-65`'s to record; what is pinned here is that this build asks,
publishes what it is told, and publishes `null` in each case the entry names.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.pi import PiRunner, context_figure, recorded_model

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))
WINDOW = 200000
TOKENS = 590


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "workspace",
        agent_dir_root=tmp_path / "agent-dirs",
        session_store=tmp_path / "sessions",
        pi_binary=FAKE,
        require_credentials=False,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def _open(client: TestClient, **options) -> dict:
    body = client.post("/v1/sessions", json={"options": options} if options else {})
    assert body.status_code == 201, body.text
    return body.json()


def _turn(client: TestClient, sid: str) -> str:
    body = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "one"})
    assert body.status_code == 200, body.text
    return body.json()["sdk_session_id"]


def _categories(record: dict) -> dict[str, int] | None:
    usage = record["context_usage"]
    return None if usage is None else {c["name"]: c["tokens"] for c in usage["categories"]}


# --- the three RPC answers, read into a figure ------------------------------

_MODEL = {"provider": "google", "id": "gemini-3.1-flash-lite"}
_RECORDED = ("google", "gemini-3.1-flash-lite")


def _answers(usage: object = None, listed: object = None) -> tuple[dict, dict, dict]:
    stats = {"data": {} if usage is None else {"contextUsage": usage}}
    models = [_MODEL] if listed is None else listed
    return ({"data": {"model": {**_MODEL, "contextWindow": 1048576}}},
            stats, {"data": {"models": models}})


def _figure(*answers: object, recorded: object = _RECORDED) -> object:
    return context_figure(*answers, recorded=recorded)


def test_the_figure_is_tokens_against_the_window() -> None:
    """PI-65's row: `tokens` 1 385 on a 1 048 576 window."""
    usage = {"tokens": 1385, "contextWindow": 1048576, "percent": 0.13}
    assert _figure(*_answers(usage)) == (1385, 1048576)


def test_null_after_a_compaction() -> None:
    usage = {"tokens": None, "contextWindow": 1048576, "percent": None}
    assert _figure(*_answers(usage)) is None


def test_null_when_the_agent_gives_no_context_usage() -> None:
    assert _figure(*_answers()) is None


def test_null_for_a_model_the_catalogue_does_not_list() -> None:
    """The borrowed window: the agent copies another model's entry for an id it
    does not know, so the window is not this model's (PI-65)."""
    usage = {"tokens": 1385, "contextWindow": 1048576, "percent": 0.13}
    other = [{"provider": "google", "id": "gemini-3.1-pro-preview"}]
    assert _figure(*_answers(usage, other)) is None


def test_null_for_answers_that_are_not_the_shape() -> None:
    usage = {"tokens": 1385, "contextWindow": 0}
    assert _figure(*_answers(usage)) is None
    assert _figure({}, {}, {}) is None
    assert _figure(None, None, None) is None


def test_null_when_the_agent_resolved_another_model_than_the_session_records() -> None:
    """Agent Harness's finding (PI-66): for a recorded model it cannot load,
    the agent restores the session on its default, which IS listed."""
    usage = {"tokens": 521, "contextWindow": 1000000, "percent": 0.05}
    default = {"provider": "anthropic", "id": "claude-opus-4-8"}
    answers = ({"data": {"model": {**default, "contextWindow": 1000000}}},
               {"data": {"contextUsage": usage}}, {"data": {"models": [default]}})
    assert _figure(*answers, recorded=("anthropic", "my-private-model")) is None
    assert _figure(*answers, recorded=None) is None
    assert _figure(*answers, recorded=("anthropic", "claude-opus-4-8")) == (521, 1000000)


# --- the model the session file records -------------------------------------


def _write(path: Path, *entries: dict) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "2026-10-21T00-00-00_abc.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def _reply(eid: str, parent: str | None, provider: str, model: str) -> dict:
    return {"type": "message", "id": eid, "parentId": parent,
            "message": {"role": "assistant", "provider": provider, "model": model}}


def test_the_recorded_model_is_the_latest_on_the_branch(tmp_path: Path) -> None:
    """The agent's rule: the later of the last `model_change` and the last
    assistant reply, on the branch that ends at the last entry (PI-66)."""
    change = {"type": "model_change", "id": "1", "parentId": None,
              "provider": "anthropic", "modelId": "my-private-model"}
    found = _write(tmp_path / "a", {"type": "session", "id": "abc"}, change)
    assert recorded_model(found, "abc") == ("anthropic", "my-private-model")
    later = _reply("2", "1", "google", "gemini-3.1-flash-lite")
    found = _write(tmp_path / "b", {"type": "session", "id": "abc"}, change, later)
    assert recorded_model(found, "abc") == ("google", "gemini-3.1-flash-lite")
    # A reply on an abandoned branch does not count.
    left = _reply("3", "1", "openai", "gpt-5-mini")
    leaf = {"type": "thinking_level_change", "id": "4", "parentId": "2"}
    found = _write(tmp_path / "c", change, later, left, leaf)
    assert recorded_model(found, "abc") == ("google", "gemini-3.1-flash-lite")


def test_no_recorded_model_is_none(tmp_path: Path) -> None:
    assert recorded_model(tmp_path, "abc") is None
    found = _write(tmp_path / "a", {"type": "session", "id": "abc"})
    assert recorded_model(found, "abc") is None
    cycle = [{"type": "x", "id": "1", "parentId": "2"},
             {"type": "x", "id": "2", "parentId": "1"}]
    assert recorded_model(_write(tmp_path / "b", *cycle), "abc") is None


# --- the read, against the fake agent ---------------------------------------


def _runner(tmp_path: Path) -> PiRunner:
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    change = {"type": "model_change", "id": "m1", "provider": "anthropic",
              "modelId": "claude-haiku-4-5-20251001"}
    (sessions / "2026-10-21T00-00-00_abc.jsonl").write_text(
        '{"type": "session", "id": "abc"}\n' + json.dumps(change) + "\n",
        encoding="utf-8")
    return PiRunner(binary=FAKE, workspace=tmp_path, agent_dir=tmp_path / "agent",
                    session_dir=sessions)


def test_a_read_that_does_not_answer_is_null_within_its_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_CONTEXT", "hang")
    started = time.monotonic()
    got = asyncio.run(_runner(tmp_path).read_context("abc", timeout=2.0))
    assert got is None
    assert time.monotonic() - started < 6.0


def test_an_id_the_agent_cannot_load_is_null(tmp_path: Path) -> None:
    assert asyncio.run(_runner(tmp_path).read_context("no-such-id")) is None


def test_the_read_writes_no_config(tmp_path: Path) -> None:
    """A turn may be starting beside it, reading those files (PI-65)."""
    runner = _runner(tmp_path)
    assert asyncio.run(runner.read_context("abc")) == (TOKENS, WINDOW)
    assert list((tmp_path / "agent").iterdir()) == []


# --- what the routes publish ------------------------------------------------


def test_null_before_the_first_turn(client: TestClient) -> None:
    sid = _open(client)["session_id"]
    assert client.get(f"/v1/sessions/{sid}").json()["context_usage"] is None


def test_after_a_turn_get_has_the_figure_and_it_sums_to_the_window(
    client: TestClient,
) -> None:
    sid = _open(client)["session_id"]
    _turn(client, sid)
    got = _categories(client.get(f"/v1/sessions/{sid}").json())
    assert got == {"In use": TOKENS, "Free space": WINDOW - TOKENS}


def test_after_a_streamed_turn_too(client: TestClient) -> None:
    sid = _open(client)["session_id"]
    with client.stream("POST", f"/v1/sessions/{sid}/messages/stream",
                       json={"prompt": "one"}) as stream:
        assert stream.status_code == 200
        "".join(stream.iter_text())
    got = _categories(client.get(f"/v1/sessions/{sid}").json())
    assert got == {"In use": TOKENS, "Free space": WINDOW - TOKENS}


def test_a_resumed_session_has_it_before_its_first_turn(client: TestClient) -> None:
    """**The question Agent Harness asked** (PI-65): the `201` and the first
    `GET` of a session opened with `resume` both carry the figure."""
    first = _open(client)["session_id"]
    issued = _turn(client, first)
    resumed = _open(client, resume=issued)
    assert resumed["turns"] == 0
    assert _categories(resumed) == {"In use": TOKENS, "Free space": WINDOW - TOKENS}
    got = client.get(f"/v1/sessions/{resumed['session_id']}").json()
    assert _categories(got) == _categories(resumed)


@pytest.mark.parametrize("variant", ["compacted", "absent", "unknown-model", "substituted"])
def test_each_null_case_reaches_the_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    monkeypatch.setenv("FAKE_PI_CONTEXT", variant)
    sid = _open(client)["session_id"]
    _turn(client, sid)
    assert client.get(f"/v1/sessions/{sid}").json()["context_usage"] is None


# --- against the real agent -------------------------------------------------

_BIN = Path(__file__).parent.parent / "spike" / "node_modules" / ".bin" / (
    "pi.cmd" if sys.platform == "win32" else "pi")


@pytest.mark.live
def test_live_a_resumed_session_reports_the_window_through_the_routes(
    tmp_path: Path,
) -> None:
    """The whole path against the real agent: one turn, then a session opened
    with `resume` reports `In use` equal to that turn's last `totalTokens`
    (PI-65). **Spends money**: one one-word turn on `gemini-3.1-flash-lite`,
    well under a cent. Needs `GEMINI_API_KEY`; `AGENT_SERVICE_PI_BINARY`
    overrides the binary (default the spike's install; `pi` in the image).
    """
    import os

    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not set")
    binary = Path(os.environ.get("AGENT_SERVICE_PI_BINARY", str(_BIN)))
    settings = Settings(
        workspace_dir=tmp_path / "workspace", agent_dir_root=tmp_path / "agent-dirs",
        session_store=tmp_path / "sessions", pi_binary=binary,
    )
    with TestClient(create_app(settings)) as client:
        sid = _open(client, model="google/gemini-3.1-flash-lite")["session_id"]
        turn = client.post(f"/v1/sessions/{sid}/messages",
                           json={"prompt": "Reply with the single word ok."})
        assert turn.status_code == 200, turn.text
        issued = turn.json()["sdk_session_id"]
        last = turn.json()["usage"]
        after_turn = _categories(client.get(f"/v1/sessions/{sid}").json())
        files = sorted((tmp_path / "sessions" / sid).glob("*.jsonl"))
        before = [f.read_bytes() for f in files]
        resumed = _open(client, resume=issued)
        print(f"\nturn usage={last}\nafter turn={after_turn}\n"
              f"resumed 201={_categories(resumed)}")
        assert after_turn is not None
        assert after_turn["In use"] == last["totalTokens"]
        assert after_turn["In use"] + after_turn["Free space"] == 1048576
        assert _categories(resumed) == after_turn
        # The reads wrote nothing into the conversation they read.
        assert [f.read_bytes() for f in files] == before
