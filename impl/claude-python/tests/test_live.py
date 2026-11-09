"""Deselected by default (`addopts = -m 'not live'`).

Run explicitly:  uv run pytest -m live -v
Costs up to roughly $0.09 for the one-shot run plus $0.035 for the two-turn
session test, at the claude-sonnet-5 default. Both are measured, not
estimated: the session test was $0.0347 on its last run. An earlier "~$0.20"
here overstated it by 6x -- if you are reading these numbers to decide
whether to run the suite, they should not scare you off a 3-cent test.
"""

from pathlib import Path

import pytest

from agent_service.config import Settings, credentials_configured
from agent_service.runner import create_run
from agent_spec.openapi.schemas import QueryRequest

pytestmark = pytest.mark.live


def _tool_uses(events: list[dict]) -> list[str]:
    """Names of every tool the agent invoked across these normalized events.

    Returns names rather than a bool so a failure says WHICH tool ran. Reads
    the normalized `content` blocks (serialization.py), not `raw`, so it works
    with `include_raw=False`.
    """
    return [
        block.get("name", "?")
        for event in events
        for block in (event.get("content") or [])
        if block.get("type") == "tool_use"
    ]


@pytest.mark.skipif(not credentials_configured(), reason="no Anthropic credentials configured")
async def test_real_run_completes_and_reports_cost(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("the magic word is BANANA\n", encoding="utf-8")

    settings = Settings(workspace_dir=workspace)
    request = QueryRequest(
        prompt="Read hello.txt and reply with only the magic word.",
        options={"allowed_tools": ["Read"], "max_turns": 5, "include_raw": False},
    )

    run = create_run(request, settings)
    events = [event async for event in run.events()]

    assert run.session_id, "the init SystemMessage should carry a session_id"
    assert run.outcome is not None
    assert run.outcome.is_error is False
    assert "BANANA" in (run.outcome.result or "")
    assert run.outcome.total_cost_usd and run.outcome.total_cost_usd > 0
    assert run.outcome.model_usage, "model_usage should always be populated"

    types = {event["type"] for event in events}
    assert {"system", "assistant", "result"} <= types
    assert any(
        block.get("type") == "tool_use"
        for event in events
        for block in (event.get("content") or [])
    ), "the agent should have called the Read tool"


@pytest.mark.skipif(not credentials_configured(), reason="no Anthropic credentials")
async def test_real_session_retains_context_across_turns(tmp_path: Path) -> None:
    """Costs roughly $0.035 — two turns at the claude-sonnet-5 floor.

    The canary for the whole point of Plan 2: that a session actually RETAINS
    context, rather than merely being able to answer the same question twice.

    Asserting only `"ORCHID" in result` for turn 2 does NOT test that, and
    that is what this test used to do. `Read` and `Glob` are both allowed and
    `fact.txt` is still sitting in the workspace, so an agent that had lost
    every scrap of context would simply read the file again and the assertion
    would pass -- the test would go green on precisely the regression it
    exists to catch. Turn 2's events were not even bound to a name.

    So the load-bearing assertion is the TOOL COUNT, not the answer: turn 2
    must produce no `tool_use` block at all, because the passphrase is already
    in the conversation history. Turn 1's assertion is the deliberate mirror
    of it -- it MUST use a tool, which is what proves the workspace and the
    tool grant are wired up and that turn 2's silence means "remembered"
    rather than "could not read anything either".
    """
    from agent_service.registry import SessionRegistry
    from agent_spec.openapi.schemas import RunOptions

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "fact.txt").write_text("the passphrase is ORCHID\n", encoding="utf-8")

    settings = Settings(workspace_dir=workspace)
    registry = SessionRegistry(settings)
    sid = await registry.create(
        RunOptions(allowed_tools=["Read", "Glob"], max_turns=4, include_raw=False), None
    )
    try:
        session = registry.get(sid)

        turn_one = [
            e
            async for e in session.send("Read fact.txt and reply with only the passphrase.")
        ]
        assert any(e["type"] == "result" for e in turn_one)
        assert "ORCHID" in (session.last_turn.outcome.result or "")
        # Turn 1 had to go and look. Without this, turn 2's zero-tool
        # assertion below would also pass on a session that could not use
        # tools at all.
        assert _tool_uses(turn_one), "turn 1 should have read the file"

        # The point of a session: turn 2 must NOT need to re-read the file.
        # `Read` and `Glob` are still granted and `fact.txt` is still there,
        # so re-reading is available and merely unnecessary -- which is what
        # makes zero tool calls evidence of retained context rather than of a
        # missing capability.
        turn_two = [
            e
            async for e in session.send("What was that passphrase? Reply with only the word.")
        ]
        assert "ORCHID" in (session.last_turn.outcome.result or "")
        assert not _tool_uses(turn_two), (
            "turn 2 must answer from conversation history, not by re-reading "
            f"fact.txt; it called {_tool_uses(turn_two)}"
        )
        assert session.turns == 2
        assert session.total_cost_usd > 0
        assert session.session_id
    finally:
        await registry.close_all()
