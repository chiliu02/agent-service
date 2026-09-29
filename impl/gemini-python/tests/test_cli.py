"""The runner, against a fake agent that reproduces what was measured.

**Free.** `fake_cli_agent.py` emits the shapes a real turn emits and exits with
the codes a real agent exits with, so the parsing, the exit-code mapping, the
two-stream envelope and the transcript capture are all testable for nothing.

**What it cannot test is whether those shapes are still true** -- that is what
the spike measured and what a `live` test re-checks on an upgrade. The fake is
faithful to a measurement, not a substitute for one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agent_service.cli import (
    CliError,
    CliRunner,
    CredentialMissing,
    ResumeTargetMissing,
    TrustRefused,
    TurnTimeout,
)

pytestmark = pytest.mark.anyio

FAKE = (sys.executable, str(Path(__file__).parent / "fake_cli_agent.py"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _runner(tmp_path: Path, **kwargs) -> CliRunner:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return CliRunner(binary=FAKE, workspace=workspace, home=tmp_path / "home", **kwargs)


async def test_a_turn_is_parsed_and_the_answer_reassembled(tmp_path: Path) -> None:
    """GP-15: `message` events carry `delta` and there is no terminal message.

    A reader that waits for a non-delta message waits forever, so the answer is
    reassembled from the chunks.
    """
    result = await _runner(tmp_path).run("say hello", timeout=30)
    assert result.exit_code == 0
    assert result.assistant_text == "hello world"
    assert result.sdk_session_id


async def test_two_models_are_billed_for_one_turn(tmp_path: Path) -> None:
    """GP-16: a router model is billed beside the one that answers.

    Reporting only the answering model under-reports the turn.
    """
    result = await _runner(tmp_path).run("say hello", timeout=30)
    assert set(result.models_used) == {"gemini-3.5-flash", "gemini-3.1-flash-lite"}


async def test_the_tool_loop_is_visible_and_its_output_is_not(tmp_path: Path) -> None:
    """GP-17 and GP-40: the call is observable, the result content is not.

    Pinned so that a future version which starts reporting output is noticed as
    a change rather than absorbed silently.
    """
    result = await _runner(tmp_path).run("tools please", timeout=30)
    uses = [e for e in result.events if e["type"] == "tool_use"]
    results = [e for e in result.events if e["type"] == "tool_result"]
    assert uses[0]["tool_name"] == "read_file"
    assert uses[0]["parameters"] == {"file_path": "seed.txt"}
    assert uses[0]["tool_id"] == results[0]["tool_id"], "the correlation key"
    assert results[0]["output"] == "", "a work tool reports no content"


async def test_the_transcript_lands_in_our_home_and_can_be_kept(tmp_path: Path) -> None:
    """GP-39: HOME is the override GP-13 said did not exist.

    And GP-10 is why it matters: the agent deletes its own transcript on the
    first resume, so the copy is the durability mechanism.
    """
    runner = _runner(tmp_path)
    result = await runner.run("say hello", timeout=30)
    assert result.transcript is not None, "no transcript was found under our HOME"
    assert (tmp_path / "home") in result.transcript.parents

    kept = CliRunner.keep(result.transcript, tmp_path / "store" / "session.jsonl")
    assert kept.read_bytes() == result.transcript.read_bytes()


async def test_a_resumed_turn_mints_a_new_id(tmp_path: Path) -> None:
    """GP-11: `--session-file` loads a transcript rather than adopting an identity.

    Which is why GP-34 refuses a caller-supplied id: there is no stable one to
    promise.
    """
    runner = _runner(tmp_path)
    first = await runner.run("say hello", timeout=30)
    assert first.transcript is not None
    resumed = await runner.run("again", timeout=30, session_file=first.transcript)
    assert resumed.sdk_session_id != first.sdk_session_id


async def test_the_two_session_flags_are_refused_together(tmp_path: Path) -> None:
    """GP-11: the agent calls them mutually exclusive and exits 1.

    Refused here rather than discovered at run time.
    """
    with pytest.raises(CliError, match="mutually exclusive"):
        await _runner(tmp_path).run(
            "x", timeout=30, session_file=tmp_path / "t.jsonl", sdk_session_id="abc"
        )


@pytest.mark.parametrize(
    ("code", "expected"),
    [(41, CredentialMissing), (42, ResumeTargetMissing), (55, TrustRefused), (44, CliError)],
)
async def test_exit_codes_become_their_own_errors(
    tmp_path: Path, code: int, expected: type[Exception]
) -> None:
    """GP-06. `42` is a 404 and not a 400, which is the one that matters."""
    with pytest.raises(expected) as caught:
        await _runner(tmp_path).run(f"exit:{code}", timeout=30)
    assert caught.value.exit_code == code
    assert "fake failure" in caught.value.detail


async def test_a_failure_with_no_envelope_is_still_reported(tmp_path: Path) -> None:
    """GP-09: `--sandbox` fails with PLAIN TEXT, not JSON, on stderr.

    A reader that assumes stderr parses as JSON crashes on exactly this.
    """
    with pytest.raises(CliError) as caught:
        await _runner(tmp_path).run("plain:44", timeout=30)
    assert "GEMINI_SANDBOX" in caught.value.detail


async def test_a_turn_that_never_ends_is_killed(tmp_path: Path) -> None:
    """GP-18 and GP-02: turns can fail to terminate and no cancel verb exists.

    The wall clock is the only exit, so it is enforced here rather than hoped
    for -- and the process must actually die.
    """
    with pytest.raises(TurnTimeout, match="did not finish"):
        await _runner(tmp_path).run("hang", timeout=1.5)


def test_the_agent_is_spawned_into_its_own_process_group_on_posix() -> None:
    """GP-45. **A grandchild holding a pipe is what kept a killed turn alive.**

    Measured, not reasoned: an interrupt at six seconds let the turn run on for
    7.7s, 69.5s and 30.5s on three consecutive runs, because `communicate()`
    waits for EOF and the pipes outlive the process that was killed. Asserted
    here so that removing the flag -- which changes nothing visible on a
    developer's machine -- fails on the platform the image actually runs on.
    """
    from agent_service.cli import _OWN_PROCESS_GROUP  # noqa: PLC0415

    expected = {"start_new_session": True} if os.name == "posix" else {}
    assert _OWN_PROCESS_GROUP == expected


def test_killing_a_dead_process_is_not_an_error() -> None:
    """A turn that finished between the decision to stop it and the request.

    That race is unavoidable and reported in the body as `interrupted: false`,
    so the kill path must never raise -- an exception here would turn a
    successful interrupt into a 500.
    """
    from agent_service.cli import kill_process_tree  # noqa: PLC0415

    class Gone:
        pid = 2 ** 31 - 1  # never a live pid

        def kill(self) -> None:
            raise ProcessLookupError

    kill_process_tree(Gone())  # must simply return


def test_the_system_prompt_file_reaches_the_agent_as_an_environment_variable(
    tmp_path: Path,
) -> None:
    """GP-66. There is no `--system-prompt` flag: the agent reads an env var.

    **The ABSOLUTE path, never the `1` switch form.** The switch resolves
    its project-default file against the working directory, which is the caller's
    mounted workspace -- a file the agent itself can write. A request that sent
    no system prompt would then silently acquire one.
    """
    prompt_file = tmp_path / "home" / "system.md"
    runner = _runner(tmp_path, system_prompt_file=prompt_file)

    env = runner.env()

    assert env["GEMINI_SYSTEM_MD"] == str(prompt_file)
    assert Path(env["GEMINI_SYSTEM_MD"]).is_absolute()
    assert "--system-prompt" not in runner.argv(
        "hi", session_file=None, sdk_session_id=None, approval_mode="default"
    )


def test_no_system_prompt_leaves_the_variable_unset(tmp_path: Path) -> None:
    """GP-66. Unset is the built-in prompt, and `0`/`false` would be the same.

    Setting it to a falsy string would be one more value to get wrong for no
    gain: absence is what the agent already treats as "use your own".
    """
    assert "GEMINI_SYSTEM_MD" not in _runner(tmp_path).env()
