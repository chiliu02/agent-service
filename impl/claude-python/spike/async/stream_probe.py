import asyncio, sys, time
from contextlib import suppress
def head(t): print(f"\n=== {t}")

async def echo_server():
    async def handle(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            with suppress(Exception):
                writer.close(); await writer.wait_closed()
    return await asyncio.start_server(handle, "127.0.0.1", 0)

async def connect(server):
    port = server.sockets[0].getsockname()[1]
    return await asyncio.open_connection("127.0.0.1", port)

async def r1_read_is_up_to():
    head("R1 read(n) returns UP TO n bytes -- there are no message boundaries")
    srv = await echo_server()
    r, w = await connect(srv)
    w.write(b"hello"); await w.drain()
    w.write(b"world"); await w.drain()
    got = await r.read(100)
    print(f"  two writes of 5 bytes, one read(100) -> {got!r}")
    print("  => a stream is a byte pipe. Framing is YOUR job.")
    w.write(b"0123456789"); await w.drain()
    print(f"  read(4) of a 10-byte write -> {await r.read(4)!r}  (partial)")
    print(f"  readexactly(6)             -> {await r.readexactly(6)!r}  (exact, or raises)")
    w.close(); await w.wait_closed(); srv.close(); await srv.wait_closed()

async def r2_limits():
    head("R2 readline()/readuntil() have a LIMIT (default 64 KiB)")
    srv = await echo_server()
    r, w = await asyncio.open_connection("127.0.0.1", srv.sockets[0].getsockname()[1], limit=64)
    print(f"  opened with limit=64 bytes; reader._limit={r._limit}")
    w.write(b"x" * 200 + b"\n"); await w.drain()
    try:
        await r.readline()
    except ValueError as exc:
        print(f"  a 200-byte line -> {type(exc).__name__}: {exc}")
    with suppress(Exception):
        w.close(); await w.wait_closed()
    srv.close(); await srv.wait_closed()
    print(f"  default limit is {asyncio.streams._DEFAULT_LIMIT} bytes "
          "-- NDJSON longer than this needs an explicit `limit=`")

async def r3_write_never_blocks():
    head("R3 write() is NOT a coroutine -- drain() is the backpressure")
    srv = await echo_server()
    r, w = await connect(srv)
    payload = b"z" * (4 * 1024 * 1024)
    t0 = time.monotonic()
    w.write(payload)                       # no await
    print(f"  write() of 4MB returned in {time.monotonic()-t0:.4f}s (buffered, not sent)")
    t0 = time.monotonic()
    await w.drain()
    print(f"  await drain() took {time.monotonic()-t0:.4f}s (waits for the buffer to drop)")
    total = 0
    while total < len(payload):
        total += len(await r.read(1 << 20))
    print(f"  echoed back {total} bytes")
    w.close(); await w.wait_closed(); srv.close(); await srv.wait_closed()

async def r4_eof():
    head("R4 EOF: read() -> b'', readexactly() -> IncompleteReadError")
    srv = await echo_server()
    r, w = await connect(srv)
    w.write(b"abc"); await w.drain()
    w.write_eof()
    print(f"  read(10) -> {await r.read(10)!r}")
    print(f"  read(10) at EOF -> {await r.read(10)!r}   at_eof()={r.at_eof()}")
    r2, w2 = await connect(srv)
    w2.write(b"ab"); await w2.drain(); w2.write_eof()
    try:
        await r2.readexactly(5)
    except asyncio.IncompleteReadError as exc:
        print(f"  readexactly(5) with 2 available -> IncompleteReadError, partial={exc.partial!r}, expected={exc.expected}")
    for x in (w, w2):
        with suppress(Exception): x.close(); await x.wait_closed()
    srv.close(); await srv.wait_closed()

async def r5_one_reader():
    head("R5 only ONE coroutine may read a StreamReader at a time")
    srv = await echo_server()
    r, w = await connect(srv)
    a = asyncio.create_task(r.readline())
    await asyncio.sleep(0)
    b = asyncio.create_task(r.readline())
    await asyncio.sleep(0)
    try:
        await b
    except RuntimeError as exc:
        print(f"  second concurrent readline() -> RuntimeError: {exc}")
    a.cancel()
    with suppress(BaseException): await a
    w.close()
    with suppress(Exception): await w.wait_closed()
    srv.close(); await srv.wait_closed()

async def r6_close_is_two_steps():
    head("R6 close() is a REQUEST; wait_closed() is the completion")
    srv = await echo_server()
    r, w = await connect(srv)
    w.close()
    print(f"  right after close(): is_closing()={w.is_closing()}")
    await w.wait_closed()
    print(f"  after wait_closed(): is_closing()={w.is_closing()}")
    try:
        w.write(b"late")
        await w.drain()
    except (ConnectionResetError, RuntimeError) as exc:
        print(f"  writing after close -> {type(exc).__name__}: {exc}")
    else:
        print("  writing after close was silently dropped (no error)")
    srv.close(); await srv.wait_closed()

async def r7_subprocess():
    head("R7 create_subprocess_exec gives you the same two objects")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import sys;[print(f'line-{i}',flush=True) for i in range(3)];"
        "sys.stderr.write('a diagnostic with no newline')",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    print(f"  stdout is {type(proc.stdout).__name__}, stdin is {type(proc.stdin).__name__}")
    lines = []
    while line := await proc.stdout.readline():
        lines.append(line.rstrip().decode())
    err = await proc.stderr.read()
    await proc.wait()
    print(f"  readline() framing over stdout -> {lines}")
    print(f"  stderr had NO trailing newline -> {err!r}")
    print("  ^ a readline() loop would have dropped that last partial line at EOF")

async def main():
    for p in (r1_read_is_up_to, r2_limits, r3_write_never_blocks, r4_eof,
              r5_one_reader, r6_close_is_two_steps, r7_subprocess):
        await p()
asyncio.run(main())
