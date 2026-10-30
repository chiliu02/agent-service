"""The session routes: open, list, read, close — and what each refuses.

**Free: no agent runs here.** Opening a session writes a policy file and makes a
directory; nothing spawns until a turn is taken. That is a property of this
build rather than a testing trick — a session is a directory and a lock, never a
live process (`PI-11`), which is why closing one is cheap.
"""

from __future__ import annotations

import time


def _bare_session(tmp_path: Path):
    """A `Session` with nothing but its directories, for the record helpers.

    Built directly rather than through the registry: these tests are about what
    `finish()` writes into `last_turn`, and a registry would drag a whole
    deployment in to prove it.
    """
    from agent_service.registry import Session

    now = time.time()
    return Session(
        session_id="s-1",
        workspace=tmp_path,
        agent_dir=tmp_path / "agent-dirs" / "s-1",
        session_dir=tmp_path / "sessions" / "s-1",
        created_at=now,
        last_used_at=now,
    )

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_spec.openapi.examples import flat


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_dir_root": tmp_path / "agent-dirs",
        "session_store": tmp_path / "sessions",
        "pi_binary": Path("pi-not-installed"),
        "require_credentials": False,
    }
    return Settings(**{**base, **kwargs})


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def test_opening_a_session_returns_our_handle_and_no_agent_id_yet(
    client: TestClient,
) -> None:
    """`sdk_session_id` is null until a turn, because the agent mints it then.

    Null means *not known yet*, never *not told* — and on this build it will
    change on every turn (`PI-13`), so it is never a key.
    """
    body = client.post("/v1/sessions", json={}).json()
    assert body["session_id"]
    assert body["sdk_session_id"] is None
    assert body["turns"] == 0
    # **Null before any turn, and a real figure after one** (`PI-17`). Null here
    # means "nothing spent yet"; on two of the four builds it means "this agent
    # cannot price a turn at all", and those are different claims.
    assert body["total_cost_usd"] is None




def test_an_undeclared_permission_mode_is_refused(client: TestClient) -> None:
    """Refused now rather than by the agent at the first turn.

    The set comes from the same table capabilities publishes, so a refusal here
    can never disagree with what was advertised.
    """
    response = client.post("/v1/sessions",
                           json={"options": {"permission_mode": "definitely-not-a-mode"}})
    assert response.status_code == 400
    assert response.json()["type"].endswith("/unknown-permission-mode")






def test_listing_comes_from_our_store(client: TestClient) -> None:
    """`PI-09`: the agent's own listing cannot answer this route truthfully."""
    first = client.post("/v1/sessions", json={"title": "one"}).json()["session_id"]
    second = client.post("/v1/sessions", json={"title": "two"}).json()["session_id"]
    listed = [s["session_id"] for s in client.get("/v1/sessions").json()["sessions"]]
    assert listed == [first, second], "ordered by creation"


def test_an_unknown_session_is_a_404_that_explains_the_two_ids(
    client: TestClient,
) -> None:
    """Feeding an agent conversation id into a path is the classic mistake."""
    response = client.get("/v1/sessions/not-a-session")
    assert response.status_code == 404
    assert response.json()["type"].endswith("/session-not-found")
    assert "sdk_session_id" in response.json()["detail"]


def test_closing_removes_the_session_but_keeps_the_transcript(
    client: TestClient, tmp_path: Path
) -> None:
    """DELETE means one thing: the session is gone, the conversation is not.

    Deleting the transcript here would make `options.resume` mean "unless
    somebody closed the session", which is not what it says.
    """
    session_id = client.post("/v1/sessions", json={}).json()["session_id"]
    transcript = tmp_path / "store" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")

    assert client.delete(f"/v1/sessions/{session_id}").status_code == 204
    assert client.get(f"/v1/sessions/{session_id}").status_code == 404
    assert not (tmp_path / "home" / session_id).exists(), "the agent home should go"
    assert transcript.exists(), "the transcript must survive a close"



def test_last_turn_reports_a_timeout_the_504_could_not(tmp_path: Path) -> None:
    """a timed-out turn returns 504 and no RunResponse.

    So the session's `last_turn` is the only surface that can ever say the wall
    clock ran out, once the problem document has been read and discarded.
    """
    session = _bare_session(tmp_path)
    session.finish(interrupted=False, timed_out=True)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "timed_out"


def test_last_turn_reports_an_interrupt_as_an_interrupt(tmp_path: Path) -> None:
    """never as a crash -- `interrupted` outranks `is_error`."""
    session = _bare_session(tmp_path)
    session.finish(interrupted=True, timed_out=False)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "interrupted"


def test_last_turn_of_an_ordinary_turn_ends_the_turn(tmp_path: Path) -> None:
    session = _bare_session(tmp_path)
    session.finish(interrupted=False, timed_out=False)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "end_turn"



def test_the_preset_object_form_is_refused_by_type(client: TestClient) -> None:
    """`PI-20`. `system_prompt` is refused for `object` and honoured for `string`.

    The preset object names a Claude preset this agent does not have, so there
    is nothing to map it to -- and the field as a whole cannot be refused,
    because the string form works. That is what `types` on an
    `unsupported_options` entry is for, and a client reads which shape is
    refused instead of discovering it from a 400.
    """
    refused = client.post(
        "/v1/sessions",
        json={"options": {"system_prompt": {"type": "preset", "preset": "claude_code"}}},
    )
    assert refused.status_code == 400
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json()["type"].endswith("/unsupported-options")



def test_working_directory_is_honoured_and_bounded(
    client: TestClient, tmp_path: Path,
) -> None:
    """`PI-30`. Accepted and read by nothing until 2026-09-03.

    **The control matters both ways here**: an existing subdirectory must open a
    session, and the two bad values must not. A resolver that refused everything
    would satisfy the refusals alone.
    """
    (tmp_path / "workspace" / "sub").mkdir(parents=True)
    ok = client.post("/v1/sessions", json={"options": {"working_directory": "sub"}})
    assert ok.status_code == 201, ok.text

    escaped = client.post(
        "/v1/sessions", json={"options": {"working_directory": "../../etc"}}
    )
    assert escaped.status_code == 400
    assert escaped.json()["type"].endswith("/invalid-working-directory")

    missing = client.post(
        "/v1/sessions", json={"options": {"working_directory": "not-there"}}
    )
    assert missing.status_code == 400
    assert "does not exist" in missing.json()["detail"]


def test_the_runner_starts_in_the_subdirectory(
    client: TestClient, tmp_path: Path,
) -> None:
    """`PI-30`. The seam again -- the session held it and the runner ignored it.

    On this build the working directory is also a boundary: the agent's own
    guard refuses a file tool outside the directory it was started in, so this
    is not only where it begins.
    """
    from agent_service.api import _runner_for  # noqa: PLC0415
    from agent_service.registry import Registry  # noqa: PLC0415

    settings = _settings(tmp_path)
    (settings.workspace_dir / "sub").mkdir(parents=True)
    registry = Registry(settings)
    session = registry.create(working_directory="sub")

    assert _runner_for(settings, session).workspace == settings.workspace_dir / "sub"
    assert _runner_for(settings, registry.create()).workspace == settings.workspace_dir


# --- what replaced the policy file on this build ------------------------------


def test_each_session_gets_its_own_agent_directory(
    client: TestClient, tmp_path: Path
) -> None:
    """`PI-05`: one session cannot see another's auth cache, settings or store."""
    first = client.post("/v1/sessions", json={}).json()["session_id"]
    second = client.post("/v1/sessions", json={}).json()["session_id"]
    assert (tmp_path / "agent-dirs" / first).is_dir()
    assert (tmp_path / "agent-dirs" / second).is_dir()
    assert first != second


def test_the_tool_grant_reaches_the_command_line(
    client: TestClient, tmp_path: Path
) -> None:
    """`PI-24`: the allowlist IS the tool boundary on this build.

    The Gemini build writes a generated policy file and asserts against its TOML;
    here the same intent is `--tools`, so the assertion is on argv.
    """
    from agent_service.api import _runner_for
    from agent_service.config import Settings

    body = {"options": {"allowed_tools": ["read", "grep"]}}
    sid = client.post("/v1/sessions", json=body).json()["session_id"]
    registry = client.app.state.registry
    session = registry.get(sid)
    runner = _runner_for(
        Settings(workspace_dir=tmp_path, agent_dir_root=tmp_path / "agent-dirs",
                 session_store=tmp_path / "sessions", pi_binary=Path("pi")),
        session,
    )
    argv = runner.argv("hi", sdk_session_id=None, resume=None)
    assert argv[argv.index("--tools") + 1] == "read,grep"


def test_a_denied_tool_is_subtracted_from_the_effective_grant(
    client: TestClient, tmp_path: Path
) -> None:
    """`PI-25`: subtracted from the DEFAULT set too, which is the case that bites.

    A request denying `write` and naming no `allowed_tools` must still lose it --
    the default grant contains it.
    """
    body = {"options": {"disallowed_tools": ["write"]}}
    sid = client.post("/v1/sessions", json=body).json()["session_id"]
    session = client.app.state.registry.get(sid)
    assert "write" not in (session.allowed_tools or ())
    assert "read" in (session.allowed_tools or ())


def test_ask_question_is_refused_whatever_the_caller_asks_for(
    client: TestClient,
) -> None:
    """`PI-25`: it exists to ask a human, and there is no human."""
    body = {"options": {"allowed_tools": ["read", "ask_question"]}}
    sid = client.post("/v1/sessions", json=body).json()["session_id"]
    session = client.app.state.registry.get(sid)
    assert "ask_question" not in (session.allowed_tools or ())


def test_a_supplied_session_id_is_HONOURED(client: TestClient) -> None:
    """`PI-14`: `--session-id` is echoed back verbatim, measured free.

    The Codex and Gemini builds refuse this, and their suites assert the
    refusal. `allow_supplied_sdk_session_id` is what a client reads to tell.
    """
    supplied = "01a07999-0000-7000-8000-000000000001"
    body = {"sdk_session_id": supplied}
    created = client.post("/v1/sessions", json=body)
    assert created.status_code == 201
    session = client.app.state.registry.get(created.json()["session_id"])
    assert session.sdk_session_ids == [supplied]


def test_the_system_prompt_is_carried_as_a_flag_not_a_file(
    client: TestClient, tmp_path: Path
) -> None:
    """`PI-20`: no file is written, so there is no file for a later turn to read."""
    body = {"options": {"system_prompt": "be terse"}}
    sid = client.post("/v1/sessions", json=body).json()["session_id"]
    session = client.app.state.registry.get(sid)
    assert session.system_prompt == "be terse"
    assert not list((tmp_path / "agent-dirs" / sid).glob("*.md"))


def test_a_supplied_id_that_is_not_a_uuid_is_400(client: TestClient) -> None:
    """AS-14, and this build failed it until the container tier said so.

    Adopting a caller's id is a privilege that comes with an obligation: the id
    this build is given is the id it reports and resumes from, so an unparseable
    one would be adopted rather than corrected.
    """
    for bad in ("not-a-uuid", "", "7ad25f07-08d4-4b3a-9f21"):
        r = client.post("/v1/sessions", json={"sdk_session_id": bad})
        assert r.status_code == 400, f"{bad!r} was accepted"
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["detail"]


def test_a_supplied_id_together_with_resume_is_400(client: TestClient) -> None:
    """AS-14's other half: naming a new conversation and continuing an old one.

    The agent refuses the equivalent pair of flags outright; this refuses it
    before a turn is taken.
    """
    import uuid as _uuid

    r = client.post("/v1/sessions", json={
        "sdk_session_id": str(_uuid.uuid4()),
        "options": {"resume": str(_uuid.uuid4())},
    })
    assert r.status_code == 400
    assert r.json()["detail"]


# --- setting_paths, over the route ------------------------------------------


def test_a_named_path_that_does_not_exist_is_a_400_at_session_creation(
    client: TestClient, tmp_path: Path
) -> None:
    """**Through the route, because that is the only thing that proves it** (`PI-59`).

    A resolver test passes whether or not anything calls the resolver -- which is
    the hole the Codex build fell into with `unsupported()`, covered six ways
    while nothing invoked it. This sends the request.

    **At creation rather than at the turn**, so a broken mount fails the thing
    the caller is doing now instead of every turn that follows.
    """
    r = client.post("/v1/sessions", json={
        "options": {"setting_paths": {"instructions": [str(tmp_path / "absent.md")]}}
    })
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"].endswith("/invalid-setting-path")
    assert "absent.md" in r.json()["detail"]


def test_a_named_path_that_exists_opens_a_session(
    client: TestClient, tmp_path: Path
) -> None:
    """The accepting half, so the test above cannot pass by refusing everything."""
    brief = tmp_path / "brief.md"
    brief.write_text("# brief\n", encoding="utf-8")
    persona = tmp_path / "skills" / "persona"
    persona.mkdir(parents=True)
    (persona / "SKILL.md").write_text(
        "---\nname: persona\ndescription: What it does and when.\n---\n\nbody\n",
        encoding="utf-8",
    )

    r = client.post("/v1/sessions", json={"options": {"setting_paths": {
        "instructions": [str(brief)], "skills": [str(persona)],
    }}})
    assert r.status_code == 201, r.text


def test_this_build_does_not_publish_setting_paths_as_unsupported(
    client: TestClient,
) -> None:
    """The one build that honours it must not also advertise refusing it."""
    published = flat(client.get("/v1/deployment").json())["unsupported_options"]
    assert "setting_paths" not in [entry["field"] for entry in published]
