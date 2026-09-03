import asyncio, sys
from contextlib import suppress

async def boom(): raise ValueError("child boom")
async def fine(d=0.01): await asyncio.sleep(d); return "ok"

async def main():
    print(f"=== python {sys.version.split()[0]}")
    print("=== a plain `except ValueError` against a TaskGroup")
    try:
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(boom())
        except ValueError:
            print("  caught by `except ValueError`")
    except BaseExceptionGroup as eg:
        print(f"  NOT caught -- escaped as {type(eg).__name__}: {eg.exceptions}")
    print("  a one-child group is still a group; there is no auto-unwrapping")

    print("=== except* runs EVERY matching clause")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(boom())
            tg.create_task(asyncio.sleep(0, result=None))
            async def kb(): raise KeyError("k")
            tg.create_task(kb())
    except* ValueError as eg:
        print(f"  except* ValueError -> {eg.exceptions}")
    except* KeyError as eg:
        print(f"  except* KeyError   -> {eg.exceptions}")

    print("=== reading a sibling's handle after the group failed")
    t = None
    try:
        async with asyncio.TaskGroup() as tg:
            t = tg.create_task(fine(0.5))
            tg.create_task(boom())
    except* ValueError:
        pass
    print(f"  sibling task: cancelled={t.cancelled()}")
    try:
        t.result()
    except asyncio.CancelledError:
        print("  .result() raises CancelledError -- there is no result to read")

    print("=== empty fan-outs")
    print(f"  gather() with no args -> {await asyncio.gather()}")
    async with asyncio.TaskGroup():
        pass
    print("  empty TaskGroup -> exits immediately")

    print("=== as_completed: results as they arrive")
    tasks = [asyncio.create_task(asyncio.sleep(d, result=f"after {d}")) for d in (0.03, 0.01, 0.02)]
    got = []
    for fut in asyncio.as_completed(tasks):
        got.append(await fut)
    print(f"  {got}")
    print(f"  supports `async for`: {hasattr(asyncio.as_completed(tasks), '__aiter__')}")

asyncio.run(main())
