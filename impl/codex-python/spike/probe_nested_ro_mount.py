"""Does a read-only bind mounted UNDERNEATH the workspace survive into the sandbox?

Agent Harness masks subtrees of one worktree so a developer persona cannot edit
the tests and a tester persona cannot edit the sources -- a deny list built from
nested read-only bind mounts, and every file still at exactly one path. That
partition is a property of the CONTAINER's mount namespace. Codex builds a
namespace of its own, so the mask holding outside it proves nothing about the
shell the agent actually runs in. (CX-62) is the answer and the mount table.

**The control is not optional.** A sandbox that refuses the masked write AND the
unmasked one has said nothing, so both are attempted in the same command and
both answers are printed. `mountinfo` from inside the sandbox is the half that
explains whichever answer the writes give.

    docker run --rm --env-file impl/codex-python/.env \
      -v <spike>:/spike -v <ws>:/workspace -v <ws>/src/test:/workspace/src/test:ro \
      --cap-drop ALL --security-opt no-new-privileges:true \
      --security-opt seccomp=unconfined \
      --entrypoint python3 agent-service-codex-python:<tag> \
      /spike/probe_nested_ro_mount.py

The workspace needs `src/main`, `src/test` and a `.git` holding a `MARKER` file.
`--security-opt seccomp=unconfined` is not optional either (CX-01).
"""

from __future__ import annotations

import asyncio
import os
import sys

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

MODEL = os.environ.get("PROBE_MODEL", "gpt-5-mini")

#: Every answer is a literal token in the output rather than something inferred
#: from an exit code -- the same shape (CX-03) used for egress, and for the same
#: reason: "blocked" and "never ran" are otherwise the same observation.
MASK_COMMAND = (
    "touch /workspace/src/test/ESCAPED.txt 2>&1; "
    "[ -f /workspace/src/test/ESCAPED.txt ] && echo MASK:DEFEATED || echo MASK:HELD; "
    "touch /workspace/src/main/CONTROL.txt 2>&1; "
    "[ -f /workspace/src/main/CONTROL.txt ] && echo CONTROL:WRITABLE || echo CONTROL:BLOCKED; "
    "echo ---MOUNTINFO---; "
    "grep ' /workspace' /proc/self/mountinfo | sed 's/ - .*//'"
)

#: The mount table above shows `/workspace/.git` remounted read-only from a
#: device that is not the workspace bind, in a workspace that had no `.git` at
#: all. Whether the REAL directory is read-only or an empty mask changes what a
#: caller can do with it, so it is measured rather than read off a mount line.
GIT_COMMAND = (
    "ls -a /workspace/.git 2>&1 | tr '\n' ' '; echo; "
    "[ -f /workspace/.git/MARKER ] && echo GIT:REAL-CONTENT-VISIBLE || echo GIT:MASKED-EMPTY; "
    "touch /workspace/.git/W 2>&1; "
    "[ -f /workspace/.git/W ] && echo GIT:WRITABLE || echo GIT:READONLY"
)


def _prompt(command: str) -> str:
    return (
        f"Run exactly this shell command: {command}\n"
        "Then report its complete output verbatim, including any error text. "
        "Do not retry, do not use any other tool, and do not explain."
    )


async def _run(label: str, command: str) -> None:
    codex = AsyncCodex(CodexConfig(cwd="/workspace"))
    await codex.login_api_key(os.environ["OPENAI_API_KEY"])
    thread = await codex.thread_start(
        cwd="/workspace",
        sandbox=Sandbox.workspace_write,
        approval_mode=ApprovalMode.deny_all,
        model=MODEL,
    )
    turn = await thread.turn(_prompt(command))

    print(f"\n{'=' * 72}\n== {label}\n{'=' * 72}")
    async for event in turn.stream():
        blob = repr(event)
        # The completed `commandExecution` carries the whole of stdout+stderr in
        # one field; the deltas carry the model's retelling of it, which is not
        # evidence of anything.
        marker = "aggregated_output='"
        if marker in blob:
            body = blob[blob.index(marker) + len(marker) :]
            print(body[: body.index("', command=")].encode().decode("unicode_escape"))
    await codex.close()


async def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("no credential; set OPENAI_API_KEY")
        return 2
    await _run("nested read-only mask, workspace_write", MASK_COMMAND)
    await _run("what the sandbox does to .git", GIT_COMMAND)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
