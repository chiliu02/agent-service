import asyncio, sys, time
from asyncio.subprocess import PIPE
PY_ = sys.executable
BIG = "import sys;sys.stdout.write('x'*5_000_000)"

async def main():
    print("--- wait() with an UNDRAINED pipe", flush=True)
    p = await asyncio.create_subprocess_exec(PY_, "-c", BIG, stdout=PIPE)
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(1.0):
            await p.wait()
        print(f"  wait(): returned in {time.monotonic()-t0:.3f}s", flush=True)
    except TimeoutError:
        print("  wait(): still blocked after 1.0s", flush=True)
    p.kill()
    try:
        async with asyncio.timeout(1.0):
            await p.wait()
        print("  kill()+wait(): returned", flush=True)
    except TimeoutError:
        print("  kill()+wait(): STILL blocked -- kill does not free you", flush=True)
    t0, n = time.monotonic(), 0
    while chunk := await p.stdout.read(1 << 16):
        n += len(chunk)
    print(f"  after draining {n} bytes: wait() -> rc={await p.wait()} "
          f"in {time.monotonic()-t0:.3f}s", flush=True)

    print("--- communicate() drains WHILE waiting", flush=True)
    p2 = await asyncio.create_subprocess_exec(PY_, "-c", BIG, stdout=PIPE)
    t0 = time.monotonic()
    out, _ = await p2.communicate()
    print(f"  {len(out)} bytes, rc={p2.returncode}, {time.monotonic()-t0:.3f}s", flush=True)

asyncio.run(main())
