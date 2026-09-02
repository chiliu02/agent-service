"""The schema-revision boot gate (0.10.0) — Agent Studio's four clauses.

From Studio's own clauses (CP-137), adopted verbatim:

1. image expects *R*, database at *R* → starts normally;
2. image expects *R*, database **earlier** → refuses, message names both;
3. image expects *R*, database **later** → refuses, message names both;
4. no database configured → starts normally, nothing compared.

**Clause 3 is written first**, as Studio asked, because it is the direction a
single-sided implementation omits and the one a drain-then-cutover produces: a
container on the old tag against a schema that moved forward *succeeds* and
writes rows missing a column the fleet relies on.
"""

from __future__ import annotations

import pytest

postgres = pytest.mark.postgres


async def _engine_at(url: str, revision: str | None):  # noqa: ANN202
    """A database whose `alembic_version` says `revision`, or which has none.

    The gate reads that table and nothing else, so a real migration run is not
    needed to exercise it -- and using one would tie these tests to whatever the
    head happens to be, which is the thing under test.
    """
    from sqlalchemy import text

    from agent_spec.db import create_engine

    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        if revision is not None:
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version "
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision}
            )
    return engine


# --- clause 3, first: the image is BEHIND the database ----------------------


@postgres
@pytest.mark.anyio
async def test_it_refuses_when_the_database_is_AHEAD_of_this_image(
    postgres_url: str,
) -> None:
    """The direction that matters, and the one a cutover produces.

    Such a container would otherwise start and write silently-incomplete rows:
    a schema that gained a column is still readable by code that does not know
    about it, so nothing raises and nothing is detectable afterwards.
    """
    from agent_spec.db.revision import (
        EXPECTED_REVISION,
        SchemaRevisionMismatch,
        verify_schema_revision,
    )

    engine = await _engine_at(postgres_url, "zzz_a_later_revision")
    try:
        with pytest.raises(SchemaRevisionMismatch) as excinfo:
            await verify_schema_revision(engine)
        # "message names both" -- clause 3's own requirement.
        assert EXPECTED_REVISION in str(excinfo.value)
        assert "zzz_a_later_revision" in str(excinfo.value)
    finally:
        await engine.dispose()


# --- clause 2: the image is AHEAD of the database ---------------------------


@postgres
@pytest.mark.anyio
async def test_it_refuses_when_the_database_is_BEHIND_this_image(
    postgres_url: str,
) -> None:
    from agent_spec.db.revision import (
        EXPECTED_REVISION,
        SchemaRevisionMismatch,
        verify_schema_revision,
    )

    engine = await _engine_at(postgres_url, "a5cf3bd007f9")
    try:
        with pytest.raises(SchemaRevisionMismatch) as excinfo:
            await verify_schema_revision(engine)
        assert EXPECTED_REVISION in str(excinfo.value)
        assert "a5cf3bd007f9" in str(excinfo.value)
    finally:
        await engine.dispose()


@postgres
@pytest.mark.anyio
async def test_a_database_that_was_never_migrated_is_refused_and_says_so(
    postgres_url: str,
) -> None:
    """The extreme of clause 2, and the message differs on purpose.

    "No revision at all" is a different operator mistake from "the wrong
    revision" -- somebody skipped the migration rather than mis-paired a tag --
    so it names the remedy that actually applies.

    **This reverses a sentence in 0.6.0's notes**: "the service boots against an
    unmigrated database. No gate covers this, and none is planned." A gate
    covers it now, and only at boot. A service already running when the schema
    is dropped still reports through `/healthz` and still takes nothing down.
    """
    from agent_spec.db.revision import SchemaRevisionMismatch, verify_schema_revision

    engine = await _engine_at(postgres_url, None)
    try:
        with pytest.raises(SchemaRevisionMismatch) as excinfo:
            await verify_schema_revision(engine)
        assert excinfo.value.actual is None
        assert "no revision at all" in str(excinfo.value)
        assert "alembic upgrade head" in str(excinfo.value)
    finally:
        await engine.dispose()


# --- clause 1: matching -----------------------------------------------------


@postgres
@pytest.mark.anyio
async def test_it_starts_when_the_revisions_match(postgres_url: str) -> None:
    from agent_spec.db.revision import EXPECTED_REVISION, verify_schema_revision

    engine = await _engine_at(postgres_url, EXPECTED_REVISION)
    try:
        await verify_schema_revision(engine)  # must not raise
    finally:
        await engine.dispose()


@postgres
@pytest.mark.anyio
async def test_a_real_migrated_database_satisfies_the_gate(postgres_url: str) -> None:
    """Clause 1 again, against a database Alembic actually migrated.

    The tests above write `alembic_version` by hand, which exercises the gate
    but proves nothing about the constant matching what a migration produces.
    This closes that gap end to end.
    """
    from sqlalchemy import text

    from agent_spec.db import create_engine
    from agent_spec.db.revision import EXPECTED_REVISION, current_revision
    from agent_spec.db.testing import run_alembic as _alembic

    engine = create_engine(postgres_url)
    try:
        # From nothing, including any `alembic_version` an earlier test left --
        # a stale one makes `upgrade head` a no-op that then proves nothing.
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))

        await _alembic(postgres_url, "head")

        assert await current_revision(engine) == EXPECTED_REVISION
    finally:
        await engine.dispose()


# --- 0.13.0: the connection gate around the revision gate -------------------
#
# NOTE none of these needs the `postgres` marker. The point of them is a
# database that ANSWERS NOTHING, so a running server would be the wrong fixture.
#
# One thing they deliberately do NOT assert, because the four tests above
# already do: that `SchemaRevisionMismatch` still escapes as itself. If the
# `try` in `verify_schema_revision` reached past `current_revision` and covered
# the comparison, every one of those would fail with `DatabaseUnreachable`
# instead. A separate structural test would be a second statement of a thing
# already pinned.


@pytest.mark.anyio
async def test_an_unreachable_database_is_refused_with_a_message_not_a_traceback() -> (
    None
):
    """0.13.0. The defect Agent Studio was told about before they hit it.

    Reported to Studio (CP-136): a container
    given `AGENT_SERVICE_DATABASE_URL` pointing somewhere unreachable died with
    a bare `socket.gaierror` as the last line before `Application startup
    failed`. The exit code was already right (3, the same as every other boot
    gate); nothing said which host, or which variable to look at.

    It matters now rather than eventually because Studio's D-04 gives every
    container in a fleet the same connection string, so this is the failure
    their wiring meets first -- wrong host, wrong port, Postgres not up yet.

    **Port 1 on loopback, not a bogus hostname.** A refused connection is
    immediate and needs no resolver; a `.invalid` host would exercise the DNS
    arm of the same `except` at the cost of a DNS timeout in CI. The broad catch
    covers both, and this is the deterministic half.
    """
    from agent_spec.db import create_engine
    from agent_spec.db.revision import DatabaseUnreachable, verify_schema_revision

    engine = create_engine("postgresql://someuser:hunter2@127.0.0.1:1/somedb")
    try:
        with pytest.raises(DatabaseUnreachable) as excinfo:
            await verify_schema_revision(engine)
    finally:
        await engine.dispose()

    message = str(excinfo.value)
    # Where it tried, so an operator can compare it with what they meant.
    assert "127.0.0.1:1" in message
    assert "somedb" in message
    assert "someuser" in message
    # What to look at, named exactly.
    assert "AGENT_SERVICE_DATABASE_URL" in message
    # And that unsetting it is a supported answer rather than a defeat.
    assert "without persistence" in message
    # The driver's own class name survives -- it is the one piece of the
    # original that distinguishes a refusal from a DNS failure from a timeout.
    assert excinfo.value.__cause__ is not None


@pytest.mark.anyio
async def test_the_unreachable_message_never_carries_the_password() -> None:
    """`get_settings` pops the URL out of the environment so the agent cannot
    read it. A boot log that printed it back would undo that in one line.

    Asserted against the message AND the repr, because an exception reaches a
    log through either.
    """
    from agent_spec.db import create_engine
    from agent_spec.db.revision import DatabaseUnreachable, verify_schema_revision

    secret = "s3cr3t-do-not-log"  # noqa: S105 - the thing under test
    engine = create_engine(f"postgresql://someuser:{secret}@127.0.0.1:1/somedb")
    try:
        with pytest.raises(DatabaseUnreachable) as excinfo:
            await verify_schema_revision(engine)
    finally:
        await engine.dispose()

    assert secret not in str(excinfo.value)
    assert secret not in repr(excinfo.value)


# --- clause 4, and the test that makes the baked constant safe --------------


def test_the_expected_revision_is_the_alembic_head() -> None:
    """`EXPECTED_REVISION` equals the head in the migration tree.

    **This test is part of the feature, not a check on it.** The image ships no
    `migrations/` -- measured: `/app` holds `pyproject.toml`, `uv.lock`,
    `README.md` and `src/` and nothing else -- so the gate cannot read the head
    at runtime and the constant is the only statement of it. A constant that
    drifted from the tree would make the gate confidently wrong, which is worse
    than not having one.

    **Since Plan 9 step 2 the tree is `impl/common/db/`, shared**, which
    strengthens this rather than weakening it: every implementation that
    persists bakes the same expected revision, because they migrate one database
    between them. Three images disagreeing about the head is precisely what the
    gate exists to catch, so each build needs its own copy of this test.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from agent_spec.db.revision import EXPECTED_REVISION
    from agent_spec.db.testing import ALEMBIC

    script = ScriptDirectory.from_config(Config(str(ALEMBIC / "alembic.ini")))
    heads = script.get_heads()

    assert list(heads) == [EXPECTED_REVISION], (
        f"EXPECTED_REVISION is {EXPECTED_REVISION!r} but the migration tree's "
        f"head is {heads}. Bump the constant in the same commit as the "
        f"revision -- see src/agent_service/db/revision.py."
    )


def test_no_database_configured_compares_nothing() -> None:
    """Clause 4, asserted structurally.

    The gate is reachable only through `Persistence`, which `create_app`
    constructs only when `database_url` is set. With persistence off the module
    is never imported at all -- which
    `test_persistence_wiring.test_no_database_url_imports_no_database_code`
    already pins for the whole `agent_service.db` package, this module included.
    """
    import inspect

    from agent_service.api import create_app

    source = inspect.getsource(create_app)
    # The call is inside the `if app.state.persistence is not None:` branch.
    assert "verify_revision()" in source
    before, _, after = source.partition("await app.state.persistence.verify_revision()")
    assert "if app.state.persistence is not None:" in before
