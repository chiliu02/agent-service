import asyncio, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def c1_releases_the_lock():
    head("C1 wait() RELEASES the lock, then re-acquires before returning")
    cond = asyncio.Condition()
    log = []
    async def waiter():
        async with cond:
            log.append(f"waiter holds lock: {cond.locked()}")
            await cond.wait()
            log.append(f"waiter re-acquired: {cond.locked()}")
    t = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    log.append(f"while waiter is in wait(), lock free? {not cond.locked()}")
    async with cond:
        cond.notify()
        log.append("notifier holds the lock and has notified")
    await t
    for line in log: print(f"  {line}")

async def c2_notify_needs_the_lock():
    head("C2 wait() and notify() both REQUIRE the lock")
    cond = asyncio.Condition()
    try:
        cond.notify()
    except RuntimeError as exc:
        print(f"  notify() unlocked -> RuntimeError: {exc}")
    async def bad():
        await cond.wait()
    try:
        await bad()
    except RuntimeError as exc:
        print(f"  wait() unlocked   -> RuntimeError: {exc}")

async def c3_notify_n():
    head("C3 notify(n) wakes n; notify_all() wakes all")
    for how in ("notify(1)", "notify(2)", "notify_all()"):
        cond, woke = asyncio.Condition(), []
        async def w(n):
            async with cond:
                await cond.wait(); woke.append(n)
        tasks = [asyncio.create_task(w(n)) for n in "abcd"]
        await asyncio.sleep(0.01)
        async with cond:
            if how == "notify(1)": cond.notify()
            elif how == "notify(2)": cond.notify(2)
            else: cond.notify_all()
        await asyncio.sleep(0.02)
        print(f"  {how:12} -> woke {woke}")
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

async def c4_stale_wakeup():
    head("C4 waking does NOT mean the predicate holds -- always loop")
    cond = asyncio.Condition()
    items, got = [], []
    async def consumer(n, use_loop):
        async with cond:
            if use_loop:
                while not items:
                    await cond.wait()
            else:
                await cond.wait()
            got.append((n, items.pop() if items else "NOTHING -- took a stale wakeup"))
    tasks = [asyncio.create_task(consumer(n, use_loop=False)) for n in "ab"]
    await asyncio.sleep(0.01)
    async with cond:
        items.append("one-item")
        cond.notify_all()               # two waiters, ONE item
    await asyncio.sleep(0.02)
    print(f"  bare `await wait()`: {got}")
    for t in tasks: t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

async def c5_wait_for():
    head("C5 wait_for(predicate) writes the loop for you")
    cond = asyncio.Condition()
    state = {"ready": False}
    async def waiter():
        async with cond:
            await cond.wait_for(lambda: state["ready"])
            return "predicate held on return"
    t = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    async with cond:
        cond.notify_all()               # spurious: predicate still False
    await asyncio.sleep(0.01)
    print(f"  after a notify with predicate False: still waiting = {not t.done()}")
    async with cond:
        state["ready"] = True
        cond.notify_all()
    print(f"  {await t}")

async def c6_cancel_during_wait():
    head("C6 a cancelled waiter must re-acquire the lock before propagating")
    cond = asyncio.Condition()
    async def waiter():
        async with cond:
            await cond.wait()
    t = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    async with cond:                    # hold it so the cancel cannot complete
        t.cancel()
        await asyncio.sleep(0.01)
        print(f"  cancelled, but notifier holds the lock: waiter done? {t.done()}")
    with suppress(asyncio.CancelledError):
        await t
    print(f"  after release: done={t.done()} cancelled={t.cancelled()} "
          f"lock free={not cond.locked()}")

async def c7_shared_lock():
    head("C7 a Condition can share an existing Lock")
    lock = asyncio.Lock()
    cond = asyncio.Condition(lock)
    async with cond:
        print(f"  entering the Condition took the Lock: locked()={lock.locked()}")
    print(f"  and released it: locked()={lock.locked()}")

async def main():
    for p in (c1_releases_the_lock, c2_notify_needs_the_lock, c3_notify_n,
              c4_stale_wakeup, c5_wait_for, c6_cancel_during_wait, c7_shared_lock):
        await p()
asyncio.run(main())
