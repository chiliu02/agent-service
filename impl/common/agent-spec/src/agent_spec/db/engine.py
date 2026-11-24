"""Async engine and session factory.

Construction only. Nothing here reads or writes rows -- `repository.py` (Task 3)
is the sole A.1 write path -- and nothing here is wired into the app lifespan
yet, which is Task 4.

The service must run with no database at all, so this module is imported only
when `Settings.database_url` is set. Keep it free of import-time side effects so
that stays cheap.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# The driver this service is built and tested against. The persistence design
# picks asyncpg; a `postgresql://` URL would silently select psycopg2 and then
# fail at first use inside the event loop, which is a confusing way to find out.
_ASYNC_SCHEME = "postgresql+asyncpg://"


class InvalidDatabaseUrl(ValueError):
    """The configured URL is not one this service can use."""


def normalize_url(url: str) -> str:
    """Accept the URL people actually write, reject the ones that cannot work.

    `postgresql://` and `postgres://` are upgraded to the asyncpg driver rather
    than rejected: they are what every Postgres tool, connection string in a
    password manager, and cloud console hands you, and silently getting a sync
    driver inside an async service is a worse outcome than a rewrite.
    """
    if url.startswith(_ASYNC_SCHEME):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return _ASYNC_SCHEME + url[len(prefix) :]
    raise InvalidDatabaseUrl(
        f"expected a postgresql:// or {_ASYNC_SCHEME} URL, got {url.split('://')[0]}://"
    )


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """One engine per process.

    `pool_pre_ping` is on deliberately. This service holds sessions open for as
    long as an agent conversation lasts, so a pooled connection can easily sit
    idle past a server-side or firewall idle cut; without pre-ping the first
    query after that returns a stale-connection error to whatever unlucky
    request picked it up.
    """
    return create_async_engine(normalize_url(url), echo=echo, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """`expire_on_commit=False` so committed objects stay readable.

    The default expires every attribute at commit, so touching one afterwards
    triggers a lazy refresh -- an implicit IO round trip, which in this codebase
    would be an await appearing somewhere the recorder specification says there is
    none.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
