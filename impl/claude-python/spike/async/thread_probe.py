import asyncio, concurrent.futures as cf, contextvars, functools, threading, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

def blocking(label, secs=0.1):
    time.sleep(secs)                       # real blocking, releases the GIL
    return f"{label}@{threading.current_thread().name}"

def cpu(n=8_000_000):
    x = 0
    for i in range(n): x += i
    return x

async def t1_it_is_a_thread():
    head("T1 to_thread really is another thread")
    print(f"  loop thread : {threading.current_thread().name}")
    print(f"  worker      : {await asyncio.to_thread(blocking, 'job', 0.01)}")

async def t2_cancel_does_not_stop_it():
    head("T2 CANCELLATION DOES NOT STOP THE THREAD")
    finished = threading.Event()
    def stubborn():
        time.sleep(0.3)
        finished.set()
        return "ran to completion anyway"
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            await asyncio.to_thread(stubborn)
    except TimeoutError:
        print(f"  TimeoutError at {time.monotonic()-t0:.3f}s -- the await gave up")
    print(f"  thread finished yet? {finished.is_set()}  (still running)")
    await asyncio.sleep(0.35)
    print(f"  thread finished now?  {finished.is_set()}  <-- it never noticed")
    print("  => a deadline over to_thread bounds YOUR WAIT, not the work")

async def t3_io_parallelises():
    head("T3 blocking I/O DOES overlap in threads")
    t0 = time.monotonic()
    out = await asyncio.gather(*(asyncio.to_thread(blocking, f"j{i}", 0.1) for i in range(4)))
    print(f"  4 x 0.1s sleeps -> {time.monotonic()-t0:.3f}s wall (not 0.4s)")
    print(f"  distinct threads: {len({o.split('@')[1] for o in out})}")

async def t4_cpu_does_not():
    head("T4 CPU-bound work does NOT (the GIL is still there)")
    t0 = time.monotonic(); cpu(); cpu(); one = time.monotonic()-t0
    t0 = time.monotonic()
    await asyncio.gather(*(asyncio.to_thread(cpu) for _ in range(2)))
    two = time.monotonic()-t0
    print(f"  2x sequential in-loop : {one:.3f}s")
    print(f"  2x via to_thread      : {two:.3f}s  (speedup {one/two:.2f}x)")
    print("  => threads are for BLOCKING calls; use a ProcessPoolExecutor for CPU")

async def t5_pool_is_finite():
    head("T5 the default pool is finite -- excess work QUEUES")
    pool = cf.ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    await asyncio.gather(*(loop.run_in_executor(pool, blocking, f"j{i}", 0.1) for i in range(6)))
    print(f"  6 jobs x 0.1s through a 2-worker pool -> {time.monotonic()-t0:.3f}s (3 waves)")
    print(f"  default pool max_workers = {cf.ThreadPoolExecutor()._max_workers} "
          "(min(32, cpu+4)); saturating it stalls EVERY to_thread in the process")
    pool.shutdown(wait=False)

cv = contextvars.ContextVar("cv", default="unset")

async def t6_contextvars():
    head("T6 to_thread propagates contextvars; run_in_executor does not")
    cv.set("request-42")
    print(f"  to_thread        -> {await asyncio.to_thread(cv.get)!r}")
    loop = asyncio.get_running_loop()
    print(f"  run_in_executor  -> {await loop.run_in_executor(None, cv.get)!r}")

async def t7_kwargs():
    head("T7 to_thread takes kwargs; run_in_executor takes none")
    print(f"  to_thread kwargs -> {await asyncio.to_thread(blocking, 'kw', secs=0.01)}")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, blocking, "kw", secs=0.01)
    except TypeError as exc:
        print(f"  run_in_executor kwargs -> TypeError: {exc}")
    print(f"  ...so: {await loop.run_in_executor(None, functools.partial(blocking, 'kw', secs=0.01))}")

async def t8_bridge_back():
    head("T8 calling back INTO the loop from a thread")
    loop = asyncio.get_running_loop()
    ev = asyncio.Event()
    def worker():
        time.sleep(0.02)
        loop.call_soon_threadsafe(ev.set)      # the ONLY safe way
        return "signalled via call_soon_threadsafe"
    task = asyncio.create_task(asyncio.to_thread(worker))
    await asyncio.wait_for(ev.wait(), 1.0)
    print(f"  {await task}")
    async def coro(): return "coroutine ran on the loop"
    def worker2():
        fut = asyncio.run_coroutine_threadsafe(coro(), loop)
        return fut.result(timeout=1)
    print(f"  {await asyncio.to_thread(worker2)}")

async def t9_exceptions():
    head("T9 exceptions cross the boundary normally")
    def bad(): raise ValueError("from the worker thread")
    try:
        await asyncio.to_thread(bad)
    except ValueError as exc:
        print(f"  {type(exc).__name__}: {exc}")

asyncio.run(t1_it_is_a_thread())
asyncio.run(t2_cancel_does_not_stop_it())
for p in (t3_io_parallelises, t4_cpu_does_not, t5_pool_is_finite, t6_contextvars,
          t7_kwargs, t8_bridge_back, t9_exceptions):
    asyncio.run(p())
