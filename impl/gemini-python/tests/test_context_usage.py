"""`context_usage`, read from the last model call the kept transcript records (GP-80).

**Free: the fake agent, no key, no model.** What is pinned here is where the
figure comes from and when it is `null`. Whether `input + output` predicts the
next prompt is GP-80's measurement against the real CLI, and is not repeated
per test.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import context_usage

FAKE = (sys.executable, str(Path(__file__).parent / "fake_cli_agent.py"))
WINDOW = 1_048_576


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


def _gemini(tokens: dict, model: str = "gemini-3.5-flash-lite") -> dict:
    return {"id": "x", "type": "gemini", "content": "", "tokens": tokens, "model": model}


def _write(path: Path, *entries: dict | str) -> Path:
    path.write_text(
        "".join((e if isinstance(e, str) else json.dumps(e)) + "\n" for e in entries),
        encoding="utf-8",
    )
    return path


def _categories(usage) -> dict[str, int]:
    """By name, from a `ContextUsage` or from its JSON."""
    categories = usage["categories"] if isinstance(usage, dict) else usage.categories
    return {c["name"]: c["tokens"] for c in categories}


def test_in_use_is_the_last_calls_input_plus_output(tmp_path: Path) -> None:
    """Not `total`, which adds `thoughts` and overstates the next prompt."""
    path = _write(
        tmp_path / "t.jsonl",
        {"sessionId": "s", "kind": "main"},
        _gemini({"input": 100, "output": 5, "thoughts": 50, "total": 155}),
        {"type": "user", "content": "again"},
        _gemini({"input": 31954, "output": 1, "thoughts": 40, "total": 31995}),
    )
    assert _categories(context_usage(path)) == {
        "In use": 31955, "Free space": WINDOW - 31955,
    }


def test_the_window_follows_the_model_that_ran(tmp_path: Path) -> None:
    """The CLI's `tokenLimit()`: one figure, except the two Gemma 4 ids."""
    gemma = _write(tmp_path / "g.jsonl",
                   _gemini({"input": 1000, "output": 0}, model="gemma-4-31b-it"))
    assert _categories(context_usage(gemma))["Free space"] == 256_000 - 1000


@pytest.mark.parametrize("entries", [
    (),
    ({"sessionId": "s", "kind": "main"}, {"type": "user", "content": "hi"}),
    ("not json at all",),
])
def test_null_when_no_model_call_is_recorded(tmp_path: Path, entries) -> None:
    assert context_usage(_write(tmp_path / "t.jsonl", *entries)) is None


def test_null_with_no_transcript(tmp_path: Path) -> None:
    assert context_usage(tmp_path / "absent.jsonl") is None


def test_a_line_that_does_not_parse_is_skipped(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl",
                  _gemini({"input": 10, "output": 2}), "{truncated")
    assert _categories(context_usage(path))["In use"] == 12


def test_a_new_session_is_null_until_its_first_turn(client: TestClient) -> None:
    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    assert client.get(f"/v1/sessions/{sid}").json()["context_usage"] is None

    assert client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"}).status_code == 200
    usage = client.get(f"/v1/sessions/{sid}").json()["context_usage"]
    assert usage == {"categories": [
        {"name": "In use", "tokens": 8686},
        {"name": "Free space", "tokens": WINDOW - 8686},
    ]}


def test_a_resumed_session_has_it_before_its_first_turn(client: TestClient) -> None:
    """The transcript is copied in at create (GP-70), so the `201` carries it."""
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    issued = client.post(
        f"/v1/sessions/{first}/messages", json={"prompt": "hi"}
    ).json()["sdk_session_id"]

    resumed = client.post("/v1/sessions", json={"options": {"resume": issued}})
    assert resumed.status_code == 201
    assert _categories(resumed.json()["context_usage"]) == {
        "In use": 8686, "Free space": WINDOW - 8686,
    }


def test_a_changed_transcript_is_read_again(client: TestClient) -> None:
    """The cache is keyed on the file, so a new turn is never served stale."""
    from agent_service.registry import Registry  # noqa: PLC0415

    sid = client.post("/v1/sessions", json={}).json()["session_id"]
    client.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
    registry: Registry = client.app.state.registry  # type: ignore[attr-defined]
    session = registry.get(sid)
    assert _categories(session.context_usage())["In use"] == 8686

    _write(session.transcript, _gemini({"input": 20000, "output": 4}))
    stat = session.transcript.stat()
    os.utime(session.transcript, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert _categories(session.context_usage())["In use"] == 20004
