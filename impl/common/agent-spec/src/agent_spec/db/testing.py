"""Getting a Postgres for the tests that need one.

Two routes, tried in this order:

1. **`AGENT_SERVICE_TEST_DATABASE_URL`** -- a server that is already running.
   Fastest, reuses whatever the developer already has up, and the only route
   that works when no Docker daemon is reachable from the test process.
2. **testcontainers** -- start `postgres:17-alpine`, once per session, and throw
   it away at the end.

Only when BOTH are unavailable do the Postgres-backed tests skip.

**This ordering is a correction, not a convenience.** plan-03 Task 2 decided
these tests should "run automatically wherever a container exists" and then
gated them on an environment variable -- so on a machine with Docker running and
no variable exported, seven files' worth of coverage skipped silently and the run
still reported green. Route 2 is what makes the original decision true.

`IMAGE` is deliberately the SAME tag `compose.yaml` runs. A second pin here
would let the suite pass against a Postgres version the deployment never uses.

## Read from the installed testcontainers 4.15.0, not assumed

- `PostgresContainer._connect()` waits by exec'ing `psql` **inside** the
  container (`ExecWaitStrategy`). Readiness therefore needs no host-side driver,
  which is why this works with only `asyncpg` installed and no `psycopg2`.
- The constructor's `driver` default is `"psycopg2"`, and it lands in the URL
  `get_connection_url()` returns. `driver=None` is what yields a plain
  `postgresql://`, which `normalize_url` then upgrades to asyncpg.
- `username`/`password`/`dbname` fall back to `POSTGRES_USER`/
  `POSTGRES_PASSWORD`/`POSTGRES_DB` **from the ambient environment** when not
  passed. Those are exactly the variables `compose.yaml`'s persistence profile
  asks a developer to export, so leaving them implicit would let a shell
  variable meant for compose silently change the test container's credentials.
  Passed explicitly for that reason.

The credentials match compose's (`postgres` / database `agent`) for one concrete
reason: `test_live_persistence.py`'s outage test probes with a hardcoded
`pg_isready -U postgres -d agent`, and that has to keep working against a
container this harness started.

`db/init/01-roles.sql` is deliberately NOT mounted. Nothing here needs the
role split, and its `ALTER SCHEMA public OWNER` would be a failure surface for
no test benefit; tests connect as the superuser, as they already did against a
hand-run throwaway server.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
from collections.abc import Iterator

import pytest

ENV_URL = "AGENT_SERVICE_TEST_DATABASE_URL"
ENV_CONTAINER = "AGENT_SERVICE_TEST_PG_CONTAINER"

IMAGE = "postgres:17-alpine"
USERNAME = "postgres"
PASSWORD = "postgres"
DBNAME = "agent"


@dataclasses.dataclass(frozen=True)
class Postgres:
    """A server the tests may drop and recreate the schema in at will."""

    url: str

    #: Docker container name, for the one live test that stops and restarts the
    #: server mid-turn. `None` means an external URL was supplied without
    #: naming its container, and that test alone has to skip.
    container: str | None

    #: Where it came from, for `-v` output. Worth reporting: "skipped" and
    #: "ran against a container you did not notice starting" are both surprises
    #: if the run does not say which happened.
    source: str


@contextlib.contextmanager
def acquire() -> Iterator[Postgres]:
    """Yield a Postgres, or `pytest.skip` if neither route is available."""
    url = os.environ.get(ENV_URL)
    if url:
        yield Postgres(
            url=url,
            container=os.environ.get(ENV_CONTAINER),
            source=f"${ENV_URL}",
        )
        return

    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover - a dev dependency is missing
        pytest.skip(f"no ${ENV_URL} and testcontainers is not importable ({exc}); run `uv sync`")

    container = None
    try:
        # CONSTRUCTION IS INSIDE THE TRY, and that is not defensive padding:
        # `DockerContainer.__init__` builds a `DockerClient`, which talks to the
        # daemon. With no daemon reachable the constructor itself raises, so a
        # try that wrapped only `start()` let a `NewConnectionError` out and
        # ERRORED every Postgres test instead of skipping it. Measured, by
        # pointing DOCKER_HOST at a closed port.
        container = PostgresContainer(
            IMAGE,
            username=USERNAME,
            password=PASSWORD,
            dbname=DBNAME,
            driver=None,
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - no daemon, no image, no reaper; all the same answer
        # `start()` can also fail AFTER the container is up, by timing out on the
        # readiness wait. Stop it here rather than leaving it for the reaper,
        # which only collects after its reconnection timeout and is itself
        # optional.
        if container is not None:
            with contextlib.suppress(Exception):
                container.stop()
        # A SKIP and not an error. A checkout with no Docker must still get a
        # green run: persistence is optional by decision, and a test harness
        # that makes Docker mandatory quietly reverses that decision.
        # Truncated: a `DockerException` wraps the whole urllib3 retry chain, and
        # the useful part -- "the daemon is not reachable" -- is at the front.
        detail = " ".join(str(exc).split())[:140]
        pytest.skip(f"no ${ENV_URL} and no usable Docker ({type(exc).__name__}: {detail})")

    try:
        yield Postgres(
            url=container.get_connection_url(),
            container=container.get_wrapped_container().name,
            source=f"testcontainers {IMAGE}",
        )
    finally:
        container.stop()


# --- the shared migration tree, for tests that need a migrated database ------
#
# Here rather than in a test file because BOTH this package's tests and every
# implementation's need it: `test_migrations.py` migrates a throwaway database,
# and each build's `test_schema_gate.py` needs a really-migrated one to prove
# its baked `EXPECTED_REVISION` matches what Alembic produces. When these lived
# in one implementation's `tests/`, the other had to import across packages --
# which is not importable, and is how `test_schema_gate` broke the moment the
# shared tests moved.

from pathlib import Path as _Path

#: `impl/common/db/` -- the Alembic tree, which belongs to no implementation
#: (Plan 9 step 2). Resolved from this file: `src/agent_spec/db/testing.py` ->
#: up four to `impl/common/agent-spec/`, then across to `db/`.
ALEMBIC = _Path(__file__).resolve().parents[3].parent / "db"


def alembic_config(url: str):  # noqa: ANN201
    """An Alembic `Config` pointed at the shared tree and a throwaway database."""
    import argparse

    from alembic.config import Config

    cfg = Config(str(ALEMBIC / "alembic.ini"))
    # The CLI's `-x url=...`, by hand: `env.py` reads `config.cmd_opts.x`, which
    # the CLI populates and which is None for a Config built in code.
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    # `env.py` honours this. Without it, `fileConfig` reconfigures logging for
    # the rest of the pytest process and silences every logger already created.
    cfg.attributes["configure_logger"] = False
    return cfg


async def run_alembic(url: str, *stops: str) -> None:
    """Run `upgrade`/`downgrade` off the event loop. `base` means downgrade.

    Off the loop because `command.upgrade` is synchronous and `env.py` calls
    `asyncio.run` -- calling it directly from a running loop raises.
    """
    import asyncio

    from alembic import command

    cfg = alembic_config(url)
    for stop in stops:
        action = command.downgrade if stop == "base" else command.upgrade
        await asyncio.to_thread(action, cfg, stop)


def render_ddl(target: str = "head") -> tuple[str, str]:
    """`(revision, SQL)` a deployment would apply, rendered from base, offline.

    **Here rather than in an implementation's `scripts/`** because what it
    renders is the SPECIFICATION's artifact (AS-30):
    `schema/agent-service-<revision>.sql`. `dump-schema.py` writes the
    file and this produces its contents; a test that checks the published DDL
    against the migrations must not have to reach into one implementation to do
    it.

    `target` names a revision to stop at, so a file for a revision that is no
    longer the head stays reproducible.
    """
    import io

    from alembic import command
    from alembic.script import ScriptDirectory

    cfg = alembic_config("postgresql://unused/unused")  # never connected to
    script = ScriptDirectory.from_config(cfg)
    revision = (
        script.get_current_head() or "unknown"
        if target == "head"
        else script.get_revision(target).revision
    )
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, target, sql=True)
    return revision, buffer.getvalue()


def ddl_header(revision: str, source: str, extra: str = "") -> str:
    """The two-line preamble. **Deterministic** -- no timestamp, no build
    version -- which is what makes regeneration idempotent and therefore what
    lets `freeze` compare a published DDL file at all."""
    lines = [
        f"-- agent-service -- PostgreSQL schema at Alembic revision {revision}",
        f"-- Generated by scripts/dump-schema.py from {source}.",
    ]
    if extra:
        lines.append(f"-- {extra}")
    lines.append("-- Do not edit; regenerate.")
    return "\n".join(lines) + "\n\n"
