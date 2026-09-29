"""One real turn against a real model. **THESE SPEND MONEY.**

Deselected by default — `addopts = "-m 'not live'"`. Run deliberately:

    uv run pytest -m live

**Kept deliberately small.** One short prompt, `read_only` so the agent cannot
write, and a turn limit implied by the prompt itself. Do not add `-m live` to a
run "to be thorough".

**What these exist to prove** is the one thing no free test could: that
`send()` works end to end. Everything up to a turn — starting the app-server,
creating a thread, mapping notifications, refusing a resume with no rollout —
is already covered for free in `test_sessions.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from agent_spec.openapi.schemas import RunOptions
from dotenv import load_dotenv

from agent_service.sessions import CodexSession

# Tests do not load `.env` on their own -- only the entrypoint does. Loading it
# here is what lets `uv run pytest -m live` work from a checkout. It does NOT
# weaken the guard: `live` is what keeps these out of the default run, and
# `.ci/ci.py` never passes `-m live`.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")),
        reason="no OpenAI credential configured",
    ),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_a_real_turn_streams_events_and_completes(tmp_path) -> None:  # noqa: ANN001
    """**The first turn this implementation has ever taken.**

    Asserts the shape the API layer depends on, not the model's words: events
    arrive, they are valid `AgentEvent`s, and the turn terminates with a
    status. What the agent *says* is not this service's business.
    """
    session = CodexSession(
        cwd=str(tmp_path / "ws"),
        codex_home=str(tmp_path / "codexhome"),
    )
    # read_only: the agent cannot write, so a misbehaving turn cannot touch
    # anything even inside a temp directory.
    await session.open(RunOptions(permission_mode="plan"))
    try:
        outcome = await session.send("Reply with exactly the word: ok", RunOptions())
    finally:
        await session.close()

    assert outcome.events, "a real turn produced no events at all"

    # Every event must satisfy the published model -- this is the one place the
    # mapper meets real payloads rather than constructed ones.
    from agent_spec.openapi.schemas import AgentEvent

    for event in outcome.events:
        AgentEvent.model_validate(event)

    # **`completed`, not merely "terminated".** This assertion was
    # `outcome.status is not None` until 2026-08-08, and it passed against a turn
    # that failed with `401 Missing bearer or basic authentication in header` --
    # `status == "failed"` is not None. A live test that cannot tell a working
    # turn from a broken one is worse than no live test: it costs money and
    # certifies nothing. The error is carried into the message because the whole
    # value of a live failure is what the far end said.
    assert outcome.status == "completed", (
        f"the turn did not succeed: status={outcome.status!r} error={outcome.error!r}"
    )
    assert outcome.error is None, f"the turn reported an error: {outcome.error!r}"

    # Measured expectation, not a hope: Codex reports tokens and no money.
    assert outcome.total_cost_usd is None


async def test_usage_is_reported_and_cost_is_not(tmp_path) -> None:  # noqa: ANN001
    """The measurement that made `SessionRecord.total_cost_usd` nullable in
    0.16.0, confirmed against a live turn rather than against the package.

    If this ever fails because `usage` is absent, the specification's `usage`
    field is unsatisfiable here too and that is worth knowing immediately.
    """
    session = CodexSession(
        cwd=str(tmp_path / "ws"),
        codex_home=str(tmp_path / "codexhome"),
    )
    await session.open(RunOptions(permission_mode="plan"))
    try:
        outcome = await session.send("Say: done", RunOptions())
    finally:
        await session.close()

    # Same correction as above: a failed turn reports no usage either, so
    # checking usage without checking success measures nothing.
    assert outcome.status == "completed", (
        f"the turn did not succeed: status={outcome.status!r} error={outcome.error!r}"
    )
    assert outcome.total_cost_usd is None, "Codex reported a cost; the 0.16.0 note is wrong"
    # `usage` may legitimately be None on a turn the SDK attributed nothing to;
    # what must not happen is a crash reading it.
    assert outcome.usage is None or isinstance(outcome.usage, dict)
