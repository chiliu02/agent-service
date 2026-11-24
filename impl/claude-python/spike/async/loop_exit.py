import asyncio, threading, time
from contextlib import suppress

print("=== what asyncio.run() does on the way out", flush=True)
log = []
async def leftover(name):
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        log.append(f"{name}: cancelled by asyncio.run()"); raise

held = {}
async def main():
    asyncio.create_task(leftover("pending-task"))
    async def gen():
        try:
            yield 1
            yield 2
        finally:
            log.append("asyncgen: finalised")
    g = gen()
    held["g"] = g                      # keep it REACHABLE so the GC hook cannot fire
    async for _ in g:
        break
    await asyncio.sleep(0.02)
    log.append("--- main() returns here ---")

t0 = time.monotonic()
asyncio.run(main())
for line in log: print(f"  {line}", flush=True)
print(f"  run() returned in {time.monotonic()-t0:.3f}s", flush=True)
print("  a still-referenced asyncgen is finalised by shutdown_asyncgens(), AFTER main()", flush=True)
print("  documented order: cancel remaining tasks -> shutdown_asyncgens ->", flush=True)
print("                    shutdown_default_executor -> loop.close()", flush=True)

print("=== does a sleep(0) spinner starve timers? (I assumed yes)", flush=True)
async def busy_vs_timer():
    stop = False
    async def busy():
        while not stop:
            await asyncio.sleep(0)
    b = asyncio.create_task(busy())
    lateness = []
    for _ in range(5):
        t0 = time.perf_counter()
        await asyncio.sleep(0.02)
        lateness.append((time.perf_counter() - t0 - 0.02) * 1000)
    stop = True; b.cancel()
    with suppress(asyncio.CancelledError): await b
    print(f"  20ms timer lateness beside a sleep(0) spinner: "
          f"{[round(x,1) for x in lateness]} ms", flush=True)
    print("  NO -- sleep(0) re-queues to _ready, and _run_once still polls I/O and", flush=True)
    print("  fires timers every iteration. Only a callback that NEVER yields starves them.", flush=True)
asyncio.run(busy_vs_timer())

print("=== call_soon_threadsafe wakes a loop parked in the selector", flush=True)
async def wake():
    loop = asyncio.get_running_loop()
    got = asyncio.Event()
    def from_thread():
        time.sleep(0.05)
        loop.call_soon_threadsafe(got.set)
    threading.Thread(target=from_thread, daemon=True).start()
    t0 = time.perf_counter()
    await got.wait()
    print(f"  loop woke {(time.perf_counter()-t0)*1000:.1f}ms after the thread called it,", flush=True)
    print("  with nothing else scheduled -- the call writes to the self-pipe / IOCP port", flush=True)
    print("  that the selector is blocked on", flush=True)
asyncio.run(wake())
