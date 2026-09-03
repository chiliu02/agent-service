"""plan-03 Task 9: persistence under a real agent. COSTS MONEY.

Deselected by default with the rest of the live suite. Needs credentials, plus a
database from `tests/dbharness.py` -- `AGENT_SERVICE_TEST_DATABASE_URL` if set,
else a testcontainer.

The Postgres-outage test needs more than a URL: it stops and restarts the server
mid-turn, so it needs the container's NAME. It gets that from the harness when
the harness started the container, or from
`AGENT_SERVICE_TEST_PG_CONTAINER` when an external URL was supplied. With an
external URL and no name it skips on its own, rather than guessing a name and
stopping something that was never offered up for it.

Measurements from these runs are recorded in CP-092.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_service.config import Settings, credentials_configured
from agent_spec.openapi.schemas import RunOptions
from agent_spec.db import testing as dbharness

pytestmark = [pytest.mark.live, pytest.mark.postgres]

needs = pytest.mark.skipif(not credentials_configured(), reason="needs credentials")


async def _reset_db(url: str) -> None:
    from agent_spec.db import Base, create_engine

    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


def _settings(workspace: Path, config_dir: Path, url: str) -> Settings:
    # CLAUDE_CONFIG_DIR is set per test so the resume case can DELETE the CLI's
    # own on-disk transcript and prove materialization came from the store
    # rather than from a file that happened to still be there.
    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return Settings(
        workspace_dir=workspace,
        database_url=url,
        # Small caps: this is about persistence, not agent capability, and every
        # turn is real money.
        default_max_turns=3,
        default_request_timeout_s=120,
    )


def _text(events: list[dict]) -> str:
    return " ".join(
        block.get("text", "")
        for event in events
        for block in (event.get("content") or [])
        if block.get("type") == "text"
    )


@needs
async def test_a_real_session_reconstructs_from_stored_rows(
    tmp_path: Path, postgres_url: str
) -> None:
    """Three real turns, one interrupted. The stored rows must tell the truth."""
    from sqlalchemy import text as sql

    from agent_spec.db import create_engine
    from agent_spec.db.wiring import Persistence
    from agent_service.registry import SessionRegistry

    await _reset_db(postgres_url)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = _settings(workspace, tmp_path / "cfg", postgres_url)

    persistence = Persistence(postgres_url)
    persistence.start()
    registry = SessionRegistry(
        settings, recorder=persistence.recorder, session_store=persistence.session_store
    )

    sid = await registry.create(RunOptions(), title="live")
    session = registry.get(sid)

    for prompt in ("Reply with exactly: ONE", "Reply with exactly: TWO"):
        async for _ in session.send(prompt):
            pass

    # Turn 3: start it, then interrupt mid-flight.
    generator = session.send("Count slowly from 1 to 40, one number per line.")
    await anext(generator)
    await asyncio.sleep(2.0)
    await session.interrupt()
    try:
        async for _ in generator:
            pass
    except BaseException:  # noqa: BLE001 - an interrupted drain ends however it ends
        pass

    sdk_session_id = session.session_id
    await registry.close(sid)
    await persistence.aclose()

    engine = create_engine(postgres_url)
    async with engine.connect() as conn:
        runs = (
            await conn.execute(
                sql(
                    "SELECT id, interrupted, outcome_missing, result_text, cost_usd, "
                    "num_turns FROM runs ORDER BY started_at"
                )
            )
        ).all()
        events = await conn.scalar(sql("SELECT count(*) FROM events"))
        sess = (
            await conn.execute(
                sql("SELECT total_turns, total_cost_usd, status, sdk_session_id FROM sessions")
            )
        ).one()
        mirrored = await conn.scalar(sql("SELECT count(*) FROM transcript_entries"))
    await engine.dispose()

    print(f"\n[T9-A] runs={len(runs)} events={events} mirrored_entries={mirrored}")
    for row in runs:
        print(
            f"[T9-A]   interrupted={row.interrupted} outcome_missing={row.outcome_missing} "
            f"cost_usd={row.cost_usd} num_turns={row.num_turns} "
            f"result={(row.result_text or '')[:30]!r}"
        )
    print(
        f"[T9-A] session total_turns={sess.total_turns} "
        f"total_cost_usd={sess.total_cost_usd} status={sess.status}"
    )

    assert len(runs) == 3, "one row per turn, including the interrupted one"
    assert sess.sdk_session_id == sdk_session_id
    # The interrupted turn must NOT read as a clean success.
    assert runs[2].interrupted is True or runs[2].outcome_missing is True
    assert events > 0
    assert mirrored > 0, "the A.2 mirror produced nothing"
    assert sess.total_turns <= 3, "total_turns counts turns that reached a result"


@needs
async def test_resume_after_a_restart_with_the_local_transcript_deleted(
    tmp_path: Path, postgres_url: str
) -> None:
    """The whole point of A.2: continuity when the local file is gone.

    Deleting `CLAUDE_CONFIG_DIR` between the two halves is what makes this a
    test of the STORE. Left in place, the CLI would resume from its own on-disk
    transcript and the store would prove nothing.
    """
    from agent_spec.db.wiring import Persistence
    from agent_service.registry import SessionRegistry

    await _reset_db(postgres_url)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_dir = tmp_path / "cfg"
    settings = _settings(workspace, config_dir, postgres_url)

    persistence = Persistence(postgres_url)
    persistence.start()
    registry = SessionRegistry(
        settings, recorder=persistence.recorder, session_store=persistence.session_store
    )
    sid = await registry.create(RunOptions(), title="live-resume")
    session = registry.get(sid)
    async for _ in session.send("Remember this number: 8675309. Reply with exactly: OK"):
        pass
    sdk_session_id = session.session_id
    await registry.close(sid)
    await persistence.aclose()

    local_files = sum(1 for _ in config_dir.rglob("*")) if config_dir.exists() else 0
    shutil.rmtree(config_dir, ignore_errors=True)
    print(
        f"\n[T9-B] removed local transcript dir ({local_files} paths); "
        f"resuming {sdk_session_id}"
    )

    persistence2 = Persistence(postgres_url)
    persistence2.start()
    registry2 = SessionRegistry(
        settings, recorder=persistence2.recorder, session_store=persistence2.session_store
    )
    sid2 = await registry2.create(RunOptions(resume=sdk_session_id), title="resumed")
    session2 = registry2.get(sid2)
    events = [
        event
        async for event in session2.send(
            "What number did I ask you to remember? Digits only."
        )
    ]
    await registry2.close(sid2)
    await persistence2.aclose()

    reply = _text(events)
    print(f"[T9-B] resumed reply: {reply[:120]!r}")
    assert "8675309" in reply, "the agent did not retain context across the restart"


@needs
async def test_killing_postgres_mid_turn_does_not_fail_the_turn(
    tmp_path: Path, postgres_server: dbharness.Postgres
) -> None:
    """The turn must survive the database, not the other way round."""
    from agent_spec.db.wiring import Persistence
    from agent_service.registry import SessionRegistry

    container = postgres_server.container
    if container is None:
        pytest.skip(
            f"the server behind ${dbharness.ENV_URL} is not named; set "
            f"${dbharness.ENV_CONTAINER} to the container this test may stop"
        )
    postgres_url = postgres_server.url

    await _reset_db(postgres_url)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = _settings(workspace, tmp_path / "cfg", postgres_url)

    persistence = Persistence(postgres_url)
    persistence.start()
    registry = SessionRegistry(
        settings, recorder=persistence.recorder, session_store=persistence.session_store
    )
    sid = await registry.create(RunOptions(), title="live-outage")
    session = registry.get(sid)

    killed = False
    collected: list[dict] = []
    async for event in session.send("Reply with exactly: ALIVE"):
        collected.append(event)
        if not killed:
            subprocess.run(  # noqa: S603, S607
                ["docker", "stop", container], check=False, capture_output=True
            )
            killed = True
    turn = session.last_turn

    print(
        f"\n[T9-C] turn completed with postgres down: events={len(collected)} "
        f"outcome_recorded={turn is not None and turn.outcome is not None}"
    )

    # THE ASSERTION THAT MATTERS: the turn finished normally anyway.
    assert turn is not None
    assert turn.outcome is not None, "a database outage failed the turn"
    assert not turn.timed_out

    subprocess.run(  # noqa: S603, S607
        ["docker", "start", container], check=False, capture_output=True
    )
    for _ in range(60):
        probe = subprocess.run(  # noqa: S603, S607
            ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "agent"],
            check=False,
            capture_output=True,
        )
        if probe.returncode == 0:
            break
        await asyncio.sleep(1)

    await registry.close(sid)
    await persistence.aclose()
    stats = persistence.writer.stats
    print(
        f"[T9-C] writer: written={stats.written} failed_batches={stats.failed_batches} "
        f"dropped_stream_event={stats.dropped_stream_events} "
        f"dropped_other={stats.dropped_over_hard_cap}"
    )
    assert stats.failed_batches > 0, "postgres was stopped; some batch should have failed"


@needs
async def test_the_cost_column_carries_its_own_warning() -> None:
    """`sessions.total_cost_usd` will be read as authoritative. It is not.

    A stored column with that name invites a spend report. The caveat therefore
    has to live in the SCHEMA, not only in the docs, or the next person to write
    a dashboard will never see it.
    """
    from agent_spec.db.models import Session

    comment = Session.__doc__ or ""
    import inspect

    source = inspect.getsource(Session)
    assert "FLOOR" in source or "floor" in source, (
        "the total_cost_usd column must carry its own warning in models.py"
    )
    assert "interrupt" in source.lower()
    assert comment  # the class is documented at all
