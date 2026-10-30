"""What is `ThreadTokenUsage.last` -- one model call, or one turn? (CX-68)

Turn 1 forces several model calls (tool use); turns 2 and 3 are one word each.
Every `thread/tokenUsage/updated` is printed, so the count per turn and the
relation between consecutive `last` values answer it.

    uv run --env-file .env python spike/probe_context_window.py

**Costs real tokens**: about 110k input, almost all of it cached, on three
turns. The scratch `CODEX_HOME` holds `auth.json` after `login_api_key()`, so it
is removed on the way out.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

MODEL = os.environ.get("PROBE_MODEL", "gpt-5.1")


def _row(u) -> str:
    l, t = u.last, u.total
    return (
        f"last in={l.input_tokens} cached={l.cached_input_tokens} out={l.output_tokens} "
        f"tot={l.total_tokens} | total in={t.input_tokens} out={t.output_tokens} "
        f"tot={t.total_tokens} | window={u.model_context_window}"
    )


async def _turn(thread, prompt: str) -> None:
    print(f"\n=== TURN: {prompt!r}")
    turn = await thread.turn(prompt)
    async for n in turn.stream():
        method = getattr(n, "method", None)
        payload = getattr(n, "payload", None)
        if method == "thread/tokenUsage/updated":
            print("  USAGE", _row(payload.token_usage))
        elif method == "item/completed":
            print("  item", type(payload.item.root if hasattr(payload.item, "root") else payload.item).__name__)
        elif method == "turn/completed":
            print("  completed", payload.turn.status)
            break


async def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="cw-ws-"))
    for i in range(3):
        (work / f"f{i}.txt").write_text(f"file {i}: " + "lorem ipsum " * 400)
    home = Path(tempfile.mkdtemp(prefix="cw-home-"))
    os.environ["CODEX_HOME"] = str(home)
    codex = AsyncCodex(CodexConfig())
    await codex.login_api_key(os.environ["OPENAI_API_KEY"])
    thread = await codex.thread_start(
        cwd=str(work), sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all, model=MODEL,
    )
    await _turn(thread, "List the files here, then read f0.txt, f1.txt and f2.txt one at a time "
                        "with separate shell commands, then tell me how many words each has.")
    await _turn(thread, "Reply with the single word ok.")
    await _turn(thread, "Reply with the single word ok again.")
    await codex.close()
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
