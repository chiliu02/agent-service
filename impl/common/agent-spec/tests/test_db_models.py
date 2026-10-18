"""plan-03 Task 2: schema, engine, migrations.

Most of this is metadata assertions, which run free and offline. The one thing
metadata cannot prove -- that a partial unique index actually permits many NULL
uuids per session -- needs a live server, which `tests/dbharness.py` supplies:
`AGENT_SERVICE_TEST_DATABASE_URL` if set, else a testcontainer, else a skip.

Skipped, not deselected: `live` is deselected by a marker filter because it
costs money, whereas this one is free and merely needs a container, so it should
run automatically wherever one is available.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Numeric

from agent_spec.db import (
    Base,
    Event,
    InvalidDatabaseUrl,
    Run,
    Session,
    TranscriptEntry,
    normalize_url,
)

postgres = pytest.mark.postgres


# -- configuration ------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
    ],
)
def test_urls_people_actually_write_are_upgraded_to_asyncpg(given: str, expected: str) -> None:
    # Silently getting a SYNC driver inside an async service is a worse outcome
    # than a rewrite -- it fails at first use, inside the event loop, far from
    # the configuration that caused it.
    assert normalize_url(given) == expected


@pytest.mark.parametrize("bad", ["mysql://u:p@h/db", "sqlite:///x.db", "not-a-url"])
def test_a_non_postgres_url_is_rejected_loudly(bad: str) -> None:
    with pytest.raises(InvalidDatabaseUrl):
        normalize_url(bad)


# -- the identity decision ----------------------------------------------------


def test_the_session_key_is_the_service_sid_not_the_sdks() -> None:
    """Pins plan-03 Task 2's decision, which reverses the design's original.

    `SessionRecord.session_id` publishes the service-side `sid` (`api.py:130`),
    so that is the only id a client has ever seen. The SDK's is a separate,
    nullable column because it does not exist until the first turn.
    """
    pk = [c.name for c in Session.__table__.primary_key.columns]
    assert pk == ["id"]
    sdk = Session.__table__.columns["sdk_session_id"]
    assert sdk.nullable is True
    assert sdk.index is True


def test_a_run_can_exist_without_a_session() -> None:
    # A one-shot POST /v1/query is never registered, so it has no sid. If this
    # column became NOT NULL, one-shot runs would stop being recordable.
    assert Run.__table__.columns["session_id"].nullable is True


# -- schema shape -------------------------------------------------------------


def test_every_table_is_present() -> None:
    assert set(Base.metadata.tables) == {
        "sessions",
        "runs",
        "events",
        "transcript_entries",
    }


def test_money_is_numeric_never_float() -> None:
    # Summed for reporting; a binary float makes two identical reports disagree
    # in the sixth decimal.
    for column in (
        Session.__table__.columns["total_cost_usd"],
        Run.__table__.columns["cost_usd"],
    ):
        assert isinstance(column.type, Numeric)
        assert column.type.scale == 6


def test_an_unpriced_session_is_null_and_not_zero() -> None:
    """`sessions.total_cost_usd` must be nullable AND have no server default.

    **Two assertions because either alone leaves the defect standing.** A
    nullable column that still defaults to `0` records `0` for every row nobody
    prices, which is exactly the state this is here to prevent: a build that
    cannot price a turn -- Codex reports no monetary figure anywhere -- would
    fill a shared table with zeros indistinguishable from *free*.

    The distinction the published document draws since 0.16.0:

      0     this build CAN price a turn; the floor has not moved
      NULL  this build cannot price a turn at all

    Revision `d3f9a0c15e27`. `Run.cost_usd` was already nullable and is checked
    alongside so that a future "tidy-up" restoring a default to either one has
    to argue with a test rather than with a comment.
    """
    total = Session.__table__.columns["total_cost_usd"]
    assert total.nullable is True, (
        "sessions.total_cost_usd is NOT NULL again -- a build that cannot price "
        "a turn then has to write a number it does not have"
    )
    assert total.server_default is None, (
        "sessions.total_cost_usd has a server default again; a default of 0 "
        "makes the column nullable in name only"
    )
    assert Run.__table__.columns["cost_usd"].nullable is True


def test_every_timestamp_carries_a_timezone() -> None:
    # A naive column reinterprets values in the server's local zone, so two
    # deployments in different regions disagree about when a run happened.
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if type(column.type).__name__ == "DateTime":
                assert column.type.timezone is True, f"{table.name}.{column.name}"


def test_events_cannot_hold_two_rows_at_the_same_position() -> None:
    names = {c.name for c in Event.__table__.constraints}
    assert "events_run_seq_unique" in names


def test_the_transcript_dedup_index_is_partial() -> None:
    """The load-bearing detail, and the one most likely to be lost silently.

    A PLAIN unique index on (session_key, uuid) would collapse every NULL-uuid
    entry -- titles, tags, mode markers, which the SDK says must be appended
    WITHOUT dedup -- into a single row per session. Postgres treats NULLs as
    distinct in a unique index by default, so this would not error; it would
    just quietly keep one. Hence the predicate.
    """
    index = next(
        i for i in TranscriptEntry.__table__.indexes if i.name == "transcript_entries_dedup"
    )
    assert index.unique is True
    where = index.dialect_options["postgresql"]["where"]
    assert where is not None
    assert "uuid IS NOT NULL" in str(where)


# -- against a real Postgres --------------------------------------------------


@postgres
@pytest.mark.anyio
async def test_the_partial_index_permits_many_null_uuids_per_session(
    postgres_url: str,
) -> None:
    """What metadata cannot prove. Verified against a live server.

    Three NULL-uuid rows for one session must coexist; a repeated (session_key,
    uuid) must be rejected; the same uuid under a DIFFERENT session must be
    accepted.
    """
    from sqlalchemy import text as sql
    from sqlalchemy.exc import IntegrityError

    from agent_spec.db import create_engine

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    insert = sql(
        "INSERT INTO transcript_entries (session_key, uuid, entry) "
        "VALUES (:k, :u, '{}'::jsonb)"
    )
    async with engine.begin() as conn:
        for _ in range(3):
            await conn.execute(insert, {"k": "s1", "u": None})
        await conn.execute(insert, {"k": "s1", "u": "u-1"})

    async with engine.connect() as conn:
        count = await conn.scalar(
            sql("SELECT count(*) FROM transcript_entries WHERE session_key='s1' AND uuid IS NULL")
        )
    assert count == 3

    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(insert, {"k": "s1", "u": "u-1"})

    # The index is scoped to a session, so another session may reuse the uuid.
    async with engine.begin() as conn:
        await conn.execute(insert, {"k": "s2", "u": "u-1"})

    await engine.dispose()
