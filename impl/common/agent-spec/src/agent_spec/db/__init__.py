"""The database half of the specification — the schema, and what conforms to it.

AS-30 makes the published DDL the specification's, exactly as AS-24 makes the
OpenAPI document the specification's. `agent_spec.openapi` generates one;
this package conforms to the other.

**Requires the `db` extra.** A build that persists depends on `agent-spec[db]`;
one that does not takes plain `agent-spec` and never imports anything here.

## Nothing is imported eagerly, and a test would have caught it if it were

The names below resolve through `__getattr__` (PEP 562) rather than through
top-level imports. That is not a style choice:

**`agent_service` must not import SQLAlchemy when no database is configured.**
plan-03's global constraint, pinned by a FRESH-INTERPRETER test --
`test_no_database_url_imports_no_database_code` -- because an in-process
`sys.modules` check passes regardless once any other test has imported it.

Eager re-exports here broke it the moment the seam moved into this package:
`agent_service.sessions` imports `RunOutcome` from `agent_spec.db.outcome`, and
importing any submodule runs this file, which imported `engine` and `models`,
which import SQLAlchemy. **The service pulled a database driver into every
no-database deployment by importing a dataclass.** The test found it within
minutes of the move; it is exactly the failure that test exists for.

So: `from agent_spec.db import create_engine` still works and still costs
SQLAlchemy, because it asks for it. `from agent_spec.db.outcome import
RunOutcome` costs nothing, because it asks for nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers only, never at runtime
    from agent_spec.db.engine import (
        InvalidDatabaseUrl,
        create_engine,
        create_sessionmaker,
        normalize_url,
    )
    from agent_spec.db.models import Base, Event, Run, Session, TranscriptEntry

#: name -> the submodule it lives in. Consulted by `__getattr__` below.
_LAZY: dict[str, str] = {
    "InvalidDatabaseUrl": "engine",
    "create_engine": "engine",
    "create_sessionmaker": "engine",
    "normalize_url": "engine",
    "Base": "models",
    "Event": "models",
    "Run": "models",
    "Session": "models",
    "TranscriptEntry": "models",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Import the submodule only when one of its names is actually asked for."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f"{__name__}.{module}"), name)
