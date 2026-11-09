import asyncio
lock = asyncio.Lock()          # module scope: one object, many loops

async def leak():
    await lock.acquire()       # never released -- e.g. a test that failed mid-way
    return "loop 1 acquired and leaked it"

async def later():
    try:
        async with asyncio.timeout(0.1):
            async with lock:
                return "loop 2 acquired"
    except TimeoutError:
        return "loop 2 TIMED OUT -- state carried over from a dead loop"

print(" ", asyncio.run(leak()))
print(" ", asyncio.run(later()))
print("  no exception was raised at any point; locked() =", lock.locked())

# and a waiter left pending on a dead loop
lock2 = asyncio.Lock()
async def with_waiter():
    await lock2.acquire()
    w = asyncio.create_task(lock2.acquire())
    await asyncio.sleep(0)
    return f"loop A: locked={lock2.locked()} waiters={len(lock2._waiters or [])}"
async def next_loop():
    try:
        async with asyncio.timeout(0.1):
            await lock2.acquire()
        return "loop B acquired"
    except TimeoutError:
        return "loop B timed out"
    except Exception as exc:
        return f"loop B {type(exc).__name__}: {exc}"
print(" ", asyncio.run(with_waiter()))
print(" ", asyncio.run(next_loop()))
