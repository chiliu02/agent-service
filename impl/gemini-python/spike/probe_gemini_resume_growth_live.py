"""Does THIS BUILD's resume send an earlier tool result again on every turn? (GP-78)

**SPENDS MONEY, a little.** Three turns on a pinned cheap model through the
service's own HTTP surface: one reads a file of about 30k tokens with a tool,
two are one word. About 200k input tokens, under 0.10 USD on
`gemini-3.1-flash-lite`.

**Why this exists.** GP-77's probe drives the CLI directly, imitating how this
build resumes. It found that each `--session-file` resume adds one more copy of
an earlier tool result to the prompt. An imitation is not the build: this
build keeps one `HOME` per session across turns and picks the transcript it
copies out by itself (GP-39). So this probe asks the build, through
`POST /v1/sessions` and `POST /v1/sessions/{sid}/messages`, and reads each
turn's `token_usage.input_tokens` from the response.

**How to read the output.** Turn 1 makes at least two model calls, and its
input is their sum, so it holds about ONE copy of the file. Each later turn is
one model call. If the build carries one copy, turns 2 and 3 are each about
the size of turn 1's last call. If each resume adds a copy, turn 2 is about
one file larger than that and turn 3 about two files larger. The probe also
counts how many times the file's last line occurs in the transcript the
service keeps.

**Run it** from `impl/gemini-python`:

    uv run --env-file .env python spike/probe_gemini_resume_growth_live.py

`GEMINI_PROBE_MODEL` overrides the model. `GEMINI_BINARY` overrides the CLI,
which is how a candidate CLI version is checked before the image pins it. Each
turn is capped at `CAP` seconds.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agent_service.api import create_app  # noqa: E402
from agent_service.config import Settings  # noqa: E402

MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")
CAP = 120
BIG_LINES = 1200
MARKER = "the code is 4417"


def _client(root: Path) -> TestClient:
    settings = Settings(
        workspace_dir=root / "workspace",
        agent_home_root=root / "homes",
        transcript_store=root / "transcripts",
        gemini_binary=Path(os.environ.get("GEMINI_BINARY") or (
            Path(__file__).resolve().parents[1]
            / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini"))),
        model=MODEL,
        turn_timeout_s=CAP,
        require_credentials=False,
    )
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / "big.txt").write_text(
        "".join(f"line {i}: inventory item {i * 7919 % 10007} is stored in bay "
                f"{i % 37} on shelf {i % 11}\n" for i in range(BIG_LINES))
        + MARKER + "\n", encoding="utf-8")
    return TestClient(create_app(settings))


def _turn(client: TestClient, sid: str, label: str, prompt: str, root: Path) -> None:
    r = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": prompt})
    if r.status_code != 200:
        raise SystemExit(f"{label}: {r.status_code} {r.text[:400]}")
    body = r.json()
    usage = body.get("token_usage") or {}
    copies = sum(p.read_text(encoding="utf-8").count(MARKER)
                 for p in (root / "transcripts").glob("*.jsonl"))
    print(f"{label}: input_tokens={usage.get('input_tokens')} "
          f"output_tokens={usage.get('output_tokens')} "
          f"copies of the file in the kept transcript={copies} "
          f"result={str(body.get('result') or '').strip()[:40]!r}")


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with _client(root) as client:
            created = client.post("/v1/sessions", json={"options": {"model": MODEL}})
            if created.status_code != 201:
                raise SystemExit(f"create: {created.status_code} {created.text[:400]}")
            sid = created.json()["session_id"]
            print(f"model={MODEL} session={sid}")
            _turn(client, sid, "turn 1 (reads big.txt)",
                  "Use your read_file tool to read big.txt, then reply with only the "
                  "code on its last line.", root)
            _turn(client, sid, "turn 2 (one word)", "Reply with the single word: ok", root)
            _turn(client, sid, "turn 3 (one word)", "Reply with the single word: again", root)
            client.delete(f"/v1/sessions/{sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
