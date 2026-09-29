"""What gets recorded, and what must never be imported when nothing is.

**Free: no database and no agent.** The recorder is a protocol, so a capturing
stand-in answers every question about WHAT is written without a Postgres to
write it to — and the one question that needs a real interpreter gets one.

The rows themselves are `agent_spec.db`'s, tested there. What is this build's
own is the seam: which calls happen, in which order, with which of the two
session ids, and what a turn that never produced an envelope records.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_service.api import _run_turn, create_app
from agent_service.config import Settings
from agent_service.persistence import to_run_outcome
from agent_service.registry import Registry

FAKE = (sys.executable, str(Path(__file__).parent / "fake_cli_agent.py"))
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Capturing:
    """A `RunRecorder` that keeps what it was told, in order."""

    def __init__(self) -> None:
        self.opened: list[dict[str, Any]] = []
        self.closed: list[dict[str, Any]] = []
        self.started: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.finished: list[dict[str, Any]] = []

    def session_opened(self, sid: str, **kw: Any) -> None:
        self.opened.append({"sid": sid, **kw})

    def session_closed(self, sid: str, **kw: Any) -> None:
        self.closed.append({"sid": sid, **kw})

    def start_run(self, run_id: str, **kw: Any) -> None:
        self.started.append({"run_id": run_id, **kw})

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self.events.append((run_id, event))

    def finish_run(self, run_id: str, **kw: Any) -> None:
        self.finished.append({"run_id": run_id, **kw})


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "home",
        "transcript_store": tmp_path / "store",
        "gemini_binary": FAKE,
        "require_credentials": False,
    }
    settings = Settings(**{**base, **kwargs})
    # The lifespan makes these when the app boots; these tests drive `_run_turn`
    # directly, and the agent is spawned with the workspace as its cwd.
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    settings.agent_home_root.mkdir(parents=True, exist_ok=True)
    settings.transcript_store.mkdir(parents=True, exist_ok=True)
    return settings


# --- the lazy import ------------------------------------------------------

def test_no_database_url_imports_no_sqlalchemy() -> None:
    """**A FRESH INTERPRETER**, because by the time this file runs other tests
    have imported the world and an in-process `sys.modules` check would pass
    whatever `create_app` does.

    This is not about startup milliseconds. A database must never become a hard
    dependency of this build, and the way that decays is an unconditional import
    creeping into `api.py` and going unnoticed on the machine that has one.
    """
    code = (
        "import sys;"
        "from agent_service.api import create_app;"
        "from agent_service.config import Settings;"
        "from pathlib import Path;"
        "app = create_app(Settings(workspace_dir=Path('./workspace'),"
        " agent_home_root=Path('./temp/h'), transcript_store=Path('./temp/t'),"
        " gemini_binary=Path('gemini'), require_credentials=False));"
        "assert app.state.persistence is None, 'persistence built without a URL';"
        "leaked = [m for m in sys.modules if m == 'sqlalchemy' "
        "or m.startswith('agent_spec.db.wiring')];"
        "print('LEAKED:' + ','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=ROOT / "src", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "LEAKED:\n" in result.stdout or result.stdout.strip() == "LEAKED:", (
        f"a no-database app imported a database: {result.stdout.strip()}"
    )


def test_healthz_says_null_not_false_when_nothing_is_configured(
    tmp_path: Path,
) -> None:
    """**`null` is *none configured*; `false` claims one was checked.**

    A client deciding whether history is available must be able to tell "there
    is no database here" from "the database is down", and a single boolean
    cannot carry both.
    """
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get("/healthz").json()
    assert body["database_configured"] is False
    assert body["database_usable"] is None


# --- what a turn records --------------------------------------------------

@pytest.fixture
def wired(tmp_path: Path) -> tuple[Registry, Capturing, Settings]:
    recorder = Capturing()
    settings = _settings(tmp_path)
    return Registry(settings, recorder), recorder, settings


@pytest.mark.anyio
async def test_a_completed_turn_records_start_events_and_finish(
    wired: tuple[Registry, Capturing, Settings],
) -> None:
    registry, recorder, settings = wired
    session = registry.create(title="t")
    await _run_turn(settings, session, "say hello", recorder)

    assert len(recorder.started) == 1
    assert len(recorder.finished) == 1
    run_id = recorder.started[0]["run_id"]
    assert recorder.finished[0]["run_id"] == run_id, "one run, one id"
    assert recorder.events, "a turn's events were not recorded"
    assert {rid for rid, _ in recorder.events} == {run_id}

    # **The stored key is OURS.** The agent's id changes every turn on a resumed
    # session (GP-34), so a reader groups by this one and never by that one.
    assert recorder.started[0]["sid"] == session.session_id
    assert recorder.finished[0]["sid"] == session.session_id
    assert recorder.finished[0]["outcome"] is not None
    # Null and never 0.0: this agent reports no monetary figure at all (GP-16).
    assert recorder.finished[0]["turn_cost_usd"] is None


@pytest.mark.anyio
async def test_the_agents_id_is_unknown_at_the_start_and_known_at_the_end(
    wired: tuple[Registry, Capturing, Settings],
) -> None:
    """`session_id` is the AGENT's, and it arrives with the opening event.

    So it is genuinely `None` when the run starts, and passing it again at the
    end is not redundancy -- it is the only point at which it is known.
    """
    registry, recorder, settings = wired
    session = registry.create()
    await _run_turn(settings, session, "say hello", recorder)
    assert recorder.started[0]["session_id"] is None
    assert recorder.finished[0]["session_id"] == session.sdk_session_id
    assert recorder.finished[0]["session_id"], "the agent minted no id"


@pytest.mark.anyio
async def test_a_one_shot_query_records_a_run_with_NO_sid(
    wired: tuple[Registry, Capturing, Settings],
) -> None:
    """**`sid` is `None` for a query**, because it is never registered.

    Recording the ephemeral `query-...` id would put a key in the row that
    resolves to nothing: no client has seen it and no route accepts it.
    """
    registry, recorder, settings = wired
    session = registry.ephemeral()
    await _run_turn(settings, session, "say hello", recorder)
    assert recorder.started[0]["sid"] is None
    assert recorder.finished[0]["sid"] is None
    assert recorder.finished[0]["outcome"] is not None


@pytest.mark.anyio
async def test_a_timed_out_turn_finishes_the_run_with_no_outcome(
    tmp_path: Path,
) -> None:
    """**`outcome=None` is a real state, not a gap.**

    The turn reached an end and produced no envelope. A reader must be able to
    tell that from a turn that finished badly -- and on this target a turn that
    cannot terminate is routine rather than exceptional (GP-18), so this is the
    common case rather than the corner.
    """
    recorder = Capturing()
    settings = _settings(tmp_path, turn_timeout_s=1)
    registry = Registry(settings, recorder)
    session = registry.create()
    await _run_turn(settings, session, "hang", recorder)

    assert len(recorder.finished) == 1, "a killed turn left its run open"
    assert recorder.finished[0]["outcome"] is None
    assert recorder.finished[0]["timed_out"] is True
    assert recorder.finished[0]["interrupted"] is False


# --- session rows ---------------------------------------------------------

def test_opening_and_closing_a_session_are_both_recorded(
    wired: tuple[Registry, Capturing, Settings],
) -> None:
    registry, recorder, _ = wired
    session = registry.create(title="named", permission_mode="yolo")
    assert recorder.opened[0]["sid"] == session.session_id
    assert recorder.opened[0]["title"] == "named"
    assert recorder.opened[0]["permission_mode"] == "yolo"

    registry.close(session.session_id)
    assert recorder.closed[0] == {"sid": session.session_id, "status": "closed",
                                  "at": recorder.closed[0]["at"]}


def test_a_swept_session_is_recorded_as_EXPIRED_not_closed(tmp_path: Path) -> None:
    """A client that tidied up and one that walked away are different facts.

    `session_idle_ttl_s` is published, so a consumer sizes a reconciliation
    window from it -- and then needs to know which of its sessions the window
    actually took.
    """
    recorder = Capturing()
    registry = Registry(_settings(tmp_path, session_idle_ttl_s=0), recorder)
    registry.create()
    assert registry.sweep() == 1
    assert recorder.closed[0]["status"] == "expired"


def test_sweeping_a_stale_session_does_not_recurse(tmp_path: Path) -> None:
    """**A latent crash, and the published TTL is what would have triggered it.**

    `close()` resolved its argument through `get()`, and `get()` sweeps -- so a
    session that was genuinely stale re-entered the sweep, found itself stale
    again, and recursed until the stack ran out. Every request after a session
    idled past `session_idle_ttl_s` would have been a 500.

    Nothing caught it because no test had ever let a session age past the TTL,
    and the TTL is 1800 seconds.
    """
    registry = Registry(_settings(tmp_path, session_idle_ttl_s=0))
    registry.create()
    assert registry.sweep() == 1
    assert registry.list() == []


# --- the seam -------------------------------------------------------------

def test_the_stored_outcome_agrees_with_what_the_wire_returned() -> None:
    """The rows store what `/v1` returns, so a disagreement is a row that
    contradicts the response the caller already got."""

    class _Result:
        assistant_text = "hello"
        stats = {"status": "success", "duration_ms": 12,
                 "models": {"gemini-3.1-flash-lite": {"total_tokens": 7}}}

    outcome = to_run_outcome(_Result(), "agent-id-1")
    assert outcome.session_id == "agent-id-1"
    assert outcome.result == "hello"
    assert outcome.is_error is False
    assert outcome.duration_ms == 12
    assert outcome.model_usage == {"gemini-3.1-flash-lite": {"total_tokens": 7}}
    # The six this agent cannot fill are None rather than absent, so a reader can
    # tell "this build cannot say" from "nobody has looked".
    assert outcome.total_cost_usd is None
    assert outcome.permission_denials is None
    assert outcome.limit_hit is None


def test_a_refusal_is_not_an_error_because_the_agent_exits_zero() -> None:
    """GP-18: a run that declined to do the work still reports success.

    So `is_error` cannot be derived from the text, and only the envelope's own
    status may set it. Getting this wrong would mark ordinary refusals as
    failures in every stored row.
    """
    class _Refused:
        assistant_text = "I will not do that."
        stats = {"status": "success"}

    assert to_run_outcome(_Refused(), None).is_error is False

    class _Failed:
        assistant_text = ""
        stats = {"status": "error"}

    assert to_run_outcome(_Failed(), None).is_error is True
