"""What is the one process still alive after a clean close()?

`probe_open_timeout_leak.py`'s CONTROL reported `alive_after_close: 1` two
seconds after `registry.close()`. S5 measured zero leaked after `disconnect()`,
so either that finding does not hold for a session that never took a turn, or
the straggler is something else entirely and the counting is naive.

Free -- no prompt is ever sent. Prints the identity of anything still running,
because "1 process" is not a finding until it has a name.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    sys.exit("psutil not installed; run `uv sync`")

from agent_service.config import Settings
from agent_service.registry import SessionRegistry
from agent_spec.openapi.schemas import RunOptions

ME = psutil.Process()


def snapshot() -> dict[int, str]:
    out: dict[int, str] = {}
    for c in ME.children(recursive=True):
        try:
            out[c.pid] = f"{c.name()} :: {' '.join(c.cmdline())[:120]}"
        except psutil.Error:
            out[c.pid] = "<gone>"
    return out


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="straggler_") as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        settings = Settings(
            workspace_dir=ws, require_credentials=False, require_mounts=False
        )
        registry = SessionRegistry(settings, open_timeout_s=30.0)

        before = set(snapshot())
        sid = await registry.create(RunOptions(), None)
        during = snapshot()
        print(f"children during the session: {len(set(during) - before)}")
        for pid, what in during.items():
            if pid not in before:
                print(f"  [{pid}] {what}")

        await registry.close(sid)

        for wait in (2, 5, 10):
            await asyncio.sleep(wait if wait == 2 else wait - 2 if wait == 5 else 5)
            now = snapshot()
            survivors = {p: w for p, w in now.items() if p not in before}
            print(f"\n{wait}s after close(): {len(survivors)} survivor(s)")
            for pid, what in survivors.items():
                print(f"  [{pid}] {what}")
            if not survivors:
                print("  -> nothing left; S5 holds for a session with no turn")
                return

        print(
            "\n  -> still alive after 10s. This is a real straggler, not a "
            "slow exit."
        )


if __name__ == "__main__":
    asyncio.run(main())
