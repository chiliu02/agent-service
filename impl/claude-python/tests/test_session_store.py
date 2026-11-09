"""plan-03 Task 6: the A.2 `SessionStore` adapter.

The acceptance criterion is the SDK's own conformance suite. It ships 14
behavioural specifications and skips the ones for optional methods an adapter does
not override -- so passing it is a real signal about `append`/`load` and an
honest silence about the rest.
"""

from __future__ import annotations

import pytest

postgres = pytest.mark.postgres


async def _prepared_engine(url: str):  # noqa: ANN202
    from agent_spec.db import Base, create_engine

    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine


@postgres
@pytest.mark.anyio
async def test_the_sdks_own_conformance_suite_passes(postgres_url: str) -> None:
    from claude_agent_sdk.testing import run_session_store_conformance

    from sqlalchemy import text as sql

    from agent_spec.db import create_sessionmaker
    from agent_service.db.session_store import PostgresSessionStore

    engine = await _prepared_engine(postgres_url)
    sessionmaker = create_sessionmaker(engine)

    async def make_store():  # noqa: ANN202
        # The suite calls this repeatedly and expects a GENUINELY FRESH store
        # each time -- several specifications (#3 call ordering, #9 delete) assume
        # an empty one. Handing back the same populated store makes specification #3
        # fail on data left by #1, which looks like an ordering bug in the
        # adapter and is not.
        async with engine.begin() as conn:
            await conn.execute(sql("TRUNCATE transcript_entries"))
        return PostgresSessionStore(sessionmaker)

    try:
        await run_session_store_conformance(make_store)
    finally:
        await engine.dispose()


@postgres
@pytest.mark.anyio
async def test_appending_the_same_batch_twice_stores_it_once(postgres_url: str) -> None:
    """The documented idempotency rule, asserted directly.

    The SDK says most entries carry a stable `uuid` that adapters should treat
    as an idempotency key. A retried batch -- which the SDK does retry, up to
    three times -- must not double every row.
    """
    from sqlalchemy import text as sql

    from agent_spec.db import create_sessionmaker
    from agent_service.db.session_store import PostgresSessionStore

    engine = await _prepared_engine(postgres_url)
    store = PostgresSessionStore(create_sessionmaker(engine))
    key = {"project_key": "p", "session_id": "s"}
    batch = [
        {"type": "user", "uuid": "u-1", "text": "hi"},
        {"type": "assistant", "uuid": "u-2", "text": "hello"},
        # No uuid: titles, tags and mode markers legitimately have none and
        # MUST be appended without dedup, which is why the unique index is
        # partial rather than plain.
        {"type": "title", "title": "chat"},
    ]
    try:
        await store.append(key, batch)
        await store.append(key, batch)

        async with engine.connect() as conn:
            total = await conn.scalar(sql("SELECT count(*) FROM transcript_entries"))
            with_uuid = await conn.scalar(
                sql("SELECT count(*) FROM transcript_entries WHERE uuid IS NOT NULL")
            )
            without = await conn.scalar(
                sql("SELECT count(*) FROM transcript_entries WHERE uuid IS NULL")
            )
        loaded = await store.load(key)
    finally:
        await engine.dispose()

    assert with_uuid == 2, "uuid-bearing entries were duplicated by the retry"
    # The no-uuid entry is appended BOTH times, by design.
    assert without == 2
    assert total == 4
    assert loaded is not None
    # Verbatim round trip: what went in is what comes out.
    assert {"type": "user", "uuid": "u-1", "text": "hi"} in loaded


@postgres
@pytest.mark.anyio
async def test_load_returns_none_for_a_key_never_written(postgres_url: str) -> None:
    from agent_spec.db import create_sessionmaker
    from agent_service.db.session_store import PostgresSessionStore

    engine = await _prepared_engine(postgres_url)
    store = PostgresSessionStore(create_sessionmaker(engine))
    try:
        # None, not [] -- the SDK reads this to decide whether there is
        # anything to resume from at all.
        assert await store.load({"project_key": "p", "session_id": "never"}) is None
    finally:
        await engine.dispose()


def test_a_mirror_failure_reaches_clients_as_a_system_event_not_agent_output() -> None:
    """`MirrorErrorMessage` is a SystemMessage subclass. Where does it surface?

    DECIDED: it flows through to API clients, unfiltered, like every other SDK
    message -- the README's specification is that every message is returned
    normalized, and silently dropping one because it is inconvenient would make
    that false. It is additionally logged by the adapter, which is where the
    actual cause lives.

    What matters for a console is that it normalizes to `type: "system"`, NOT
    `assistant`, so rendering assistant content never shows it as something the
    agent said. `event_type` walks the MRO, so the subclass resolves to its
    base's wire type rather than to "unknown".
    """
    from claude_agent_sdk import MirrorErrorMessage

    from agent_service.serialization import normalize

    message = MirrorErrorMessage(subtype="mirror_error", data={"error": "boom"})
    event = normalize(message, seq=1, include_raw=False)
    assert event["type"] == "system"
    assert event["subtype"] == "mirror_error"
    # No content blocks: nothing a chat view would render as a message.
    assert event["content"] is None
