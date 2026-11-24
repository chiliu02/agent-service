"""Does a session id get consumed by CREATION, or only by a TURN?

AS-27 in the specification asserts that a create returning 504 may have consumed the
supplied `sdk_session_id`, and ST-5 obliges the consumer to mint a fresh UUID
per ATTEMPT because of it. That was INFERRED from probe P1 -- which measured a
reused id being refused after a turn had actually run -- and never measured for
creation alone. If creation does not burn the id, ST-5 is complexity the
consumer does not need.

Free. No prompt is ever sent in cases A and B.

  A. Time out `create()` inside the measured spawn window, then create again
     with the SAME id and a generous timeout. Refused, or fine?
  B. Create successfully, close without taking a turn, then reuse the id.
  C. Control: create, take NO turn... then reuse. (Same as B; kept separate so
     a difference between "timed out" and "clean" is visible.)

    uv run python spike/probe_id_burn.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

from agent_service.config import Settings
from agent_service.registry import SessionOpenTimeout, SessionRegistry
from agent_spec.openapi.schemas import RunOptions

RESULTS: list[tuple[str, str]] = []


def record(case: str, finding: str) -> None:
    RESULTS.append((case, finding))
    print(f"\n>>> {case}: {finding}\n", flush=True)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def settings_for(ws: Path) -> Settings:
    return Settings(workspace_dir=ws, require_credentials=False, require_mounts=False)


async def reuse(ws: Path, sdk_id: str) -> str:
    """Try to open a session on `sdk_id` with a generous timeout."""
    registry = SessionRegistry(settings_for(ws), open_timeout_s=60.0)
    try:
        sid = await registry.create(RunOptions(), None, sdk_id)
    except Exception as exc:  # noqa: BLE001
        return f"REFUSED -- {type(exc).__name__}: {str(exc)[:120]}"
    await registry.close(sid)
    return "ACCEPTED"


async def case_a(ws: Path) -> None:
    """A create that TIMES OUT, then the same id again."""
    rule("A -- id supplied to a create that times out, then reused")
    sdk_id = str(uuid.uuid4())
    print(f"  id: {sdk_id}")

    # 2.0s lands after the CLI spawns (~0.46s) and before open() returns
    # (~3.47s) -- the window T1 measured.
    registry = SessionRegistry(settings_for(ws), open_timeout_s=2.0)
    try:
        await registry.create(RunOptions(), None, sdk_id)
        first = "create SUCCEEDED (timeout did not fire -- inconclusive)"
    except SessionOpenTimeout:
        first = "SessionOpenTimeout, as intended"
    except Exception as exc:  # noqa: BLE001
        first = f"{type(exc).__name__}: {exc}"
    print(f"  first attempt : {first}")

    second = await reuse(ws, sdk_id)
    print(f"  reuse         : {second}")
    record("A", f"after a timed-out create, reusing the id is {second}")


async def case_b(ws: Path) -> None:
    """A create that SUCCEEDS but takes no turn, then the same id again."""
    rule("B -- id used by a successful create with NO turn, then reused")
    sdk_id = str(uuid.uuid4())
    print(f"  id: {sdk_id}")

    registry = SessionRegistry(settings_for(ws), open_timeout_s=60.0)
    sid = await registry.create(RunOptions(), None, sdk_id)
    await registry.close(sid)
    print("  first attempt : created and closed, no turn taken")

    second = await reuse(ws, sdk_id)
    print(f"  reuse         : {second}")
    record("B", f"after a create with no turn, reusing the id is {second}")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="idburn_") as td:
        root = Path(td)
        for name, fn in (("A", case_a), ("B", case_b)):
            ws = root / name.lower()
            ws.mkdir()
            try:
                async with asyncio.timeout(300):
                    await fn(ws)
            except TimeoutError:
                record(name, "TIMED OUT")
            except Exception as exc:  # noqa: BLE001
                record(name, f"RAISED {type(exc).__name__}: {exc}")

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")
    print(
        "\n  AS-27 / ST-5 hold only if a create ALONE can burn the id. If both "
        "cases are ACCEPTED, the fresh-per-attempt rule is unnecessary and the "
        "clause should say so."
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
