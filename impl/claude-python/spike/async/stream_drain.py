import asyncio, time
from contextlib import suppress

async def main():
    print("=== write() buffers without limit; drain() is the only backpressure")
    stalled = asyncio.Event()
    async def deaf(reader, writer):        # accepts, then NEVER reads
        await stalled.wait()
        with suppress(Exception):
            writer.close(); await writer.wait_closed()
    srv = await asyncio.start_server(deaf, "127.0.0.1", 0)
    r, w = await asyncio.open_connection("127.0.0.1", srv.sockets[0].getsockname()[1])
    tr = w.transport
    low, high = tr.get_write_buffer_limits()
    print(f"  transport water marks: low={low} high={high} bytes")

    chunk, written, t0 = b"z" * (256 * 1024), 0, time.monotonic()
    for _ in range(64):                    # 16 MiB aimed at a peer that never reads
        w.write(chunk); written += len(chunk)
    print(f"  wrote {written//1024} KiB with NO await in {time.monotonic()-t0:.4f}s")
    print(f"  buffered now: {tr.get_write_buffer_size()} bytes "
          f"({tr.get_write_buffer_size()//high}x the high-water mark)")
    print("  ^ write() never refuses and never blocks, whatever the marks say")

    t0 = time.monotonic()
    try:
        async with asyncio.timeout(1.0):
            await w.drain()
        print(f"  drain() returned after {time.monotonic()-t0:.3f}s; "
              f"buffered now {tr.get_write_buffer_size()} bytes")
        print("  (loopback + OS socket buffers absorbed it here; against a slow")
        print("   real peer this is where the producer gets throttled)")
    except TimeoutError:
        print(f"  drain() still waiting after {time.monotonic()-t0:.3f}s")
    stalled.set()
    with suppress(Exception):
        w.close(); await w.wait_closed()
    srv.close(); await srv.wait_closed()

asyncio.run(main())
