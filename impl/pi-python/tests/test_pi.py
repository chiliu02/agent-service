"""The runner, against the double. **No credential, no network, no cost.**

Every assertion here is pinned to a shape read out of a real turn and recorded in this
build's references file; the double reproduces those shapes and this file
proves the runner reads them the way the references say it does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_service.pi import (
    CredentialMissing,
    PiError,
    PiRunner,
    ResumeTargetMissing,
    StreamingTurn,
    TurnTimeout,
    build_result,
    parse_stream,
)

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def runner(tmp_path: Path, **kwargs) -> PiRunner:
    return PiRunner(
        binary=FAKE,
        workspace=tmp_path,
        agent_dir=tmp_path / "agent",
        session_dir=tmp_path / "sessions",
        **kwargs,
    )


# --- the command line --------------------------------------------------------


def test_the_three_suppression_flags_are_always_passed(tmp_path: Path) -> None:
    """`PI-19`: nothing this build runs reads ambient configuration."""
    argv = runner(tmp_path).argv("hi", sdk_session_id=None, resume=None)
    assert "--no-skills" in argv
    assert "--no-extensions" in argv
    assert "--no-context-files" in argv


def test_stdin_is_never_inherited(tmp_path: Path) -> None:
    """`PI-12`: the flag that stops a hang indistinguishable from a stuck model.

    Asserted on the call rather than the argv, because it is a subprocess
    keyword and not a flag -- which is exactly why it is easy to drop.
    """
    import asyncio
    import inspect

    source = inspect.getsource(PiRunner.run)
    assert "stdin=asyncio.subprocess.DEVNULL" in source
    assert asyncio.subprocess.DEVNULL is not None


def test_a_qualified_model_is_passed_whole_and_suppresses_the_provider_flag(
    tmp_path: Path,
) -> None:
    """`PI-10`: `--model anthropic/x` is self-contained, measured against the agent."""
    argv = runner(tmp_path, provider="openai",
                  model="anthropic/claude-haiku-4-5").argv(
        "hi", sdk_session_id=None, resume=None)
    assert "--model" in argv and "anthropic/claude-haiku-4-5" in argv
    assert "--provider" not in argv


def test_a_bare_model_keeps_the_deployment_provider(tmp_path: Path) -> None:
    argv = runner(tmp_path, provider="openai", model="gpt-5-nano").argv(
        "hi", sdk_session_id=None, resume=None)
    assert argv[argv.index("--provider") + 1] == "openai"


def test_resume_and_a_supplied_id_are_mutually_exclusive(tmp_path: Path) -> None:
    """`PI-14`: refused here rather than discovered at run time."""
    with pytest.raises(PiError):
        runner(tmp_path).argv("hi", sdk_session_id="a", resume="b")


def test_no_tools_is_spelled_with_its_own_flag(tmp_path: Path) -> None:
    """An empty `--tools` is a parse error, so "allow nothing" needs the flag."""
    argv = runner(tmp_path, allowed_tools=()).argv("hi", sdk_session_id=None,
                                                   resume=None)
    assert "--no-tools" in argv
    assert "--tools" not in argv


def test_the_system_prompt_is_a_flag_not_a_file(tmp_path: Path) -> None:
    """`PI-20`: no file to write and no path resolved against the workspace."""
    argv = runner(tmp_path, system_prompt="be terse").argv(
        "hi", sdk_session_id=None, resume=None)
    assert argv[argv.index("--system-prompt") + 1] == "be terse"


# --- a turn ------------------------------------------------------------------


async def test_a_turn_reports_text_cost_and_the_session_id(tmp_path: Path) -> None:
    result = await runner(tmp_path).run("hello", timeout=30)
    assert result.assistant_text == "ok"
    assert result.sdk_session_id
    # `PI-17`: a real figure, in USD.
    assert result.total_cost_usd == pytest.approx(0.000758)


async def test_cost_is_SUMMED_across_the_model_calls_of_one_invocation(
    tmp_path: Path,
) -> None:
    """`PI-16`: one HTTP turn is several model calls, and the turn costs their sum."""
    result = await runner(tmp_path).run("twocalls please", timeout=30)
    assert len(result.turn_usages) == 2
    assert result.total_cost_usd == pytest.approx(0.000758 + 0.002210)
    # The second call reports FEWER input tokens than the first, which is what
    # proves these are per-call figures rather than a running total.
    assert result.turn_usages[1]["input"] < result.turn_usages[0]["input"]


async def test_a_supplied_id_is_echoed_back(tmp_path: Path) -> None:
    """`PI-14`, and the whole of what `allow_supplied_sdk_session_id` promises."""
    supplied = "01a07999-0000-7000-8000-000000000001"
    result = await runner(tmp_path).run("hi", timeout=30, sdk_session_id=supplied)
    assert result.sdk_session_id == supplied


async def test_a_resumed_turn_keeps_the_conversation_id(tmp_path: Path) -> None:
    """`PI-13`: the id is the conversation's, not the turn's."""
    first = await runner(tmp_path).run("hi", timeout=30)
    again = await runner(tmp_path).run("more", timeout=30,
                                       resume=first.sdk_session_id)
    assert again.sdk_session_id == first.sdk_session_id


async def test_the_session_file_stays_put(tmp_path: Path) -> None:
    """`PI-09`: nothing here rescues a transcript, because nothing destroys one."""
    await runner(tmp_path).run("hi", timeout=30)
    assert list((tmp_path / "sessions").glob("*.jsonl"))


async def test_tool_events_carry_a_result_with_real_text(tmp_path: Path) -> None:
    """`PI-36`, which is not true of the Gemini target."""
    result = await runner(tmp_path).run("use tools", timeout=30)
    end = next(e for e in result.events if e["type"] == "tool_execution_end")
    assert end["result"]["content"][0]["text"] == "Successfully wrote to hello.txt"
    assert end["isError"] is False


async def test_models_used_is_keyed_provider_slash_model(tmp_path: Path) -> None:
    """`PI-18`: assembled here, in the form `RunOptions.model` accepts."""
    result = await runner(tmp_path).run("twocalls", timeout=30)
    assert list(result.models_used) == ["anthropic/claude-haiku-4-5-20251001"]
    entry = result.models_used["anthropic/claude-haiku-4-5-20251001"]
    assert entry["cost_usd"] == pytest.approx(0.000758 + 0.002210)


# --- failure -----------------------------------------------------------------


async def test_a_missing_credential_is_classified_from_the_MESSAGE(
    tmp_path: Path,
) -> None:
    """`PI-15`: the exit code is 1 for everything, so the text is the signal."""
    with pytest.raises(CredentialMissing):
        await runner(tmp_path).run("nokey", timeout=30)


async def test_an_unknown_resume_target_is_its_own_error(tmp_path: Path) -> None:
    """`PI-15`, and it is what makes the route answer 404 rather than 502."""
    with pytest.raises(ResumeTargetMissing):
        await runner(tmp_path).run("nosession", timeout=30)


async def test_an_unrecognised_failure_stays_generic(tmp_path: Path) -> None:
    """Not forced into a category it does not belong to."""
    with pytest.raises(PiError) as raised:
        await runner(tmp_path).run("fail: something else entirely", timeout=30)
    assert not isinstance(raised.value, (CredentialMissing, ResumeTargetMissing))


async def test_a_turn_that_will_not_end_is_killed(tmp_path: Path) -> None:
    with pytest.raises(TurnTimeout):
        await runner(tmp_path).run("hang", timeout=1)


# --- streaming ---------------------------------------------------------------


async def test_streaming_yields_events_and_then_a_result(tmp_path: Path) -> None:
    stream = StreamingTurn(runner(tmp_path), "hello", timeout=30)
    seen = [event async for event in stream.__aiter__()]
    assert seen[0]["type"] == "session"
    assert stream.failure is None
    assert stream.result is not None
    assert stream.result.assistant_text == "ok"


async def test_a_streaming_failure_arrives_in_band(tmp_path: Path) -> None:
    """A stream has committed its response by the time the process exits."""
    stream = StreamingTurn(runner(tmp_path), "nokey", timeout=30)
    [event async for event in stream.__aiter__()]
    assert stream.result is None
    assert isinstance(stream.failure, CredentialMissing)


# --- parsing -----------------------------------------------------------------


def test_unparseable_lines_are_skipped_not_fatal() -> None:
    events = parse_stream('{"type":"a"}\nnot json\n\n{"type":"b"}\n')
    assert [e["type"] for e in events] == ["a", "b"]


def test_a_result_with_no_usage_prices_at_none_not_zero() -> None:
    """`PI-17`: `0.0` would read as free, which is a different claim."""
    result = build_result(0, [{"type": "session", "id": "x"}])
    assert result.total_cost_usd is None
