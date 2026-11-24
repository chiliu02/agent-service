import anyio, asyncio, time
from contextlib import suppress
def head(t): print(f"\n=== {t}", flush=True)

async def a1_level_triggered():
    head("A1 swallowing a cancellation: asyncio vs anyio")
    # asyncio (this is Part 3's swallow_probe result, re-run for contrast)
    t0 = time.monotonic(); raised = None
    try:
        async with asyncio.timeout(0.05):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass                      # swallow
            await asyncio.sleep(0.20)     # deadline long gone
    except BaseException as exc:
        raised = type(exc).__name__
    print(f"  asyncio.timeout : ran {time.monotonic()-t0:.3f}s past a 0.05s deadline, "
          f"raised={raised}", flush=True)

    t0 = time.monotonic(); cancelled_count = 0
    with anyio.move_on_after(0.05) as scope:
        for _ in range(4):
            try:
                await anyio.sleep(0.10)
            except anyio.get_cancelled_exc_class():
                cancelled_count += 1      # swallow, repeatedly
    print(f"  anyio scope     : exited after {time.monotonic()-t0:.3f}s, "
          f"cancelled_caught={cancelled_count}, scope.cancel_called={scope.cancel_called}", flush=True)
    print("  => anyio re-delivers at EVERY checkpoint until you leave the scope.", flush=True)
    print("     asyncio delivers ONCE; swallow it and the deadline is gone.", flush=True)

async def a2_nursery_cannot_abandon():
    head("A2 a task group will not let you walk away from a child")
    log, t0 = [], time.monotonic()
    async def child():
        await anyio.sleep(0.3); log.append("child finished")
    async with anyio.create_task_group() as tg:
        tg.start_soon(child)
        log.append("body done")
    print(f"  {log} -- the `async with` waited {time.monotonic()-t0:.2f}s", flush=True)
    print("  There is no anyio equivalent of create_task() + never awaiting it.", flush=True)

async def a3_lock_nowait():
    head("A3 'take it only if free' is first-class in anyio")
    lock = anyio.Lock()
    # From a DIFFERENT task, which is the case sessions.py._acquire_lock_now cares about.
    async def contender():
        try:
            lock.acquire_nowait()
            print("  acquired (unexpected)", flush=True)
        except anyio.WouldBlock:
            print("  lock.acquire_nowait() from another task -> anyio.WouldBlock", flush=True)
    await lock.acquire()
    async with anyio.create_task_group() as tg:
        tg.start_soon(contender)
    print("  asyncio has no equivalent; sessions.py._acquire_lock_now uses `timeout(0)`.", flush=True)
    # And the SAME task re-acquiring is caught rather than deadlocking:
    try:
        lock.acquire_nowait()
    except RuntimeError as exc:
        print(f"  same task re-acquiring -> RuntimeError: {exc}", flush=True)
        print("  asyncio.Lock just hangs forever here (Part 4, L2).", flush=True)
    lock.release()

async def a4_shield():
    head("A4 shielding is a REGION, not a wrapper")
    done = []
    async def cleanup():
        with anyio.CancelScope(shield=True):
            await anyio.sleep(0.15)
            done.append("cleanup completed under cancellation")
    with anyio.move_on_after(0.05):
        await cleanup()
    print(f"  {done}", flush=True)
    print("  asyncio.shield() protects ONE awaitable; a CancelScope protects a BLOCK.", flush=True)

async def a5_group_errors():
    head("A5 what escapes a task group")
    try:
        async with anyio.create_task_group() as tg:
            async def boom(): raise ValueError("child failed")
            tg.start_soon(boom)
            await anyio.sleep(1)          # sibling gets cancelled
    except BaseException as exc:
        print(f"  {type(exc).__name__}: {getattr(exc,'exceptions',exc)}", flush=True)
    print("  anyio 4 raises ExceptionGroup, same as asyncio.TaskGroup.", flush=True)

async def main():
    for f in (a1_level_triggered, a2_nursery_cannot_abandon, a3_lock_nowait, a4_shield, a5_group_errors):
        await f()

anyio.run(main)   # asyncio backend by default
