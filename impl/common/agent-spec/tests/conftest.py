"""Fixtures for the shared persistence layer's own tests.

**This package has tests because it has code**, and since 2026-08-08 that code
is the database half of the specification: the ORM that conforms to the
published DDL, the queue that carries a turn to it, and the repository that
writes it. Those tests moved here with the modules they exercise -- a shared
layer whose tests live in one implementation is a layer only that
implementation is keeping honest.

**What did NOT move**, and the line is the same one the modules follow:
`test_recorder.py` drives an `AgentSession` with a fake Claude client, so it
asserts that *one build* calls the seam correctly rather than that the seam
works. It stays in `impl/claude-python/tests/`.

The Postgres harness is `agent_spec.db.testing`, inside the package rather than
beside these tests, because both this package and every implementation's suite
need it -- and a harness copied into two test trees is two harnesses.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_spec.db import testing as dbharness


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[dbharness.Postgres]:
    """A Postgres, from an env var or from testcontainers. See `dbharness`."""
    with dbharness.acquire() as pg:
        yield pg


@pytest.fixture(scope="session")
def postgres_url(postgres_server: dbharness.Postgres) -> str:
    return postgres_server.url
