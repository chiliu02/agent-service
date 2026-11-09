import asyncio, gc, sys
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def f1_taxonomy():
    head("F1 a Task IS a Future")
    print(f"  issubclass(Task, Future) -> {issubclass(asyncio.Task, asyncio.Future)}")
    fut = asyncio.get_running_loop().create_future()
    print(f"  a bare Future: done={fut.done()} -- nothing is computing it")
    fut.set_result("fulfilled from outside")
    print(f"  after set_result: {await fut!r}")
    t = asyncio.create_task(asyncio.sleep(0, result="fulfilled by a coroutine"))
    print(f"  a Task:        {await t!r}")
    print("  => Future = a slot someone else fills. Task = a Future a coroutine fills.")

async def f2_invalid_state():
    head("F2 reading a Future before it is done")
    t = asyncio.create_task(asyncio.sleep(0.05, result="later"))
    for meth in ("result", "exception"):
        try:
            getattr(t, meth)()
        except asyncio.InvalidStateError as exc:
            print(f"  .{meth}() while pending -> InvalidStateError: {exc}")
    try:
        t.set_result("nope")
    except RuntimeError as exc:
        print(f"  .set_result() on a Task  -> RuntimeError: {exc}")
    await t

async def f3_scheduling():
    head("F3 create_task SCHEDULES; it does not start the coroutine")
    log = []
    async def child(): log.append("child ran")
    t = asyncio.create_task(child())
    log.append("after create_task")
    await t
    print(f"  {log}   <-- the body had not run when create_task returned")

async def f4_never_retrieved():
    head("F4 a task that fails and is never awaited")
    seen = []
    asyncio.get_running_loop().set_exception_handler(
        lambda loop, ctx: seen.append(ctx.get("message"))
    )
    async def boom(): raise ValueError("nobody will ask about this")
    t = asyncio.create_task(boom())
    await asyncio.sleep(0.01)
    print(f"  task done={t.done()}, exception STORED = {t.exception()!r}")
    print("  (retrieving it above is what stops the warning)")
    t2 = asyncio.create_task(boom())
    await asyncio.sleep(0.01)
    del t2
    gc.collect(); await asyncio.sleep(0)
    print(f"  never retrieved -> loop handler saw: {seen or '(nothing)'}")
    asyncio.get_running_loop().set_exception_handler(None)

async def f5_cancel_bool():
    head("F5 cancel() returns whether the request was ACCEPTED")
    t = asyncio.create_task(asyncio.sleep(1))
    await asyncio.sleep(0)
    print(f"  cancel() on a pending task -> {t.cancel()}")
    with suppress(asyncio.CancelledError): await t
    print(f"  cancel() on a finished task -> {t.cancel()}")
    print(f"  done={t.done()} cancelled={t.cancelled()}")

async def f6_swallowed_cancel():
    head("F6 a task that SWALLOWS its cancellation is not 'cancelled'")
    async def stubborn():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return "I decided to finish normally"
    t = asyncio.create_task(stubborn())
    await asyncio.sleep(0)
    accepted = t.cancel()
    result = await t
    print(f"  cancel() returned {accepted}, but result={result!r}")
    print(f"  done={t.done()} cancelled={t.cancelled()}  <-- cancel() is a REQUEST")

async def f7_done_callback():
    head("F7 add_done_callback: fires on success, failure AND cancellation")
    log = []
    async def ok(): return 1
    async def bad(): raise ValueError("x")
    async def slow(): await asyncio.sleep(1)
    for name, coro in (("ok", ok()), ("bad", bad()), ("slow", slow())):
        t = asyncio.create_task(coro)
        t.add_done_callback(lambda task, n=name: log.append((n, task.cancelled())))
        if name == "slow":
            await asyncio.sleep(0); t.cancel()
        with suppress(BaseException): await t
    await asyncio.sleep(0)
    print(f"  {log}")
    t = asyncio.create_task(ok()); await t
    fired = []
    t.add_done_callback(lambda task: fired.append("late"))
    print(f"  added AFTER completion, before yielding: {fired}")
    await asyncio.sleep(0)
    print(f"  ...after one loop turn: {fired}  <-- scheduled via call_soon, never immediate")

async def f8_await_twice():
    head("F8 awaiting a Task twice is fine (unlike a generator)")
    t = asyncio.create_task(asyncio.sleep(0, result="v"))
    print(f"  {await t!r}, {await t!r}, .result()={t.result()!r}")
    c = asyncio.create_task(asyncio.sleep(1))
    await asyncio.sleep(0); c.cancel()
    for i in range(2):
        try: await c
        except asyncio.CancelledError: print(f"  awaiting a cancelled task (#{i+1}) -> CancelledError")

async def f9_weakref():
    head("F9 the loop keeps only a WEAK reference to a task")
    ran = []
    async def worker(n):
        await asyncio.sleep(0.01)
        ran.append(n)
    for n in range(200):
        asyncio.create_task(worker(n))     # no reference kept anywhere
    for _ in range(5):
        gc.collect()
        await asyncio.sleep(0)
    await asyncio.sleep(0.1)
    print(f"  spawned 200 unreferenced tasks, {len(ran)} ran to completion")
    print(f"  live tasks now: {len(asyncio.all_tasks()) - 1}")
    print("  (not reproducing a loss here does NOT prove it cannot happen -- see the notes)")

async def f10_introspection():
    head("F10 naming and enumerating")
    async def child(): await asyncio.sleep(0.02)
    t = asyncio.create_task(child(), name="reaper")
    print(f"  get_name()      -> {t.get_name()!r}")
    print(f"  current_task()  -> {asyncio.current_task().get_name()!r}")
    print(f"  all_tasks()     -> {sorted(x.get_name() for x in asyncio.all_tasks())}")
    await t

async def f11_ensure_future():
    head("F11 ensure_future vs create_task")
    async def c(): return 1
    t = asyncio.ensure_future(c())
    print(f"  ensure_future(coroutine) -> {type(t).__name__}")
    fut = asyncio.get_running_loop().create_future(); fut.set_result(2)
    print(f"  ensure_future(future)    -> {type(asyncio.ensure_future(fut)).__name__} "
          f"(same object: {asyncio.ensure_future(fut) is fut})")
    try:
        asyncio.create_task(fut)
    except TypeError as exc:
        print(f"  create_task(future)      -> TypeError: {str(exc)[:60]}...")
    await t

async def main():
    for p in (f1_taxonomy, f2_invalid_state, f3_scheduling, f4_never_retrieved,
              f5_cancel_bool, f6_swallowed_cancel, f7_done_callback, f8_await_twice,
              f9_weakref, f10_introspection, f11_ensure_future):
        await p()
asyncio.run(main())
