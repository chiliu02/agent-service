import asyncio, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def s1_counter():
    head("S1 a Semaphore is a counter, and `locked()` means 'value is 0'")
    sem = asyncio.Semaphore(2)
    print(f"  Semaphore(2): locked()={sem.locked()}")
    await sem.acquire(); print(f"  after 1 acquire: locked()={sem.locked()}")
    await sem.acquire(); print(f"  after 2 acquires: locked()={sem.locked()}  <-- exhausted")
    sem.release();       print(f"  after 1 release:  locked()={sem.locked()}")
    sem.release()

async def s2_limits_concurrency():
    head("S2 the point: bounded concurrency over an unbounded fan-out")
    sem, live, peak = asyncio.Semaphore(3), 0, 0
    async def job(n):
        nonlocal live, peak
        async with sem:
            live += 1; peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
    t0 = time.monotonic()
    await asyncio.gather(*(job(n) for n in range(20)))
    print(f"  20 jobs, Semaphore(3): peak concurrency={peak}, "
          f"wall={time.monotonic()-t0:.3f}s (~7 waves of 0.01s)")

async def s3_release_unbounded():
    head("S3 Semaphore.release() can push the value ABOVE its initial count")
    sem = asyncio.Semaphore(1)
    sem.release(); sem.release()
    got = 0
    for _ in range(3):
        try:
            async with asyncio.timeout(0):
                await sem.acquire()
            got += 1
        except TimeoutError:
            break
    print(f"  Semaphore(1) + 2 stray release()s -> {got} concurrent acquires")
    bs = asyncio.BoundedSemaphore(1)
    try:
        bs.release()
    except ValueError as exc:
        print(f"  BoundedSemaphore(1).release() -> ValueError: {exc}")
    print("  => use BoundedSemaphore to catch double-release bugs")

async def s4_no_owner():
    head("S4 no owner: any task can release, and there is no reentrancy")
    sem = asyncio.Semaphore(1)
    await sem.acquire()
    async def stranger(): sem.release()
    await stranger()
    print(f"  a different coroutine released it: locked()={sem.locked()}")
    await sem.acquire()
    try:
        async with asyncio.timeout(0.05):
            await sem.acquire()      # same task, second acquire
        print("  re-acquired (would mean the count was > 1)")
    except TimeoutError:
        print("  same task re-acquiring Semaphore(1) DEADLOCKS -- no owner tracking")
    sem.release()

async def s5_fairness():
    head("S5 FIFO fairness, same as Lock")
    sem, order = asyncio.Semaphore(1), []
    async def worker(name):
        async with sem:
            order.append(name); await asyncio.sleep(0.005)
    await sem.acquire()
    tasks = [asyncio.create_task(worker(n)) for n in "ABCDE"]
    await asyncio.sleep(0)
    sem.release()
    await asyncio.gather(*tasks)
    print(f"  arrival A,B,C,D,E -> service {','.join(order)}")

async def s6_zero_as_gate():
    head("S6 Semaphore(0) is a counting gate (N permits handed out later)")
    sem, done = asyncio.Semaphore(0), []
    async def w(n):
        await sem.acquire(); done.append(n)
    tasks = [asyncio.create_task(w(n)) for n in "abc"]
    await asyncio.sleep(0)
    sem.release(); sem.release()
    await asyncio.sleep(0.01)
    print(f"  2 releases against 3 waiters -> {done} (a Queue-like hand-off, not a broadcast)")
    for t in tasks: t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

async def s7_bounded_with_timeout():
    head("S7 no timeout parameter -- same idiom as Lock")
    sem = asyncio.Semaphore(1)
    await sem.acquire()
    try:
        async with asyncio.timeout(0):
            await sem.acquire()
        print("  acquired")
    except TimeoutError:
        print("  timeout(0) -> refused without waiting, exactly as with a Lock")
    sem.release()

async def s8_leak_on_error():
    head("S8 `async with sem` releases on an exception; manual acquire may not")
    sem = asyncio.Semaphore(1)
    with suppress(ValueError):
        async with sem:
            raise ValueError("boom")
    print(f"  after `async with` + raise: locked()={sem.locked()} (released)")
    await sem.acquire()
    try:
        raise ValueError("boom")
    except ValueError:
        pass                     # forgot the release
    print(f"  after manual acquire + raise: locked()={sem.locked()} <-- permit LEAKED")

async def main():
    for p in (s1_counter, s2_limits_concurrency, s3_release_unbounded, s4_no_owner,
              s5_fairness, s6_zero_as_gate, s7_bounded_with_timeout, s8_leak_on_error):
        await p()
asyncio.run(main())
