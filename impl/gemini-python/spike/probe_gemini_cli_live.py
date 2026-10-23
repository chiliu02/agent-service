"""What a REAL headless turn does -- the stream, the approval modes, the trust gate.

**This one SPENDS MONEY.** Four real turns, roughly 40k tokens of mostly cached
context, cents. `probe_gemini_cli.py` beside it answers everything that is free
and should be run first; this one only asks what a turn can answer.

    GEMINI_API_KEY=... uv run --no-project python probe_gemini_cli_live.py [node_modules]

**The three questions, and why each needed a credential.**

1. **The trust gate.** The free probe saw *warnings* about an untrusted folder
   and read them as a silent degradation. With a key the same folder REFUSES the
   run outright, exit 55, before a single token is spent. A boot gate has to know
   the difference between "works differently" and "does not work".
2. **What `--approval-mode` permits.** The free probe could see the mode reach
   the Policy Engine and could see the ask-user tool removed in headless. Only a
   turn says whether a write actually lands, and the answer differs per mode.
3. **The `stream-json` events as EMITTED.** The free probe read the keys off the
   constructor. A real turn adds one the constructor did not show.

**Each mode runs in its own workspace**, because the question is whether a file
appears, and a shared directory would answer it once for all three.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: **Pinned to the cheapest tier on purpose** (user, 2026-08-11, after the spike
#: cost real money). Two things make this the right default:
#:
#: - The unpinned default is `auto`, which bills **two** models per turn -- a
#:   `utility_router` beside the one that answers. Pinning removes the router
#:   entirely; measured, a one-word turn then bills one model with role `main`.
#: - The real cost was never the prompts. It was capped runs burning
#:   `invoke_agent` subagent loops for the whole timeout, which is why `CAP`
#:   below is short.
#:
#: **Override with `GEMINI_PROBE_MODEL` when the finding is about the model.**
#: The event shapes, exit codes and policy decisions this probe measures are
#: engine behaviour and do not move with it -- but §4's non-determination was
#: measured on `gemini-3.5-flash` and a re-run here will not reproduce those
#: exact numbers.
MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")

#: `default` prompts for approval, and in headless there is nobody to ask.
#: `auto_edit` auto-approves edit tools; `yolo` auto-approves everything.
MODES = ("default", "auto_edit", "yolo")

WRITE_PROMPT = ("Create a file named hello.txt in the current directory containing "
                "exactly HELLO. Then say DONE.")

#: **`default` does not reliably terminate**, so every run here is capped. Nine
#: trials of the identical prompt, across two independent runs of this probe,
#: gave one write, three finishes that did nothing, and five still going at 150 s
#: -- see `TRIALS` below, which is what turns that from an anecdote into a
#: measurement.
#:
#: **A policy fixes it outright**: the same mode with `deny *` plus an allowlist
#: wrote the file three times out of three in ~10 s. `probe_gemini_policy_live.py`
#: is that measurement; this constant only exists because the mode alone needs it.
#:
#: **60 s, not 150 s** (user, 2026-08-11): a run that is going to finish finishes
#: in 10-13 s, so the extra 90 s bought nothing but tokens. The distinction being
#: measured is "finished" versus "still going", and 60 s draws it just as well.
MODE_TIMEOUT = 60.0

#: How many times to repeat `default`. One run of it proves nothing: the whole
#: finding is that consecutive runs disagree.
TRIALS = 3


def _bin(node_modules: Path) -> Path:
    return node_modules / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")


def _fresh(root: Path, name: str) -> Path:
    workspace = root / name
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _run(gemini: Path, workspace: Path, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    """A capped run. A timeout is a RESULT here, not an error.

    Returned as exit code 124 -- `timeout(1)`'s convention -- with whatever the
    process had already written, because under `--approval-mode default` the
    partial event stream is the only evidence of what it was doing when it stopped
    making progress.
    """
    # `-m` goes on EVERY call, here rather than at each call site, so a probe
    # cannot accidentally bill the `auto` router by forgetting it.
    try:
        return subprocess.run([str(gemini), *args, "-m", MODEL], cwd=str(workspace),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        def _text(raw: bytes | str | None) -> str:
            if raw is None:
                return ""
            return raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        return subprocess.CompletedProcess(
            expired.cmd, 124, _text(expired.stdout), _text(expired.stderr))


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

    # --- 1. the trust gate, WITH a valid credential --------------------------
    workspace = _fresh(root, "live-trust")
    proc = _run(gemini, workspace, "-p", "Reply with exactly: OK", "-o", "json")
    print(f"untrusted folder, valid key: exit {proc.returncode}, "
          f"stdout {len(proc.stdout)} B, stderr {len(proc.stderr)} B")
    print(f"  stderr: {proc.stderr.strip()[:160]!r}")
    print("  ^ a REFUSAL, not a degradation: --skip-trust or GEMINI_CLI_TRUST_WORKSPACE=true")

    # --- 2. a successful run writes its envelope to STDOUT -------------------
    proc = _run(gemini, workspace, "-p", "Reply with exactly: OK", "-o", "json", "--skip-trust")
    envelope = json.loads(proc.stdout)
    print(f"\nsuccessful run: exit {proc.returncode}, stdout {len(proc.stdout)} B "
          f"(the FAILED run put its envelope on stderr instead)")
    print(f"  session_id: {envelope.get('session_id')}")
    print(f"  response:   {str(envelope.get('response'))[:60]!r}")
    # The per-model breakdown is `model_usage`, and a one-word turn already bills
    # TWO models -- a router beside the model that answers.
    print(f"  models billed: {sorted(envelope.get('stats', {}).get('models', {}))}")

    # --- 3. stream-json, as actually emitted ---------------------------------
    workspace = _fresh(root, "live-stream")
    (workspace / "seed.txt").write_text("alpha\n", encoding="utf-8")
    proc = _run(gemini, workspace, "-p", "Read the file seed.txt and tell me its contents.",
                "-o", "stream-json", "--skip-trust")
    print("\nstream-json, as EMITTED:")
    seen_keys: dict[str, set] = {}
    for event in _events(proc.stdout):
        kind = event.get("type", "?")
        seen_keys.setdefault(kind, set()).update(k for k in event if k != "type")
        if kind == "tool_use":
            print(f"  tool_use     {event['tool_name']} {json.dumps(event['parameters'])[:70]}")
        elif kind == "tool_result":
            print(f"  tool_result  status={event['status']} output={event.get('output')!r}")
    for kind, keys in seen_keys.items():
        print(f"  keys: {kind:<12} {sorted(keys)}")
    print("  ^ `delta` on `message` is NOT in the constructor the free probe read;")
    print("    `init.model` is the literal string 'auto', not the model that answers.")

    # --- 4. what each approval mode actually PERMITS -------------------------
    #
    # **`default` is repeated, and the repetition IS the finding.** A single run
    # of it produces a confident-looking row that the next run contradicts.
    print(f"\napproval modes -- does the write land?  (default x{TRIALS}, {MODE_TIMEOUT:.0f}s cap)")
    for mode in MODES:
        for trial in range(TRIALS if mode == "default" else 1):
            workspace = _fresh(root, f"live-mode-{mode}-{trial}")
            proc = _run(gemini, workspace, "-p", WRITE_PROMPT, "-o", "stream-json",
                        "--skip-trust", "--approval-mode", mode, timeout=MODE_TIMEOUT)
            events = _events(proc.stdout)
            wrote = (workspace / "hello.txt").exists()
            tools = [e["tool_name"] for e in events if e.get("type") == "tool_use"]
            status = next((e.get("status") for e in events if e.get("type") == "result"), "-")
            outcome = "DID NOT FINISH" if proc.returncode == 124 else f"exit {proc.returncode}"
            label = f"{mode}[{trial}]" if mode == "default" else mode
            print(f"  {label:<12} {outcome:<14} result={status:<8} "
                  f"hello.txt={'YES' if wrote else 'NO':<3}  tools={tools}")
    print("  ^ `auto_edit` and `yolo` write, every time, in seconds.")
    print("    `default` is NOT a boundary and NOT deterministic: across nine trials")
    print("    in two runs it wrote once, finished three times having done nothing,")
    print("    and five times was still running at the cap -- with `invoke_agent` in")
    print("    most of them. When it declines it still exits 0 with result status")
    print("    'success', so a refusal is indistinguishable from a completed task")
    print("    except in the prose. Give it a policy and all of that goes away:")
    print("    see probe_gemini_policy_live.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
