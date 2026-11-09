"""Does a create() that times out in open() leak the CLI subprocess?

FREE. `connect()` spawns the CLI but sends no prompt, so nothing here costs a
token.

THE CODE UNDER TEST is `SessionRegistry.create()`'s timeout arm:

    except TimeoutError as exc:
        self._reserved -= 1
        raise SessionOpenTimeout(...)

The reservation is released and the exception is raised -- but `session` is
dropped without an explicit `disconnect()`, and by then `AgentSession.open()`
may already have spawned the CLI. If nothing else reclaims it, a 504 on create
leaves a subprocess with no owner, and a client that retries on 504 leaves one
per attempt.

Three questions, because "leaks" has three different answers with different
severities:

  A. Is a child process alive immediately after the timeout?
  B. Is it still alive a few seconds later?
  C. Does a forced `gc.collect()` reclaim it? Plan 1 found abandoned `query()`
     subprocesses were reclaimed only by the cyclic GC, which is
     non-deterministic but not unbounded. Same question here.

Also runs a CONTROL: a create allowed to succeed, then closed, which S5 already
measured as leaving nothing behind. If the control leaks, the measurement
apparatus is wrong rather than the code.

    uv run python spike/probe_open_timeout_leak.py
"""

from __future__ import annotations

import asyncio
import gc
import sys
import tempfile
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    sys.exit("psutil not installed; run `uv sync` (it is a dev dependency)")

from agent_service.config import Settings
from agent_service.registry import SessionOpenTimeout, SessionRegistry
from agent_spec.openapi.schemas import RunOptions

ME = psutil.Process()


def children() -> set[int]:
    return {c.pid for c in ME.children(recursive=True)}


def alive(pids: set[int]) -> set[int]:
    out = set()
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                out.add(pid)
        except psutil.NoSuchProcess:
            pass
    return out


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


async def _watch(before: set[int], seen: set[int], stop: asyncio.Event) -> None:
    """Sample children continuously.

    A single reading AFTER the timeout cannot tell "never spawned" from
    "spawned and already gone", and those are opposite answers. This records
    every pid that appears at any point, so the first version's `spawned=0`
    cannot be mistaken for evidence of no leak.
    """
    while not stop.is_set():
        seen |= children() - before
        await asyncio.sleep(0.02)


async def timeout_case(ws: Path, open_timeout_s: float) -> dict[str, object]:
    settings = Settings(
        workspace_dir=ws, require_credentials=False, require_mounts=False
    )
    registry = SessionRegistry(settings, open_timeout_s=open_timeout_s)

    before = children()
    seen: set[int] = set()
    stop = asyncio.Event()
    watcher = asyncio.create_task(_watch(before, seen, stop))
    try:
        await registry.create(RunOptions(), None)
        outcome = "create SUCCEEDED (timeout did not fire)"
    except SessionOpenTimeout:
        outcome = "SessionOpenTimeout"
    except Exception as exc:  # noqa: BLE001
        outcome = f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        await watcher

    spawned = seen | (children() - before)
    await asyncio.sleep(2.0)
    still = alive(spawned)

    gc.collect()
    await asyncio.sleep(2.0)
    after_gc = alive(spawned)

    # Whatever survives is cleaned up here so the next case starts even.
    for pid in after_gc:
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass

    return {
        "open_timeout_s": open_timeout_s,
        "outcome": outcome,
        "spawned": len(spawned),
        "alive_after_2s": len(still),
        "alive_after_gc": len(after_gc),
        "registered_sessions": len(registry.list()),
    }


async def control_case(ws: Path) -> tuple[dict[str, object], float, float]:
    """A create allowed to finish, then closed. S5 says: nothing left.

    Also times the open, and times when the child first APPEARS -- the timeout
    cases have to land between those two points to test anything, and picking
    them blind is how the first run measured nothing.
    """
    settings = Settings(
        workspace_dir=ws, require_credentials=False, require_mounts=False
    )
    registry = SessionRegistry(settings, open_timeout_s=30.0)
    before = children()
    seen: set[int] = set()
    stop = asyncio.Event()
    spawn_at: list[float] = []

    async def watch_timed() -> None:
        t0 = asyncio.get_running_loop().time()
        while not stop.is_set():
            new = children() - before
            if new and not spawn_at:
                spawn_at.append(asyncio.get_running_loop().time() - t0)
            seen.update(new)
            await asyncio.sleep(0.02)

    watcher = asyncio.create_task(watch_timed())
    t0 = asyncio.get_running_loop().time()
    sid = await registry.create(RunOptions(), None)
    open_s = asyncio.get_running_loop().time() - t0
    stop.set()
    await watcher

    spawned = seen | (children() - before)
    await registry.close(sid)
    await asyncio.sleep(2.0)
    first_spawn = spawn_at[0] if spawn_at else float("nan")
    return (
        {
            "outcome": "created then closed",
            "open_took_s": round(open_s, 3),
            "child_appeared_at_s": round(first_spawn, 3),
            "spawned": len(spawned),
            "alive_after_close": len(alive(spawned)),
        },
        open_s,
        first_spawn,
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="leakprobe_") as td:
        root = Path(td)

        rule("CONTROL -- create, then close (S5 says nothing is left behind)")
        ws = root / "control"
        ws.mkdir()
        control, open_s, first_spawn = await control_case(ws)
        print(f"  {control}")

        # AIMED, not guessed: the interesting timeouts are the ones that land
        # AFTER the child appears and BEFORE open() returns. Timing that window
        # from a real open is the whole reason the control measures it.
        if first_spawn == first_spawn:  # not NaN
            span = max(open_s - first_spawn, 0.0)
            candidates = [
                round(first_spawn + span * f, 3) for f in (0.1, 0.35, 0.6, 0.85, 0.97)
            ]
        else:
            candidates = [0.5, 1.0, 2.0, 4.0]
        print(f"\n  child appeared at {first_spawn:.3f}s, open returned at {open_s:.3f}s")
        print(f"  aiming timeouts inside that window: {candidates}")

        results = []
        for i, t in enumerate(candidates):
            rule(f"TIMEOUT CASE -- open_timeout_s={t}")
            ws = root / f"t{i}"
            ws.mkdir()
            r = await timeout_case(ws, t)
            print(f"  {r}")
            results.append(r)

    rule("SUMMARY")
    print(f"  control: {control}")
    for r in results:
        verdict = (
            "LEAK -- survives GC"
            if r["alive_after_gc"]
            else "reclaimed by GC"
            if r["alive_after_2s"]
            else "no surviving child"
        )
        print(
            f"  open_timeout_s={r['open_timeout_s']:<5} {r['outcome']:<24} "
            f"spawned={r['spawned']} alive@2s={r['alive_after_2s']} "
            f"alive@gc={r['alive_after_gc']}  -> {verdict}"
        )


if __name__ == "__main__":
    asyncio.run(main())
