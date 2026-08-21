import asyncio
from contextlib import aclosing

async def drain(tag, n):
    print(f"  [{tag}] start")
    try:
        for i in range(n):
            await asyncio.sleep(0)
            print(f"  [{tag}] produce {i}")
            yield i
        print(f"  [{tag}] exhausted")
    except GeneratorExit:
        print(f"  [{tag}] !! GeneratorExit -- somebody called aclose()")
        raise
    except BaseException as exc:
        print(f"  [{tag}] !! {type(exc).__name__}")
        raise
    finally:
        print(f"  [{tag}] finally (the only line you can rely on)")

async def main():
    print("A. drained to exhaustion:")
    async for x in drain("A", 2):
        pass

    print("B. break, NO aclosing -- watch what is missing:")
    async for x in drain("B", 5):
        break
    await asyncio.sleep(0)

    print("C. break, WITH aclosing:")
    async with aclosing(drain("C", 5)) as g:
        async for x in g:
            break

    print("D. consumer raises, WITH aclosing:")
    try:
        async with aclosing(drain("D", 5)) as g:
            async for x in g:
                raise ValueError("consumer died")
    except ValueError:
        print("  caught outside")

    print("E. `as` binds the generator itself, not a wrapper:")
    g = drain("E", 1)
    async with aclosing(g) as h:
        print(f"  h is g -> {h is g}")

    print("F. aclose() on an exhausted generator is a no-op:")
    g2 = drain("F", 1)
    async for _ in g2:
        pass
    await g2.aclose()
    print("  (nothing from the aclose)")

    print("G. aclose() on a never-started generator runs no code at all:")
    g3 = drain("G", 1)
    await g3.aclose()
    print("  (no 'start', no 'finally')")

asyncio.run(main())
