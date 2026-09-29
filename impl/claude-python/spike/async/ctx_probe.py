import asyncio
async def main():
    try:
        async with asyncio.timeout(0.05):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0.15)
            raise ValueError("boom")
    except ValueError as exc:
        chain, e = [], exc
        while e is not None:
            chain.append(type(e).__name__)
            e = e.__context__
        print("  __context__ chain:", " -> ".join(chain))
        print("  __cause__:", exc.__cause__)
asyncio.run(main())
