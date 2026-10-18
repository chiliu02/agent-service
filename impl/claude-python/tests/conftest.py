import dataclasses
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_spec.db.outcome import RunOutcome
from agent_service.runner import Run
from agent_spec.openapi.schemas import QueryRequest
from agent_service.sessions import TurnResult
from agent_spec.db import testing as dbharness


# -- Postgres -----------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _not_a_container() -> Iterator[None]:
    """The suite is not a container, so the mount guard must be off.

    `Settings.require_mounts` defaults **True** (Q14, user decision): the
    deployment that most needs the check is the one least likely to remember a
    flag, so the container gets it free and everything else opts out. A test
    run is "everything else" -- `tmp_path` workspaces are ordinary directories,
    never mount points, so with the guard on every test that drives the
    lifespan refuses to boot.

    Set as an ENVIRONMENT VARIABLE rather than a `Settings` kwarg because
    fourteen test modules construct their own `Settings(...)`, and a fixture
    default would only reach the ones using the shared fixture below. Explicit
    kwargs still win over the environment, so `test_config.py`'s
    `Settings(require_mounts=True)` cases are unaffected -- which is what keeps
    the guard itself covered.
    """
    import os

    previous = os.environ.get("AGENT_SERVICE_REQUIRE_MOUNTS")
    os.environ["AGENT_SERVICE_REQUIRE_MOUNTS"] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENT_SERVICE_REQUIRE_MOUNTS", None)
        else:
            os.environ["AGENT_SERVICE_REQUIRE_MOUNTS"] = previous


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[dbharness.Postgres]:
    """A Postgres, from an env var or from testcontainers. See `dbharness`.

    SESSION scoped, so at most one container starts per run and only if some
    test actually asks for it -- an offline suite never touches Docker.

    Deliberately SYNC. `pytest-asyncio`'s `asyncio_mode = auto` gives each test
    its own event loop, and a session-scoped ASYNC fixture would be bound to
    whichever loop happened to create it. A plain string has no such problem,
    which is why every consumer builds its own engine from the URL rather than
    sharing one from here.

    Isolation between tests is still each test's own `drop_all`/`create_all`, as
    it was when this was a hand-run throwaway server. One server, one schema, so
    these tests are NOT safe to run in parallel across processes.
    """
    with dbharness.acquire() as pg:
        print(f"\n[postgres] {pg.source} -> {pg.url.rsplit('@', 1)[-1]}")
        yield pg


@pytest.fixture(scope="session")
def postgres_url(postgres_server: dbharness.Postgres) -> str:
    """The URL alone -- what almost every Postgres-backed test actually wants."""
    return postgres_server.url


class FakeRun(Run):
    """A Run that replays canned events without touching the SDK."""

    def __init__(self, events: list[dict], outcome: RunOutcome | None) -> None:
        self._events = events
        self._outcome = outcome
        self.session_id = outcome.session_id if outcome else None
        self.outcome = None

    async def events(self) -> AsyncIterator[dict]:  # type: ignore[override]
        for event in self._events:
            yield event
        self.outcome = self._outcome


DEFAULT_EVENTS = [
    {"seq": 1, "type": "system", "subtype": "init", "content": None},
    {
        "seq": 2,
        "type": "assistant",
        "subtype": None,
        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
    },
    {"seq": 3, "type": "result", "subtype": "success", "content": None},
]

DEFAULT_OUTCOME = RunOutcome(
    session_id="sess-test",
    result="done",
    is_error=False,
    subtype="success",
    terminal_reason="completed",
    num_turns=2,
    total_cost_usd=0.09,
    duration_ms=123,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings. Note `require_credentials=False`.

    Follow-up item 8 makes the lifespan REFUSE TO BOOT without an Anthropic
    credential, and several tests here drive that lifespan for real -- the
    reaper/close_all test directly, and every `_running_server` test through
    uvicorn. None of them has credentials, nor should they: the whole suite is
    offline and the agent layer is faked.

    Set HERE rather than by monkeypatching `credentials_configured` globally,
    so "these tests deliberately boot without credentials" is visible at the
    fixture instead of hidden in a conftest-level patch. It also keeps the
    tests independent of whether the developer running them happens to have a
    real key exported. The refusal itself is exercised in test_config.py,
    which builds its own `Settings(require_credentials=True)`.
    """
    return Settings(workspace_dir=tmp_path / "ws", require_credentials=False)


@pytest.fixture
def fake_factory():
    """Returns (factory, state). Mutate state to change what the run yields."""
    state = {
        "events": list(DEFAULT_EVENTS),
        "outcome": dataclasses.replace(DEFAULT_OUTCOME),
        "raise": None,
    }

    def factory(req: QueryRequest, settings: Settings) -> Run:
        if state["raise"] is not None:
            raise state["raise"]
        return FakeRun(state["events"], state["outcome"])

    return factory, state


@pytest.fixture
async def client(settings: Settings, fake_factory) -> AsyncIterator[AsyncClient]:
    factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class FakeSession:
    """A session that replays canned events, for HTTP-level tests."""

    def __init__(self, events=None, turn=None, title=None) -> None:
        self._events = events if events is not None else list(DEFAULT_EVENTS)
        self._turn = turn
        self.title = title
        self.session_id = "sdk-sess-1"
        self.status = "idle"
        self.created_at = 1000.0
        self.last_used_at = 1000.0
        self.turns = 1
        self.total_cost_usd = 0.09
        self.last_turn = None
        # Follow-up item 12: the count the last turn's pre-drain discarded.
        # Mirrors AgentSession's own attribute, which `_record` reports.
        self.last_residue_discarded = 0
        self.raise_on_send = None
        self.raise_on_close = None
        self.interrupted = 0
        # What `interrupt()` reports back: whether a control request actually
        # went out. Mirrors `AgentSession.interrupt()`'s return value, which is
        # the only honest source for the interrupt endpoint's response body --
        # `status` cannot tell an abandoned-turn interrupt (which fires, on an
        # "idle" session) from a no-op (which does not).
        self.interrupt_fires = True
        self.model = None
        self.permission_mode = None
        # Call COUNTS, not just the resulting value. `model`/`permission_mode`
        # start as None, which is also what an unguarded `PATCH {}` would push
        # at the SDK -- so the values alone cannot tell "never called" from
        # "called with None", and a test asserting only on them passes with
        # api.py's `is not None` guards deleted. Those guards are load-bearing:
        # `set_model(None)` means "use the default" to the real SDK, so an
        # unguarded empty PATCH would silently RESET the session's model.
        self.set_model_calls = 0
        self.set_permission_mode_calls = 0
        self.closed = False

    async def open(self) -> None: ...

    async def close(self) -> None:
        if self.raise_on_close is not None:
            raise self.raise_on_close
        self.closed = True

    @property
    def idle_seconds(self) -> float:
        return 0.0

    async def send(self, prompt):  # noqa: ANN001
        if self.raise_on_send is not None:
            raise self.raise_on_send
        for event in self._events:
            yield event
        self.last_turn = self._turn or TurnResult(
            session_id="sdk-sess-1", outcome=DEFAULT_OUTCOME, interrupted=False
        )

    async def interrupt(self) -> bool:
        self.interrupted += 1
        return self.interrupt_fires

    async def set_model(self, model) -> None:  # noqa: ANN001
        self.set_model_calls += 1
        self.model = model

    async def set_permission_mode(self, mode) -> None:  # noqa: ANN001
        self.set_permission_mode_calls += 1
        self.permission_mode = mode

    async def context_usage(self):
        return {"categories": [{"name": "Messages", "tokens": 7}]}


@pytest.fixture
def fake_registry(settings):
    """A real SessionRegistry wired to FakeSession -- exercises registry logic
    (cap, reaping, lookup) without a subprocess."""
    from agent_service.registry import SessionRegistry

    made: list[FakeSession] = []

    def factory(options, settings_, title=None):  # noqa: ANN001, ARG001
        s = FakeSession(title=title)
        made.append(s)
        return s

    registry = SessionRegistry(settings, session_factory=factory)
    registry.made = made  # type: ignore[attr-defined]
    return registry


@pytest.fixture
async def session_client(settings, fake_factory, fake_registry):
    factory, _ = fake_factory
    app = create_app(settings=settings, run_factory=factory, registry=fake_registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
