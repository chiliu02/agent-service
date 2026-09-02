"""The session and turn routes, against a REAL app-server.

**Free.** Creating a session starts a `codex app-server` subprocess and creates
a thread; neither sends a prompt, so nothing is billed. What needs a credential
is the turn itself, and that is marked `live` in `test_live.py`.

Each test gets its own `CODEX_HOME` and workspace under `tmp_path`, so the 65
files the app-server unpacks on first start go somewhere disposable and nothing
touches the developer's real one.

**Why a real subprocess rather than a fake registry.** The routes are thin; what
is worth testing is the thing underneath them -- that a thread really is created,
that the id really is known at creation, that a close really frees the process.
A fake would assert this file's own assumptions back at it.
"""

from __future__ import annotations

import uuid

import pytest
from agent_spec.openapi.schemas import Problem, SessionList, SessionRecord
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.registry import SessionRegistry


@pytest.fixture
def client(tmp_path):  # noqa: ANN001, ANN201
    """A real app with a real registry, pointed at disposable directories."""
    settings = Settings(
        require_credentials=False,
        # `tmp_path` is a real directory and NOT a mount, which is exactly the
        # state the mounts gate refuses -- so an in-process test must switch it
        # off. That is not a weakening of the test: what it exercises is the
        # routes, and `test_api_meta.py` owns the gate.
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=tmp_path / "home",
        max_sessions=2,
    )
    app = create_app(settings, SessionRegistry(settings))
    # `with` matters: the lifespan owns the reaper and the shutdown sweep, and a
    # bare TestClient would run neither.
    with TestClient(app) as c:
        yield c


def _create(client: TestClient, **body) -> dict:  # noqa: ANN003
    r = client.post("/v1/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- creation and identifiers ----------------------------------------------


def test_a_created_session_validates_against_the_shared_model(client) -> None:  # noqa: ANN001
    SessionRecord.model_validate(_create(client))


def test_the_sdk_id_is_known_at_creation_and_is_not_the_path_handle(client) -> None:  # noqa: ANN001
    """**Where this build differs from the specification's expectation.**

    AS-15 says `sdk_session_id` is null on the 201 and populated from the first
    turn, because the Claude CLI does not mint its id before then. Codex mints
    the thread id at `thread_start()`, so it is known immediately -- and
    reporting a value this service HAS would be withholding the truth to match
    another implementation's timing.

    The field's own description in the specification says "or null when it is
    not known yet", which is the wording this satisfies. See
    (CX-15).
    """
    record = _create(client)
    assert record["sdk_session_id"], "the thread id is known at creation and must be reported"
    assert len(record["sdk_session_id"]) == 36, "expected a UUID"
    # Two identifiers, never merged: the path handle is the service's own.
    assert record["session_id"] != record["sdk_session_id"]


def test_a_supplied_sdk_session_id_is_refused_not_ignored(client) -> None:  # noqa: ANN001
    """**Refusing is the honest answer and silence would be the dangerous one.**

    Codex offers no way to set the thread id. Accepting the field and returning
    a different id would break the exact mapping AS-13 exists to provide, and
    would break it silently -- a caller would join its records to an id no
    conversation has.
    """
    r = client.post("/v1/sessions", json={"sdk_session_id": str(uuid.uuid4())})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    Problem.model_validate(r.json())
    detail = r.json()["detail"]
    # The refusal must say what to do instead, or the caller is left guessing.
    assert "sdk_session_id" in detail and "mints" in detail
    # 0.19.0, and it was promised: a `type` a client branches on rather than a
    # sentence it matches. This route answers 400 for a limit above its cap and
    # for an unsupported option too, and only this one means "stop sending it".
    assert r.json()["type"] == (
        "https://agent-service.invalid/problems/sdk-session-id-unsupported"
    )


def test_the_deprecated_alias_is_refused_the_same_way(client) -> None:  # noqa: ANN001
    """`session_id` on the request is the 0.4.0 spelling and folds into the same
    field, so it must meet the same refusal rather than slipping past it."""
    r = client.post("/v1/sessions", json={"session_id": str(uuid.uuid4())})
    assert r.status_code == 400


def test_refusing_a_supplied_id_starts_no_subprocess(client) -> None:  # noqa: ANN001
    """The check is before the cap and before the spawn. A 400 that cost an
    app-server would let a caller exhaust the cap with requests this build
    cannot honour."""
    for _ in range(5):
        assert client.post("/v1/sessions", json={"sdk_session_id": str(uuid.uuid4())}).status_code == 400
    assert client.get("/v1/sessions").json()["sessions"] == []
    # And a legitimate create still works -- the cap was never touched.
    assert client.post("/v1/sessions", json={}).status_code == 201


# --- AS-32: options this build cannot honour are refused, not dropped --------
#
# **All of this existed as a function nothing called.** `options.unsupported()`
# was written, unit-tested and imported, and no caller ever saw its output --
# so every field below was silently dropped while (CX-10)
# recorded that callers were told. These tests are against the route, on
# purpose: a unit test of the helper is what passed while the behaviour was
# missing.


def test_a_stdio_mcp_server_is_accepted(client) -> None:  # noqa: ANN001
    """**MCP works on this build as of 2026-08-09**, where it was refused before.

    A real app-server starts here, so this exercises the whole configuration
    path: `mcp_overrides` builds the `--config` arguments, the CLI parses them,
    and the app-server accepts the thread. What it does NOT exercise is the
    agent calling the tool -- that needs a turn, and it is measured in
    `spike/probe_approval_handler.py`.
    """
    servers = {"acme": {"type": "stdio", "command": "python3", "args": ["-c", "pass"]}}

    r = client.post("/v1/sessions", json={"options": {"mcp_servers": servers}})

    assert r.status_code == 201, r.text


def test_an_sse_server_is_refused_because_codex_has_no_such_transport(client) -> None:  # noqa: ANN001
    """`sse` and streamable `http` are different protocols and Codex has one.

    Refused rather than configured as HTTP: pointing an HTTP client at an SSE
    endpoint fails later and further away, in the agent's tool call rather than
    in the caller's request.
    """
    servers = {"acme": {"type": "sse", "url": "https://mcp.example.com/sse"}}

    r = client.post("/v1/sessions", json={"options": {"mcp_servers": servers}})

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    Problem.model_validate(r.json())
    assert "sse" in r.json()["detail"]
    assert r.json()["type"] == "https://agent-service.invalid/problems/unsupported-options"


def test_an_http_server_takes_a_bearer_token_and_refuses_other_headers(client) -> None:  # noqa: ANN001
    """Codex carries a bearer token and no other header, and says which it is.

    The token itself is never in the config: it becomes an environment variable
    the app-server reads, named per server. **That keeps it out of the process
    table** -- it does not keep it from the agent, which runs as the same user.
    """
    ok = {"acme": {"type": "http", "url": "https://mcp.example.com/mcp",
                   "headers": {"Authorization": "Bearer t"}}}
    assert client.post("/v1/sessions", json={"options": {"mcp_servers": ok}}).status_code == 201

    bad = {"acme": {"type": "http", "url": "https://mcp.example.com/mcp",
                    "headers": {"X-Api-Key": "k"}}}
    r = client.post("/v1/sessions", json={"options": {"mcp_servers": bad}})
    assert r.status_code == 400
    assert "X-Api-Key" in r.json()["detail"]


def test_an_operator_can_still_forbid_mcp_entirely(tmp_path) -> None:  # noqa: ANN001
    """`allow_mcp_servers=false` is a deployment's answer, not a build's.

    **The reason is attribution rather than capability**, exactly as on the
    Claude build: a stdio server is a subprocess that starts with the session,
    before any prompt, and appears in no turn's events -- while a shell command
    is the agent's own decision and is recorded.
    """
    settings = Settings(
        require_credentials=False,
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=tmp_path / "home",
        allow_mcp_servers=False,
    )
    with TestClient(create_app(settings, SessionRegistry(settings))) as c:
        assert c.get("/v1/capabilities").json()["allow_mcp_servers"] is False
        servers = {"acme": {"type": "stdio", "command": "python3"}}
        r = c.post("/v1/sessions", json={"options": {"mcp_servers": servers}})

    assert r.status_code == 400
    assert "acme" in r.json()["detail"]
    assert r.json()["type"] == "https://agent-service.invalid/problems/unsupported-options"


def test_the_published_transports_are_the_ones_accepted(client) -> None:  # noqa: ANN001
    """**AS-32 for MCP**: `capabilities.mcp` predicts which servers are refused.

    Driven from the published value rather than a list written here, so a
    transport added to `MCP_TRANSPORTS` without the mapping reaching it fails.
    """
    mcp = client.get("/v1/capabilities").json()["mcp"]
    assert mcp["http_headers"] == "bearer_only"

    probes = {
        "stdio": {"type": "stdio", "command": "python3"},
        "http": {"type": "http", "url": "https://mcp.example.com/mcp"},
        "sse": {"type": "sse", "url": "https://mcp.example.com/sse"},
    }
    for transport, server in probes.items():
        r = client.post("/v1/sessions", json={"options": {"mcp_servers": {"x": server}}})
        expected = 201 if transport in mcp["transports"] else 400
        assert r.status_code == expected, f"{transport}: {r.text}"
        if r.status_code == 201:
            # `max_sessions` is 2 in this fixture and each accepted transport
            # holds one. Leaking them makes the LAST probe fail with a 429,
            # which reads as a refused transport and is not one.
            client.delete(f"/v1/sessions/{r.json()['session_id']}")


def test_every_published_unsupported_option_really_is_refused(client) -> None:  # noqa: ANN001
    """**The published list and the behaviour, checked against each other.**

    AS-32's failure mode is a capability that says one thing while the code does
    another, so this drives the request from `/v1/capabilities` rather than from
    a list written here. A name added to `REFUSED_OPTIONS` without the refusal
    reaching it fails here.
    """
    published = client.get("/v1/capabilities").json()["unsupported_options"]
    assert published, "this build refuses several options; an empty list is wrong"

    #: A value that is TRUTHY for each field's type -- the refusal is truthiness
    #: based, so `[]` or `{}` would prove nothing.
    probes = {
        "allowed_tools": ["Read"],
        "disallowed_tools": ["Bash"],
        "setting_sources": ["project"],
        "max_turns": 5,
        "max_budget_usd": 1.0,
        "mcp_servers": {"acme": {"type": "http", "url": "https://mcp.example.com/mcp"}},
        "system_prompt": {"type": "preset", "preset": "claude_code"},
    }
    for entry in published:
        # An entry is `{field, types?}` since 2026-08-09: `types` absent means
        # the whole field is refused, present means only those JSON types are.
        # Studio caught the string form -- `"system_prompt (preset form)"` --
        # being unmatchable by a client comparing field names.
        field = entry["field"]
        assert field in probes, f"no probe for published field {field!r}"
        r = client.post("/v1/sessions", json={"options": {field: probes[field]}})
        assert r.status_code == 400, f"{field} is published as unsupported and was accepted"
        assert field in r.json()["detail"], field


def test_a_string_system_prompt_is_honoured_and_only_the_preset_form_is_not(client) -> None:  # noqa: ANN001
    """The list names a form, not the whole field, and this is what that means.

    A build that refused `system_prompt` outright would refuse the shape it
    actually supports -- `base_instructions` takes the string.
    """
    assert client.post(
        "/v1/sessions", json={"options": {"system_prompt": "Be terse."}}
    ).status_code == 201


def test_an_empty_container_asks_for_nothing_and_is_not_refused(client) -> None:  # noqa: ANN001
    """`mcp_servers: {}` configures no servers, so there is nothing to drop and
    nothing to refuse. Refusing it would fail a caller for sending a field whose
    value asks for exactly what this build does."""
    assert client.post(
        "/v1/sessions", json={"options": {"mcp_servers": {}, "allowed_tools": []}}
    ).status_code == 201


def test_refusing_unsupported_options_starts_no_subprocess(client) -> None:  # noqa: ANN001
    """Same property the supplied-id refusal has, and it needs its own test
    because it is a different check in a different place: a 400 that cost an
    app-server lets a caller exhaust `max_sessions` with requests this build
    cannot honour."""
    for _ in range(5):
        assert client.post(
            "/v1/sessions", json={"options": {"max_turns": 3}}
        ).status_code == 400
    assert client.get("/v1/sessions").json()["sessions"] == []
    assert client.post("/v1/sessions", json={}).status_code == 201


def test_the_one_shot_route_refuses_before_it_commits_a_200(client) -> None:  # noqa: ANN001
    """`/v1/query` creates a real session, so the refusal reaches it as a 400 --
    which is why that route declares one. The streaming twin commits its 200
    first and reports the same refusal in band; that difference is the reason
    `/v1/query/stream` declares no 400."""
    r = client.post("/v1/query", json={"prompt": "hi", "options": {"max_budget_usd": 1.0}})
    assert r.status_code == 400
    assert "max_budget_usd" in r.json()["detail"]

    with client.stream(
        "POST", "/v1/query/stream", json={"prompt": "hi", "options": {"max_budget_usd": 1.0}}
    ) as stream:
        assert stream.status_code == 200
        body = "".join(stream.iter_text())
    assert "event: error" in body and "max_budget_usd" in body


# --- lifecycle --------------------------------------------------------------


def test_a_session_appears_in_the_list_and_deletes_cleanly(client) -> None:  # noqa: ANN001
    sid = _create(client)["session_id"]

    listed = client.get("/v1/sessions")
    SessionList.model_validate(listed.json())
    assert any(s["session_id"] == sid for s in listed.json()["sessions"])

    assert client.get(f"/v1/sessions/{sid}").status_code == 200
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404


def test_the_sdk_id_is_not_a_path_handle(client) -> None:  # noqa: ANN001
    """AS-20, over a real server. The two identifiers are different namespaces
    and using one where the other belongs is a 404, not a lookup that happens
    to work."""
    record = _create(client)
    assert client.get(f"/v1/sessions/{record['sdk_session_id']}").status_code == 404


def test_an_unknown_session_is_a_problem_document(client) -> None:  # noqa: ANN001
    r = client.get(f"/v1/sessions/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    # A sentence naming the id, not the bare id -- which would tell a client
    # nothing about what it is being shown.
    assert "No session with id" in r.json()["detail"]


def test_the_published_cap_is_the_enforced_cap(client) -> None:  # noqa: ANN001
    """The only test that proves the published denominator is the real one,
    which is the entire reason `max_sessions` is published at all."""
    cap = client.get("/v1/capabilities").json()["max_sessions"]
    for _ in range(cap):
        assert client.post("/v1/sessions", json={}).status_code == 201

    r = client.post("/v1/sessions", json={})
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert str(cap) in r.json()["detail"]


def test_closing_a_session_frees_a_slot(client) -> None:  # noqa: ANN001
    """The cap must be a live count, not a high-water mark."""
    cap = client.get("/v1/capabilities").json()["max_sessions"]
    ids = [_create(client)["session_id"] for _ in range(cap)]
    assert client.post("/v1/sessions", json={}).status_code == 429
    assert client.delete(f"/v1/sessions/{ids[0]}").status_code == 204
    assert client.post("/v1/sessions", json={}).status_code == 201


# --- PATCH ------------------------------------------------------------------


def test_patch_changes_the_model_and_reads_back(client) -> None:  # noqa: ANN001
    sid = _create(client)["session_id"]
    r = client.patch(f"/v1/sessions/{sid}", json={"model": "gpt-5-codex-mini"})
    assert r.status_code == 200
    assert r.json()["model"] == "gpt-5-codex-mini"
    # And it persists -- a PATCH that only decorated its own response would pass
    # the line above and change nothing.
    assert client.get(f"/v1/sessions/{sid}").json()["model"] == "gpt-5-codex-mini"


def test_patch_with_no_fields_changes_nothing(client) -> None:  # noqa: ANN001
    """An omitted field must not be forwarded as null: that would turn an empty
    PATCH from a no-op into a silent reset of both settings."""
    sid = _create(client)["session_id"]
    before = client.get(f"/v1/sessions/{sid}").json()
    assert client.patch(f"/v1/sessions/{sid}", json={}).status_code == 200
    after = client.get(f"/v1/sessions/{sid}").json()
    assert (after["model"], after["permission_mode"]) == (
        before["model"], before["permission_mode"],
    )


def test_patch_on_an_unknown_session_is_404(client) -> None:  # noqa: ANN001
    assert client.patch(f"/v1/sessions/{uuid.uuid4()}", json={"model": "x"}).status_code == 404


# --- interrupt --------------------------------------------------------------


def test_interrupting_an_idle_session_is_200_and_says_it_did_nothing(client) -> None:  # noqa: ANN001
    """Asking to stop a turn that already finished is not an error -- that race
    is unavoidable for any client, so it is answered rather than punished."""
    sid = _create(client)["session_id"]
    r = client.post(f"/v1/sessions/{sid}/interrupt")
    assert r.status_code == 200
    assert r.json()["interrupted"] is False
    assert r.json()["status"] in ("idle", "running", "closed")


def test_interrupting_an_unknown_session_is_404(client) -> None:  # noqa: ANN001
    assert client.post(f"/v1/sessions/{uuid.uuid4()}/interrupt").status_code == 404


# --- turns, without a credential -------------------------------------------


def test_a_turn_on_an_unknown_session_is_404(client) -> None:  # noqa: ANN001
    r = client.post(f"/v1/sessions/{uuid.uuid4()}/messages", json={"prompt": "hi"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_streaming_a_turn_on_an_unknown_session_is_404_not_an_sse_frame(client) -> None:  # noqa: ANN001
    """**The one that is easy to get wrong.** A streaming route that commits its
    200 before resolving the session can only report the failure in-band, so a
    caller gets `200 text/event-stream` for a session that does not exist. This
    build resolves first, which is what keeps it a real status code."""
    r = client.post(
        f"/v1/sessions/{uuid.uuid4()}/messages/stream", json={"prompt": "hi"}
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_an_empty_prompt_is_refused_by_the_model_not_the_agent(client) -> None:  # noqa: ANN001
    """`TurnRequest.prompt` has `min_length=1`, so this never reaches the SDK --
    and a 422 must still be a problem document."""
    sid = _create(client)["session_id"]
    r = client.post(f"/v1/sessions/{sid}/messages", json={"prompt": ""})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


# --- history routes ---------------------------------------------------------


def test_both_history_routes_refuse_with_the_documented_type(client) -> None:  # noqa: ANN001
    """**"History is off" and "no such session" are different answers**, and a
    console acts differently on each. The `type` is what separates them; a
    client should never have to string-match on prose."""
    disabled = "https://agent-service.invalid/problems/persistence-disabled"
    for path in (f"/v1/sessions/{uuid.uuid4()}/transcript", f"/v1/runs/{uuid.uuid4()}"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/problem+json"), path
        assert r.json()["type"] == disabled, path
        # The refusal names the variable that turns it on. One that does not
        # sends the reader to the source.
        assert "AGENT_SERVICE_DATABASE_URL" in r.json()["detail"], path


def test_the_refusal_does_not_depend_on_the_session_existing(client) -> None:  # noqa: ANN001
    """A real session's transcript refuses identically -- the answer is about
    the service's configuration, not about the id."""
    sid = _create(client)["session_id"]
    r = client.get(f"/v1/sessions/{sid}/transcript")
    assert r.status_code == 404
    assert r.json()["type"] == "https://agent-service.invalid/problems/persistence-disabled"


def test_as16_the_record_and_its_last_turn_agree_about_the_sdk_id(tmp_path) -> None:  # noqa: ANN001
    """**Found by the first paid conformance run this build ever had**, which is
    the argument for having run it: `last_turn.sdk_session_id` was hardcoded
    `None` while the record beside it carried the thread id.

    Same shape as the `token_usage` defect one field along -- `null` means NOT
    KNOWN, and this build knows the id from `thread_start()`, before any turn.
    A turn cannot belong to a different conversation than the session it ran
    in.

    Driven through the route with a stubbed outcome so it costs nothing: what
    is under test is the rendering, not the turn.
    """
    from agent_service.sessions import TurnOutcome

    settings = Settings(
        require_credentials=False,
        require_mounts=False,
        workspace_dir=tmp_path / "ws",
        codex_home=tmp_path / "home",
    )
    # Its own registry, held here, because the entry has to be reachable to
    # stand a completed turn on it without paying for one.
    registry = SessionRegistry(settings)
    with TestClient(create_app(settings, registry)) as c:
        sid = _create(c)["session_id"]
        entry = registry.get(sid)
        entry.last_turn = TurnOutcome(status="completed")
        entry.turns = 1
        record = c.get(f"/v1/sessions/{sid}").json()
    assert record["sdk_session_id"], "this build knows the id at creation"
    assert record["last_turn"]["sdk_session_id"] == record["sdk_session_id"]


def test_resuming_a_conversation_that_is_gone_says_so(client) -> None:  # noqa: ANN001
    """**A 400 a caller can act on, which it was not until 2026-08-09.**

    Measured in (CX-18): destroy `CODEX_HOME` and a resume that
    worked a minute earlier answers `400` with `detail: "InvalidRequestError"`
    -- the right status and indistinguishable from a malformed body. *The
    history is gone* means stop retrying this id and open a new session; *your
    request is wrong* means fix the body. Only one of those is worth a retry.

    Free: the resume fails while the thread is being opened, before any prompt.
    """
    r = client.post(
        "/v1/sessions",
        json={"options": {"resume": "019fe000-0000-7000-8000-000000000000"}},
    )

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    Problem.model_validate(r.json())
    assert r.json()["type"] == (
        "https://agent-service.invalid/problems/resume-target-not-found"
    )
    # The remedy, not just the diagnosis.
    detail = r.json()["detail"]
    assert "resume" in detail and "new session" in detail


def test_a_failed_resume_starts_no_session(client) -> None:  # noqa: ANN001
    """Same property the other pre-flight refusals have: a 400 must not cost a
    slot. The resume is attempted inside `open()`, so this is the one refusal
    that happens AFTER a subprocess starts -- and the registry must still be
    clean afterwards."""
    for _ in range(3):
        client.post(
            "/v1/sessions",
            json={"options": {"resume": "019fe000-0000-7000-8000-000000000000"}},
        )

    assert client.get("/v1/sessions").json()["sessions"] == []
    assert client.post("/v1/sessions", json={}).status_code == 201


def test_no_bound_on_a_tool_call_is_published_as_null_not_omitted(client) -> None:  # noqa: ANN001
    """CX-60: all four null, and null means "no bound" rather than "not looked".

    The distinction is the whole value of the field to a consumer choosing a
    deadline. A missing key would say nothing; `null` says this client imposes
    nothing, which is what `codex mcp get --json` and the absence of any
    tool-call timeout message in the binary both show.

    `progress_resets_idle` is null for the reason the other three are: with no
    timer at all, `true` would claim a mechanism that is not there and `false`
    would claim a restriction that is not there either.
    """
    tool_call = client.get("/v1/capabilities").json()["mcp"]["tool_call"]

    assert set(tool_call) == {
        "request_timeout_s",
        "idle_timeout_s",
        "total_timeout_s",
        "progress_resets_idle",
    }
    assert all(value is None for value in tool_call.values()), tool_call
