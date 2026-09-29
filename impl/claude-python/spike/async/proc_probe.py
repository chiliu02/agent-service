import asyncio, os, sys, platform
from asyncio.subprocess import PIPE
from contextlib import suppress
PY_ = sys.executable
def head(t): print(f"\n=== {t}", flush=True)

CHILD = r'''
import sys
for line in sys.stdin:
    sys.stdout.write("echo:" + line)
    sys.stdout.flush()
sys.stdout.write("saw EOF, flushed my state\n")
sys.stdout.flush()
'''

async def p1_basics():
    head("what create_subprocess_exec hands back")
    p = await asyncio.create_subprocess_exec(PY_, "-c", "print('hi')",
                                             stdin=PIPE, stdout=PIPE, stderr=PIPE)
    print(f"  pid={p.pid}  returncode before wait: {p.returncode!r}", flush=True)
    print(f"  stdin={type(p.stdin).__name__}  stdout={type(p.stdout).__name__}", flush=True)
    out = await p.stdout.read()
    print(f"  stdout={out!r}; returncode still {p.returncode!r}  (EOF is not exit)", flush=True)
    print(f"  after wait(): {await p.wait()!r}", flush=True)

async def p2_cancel_does_not_kill():
    head("cancelling wait() does NOT kill the process")
    p = await asyncio.create_subprocess_exec(PY_, "-c", "import time;time.sleep(3)")
    with suppress(TimeoutError):
        async with asyncio.timeout(0.2):
            await p.wait()
    await asyncio.sleep(0.2)
    print(f"  after a timed-out wait(): returncode={p.returncode!r} -- still running", flush=True)
    p.kill()
    print(f"  explicit kill() -> rc={await p.wait()}", flush=True)

async def p3_terminate_vs_kill():
    head(f"terminate() vs kill() on {platform.system()}")
    src = ("import signal,time\nsignal.signal(signal.SIGTERM, lambda *a: None)\ntime.sleep(5)\n"
           if os.name != "nt" else "import time;time.sleep(5)")
    p = await asyncio.create_subprocess_exec(PY_, "-c", src)
    await asyncio.sleep(0.3)
    p.terminate()
    try:
        async with asyncio.timeout(1.0):
            print(f"  terminate() -> exited rc={await p.wait()}", flush=True)
    except TimeoutError:
        print("  terminate() IGNORED by a SIGTERM handler; escalating", flush=True)
        p.kill()
        print(f"  kill() -> rc={await p.wait()}", flush=True)
    if os.name == "nt":
        print("  NOTE: on Windows terminate() and kill() are BOTH TerminateProcess.", flush=True)
        print("  There is no SIGTERM, so a child cannot run a graceful handler.", flush=True)

async def p4_orphaned_grandchild():
    head("killing a child does NOT kill its grandchildren")
    here = os.path.dirname(os.path.abspath(__file__))
    marker = os.path.join(here, "_grandchild.txt").replace("\\", "/")
    print(f"  marker: {marker}", flush=True)
    with suppress(FileNotFoundError): os.remove(marker)
    gc_src = f"import time;time.sleep(1.0);open({marker!r},'w').write('I outlived my parent')"
    child_src = f"import subprocess,time\nsubprocess.Popen([{PY_!r},'-c',{gc_src!r}])\ntime.sleep(5)\n"
    p = await asyncio.create_subprocess_exec(PY_, "-c", child_src)
    await asyncio.sleep(0.4)
    p.kill(); await p.wait()
    print(f"  child killed (rc={p.returncode}); waiting for the grandchild...", flush=True)
    await asyncio.sleep(1.6)
    print(f"  grandchild SURVIVED: {open(marker).read()!r}" if os.path.exists(marker)
          else "  grandchild did not run", flush=True)
    with suppress(FileNotFoundError): os.remove(marker)

async def p5_stdin_eof():
    head("closing stdin is the graceful stop (what the SDK tries first)")
    p = await asyncio.create_subprocess_exec(PY_, "-u", "-c", CHILD, stdin=PIPE, stdout=PIPE)
    p.stdin.write(b"one\n"); await p.stdin.drain()
    print(f"  {(await p.stdout.readline()).decode().strip()}", flush=True)
    p.stdin.close()
    print(f"  after closing stdin: {(await p.stdout.readline()).decode().strip()}", flush=True)
    print(f"  exited cleanly rc={await p.wait()}", flush=True)

async def p6_exec_vs_shell():
    head("exec vs shell")
    p = await asyncio.create_subprocess_exec(
        PY_, "-c", "print('exec: argv passed straight to the OS')", stdout=PIPE)
    print(f"  {(await p.communicate())[0].decode().strip()}", flush=True)
    hostile = "world & echo INJECTED" if os.name == "nt" else "world; echo INJECTED"
    p = await asyncio.create_subprocess_shell(f"echo hello {hostile}", stdout=PIPE)
    out, _ = await p.communicate()
    sep = "&" if os.name == "nt" else ";"
    print(f"  shell + hostile input -> {out.decode().strip()!r}", flush=True)
    print(f"  ^ '{sep}' is a command separator to the shell; the second command RAN", flush=True)

async def main():
    for f in (p1_basics, p2_cancel_does_not_kill, p3_terminate_vs_kill,
              p4_orphaned_grandchild, p5_stdin_eof, p6_exec_vs_shell):
        await f()
asyncio.run(main())
