from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from agent_service.config import Settings
from agent_service.errors import RunTimeout
from agent_service.runner import Run, create_run
from agent_spec.openapi.schemas import QueryRequest


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_dir=tmp_path / "ws")


def _messages() -> list[object]:
    return [
        SystemMessage(subtype="init", data={"session_id": "sess-42"}),
        AssistantMessage(content=[TextBlock(text="reading")], model="claude-sonnet-5"),
        AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Read", input={"file_path": "a.txt"})],
            model="claude-sonnet-5",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=90,
            is_error=False,
            num_turns=2,
            session_id="sess-42",
            stop_reason="end_turn",
            total_cost_usd=0.09,
            result="done",
            terminal_reason="completed",
        ),
    ]


def _fake_query(messages: list[object]):
    async def fake(*, prompt, options, **kwargs):  # noqa: ANN001, ARG001
        for m in messages:
            yield m

    return fake


# --- Finding 5 (Task 11 follow-up, review round 1) -----------------------
#
# Every _fake_query above accepts `prompt` and never inspects it, so nothing
# in this suite would catch a revert of the e7e494d streaming-envelope fix.
# Nor would the SDK's own ValueError guard: can_use_tool is no longer set by
# default (permission_enforcement defaults to "none"), so a reverted runner.py
# would not raise at all in most configurations -- only a paid live run would
# ever reveal it, which is exactly the class of regression a unit test should
# catch cheaply instead.


async def test_prompt_is_sent_as_an_async_iterable_not_a_plain_string(
    settings: Settings, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    async def fake(*, prompt, options, **kwargs):  # noqa: ANN001, ARG001
        captured["prompt"] = prompt
        for m in _messages():
            yield m

    monkeypatch.setattr("agent_service.runner.query", fake)
    run = create_run(QueryRequest(prompt="the verbatim prompt text"), settings)
    [e async for e in run.events()]

    prompt_arg = captured["prompt"]
    assert not isinstance(prompt_arg, str)
    assert isinstance(prompt_arg, AsyncIterator)

    # runner.py's fake `query` above never iterated it, so it is still fully
    # unconsumed here -- draining it now is the only way to inspect the shape
    # actually sent.
    envelopes = [item async for item in prompt_arg]
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["type"] == "user"
    assert envelope["message"] == {"role": "user", "content": "the verbatim prompt text"}


async def test_events_are_sequential_and_typed(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go"), settings)
    events = [e async for e in run.events()]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert [e["type"] for e in events] == ["system", "assistant", "assistant", "result"]


async def test_session_id_is_captured_from_the_init_message(
    settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.session_id == "sess-42"


# --- an unpriced turn is null, never 0.0 -------------------------------------


def test_a_successful_turn_the_sdk_attributed_nothing_to_reports_null_cost() -> None:
    """Measured (probe_gateway_cost C2): a turn that completed normally --
    `subtype: success`, a real answer -- came back with `total_cost_usd: 0`,
    every `usage` token count zero and `model_usage` empty. That turn ran; the
    numbers are missing, not zero, so `0.0` ("free") is the one answer that is
    certainly wrong."""
    from agent_service.runner import build_outcome

    outcome = build_outcome(
        {
            "subtype": "success",
            "is_error": False,
            "total_cost_usd": 0,
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
            },
            "model_usage": {},
            "result": "OK",
        },
        "sess-1",
    )
    assert outcome.total_cost_usd is None
    # The empty shape is still reported -- it is the evidence for anyone
    # diagnosing why the price is unknown.
    assert outcome.usage == {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }


def test_an_ordinary_turn_is_never_caught_by_the_unpriced_rule() -> None:
    """Every conjunct is required. A real turn keeps its price."""
    from agent_service.runner import build_outcome, unpriced_turn

    real = {
        "subtype": "success",
        "is_error": False,
        "total_cost_usd": 0.027395,
        "usage": {"input_tokens": 10, "output_tokens": 46},
        "model_usage": {"claude-haiku-4-5": {}},
    }
    assert unpriced_turn(real) is False
    assert build_outcome(real, "sess-1").total_cost_usd == 0.027395

    # A genuinely free turn the SDK priced at zero but DID account for keeps its
    # 0.0: real token counts mean the SDK attributed the work.
    priced_zero = {**real, "total_cost_usd": 0}
    assert unpriced_turn(priced_zero) is False

    # A turn that reported no usage structure at all is not this shape either --
    # that is "the SDK said nothing", which other rules already cover.
    assert unpriced_turn({**real, "total_cost_usd": 0, "usage": None}) is False

    # And a FAILED turn is the aborted shape, which `unattributed_abort` owns.
    assert unpriced_turn({**real, "total_cost_usd": 0, "is_error": True}) is False


async def test_outcome_is_populated_from_the_result_message(
    settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.outcome is not None
    assert run.outcome.result == "done"
    assert run.outcome.is_error is False
    assert run.outcome.total_cost_usd == 0.09
    assert run.outcome.terminal_reason == "completed"
    assert run.outcome.limit_hit is None


async def test_a_one_shot_run_prices_itself_from_the_cumulative_figure(
    settings: Settings, monkeypatch
) -> None:
    """The one-shot connection lasts exactly one run, so the SDK's cumulative
    figure IS this run's cost. The happy path, pinned alongside the guard below
    so a guard that swallowed every price would not go unnoticed."""
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.turn_cost_usd == 0.09


async def test_a_one_shot_run_that_aborted_at_zero_prices_nothing(
    settings: Settings, monkeypatch
) -> None:
    """`RunResponse.turn_cost_usd` documents ONE meaning for FOUR routes, and
    `/v1/query` reads this property rather than the session's `TurnResult`.
    Without this the description promised `null` for an aborted, unpriced run
    while the one-shot path still answered `0.0` -- the answer the whole fix
    declares certainly wrong -- on half the routes it governs.

    Not reachable by a caller today (`/v1/query` has no interrupt endpoint), so
    this pins the specification rather than a live path. Kills a revert of the
    `unattributed_abort` call in `Run.turn_cost_usd`.
    """
    messages = _messages()
    messages[-1] = ResultMessage(
        subtype="error_during_execution",
        duration_ms=100,
        duration_api_ms=90,
        is_error=True,
        num_turns=2,
        session_id="sess-42",
        total_cost_usd=0.0,
        result=None,
        terminal_reason="aborted_tools",
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query(messages))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]

    assert run.outcome.terminal_reason == "aborted_tools"
    # The SDK's own figure is passed through untouched; only the answer to
    # "what did this run cost" changes.
    assert run.outcome.total_cost_usd == 0.0
    assert run.turn_cost_usd is None


async def test_a_one_shot_run_that_aborted_with_a_price_still_reports_it(
    settings: Settings, monkeypatch
) -> None:
    """The `price == 0.0` conjunct on the one-shot path. An aborted run the SDK
    DID price is attributed, and throwing that away would be its own lie."""
    messages = _messages()
    messages[-1] = ResultMessage(
        subtype="error_during_execution",
        duration_ms=100,
        duration_api_ms=90,
        is_error=True,
        num_turns=2,
        session_id="sess-42",
        total_cost_usd=0.04,
        result=None,
        terminal_reason="aborted_streaming",
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query(messages))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]

    assert run.turn_cost_usd == 0.04


async def test_a_completed_one_shot_run_priced_at_zero_is_free_not_unknown(
    settings: Settings, monkeypatch
) -> None:
    """The `terminal_reason` conjunct on the one-shot path, and the mirror of
    `test_a_turn_the_sdk_priced_at_zero_is_free_not_unknown` in test_sessions.
    A run that COMPLETED and was priced at nothing genuinely cost nothing --
    0.0, not null. This is what stops the guard swallowing every zero."""
    messages = _messages()
    messages[-1] = ResultMessage(
        subtype="success",
        duration_ms=100,
        duration_api_ms=90,
        is_error=False,
        num_turns=2,
        session_id="sess-42",
        total_cost_usd=0.0,
        result="done",
        terminal_reason="completed",
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query(messages))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]

    assert run.turn_cost_usd is not None
    assert run.turn_cost_usd == 0.0


# Marker strings below are real, observed values, not guesses: captured via
# spike/probe_limits.py against claude-agent-sdk==0.2.128 on 2026-07-26
# (CP-065 has the transcript). Each test below
# sets exactly ONE of {subtype, terminal_reason} to a limit-marking value and
# leaves the other at a non-limit value, so a pass proves that field alone
# drives detection -- unlike the original combined test, which set both
# fields at once and could not tell which one `_detect_limit` actually used.


async def test_limit_hit_turns_detected_via_subtype(settings: Settings, monkeypatch) -> None:
    capped = ResultMessage(
        subtype="error_max_turns",  # real value observed for max_turns=1
        duration_ms=10,
        duration_api_ms=5,
        is_error=True,
        num_turns=2,
        session_id="s",
        # terminal_reason intentionally omitted (defaults to None) to isolate subtype
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query([capped]))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.outcome.limit_hit == "turns"


async def test_limit_hit_turns_detected_via_terminal_reason(
    settings: Settings, monkeypatch
) -> None:
    capped = ResultMessage(
        subtype="success",  # not a limit marker on its own
        duration_ms=10,
        duration_api_ms=5,
        is_error=True,
        num_turns=2,
        session_id="s",
        terminal_reason="max_turns",  # real value, corroborated by the SDK's own docstring
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query([capped]))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.outcome.limit_hit == "turns"


async def test_limit_hit_budget_detected_via_subtype(settings: Settings, monkeypatch) -> None:
    capped = ResultMessage(
        subtype="error_max_budget_usd",  # real value observed for max_budget_usd=0.01
        duration_ms=10,
        duration_api_ms=5,
        is_error=True,
        num_turns=1,
        session_id="s",
        # terminal_reason intentionally omitted to isolate subtype
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query([capped]))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.outcome.limit_hit == "budget"


async def test_limit_hit_budget_detected_via_terminal_reason(
    settings: Settings, monkeypatch
) -> None:
    capped = ResultMessage(
        subtype="success",  # not a limit marker on its own
        duration_ms=10,
        duration_api_ms=5,
        is_error=True,
        num_turns=1,
        session_id="s",
        terminal_reason="budget_exhausted",  # real value observed for max_budget_usd=0.01
    )
    monkeypatch.setattr("agent_service.runner.query", _fake_query([capped]))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    assert run.outcome.limit_hit == "budget"


async def test_timeout_raises_run_timeout(settings: Settings, monkeypatch) -> None:
    import asyncio

    async def slow(*, prompt, options, **kwargs):  # noqa: ANN001, ARG001
        await asyncio.sleep(5)
        yield None

    monkeypatch.setattr("agent_service.runner.query", slow)
    req = QueryRequest(prompt="go", options={"timeout_s": 1})
    run = create_run(req, settings)
    with pytest.raises(RunTimeout):
        [e async for e in run.events()]


async def test_raw_is_included_when_configured(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go", options={"include_raw": True}), settings)
    events = [e async for e in run.events()]
    assert "raw" in events[0]


async def test_raw_is_omitted_when_disabled(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go", options={"include_raw": False}), settings)
    events = [e async for e in run.events()]
    assert "raw" not in events[0]


async def test_underlying_query_stream_is_closed_when_events_is_abandoned(
    settings: Settings, monkeypatch
) -> None:
    """Proves runner.py's own aclosing(query(...)) unwinds when events() is
    explicitly aclose()'d -- NOT that this happens automatically in production.

    This test calls `gen.aclose()` itself, which throws GeneratorExit into
    `events()` directly. That is a real, supported way `events()` can be torn
    down (e.g. a caller that already holds the generator and knows to close
    it), and it proves `runner.py`'s own `aclosing(query(...))` correctly
    reacts to being closed. It does NOT reproduce a real CancelledError from
    task cancellation / client disconnect in production -- Starlette's
    StreamingResponse never calls aclose() on its body iterator on that path
    (see api.py's `run_query_stream` and its `test_api_stream.py` coverage),
    so that case is exercised elsewhere, not by this test.
    """
    closed: list[bool] = []

    async def fake_query(*, prompt, options, **kwargs):  # noqa: ANN001, ARG001
        try:
            yield SystemMessage(subtype="init", data={"session_id": "sess-1"})
            yield AssistantMessage(
                content=[TextBlock(text="still working")], model="claude-sonnet-5"
            )
        finally:
            closed.append(True)

    monkeypatch.setattr("agent_service.runner.query", fake_query)
    run = create_run(QueryRequest(prompt="go"), settings)
    gen = run.events()
    await gen.__anext__()  # consume exactly one event, then abandon
    await gen.aclose()  # mimics the consumer disappearing mid-run
    assert closed == [True]


async def test_outcome_stays_none_when_stream_ends_without_a_result_message(
    settings: Settings, monkeypatch
) -> None:
    """CLI crash / early exit / disconnect before a ResultMessage arrives.

    The stream simply ends -- no exception, no ResultMessage. Iteration must
    complete normally (no raise) and `outcome` must stay None so callers can
    distinguish "never finished" from both a normal and a limit-hit finish.
    """
    only_system_and_text = [
        SystemMessage(subtype="init", data={"session_id": "sess-99"}),
        AssistantMessage(content=[TextBlock(text="partial...")], model="claude-sonnet-5"),
    ]
    monkeypatch.setattr("agent_service.runner.query", _fake_query(only_system_and_text))
    run = create_run(QueryRequest(prompt="go"), settings)
    events = [e async for e in run.events()]
    assert [e["type"] for e in events] == ["system", "assistant"]
    assert run.outcome is None
    assert run.session_id == "sess-99"


async def test_events_raises_if_iterated_a_second_time(
    settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr("agent_service.runner.query", _fake_query(_messages()))
    run = create_run(QueryRequest(prompt="go"), settings)
    [e async for e in run.events()]
    with pytest.raises(RuntimeError):
        [e async for e in run.events()]
