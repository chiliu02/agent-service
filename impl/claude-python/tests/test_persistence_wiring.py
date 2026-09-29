"""plan-03 Task 4: the recorder wired to the database.

Its own file rather than an appendix to `test_recorder.py`, which is about the
seam in isolation. These two tests are about the wiring: that persistence stays
genuinely absent when it is off, and that when it is on the stored rows are a
faithful record of the turn.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent_service.config import Settings

postgres = pytest.mark.postgres


def test_no_database_url_imports_no_database_code() -> None:
    """With persistence off, SQLAlchemy must never be imported.

    A FRESH INTERPRETER, because by the time this file runs, other tests have
    already imported `agent_service.db` and an in-process `sys.modules` check
    would pass no matter what `create_app` does. The same reasoning as
    `test_errors.py`'s standalone-import test.

    This is not about startup milliseconds. plan-03's first global constraint is
    that a database must never become a hard dependency; the way that decays is
    for an unconditional import to creep into `api.py` and go unnoticed because
    everything still works on the machine that has a database.
    """
    code = (
        "import sys;"
        "from agent_service.api import create_app;"
        "from agent_service.config import Settings;"
        "app = create_app(Settings(workspace_dir='./workspace'));"
        "assert app.state.persistence is None, 'persistence built without a URL';"
        "leaked = [m for m in sys.modules if m.startswith('agent_service.db') "
        "or m == 'sqlalchemy'];"
        "print('LEAKED:' + ','.join(sorted(leaked)))"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "LEAKED:\n" in result.stdout or result.stdout.strip() == "LEAKED:", (
        f"database modules imported with no database_url: {result.stdout!r}"
    )


def test_a_database_url_builds_the_persistence_stack() -> None:
    # The other half of the branch above: a URL must actually wire it up, or
    # the test would pass just as well with persistence deleted entirely.
    from agent_service.api import create_app

    app = create_app(
        Settings(
            workspace_dir="./workspace",
            database_url="postgresql://u:p@127.0.0.1:1/none",
        )
    )
    assert app.state.persistence is not None
    # Constructing an engine does not connect, so this is safe with nothing
    # listening on that port.
    assert app.state.registry._recorder is app.state.persistence.recorder


@postgres
@pytest.mark.anyio
async def test_a_turns_rows_reconstruct_it_exactly(postgres_url: str) -> None:
    """Same events, same order, same content as the caller was streamed.

    Drives the REAL path: registry mints the sid, its default factory attaches
    the recorder, `_send_impl` records each frame, the writer batches, and
    `repository.apply` writes. Only the SDK client is faked.
    """
    from sqlalchemy import text as sql

    from agent_spec.db import Base, create_engine
    from agent_spec.db.wiring import Persistence
    from agent_service.registry import SessionRegistry
    from agent_spec.openapi.schemas import RunOptions
    from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock

    from tests.test_recorder import _result
    from tests.test_sessions import FakeClient

    # A turn carrying real result text, so `result_text` round-tripping is
    # actually asserted rather than trivially None on both sides.
    turn = [
        SystemMessage(subtype="init", data={"session_id": "sess-1"}),
        AssistantMessage(content=[TextBlock(text="hi")], model="claude-sonnet-5"),
        _result(result="all done"),
    ]

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    persistence = Persistence(postgres_url)
    persistence.start()

    client = FakeClient([turn])
    settings = Settings(workspace_dir="./workspace")
    registry = SessionRegistry(settings, recorder=persistence.recorder)
    # Patch the CLIENT factory, not the session factory: the registry only
    # attaches its recorder through its own default session factory, so a
    # custom session factory would silently record nothing.
    import agent_service.sessions as sessions_mod

    original = sessions_mod._default_client_factory
    sessions_mod._default_client_factory = lambda _o: client
    try:
        sid = await registry.create(RunOptions(), title="t")
        session = registry.get(sid)
        streamed = [event async for event in session.send("hello")]
        await registry.close(sid)
    finally:
        sessions_mod._default_client_factory = original

    await persistence.aclose()
    assert persistence.writer.stats.failed_batches == 0

    engine = create_engine(postgres_url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sql("SELECT seq, type, subtype FROM events ORDER BY seq")
            )
        ).all()
        run = (
            await conn.execute(
                sql("SELECT id, session_id, sdk_session_id, result_text, outcome_missing FROM runs")
            )
        ).one()
        sess = (
            await conn.execute(
                sql("SELECT id, status, total_turns, sdk_session_id FROM sessions")
            )
        ).one()
    await engine.dispose()

    # Same events, same order, same types as the caller saw.
    assert [r.type for r in rows] == [e["type"] for e in streamed]
    assert [r.seq for r in rows] == [e["seq"] for e in streamed]

    # The run is attached to its session by the SERVICE-side sid -- the gap
    # Task 2 could not close because the protocol did not carry it.
    assert run.session_id == sid
    assert sess.id == sid
    assert run.sdk_session_id == "sess-1"
    assert run.outcome_missing is False
    assert run.result_text == "all done"

    # Rolled up, and `total_turns` counts turns that reached a result.
    assert sess.total_turns == 1
    assert sess.status == "closed"
    assert sess.sdk_session_id == "sess-1"


@postgres
async def test_the_health_probe_distinguishes_a_missing_schema_from_a_working_one(
    postgres_url: str, caplog
) -> None:
    """`Persistence.usable()` -- the check behind `/healthz.database_usable`.

    **The case worth the test is the unmigrated schema**, because it is the one
    a `SELECT 1` passes: the connection is fine, the credential is fine, and the
    table is simply not there. It is also the likeliest state of any deployment
    that turns persistence on, since migrations do not run on startup and the
    image ships no `migrations/`. So the probe queries a real table, and this
    drops the schema to prove it notices.
    """
    import logging

    from agent_spec.db.engine import create_engine
    from agent_spec.db.models import Base
    from agent_spec.db.wiring import Persistence

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    persistence = Persistence(postgres_url)
    try:
        with caplog.at_level(logging.WARNING, logger="agent_spec.db.wiring"):
            assert await persistence.usable() is False

        # The reason goes to the log and NOT to the caller (Q16: /healthz is
        # unauthenticated), and it names the exception class, never its message.
        assert any("database probe failed" in r.message for r in caplog.records)

        # ONE line per outage, not one per healthcheck -- the route is polled
        # every 30s forever, and the unthrottled version wrote a warning each
        # time.
        caplog.clear()
        assert await persistence.usable() is False
        assert not caplog.records

        # Create the schema and it recovers with no restart, because the probe
        # is per request rather than cached from boot.
        engine = create_engine(postgres_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

        assert await persistence.usable() is True
    finally:
        await persistence.aclose()


@postgres
async def test_the_health_probe_never_raises_even_when_the_database_is_gone(
    caplog,
) -> None:
    """It is called from `/healthz`, so it must not be able to fail the route.

    An unreachable host, not a broken query: the failure arrives from a
    different layer (DNS/connect rather than SQL) and must be caught just the
    same. Marked `postgres` only because it builds a `Persistence`; it never
    reaches a server.
    """
    from agent_spec.db.wiring import Persistence

    persistence = Persistence("postgresql://u:p@no-such-host.invalid:5432/nope")
    try:
        assert await persistence.usable() is False
    finally:
        await persistence.aclose()

def test_the_preboot_specification_imports_no_database_code() -> None:
    """CP-147: `schema_revision` must not cost the pre-boot command SQLAlchemy.

    A FRESH INTERPRETER, for the same reason as the wiring test it sits beside:
    once any other test has imported the database seam, an in-process
    `sys.modules` check passes no matter what this module does.

    The value is the Alembic head, which lives next to the boot gate that
    compares it against a live database -- and importing THAT module pulls
    SQLAlchemy. The pre-boot facts are read once, at import, to build the
    document's `PrebootSpec` component, so the constant comes from the
    import-free leaf instead. The command that used to make this urgent is
    gone, and the constraint is kept: it costs nothing, and it keeps the one
    place these constants are read free of anything that can fail.
    """
    import subprocess
    import sys

    code = (
        "import sys;"
        "from agent_service.spec import specification;"
        "d = specification();"
        "assert d['schema_revision'], 'the revision is not published';"
        "assert not [m for m in sys.modules if m.startswith('sqlalchemy')], "
        "'the pre-boot specification imported a database stack'"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr


def test_the_published_schema_revision_is_the_one_the_boot_gate_enforces() -> None:
    """CP-147: the image states the DDL it requires, and cannot state a different one.

    An image depends on two published artifacts -- the OpenAPI document and the
    DDL -- and they move on separate streams, so neither can be read off the
    other. Both are on the pre-boot surface because the database is chosen
    before the container is created.
    """
    from agent_service.spec import specification
    from agent_spec.db.revision import EXPECTED_REVISION

    published = specification()["schema_revision"]
    assert published == EXPECTED_REVISION, "the image would accept a database it refuses"
    assert specification()["document_version"], "the other half of the pair is missing"
