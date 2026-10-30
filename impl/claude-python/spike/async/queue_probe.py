import asyncio, sys, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def q1_basics():
    head("Q1 maxsize=0 means UNBOUNDED (not 'zero capacity')")
    q = asyncio.Queue()
    print(f"  default maxsize={q.maxsize}")
    for i in range(1000):
        q.put_nowait(i)
    print(f"  put_nowait 1000 items, never raised: qsize={q.qsize()} full={q.full()}")

async def q2_backpressure():
    head("Q2 a bounded Queue gives BACKPRESSURE -- put() awaits")
    q = asyncio.Queue(maxsize=2)
    q.put_nowait("a"); q.put_nowait("b")
    try:
        q.put_nowait("c")
    except asyncio.QueueFull:
        print("  put_nowait on a full queue -> QueueFull (an exception on the producer)")
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            await q.put("c")
    except TimeoutError:
        print(f"  await put() on a full queue SUSPENDS the producer ({time.monotonic()-t0:.3f}s)")
    print("  ^ both shapes are wrong for a producer that must never block OR raise")
    with suppress(asyncio.QueueEmpty):
        while True: q.get_nowait()
    try:
        q.get_nowait()
    except asyncio.QueueEmpty:
        print("  get_nowait on an empty queue -> QueueEmpty")

async def q3_one_consumer_each():
    head("Q3 an item goes to exactly ONE getter (unlike Event's broadcast)")
    q, got = asyncio.Queue(), []
    async def consumer(n):
        got.append((n, await q.get())); q.task_done()
    tasks = [asyncio.create_task(consumer(n)) for n in "abc"]
    await asyncio.sleep(0)
    q.put_nowait("only-item")
    done, pending = await asyncio.wait(tasks, timeout=0.05)
    print(f"  one item, three getters: served={got}, still waiting={len(pending)}")
    for t in pending: t.cancel()

async def q4_join():
    head("Q4 join()/task_done(): completion, not emptiness")
    q = asyncio.Queue()
    for i in range(3): q.put_nowait(i)
    async def worker():
        while True:
            await q.get(); await asyncio.sleep(0.01); q.task_done()
    w = asyncio.create_task(worker())
    t0 = time.monotonic()
    await q.join()
    print(f"  join() returned after {time.monotonic()-t0:.3f}s (all 3 task_done'd)")
    w.cancel()
    try:
        q.task_done()
    except ValueError as exc:
        print(f"  one task_done() too many -> ValueError: {exc}")

async def q5_cancelled_getter():
    head("Q5 cancelling a getter must not swallow an item")
    q = asyncio.Queue()
    g1 = asyncio.create_task(q.get())
    await asyncio.sleep(0)
    g1.cancel()
    with suppress(asyncio.CancelledError):
        await g1
    q.put_nowait("payload")
    print(f"  after cancelling the only getter, a new get() -> "
          f"{await asyncio.wait_for(q.get(), 0.1)!r}  (item not lost)")

async def q6_shutdown():
    head(f"Q6 Queue.shutdown() (Python {sys.version_info.major}.{sys.version_info.minor})")
    if not hasattr(asyncio.Queue, "shutdown"):
        print("  not available on this version"); return
    q = asyncio.Queue()
    q.put_nowait("last")
    waiter = asyncio.create_task(q.get())
    await asyncio.sleep(0)
    q.shutdown()
    print(f"  drained after shutdown(): {await waiter!r}")
    try:
        await q.get()
    except asyncio.QueueShutDown:
        print("  a further get() -> QueueShutDown (no sentinel value needed)")
    try:
        q.put_nowait("late")
    except asyncio.QueueShutDown:
        print("  put after shutdown -> QueueShutDown")
    q2 = asyncio.Queue()
    q2.put_nowait("discard-me")
    q2.shutdown(immediate=True)
    print(f"  shutdown(immediate=True): qsize={q2.qsize()} (queued items discarded)")

async def q7_variants():
    head("Q7 FIFO by default; Lifo and Priority exist")
    q = asyncio.Queue()
    for x in (1,2,3): q.put_nowait(x)
    print(f"  Queue      -> {[q.get_nowait() for _ in range(3)]}")
    lq = asyncio.LifoQueue()
    for x in (1,2,3): lq.put_nowait(x)
    print(f"  LifoQueue  -> {[lq.get_nowait() for _ in range(3)]}")
    pq = asyncio.PriorityQueue()
    for x in ((3,"c"),(1,"a"),(2,"b")): pq.put_nowait(x)
    print(f"  PriorityQ  -> {[pq.get_nowait() for _ in range(3)]}")

async def main():
    for p in (q1_basics, q2_backpressure, q3_one_consumer_each, q4_join,
              q5_cancelled_getter, q6_shutdown, q7_variants):
        await p()
asyncio.run(main())
