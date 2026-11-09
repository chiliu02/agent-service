"""The session routes: open, list, read, close — and what each refuses.

**Free: no agent runs here.** Opening a session writes a policy file and makes a
directory; nothing spawns until a turn is taken. That is a property of this
build rather than a testing trick — a session is a directory and a lock, never a
live process (GP-41), which is why closing one is cheap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.policy import parses_as_toml
from agent_spec.openapi.examples import flat


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "home",
        "transcript_store": tmp_path / "store",
        "gemini_binary": Path("gemini-not-installed"),
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
    change on every turn (GP-34), so it is never a key.
    """
    body = client.post("/v1/sessions", json={}).json()
    assert body["session_id"]
    assert body["sdk_session_id"] is None
    assert body["turns"] == 0
    assert body["total_cost_usd"] is None, "0.0 would read as free (GP-16)"


def test_a_supplied_session_id_is_refused_with_a_named_type(client: TestClient) -> None:
    """GP-34. **Refused, never adopted-and-replaced.**

    Taking the field and returning a different id would break the one guarantee
    supplying it provides, and break it invisibly.
    """
    response = client.post("/v1/sessions", json={"sdk_session_id": "11111111-2222-3333-4444-555555555555"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    # The type the specification documents, not a name of this build's choosing:
    # a consumer branches on it, so inventing one would make the refusal
    # unreadable to a client that already handles the other builds.
    assert response.json()["type"].endswith("/sdk-session-id-unsupported")


def test_an_empty_supplied_id_is_refused_too(client: TestClient) -> None:
    """Presence, not truthiness. `""` IS a supplied id.

    Reading it as falsy accepted the request and returned a different id, which
    is the adopt-and-replace this build refuses to do (GP-34).
    """
    response = client.post("/v1/sessions", json={"sdk_session_id": ""})
    assert response.status_code == 400


def test_an_undeclared_permission_mode_is_refused(client: TestClient) -> None:
    """Refused now rather than by the agent at the first turn.

    The set comes from the same table capabilities publishes, so a refusal here
    can never disagree with what was advertised.
    """
    response = client.post("/v1/sessions",
                           json={"options": {"permission_mode": "definitely-not-a-mode"}})
    assert response.status_code == 400
    assert response.json()["type"].endswith("/unknown-permission-mode")


def test_each_session_gets_its_own_policy_file_and_home(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-39 and GP-19: an isolated HOME, and a policy written before any turn.

    The policy exists at open rather than at first turn so that a session which
    never takes one still cannot have been unbounded.
    """
    session_id = client.post("/v1/sessions", json={}).json()["session_id"]
    policy = tmp_path / "home" / session_id / "admin-policy.toml"
    assert policy.is_file(), "no policy was written for the session"
    rules = parses_as_toml(policy.read_text(encoding="utf-8"))["rule"]
    assert rules[0] == {"toolName": "*", "decision": "deny", "priority": 900}


def test_the_shell_never_reaches_a_generated_policy(client: TestClient, tmp_path: Path) -> None:
    """GP-20: asking for the shell must not produce a policy that allows it.

    An unrestricted `run_shell_command` voids every other rule, so a caller
    naming it gets a policy without it rather than a policy that means nothing.
    """
    session_id = client.post(
        "/v1/sessions",
        json={"options": {"allowed_tools": ["read_file", "run_shell_command"]}},
    ).json()["session_id"]
    document = (tmp_path / "home" / session_id / "admin-policy.toml").read_text()
    assert "run_shell_command" not in document


def test_a_denied_tool_is_removed_from_the_default_allow_list(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-57: `disallowed_tools` was accepted and never read.

    The regression shape exactly: a deny list and NO `allowed_tools`, so the
    allow set comes from this build's default -- which contains `write_file`.
    """
    session_id = client.post(
        "/v1/sessions",
        json={"options": {"disallowed_tools": ["write_file"]}},
    ).json()["session_id"]
    document = (tmp_path / "home" / session_id / "admin-policy.toml").read_text()
    assert "write_file" not in document, "a denied tool reached the policy"
    assert "read_file" in document, "the rest of the default list must survive"


def test_a_denied_tool_is_removed_from_a_callers_allow_list(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-57, the other half: deny wins over the caller's own allow list.

    Nearly redundant under deny-`*` -- anything absent is already denied -- but a
    caller sending both must not find the allow list quietly winning.
    """
    session_id = client.post(
        "/v1/sessions",
        json={
            "options": {
                "allowed_tools": ["read_file", "write_file"],
                "disallowed_tools": ["write_file"],
            }
        },
    ).json()["session_id"]
    document = (tmp_path / "home" / session_id / "admin-policy.toml").read_text()
    assert "write_file" not in document
    assert "read_file" in document


def test_listing_comes_from_our_store(client: TestClient) -> None:
    """GP-14: the agent's own listing cannot answer this route truthfully."""
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


def test_the_cap_is_a_429_and_matches_what_is_published(tmp_path: Path) -> None:
    """`max_sessions` is published so a caller can check before opening (AS-33).

    A cap reachable only by scraping the prose of an error is a cap nobody can
    plan around.
    """
    with TestClient(create_app(_settings(tmp_path, max_sessions=2))) as client:
        assert flat(client.get("/v1/deployment").json())["max_sessions"] == 2
        assert client.post("/v1/sessions", json={}).status_code == 201
        assert client.post("/v1/sessions", json={}).status_code == 201
        third = client.post("/v1/sessions", json={})
        assert third.status_code == 429
        assert third.json()["type"].endswith("/max-sessions-reached")


def _bare_session(tmp_path: Path):
    """A `Session` with only the fields the dataclass requires."""
    from agent_service.registry import Session

    return Session(
        session_id="s1",
        workspace=tmp_path,
        agent_home=tmp_path / "home",
        policy_file=tmp_path / "home" / "admin-policy.toml",
        transcript=tmp_path / "t.jsonl",
        created_at=0.0,
        last_used_at=0.0,
    )


def test_last_turn_reports_a_timeout_the_504_could_not(tmp_path: Path) -> None:
    """GP-58: a timed-out turn returns 504 and no RunResponse.

    So the session's `last_turn` is the only surface that can ever say the wall
    clock ran out, once the problem document has been read and discarded.
    """
    session = _bare_session(tmp_path)
    session.finish(interrupted=False, timed_out=True)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "timed_out"


def test_last_turn_reports_an_interrupt_as_an_interrupt(tmp_path: Path) -> None:
    """GP-58: never as a crash -- `interrupted` outranks `is_error`."""
    session = _bare_session(tmp_path)
    session.finish(interrupted=True, timed_out=False)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "interrupted"


def test_last_turn_of_an_ordinary_turn_ends_the_turn(tmp_path: Path) -> None:
    session = _bare_session(tmp_path)
    session.finish(interrupted=False, timed_out=False)
    assert session.last_turn is not None
    assert session.last_turn.stop_kind == "end_turn"


def test_a_system_prompt_string_is_written_into_the_session_home(
    client: TestClient, tmp_path: Path,
) -> None:
    """GP-66. The agent takes a FILE, so the string has to become one.

    **In the session's own HOME, never the workspace.** The workspace is one
    directory shared by every session and writable by the agent, so a prompt
    written there would be readable and rewritable by the next turn.

    It is written at provisioning rather than per turn because this build spawns
    the agent once per turn (GP-41) and the file must outlive the request that
    carried it.
    """
    created = client.post(
        "/v1/sessions", json={"options": {"system_prompt": "You are a teapot."}}
    )
    assert created.status_code == 201

    home = tmp_path / "home" / created.json()["session_id"]
    assert (home / "system.md").read_text(encoding="utf-8") == "You are a teapot."


def test_the_preset_object_form_is_refused_by_type(client: TestClient) -> None:
    """GP-66. `system_prompt` is refused for `object` and honoured for `string`.

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


def test_no_system_prompt_writes_no_file(client: TestClient, tmp_path: Path) -> None:
    """Omitted is the agent's own prompt, and nothing is left in the home.

    An empty file would not be the same thing: `GEMINI_SYSTEM_MD` pointing at one
    replaces the built-in prompt with nothing at all.
    """
    created = client.post("/v1/sessions", json={})
    home = tmp_path / "home" / created.json()["session_id"]
    assert not (home / "system.md").exists()


def test_the_runner_for_a_session_carries_its_system_prompt(
    client: TestClient, tmp_path: Path,
) -> None:
    """GP-66. **The seam, which is where this option was broken.**

    The file was written at provisioning and the runner knew how to turn a path
    into `GEMINI_SYSTEM_MD` -- and `_runner_for` passed neither to the other, so
    a caller's system prompt reached disk and nothing else. Both ends had tests.
    A live turn is what found it, and this is the test that would have.
    """
    from agent_service.api import _runner_for  # noqa: PLC0415
    from agent_service.registry import Registry  # noqa: PLC0415

    settings = _settings(tmp_path)
    registry = Registry(settings)
    session = registry.ephemeral(system_prompt="You are a teapot.")

    env = _runner_for(settings, session).env()

    assert env["GEMINI_SYSTEM_MD"] == str(session.system_prompt_file)
    assert Path(env["GEMINI_SYSTEM_MD"]).read_text(encoding="utf-8") == (
        "You are a teapot."
    )
    assert "GEMINI_SYSTEM_MD" not in _runner_for(
        settings, registry.ephemeral()
    ).env()


def test_working_directory_is_honoured_and_bounded(
    client: TestClient, tmp_path: Path,
) -> None:
    """GP-68. Accepted and read by nothing until 2026-09-03.

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
    """GP-68. The seam again -- the session held it and the runner ignored it.

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
