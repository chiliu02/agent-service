"""Does a `--session-id` session survive being resumed? Measured, three turns.

**This one SPENDS MONEY** -- three real turns, a few thousand tokens.

    GEMINI_API_KEY=... uv run --no-project python probe_gemini_sessions_live.py [node_modules]

**Why it exists.** GP-11 records the round trip, established by READING
`SessionSelector.findSession`: `--session-id <uuid>` to create, `--resume <uuid>`
to continue. That is true and it is not the whole story, because `findSession`
resolves against `listSessions()`, and `listSessions()` drops any record whose
`hasResumableContent` is false. So whether a resume works a SECOND time is a
question about what the previous run left on disk, and no amount of reading the
selector answers it.

**What it prints is the disk after every turn**, because the failure this found
is a file that stops being listed and then stops existing. A probe that recorded
only the model's answers would have reported two happy turns and missed it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

#: `Storage.getProjectTempDir()` -- NOT under the project. The session lives in
#: the user's home, keyed by a project identifier, which is why this probe has to
#: go looking for it rather than list the workspace.
GEMINI_HOME = Path(os.path.expanduser("~")) / ".gemini"

#: **Pinned to the cheapest tier on purpose** (user, 2026-08-11, after the spike
#: cost real money). The unpinned default is `auto`, which bills **two** models
#: per turn -- a `utility_router` beside the one that answers -- and pinning
#: removes the router entirely (measured). Override with `GEMINI_PROBE_MODEL`.
#:
#: **The findings here do not move with it.** Policy decisions, tool
#: registration and exit codes are engine behaviour. What DOES move is how often
#: the agent flails, so GP-18's nine-trial tally stays pinned to the
#: `gemini-3.5-flash` numbers it was measured on.
MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")



def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


def _chats_dir(workspace: Path) -> Path:
    return GEMINI_HOME / "tmp" / workspace.name.lower() / "chats"


def _disk(workspace: Path) -> list[str]:
    chats = _chats_dir(workspace)
    if not chats.is_dir():
        return []
    return sorted(
        f"{p.name} ({p.stat().st_size} B)" for p in chats.glob("session-*.jsonl")
    )


def _turn(gemini: Path, workspace: Path, prompt: str, *flags: str) -> dict:
    """One headless turn. `--skip-trust` is mandatory; see the write-up."""
    proc = subprocess.run(
        [str(gemini), "-p", prompt, "-o", "json", "--skip-trust", "-m", MODEL, *flags],
        cwd=str(workspace), capture_output=True, text=True, timeout=300,
    )
    parsed: dict | None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "exit": proc.returncode,
        "stdout_bytes": len(proc.stdout),
        "stderr_bytes": len(proc.stderr),
        "parsed": parsed,
        "stderr": proc.stderr.strip(),
    }


def _report(label: str, turn: dict, workspace: Path, gemini: Path) -> None:
    parsed = turn["parsed"]
    print(f"\n--- {label} ---")
    print(f"  exit {turn['exit']}   stdout {turn['stdout_bytes']} B   stderr {turn['stderr_bytes']} B")
    if parsed:
        print(f"  session_id: {parsed.get('session_id')}")
        print(f"  response:   {str(parsed.get('response'))[:90]!r}")
        if parsed.get("error"):
            print(f"  error:      {json.dumps(parsed['error'])[:200]}")
    else:
        # The failure mode the free probe already flagged: on a bad run stdout is
        # empty and the message is on stderr.
        print(f"  stdout DID NOT PARSE; stderr: {turn['stderr'][:300]!r}")
    print(f"  on disk:    {_disk(workspace) or '(nothing)'}")
    listed = subprocess.run(
        [str(gemini), "--list-sessions", "--skip-trust"],
        cwd=str(workspace), capture_output=True, text=True, timeout=120,
    )
    body = " / ".join(line.strip() for line in listed.stdout.splitlines() if line.strip())
    print(f"  --list-sessions: {body[:220] or '(empty)'}")


def main(argv: list[str]) -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    if not gemini.exists():
        print(f"gemini not found at {gemini}", file=sys.stderr)
        return 2

    # A fresh directory name, so the project identifier -- and therefore the
    # chats directory -- is this run's alone.
    workspace = Path(f"./temp/sess-{uuid.uuid4().hex[:8]}").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    supplied = str(uuid.uuid4())
    print(f"workspace: {workspace.name}")
    print(f"supplied session id: {supplied}")
    print(f"chats dir: {_chats_dir(workspace)}")

    _report("turn 1 -- create with --session-id",
            _turn(gemini, workspace, "Remember this codeword: PLATYPUS. Reply with just: STORED",
                  "--session-id", supplied), workspace, gemini)

    _report("turn 2 -- first --resume",
            _turn(gemini, workspace, "What was the codeword? Reply with just the word.",
                  "--resume", supplied), workspace, gemini)

    _report("turn 3 -- second --resume of the SAME id",
            _turn(gemini, workspace, "What was the codeword? Reply with just the word.",
                  "--resume", supplied), workspace, gemini)

    print("\nThe question this answers: is `options.resume` durable across more "
          "than one continuation on the CLI interface, and does the session stay "
          "visible to --list-sessions while it is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
