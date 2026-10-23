"""plan-03 Task 1: the recorder seam, with no database behind it.

The central assertion in every test here is the same one: **what reaches the
recorder is exactly what reaches the HTTP response**. If those two ever diverge,
a stored transcript silently stops being a record of what the caller saw, and
nothing else in the suite would notice.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from agent_service.config import Settings
from agent_service.errors import RunTimeout
from agent_spec.db.recorder import NULL_RECORDER, NullRecorder, RunRecorder
from agent_service.runner import Run, create_run
from agent_spec.openapi.schemas import QueryRequest, RunOptions
from agent_service.sessions import AgentSession
from tests.test_sessions import FakeClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_dir=tmp_path / "ws")


class RecordingRecorder:
    """Captures every call in order. Satisfies `RunRecorder` structurally."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []
        self.sessions_opened: list[dict[str, Any]] = []
        self.sessions_closed: list[dict[str, Any]] = []

    def session_opened(self, sid, *, title, model, permission_mode, at) -> None:  # noqa: ANN001
        self.sessions_opened.append({"sid": sid, "title": title, "at": at})

    def session_closed(self, sid, *, status, at) -> None:  # noqa: ANN001
        self.sessions_closed.append({"sid": sid, "status": status, "at": at})

    def start_run(self, run_id, *, sid, session_id, prompt, at) -> None:  # noqa: ANN001
        self.starts.append(
            {"run_id": run_id, "sid": sid, "session_id": session_id, "prompt": prompt}
        )

    def append_event(self, run_id, event) -> None:  # noqa: ANN001
        self.events.append((run_id, event))

    def finish_run(  # noqa: ANN001, PLR0913
        self, run_id, *, sid, session_id, outcome, turn_cost_usd, interrupted, timed_out, at
    ) -> None:
        self.finishes.append(
            {
                "run_id": run_id,
                "sid": sid,
                "session_id": session_id,
                "outcome": outcome,
                "turn_cost_usd": turn_cost_usd,
                "interrupted": interrupted,
                "timed_out": timed_out,
            }
        )

    @property
    def recorded_events(self) -> list[dict[str, Any]]:
        return [event for _, event in self.events]


def _result(**kw: Any) -> ResultMessage:
    base: dict[str, Any] = dict(
        subtype="success",
        duration_ms=10,
        duration_api_ms=9,
        is_error=False,
        num_turns=1,
        session_id="sess-1",
        total_cost_usd=0.05,
    )
    base.update(kw)
    return ResultMessage(**base)


def _turn() -> list[object]:
    return [
        SystemMessage(subtype="init", data={"session_id": "sess-1"}),
        AssistantMessage(content=[TextBlock(text="hi")], model="claude-sonnet-5"),
        _result(),
    ]


# -- the protocol itself ------------------------------------------------------


def test_the_null_recorder_satisfies_the_protocol_and_is_shared() -> None:
    # `RunRecorder` is a plain Protocol, so this is a typing-level claim made
    # executable: every method must exist with the documented keywords.
    recorder: RunRecorder = NullRecorder()
    recorder.session_opened("s", title=None, model=None, permission_mode=None, at=0.0)
    recorder.session_closed("s", status="closed", at=0.0)
    recorder.start_run("r", sid=None, session_id=None, prompt="p", at=0.0)
    recorder.append_event("r", {"seq": 1})
    recorder.finish_run(
        "r",
        sid=None,
        session_id=None,
        outcome=None,
        turn_cost_usd=None,
        interrupted=False,
        timed_out=False,
        at=0.0,
    )
    assert isinstance(NULL_RECORDER, NullRecorder)


def test_a_run_has_an_identity_even_with_no_recorder(settings: Settings) -> None:
    # The id is minted by the caller precisely so it exists in the shipped
    # no-database configuration.
    run = create_run(QueryRequest(prompt="p"), settings)
    assert run.run_id
    assert run._recorder is NULL_RECORDER


# -- one-shot runs ------------------------------------------------------------


async def _drain(run: Run) -> list[dict[str, Any]]:
    return [event async for event in run.events()]


@pytest.mark.anyio
async def test_a_clean_run_records_exactly_what_it_yielded(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingRecorder()
    _patch_query(monkeypatch, _turn())
    run = create_run(QueryRequest(prompt="p"), settings, recorder)

    yielded = await _drain(run)

    assert recorder.recorded_events == yielded
    assert [e["type"] for e in yielded] == ["system", "assistant", "result"]
    assert len(recorder.starts) == 1
    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["outcome"] is not None
    assert recorder.finishes[0]["timed_out"] is False
    assert recorder.finishes[0]["run_id"] == run.run_id


@pytest.mark.anyio
async def test_a_run_abandoned_mid_stream_still_finishes_with_no_outcome(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingRecorder()
    _patch_query(monkeypatch, _turn())
    run = create_run(QueryRequest(prompt="p"), settings, recorder)

    # Take one frame and walk away, the way a disconnected SSE consumer does.
    gen = run.events()
    first = await anext(gen)
    await gen.aclose()

    assert recorder.recorded_events == [first]
    # The event was recorded BEFORE the yield, which is why the frame the
    # consumer actually received is not the one that goes missing.
    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["outcome"] is None
    assert recorder.finishes[0]["turn_cost_usd"] is None


@pytest.mark.anyio
async def test_a_timed_out_run_is_recorded_as_timed_out(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingRecorder()

    async def _slow(*_args: Any, **_kw: Any):  # noqa: ANN202
        yield SystemMessage(subtype="init", data={"session_id": "sess-1"})
        await asyncio.sleep(5)

    monkeypatch.setattr("agent_service.runner.query", _slow)
    req = QueryRequest(prompt="p", options={"timeout_s": 1})
    run = create_run(req, settings, recorder)

    with pytest.raises(RunTimeout):
        await _drain(run)

    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["timed_out"] is True
    assert recorder.finishes[0]["outcome"] is None


def _patch_query(monkeypatch: pytest.MonkeyPatch, messages: list[object]) -> None:
    async def _fake(*_args: Any, **_kw: Any):  # noqa: ANN202
        for message in messages:
            yield message

    monkeypatch.setattr("agent_service.runner.query", _fake)


# -- session turns ------------------------------------------------------------


def _session(settings: Settings, client: FakeClient, recorder: RunRecorder) -> AgentSession:
    return AgentSession(
        RunOptions(), settings, client_factory=lambda _o: client, recorder=recorder
    )


@pytest.mark.anyio
async def test_a_clean_turn_records_exactly_what_it_yielded(settings: Settings) -> None:
    recorder = RecordingRecorder()
    session = _session(settings, FakeClient([_turn()]), recorder)
    await session.open()

    yielded = [event async for event in session.send("p")]

    assert recorder.recorded_events == yielded
    assert len(recorder.starts) == 1
    assert len(recorder.finishes) == 1
    finish = recorder.finishes[0]
    assert finish["outcome"] is not None
    assert finish["interrupted"] is False
    assert finish["timed_out"] is False
    # Resolved by the time the turn ends, even though it was unknown at start.
    assert recorder.starts[0]["session_id"] is None
    assert finish["session_id"] == "sess-1"


@pytest.mark.anyio
async def test_two_turns_get_distinct_run_ids(settings: Settings) -> None:
    recorder = RecordingRecorder()
    session = _session(settings, FakeClient([_turn(), _turn()]), recorder)
    await session.open()

    async for _ in session.send("one"):
        pass
    async for _ in session.send("two"):
        pass

    ids = [start["run_id"] for start in recorder.starts]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert [f["run_id"] for f in recorder.finishes] == ids


@pytest.mark.anyio
async def test_a_turn_abandoned_mid_drain_finishes_with_no_outcome(
    settings: Settings,
) -> None:
    recorder = RecordingRecorder()
    session = _session(settings, FakeClient([_turn()]), recorder)
    await session.open()

    gen = session.send("p")
    first = await anext(gen)
    await gen.aclose()

    assert recorder.recorded_events == [first]
    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["outcome"] is None


@pytest.mark.anyio
async def test_a_turn_with_no_result_message_finishes_with_no_outcome(
    settings: Settings,
) -> None:
    # The drain ends of its own accord but never sees a ResultMessage. The
    # finally reads LOCALS, so this must not report the previous turn's result.
    recorder = RecordingRecorder()
    client = FakeClient([_turn(), [AssistantMessage(content=[TextBlock(text="x")], model="m")]])
    session = _session(settings, client, recorder)
    await session.open()

    async for _ in session.send("one"):
        pass
    async for _ in session.send("two"):
        pass

    assert recorder.finishes[0]["outcome"] is not None
    assert recorder.finishes[1]["outcome"] is None
    assert recorder.finishes[1]["turn_cost_usd"] is None


@pytest.mark.anyio
async def test_an_interrupted_turn_is_recorded_as_interrupted(settings: Settings) -> None:
    recorder = RecordingRecorder()
    client = FakeClient([_turn()])
    session = _session(settings, client, recorder)
    await session.open()

    gen = session.send("p")
    await anext(gen)
    await session.interrupt()
    with contextlib.suppress(Exception):
        await gen.aclose()

    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["interrupted"] is True


@pytest.mark.anyio
async def test_a_busy_session_records_nothing_for_the_rejected_turn(
    settings: Settings,
) -> None:
    # SessionBusy raises before the lock is won, so no run may be started for
    # it -- otherwise every collision would leave an orphan row.
    recorder = RecordingRecorder()
    session = _session(settings, FakeClient([_turn()]), recorder)
    await session.open()

    gen = session.send("first")
    await anext(gen)
    with pytest.raises(Exception):  # noqa: B017 - SessionBusy
        await anext(session.send("second"))
    await gen.aclose()

    assert len(recorder.starts) == 1
