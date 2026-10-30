"""L7 — does allowed_tools honour SCOPED permission rules?

L3 showed allowed_tools is per-tool, not per-path: ["Read"] approves every read
anywhere. Claude Code's permission system supports scoped rules like
`Bash(git status:*)`. If ClaudeAgentOptions.allowed_tools honours that syntax the
service gains a real declarative permission layer (Q13).

Test: allow ONLY `Bash(git status:*)`, then ask for `git status` (should run) and
`git log` (should be denied).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query  # noqa: E402


async def run(prompt: str, options: ClaudeAgentOptions) -> tuple[str, ResultMessage | None]:
    text: list[str] = []
    calls: list[str] = []
    result: ResultMessage | None = None
    async with asyncio.timeout(180):
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage):
                result = msg
                continue
            for b in getattr(msg, "content", None) or []:
                n = type(b).__name__
                if n == "TextBlock":
                    text.append(b.text)
                elif n == "ToolUseBlock":
                    calls.append(f"{b.name}({json.dumps(b.input)[:120]})")
    print("  tool calls:")
    for c in calls:
        print(f"    - {c}")
    return "\n".join(text), result


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="l7_") as td:
        ws = Path(td) / "repo"
        ws.mkdir()
        (ws / "a.txt").write_text("hello\n", encoding="utf-8")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "spike@localhost"],
            ["git", "config", "user.name", "spike"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "initial"],
        ):
            subprocess.run(cmd, cwd=ws, check=True, capture_output=True)
        (ws / "b.txt").write_text("uncommitted\n", encoding="utf-8")

        print("=" * 78)
        print("L7 — allowed_tools=['Bash(git status:*)']")
        print("=" * 78)
        print(f"repo: {ws}\n")

        text, result = await run(
            "Do exactly two things, in order, and report the outcome of each:\n"
            "1. Run `git status --short` with the Bash tool.\n"
            "2. Run `git log --oneline` with the Bash tool.\n"
            "State clearly for EACH whether it ran or was denied.",
            ClaudeAgentOptions(
                cwd=str(ws),
                allowed_tools=["Bash(git status:*)"],
                permission_mode="dontAsk",
                setting_sources=[],
                max_turns=8,
            ),
        )

        print(f"\n  text: {text[:900]}\n")
        if result:
            print(f"  subtype           : {result.subtype}")
            print(f"  is_error          : {result.is_error}")
            print(f"  permission_denials: {json.dumps(result.permission_denials, indent=2)[:1200]}")
            print(f"  cost_usd          : {result.total_cost_usd}")

        print("\n>>> L7 VERDICT")
        denials = (result.permission_denials if result else None) or []
        if denials:
            print("    Scoped rules ARE enforced — at least one call was denied.")
            print("    => Q13: allowed_tools supports a real per-command permission layer.")
        else:
            print("    No denials recorded.")
            print("    => Either both commands were allowed (scoping NOT enforced —")
            print("       the bare 'Bash' capability was granted), or the agent never")
            print("       attempted the second command. Check the tool calls above.")


if __name__ == "__main__":
    # NOTE: do NOT set WindowsSelectorEventLoopPolicy here. The SDK spawns the
    # CLI as a subprocess, and the selector loop raises NotImplementedError for
    # subprocesses on Windows. The default Proactor loop is required.
    asyncio.run(main())
