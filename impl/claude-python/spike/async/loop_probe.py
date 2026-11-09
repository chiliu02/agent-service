import asyncio, sys, time, platform, statistics
from contextlib import suppress
def head(t): print(f"\n=== {t}", flush=True)

async def l1_everything_is_a_callback():
    head("L1 the loop is a queue of callbacks, drained FIFO")
    loop, order = asyncio.get_running_loop(), []
    for n in "abc":
        loop.call_soon(lambda n=n: order.append(n))
    print(f"  _ready depth right now: {len(loop._ready)}", flush=True)
    await asyncio.sleep(0)
    print(f"  after one turn: {order}  (FIFO)", flush=True)

async def l2_one_turn_is_a_snapshot():
    head("L2 one iteration drains a SNAPSHOT of the queue")
    loop, order = asyncio.get_running_loop(), []
    def outer():
        order.append("outer")
        loop.call_soon(lambda: order.append("added-during-drain"))
    loop.call_soon(outer)
    loop.call_soon(lambda: order.append("already-queued"))
    await asyncio.sleep(0)
    print(f"  after ONE turn:  {order}", flush=True)
    await asyncio.sleep(0)
    print(f"  after TWO turns: {order}", flush=True)
    print("  => a callback scheduled during a drain runs NEXT turn. That is the fairness rule.", flush=True)

async def l3_sleep_zero():
    head("L3 what `await asyncio.sleep(0)` actually does")
    loop, marks = asyncio.get_running_loop(), []
    loop.call_soon(lambda: marks.append("callback"))
    marks.append("before")
    await asyncio.sleep(0)
    marks.append("after")
    print(f"  {marks}  <-- sleep(0) let exactly one queued callback run", flush=True)
    fut = loop.create_future(); fut.set_result(1)
    loop.call_soon(lambda: marks.append("NOT-run"))
    n_before = len(marks)
    await fut
    print(f"  awaiting an ALREADY-DONE future ran {len(marks)-n_before} callbacks "
          "-- it does not yield", flush=True)

async def l4_blocking_stalls_everything():
    head("L4 one blocking callback stalls every timer on the loop")
    late = []
    async def ticker():
        for _ in range(5):
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            late.append((time.perf_counter() - t0 - 0.01) * 1000)
    t = asyncio.create_task(ticker())
    await asyncio.sleep(0.005)
    time.sleep(0.20)                      # a blocking call ON the loop thread
    await t
    print(f"  a 200ms blocking sleep made a 10ms timer late by "
          f"{max(late):.1f}ms (worst of 5)", flush=True)
    print(f"  all lateness (ms): {[round(x,1) for x in late]}", flush=True)

async def l5_timer_resolution():
    head(f"L5 timer granularity on {platform.system()}")
    for target in (0.0005, 0.001, 0.005, 0.020):
        samples = []
        for _ in range(20):
            t0 = time.perf_counter()
            await asyncio.sleep(target)
            samples.append((time.perf_counter() - t0) * 1000)
        print(f"  sleep({target:<6}) -> median {statistics.median(samples):6.2f}ms "
              f"(asked {target*1000:.2f}ms)", flush=True)
    print("  => sub-tick sleeps cost a whole tick. sessions.py:72 records ~15.5ms on Windows.", flush=True)

async def l6_debug_mode():
    head("L6 debug mode names the callback that blocked you")
    import logging
    seen = []
    class Grab(logging.Handler):
        def emit(self, r): seen.append(r.getMessage())
    log = logging.getLogger("asyncio")
    log.addHandler(Grab()); log.setLevel(logging.WARNING)
    loop = asyncio.get_running_loop()
    loop.set_debug(True)
    loop.slow_callback_duration = 0.05
    def hog(): time.sleep(0.12)
    loop.call_soon(hog)
    await asyncio.sleep(0.2)
    loop.set_debug(False)
    print(f"  {seen[0][:110] if seen else '(no warning captured)'}", flush=True)
    print("  enable with loop.set_debug(True) or PYTHONASYNCIODEBUG=1", flush=True)

async def l7_handles():
    head("L7 call_later returns a cancellable handle")
    loop, fired = asyncio.get_running_loop(), []
    h1 = loop.call_later(0.02, lambda: fired.append("kept"))
    h2 = loop.call_later(0.02, lambda: fired.append("cancelled"))
    print(f"  handle types: {type(h1).__name__}; scheduled heap depth={len(loop._scheduled)}", flush=True)
    h2.cancel()
    await asyncio.sleep(0.05)
    print(f"  fired: {fired}", flush=True)

async def l8_which_loop():
    head("L8 which loop implementation is running")
    loop = asyncio.get_running_loop()
    print(f"  {type(loop).__module__}.{type(loop).__name__}", flush=True)
    print(f"  supports add_reader? ", end="", flush=True)
    try:
        import socket
        s = socket.socketpair()[0]
        loop.add_reader(s.fileno(), lambda: None)
        loop.remove_reader(s.fileno()); s.close()
        print("yes", flush=True)
    except NotImplementedError:
        print("NO -- Proactor/IOCP has no add_reader", flush=True)
    except Exception as exc:
        print(f"error: {type(exc).__name__}", flush=True)

async def main():
    for f in (l1_everything_is_a_callback, l2_one_turn_is_a_snapshot, l3_sleep_zero,
              l4_blocking_stalls_everything, l5_timer_resolution, l6_debug_mode,
              l7_handles, l8_which_loop):
        await f()
asyncio.run(main())
