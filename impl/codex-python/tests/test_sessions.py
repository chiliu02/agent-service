"""`CodexSession` against a REAL app-server.

**These start a real `codex app-server` subprocess and cost nothing.** The
measurement that makes them possible: the app-server connects and creates a
thread *without a credential* -- `account=None, requires_openai_auth=True` --
so everything up to actually taking a turn is testable for free.

**A turn is not**, and there is no fake here pretending otherwise. What needs a
credential is marked `live` and deselected by default, exactly as the Claude
build marks the tests that spend money.

Each test gets its own `CODEX_HOME` in a tmp dir, so nothing touches the
developer's real one and the 65 files the app-server writes on first start go
somewhere disposable.
"""

from __future__ import annotations

import asyncio

import pytest
from agent_spec.openapi.schemas import RunOptions

from agent_service.sessions import CodexSession, RunTimeout, TurnOutcome

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session(tmp_path):  # noqa: ANN201
    """An open session with a disposable CODEX_HOME and workspace."""
    # Neither directory is created here on purpose: CodexSession makes both,
    # and a test that pre-creates them would not notice if it stopped.
    s = CodexSession(
        cwd=str(tmp_path / "ws"),
        codex_home=str(tmp_path / "codexhome"),
    )
    await s.open(RunOptions())
    try:
        yield s
    finally:
        await s.close()


# --- what works without a credential ----------------------------------------


async def test_opening_a_session_yields_a_thread_id(session) -> None:  # noqa: ANN001
    """`sdk_session_id` is known AT CREATION here, unlike the Claude build where
    it arrives with the first turn's init message.

    That is a real difference in this implementation's favour: the specification
    lets `sdk_session_id` be null on a fresh session, and this build never needs
    to use that allowance.
    """
    assert session.sdk_session_id
    assert len(session.sdk_session_id) == 36, "expected a UUID"


async def test_interrupt_with_no_running_turn_is_false_not_an_error(session) -> None:  # noqa: ANN001
    """`POST /v1/sessions/{sid}/interrupt` on an idle session is a legitimate
    request, not a fault -- the caller cannot know whether the turn finished
    between its two calls."""
    assert await session.interrupt() is False


async def test_close_is_idempotent(session) -> None:  # noqa: ANN001
    """The lifespan's shutdown sweep and an explicit DELETE can both reach a
    session; the second must not raise."""
    await session.close()
    await session.close()


async def test_codex_home_is_honoured(tmp_path) -> None:  # noqa: ANN001
    """The lever Gemini lacks, asserted rather than assumed: state must land in
    the directory we chose, because that is what lets a container mount it and
    keep threads across a restart."""
    home = tmp_path / "chosen-home"
    s = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(home))
    assert home.is_dir(), "CODEX_HOME was not created at construction"
    await s.open(RunOptions())
    try:
        assert any(home.rglob("*.sqlite")), "no app-server state under CODEX_HOME"
    finally:
        await s.close()


async def test_resuming_a_thread_with_no_turns_raises_rather_than_starting_fresh(
    session,  # noqa: ANN001
    tmp_path,
) -> None:
    """**Measured semantics, pinned.** A thread that has taken no turn has no
    rollout, and Codex refuses to resume it.

    The error is deliberately allowed to propagate: a caller that asked to
    continue a conversation must not silently be given a new one. The Claude
    build states the same rule -- a slow store fails the resume rather than
    starting fresh.
    """
    orphan = session.sdk_session_id
    second = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(tmp_path / "codexhome"))
    with pytest.raises(Exception) as excinfo:
        await second.open(RunOptions(), resume=orphan)
    await second.close()
    assert "rollout" in str(excinfo.value).lower()


# --- authentication ---------------------------------------------------------
#
# **All free.** `login_api_key()` is a LOCAL write -- it stores the key in
# `CODEX_HOME/auth.json` and validates nothing -- so a fake key exercises the
# whole path this build depends on without a network call or a cent spent.


async def test_a_session_logs_the_app_server_in(tmp_path) -> None:  # noqa: ANN001
    """**The bug this build shipped with, pinned.**

    Measured 2026-08-08: the app-server reads neither `OPENAI_API_KEY` nor
    `CODEX_API_KEY`, even with both exported into its process. Until `open()`
    called `login_api_key()`, every turn went out with no `Authorization` header
    and came back `401 Missing bearer or basic authentication in header` -- an
    error that reads as a bad key and is not one.

    Deleting the login from `open()` fails here, for free, instead of at a live
    turn that costs money to discover.
    """
    s = CodexSession(
        cwd=str(tmp_path / "ws"),
        codex_home=str(tmp_path / "home"),
        api_key="sk-not-a-real-key",
    )
    await s.open(RunOptions())
    try:
        account = await s._codex.account()
        assert account.account is not None, "open() did not authenticate the app-server"
    finally:
        await s.close()
    assert (tmp_path / "home" / "auth.json").exists(), "no auth store was written"


async def test_no_credential_leaves_the_app_server_unauthenticated(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """The control for the test above -- without it, that one would pass against
    an app-server that authenticated itself somehow and prove nothing.

    Also the measurement `test_sessions.py`'s docstring rests on: a session
    opens, and a thread is created, with no credential at all.
    """
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(tmp_path / "home"))
    await s.open(RunOptions())
    try:
        assert (await s._codex.account()).account is None
        assert s.sdk_session_id, "a thread must still be creatable without a credential"
    finally:
        await s.close()


async def test_the_key_is_read_from_the_environment_when_not_passed(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Production passes no key -- it comes from `config.api_key()`, which is
    what the boot gate checked. A session that read only its constructor
    argument would boot past the gate and then authenticate nothing."""
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
    s = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(tmp_path / "home"))
    await s.open(RunOptions())
    try:
        assert (await s._codex.account()).account is not None
    finally:
        await s.close()


# --- the outcome shape ------------------------------------------------------


def test_the_outcome_reports_no_cost_and_that_is_deliberate() -> None:
    """Codex reports tokens and no money -- measured over the whole package.

    0.16.0 made `SessionRecord.total_cost_usd` nullable for exactly this, so
    `None` is the honest answer where `0.0` would read as *free*.
    """
    assert TurnOutcome().total_cost_usd is None


def test_an_outcome_with_no_terminating_event_is_still_reportable() -> None:
    """A turn whose app-server died mid-stream must still be reportable --
    `outcome_recorded: false` in the specification's terms."""
    outcome = TurnOutcome()
    assert outcome.status is None
    assert outcome.events == []


# --- the turn deadline, which needs no credential ----------------------------
#
# **The whole point of these is that they cost nothing.** A turn needs a
# credential, but a turn that never finishes does not -- so the deadline, the
# interrupt it fires and the partial outcome it carries are all testable for free
# against a hand-made turn handle. (CX-11) is the defect
# they close: `timeout_s` was named as service-enforced and enforced by nothing.


class _HangingTurn:
    """A turn handle that never produces an event and records its interrupt."""

    def __init__(self) -> None:
        self.interrupted = False

    async def stream(self):  # noqa: ANN202
        await asyncio.sleep(3600)
        yield None  # pragma: no cover - unreachable, and that is the point

    async def interrupt(self) -> None:
        self.interrupted = True


class _FakeThread:
    def __init__(self, turn: _HangingTurn) -> None:
        self._turn = turn

    async def turn(self, prompt: str, **kwargs):  # noqa: ANN202, ARG002
        return self._turn


def _detached_session(tmp_path, turn: _HangingTurn) -> CodexSession:
    """A session with a fake thread and no app-server behind it."""
    s = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(tmp_path / "home"))
    s._thread = _FakeThread(turn)
    return s


async def test_a_turn_that_outlives_its_budget_raises_RunTimeout(tmp_path) -> None:  # noqa: ANN001
    turn = _HangingTurn()
    session = _detached_session(tmp_path, turn)
    with pytest.raises(RunTimeout) as excinfo:
        await session.send("hello", RunOptions(), timeout_s=0.05)
    assert "0.05" in str(excinfo.value)


async def test_the_abandoned_turn_is_INTERRUPTED_not_merely_dropped(tmp_path) -> None:  # noqa: ANN001
    """**The part that costs money if it is missing.** Without the interrupt the
    app-server goes on spending on a turn nobody is waiting for, and the session's
    turn lock is already free for the next one -- two live turns on one
    conversation."""
    turn = _HangingTurn()
    session = _detached_session(tmp_path, turn)
    with pytest.raises(RunTimeout):
        await session.send("hello", RunOptions(), timeout_s=0.05)
    assert turn.interrupted is True


async def test_the_timeout_carries_the_partial_outcome(tmp_path) -> None:  # noqa: ANN001
    """`timed_out` on the outcome is what keeps a timeout distinguishable on a
    `SessionRecord` fetched later, when the 504 is long gone."""
    session = _detached_session(tmp_path, _HangingTurn())
    with pytest.raises(RunTimeout) as excinfo:
        await session.send("hello", RunOptions(), timeout_s=0.05)
    outcome = excinfo.value.outcome
    assert outcome is not None
    assert outcome.timed_out is True
    # No `turn/completed` arrived, so the turn is NOT recorded as having reached
    # an end of its own accord.
    assert outcome.status is None


async def test_the_turn_handle_is_released_after_a_timeout(tmp_path) -> None:  # noqa: ANN001
    """A handle left behind would make the next `interrupt()` aim at a turn that
    is over -- and would report `True` for having done so."""
    session = _detached_session(tmp_path, _HangingTurn())
    with pytest.raises(RunTimeout):
        await session.send("hello", RunOptions(), timeout_s=0.05)
    assert await session.interrupt() is False


async def test_no_deadline_means_no_timeout(tmp_path) -> None:  # noqa: ANN001
    """The control: `asyncio.timeout(None)` must be a no-op context rather than
    an immediate expiry, or every unbounded turn would 504 at once."""
    session = _detached_session(tmp_path, _HangingTurn())
    with pytest.raises(TimeoutError):
        # A real wait, bounded by the test rather than by the service, proving
        # the service did not bound it.
        async with asyncio.timeout(0.1):
            await session.send("hello", RunOptions(), timeout_s=None)


# --- what the REGISTRY does with a timed-out turn -----------------------------
#
# Two guarantees, and both were broken by the first version of the deadline:
# `finish_run` recorded `timed_out=False` unconditionally, and `entry.last_turn`
# was assigned after the `try`, which no exception reaches. The second is the
# nastier one -- it leaves the PREVIOUS turn standing as the session's last, so a
# timed-out turn is not merely unreported but misattributed.
#
# `session_factory` and `recorder` are both injectable, so none of this needs an
# app-server, a credential or a database.


class _TimingOutSession:
    """A session whose every turn expires, carrying a partial outcome."""

    sdk_session_id = "11111111-2222-3333-4444-555555555555"

    def __init__(self) -> None:
        self.closed = False

    async def open(self, options, resume=None) -> None:  # noqa: ANN001, ARG002
        return None

    async def send(self, prompt, options, *, timeout_s=None):  # noqa: ANN001, ARG002
        outcome = TurnOutcome(timed_out=True, duration_ms=1)
        raise RunTimeout(f"turn exceeded {timeout_s}s", outcome)

    async def interrupt(self) -> bool:
        return False

    async def close(self) -> None:
        self.closed = True


class _CapturingRecorder:
    """Records the arguments `finish_run` was called with, and nothing else."""

    def __init__(self) -> None:
        self.finished: list[dict] = []

    def start_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        return None

    def finish_run(self, run_id, **kwargs) -> None:  # noqa: ANN001, ARG002
        self.finished.append(kwargs)

    def session_opened(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None

    def session_closed(self, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
        return None


async def _timing_out_registry(tmp_path):  # noqa: ANN202
    from agent_service.config import Settings
    from agent_service.registry import SessionRegistry

    recorder = _CapturingRecorder()
    registry = SessionRegistry(
        Settings(require_credentials=False, require_mounts=False, workspace_dir=tmp_path),
        # The registry calls its factory with `(options, workspace_subdir)`.
        session_factory=lambda options, subdir: _TimingOutSession(),
        recorder=recorder,
    )
    sid = await registry.create(RunOptions())
    return registry, recorder, sid


async def test_a_timed_out_turn_is_RECORDED_as_timed_out(tmp_path) -> None:  # noqa: ANN001
    """It was hardcoded `False`, which was true while nothing could time out and
    is the whole of what a stored run has left once the 504 is gone."""
    registry, recorder, sid = await _timing_out_registry(tmp_path)
    with pytest.raises(RunTimeout):
        await registry.send(sid, "hello", RunOptions())
    assert recorder.finished, "finish_run was never called for a failed turn"
    assert recorder.finished[-1]["timed_out"] is True


async def test_a_timed_out_turn_becomes_the_sessions_LAST_turn(tmp_path) -> None:  # noqa: ANN001
    """**The misattribution bug.** With `entry.last_turn` assigned after the
    `try`, a timeout left the previous turn standing as the session's last -- so
    `GET /v1/sessions/{sid}` would report somebody else's success as the most
    recent thing that happened."""
    registry, _recorder, sid = await _timing_out_registry(tmp_path)
    with pytest.raises(RunTimeout):
        await registry.send(sid, "hello", RunOptions())
    last = registry.get(sid).last_turn
    assert last is not None, "the timed-out turn left no record at all"
    assert last.timed_out is True
    assert last.status is None


async def test_the_turn_still_counts_and_still_stamps(tmp_path) -> None:  # noqa: ANN001
    """A turn that broke still happened. A `last_used_at` that only moves on
    success makes the reaper collect the session whose turns are failing -- the
    one it should leave alone longest."""
    registry, _recorder, sid = await _timing_out_registry(tmp_path)
    before = registry.get(sid).last_used_at
    with pytest.raises(RunTimeout):
        await registry.send(sid, "hello", RunOptions())
    entry = registry.get(sid)
    assert entry.turns == 1
    assert entry.last_used_at >= before


async def test_the_session_is_usable_again_after_a_timeout(tmp_path) -> None:  # noqa: ANN001
    """The turn lock must be released. A timeout that left it held would turn one
    slow turn into a permanently 409-ing session."""
    registry, _recorder, sid = await _timing_out_registry(tmp_path)
    for _ in range(2):
        with pytest.raises(RunTimeout):
            await registry.send(sid, "hello", RunOptions())
    assert registry.get(sid).turns == 2


async def test_a_turn_whose_CONSUMER_went_away_is_interrupted_too(tmp_path) -> None:  # noqa: ANN001
    """CX-54: a closed browser tab costs the same as a deadline that expires.

    The interrupt was wired to the timeout branch only, so a cancelled turn --
    a dropped SSE consumer, a relay releasing its upstream -- left the
    app-server spending on a turn nobody was waiting for. Worse, the `finally`
    clears the turn handle, so nothing could stop it afterwards either.
    """
    turn = _HangingTurn()
    session = _detached_session(tmp_path, turn)

    running = asyncio.create_task(session.send("hello", RunOptions(), timeout_s=None))
    # Let it reach the stream, so there is a live turn to abandon.
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    # The interrupt is shielded, so it completes after this frame gave up on it.
    await asyncio.sleep(0.05)

    assert turn.interrupted is True, "the app-server was left spending"
