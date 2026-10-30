"""`AGENT_ID` provenance (0.9.0) — Agent Studio's four acceptance clauses.

The clauses are Studio's own words (CP-138), adopted
verbatim in this side's acceptance so the ask is checkable rather than
interpretable:

1. a container started with `AGENT_ID=<x>` creates a session whose `sessions`
   row has `agent_id = '<x>'`;
2. the transcript entries written by a turn on that session carry the same
   value;
3. a container started with **no** `AGENT_ID` creates a session successfully,
   `agent_id` is null, and nothing else differs;
4. the value is never echoed back into a place a caller could set it.

**Clause 4 is structural rather than validated**, which is why its test asserts
the absence of a parameter rather than the rejection of a value: `agent_id` is a
process constant held by the two writers, `session_opened` takes no such
argument, and `SessionCreate` has no such field. There is nothing for a caller
value to arrive through. A test that posted `{"agent_id": "..."}` and checked it
was ignored would pass just as well against a service that accepted it and then
overwrote it — a weaker property, and not the one Studio asked for.
"""

from __future__ import annotations

import pytest

postgres = pytest.mark.postgres

AGENT = "agent-7f3c9a1e"


async def _prepared_engine(url: str):  # noqa: ANN202
    from agent_spec.db import Base, create_engine

    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine


# --- clause 1: the sessions row ---------------------------------------------


@postgres
@pytest.mark.anyio
@pytest.mark.parametrize("agent_id", [AGENT, None], ids=["with-agent-id", "without"])
async def test_the_session_row_carries_the_agent_id_or_null(
    postgres_url: str, agent_id: str | None
) -> None:
    """Clauses 1 and 3 together, because they are the same assertion.

    Parametrised deliberately rather than written twice: clause 3's claim is
    that the no-`AGENT_ID` deployment differs in the column and in *nothing
    else*, and the cheapest way to mean that is to run one body against both.
    """
    from sqlalchemy import select

    from agent_spec.db import create_sessionmaker
    from agent_spec.db.models import Session
    from agent_spec.db.database import DatabaseRecorder
    from agent_spec.db.writer import QueueWriter

    engine = await _prepared_engine(postgres_url)
    try:
        sessionmaker = create_sessionmaker(engine)
        writer = QueueWriter(sessionmaker)
        writer.start()
        try:
            DatabaseRecorder(writer, agent_id).session_opened(
                "sid-1", title="t", model="m", permission_mode="dontAsk", at=1.0
            )
        finally:
            # Flushes what is queued, then stops. The recorder is a pure sink;
            # nothing is written until the writer drains.
            await writer.aclose()

        async with sessionmaker() as db:
            row = (await db.execute(select(Session))).scalar_one()

        assert row.agent_id == agent_id
        # "and nothing else differs" -- the rest of the row is written the same
        # way with the variable set or unset.
        assert row.id == "sid-1"
        assert row.title == "t"
        assert row.model == "m"
        assert row.status == "idle"
    finally:
        await engine.dispose()


# --- clause 2: the transcript entries ---------------------------------------


@postgres
@pytest.mark.anyio
@pytest.mark.parametrize("agent_id", [AGENT, None], ids=["with-agent-id", "without"])
async def test_transcript_entries_carry_the_same_value(
    postgres_url: str, agent_id: str | None
) -> None:
    """Clause 2, and the reason part C was not optional.

    `transcript_entries` has no foreign key to `sessions`, so this column is
    the only thing that can attribute a transcript. See the column comment in
    `db/models.py` for why the join that looks available is unsound.
    """
    from sqlalchemy import select

    from agent_spec.db import create_sessionmaker
    from agent_spec.db.models import TranscriptEntry
    from agent_service.db.session_store import PostgresSessionStore

    engine = await _prepared_engine(postgres_url)
    try:
        sessionmaker = create_sessionmaker(engine)
        store = PostgresSessionStore(sessionmaker, agent_id)
        key = {"project_key": "proj", "session_id": "sdk-1"}

        await store.append(key, [{"uuid": "u1", "type": "user"}])

        async with sessionmaker() as db:
            rows = (await db.execute(select(TranscriptEntry))).scalars().all()

        assert [r.agent_id for r in rows] == [agent_id]
        # The mirrored entry itself is untouched: the stamp is a COLUMN, never
        # folded into `entry`. `load` must return entries deep-equal to what was
        # appended, and an added key would come back as a difference.
        assert rows[0].entry == {"uuid": "u1", "type": "user"}
    finally:
        await engine.dispose()


# --- clause 4: not settable by a caller -------------------------------------


def test_no_request_shape_can_carry_an_agent_id() -> None:
    """Clause 4, asserted where it is actually enforced: the type system.

    Not a round trip through the API, because that would prove only that one
    route ignores one field today.
    """
    import inspect

    from agent_spec.db.recorder import RunRecorder
    from agent_spec.openapi.schemas import RunOptions, SessionCreate

    assert "agent_id" not in SessionCreate.model_fields
    assert "agent_id" not in RunOptions.model_fields
    # The sink protocol takes no such argument either, so a future route could
    # not thread one through without changing this signature -- which is the
    # point of holding the value on the recorder instead of passing it in.
    assert "agent_id" not in inspect.signature(RunRecorder.session_opened).parameters


def test_the_record_exposes_agent_id_and_the_create_body_does_not() -> None:
    """The asymmetry Studio asked for: readable, never writable.

    `SessionRecord.agent_id` exists so the party that asked for the column can
    read it over `/v1` rather than by querying a schema whose shape is not in
    the signed bundle. `SessionCreate` has no counterpart, and must not gain
    one.
    """
    from agent_spec.openapi.schemas import SessionCreate, SessionRecord

    assert "agent_id" in SessionRecord.model_fields
    assert "agent_id" not in SessionCreate.model_fields

    # Nullable but NOT optional: always present, so `null` means "that container
    # had no AGENT_ID" and can never mean "this service did not tell you".
    assert SessionRecord.model_fields["agent_id"].is_required() is False
    dumped = SessionRecord(
        session_id="s",
        status="idle",
        created_at=0.0,
        last_used_at=0.0,
        turns=0,
        total_cost_usd=0.0,
    ).model_dump()
    assert "agent_id" in dumped
    assert dumped["agent_id"] is None


def test_the_setting_reads_the_unprefixed_variable_only(monkeypatch) -> None:  # noqa: ANN001
    """`AGENT_ID`, not `AGENT_SERVICE_AGENT_ID`.

    The name belongs to the consumer that sets it, so it does not take this
    service's prefix -- the same reason `ANTHROPIC_API_KEY` does not. The
    prefixed spelling is deliberately NOT also accepted: two names for one value
    is the ambiguity `sdk_session_id` exists to prevent.
    """
    from agent_service.config import Settings

    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_AGENT_ID", raising=False)
    assert Settings().agent_id is None

    monkeypatch.setenv("AGENT_SERVICE_AGENT_ID", "prefixed")
    assert Settings().agent_id is None, "the prefixed spelling must not be read"

    monkeypatch.setenv("AGENT_ID", AGENT)
    assert Settings().agent_id == AGENT
