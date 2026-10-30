"""How full is a RESUMED Gemini conversation's window, before its next turn? (GP-77)

**SPENDS MONEY, a little.** Seven short turns on a pinned cheap model, one of
them with a tool call that puts about 30k tokens of file into the history, and
one compression. About 400k input tokens in all, which is under 0.15 USD on
`gemini-3.1-flash-lite`. Step G is keyless and free.

**Why this exists.** Agent Harness reads `context_usage` from a session opened
with `resume`, before that session's first turn. This build spawns the CLI per
turn and resumes with `--session-file` from a copy of the last turn's
transcript (GP-11), so the copy is the one thing it holds between turns. This
probe measures whether that copy carries the number, whether the number
predicts the next prompt, and what a compression does to both.

**Each turn is run the way the build runs one**: `-p <prompt> -o stream-json`,
the model pinned with `-m`, its own `HOME`, `GEMINI_CLI_TRUST_WORKSPACE=true`
(GP-08), and `--session-file <copy>` to resume. After each turn the newest
`session-*.jsonl` under that `HOME` is copied out, as the build does.

**What it measures.** Every turn prints the `result` event's `stats`, every
`gemini` record's `tokens` in the transcript it produced (a record is written
again when it gains tool calls, so the LAST line per `id` counts), and the
transcript's line kinds. Every resumed turn also prints how its first model
call's `input` compares with the previous transcript's last record, as
`input + output` and as `total` (which adds `thoughts`). That comparison is
what decides whether a stored transcript can say how full the next prompt is.

- **A.** A one-word turn, fresh.
- **B.** A one-word turn resumed from A: a resume with no tool call.
- **C.** Resumed from B, a turn that reads `big.txt` (about `BIG_LINES` lines)
  with a tool, so it makes at least two calls and the history grows by the
  file. Shows that `stats` is the SUM of the calls, not a size.
- **D.** A one-word turn resumed from C: a resume after a tool call. Measured
  2026-10-20: C's transcript stores the tool result twice (in the `gemini`
  record's `toolCalls[].result` and again as a `user` message), and D's
  `input` is one copy of the file larger than C's last call (GP-78).
- **D2.** A one-word turn resumed from D: does the prompt stay there, or gain
  another copy with each resume? Measured: another copy.
- **E.** A one-word turn resumed from D with `model.compressionThreshold` at
  `COMPRESS_AT` in the scratch HOME's `settings.json`, so the CLI compresses
  before its call. A compression shows as `stats` larger than the records,
  because the summary call is not recorded, and as a smaller `input`.
- **F.** A one-word turn resumed from E with the default threshold: does the
  compression survive a `--session-file` resume, or does the next prompt go
  back to the uncompressed size?
- **G.** `-p /stats` with an invalid key: does headless mode have a stats
  command that answers without a model call? Free.

**Run it** from `impl/gemini-python`:

    uv run --env-file .env python spike/probe_gemini_context_usage_live.py

`GEMINI_PROBE_MODEL` overrides the model (default `gemini-3.1-flash-lite`).
`GEMINI_BINARY` overrides the binary (default `node_modules/.bin/gemini`, or
`gemini.cmd` on Windows, which is the one that runs there). `PROBE_KEEP=1`
keeps the scratch directory and prints its path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")
TURN_TIMEOUT_S = 120
#: A fraction of the window. Any prompt above `COMPRESS_AT * 1 048 576`, about
#: ten tokens, triggers a compression before the call.
COMPRESS_AT = 0.00001
#: Lines in `big.txt`. Distinct lines, so the file does not compress to nothing
#: in a summary and does not trip the read tool's own limits.
BIG_LINES = 1200
#: The last line of `big.txt`, and the answer step C asks for.
MARKER = "the code is 4417"

HERE = Path(__file__).resolve().parent
DEFAULT_BIN = HERE.parent / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")
GEMINI = os.environ.get("GEMINI_BINARY", str(DEFAULT_BIN))


def records(transcript: Path) -> list[dict]:
    """The `gemini` records, last line per id, in first-seen order."""
    order: list[str] = []
    latest: dict[str, dict] = {}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "gemini" or "id" not in rec:
            continue
        if rec["id"] not in latest:
            order.append(rec["id"])
        latest[rec["id"]] = rec
    return [latest[i] for i in order]


def kinds(transcript: Path) -> dict[str, int]:
    """How many lines of each kind the transcript has, for spotting markers."""
    out: dict[str, int] = {}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        k = rec.get("type") or ("$set" if "$set" in rec else "/".join(sorted(rec))[:40])
        out[k] = out.get(k, 0) + 1
    return out


class Gemini:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ws = root / "ws"
        self.store = root / "store"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.store.mkdir(parents=True, exist_ok=True)
        (self.ws / "big.txt").write_text(
            "".join(f"line {i}: inventory item {i * 7919 % 10007} is stored in bay "
                    f"{i % 37} on shelf {i % 11}\n" for i in range(BIG_LINES))
            + MARKER + "\n", encoding="utf-8")
        self.n = 0

    def turn(self, label: str, prompt: str, *, resume: Path | None = None,
             settings: dict | None = None, env: dict | None = None) -> Path | None:
        """One turn in its own HOME, as the build takes it; return the copy."""
        self.n += 1
        home = self.root / f"home{self.n}"
        (home / ".gemini").mkdir(parents=True, exist_ok=True)
        if settings is not None:
            (home / ".gemini" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        argv = [GEMINI, "-p", prompt, "-o", "stream-json", "-m", MODEL, "--approval-mode", "default"]
        before = resume.stat().st_size if resume else None
        if resume:
            argv += ["--session-file", str(resume)]
        run_env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
                   "GEMINI_CLI_TRUST_WORKSPACE": "true", **(env or {})}
        p = subprocess.run(argv, cwd=self.ws, env=run_env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=TURN_TIMEOUT_S)
        print(f"\n== {label}  (rc={p.returncode})")
        stats = None
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                print(f"  stdout (not JSON): {line[:200]}")
                continue
            t = ev.get("type")
            if t == "result":
                stats = ev.get("stats")
            elif t == "init" and self.n == 1:
                print(f"  init event fields: {sorted(ev)}")
            elif t not in ("message", "init"):
                print(f"  event {t}: {json.dumps(ev)[:200]}")
        if p.returncode != 0 or not p.stdout.strip():
            print(f"  stderr: {p.stderr.strip()[:400]}")
        if stats:
            print(f"  result.stats: input_tokens={stats.get('input_tokens')} "
                  f"output_tokens={stats.get('output_tokens')} total_tokens={stats.get('total_tokens')}")
        if resume:
            print(f"  --session-file copy unchanged: {resume.stat().st_size == before}")
        produced = sorted(home.rglob("session-*.jsonl"), key=lambda f: f.stat().st_mtime)
        if not produced:
            print("  no transcript produced")
            return None
        copy = self.store / f"turn{self.n}.jsonl"
        shutil.copy2(produced[-1], copy)
        recs = records(copy)
        print(f"  transcript lines by kind: {kinds(copy)}")
        # big.txt's last line occurs once per copy of the file anywhere in the
        # transcript, so this counts how many times the tool result is stored.
        text = copy.read_text(encoding="utf-8")
        per_kind: dict[str, int] = {}
        for line in text.splitlines():
            if MARKER in line:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                where = rec.get("type") or ("$set:" + ",".join(rec.get("$set", {})))
                if rec.get("toolCalls"):
                    where += "+toolCalls"
                per_kind[where] = per_kind.get(where, 0) + line.count(MARKER)
        print(f"  copies of big.txt in the transcript: {text.count(MARKER)} by line kind {per_kind}")
        for r in recs:
            print(f"  record {r['id'][:8]} model={r.get('model')} tokens={r.get('tokens')}")
        if recs and stats:
            print(f"  sum of record inputs={sum((r.get('tokens') or {}).get('input', 0) for r in recs)}"
                  " (records from earlier turns included, if repeated)")
        return copy


def compare(prev: Path | None, this: Path | None) -> None:
    """The resumed turn's first new call against the previous last record."""
    before = records(prev) if prev else []
    seen = {r["id"] for r in before}
    # By id, not by position: a compression rewrites the history, so the
    # transcript after one can hold FEWER records than the one before it.
    new = [r for r in (records(this) if this else [])
           if r["id"] not in seen and r.get("tokens")]
    if not before or not new:
        print("  COMPARE: not enough records")
        return
    last = before[-1].get("tokens") or {}
    first = new[0].get("tokens") or {}
    io = last.get("input", 0) + last.get("output", 0)
    print(f"  COMPARE previous last: input={last.get('input')} output={last.get('output')} "
          f"thoughts={last.get('thoughts')} total={last.get('total')}")
    print(f"  COMPARE this turn's first call input={first.get('input')}: "
          f"minus (input+output)={first.get('input', 0) - io:+d}, "
          f"minus total={first.get('input', 0) - last.get('total', 0):+d}")


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    root = Path(tempfile.mkdtemp(prefix="gem-ctx-")).resolve()
    g = Gemini(root)
    print(f"binary={GEMINI} model={MODEL} scratch={root}")
    try:
        a = g.turn("A. one word, fresh", "Reply with the single word: ok")
        b = g.turn("B. one word, resumed (no tool call before it)",
                   "Reply with the single word: again", resume=a)
        compare(a, b)
        c = g.turn("C. resumed, read big.txt with a tool",
                   "Use your read_file tool to read big.txt, then reply with only the "
                   "code on its last line.", resume=b)
        compare(b, c)
        d = g.turn("D. one word, resumed after the tool call",
                   "Reply with the single word: next", resume=c)
        compare(c, d)
        d2 = g.turn("D2. one word, resumed again", "Reply with the single word: still",
                    resume=d)
        compare(d, d2)
        e = g.turn(f"E. one word, resumed, compressionThreshold={COMPRESS_AT}",
                   "Reply with the single word: squeeze", resume=d2,
                   settings={"model": {"compressionThreshold": COMPRESS_AT}})
        compare(d2, e)
        f = g.turn("F. one word, resumed from the compressed turn, default threshold",
                   "Reply with the single word: done", resume=e)
        compare(e, f)
        g.turn("G. -p /stats with an invalid key (keyless, free)", "/stats",
               env={"GEMINI_API_KEY": "invalid-key-for-probe"})
    finally:
        if os.environ.get("PROBE_KEEP") == "1":
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
