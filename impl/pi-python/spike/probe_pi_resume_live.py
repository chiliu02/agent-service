"""Does `options.resume` restore the conversation, through the HTTP surface?

**SPENDS MONEY. Two turns, both tiny, on a pinned cheap model.**

**The seam this exists for.** `PI-13` measured that the AGENT resumes: a second
`-p` process given `--session <id>` recalled the first's work, on three
providers. `PI-52` wired `options.resume` and pinned the argv with tests against
the fake agent. Neither drives the whole chain -- service, argv, agent, model --
and that is exactly the shape of defect this repository keeps finding: both ends
tested, the seam not, and only a live turn catches it.

**It is the Claude build's T9-B, on this target.** Plant a number, DESTROY the
session that holds it, resume by the id alone, ask for the number back.

**The DELETE is not decoration.** It is what makes this a test of the index
rather than of a session that happened to still be open -- before `PI-52` the
only route from an id to a conversation died with the session.

Run:

    GEMINI_API_KEY=... uv run python spike/probe_pi_resume_live.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

#: **Pinned, and do not remove it to "be thorough".** The default provider is
#: whatever the deployment says; an unpinned run can pick an expensive model, and
#: this probe answers a question about plumbing rather than about capability.
MODEL = os.environ.get("PI_PROBE_MODEL", "google/gemini-3.1-flash-lite")

#: The canary. Digits only, so a model that answers in a sentence still contains
#: it and a model that forgot cannot produce it by chance.
NUMBER = "8675309"

#: **A cap, because a turn that cannot finish is the expensive one.** Two turns
#: at a minute each is the whole budget of this probe.
TIMEOUT_S = 60


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2

    from fastapi.testclient import TestClient

    from agent_service.api import create_app
    from agent_service.config import Settings

    root = Path(tempfile.mkdtemp(prefix="pi-resume-"))
    (root / "workspace").mkdir()
    settings = Settings(
        workspace_dir=root / "workspace",
        agent_dir_root=root / "agent-dirs",
        session_store=root / "sessions",
        pi_binary=Path("pi.cmd" if os.name == "nt" else "pi"),
        require_credentials=False,
        model=MODEL,
        turn_timeout_s=TIMEOUT_S,
    )
    print(f"model:  {MODEL}")
    print(f"store:  {settings.session_store}")

    with TestClient(create_app(settings)) as client:
        first = client.post("/v1/sessions", json={"title": "live-resume"})
        if first.status_code != 201:
            print(f"FAILED to open a session: {first.status_code} {first.text}")
            return 1
        sid = first.json()["session_id"]

        planted = client.post(f"/v1/sessions/{sid}/messages", json={
            "prompt": f"Remember this number: {NUMBER}. Reply with exactly: OK",
        })
        if planted.status_code != 200:
            print(f"FAILED turn 1: {planted.status_code} {planted.text[:400]}")
            return 1
        issued = planted.json()["sdk_session_id"]
        print(f"turn 1: {planted.json()['result'].strip()[:60]!r}  id={issued}")

        # **The session goes; the conversation must not.** This is the half that
        # was unreachable before `PI-52`.
        dropped = client.delete(f"/v1/sessions/{sid}")
        gone = client.get(f"/v1/sessions/{sid}")
        print(f"delete: {dropped.status_code}, then GET: {gone.status_code}")

        second = client.post("/v1/sessions", json={
            "title": "resumed", "options": {"resume": issued},
        })
        if second.status_code != 201:
            print(f"FAILED to resume: {second.status_code} {second.text[:400]}")
            return 1
        resumed = second.json()["session_id"]

        asked = client.post(f"/v1/sessions/{resumed}/messages", json={
            "prompt": "What number did I ask you to remember? Digits only.",
        })
        if asked.status_code != 200:
            print(f"FAILED turn 2: {asked.status_code} {asked.text[:400]}")
            return 1
        answer = asked.json()["result"]
        print(f"turn 2: {answer.strip()[:120]!r}")

        # **The control**, and without it this proves nothing: a fresh session
        # asked the same question must NOT produce the number. Otherwise a model
        # that guesses, or a prompt that leaks, reads as a successful resume.
        control_id = client.post("/v1/sessions", json={"title": "control"}).json()[
            "session_id"
        ]
        control = client.post(f"/v1/sessions/{control_id}/messages", json={
            "prompt": "What number did I ask you to remember? Digits only.",
        })
        control_text = control.json().get("result", "") if control.status_code == 200 else ""
        print(f"control: {control_text.strip()[:120]!r}")

    recalled = NUMBER in answer
    leaked = NUMBER in control_text
    print()
    print(f"resumed conversation recalled the number: {recalled}")
    print(f"control (fresh session) produced it anyway: {leaked}")
    if recalled and not leaked:
        print("\nRESULT: options.resume RESTORES the conversation on pi-python.")
        return 0
    if leaked:
        print("\nRESULT: INCONCLUSIVE -- the control produced it too.")
        return 1
    print("\nRESULT: the resumed session did NOT retain the conversation.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
