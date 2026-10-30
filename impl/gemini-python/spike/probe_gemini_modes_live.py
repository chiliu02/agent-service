"""`modes = [...]`, and the typo that voids an entire admin policy.

**Four turns SPEND MONEY; the last two checks are FREE** and are the ones you
would run in production.

    GEMINI_API_KEY=... uv run --no-project python probe_gemini_modes_live.py [node_modules]

**Why this exists.** GP-24 found that the redirection
guard is on under `default` and off under `yolo` -- so the approval mode is a
security-relevant setting, not a preference. `modes = [...]` promises to pin a
rule to a mode, which would stop a caller's `permission_mode` from quietly
changing what a service-imposed policy enforces. It works.

**And then the vocabulary bites.** The `--approval-mode` FLAG takes `auto_edit`.
The policy `modes` FIELD takes `autoEdit`. Both are printed by the tool's own
help and handshake respectively, so writing the flag's spelling into a policy is
the single most likely mistake anyone will make here -- and the consequence is
that **the whole file is discarded**, the run proceeds with no policy at all, and
it exits 0.

**The free preflight at the end is the answer to that**, and it is the reason
this probe is worth keeping rather than reading once.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CAP = 60.0
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


WRITE_PROMPT = ("Create a file named hello.txt containing exactly HELLO. Then say DONE.")

#: A mode-scoped deny sitting on top of a working allowlist. Under `yolo` the
#: third rule fires and `write_file` disappears; under `default` it does not.
SCOPED = """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = ["read_file", "write_file", "list_directory"]
decision = "allow"
priority = 950

[[rule]]
toolName = "write_file"
decision = "deny"
priority = 990
modes = ["yolo"]
"""

#: The SAME intent with the flag's spelling instead of the enum's. Rule 1 is
#: valid and denies everything; rule 2 is not. **Both are discarded.**
TYPO = """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = "write_file"
decision = "deny"
priority = 990
modes = ["auto_edit"]
"""

#: §8's hole, closed by a rule instead of by a mode: deny any shell command
#: containing a redirection. `commandRegex` is anchored just after the opening
#: quote of the serialized command, so `[^"]*>` means "contains a `>`".
NO_REDIR = """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = "run_shell_command"
commandPrefix = "echo"
decision = "allow"
priority = 950

[[rule]]
toolName = "run_shell_command"
commandRegex = '[^"]*>'
decision = "deny"
priority = 990
"""


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


def _turn(gemini: Path, root: Path, label: str, mode: str, policy: Path,
          prompt: str = WRITE_PROMPT) -> None:
    workspace = root / f"modes-{label}"
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [str(gemini), "-p", prompt, "-o", "stream-json", "--skip-trust",
             "--approval-mode", mode, "--admin-policy", str(policy),
             "-m", MODEL],
            cwd=str(workspace), capture_output=True, text=True, timeout=CAP)
        outcome, stdout, stderr = f"exit {proc.returncode}", proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as expired:
        outcome = "DID NOT FINISH"
        stdout = (expired.stdout or b"").decode("utf-8", "replace") if not isinstance(
            expired.stdout, str) else expired.stdout
        stderr = ""

    errors = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool_result" and event.get("error"):
            errors.append(event["error"].get("type"))
    print(f"  {label:<18} mode={mode:<10} {outcome:<10} "
          f"hello.txt={'CREATED' if (workspace / 'hello.txt').exists() else 'no':<8} "
          f"errors={sorted(set(e for e in errors if e)) or '-'}")
    if "Policy file error" in stderr:
        print(f"  {'':<18} STDERR SAYS: the policy file was rejected -- and the run "
              f"continued anyway")


def _preflight(gemini: Path, root: Path, policy: Path) -> bool:
    """Validate a policy file with NO credential and NO turn.

    **This is free**, and it is the only defence against the typo above: the
    error goes to stderr and the exit code stays 0, so nothing in-band tells a
    service that its boundary just evaporated.
    """
    proc = subprocess.run(
        [str(gemini), "--list-sessions", "--skip-trust", "--admin-policy", str(policy)],
        cwd=str(root), capture_output=True, text=True, timeout=90,
        env={k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"})
    return "Policy file error" in proc.stderr


def main(argv: list[str]) -> int:
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    if not gemini.exists():
        print(f"gemini not found at {gemini}", file=sys.stderr)
        return 2
    root = Path("./temp").resolve()
    root.mkdir(parents=True, exist_ok=True)
    policy_dir = root / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, body in (("scoped", SCOPED), ("typo", TYPO), ("no-redir", NO_REDIR)):
        path = policy_dir / f"modes-{name}.toml"
        path.write_text(body.lstrip(), encoding="utf-8")
        files[name] = path

    if os.environ.get("GEMINI_API_KEY"):
        print("1. does `modes = [\"yolo\"]` scope a rule to one mode?")
        _turn(gemini, root, "scoped-yolo", "yolo", files["scoped"])
        _turn(gemini, root, "scoped-default", "default", files["scoped"])
        print("   ^ same file, opposite outcomes. The scoping is exact: under yolo the")
        print("     deny fires and write_file is deregistered; under default it does not.\n")

        print("2. `modes = [\"auto_edit\"]` -- the flag's spelling, not the enum's")
        _turn(gemini, root, "typo", "yolo", files["typo"])
        print("   ^ rule 1 of that file is a VALID `deny *`. It did not apply either.")
        print("     ONE bad value discards the WHOLE file, and the run exits 0.\n")

        print("3. closing §8's redirection hole with a rule instead of a mode")
        _turn(gemini, root, "no-redir", "yolo", files["no-redir"],
              "Run this exact shell command and nothing else: echo HELLO > hello.txt")
        print("   ^ denied under yolo, where the built-in guard is switched off.\n")
    else:
        print("GEMINI_API_KEY not set -- skipping the four paid turns, "
              "running the free half only.\n")

    # --- the free half ------------------------------------------------------
    print("4. the preflight: validate a policy with NO key and NO turn")
    for name in ("scoped", "no-redir", "typo"):
        bad = _preflight(gemini, root, files[name])
        print(f"  {files[name].name:<22} rejected={bad}")
    print("   ^ costs nothing, needs no credential, and is the ONLY way to catch")
    print("     the typo before it silently removes every boundary you configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
