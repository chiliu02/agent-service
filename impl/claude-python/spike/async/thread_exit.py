import asyncio, time, threading

print("=== the nested-loop problem test_migrations.py hits")
def sync_that_runs_its_own_loop():          # like alembic's command.upgrade
    async def inner(): return "inner loop ran"
    return asyncio.run(inner())

async def direct():
    try:
        return sync_that_runs_its_own_loop()
    except RuntimeError as exc:
        return f"RuntimeError: {exc}"
async def viathread():
    return await asyncio.to_thread(sync_that_runs_its_own_loop)

print("  called directly from a coroutine :", asyncio.run(direct()))
print("  called via asyncio.to_thread     :", asyncio.run(viathread()))

print("=== asyncio.run() WAITS for the default executor at exit")
def slow(): time.sleep(0.4); print("    [thread] finished")
async def main():
    t = asyncio.create_task(asyncio.to_thread(slow))
    await asyncio.sleep(0.02)
    t.cancel()
    try: await t
    except asyncio.CancelledError: print("    the await was cancelled at ~0.02s")
t0 = time.monotonic()
asyncio.run(main())
print(f"  asyncio.run() returned after {time.monotonic()-t0:.3f}s "
      "-- shutdown_default_executor() joined the thread")
print(f"  live threads now: {[t.name for t in threading.enumerate()]}")
