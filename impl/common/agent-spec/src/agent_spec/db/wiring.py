"""Assembles the persistence stack and owns its lifecycle.

`api.py` imports this module **only when `Settings.database_url` is set**, so a
service with no database never touches SQLAlchemy at all. That is not a
micro-optimisation: it is what keeps the no-database configuration a genuinely
separate path rather than one that merely happens to be unused, and there is a
test asserting `agent_service.db` is absent from `sys.modules` after building an
app without a URL.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from agent_spec.db.engine import create_engine, create_sessionmaker
from agent_spec.db.models import Session as SessionRow
from agent_spec.db.database import DatabaseRecorder
from agent_spec.db.writer import QueueWriter

log = logging.getLogger(__name__)

# How long the writer may spend draining at shutdown. Small on purpose: the
# queue drains in batches of 500, so a healthy database finishes in
# milliseconds, and a slow one is exactly the case where waiting is pointless.
# `config.shutdown_budget_s` (60s) is dominated by closing agent sessions, each
# of which is bounded by its own turn timeout; spending a meaningful slice of it
# on observability rows would trade an agent's clean exit for a log entry.
DRAIN_TIMEOUT_S = 5.0

# How long `usable()` may take. **Bounded because `/healthz` is the container's
# healthcheck** (`curl -fsS http://127.0.0.1:8000/healthz`, timeout 5s, 3
# retries). An unbounded probe against a database that hangs rather than
# refusing would hang `/healthz` with it, the healthcheck would fail, and
# compose would restart a service whose agent side is working perfectly --
# turning a database outage into a service outage, which is the exact inversion
# of "persistence is optional". 2s leaves headroom under the 5s.
HEALTH_PROBE_TIMEOUT_S = 2.0


class Persistence:
    """Engine, writer and recorder, constructed together and closed together."""

    def __init__(
        self,
        database_url: str,
        agent_id: str | None = None,
        *,
        session_store_factory: Callable[[Any, str | None], Any] | None = None,
    ) -> None:
        # `agent_id` is the container's `AGENT_ID`, resolved once at startup and
        # handed to both write paths here. Defaulted so every existing
        # construction site -- and every test -- keeps working unchanged; a
        # deployment without the variable is normal, not degraded.
        self._engine = create_engine(database_url)
        # Shared by the writer and the read routes. One pool: reads are rare
        # and small next to the write path, and a second pool would double the
        # connection count for no benefit.
        self.sessionmaker = create_sessionmaker(self._engine)
        self.writer = QueueWriter(self.sessionmaker)
        self.recorder = DatabaseRecorder(self.writer, agent_id)
        # A.2, sharing the same pool. Its writes are the SDK's, on the SDK's
        # schedule -- nothing here goes through the A.1 queue.
        #
        # **INJECTED, because A.2 is the one genuinely SDK-shaped part of
        # persistence.** `PostgresSessionStore` satisfies the Claude SDK's
        # `SessionStore` protocol so the CLI can resume from it; Codex has
        # thread items and no such seam, and passes nothing. A build without one
        # gets `None`, and every other write path is unaffected -- A.1 is what
        # `/v1/sessions/{sid}/transcript` reads and it is the platform's.
        self.session_store = (
            session_store_factory(self.sessionmaker, agent_id)
            if session_store_factory is not None
            else None
        )
        # Set for as long as the probe keeps failing, so a sustained outage
        # produces ONE warning and one recovery line rather than one per
        # healthcheck. Copied from `QueueWriter`'s `_warned`, which exists for
        # the same reason -- and needed more here, because the healthcheck polls
        # this route every 30s forever (every 1s inside `start_period`), so the
        # unthrottled version wrote a WARNING per poll for as long as the
        # database was down. Measured while verifying this feature.
        self._probe_failing = False

    async def verify_revision(self) -> None:
        """The schema-revision boot gate. See `db/revision.py`.

        Lives here rather than in `config.py` beside the credential and mount
        gates for one reason: those are pure checks on settings and this one
        needs a connection, so it cannot run before there is an engine.
        """
        from agent_spec.db.revision import verify_schema_revision

        await verify_schema_revision(self._engine)

    def start(self) -> None:
        """Start the drain task. Needs a running loop, so: lifespan, not init."""
        self.writer.start()

    async def usable(self) -> bool:
        """Can this service actually read and write its database, right now?

        **It queries a real table, not `SELECT 1`.** Three misconfigurations
        were driven against a container one at a time, and all three left the
        service booting healthy while every write was discarded (Q16's table):

        | Misconfiguration | What fails |
        |---|---|
        | Host unresolvable | connect -- `gaierror` |
        | Wrong password | connect -- `InvalidPasswordError` |
        | Schema never migrated | the QUERY -- `ProgrammingError` |

        `SELECT 1` catches the first two and passes the third, which is the one
        that is hardest to spot and the most likely: migrations do NOT run on
        startup and the image ships no `migrations/`, so an unmigrated schema is
        the default first state of any deployment that enables persistence.
        Touching `sessions` is what makes this probe answer the question a
        deployment actually has.

        **Never raises**, for the same reason `RunRecorder` never does: this is
        called from `/healthz`, and an endpoint whose job is to describe a
        failure must not become one.

        **Reports a boolean, and the reason goes to the log.** Not squeamishness
        -- `/healthz` is unauthenticated, and Q16 decided that which of an
        operator's database mistakes is in force is not something an anonymous
        caller is told. The WARNING carries the exception CLASS NAME only, the
        same line `api.py` and `errors.py` already draw.
        """
        try:
            async with asyncio.timeout(HEALTH_PROBE_TIMEOUT_S):
                async with self.sessionmaker() as db:
                    await db.execute(select(SessionRow.id).limit(1))
        except Exception as exc:  # noqa: BLE001 - a probe that raises is a bug
            if not self._probe_failing:
                self._probe_failing = True
                log.warning(
                    "database probe failed (%s); /healthz now reports "
                    "database_usable=false. Rows are being DISCARDED -- see the "
                    "writer's own ERROR lines for the batches. Logged once per "
                    "outage, not once per healthcheck",
                    type(exc).__name__,
                )
            return False
        if self._probe_failing:
            self._probe_failing = False
            log.info("database probe recovered; /healthz reports database_usable=true")
        return True

    async def aclose(self) -> None:
        """Drain, then dispose. ORDER IS LOAD-BEARING.

        The writer must finish with the pool before the engine disposes of it,
        or the final batch -- which contains the `session_closed` rows that
        `close_all()` just produced -- fails against a closed pool and the last
        thing every session did goes unrecorded.
        """
        await self.writer.aclose(timeout_s=DRAIN_TIMEOUT_S)
        await self._engine.dispose()
        stats = self.writer.stats
        log.info(
            "persistence: wrote %d, dropped %d stream_event + %d other, %d failed batches",
            stats.written,
            stats.dropped_stream_events,
            stats.dropped_over_hard_cap,
            stats.failed_batches,
        )
