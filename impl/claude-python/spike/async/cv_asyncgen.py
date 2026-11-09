import asyncio, contextvars
rid = contextvars.ContextVar("rid", default="<none>")

async def drain(tag):
    try:
        for i in range(5):
            yield f"{tag}-{i} (rid={rid.get()})"
    finally:
        print(f"    [{tag}] finally runs with rid={rid.get()!r}")

async def main():
    print("=== a generator's `finally` runs in whoever CLOSES it")
    rid.set("request-A")
    g = drain("A")
    async for v in g:
        print(f"    consumed {v}")
        break
    async def background_close():          # api.py's BackgroundTask shape
        rid.set("background-task")
        await g.aclose()
    await asyncio.create_task(background_close())
    print("  ^ created under request-A, finalised under background-task")
    print("  (for the abandoned case, see cv_gc.py: the snapshot is taken when the")
    print("   generator becomes UNREACHABLE, i.e. in whoever dropped the last reference)")

asyncio.run(main())
