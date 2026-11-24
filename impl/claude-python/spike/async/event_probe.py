import asyncio, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def e1_latch():
    head("E1 an Event is a LATCH, not a pulse")
    ev = asyncio.Event()
    ev.set()
    t0 = time.monotonic()
    await ev.wait(); await ev.wait(); await ev.wait()
    print(f"  three waits on a set Event: {time.monotonic()-t0:.4f}s (all instant)")
    print(f"  is_set()={ev.is_set()}; a set Event stays set until clear()")
    ev.clear()
    try:
        async with asyncio.timeout(0.02):
            await ev.wait()
    except TimeoutError:
        print("  after clear(): wait() blocks again")

async def e2_broadcast():
    head("E2 set() wakes EVERY waiter (broadcast)")
    ev, woke = asyncio.Event(), []
    async def w(n):
        await ev.wait(); woke.append(n)
    tasks = [asyncio.create_task(w(n)) for n in "abcde"]
    await asyncio.sleep(0)
    ev.set()
    await asyncio.gather(*tasks)
    print(f"  one set() woke {len(woke)}: {woke}")
    print("  (a Queue hands an item to ONE getter; an Event releases them all)")

def e3_sync_setter():
    head("E3 set() is synchronous -- callable from a plain `def`")
    ev = asyncio.Event()
    def producer():             # not async, no loop needed to construct
        ev.set()
        return "set from a plain def, no await, no exception"
    print(f"  {producer()}  -> is_set()={ev.is_set()}")

async def e4_lost_wakeup():
    head("E4 the check/clear race -- a genuinely lost wakeup")
    items, ev = [], asyncio.Event()
    async def producer_at(delay):
        await asyncio.sleep(delay)
        items.append("row")             # append FIRST
        ev.set()                        # then signal

    # UNBOUNDED wait: producer fires between the emptiness check and clear()
    asyncio.create_task(producer_at(0))
    empty = not items                   # checked: empty
    await asyncio.sleep(0.01)           # <- producer runs HERE: appends + sets
    ev.clear()                          # <- wipes the signal we never saw
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.1):
            await ev.wait()
        print("  woke normally")
    except TimeoutError:
        print(f"  bare wait() would HANG: item is queued ({len(items)}) but the "
              f"signal was cleared ({time.monotonic()-t0:.2f}s and counting)")

    # writer.py's shape: bounded wait, then RE-CHECK the real condition
    t0 = time.monotonic()
    with suppress(TimeoutError):
        async with asyncio.timeout(0.05):   # `_flush_interval_s`
            await ev.wait()
    print(f"  bounded wait recovers it in {time.monotonic()-t0:.3f}s; "
          f"re-checking the deque finds {len(items)} item(s)")
    print("  => the Event is a HINT; the deque is the truth")

async def e5_cancelled_waiter():
    head("E5 cancelling one waiter does not break the Event")
    ev, woke = asyncio.Event(), []
    a = asyncio.create_task(ev.wait())
    b = asyncio.create_task(ev.wait())
    await asyncio.sleep(0)
    a.cancel()
    with suppress(asyncio.CancelledError):
        await a
    ev.set()
    print(f"  b still woke: {await asyncio.wait_for(b, 0.1)}  (wait() returns True)")

async def main():
    for p in (e1_latch, e2_broadcast, e4_lost_wakeup, e5_cancelled_waiter):
        await p()
e3_sync_setter()
asyncio.run(main())
