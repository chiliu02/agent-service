import asyncio, time
async def main():
    print("=== timeout(None) vs timeout(0)")
    t0=time.monotonic()
    async with asyncio.timeout(None):
        await asyncio.sleep(0.1)
    print(f"  timeout(None): no deadline, slept {time.monotonic()-t0:.3f}s")
    try:
        async with asyncio.timeout(0):
            await asyncio.sleep(0.1)
    except TimeoutError:
        print("  timeout(0): TimeoutError -- 0 is NOT 'no timeout'")

    print("=== the `as` handle on asyncio.timeout")
    async with asyncio.timeout(10) as t:
        print(f"  type={type(t).__name__} when()={t.when() is not None} "
              f"expired()={t.expired()}")
        print(f"  has reschedule={hasattr(t,'reschedule')}")
        t.reschedule(asyncio.get_running_loop().time() + 5)
        print(f"  rescheduled ok; expired()={t.expired()}")
    print("=== loop clock vs time.monotonic()")
    loop = asyncio.get_running_loop()
    print(f"  loop.time()-time.monotonic() = {loop.time()-time.monotonic():.6f}")

    print("=== task.cancel() is a request, not a completion")
    async def stubborn():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)      # cleanup that outlives the cancel
            raise
    t2 = asyncio.create_task(stubborn())
    await asyncio.sleep(0)
    print(f"  cancel() returned {t2.cancel()}; done immediately? {t2.done()}")
    try:
        await t2
    except asyncio.CancelledError:
        print("  only done after awaiting it")
asyncio.run(main())
