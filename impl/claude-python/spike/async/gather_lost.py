import asyncio
from contextlib import suppress

async def boom(name, delay, exc):
    await asyncio.sleep(delay)
    raise exc

async def main():
    print("=== the exception gather does NOT give you")
    t1 = asyncio.create_task(boom("first", 0.01, ValueError("first boom")))
    t2 = asyncio.create_task(boom("second", 0.05, RuntimeError("second boom")))
    try:
        await asyncio.gather(t1, t2)
    except BaseException as exc:
        print(f"  gather raised: {type(exc).__name__}({exc})")
    await asyncio.sleep(0.1)
    print(f"  t2 meanwhile: done={t2.done()} exception={t2.exception()!r}")
    print("  ^ that RuntimeError existed, finished, and was never surfaced by gather")

    print("=== outer deadline around gather vs around TaskGroup")
    log = []
    async def slow(n):
        try: await asyncio.sleep(1)
        except asyncio.CancelledError: log.append(f"{n}:cancelled"); raise
    with suppress(TimeoutError):
        async with asyncio.timeout(0.03):
            await asyncio.gather(slow("g1"), slow("g2"))
    print(f"  timeout around gather -> {log} (children cancelled too)")

    print("=== return_exceptions=True and a CANCELLED child")
    async def victim():
        await asyncio.sleep(1)
    v = asyncio.create_task(victim())
    async def canceller():
        await asyncio.sleep(0.02); v.cancel()
    asyncio.create_task(canceller())
    res = await asyncio.gather(v, asyncio.sleep(0.05), return_exceptions=True)
    print(f"  results: {[type(r).__name__ if isinstance(r, BaseException) else r for r in res]}")
    print("  ^ a child's CancelledError became a RESULT -- it did not propagate")

asyncio.run(main())
