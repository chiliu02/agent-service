"""A failed turn names its cause, on the wire and in the record.

Reported by the owner on 2026-11-18 against 0.33.0: an LLM endpoint missing
`/v1` failed every turn with a 404 whose message was longer than the
`VARCHAR(64)` the `runs` row held it in. The row's `UPDATE` failed and the run
kept no outcome. The column is `TEXT` since schema revision `e7a4c2b19f06`, and
the shared package's Postgres suite pins that.

**What this file pins is this build's half**: the upstream message reaches the
caller's `RunResponse` as `terminal_reason`, verbatim, and the very same string
is what the recorder is handed. The two must agree, because the tables store
what `/v1` returns.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import SessionRegistry
from agent_service.sessions import TurnOutcome

MESSAGE = (
    "unexpected status 404 Not Found: Unknown error, url: "
    "https://gateway.example/llm/0123456789abcdef/responses, "
    "cf-ray: a5c4d858aa2114bb-SYD"
)


class _FailingSession:
    """A session whose every turn ends `failed` with the reported message."""

    sdk_session_id = "11111111-2222-3333-4444-555555555555"

    async def open(self, options, resume=None) -> None:  # noqa: ANN001, ARG002
        return None

    async def send(self, prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG002
        return TurnOutcome(status="failed", error=MESSAGE, duration_ms=10_000)

    async def interrupt(self) -> bool:
        return False

    def context(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _Recorder:
    """Keeps the outcome each finished run was recorded with."""

    def __init__(self) -> None:
        self.outcomes: list = []

    def start_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        return None

    def append_event(self, run_id, event) -> None:  # noqa: ANN001, ARG002
        return None

    def finish_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        self.outcomes.append(kwargs.get("outcome"))

    def session_opened(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None

    def session_closed(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None


def _app(tmp_path):  # noqa: ANN001, ANN202
    settings = Settings(
        require_credentials=False,
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=tmp_path / "home",
    )
    recorder = _Recorder()
    registry = SessionRegistry(
        settings, session_factory=lambda options, subdir: _FailingSession(), recorder=recorder
    )
    return create_app(settings, registry), recorder


def test_the_message_is_longer_than_the_old_column() -> None:
    assert len(MESSAGE) > 64


def test_a_failed_turn_gives_the_caller_the_upstream_message(tmp_path) -> None:  # noqa: ANN001
    app, recorder = _app(tmp_path)
    with TestClient(app) as c:
        sid = c.post("/v1/sessions", json={}).json()["session_id"]
        r = c.post(f"/v1/sessions/{sid}/messages", json={"prompt": "hi"})
        record = c.get(f"/v1/sessions/{sid}").json()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_error"] is True
    assert body["subtype"] == "failed"
    assert body["terminal_reason"] == MESSAGE
    # The session's record reads the same outcome and must say the same.
    assert record["last_turn"]["terminal_reason"] == MESSAGE

    [outcome] = recorder.outcomes
    assert outcome is not None, "a failed turn that reached an end is an outcome"
    assert outcome.is_error is True
    assert outcome.terminal_reason == MESSAGE
