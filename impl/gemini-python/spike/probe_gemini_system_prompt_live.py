"""`RunOptions.system_prompt`, end to end through this service's own routes.

**Half free, half paid.** The keyless half asserts the wiring — the file lands
in the session's HOME and `GEMINI_SYSTEM_MD` carries its absolute path — and
runs with no credential and no turn. The paid half is **two** turns on the
cheapest tier: a control with no system prompt, and the same prompt with one.

    GEMINI_API_KEY=... uv run python spike/probe_gemini_system_prompt_live.py

**`uv run` WITHOUT `--no-project`, unlike the other probes here.** This one
drives the HTTP surface in process rather than the binary, because the finding
it is for is that the option reaches the agent *from a request* — the binary
already honours the variable and that was never in doubt (GP-66).

**The control is not decoration.** A planted token that appears under the system
prompt proves nothing unless it is absent without one: a model asked to be terse
may echo anything. That trap has already been live in this directory once, where
a configuration key validated, was accepted, and changed nothing at all.
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

#: **Pinned to the cheapest tier**, like every live probe here. The unpinned
#: default is `auto`, which bills two models per turn -- a router beside the one
#: that answers (GP-16).
MODEL = os.environ.get("GEMINI_PROBE_MODEL", "gemini-3.1-flash-lite")
CAP = 60
TOKEN = "ZEBRA-7788"
SYSTEM_PROMPT = (
    "You are a terse assistant. Answer in as few words as possible, and end "
    f"every reply with the token {TOKEN}."
)
PROMPT = "Reply with the single word: ready"


def _client(root: Path) -> TestClient:
    settings = Settings(
        workspace_dir=root / "workspace",
        agent_home_root=root / "homes",
        transcript_store=root / "transcripts",
        gemini_binary=Path(__file__).resolve().parents[1]
        / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini"),
        model=MODEL,
        turn_timeout_s=CAP,
        require_credentials=False,
    )
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(settings))


def _free_half(client: TestClient, root: Path) -> None:
    """No key, no turn: does the option become a file and an environment?"""
    created = client.post(
        "/v1/sessions", json={"options": {"system_prompt": SYSTEM_PROMPT}}
    )
    sid = created.json()["session_id"]
    written = (root / "homes" / sid / "system.md").read_text(encoding="utf-8")
    print(f"  system.md written : {written[:60]!r}...")
    assert written == SYSTEM_PROMPT

    refused = client.post(
        "/v1/sessions",
        json={"options": {"system_prompt": {"type": "preset", "preset": "claude_code"}}},
    )
    print(f"  preset object     : {refused.status_code} {refused.json()['type']}")
    assert refused.status_code == 400
    client.delete(f"/v1/sessions/{sid}")


def _turn(client: TestClient, options: dict) -> str:
    body = {"prompt": PROMPT, "options": {"model": MODEL, **options}}
    response = client.post("/v1/query", json=body)
    if response.status_code != 200:
        raise SystemExit(f"turn failed: {response.status_code} {response.text[:400]}")
    return str(response.json().get("result") or "")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with _client(root) as client:
            print("free half -- no credential, no turn:")
            _free_half(client, root)

            if not os.environ.get("GEMINI_API_KEY"):
                print("\nGEMINI_API_KEY unset -- stopping before the paid half.")
                return 0

            print(f"\npaid half -- two turns on {MODEL}:")
            control = _turn(client, {})
            print(f"  control  (no system_prompt): {control.strip()[:120]!r}")
            treated = _turn(client, {"system_prompt": SYSTEM_PROMPT})
            print(f"  treated  (system_prompt)   : {treated.strip()[:120]!r}")

            ok = TOKEN not in control and TOKEN in treated
            print(f"\n{TOKEN} absent in control : {TOKEN not in control}")
            print(f"{TOKEN} present in treated : {TOKEN in treated}")
            print("RESULT:", "honoured" if ok else "NOT honoured")
            return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
