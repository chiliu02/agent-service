import asyncio, time
from contextlib import suppress

def head(t): print(f"\n=== {t}")

async def l1_no_lock_needed():
    head("L1 what a lock is FOR: an invariant that must survive an `await`")
    cap, taken, rejected = 3, 0, 0
    async def admit_sync():                     # check+act, NO await between
        nonlocal taken, rejected
        if taken >= cap: rejected += 1; return
        taken += 1
    await asyncio.gather(*(admit_sync() for _ in range(10)))
    print(f"  no await between check and act: taken={taken} (cap {cap}) rejected={rejected}")

    taken = rejected = 0
    async def admit_await():                    # an await lands between them
        nonlocal taken, rejected
        if taken >= cap: rejected += 1; return
        await asyncio.sleep(0)                  # <-- the whole problem
        taken += 1
    await asyncio.gather(*(admit_await() for _ in range(10)))
    print(f"  ONE await between check and act:  taken={taken} (cap {cap}) rejected={rejected}  <-- cap breached")

    lock = asyncio.Lock()
    taken = rejected = 0
    async def admit_locked():
        nonlocal taken, rejected
        async with lock:                        # check+increment together
            if taken >= cap: rejected += 1; return
            taken += 1
        await asyncio.sleep(0)                  # slow part OUTSIDE the lock
    await asyncio.gather(*(admit_locked() for _ in range(10)))
    print(f"  lock around check+increment only: taken={taken} (cap {cap}) rejected={rejected}")

async def l2_not_reentrant():
    head("L2 asyncio.Lock is NOT reentrant")
    lock = asyncio.Lock()
    async def inner():
        async with lock:
            return "inner got it"
    async with lock:
        try:
            async with asyncio.timeout(0.1):
                print(f"  {await inner()}")
        except TimeoutError:
            print("  re-acquiring in the same task DEADLOCKED (no owner tracking)")

async def l3_release_unlocked():
    head("L3 releasing a lock you do not hold")
    lock = asyncio.Lock()
    try:
        lock.release()
    except RuntimeError as exc:
        print(f"  RuntimeError: {exc}")
    print("  ...and `release()` has no idea WHICH task held it -- any task can release")
    await lock.acquire()
    async def other(): lock.release()
    await other()
    print(f"  a different coroutine released it: locked()={lock.locked()}")

async def l4_fairness():
    head("L4 FIFO: waiters are served in arrival order, no barging")
    lock, order = asyncio.Lock(), []
    async def worker(name):
        async with lock:
            order.append(name)
            await asyncio.sleep(0.01)
    await lock.acquire()
    tasks = [asyncio.create_task(worker(n)) for n in "ABCDE"]
    await asyncio.sleep(0)
    lock.release()
    await asyncio.gather(*tasks)
    print(f"  arrival A,B,C,D,E -> service order {','.join(order)}")

async def l5_cancelled_waiter():
    head("L5 a cancelled waiter must not wedge the lock")
    lock = asyncio.Lock()
    await lock.acquire()
    w1 = asyncio.create_task(lock.acquire())
    w2 = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)
    w1.cancel()
    with suppress(asyncio.CancelledError):
        await w1
    lock.release()
    try:
        async with asyncio.timeout(0.2):
            await w2
        print(f"  w1 cancelled, w2 still got it: locked()={lock.locked()}")
        lock.release()
    except TimeoutError:
        print("  !! lock wedged by the cancelled waiter")

async def l6_hold_across_yield():
    head("L6 holding a lock across a `yield` in an async generator")
    lock = asyncio.Lock()
    async def drain():
        async with lock:
            for i in range(5):
                yield i
    g = drain()
    async for x in g:
        break                              # abandon it: no aclose()
    print(f"  after `break` with no aclose: lock.locked()={lock.locked()}  <-- held by nobody runnable")
    try:
        async with asyncio.timeout(0.05):
            await lock.acquire()
        print("  acquired")
    except TimeoutError:
        print("  a second acquirer times out -- this is sessions.py's abandoned turn")
    await g.aclose()
    print(f"  after aclose(): lock.locked()={lock.locked()}  <-- the generator's __aexit__ released it")

def l7_two_loops():
    head("L7 one Lock object, two event loops")
    lock = asyncio.Lock()                  # constructed with NO running loop
    async def use(tag):
        async with lock:
            return f"{tag} ok"
    print(f"  loop 1: {asyncio.run(use('first'))}")
    try:
        print(f"  loop 2: {asyncio.run(use('second'))}")
    except Exception as exc:
        print(f"  loop 2: {type(exc).__name__}: {exc}")

async def main():
    for p in (l1_no_lock_needed, l2_not_reentrant, l3_release_unlocked,
              l4_fairness, l5_cancelled_waiter, l6_hold_across_yield):
        await p()

asyncio.run(main())
l7_two_loops()
