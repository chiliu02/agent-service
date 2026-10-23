"""`close_all()` spends ONE budget, and the compose grace period is derived from it.

**Nothing here starts an app-server.** The subject is the sweep's arithmetic --
what it waits for, what it gives up on, what it says afterwards -- and a fake
session whose `close()` hangs on request is the only way to reach the branches
that matter. The real SDK close is already bounded (terminate, `wait(2)`,
`kill()`, two 0.5s joins), so a hung one cannot be produced on demand.

The budgets used below are sub-second on purpose: the same code path, three
orders of magnitude faster than production's 60s.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from agent_spec.openapi.schemas import RunOptions

from agent_service.config import Settings
from agent_service.registry import SessionRegistry

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeSession:
    """A session whose close can hang, raise, or return."""

    sdk_session_id = "00000000-0000-0000-0000-000000000000"

    def __init__(self, *, hang: bool = False, raises: bool = False) -> None:
        self.hang = hang
        self.raises = raises
        self.closed = False

    async def open(self, options, resume=None) -> None:  # noqa: ANN001, ARG002
        return None

    async def close(self) -> None:
        if self.raises:
            raise RuntimeError("close failed")
        if self.hang:
            # Long enough that any budget in this file expires first, and
            # cancellable -- unlike the SDK's thread, which is the point of
            # `_close_within` reporting rather than claiming.
            await asyncio.sleep(30)
        self.closed = True


async def _registry(tmp_path, sessions: list[_FakeSession], **kwargs):  # noqa: ANN202
    made = iter(sessions)
    registry = SessionRegistry(
        Settings(
            require_credentials=False,
            require_mounts=False,
            workspace_dir=tmp_path,
            **kwargs,
        ),
        session_factory=lambda options, subdir: next(made),  # noqa: ARG005
    )
    for _ in sessions:
        await registry.create(RunOptions())
    return registry


async def test_close_all_closes_every_session(tmp_path) -> None:  # noqa: ANN001
    """The plain case, which the budget must not have broken."""
    sessions = [_FakeSession() for _ in range(3)]
    registry = await _registry(tmp_path, sessions)
    await registry.close_all()
    assert all(s.closed for s in sessions)
    assert registry.list() == []


async def test_the_budget_bounds_the_WHOLE_sweep_not_each_close(tmp_path) -> None:  # noqa: ANN001
    """**The defect this fixed.** Three hanging sessions used to cost three
    unbounded closes in sequence; the container's grace period could only ever
    be a guess against a number that did not exist."""
    sessions = [_FakeSession(hang=True) for _ in range(3)]
    registry = await _registry(tmp_path, sessions)
    started = asyncio.get_running_loop().time()
    await registry.close_all(budget_s=0.3)
    elapsed = asyncio.get_running_loop().time() - started
    # Three closes that would each run for 30s, inside 0.3s. The slack is
    # scheduling noise, not another budget.
    assert elapsed < 1.0, f"the sweep took {elapsed:.3f}s of a 0.3s budget"


async def test_a_fast_close_hands_its_unused_time_to_the_rest(tmp_path) -> None:  # noqa: ANN001
    """Fair share, not a fixed slice. One healthy session and one wedged one:
    the healthy one must close, and it must not have been charged half the
    budget to do it."""
    healthy, wedged = _FakeSession(), _FakeSession(hang=True)
    registry = await _registry(tmp_path, [healthy, wedged])
    await registry.close_all(budget_s=0.4)
    assert healthy.closed, "a session that closes instantly was not closed"


async def test_one_failure_does_not_stop_the_sweep(tmp_path) -> None:  # noqa: ANN001
    """A raising close is one session's problem, never the shutdown's."""
    bad, good = _FakeSession(raises=True), _FakeSession()
    registry = await _registry(tmp_path, [bad, good])
    await registry.close_all(budget_s=5.0)
    assert good.closed


async def test_a_session_that_did_not_close_stays_REGISTERED(tmp_path) -> None:  # noqa: ANN001
    """It used to be popped on failure, which made a subprocess that may still
    be alive indistinguishable from one that shut down cleanly. `list()` after
    a sweep names exactly what is not known to have gone."""
    bad, good = _FakeSession(raises=True), _FakeSession()
    registry = await _registry(tmp_path, [bad, good])
    await registry.close_all(budget_s=5.0)
    remaining = [entry.session for _sid, entry in registry.list()]
    assert remaining == [bad]


async def test_the_sweep_says_what_it_did(tmp_path, caplog) -> None:  # noqa: ANN001
    """A clean sweep and a sweep that never ran must not look identical in a
    container's logs -- and the counts must add up to the total it reports."""
    registry = await _registry(tmp_path, [_FakeSession(), _FakeSession()])
    with caplog.at_level("INFO", logger="agent_service.registry"):
        await registry.close_all(budget_s=5.0)
    line = "\n".join(r.getMessage() for r in caplog.records)
    assert "close_all: swept 2 session(s)" in line
    assert "2 closed cleanly, 0 failed, 0 abandoned, 0 never reached" in line


async def test_an_unfinished_sweep_logs_at_ERROR_and_names_the_sessions(  # noqa: ANN001
    tmp_path, caplog
) -> None:
    """Whatever is left will not be retried and its app-server may still be
    alive when the container is killed. That is an error, not a note."""
    registry = await _registry(tmp_path, [_FakeSession(hang=True)])
    with caplog.at_level("INFO", logger="agent_service.registry"):
        await registry.close_all(budget_s=0.2)
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors, "an abandoned close was reported at INFO or not at all"
    assert "still registered" in errors[-1].getMessage()


async def test_cancelling_the_sweep_ABORTS_it(tmp_path) -> None:  # noqa: ANN001
    """A `BaseException` is the shutdown telling this to stop. Catching it
    alongside `Exception` would make the sweep outlive the thing that cancelled
    it, which is the opposite of a bounded shutdown."""
    registry = await _registry(tmp_path, [_FakeSession(hang=True), _FakeSession()])
    task = asyncio.create_task(registry.close_all(budget_s=30.0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_compose_grace_period_follows_the_shutdown_budget(tmp_path) -> None:  # noqa: ANN001
    """`stop_grace_period` is DERIVED. Pin the derivation.

    Docker sends SIGTERM, waits `stop_grace_period`, then SIGKILLs. Two budgets
    run sequentially inside that window and only the first is uvicorn's: the
    request drain (`--timeout-graceful-shutdown`, in the Dockerfile CMD), and
    THEN the lifespan shutdown -- `close_all()`, bounded by
    `shutdown_budget_s`.

    Reading all three out of the three files that own them is what stops
    somebody raising the budget, or lowering the grace, without seeing the
    other. This build had no third number at all until 2026-08-10.
    """
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    drain = float(
        re.search(
            r'"--timeout-graceful-shutdown",\s*"(\d+(?:\.\d+)?)"', dockerfile
        ).group(1)  # type: ignore[union-attr]
    )
    grace = float(
        re.search(
            r"^\s*stop_grace_period:\s*(\d+(?:\.\d+)?)s\s*$", compose, re.M
        ).group(1)  # type: ignore[union-attr]
    )
    budget = Settings(workspace_dir=tmp_path).shutdown_budget_s

    # `+ 5`: the two budgets are not the whole shutdown -- uvicorn's own
    # teardown and process exit run beyond `close_all()`, and a grace period
    # equal to their sum leaves that nothing at all.
    assert grace >= drain + budget + 5.0, (
        f"stop_grace_period {grace}s cannot cover the {drain}s request drain "
        f"plus the {budget}s close_all() budget plus a margin"
    )
    # ...and not absurdly larger either: a grace period far above the bound is
    # the same guess in the other direction.
    assert grace <= drain + budget + 30.0, (grace, drain, budget)


def test_the_budget_covers_a_full_container(tmp_path) -> None:  # noqa: ANN001
    """The budget is derived too, and this is the derivation.

    The SDK's close is `terminate()`, `wait(timeout=2)`, `kill()` on any
    exception, then two 0.5s thread joins -- ~3s at worst. A container carries
    about 16 sessions before `pids_limit` binds. A budget below their product
    would abandon healthy closes on a full container, which is the failure this
    is bounded to prevent rather than to cause.
    """
    worst_case_close_s = 3.0
    sessions_a_container_carries = 16
    budget = Settings(workspace_dir=tmp_path).shutdown_budget_s
    assert budget >= worst_case_close_s * sessions_a_container_carries
