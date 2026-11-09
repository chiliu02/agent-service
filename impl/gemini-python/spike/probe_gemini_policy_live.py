"""The Policy Engine: is it the enforceable tool boundary `--approval-mode` is not?

**This one SPENDS MONEY** -- eight turns, several deliberately capped. Read
GP-18 first: it establishes that `--approval-mode default`
is neither a boundary nor deterministic, which is the problem this probe is
looking for a solution to.

    GEMINI_API_KEY=... uv run --no-project python probe_gemini_policy_live.py [node_modules]

**The five cases, and each one exists because the previous one was not enough.**

1. **Deny one tool** under `yolo`. The obvious reading of `allowed_tools` and it
   DOES NOT HOLD: the agent writes the file through `run_shell_command` instead.
2. **Deny `*`, allow a read tool.** This holds -- and the denied tools come back
   as `tool_not_registered`, meaning they were removed from the registry rather
   than refused at call time.
3. **Deny `*`, allow exactly the task's tools**, under `--approval-mode default`,
   three times. The question is not whether it is permitted but whether it is
   DETERMINISTIC, because without a policy that mode disagrees with itself.
4. **Admin deny against user allow.** Whether the tier model is real.
5. **`ask_user` in headless.** The published documentation says it is treated as
   `deny`. Measured, it is not: the tool stays registered and throws.

**A note on `--admin-policy` versus `--policy`.** Both are "additional" policy
files; the difference is the tier they load at, which decides who wins. Case 4
is the only one that can tell them apart, so the others use `--admin-policy`
throughout for consistency.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WRITE_PROMPT = ("Create a file named hello.txt in the current directory containing "
                "exactly HELLO. Then say DONE.")

#: Denied tools are removed from the registry, so a blocked agent has nothing
#: useful left and will happily spend minutes looking for a way round. Every run
#: here is capped and a timeout is reported as a result.
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


#: How many times to repeat the case that is about determinism rather than
#: permission. One run of case 3 proves nothing.
TRIALS = 3

POLICIES: dict[str, str] = {
    # 1. The naive reading of `allowed_tools`: name the dangerous tool, deny it.
    "deny-write-only": """
[[rule]]
toolName = "write_file"
decision = "deny"
priority = 900
denyMessage = "BLOCKED-BY-SPIKE"
""",
    # 2. Deny-by-default with an allowlist -- the shape that actually holds.
    "deny-all-allow-read": """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900
denyMessage = "BLOCKED-BY-SPIKE"

[[rule]]
toolName = "read_file"
decision = "allow"
priority = 950
""",
    # 3. The same shape, sized to the task. Note that `run_shell_command` is NOT
    #    on it: case 1 is what happens when it is.
    "deny-all-allow-task": """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = ["read_file", "write_file", "list_directory"]
decision = "allow"
priority = 950
""",
    # 4. Two files, two tiers, deliberately contradicting each other. The user
    #    file uses the HIGHEST in-tier priority (999) against the admin file's
    #    900, so if in-tier numbers decided it, the allow would win.
    "admin-deny-all": """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900
""",
    "user-allow-write": """
[[rule]]
toolName = ["read_file", "write_file", "list_directory"]
decision = "allow"
priority = 999
""",
    # 5. `ask_user` where there is nobody to ask.
    "ask-user": """
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = ["read_file", "list_directory"]
decision = "allow"
priority = 950

[[rule]]
toolName = "write_file"
decision = "ask_user"
priority = 960
denyMessage = "ASKUSER-BLOCKED-BY-SPIKE"
""",
}


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


def _events(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _case(gemini: Path, root: Path, label: str, *flags: str) -> None:
    """One turn under `flags`, reported as: did the file appear, and what did it try?"""
    workspace = root / f"policy-{label}"
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "seed.txt").write_text("alpha\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [str(gemini), "-p", WRITE_PROMPT, "-o", "stream-json", "--skip-trust",
             "-m", MODEL, *flags],
            cwd=str(workspace), capture_output=True, text=True, timeout=CAP)
        outcome = f"exit {proc.returncode}"
        stdout = proc.stdout
    except subprocess.TimeoutExpired as expired:
        outcome = "DID NOT FINISH"
        raw = expired.stdout
        stdout = raw if isinstance(raw, str) else (raw or b"").decode("utf-8", "replace")

    events = _events(stdout)
    wrote = (workspace / "hello.txt").exists()
    tools = [e["tool_name"] for e in events if e.get("type") == "tool_use"]
    errors = {
        (e.get("error") or {}).get("type")
        for e in events if e.get("type") == "tool_result" and e.get("error")
    }
    print(f"  {label:<22} {outcome:<14} hello.txt={'YES' if wrote else 'NO':<3} "
          f"tools={tools[:6]}")
    if errors:
        print(f"  {'':<22} tool errors: {sorted(t for t in errors if t)}")


def main(argv: list[str]) -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    node_modules = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    gemini = _bin(node_modules)
    if not gemini.exists():
        print(f"gemini not found at {gemini}", file=sys.stderr)
        return 2

    root = Path("./temp").resolve()
    policy_dir = root / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, body in POLICIES.items():
        path = policy_dir / f"{name}.toml"
        path.write_text(body.lstrip(), encoding="utf-8")
        files[name] = path

    print(f"cap {CAP:.0f}s per turn; policies in {policy_dir}\n")

    print("1. deny ONE tool, under yolo -- does naming the dangerous tool hold?")
    _case(gemini, root, "deny-write-only", "--approval-mode", "yolo",
          "--admin-policy", str(files["deny-write-only"]))
    print("   ^ it does NOT: `write_file` is gone from the registry, so the agent")
    print("     reaches for `run_shell_command` and writes the file with a shell.\n")

    print("2. deny * + allow read_file, under yolo -- does deny-by-default hold?")
    _case(gemini, root, "deny-all-allow-read", "--approval-mode", "yolo",
          "--admin-policy", str(files["deny-all-allow-read"]))
    print("   ^ it HOLDS. Denied tools answer `tool_not_registered`, which is a")
    print("     typed, machine-readable refusal in the event stream.\n")

    print(f"3. deny * + allow the task's tools, under --approval-mode default, x{TRIALS}")
    print("   (without a policy this mode wrote once in nine trials and hung five times)")
    for trial in range(TRIALS):
        _case(gemini, root, f"deny-all-allow-task-{trial}", "--approval-mode", "default",
              "--admin-policy", str(files["deny-all-allow-task"]))
    print("   ^ deterministic, one tool call, ~10s. THIS is the mapping target for")
    print("     `permission_mode` and `allowed_tools`.\n")

    print("4. admin deny * vs user allow write_file -- is the tier model real?")
    _case(gemini, root, "precedence", "--approval-mode", "yolo",
          "--admin-policy", str(files["admin-deny-all"]),
          "--policy", str(files["user-allow-write"]))
    print("   ^ admin wins, despite the user rule carrying the higher in-tier")
    print("     number. Tier beats priority, and it terminates cleanly.\n")

    print("5. ask_user, where there is nobody to ask")
    _case(gemini, root, "ask-user", "--approval-mode", "default",
          "--admin-policy", str(files["ask-user"]))
    print("   ^ the docs say ask_user is 'treated as deny in headless'. It is NOT:")
    print("     the tool stays REGISTERED, the call throws `unhandled_exception`,")
    print("     `denyMessage` never appears, and the turn goes back to hanging.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
