import asyncio, gc, time
from contextlib import suppress

def head(t): print(f"\n=== {t}")
log = []

async def worker(name, delay, boom=None):
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        log.append(f"{name}:cancelled"); raise
    if boom:
        log.append(f"{name}:raising"); raise boom
    log.append(f"{name}:finished")
    return f"{name}-result"

async def g1_gather_failure():
    head("G1 gather: one child raises")
    log.clear()
    try:
        await asyncio.gather(
            worker("fast-fail", 0.02, ValueError("boom")),
            worker("slow-sibling", 0.20),
        )
    except ValueError as exc:
        print(f"  raised {type(exc).__name__}({exc}) -- NOT an ExceptionGroup")
    print(f"  log right after: {log}")
    await asyncio.sleep(0.25)
    print(f"  log 0.25s later:  {log}   <-- the sibling RAN ON, unsupervised")

async def g2_return_exceptions():
    head("G2 gather(return_exceptions=True)")
    log.clear()
    res = await asyncio.gather(
        worker("a", 0.01, ValueError("boom")), worker("b", 0.02),
        return_exceptions=True,
    )
    print(f"  results: {[type(r).__name__ if isinstance(r, BaseException) else r for r in res]}")
    print("  nothing raised; every child ran to completion")

async def g3_order():
    head("G3 gather returns ARGUMENT order, not completion order")
    log.clear()
    res = await asyncio.gather(worker("slow", 0.05), worker("quick", 0.01))
    print(f"  completion order: {log}")
    print(f"  returned order:   {res}")

async def g4_orphan_warning():
    head("G4 the orphaned sibling's exception")
    seen = []
    asyncio.get_running_loop().set_exception_handler(lambda l, c: seen.append(c.get("message")))
    async def both_fail():
        await asyncio.gather(
            worker("first", 0.01, ValueError("first boom")),
            worker("second", 0.03, RuntimeError("second boom")),
        )
    with suppress(ValueError):
        await both_fail()
    await asyncio.sleep(0.1); gc.collect(); await asyncio.sleep(0)
    print(f"  loop exception handler saw: {seen or '(nothing yet)'}")
    print("  the SECOND failure is not in the raised exception at all")
    asyncio.get_running_loop().set_exception_handler(None)

async def g5_gather_cancelled():
    head("G5 cancelling the gather cancels its children")
    log.clear()
    fut = asyncio.gather(worker("x", 1.0), worker("y", 1.0))
    await asyncio.sleep(0.02)
    fut.cancel()
    with suppress(asyncio.CancelledError):
        await fut
    print(f"  {log}")

async def g6_taskgroup_failure():
    head("G6 TaskGroup: one child raises")
    log.clear()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(worker("fast-fail", 0.02, ValueError("boom")))
            tg.create_task(worker("slow-sibling", 0.50))
    except* ValueError as eg:
        print(f"  caught ExceptionGroup via except*: {eg.exceptions}")
    print(f"  log: {log}   <-- sibling was CANCELLED, not orphaned")

async def g7_two_failures():
    head("G7 TaskGroup: two children raise -> both reported")
    log.clear()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(worker("a", 0.01, ValueError("boom-a")))
            tg.create_task(worker("b", 0.01, RuntimeError("boom-b")))
            tg.create_task(worker("c", 0.50))
    except BaseExceptionGroup as eg:
        print(f"  ExceptionGroup with {len(eg.exceptions)}: "
              f"{[f'{type(e).__name__}({e})' for e in eg.exceptions]}")
    print(f"  log: {log}")

async def g8_results():
    head("G8 TaskGroup gives you no results -- keep the task handles")
    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(worker("one", 0.01))
        t2 = tg.create_task(worker("two", 0.02))
    print(f"  read after the block: {t1.result()}, {t2.result()}")

async def g9_timeout_around_taskgroup():
    head("G9 asyncio.timeout around a TaskGroup")
    log.clear()
    try:
        async with asyncio.timeout(0.05):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(worker("long-1", 1.0))
                tg.create_task(worker("long-2", 1.0))
    except BaseException as exc:
        print(f"  escaped: {type(exc).__name__}({exc})")
    print(f"  log: {log}")

async def g10_create_task_after():
    head("G10 create_task after the group's body has finished")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(worker("inside", 0.01))
    try:
        tg.create_task(worker("outside", 0.01))
    except RuntimeError as exc:
        print(f"  RuntimeError: {exc}")

async def g11_body_raises():
    head("G11 the TaskGroup BODY raises")
    log.clear()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(worker("child", 0.50))
            await asyncio.sleep(0.02)
            raise KeyError("the body itself failed")
    except* KeyError as eg:
        print(f"  {eg.exceptions}")
    print(f"  log: {log}   <-- children cancelled by the body's failure")

async def g12_child_cancelled_outside():
    head("G12 a child cancelled from OUTSIDE the group")
    log.clear()
    holder = {}
    try:
        async with asyncio.TaskGroup() as tg:
            holder["t"] = tg.create_task(worker("victim", 0.50))
            tg.create_task(worker("bystander", 0.10))
            await asyncio.sleep(0.02)
            holder["t"].cancel()
    except BaseException as exc:
        print(f"  escaped: {type(exc).__name__}")
    else:
        print("  nothing raised -- a cancelled child is not a group failure")
    print(f"  log: {log}")

async def main():
    for p in (g1_gather_failure, g2_return_exceptions, g3_order, g4_orphan_warning,
              g5_gather_cancelled, g6_taskgroup_failure, g7_two_failures, g8_results,
              g9_timeout_around_taskgroup, g10_create_task_after, g11_body_raises,
              g12_child_cancelled_outside):
        await p()

asyncio.run(main())
