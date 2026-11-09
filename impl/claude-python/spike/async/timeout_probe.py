import asyncio, time
from contextlib import suppress

def head(t): print(f"\n=== {t}")

async def p1_conversion():
    head("P1 timeout converts CancelledError -> TimeoutError")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            await asyncio.sleep(5)
    except TimeoutError as exc:
        print(f"  TimeoutError after {time.monotonic()-t0:.3f}s, __cause__={exc.__cause__!r}")
    print(f"  task.cancelling() afterwards = {asyncio.current_task().cancelling()}")

async def p2_cpu():
    head("P2 a CPU-bound block ignores the deadline")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            x = 0
            for i in range(40_000_000):   # no awaits at all
                x += i
    except TimeoutError:
        print("  TimeoutError (raised only at __aexit__)")
    print(f"  block actually took {time.monotonic()-t0:.3f}s for a 0.05s deadline")

async def p3_nested():
    head("P3 nested deadlines: which one reports")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.30):          # outer
            async with asyncio.timeout(0.05):      # inner fires first
                await asyncio.sleep(5)
    except TimeoutError:
        print(f"  inner fired at {time.monotonic()-t0:.3f}s -> TimeoutError")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):          # outer fires first
            async with asyncio.timeout(5.0):       # inner never fires
                await asyncio.sleep(5)
    except TimeoutError:
        print(f"  outer fired at {time.monotonic()-t0:.3f}s -> TimeoutError "
              "(inner did NOT convert it)")

async def p4_timeout_zero():
    head("P4 asyncio.timeout(0) as a non-waiting acquire")
    lock = asyncio.Lock()
    async def try_now():
        try:
            async with asyncio.timeout(0):
                await lock.acquire()
            return True
        except TimeoutError:
            return False
    print(f"  free lock      -> acquired={await try_now()}")
    print(f"  now held by us -> acquired={await try_now()}")
    lock.release()

async def p5_mro():
    head("P5 TimeoutError's ancestry (except-clause ORDER matters)")
    print(f"  MRO: {[c.__name__ for c in TimeoutError.__mro__]}")
    print(f"  asyncio.TimeoutError is TimeoutError -> {asyncio.TimeoutError is TimeoutError}")
    print(f"  isinstance(TimeoutError(), Exception) -> {isinstance(TimeoutError(), Exception)}")
    print(f"  isinstance(CancelledError(), Exception) -> "
          f"{isinstance(asyncio.CancelledError(), Exception)}")
    # the trap: broad clause first
    try:
        async with asyncio.timeout(0.05):
            try:
                await asyncio.sleep(5)
            except Exception:
                print("  inner `except Exception` did NOT see the cancellation")
                raise
    except TimeoutError:
        print("  ...and the TimeoutError still arrived")

async def p6_swallow():
    head("P6 swallowing CancelledError inside the block")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                print(f"  swallowed at {time.monotonic()-t0:.3f}s; "
                      f"cancelling()={asyncio.current_task().cancelling()}")
            await asyncio.sleep(0.25)      # deadline already blown
            print(f"  kept running to {time.monotonic()-t0:.3f}s -- NOT re-cancelled")
    except TimeoutError:
        print(f"  TimeoutError only at __aexit__, {time.monotonic()-t0:.3f}s")

async def p7_wait_vs_wait_for():
    head("P7 asyncio.wait(timeout=) does NOT cancel; wait_for does")
    async def slow():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            print("    [slow] cancelled")
            raise
    t = asyncio.create_task(slow())
    done, pending = await asyncio.wait({t}, timeout=0.05)
    print(f"  after asyncio.wait: done={len(done)} pending={len(pending)} "
          f"cancelled={t.cancelled()} -- still running")
    t.cancel()
    with suppress(asyncio.CancelledError):
        await t
    t2 = asyncio.create_task(slow())
    with suppress(TimeoutError):
        await asyncio.wait_for(t2, timeout=0.05)
    print(f"  after wait_for: cancelled={t2.cancelled()}")

async def p8_finally():
    head("P8 awaiting inside a finally after the deadline blew")
    async def body():
        try:
            await asyncio.sleep(5)
        finally:
            t0 = time.monotonic()
            await asyncio.sleep(0.1)
            print(f"  finally's await COMPLETED ({time.monotonic()-t0:.3f}s)")
    with suppress(TimeoutError):
        async with asyncio.timeout(0.05):
            await body()
    print("  (one cancel = one CancelledError; cleanup got to run)")

async def p9_shield():
    head("P9 shield survives the deadline, but you must not await it there")
    done = asyncio.Event()
    async def critical():
        await asyncio.sleep(0.2)
        done.set()
        return "committed"
    task = asyncio.create_task(critical())
    with suppress(TimeoutError):
        async with asyncio.timeout(0.05):
            await asyncio.shield(task)
    print(f"  deadline hit; shielded task cancelled={task.cancelled()}")
    await asyncio.wait({task}, timeout=1)
    print(f"  it finished anyway: {task.result()!r}, done_event={done.is_set()}")

async def p10_fifo():
    head("P10 an UNLOCKED lock still suspends the next acquirer (FIFO fairness)")
    lock = asyncio.Lock()
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)                 # let `waiter` queue up
    lock.release()                         # no await after this line
    print(f"  lock.locked() right after release -> {lock.locked()}")
    try:
        async with asyncio.timeout(0):
            await lock.acquire()
        print("  timeout(0) acquire -> True  (would jump the queue)")
    except TimeoutError:
        print("  timeout(0) acquire -> False (a waiter is queued ahead of us)")
    await waiter
    lock.release()

async def main():
    for p in (p1_conversion, p2_cpu, p3_nested, p4_timeout_zero, p5_mro,
              p6_swallow, p7_wait_vs_wait_for, p8_finally, p9_shield, p10_fifo):
        await p()

asyncio.run(main())
