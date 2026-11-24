"""Does a RESUMED thread report how full its window is, before any turn? (CX-70)

**Why this exists.** Agent Harness reads `context_usage` from a session opened
with `resume`, before that session's first turn, to decide whether the
conversation still fits. CX-68 published the value from the turn stream only,
so it is `null` until a turn runs in the new process. This probe answers
whether Codex itself supplies the number on resume, without a turn.

**What it does, in three app-server processes sharing one scratch CODEX_HOME:**

1. **Process 1** starts a thread and takes two turns. Turn 1 forces several
   model calls (three files, one shell command each); turn 2 is one word. Every
   `thread/tokenUsage/updated` is printed.
2. **Process 2** resumes the thread and sends NO turn. It prints every
   notification for `WAIT_S` seconds, and each line says whether it arrived
   before or after `thread/resume` returned. Then it asks Codex to compact the
   thread (`thread/compact/start`) and prints what that sends.
3. **Process 3** resumes the compacted thread, again with no turn, and prints
   the same. Then it takes one one-word turn, so the first input after the
   compaction can be compared with the figure the compaction reported.

After each process the rollout file is read and its `token_count` records are
counted, so the rollout and the notifications can be compared directly.

**How notifications are seen.** The SDK routes a notification that carries a
`turnId` to that turn's queue, and holds it in a pending queue when no turn of
that id is registered. A resume registers no turn, so the probe wraps the
SDK's private `MessageRouter.route_notification` to see everything. That is a
probe technique, not a recommendation for the build.

**Run it** from `impl/codex-python`:

    uv run --env-file .env python spike/probe_resume_context.py

**Or inside the image**, which is where the build runs. Turn 1 runs shell
commands, so the container needs the `seccomp=unconfined` the build documents
(CX-01):

    docker run --rm --name codex-ctx-probe --security-opt seccomp=unconfined \
      --cap-drop ALL -e OPENAI_API_KEY -v "<this spike dir>:/probe:ro" \
      --entrypoint python agent-service-codex-python:<version> \
      -u /probe/probe_resume_context.py

`PROBE_MODEL` overrides the model (default `gpt-5.1`, the one CX-68 used);
`PROBE_WAIT_S` overrides the wait after each resume (default 8).

**Costs real tokens**: roughly 100k input tokens, most of them cached, across
about eight model calls plus one compaction call. Codex reports no cost figure.
The scratch CODEX_HOME holds `auth.json` after `login_api_key()`, so it is
deleted on exit unless `PROBE_KEEP=1`.

**Expected output, if CX-70 still holds:** process 2 prints one
`thread/tokenUsage/updated` whose `last` equals the last update of process 1,
with the old turn's `turnId`, around the moment `thread/resume` returns (before
it on the host, and once just after it in the image: the order is a race); the
rollout's
`token_count` count equals the number of updates process 1 received; the
compaction reports `last.input_tokens` 0 and a `last.total_tokens` that the
next turn's input starts from; and process 3 replays that compacted figure.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox
from openai_codex import _message_router as router

MODEL = os.environ.get("PROBE_MODEL", "gpt-5.1")
WAIT_S = float(os.environ.get("PROBE_WAIT_S", "8"))

_lock = threading.Lock()
_seen: list[tuple[float, str, object]] = []
_original = router.MessageRouter.route_notification


def _spy(self, notification):  # noqa: ANN001
    with _lock:
        _seen.append((time.monotonic(), notification.method, notification.payload))
    return _original(self, notification)


router.MessageRouter.route_notification = _spy


def _drain() -> list[tuple[float, str, object]]:
    with _lock:
        out = list(_seen)
        _seen.clear()
    return out


def _usage(payload) -> str:  # noqa: ANN001
    u = payload.token_usage
    return (f"last.in={u.last.input_tokens} last.out={u.last.output_tokens} "
            f"last.total={u.last.total_tokens} total.total={u.total.total_tokens} "
            f"window={u.model_context_window} turnId={payload.turn_id}")


def _print(label: str, rows, mark: float | None = None) -> list[str]:
    """Print notifications; return the usage lines, for comparison."""
    print(f"\n--- {label}: {len(rows)} notification(s)")
    usages = []
    for t, method, payload in rows:
        when = "" if mark is None else ("  [before resume returned]" if t < mark
                                        else f"  [+{t - mark:.2f}s after resume returned]")
        if method == "thread/tokenUsage/updated":
            line = _usage(payload)
            usages.append(line)
            print(f"  {method}  {line}{when}")
        else:
            print(f"  {method}{when}")
    return usages


def _rollout_token_counts(home: Path) -> list[dict]:
    files = sorted(home.glob("sessions/**/rollout-*.jsonl"))
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            p = rec.get("payload") or {}
            if rec.get("type") == "event_msg" and p.get("type") == "token_count" and p.get("info"):
                out.append(p["info"])
    return out


def _print_rollout(home: Path) -> None:
    counts = _rollout_token_counts(home)
    print(f"  rollout: {len(counts)} token_count record(s) with info")
    for info in counts:
        last = info.get("last_token_usage") or {}
        print(f"    last.total={last.get('total_tokens')} "
              f"window={info.get('model_context_window')}")


def _client(home: Path, work: Path) -> Codex:
    codex = Codex(CodexConfig(cwd=str(work), env={**os.environ, "CODEX_HOME": str(home)}))
    codex.login_api_key(os.environ["OPENAI_API_KEY"])
    return codex


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    home = Path(tempfile.mkdtemp(prefix="cx-resume-home-")).resolve()
    work = Path(tempfile.mkdtemp(prefix="cx-resume-ws-")).resolve()
    for i in range(3):
        (work / f"f{i}.txt").write_text(f"file {i}: " + "lorem ipsum " * 400)
    print(f"model={MODEL} CODEX_HOME={home}")
    try:
        # --- process 1: two turns --------------------------------------------
        with _client(home, work) as codex:
            thread = codex.thread_start(cwd=str(work), sandbox=Sandbox.read_only,
                                        approval_mode=ApprovalMode.deny_all, model=MODEL)
            thread_id = thread.id
            _drain()
            thread.run("List the files here, then read f0.txt, f1.txt and f2.txt one at a "
                       "time with separate shell commands, then say how many words each has.")
            turn1 = _print("process 1, turn 1 (several model calls)", _drain())
            thread.run("Reply with the single word ok.")
            turn2 = _print("process 1, turn 2 (one word)", _drain())
        _print_rollout(home)
        reference = (turn1 + turn2)[-1] if (turn1 + turn2) else None
        print(f"\n  REFERENCE (last update of process 1): {reference}")

        # --- process 2: resume, no turn; then compact -------------------------
        with _client(home, work) as codex:
            _drain()
            resumed = codex.thread_resume(thread_id)
            mark = time.monotonic()
            time.sleep(WAIT_S)
            got = _print("process 2, resume, NO turn", _drain(), mark)
            print(f"  MATCHES REFERENCE: {bool(got) and got[-1] == reference}")
            resumed.compact()
            time.sleep(WAIT_S * 3)
            _print("process 2, after thread/compact/start", _drain())
        _print_rollout(home)

        # --- process 3: resume the compacted thread, no turn ------------------
        with _client(home, work) as codex:
            _drain()
            resumed = codex.thread_resume(thread_id)
            mark = time.monotonic()
            time.sleep(WAIT_S)
            _print("process 3, resume after compaction, NO turn", _drain(), mark)
            # What does the compacted figure mean? The next call's input should
            # start from it if it is the size of the history after compaction.
            resumed.run("Reply with the single word ok.")
            _print("process 3, one-word turn after compaction", _drain())
    finally:
        if os.environ.get("PROBE_KEEP") != "1":
            shutil.rmtree(home, ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\nkept: {home} {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
