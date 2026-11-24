"""The schema-revision boot gate (0.10.0), and the connection gate around it
(0.13.0).

Refuse to start when persistence is configured and the revision this image
expects is not the revision the database is at -- **in either direction**.
Asked for by Agent Studio, and their clauses were adopted verbatim.

**Two failures, two messages**, because they are two different operator
problems: `SchemaRevisionMismatch` means the database answered and disagreed;
`DatabaseUnreachable` means it never answered. Both exit 3.

## Why a constant and not a lookup

**The image ships no migration tree.** Measured by listing `/app` inside the
published image: `pyproject.toml`, `uv.lock`, `README.md`, `src/`, and nothing
else. That is the same fact that makes migration out-of-band -- the container is
deliberately not allowed to migrate -- so there is no Alembic head to read at
runtime and the expectation has to be baked in.

`EXPECTED_REVISION` is therefore only as true as the test that pins it against
the head in the source tree, which makes that test part of the feature rather
than a check on it. See `tests/test_schema_gate.py`.

## Why this does not contradict Q16 or 0.6.0

Both declined a boot gate on the database, and both stand, because:

> **Refuse at boot what should never have started; report at runtime what may
> recover.**

This gate is boot-only. It never stops a running service, never restarts one,
and changes nothing about `/healthz` -- a database that breaks or recovers while
the service is up is still reported through `database_usable` and still takes
nothing down. What it refuses is a container starting against a schema it was
not built for, which is a statement about the pairing rather than about the
database's health.

Note the two directions do NOT have the same justification, and the reply to
Studio's ask overstated this in one line:

* **Image behind the database** -- the real one. Such a container *succeeds* and
  writes rows missing a column the fleet relies on; nothing raises, and it is
  permanent. Not recoverable by anything except a different container.
* **Image ahead of the database** -- a convenience. It *is* recoverable, by
  migrating while the service runs, and it fails loudly on first use either way.
  Studio asked for it and says as much; it is worth having so an operator learns
  at boot rather than at the first history write.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_spec.db.revision_id import EXPECTED_REVISION as _EXPECTED_REVISION

#: The Alembic head this image was built against, re-exported from the leaf
#: module that holds it so that importing THIS module -- which pulls
#: SQLAlchemy -- is never the price of reading the value. The pre-boot
#: specification publishes it and must not import a database stack; see
#: `revision_id.py` for why the split exists and what it protects.
#:
#: **BUMP IT IN `revision_id.py`**, which is the one definition.
EXPECTED_REVISION = _EXPECTED_REVISION


class SchemaRevisionMismatch(RuntimeError):
    """The database is not at the revision this image was built for.

    Raised from the lifespan, so uvicorn turns it into
    `sys.exit(STARTUP_FAILURE)` -- exit 3, the same code the credential and
    mount gates produce, which a container orchestrator can distinguish from a
    crash.
    """

    def __init__(self, expected: str, actual: str | None) -> None:
        found = actual if actual is not None else "no revision at all"
        remedy = (
            "run `alembic upgrade head` against it"
            if actual is None
            else "migrate the database, or start the image that matches it"
        )
        super().__init__(
            f"schema revision mismatch: this image expects {expected}, the "
            f"database is at {found}. Refusing to start rather than read and "
            f"write a schema it was not built for -- {remedy}. Unset "
            f"AGENT_SERVICE_DATABASE_URL to run without persistence."
        )
        self.expected = expected
        self.actual = actual


async def current_revision(engine: AsyncEngine) -> str | None:
    """The database's Alembic revision, or `None` if it has never been migrated.

    `None` covers both "no `alembic_version` table" and "the table is empty",
    because they mean the same thing to an operator and neither is worth its own
    message. `to_regclass` answers without raising, so a missing table is a
    value rather than an exception to catch and re-interpret.
    """
    async with engine.connect() as conn:
        present = await conn.scalar(text("SELECT to_regclass('alembic_version')"))
        if present is None:
            return None
        return await conn.scalar(text("SELECT version_num FROM alembic_version"))


class DatabaseUnreachable(RuntimeError):
    """The gate could not reach the database to read its revision at all.

    A SEPARATE FAILURE FROM `SchemaRevisionMismatch`, and the distinction is the
    operator's: a mismatch means the database answered and disagreed, this means
    it never answered. Both exit 3 from the lifespan, because a container that
    cannot reach its configured database is a container that would discard every
    row it was asked to persist.

    WHY THIS CLASS EXISTS (0.13.0). Before it, the driver's own exception
    propagated out of the lifespan untouched, and Agent Studio -- about to make
    every container in a fleet depend on one connection string -- would have met
    a bare `socket.gaierror: [Errno -3] Temporary failure in name resolution` as
    the last line before `Application startup failed`. The exit code was already
    right; nothing said which host, or which variable to look at. Reported to
    them to Agent Studio as a defect of this
    side rather than left to be discovered.

    NO CREDENTIAL REACHES THE MESSAGE, and the URL is never rendered. Four
    fields are read off it by name -- host, port, database, username -- so the
    password is not redacted so much as never touched, which is the version of
    this that cannot regress when someone adds a field.
    `config.get_settings` deliberately pops the connection string out of the
    environment so the agent cannot read it; a boot log that printed it back
    would undo that in one line.

    The username IS included. It is not a secret, it is the single most common
    cause of a rejected connection, and an operator staring at
    `InvalidPasswordError` needs to know which role was tried.
    """

    def __init__(self, engine: AsyncEngine, cause: BaseException) -> None:
        url = engine.url
        where = f"{url.host or '<no host>'}:{url.port or 5432}"
        super().__init__(
            f"cannot reach the database at {where} (database "
            f"{url.database or '<unset>'}, user {url.username or '<unset>'}), "
            f"so this service refuses to start: {type(cause).__name__}. "
            "It was configured by AGENT_SERVICE_DATABASE_URL, so check that "
            "the host resolves and is routable from inside this container, "
            "that the port is right, and that the credentials are accepted. "
            "Unset AGENT_SERVICE_DATABASE_URL to run without persistence, "
            "which is a supported configuration -- the service then records no "
            "history and boots with no database at all."
        )
        self.target = where


async def verify_schema_revision(engine: AsyncEngine) -> None:
    """Raise unless the database is reachable AND matches this image.

    Called from the lifespan ONLY when a database is configured. With
    persistence off there is nothing to compare and nothing is checked, which is
    Studio's acceptance clause 4 and is why this is not in `config.py` beside
    the other two gates: those need no I/O.

    THE `try` COVERS THE CONNECTION, NOT THE COMPARISON. `current_revision` is
    the only call inside it, so a `SchemaRevisionMismatch` raised below can
    never be caught and re-labelled as unreachability -- the two messages stay
    the two different things they describe.

    `except Exception` and not a driver-specific tuple, deliberately. The
    failures measured here span layers -- `socket.gaierror` from DNS escapes
    unwrapped, while a refused connection or a rejected password arrives as a
    SQLAlchemy `OperationalError` -- and a narrow catch would let exactly the
    unwrapped one through, which is the case that produced the defect. Anything
    that stops this reading the revision is reported the same way, and the
    original is chained with `from`, so the driver's own traceback is still
    printed above the message rather than swallowed.
    """
    try:
        actual = await current_revision(engine)
    except Exception as exc:  # noqa: BLE001 - re-raised, never swallowed
        raise DatabaseUnreachable(engine, exc) from exc
    if actual != EXPECTED_REVISION:
        raise SchemaRevisionMismatch(EXPECTED_REVISION, actual)
