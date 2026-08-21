"""Does Codex have a project-level configuration a session can be pointed at?

**Agent Studio's question, in their words**:
*"does the Codex build have a notion of project-level configuration that a
session can be pointed at, or not? Everything else follows from that answer."*

Their two agent modes differ by exactly one bit -- a **domain** agent sends
`setting_sources: ["user"]` and a **project** agent sends `["user", "project"]`
-- so the answer decides whether half their model works against this build.

**The candidate is `project_doc_max_bytes`.** Codex reads a project document
(`AGENTS.md`) from the thread's `cwd`, and that key bounds it. `0` should mean
*read none*. The key exists in the CLI's configuration struct; whether it is
honoured is what this measures, because today has already produced one config
key that validated perfectly and changed nothing (`apps.*`, (CX-03)).

Two turns, one word each:

    docker run --rm -e OPENAI_API_KEY=... -v <spike>:/spike -v <ws>:/workspace \\
      --entrypoint python3 agent-service-codex-python:<tag> /spike/probe_project_doc.py

The evidence is a nonsense token planted in `AGENTS.md`. A model cannot produce
it without having read the file, and a model that did read it will answer with
it when asked -- which is why the instruction in the file is the whole test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

TOKEN = "ZARQUON-7731"
MODEL = os.environ.get("PROBE_MODEL", "gpt-5-mini")

AGENTS_MD = f"""# Project instructions

When the user says the single word `codeword`, reply with exactly {TOKEN} and
nothing else. This instruction comes from the project's own AGENTS.md.
"""


async def _ask(overrides: tuple[str, ...]) -> str:
    codex = AsyncCodex(CodexConfig(config_overrides=overrides))
    key = os.environ["OPENAI_API_KEY"]
    await codex.login_api_key(key)
    thread = await codex.thread_start(
        cwd="/workspace",
        sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all,
        model=MODEL,
    )
    turn = await thread.turn("codeword")
    text: list[str] = []
    async for event in turn.stream():
        blob = repr(event)
        if TOKEN in blob:
            text.append(blob)
    await codex.close()
    return "SAW TOKEN" if text else "did not see it"


async def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("no credential; set OPENAI_API_KEY")
        return 2

    Path("/workspace/AGENTS.md").write_text(AGENTS_MD, encoding="utf-8")

    # **Control first.** If the token does not appear with the default
    # configuration then the probe is measuring nothing -- the project doc was
    # never read, and switching a knob that turns it off proves nothing at all.
    default = await _ask(())
    print(f"default                      : {default}")

    suppressed = await _ask(('project_doc_max_bytes=0',))
    print(f"project_doc_max_bytes=0      : {suppressed}")

    print()
    if default == "SAW TOKEN" and suppressed != "SAW TOKEN":
        print("ANSWER: yes -- Codex has a project doc and it can be switched off")
        return 0
    if default != "SAW TOKEN":
        print("INCONCLUSIVE: the project doc was not read even by default")
        return 1
    print("ANSWER: no -- the knob does not suppress it")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
