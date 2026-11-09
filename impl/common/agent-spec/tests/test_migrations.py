"""The Alembic revisions, run against a real Postgres.

**Why this file exists.** plan-03 Task 2 verified `upgrade head` -> assertions ->
`downgrade base` BY HAND against a throwaway container, and wrote the result into
the plan. Nothing pinned it afterwards. Every other Postgres-backed test builds
its schema with `Base.metadata.create_all`, which never executes a single
migration -- so the models and the revisions could drift apart indefinitely and
the whole suite would stay green while a real deployment, which only ever gets
its schema from `alembic upgrade`, ended up with a different one.

`test_the_migrations_and_the_models_agree` is the test that would have caught
that. The round-trip test is Task 2's by-hand check, made repeatable.

## Two things worth knowing about running Alembic in-process

- **`command.upgrade` is sync and `migrations/env.py` calls `asyncio.run`**, so
  it cannot be called from inside a running event loop. `asyncio.to_thread` gives
  it a thread with no loop of its own, which is where that `asyncio.run` is
  legal.
- **`cmd_opts` is how `-x url=...` is passed programmatically.** Alembic reads
  `config.cmd_opts.x`, which the CLI populates from `-x` and which is `None` for
  a `Config` built in code. `env.py` documents that override as existing for this
  harness; a `Namespace` is what actually reaches it.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text as sql

from alembic import command
from alembic.config import Config

postgres = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]

#: The Alembic tree and the published DDL both left this implementation in Plan
#: 9 step 2, in opposite directions: the tree is shared operator tooling under
#: `impl/common/db/`, the DDL is a delivery under `schema/`.
#:
#: **This file reads both, and that is allowed for the reason
#: `test_the_published_spec_file_matches_this_version_of_the_app` is allowed to
#: read `spec/`:** what it asserts is that THIS build agrees
#: with THAT artifact. Reading a platform file to check conformance to it is the
#: opposite of depending on one.
ALEMBIC = ROOT.parent / "db"
SPEC_SCHEMA = ROOT.parents[2] / "spec" / "database"

TABLES = {"sessions", "runs", "events", "transcript_entries"}


def _config(url: str) -> Config:
    cfg = Config(str(ALEMBIC / "alembic.ini"))
    # See the module docstring: the CLI's `-x url=...`, by hand.
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    # env.py honours this. Without it, `fileConfig` reconfigures logging for the
    # rest of the pytest process.
    cfg.attributes["configure_logger"] = False
    return cfg


async def _alembic(url: str, *stops: str) -> None:
    """Run `upgrade`/`downgrade` off the event loop. `base` means downgrade."""
    cfg = _config(url)
    for stop in stops:
        action = command.downgrade if stop == "base" else command.upgrade
        await asyncio.to_thread(action, cfg, stop)


async def _tables(url: str) -> set[str]:
    from agent_spec.db import create_engine

    engine = create_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        return {row.tablename for row in rows}
    finally:
        await engine.dispose()


async def _drop_everything(url: str) -> None:
    """Start from nothing, including any `alembic_version` a prior test left.

    `Base.metadata.drop_all` is not enough: it does not know about
    `alembic_version`, and a stale one makes `upgrade head` a no-op that then
    fails on tables it thinks it already created.
    """
    from agent_spec.db import create_engine

    engine = create_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sql("DROP SCHEMA public CASCADE"))
            await conn.execute(sql("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


# -- the drift guard ----------------------------------------------------------


@postgres
async def test_the_migrations_and_the_models_agree(postgres_url: str) -> None:
    """This build's models conform to the PLATFORM's schema.

    THE test in this file. Every other Postgres test uses `create_all`, so a
    model changed without a revision -- or a revision that does not quite say
    what the model says -- is invisible to all of them, and visible in
    production as a column that is not there.

    **Its meaning inverted in Plan 9 step 3, though not a line of its mechanism
    did.** It used to ask "have the models outrun the migrations?", where the
    answer's remedy was `alembic revision --autogenerate` -- the models being the
    authority and the migrations their rendering. The migration tree is now
    `impl/common/db/`, shared by every implementation that persists, and
    `schema/` is the published artifact. So the same comparison
    now asks the opposite question: **does this implementation's ORM layer
    conform to the schema the platform specifies?**

    Which is why the failure message no longer says "generate a revision". A
    second implementation running its own copy of this test cannot be allowed to
    autogenerate against a schema three builds share.

    `compare_type=True` matches what `env.py` configures, so a changed column
    TYPE counts as drift rather than passing silently.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from agent_spec.db import Base, create_engine

    await _drop_everything(postgres_url)
    await _alembic(postgres_url, "head")

    def diff(sync_conn) -> list:  # noqa: ANN001
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    engine = create_engine(postgres_url)
    try:
        async with engine.connect() as conn:
            differences = await conn.run_sync(diff)
    finally:
        await engine.dispose()

    assert differences == [], (
        "this build's models do not conform to the platform schema at "
        "impl/common/db/migrations/. Decide which side is wrong: if the MODELS "
        "are right, the schema needs an authored revision in the common tree "
        "plus a regenerated DDL and a manifest row; "
        "if the SCHEMA is right, this build's models are the thing to fix. "
        "`--autogenerate` is deliberately no longer the answer -- the tree is "
        f"shared. Differences: {differences}"
    )


# -- Task 2's by-hand check, made repeatable ----------------------------------


@postgres
async def test_upgrade_then_downgrade_leaves_nothing_behind(postgres_url: str) -> None:
    """`downgrade base` must be a real inverse, not an approximate one.

    A downgrade that leaves a table behind is only discovered by the next person
    to run `upgrade head` on the same database, as a "relation already exists"
    they did not cause.
    """
    await _drop_everything(postgres_url)
    await _alembic(postgres_url, "head")
    assert TABLES <= await _tables(postgres_url)

    await _alembic(postgres_url, "base")
    remaining = await _tables(postgres_url)
    # `alembic_version` is Alembic's own bookkeeping and survives by design.
    assert remaining == {"alembic_version"}, f"downgrade left tables behind: {remaining}"


@postgres
async def test_the_partial_index_predicate_survives_the_migration(
    postgres_url: str,
) -> None:
    """plan-03 Task 2: "the step most likely to lose it silently".

    The predicate has to make it from the model, through autogeneration, into the
    revision file, and out to the server. `test_db_models.py` proves the model
    declares it and that a live server honours it; both work off `create_all`.
    This is the only assertion that it is in the MIGRATED schema -- and losing it
    turns the index unique-on-everything, which rejects the legitimately
    uuid-less entries (titles, tags, mode markers) the store must append.
    """
    from agent_spec.db import create_engine

    await _drop_everything(postgres_url)
    await _alembic(postgres_url, "head")

    engine = create_engine(postgres_url)
    try:
        async with engine.connect() as conn:
            definition = await conn.scalar(
                sql("SELECT indexdef FROM pg_indexes WHERE indexname = 'transcript_entries_dedup'")
            )
    finally:
        await engine.dispose()

    assert definition is not None, "the dedup index is missing from the migrated schema"
    assert "UNIQUE" in definition
    assert "uuid IS NOT NULL" in definition, f"the predicate was lost: {definition}"


@postgres
async def test_migrations_run_as_the_documented_command_does(postgres_url: str) -> None:
    """`-x url=...` is a documented interface, so it is tested as one.

    `env.py` resolves the URL from `Settings` unless `-x url=` overrides it. The
    override is what the container's compose file and this file both rely on,
    and it is a
    single `get_x_argument` call away from silently falling back to whatever
    `.env` names -- which for a developer with persistence configured would mean
    a test suite migrating their REAL database.
    """
    from agent_spec.db import create_engine

    await _drop_everything(postgres_url)
    await _alembic(postgres_url, "head")

    engine = create_engine(postgres_url)
    try:
        async with engine.connect() as conn:
            stamped = await conn.scalar(sql("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()

    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_config(postgres_url)).get_current_head()
    assert stamped == head, "the database was migrated somewhere other than head"


# -- the published SQL, which is committed and therefore can go stale ---------


def test_the_published_sql_schema_matches_the_migrations() -> None:
    """`schema/agent-service-<revision>.sql` is current and COMMITTED.

    **Named by the ALEMBIC REVISION since Plan 9 step 1, not by
    `pyproject.toml`'s version**, and the reason is a measurement: thirteen
    published DDL files held **two** distinct bodies. Every release re-emitted an
    unchanged schema under a new build version with a new timestamp in the
    header, so eleven of the thirteen carried no schema information at all. The
    revision is the stream that moves exactly when the schema does -- and it is
    what the boot gate compares and what an operator applies.

    Nothing under `schema/` is git-ignored: every file there is generated by
    `scripts/dump-schema.py` and read by code. Committing derived output has
    exactly one hazard -- a stale copy that still looks authoritative -- and this
    is the test that pays for it, the way
    `test_the_published_spec_file_matches_this_version_of_the_app` pays for the
    OpenAPI documents.

    No database: Alembic's offline mode renders the SQL a deployment would
    apply without opening a connection, which is why this is not `@postgres`.

    **The whole file is compared, header included**, which the version-named
    era could not do: the header carried a generation timestamp, so every run
    produced a diff and only the body could be checked. Dropping the timestamp
    made regeneration idempotent, and this assertion is what that bought.

    Regenerate with `uv run python scripts/dump-schema.py --sql-only`.
    """
    import subprocess

    from agent_spec.db.testing import ddl_header, render_ddl

    head, body = render_ddl()

    published = SPEC_SCHEMA / f"agent-service-{head}.sql"
    assert published.exists(), (
        f"no published DDL for Alembic head {head}: expected {published.name} in "
        "schema/. A new revision needs its own file -- regenerate "
        "with `uv run python scripts/dump-schema.py --sql-only`."
    )

    expected = ddl_header(head, "the Alembic revisions") + body
    assert published.read_text(encoding="utf-8") == expected, (
        f"{published.name} has drifted from what the migrations render. "
        "Regenerate it. (Regeneration is idempotent since Plan 9 step 1, so an "
        "unchanged schema produces a byte-identical file.)"
    )

    # `cwd` is the DDL's own directory, not this implementation's: since Plan 9
    # step 2 the file lives outside `impl/claude-python/`, and a repo-relative
    # pathspec resolved from here would name nothing.
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", published.name],
        cwd=SPEC_SCHEMA,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, (
        f"{published.name} exists but is NOT tracked by git, so a fresh clone does not "
        "have it. Nothing under schema/ is ignored -- check .gitignore."
    )


def test_every_published_ddl_names_a_real_revision() -> None:
    """A file in `schema/` whose name is not a revision in the tree.

    **This is the guard the build-version naming could not have**, and the one
    that makes the rename worth something: under the old scheme any string was a
    plausible filename, so thirteen files accumulated and nothing could say
    which of them described a schema that ever existed. Now the set of legal
    names IS the set of revisions, so a stale file, a typo, or a revision
    deleted from the tree while its DDL stayed behind all fail here.

    It also fails in the other direction on purpose: a revision with no
    published DDL is a revision a consumer was never handed, which is exactly
    the gap Plan 9 §1.1 found for the whole directory.
    """
    from alembic.script import ScriptDirectory

    from agent_spec.db.testing import alembic_config

    script = ScriptDirectory.from_config(alembic_config("postgresql://unused/unused"))
    revisions = {rev.revision for rev in script.walk_revisions()}

    # `-models` output is deliberately excluded: it is a diffing aid, not the
    # deployed schema, and `dump-schema.py` says so in its own header.
    published = {
        path.stem.removeprefix("agent-service-")
        for path in SPEC_SCHEMA.glob("agent-service-*.sql")
        if not path.stem.endswith("-models")
    }

    assert published == revisions, (
        f"schema/ and the migration tree disagree.\n"
        f"  published with no revision: {sorted(published - revisions) or 'none'}\n"
        f"  revisions with no published DDL: {sorted(revisions - published) or 'none'}"
    )
