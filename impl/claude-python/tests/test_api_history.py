"""plan-03 Task 5: reading stored history back.

Two routes, and the interesting cases are the absences: history that was never
enabled, a session that was never recorded, and a page boundary that must not
drop or repeat an event.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings

postgres = pytest.mark.postgres

_DISABLED_TYPE = "https://agent-service.invalid/problems/persistence-disabled"


def _app(**kw) -> TestClient:  # noqa: ANN003
    # `require_credentials=False` for the same reason conftest's fixture sets
    # it: the lifespan calls `verify_credentials` and would otherwise refuse to
    # start, which is deliberate behaviour and not what these tests are about.
    return TestClient(
        create_app(Settings(workspace_dir="./workspace", require_credentials=False, **kw))
    )


# -- persistence off ----------------------------------------------------------


def test_history_routes_404_cleanly_with_no_database() -> None:
    """404, not 500, and NOT an empty list.

    An empty list would read as "this session had no events", which is a
    different and wrong answer. A 500 would read as a bug. The service is
    working exactly as configured; the resource genuinely is not here.
    """
    with _app() as client:
        for path in ("/v1/sessions/abc/transcript", "/v1/runs/abc"):
            response = client.get(path)
            assert response.status_code == 404, path
            body = response.json()
            assert body["type"] == _DISABLED_TYPE, path
            # The detail must say how to turn it on, or an operator has to read
            # the source to find out why their history is missing.
            assert "AGENT_SERVICE_DATABASE_URL" in body["detail"]


def test_the_disabled_problem_is_distinguishable_from_a_missing_session() -> None:
    # Both are 404s. A client retrying with a different session id is right in
    # one case and wasting its time in the other, so they must not be told the
    # same thing.
    with _app() as client:
        disabled = client.get("/v1/sessions/abc/transcript").json()
    assert disabled["type"] == _DISABLED_TYPE
    assert disabled["title"] == "History is not available"

    from agent_service.errors import to_problem
    from agent_service.registry import SessionNotFound

    missing = to_problem(SessionNotFound("abc"))
    assert missing.status == 404
    assert missing.type != _DISABLED_TYPE
    assert missing.title != "History is not available"


def test_reading_history_does_not_touch_the_live_session_route() -> None:
    # `GET /v1/sessions/{sid}` issues a live control request and is documented
    # as returning 502/500 when the CLI is wedged. Stored history must not
    # inherit that failure mode, which is why it is a separate route.
    with _app() as client:
        schema = client.get("/openapi.json").json()
    transcript = schema["paths"]["/v1/sessions/{sid}/transcript"]["get"]
    assert set(transcript["responses"]) == {"200", "404", "422"}
    assert "500" not in transcript["responses"]
    assert "502" not in transcript["responses"]


# -- against a real database --------------------------------------------------


@postgres
@pytest.mark.anyio
async def test_a_transcript_reads_back_paginated_and_in_order(postgres_url: str) -> None:
    from sqlalchemy import text as sql

    from agent_spec.db import Base, create_engine
    from agent_spec.db.wiring import Persistence

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sql("INSERT INTO sessions (id, status) VALUES ('s1', 'idle'), ('s2', 'idle')")
        )
        await conn.execute(
            sql("INSERT INTO runs (id, session_id, prompt) VALUES ('r1', 's1', 'p'), ('r2', 's2', 'p')")
        )
        for i in range(1, 8):
            await conn.execute(
                sql("INSERT INTO events (run_id, seq, type) VALUES ('r1', :s, 'assistant')"),
                {"s": i},
            )
        # A second session's events must never appear in the first's page.
        await conn.execute(sql("INSERT INTO events (run_id, seq, type) VALUES ('r2', 1, 'assistant')"))
    await engine.dispose()

    persistence = Persistence(postgres_url)
    try:
        async with persistence.sessionmaker() as db:
            from agent_spec.db import queries

            first = await queries.transcript(db, "s1", limit=3, after=None)
            assert [e["seq"] for e in first.events] == [1, 2, 3]
            assert first.next_after is not None

            second = await queries.transcript(db, "s1", limit=3, after=first.next_after)
            assert [e["seq"] for e in second.events] == [4, 5, 6]

            third = await queries.transcript(db, "s1", limit=3, after=second.next_after)
            # Exactly the remainder: no gap at the boundary, no repeat.
            assert [e["seq"] for e in third.events] == [7]
            # The last page reports no cursor, which is how a client stops.
            assert third.next_after is None

            # Scoped to the session, not global.
            assert all(e["run_id"] == "r1" for e in first.events + second.events + third.events)

            assert await queries.session_exists(db, "s1") is True
            assert await queries.session_exists(db, "nope") is False
    finally:
        await persistence.aclose()


@postgres
@pytest.mark.anyio
async def test_a_stored_run_reads_back_with_the_fields_the_stream_omits(
    postgres_url: str,
) -> None:
    from sqlalchemy import text as sql

    from agent_spec.db import Base, create_engine, queries
    from agent_spec.db.wiring import Persistence

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sql(
                "INSERT INTO runs (id, prompt, duration_api_ms, api_error_status, cost_usd) "
                "VALUES ('r9', 'hello', 42, 529, 0.125)"
            )
        )
    await engine.dispose()

    persistence = Persistence(postgres_url)
    try:
        async with persistence.sessionmaker() as db:
            row = await queries.run(db, "r9")
            assert await queries.run(db, "missing") is None
    finally:
        await persistence.aclose()

    assert row is not None
    # A one-shot run has no session, and that must survive the round trip as
    # null rather than becoming an error.
    assert row["session_id"] is None
    # The three fields deliberately absent from RunResponse.
    assert row["duration_api_ms"] == 42
    assert row["api_error_status"] == 529
    # NUMERIC comes back as Decimal; the schema promises a float.
    assert row["cost_usd"] == 0.125
    assert isinstance(row["cost_usd"], float)
