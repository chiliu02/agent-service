"""plan-03 Task 7: resuming a conversation from the store.

SCOPE DISCIPLINE, restated because it is easy to lose. This resumes a
CONVERSATION on a new connection: `load()` runs once in the parent before the
subprocess spawns, the SDK materializes the entries to a temp JSONL file, and
the CLI resumes with its existing resume code.

It does NOT replay an in-flight SSE stream. A turn cut short by a disconnect is
not resumable, and reconnecting mid-turn is plan-06 Blocker 2 -- a semantic
change to whether a turn survives its consumer, not a storage feature. If a test
in this file starts reaching for frame replay, it has escaped its scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.config import Settings
from agent_service.options import build_options
from agent_spec.openapi.schemas import RunOptions

postgres = pytest.mark.postgres


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_dir=tmp_path / "ws", require_credentials=False)


def test_resume_reaches_the_sdk_untouched(settings: Settings) -> None:
    # This service never mints, rewrites or validates the id -- it is the SDK's
    # and only the CLI can interpret it.
    options, _ = build_options(RunOptions(resume="sdk-session-abc"), settings)
    assert options.resume == "sdk-session-abc"


def test_no_resume_is_the_default(settings: Settings) -> None:
    options, _ = build_options(RunOptions(), settings)
    assert options.resume is None


def test_the_load_call_is_bounded(settings: Settings) -> None:
    """`load()` runs inside `registry.create()`'s own 30s open timeout.

    A longer bound here could never fire -- the outer one would win first and
    report the wrong cause ("session.open() did not complete") for what is
    actually a slow database.
    """
    options, _ = build_options(RunOptions(resume="x"), settings)
    assert options.load_timeout_ms == settings.session_store_load_timeout_ms
    assert settings.session_store_load_timeout_ms <= 30_000


def test_an_empty_resume_id_is_rejected_rather_than_ignored() -> None:
    # Same reasoning as `model`: silently treating "" as omission would hand
    # the caller a FRESH conversation when they asked to continue one, with
    # nothing in the response saying so.
    with pytest.raises(ValueError):
        RunOptions(resume="")


@postgres
@pytest.mark.anyio
async def test_a_stored_transcript_is_what_resume_would_materialize(postgres_url: str) -> None:
    """The store half of resume, without spawning a CLI.

    What the SDK does with these entries -- write them to a temp JSONL and hand
    the path to the subprocess -- is the SDK's own resume code, exercised for
    real in Task 9. What this service owes it is that `load()` returns exactly
    what was appended, in order, for the key the SDK will ask for.
    """
    from agent_spec.db import Base, create_engine, create_sessionmaker
    from agent_service.db.session_store import PostgresSessionStore

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    store = PostgresSessionStore(create_sessionmaker(engine))
    key = {"project_key": "proj", "session_id": "sdk-1"}
    first = [{"type": "user", "uuid": "a", "text": "remember 41"}]
    second = [{"type": "assistant", "uuid": "b", "text": "ok"}]
    try:
        await store.append(key, first)
        await store.append(key, second)

        # A NEW adapter over a NEW pool -- the point of resume is that nothing
        # in the original process is still around.
        reborn = PostgresSessionStore(create_sessionmaker(engine))
        loaded = await reborn.load(key)
    finally:
        await engine.dispose()

    assert loaded == first + second


@postgres
@pytest.mark.anyio
async def test_an_unknown_session_does_not_prevent_a_fresh_conversation(
    postgres_url: str,
) -> None:
    """`load()` returning None must not be an error.

    Resume degrades to a new conversation, which is worse than continuity and
    far better than a `create()` that fails. A store that raised here would
    make an unknown id fatal.
    """
    from agent_spec.db import Base, create_engine, create_sessionmaker
    from agent_service.db.session_store import PostgresSessionStore

    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    store = PostgresSessionStore(create_sessionmaker(engine))
    try:
        assert await store.load({"project_key": "p", "session_id": "never-existed"}) is None
    finally:
        await engine.dispose()


async def test_a_slow_store_fails_the_resume_rather_than_starting_fresh(
    settings: Settings, tmp_path: Path
) -> None:
    """What a `load()` timeout ACTUALLY does. Read from the SDK, then executed.

    An earlier comment in `config.py` claimed a slow load "degrades to a fresh
    conversation". **That was wrong.** `_internal/session_resume.py`'s
    `materialize_resume_session` documents "Raises ``RuntimeError`` if a store
    call fails or times out", and `_with_timeout` re-raises `TimeoutError` as
    `RuntimeError` with context. So a slow store fails `open()`, which fails
    `registry.create()`, and the caller gets an error.

    That is arguably the RIGHT behaviour -- silently starting a fresh
    conversation when someone asked to continue one would lose context without
    saying so -- but it is the opposite of what was written, so it is corrected
    rather than quietly patched.

    This drives the SDK's own materialization directly: no subprocess, no
    credentials, no cost.
    """
    import uuid

    import pytest as _pytest
    from claude_agent_sdk._internal.session_resume import materialize_resume_session

    class SlowStore:
        """Never settles inside the bound."""

        async def append(self, key, entries) -> None:  # noqa: ANN001
            return None

        async def load(self, key):  # noqa: ANN001, ANN202
            import asyncio

            await asyncio.sleep(5)
            return [{"type": "user", "uuid": "u"}]

    # A REAL uuid: `materialize_resume_session` returns None early for anything
    # that is not one, which would make this pass without testing the bound.
    options, _ = build_options(RunOptions(resume=str(uuid.uuid4())), settings, SlowStore())
    object.__setattr__(options, "load_timeout_ms", 50)

    with _pytest.raises(RuntimeError) as caught:
        await materialize_resume_session(options)
    assert "timed out" in str(caught.value)
    assert "50ms" in str(caught.value)
