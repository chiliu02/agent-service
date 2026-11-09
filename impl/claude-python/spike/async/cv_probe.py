import asyncio, contextvars, threading
from contextlib import suppress
def head(t): print(f"\n=== {t}")

request_id = contextvars.ContextVar("request_id")          # no default
depth = contextvars.ContextVar("depth", default=0)         # with default

async def v1_basics():
    head("V1 set/get/reset and the Token")
    try:
        request_id.get()
    except LookupError as exc:
        print(f"  unset, no default -> LookupError: {exc}")
    print(f"  unset, with default  -> depth.get()={depth.get()}")
    tok = request_id.set("req-1")
    print(f"  after set: {request_id.get()!r}; token.old_value={tok.old_value!r}")
    request_id.reset(tok)
    print(f"  after reset: is it back to unset? "
          f"{request_id.get('<<unset>>')!r}")

async def v2_bare_await_shares():
    head("V2 a bare `await` SHARES the caller's context")
    request_id.set("caller")
    async def callee():
        request_id.set("set-by-callee")
    await callee()
    print(f"  after `await callee()`: {request_id.get()!r}   <-- callee's set LEAKED up")

async def v3_task_copies():
    head("V3 a TASK gets a COPY -- its set() cannot escape")
    request_id.set("parent")
    async def child():
        request_id.set("set-by-child")
        return request_id.get()
    inner = await asyncio.create_task(child())
    print(f"  inside the task: {inner!r}")
    print(f"  in the parent:   {request_id.get()!r}   <-- unchanged")
    print("  => the ONLY difference from V2 is create_task. That is the whole model.")

async def v4_inherit_at_creation():
    head("V4 a task inherits the context AS IT WAS AT create_task() time")
    request_id.set("value-A")
    async def child():
        await asyncio.sleep(0.02)
        return request_id.get()
    t = asyncio.create_task(child())          # snapshot taken HERE
    request_id.set("value-B")                 # parent changes afterwards
    print(f"  parent now {request_id.get()!r}, task sees {await t!r}")

async def v5_shallow():
    head("V5 the copy is SHALLOW -- mutable values are shared")
    bag = contextvars.ContextVar("bag")
    bag.set({"seen": []})
    async def child():
        bag.get()["seen"].append("from-child")     # mutate, do not set
        bag.set({"seen": ["rebound-in-child"]})    # rebind: invisible to parent
    await asyncio.create_task(child())
    print(f"  parent's dict: {bag.get()}   <-- mutation crossed, rebinding did not")

async def v6_fanout():
    head("V6 gather / TaskGroup: one copy per child")
    request_id.set("root")
    async def child(n):
        request_id.set(f"child-{n}")
        await asyncio.sleep(0.01)
        return request_id.get()
    print(f"  gather   -> {await asyncio.gather(*(child(n) for n in range(3)))}")
    print(f"  parent   -> {request_id.get()!r}")
    async with asyncio.TaskGroup() as tg:
        ts = [tg.create_task(child(n)) for n in (7, 8)]
    print(f"  TaskGroup-> {[t.result() for t in ts]}; parent {request_id.get()!r}")

async def v7_asyncgen():
    head("V7 async generators: whose context do they run in?")
    marker = contextvars.ContextVar("marker", default="outer")
    async def gen():
        marker.set("set-inside-generator")
        yield marker.get()
        yield marker.get()
    print(f"  before iterating: {marker.get()!r}")
    async for v in gen():
        print(f"    generator sees {v!r}; caller now sees {marker.get()!r}")
    print(f"  after iterating:  {marker.get()!r}")
    print("  => an async generator runs in the CALLER's context. Its set() leaks out.")

    m2 = contextvars.ContextVar("m2", default="outer")
    async def gen2():
        m2.set("from-gen2")
        yield 1
    async def consume():
        async for _ in gen2(): pass
        return m2.get()
    t = asyncio.create_task(consume())
    print(f"  ...but wrap the consumer in a task and it is contained: "
          f"task={await t!r}, parent={m2.get()!r}")

def v8_copy_context():
    head("V8 copy_context() / ctx.run() are SYNC only")
    depth.set(1)
    ctx = contextvars.copy_context()
    def bump():
        depth.set(depth.get() + 100)
        return depth.get()
    print(f"  ctx.run(bump) -> {ctx.run(bump)}; outside still {depth.get()}")
    print(f"  ctx now holds  -> {ctx[depth]}")
    async def coro(): pass
    try:
        ctx.run(coro)
    except Exception as exc:
        print(f"  ctx.run(a coroutine fn) -> returns the coroutine, not the result")
        with suppress(Exception): coro().close()
    try:
        ctx.run(lambda: ctx.run(lambda: None))
    except RuntimeError as exc:
        print(f"  re-entering a Context -> RuntimeError: {exc}")

async def v9_callbacks():
    head("V9 call_soon copies the context too")
    request_id.set("scheduler")
    loop, seen = asyncio.get_running_loop(), []
    loop.call_soon(lambda: seen.append(request_id.get()))
    request_id.set("changed-after-scheduling")
    await asyncio.sleep(0)
    print(f"  callback saw {seen[0]!r} (snapshot at call_soon), parent {request_id.get()!r}")

def v10_threads():
    head("V10 each THREAD starts with an empty context")
    request_id_t = contextvars.ContextVar("rid_t", default="main-default")
    request_id_t.set("set-on-main")
    out = []
    t = threading.Thread(target=lambda: out.append(request_id_t.get()))
    t.start(); t.join()
    print(f"  plain threading.Thread sees {out[0]!r} (its own empty context)")
    print("  (asyncio.to_thread differs -- it copies; see Part 8)")

async def main():
    for p in (v1_basics, v2_bare_await_shares, v3_task_copies, v4_inherit_at_creation,
              v5_shallow, v6_fanout, v7_asyncgen, v9_callbacks):
        await p()
asyncio.run(main())
v8_copy_context()
v10_threads()
