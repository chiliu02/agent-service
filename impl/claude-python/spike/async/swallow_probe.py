import asyncio, time

async def case(label, after):
    t0 = time.monotonic()
    reached_after_block = False
    try:
        async with asyncio.timeout(0.05):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass                      # THE BUG
            await asyncio.sleep(0.15)     # deadline long gone
            if after is not None:
                raise after
        reached_after_block = True
    except BaseException as exc:
        print(f"  {label}: escaped {type(exc).__name__}({exc}) "
              f"cause={type(exc.__cause__).__name__ if exc.__cause__ else None} "
              f"at {time.monotonic()-t0:.3f}s")
        return
    print(f"  {label}: NOTHING raised. Block ran {time.monotonic()-t0:.3f}s "
          f"past a 0.05s deadline; code after it reached={reached_after_block}")

async def honest():
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(0.05):
            await asyncio.sleep(5)
    except TimeoutError:
        print(f"  control (no swallow): TimeoutError at {time.monotonic()-t0:.3f}s")

async def main():
    print("=== swallowing CancelledError inside asyncio.timeout")
    await honest()
    await case("swallow + clean exit ", None)
    await case("swallow + ValueError ", ValueError("something else went wrong"))

asyncio.run(main())
