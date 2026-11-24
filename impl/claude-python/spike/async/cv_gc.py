import asyncio, contextvars, gc
rid = contextvars.ContextVar("rid", default="<none>")

async def drain(tag):
    try:
        yield 1
        yield 2
    finally:
        print(f"    [{tag}] finally saw rid={rid.get()!r}")

async def main():
    print("Which context does an ABANDONED asyncgen's finaliser use?")
    rid.set("A-at-creation")
    g = drain("probe")
    async for _ in g: break            # started, now suspended
    rid.set("B-just-before-del")
    del g                              # <- refcount hits zero here
    rid.set("C-after-del")
    gc.collect()
    rid.set("D-at-collect-time")
    await asyncio.sleep(0.05)
    print("  candidates: A-at-creation / B-just-before-del / C-after-del / D-at-collect-time")

asyncio.run(main())
