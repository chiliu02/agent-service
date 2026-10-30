"""MCP servers: the settings file, the policy rules, and the allow list.

**Free: nothing is spawned.** A session writes two files and takes no turn, so
every property below is a file on disk or an argv, and the one that matters most
-- that a caller's workspace cannot add servers -- is an argv.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.mcp import (
    MCP_TOOL_CALL_REQUEST_TIMEOUT_S,
    MCP_TOOL_CALL_TOTAL_TIMEOUT_S,
    NO_SERVERS,
    SERVER_NAME_PATTERN,
    McpUnsupported,
    validate,
)
from agent_service.policy import parses_as_toml
from agent_spec.openapi.examples import flat

STDIO = {"stdio-ish": {"type": "stdio", "command": "npx", "args": ["-y", "@acme/mcp"],
                       "env": {"TOKEN": "s3cret"}}}


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


def _open(client: TestClient, servers: dict | None = None, **options) -> str:
    body: dict = {"options": dict(options)}
    if servers is not None:
        body["options"]["mcp_servers"] = servers
    return client.post("/v1/sessions", json=body).json()["session_id"]


def _settings_json(tmp_path: Path, session_id: str) -> dict:
    path = tmp_path / "home" / session_id / ".gemini" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _argv(client: TestClient, session_id: str) -> list[str]:
    """The command line a turn would use, without taking one."""
    from agent_service.api import _runner_for  # noqa: PLC0415

    registry = client.app.state.registry  # type: ignore[attr-defined]
    session = registry.get(session_id)
    runner = _runner_for(client.app.state.settings, session)  # type: ignore[attr-defined]
    return runner.argv("hi", session_file=None, sdk_session_id="x",
                       approval_mode="default")


def test_a_server_reaches_the_sessions_own_settings_file(
    client: TestClient, tmp_path: Path
) -> None:
    """GP-46: `$HOME/.gemini/settings.json` is what the agent reads.

    Per session, because each session already owns its HOME (GP-39). The
    alternative -- the workspace -- is one directory shared by every session and
    belongs to the caller, not to us.
    """
    session_id = _open(client, {"acme": {"type": "stdio", "command": "npx"}})
    assert _settings_json(tmp_path, session_id)["mcpServers"] == {
        "acme": {"command": "npx"}
    }


def test_nothing_is_written_into_the_workspace(client: TestClient, tmp_path: Path) -> None:
    """**The workspace is the caller's mounted tree and stays untouched.**

    Writing MCP configuration there would be a side effect nobody asked for, and
    two concurrent sessions would overwrite each other's.
    """
    _open(client, {"acme": {"type": "stdio", "command": "npx"}})
    assert not (tmp_path / "workspace" / ".gemini").exists()


def test_each_transport_is_written_in_the_agents_vocabulary(
    client: TestClient, tmp_path: Path
) -> None:
    """`url` with `type`, never the deprecated `httpUrl` (GP-46)."""
    session_id = _open(client, {
        "local": {"type": "stdio", "command": "npx", "args": ["-y", "x"]},
        "streamed": {"type": "sse", "url": "https://example.test/sse",
                     "headers": {"X-Key": "v"}},
        "posted": {"type": "http", "url": "https://example.test/mcp"},
    })
    written = _settings_json(tmp_path, session_id)["mcpServers"]
    assert written["local"] == {"command": "npx", "args": ["-y", "x"]}
    assert written["streamed"] == {"type": "sse", "url": "https://example.test/sse",
                                   "headers": {"X-Key": "v"}}
    assert written["posted"] == {"type": "http", "url": "https://example.test/mcp"}
    assert "httpUrl" not in json.dumps(written)


def test_the_policy_allows_the_servers_tools(client: TestClient, tmp_path: Path) -> None:
    """GP-29: `mcpName` needs `toolName` beside it, or the file is discarded.

    Without this rule the server is configured and every one of its tools is
    denied by the deny-`*` the policy opens with -- which looks exactly like a
    server that failed to start.
    """
    session_id = _open(client, {"acme": {"type": "stdio", "command": "npx"}})
    policy = tmp_path / "home" / session_id / "admin-policy.toml"
    rules = parses_as_toml(policy.read_text(encoding="utf-8"))["rule"]
    assert {"mcpName": "acme", "toolName": "*", "decision": "allow",
            "priority": 950} in rules


def test_the_allow_list_carries_exactly_what_was_sent(client: TestClient) -> None:
    """GP-47: argv beats every settings file, so this is the strict channel."""
    session_id = _open(client, {"acme": {"type": "stdio", "command": "npx"},
                                "other": {"type": "stdio", "command": "npx"}})
    argv = _argv(client, session_id)
    at = argv.index("--allowed-mcp-server-names")
    assert argv[at + 1:at + 3] == ["acme", "other"]


def test_a_request_with_NO_servers_still_passes_the_flag(client: TestClient) -> None:
    """**The property this whole mechanism exists for.**

    A workspace `.gemini/settings.json` merges into the session's own (GP-46),
    and the workspace is mounted from the host and writable by the agent. A
    caller who sent no servers has asked for no servers -- not for whatever the
    repository happens to configure -- so the flag is passed anyway, naming a
    sentinel that cannot be a real server (GP-28, GP-47).

    Omitting the flag here is the whole vulnerability, and it looks exactly like
    a harmless optimisation.
    """
    argv = _argv(client, _open(client))
    at = argv.index("--allowed-mcp-server-names")
    assert argv[at + 1] == NO_SERVERS
    assert "_" in NO_SERVERS, "a real server name cannot contain one (GP-28)"


def test_strict_false_is_REFUSED_rather_than_accepted_and_ignored(
    client: TestClient,
) -> None:
    """GP-48. **This build cannot produce non-strict behaviour.**

    Omitting the flag is one line; the reason `false` is refused is the second
    layer. The generated tool policy denies every server the request did not
    name, so a server discovered from the workspace has its tools removed from
    the model's context anyway (GP-20) -- measured live, with a workspace server
    that `gemini mcp list` showed as Connected.

    So accepting `false` would change an argv and nothing else, which is the
    accepted-and-ignored defect. The FIELD is supported for its other value,
    which is why this is a named refusal rather than an `unsupported_options`
    entry -- and `types` could not express it either, since only one value of a
    boolean is at issue.
    """
    response = client.post("/v1/sessions",
                           json={"options": {"strict_mcp_config": False}})
    assert response.status_code == 400
    assert response.json()["type"].endswith("/strict-mcp-config-required")


def test_strict_true_is_accepted_because_it_is_what_happens(
    client: TestClient,
) -> None:
    """The other value is honoured rather than refused along with it."""
    session_id = _open(client, {"acme": {"type": "stdio", "command": "npx"}},
                       strict_mcp_config=True)
    argv = _argv(client, session_id)
    assert argv[argv.index("--allowed-mcp-server-names") + 1] == "acme"


def test_an_underscore_in_a_server_name_is_refused(client: TestClient) -> None:
    """GP-28: the agent splits `mcp_<server>_<tool>` on the first `_`.

    So the name cannot be addressed by a policy rule at all. Refused here rather
    than configured and silently ungovernable.
    """
    response = client.post("/v1/sessions", json={
        "options": {"mcp_servers": {"spike_server": {"type": "stdio", "command": "x"}}}
    })
    assert response.status_code == 400
    assert response.json()["type"].endswith("/mcp-server-unsupported")


def test_an_unknown_transport_never_reaches_this_build_at_all(
    client: TestClient,
) -> None:
    """**422 from the shared schema, not 400 from this build, and that is right.**

    The agent's settings enum is `stdio|sse|http` (GP-46) and the shared
    `McpServer` union has exactly those three members -- so on THIS build every
    expressible transport is supported and there is no valid value left to
    refuse. A fourth transport is a schema violation, which the document already
    describes and a generated client cannot even construct.

    The Codex build is the contrast: `sse` parses there and is then refused with
    a 400, because it supports two of the three. `mcp.transports` is what tells
    the two apart, which is why it is published.
    """
    response = client.post("/v1/sessions", json={
        "options": {"mcp_servers": {"acme": {"type": "carrier-pigeon",
                                             "url": "https://example.test"}}}
    })
    assert response.status_code == 422


def test_a_deployment_can_forbid_them_entirely(tmp_path: Path) -> None:
    """`allow_mcp_servers` is a deployment setting, and it is published.

    A stdio server is a subprocess started with the session that appears in no
    turn's events, which is what an operator who needs every process start
    attributable to a turn is turning off.
    """
    with TestClient(create_app(_settings(tmp_path, allow_mcp_servers=False))) as client:
        assert flat(client.get("/v1/deployment").json())["allow_mcp_servers"] is False
        response = client.post("/v1/sessions", json={
            "options": {"mcp_servers": {"acme": {"type": "stdio", "command": "npx"}}}
        })
        assert response.status_code == 400
        assert response.json()["type"].endswith("/mcp-servers-not-allowed")

        # **Still strict for everyone else.** Forbidding a caller's servers must
        # not also stop guarding against the workspace's.
        session_id = client.post("/v1/sessions", json={}).json()["session_id"]
        registry = client.app.state.registry  # type: ignore[attr-defined]
        assert registry.get(session_id).mcp_allowed_names == (NO_SERVERS,)


def test_capabilities_publishes_what_is_actually_wired(client: TestClient) -> None:
    """AS-32. **`mcp_servers` must not be in `unsupported_options` any more.**

    Publishing a refusal that does not happen is the same defect as an option
    accepted and ignored, and this build has now been on both sides of it.

    **`strict_mcp_config` is back in the list and `mcp_servers` still is not**,
    which looks inconsistent and is the whole distinction: one is a field whose
    every value works except `false`, the other is a field that works and whose
    individual SERVERS may not. A value-scoped entry says the first; nothing in
    the shape can say the second, so it stays out.
    """
    caps = flat(client.get("/v1/deployment").json())
    # **The timers left `mcp` on 2026-09-03.** What a caller may EXPRESS is
    # `accepts.mcp`; how long a tool call may take is `behaviour.mcp_tool_call`,
    # because it is a bound to design a server around rather than a shape to
    # send. Both are asserted here so the split cannot quietly lose one.
    assert caps["mcp"] == {"transports": ["stdio", "sse", "http"],
                           "http_headers": "any",
                           "server_name_pattern": SERVER_NAME_PATTERN}
    assert caps["mcp_tool_call"] == {
        "request_timeout_s": MCP_TOOL_CALL_REQUEST_TIMEOUT_S,
        "idle_timeout_s": None,
        "total_timeout_s": MCP_TOOL_CALL_TOTAL_TIMEOUT_S,
        "progress_resets_idle": False,
    }
    assert caps["strict_mcp_config"] is True
    refused = {option["field"] for option in caps["unsupported_options"]}
    assert "mcp_servers" not in refused
    assert "strict_mcp_config" in refused

    entry = next(o for o in caps["unsupported_options"]
                 if o["field"] == "strict_mcp_config")
    assert entry["values"] == [False], (
        "the entry must be value-scoped: naming the field alone promises a 400 "
        "for `true`, which this build honours"
    )


def test_the_published_name_pattern_is_the_one_that_is_enforced() -> None:
    """The pattern is a promise, so it must be the gate rather than a copy.

    **A published constraint that disagrees with the actual check is the drift
    AS-32 exists to prevent**, and a consumer validating at publish time against
    a pattern this build does not really apply is worse off than one that never
    read it: it refuses names that would have worked, or stores names that fail
    at session create anyway.
    """
    for name in ("code_search", "", "a_b"):
        assert not re.fullmatch(SERVER_NAME_PATTERN, name)
        with pytest.raises(McpUnsupported):
            validate({name: {"type": "stdio", "command": "true"}})

    for name in ("codesearch", "code-search", "code.search"):
        assert re.fullmatch(SERVER_NAME_PATTERN, name)
        validate({name: {"type": "stdio", "command": "true"}})


# --- the auth method, which is in the same file and blocks every turn --------


def _auth(tmp_path: Path, session_id: str) -> dict | None:
    document = _settings_json(tmp_path, session_id)
    return document.get("security", {}).get("auth")


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA"):
        monkeypatch.delenv(name, raising=False)


def test_a_key_names_the_auth_method_in_the_settings_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GP-54: without this the agent exits 41 and no turn is ever attempted.

    **The trigger is the endpoint variable, not the key.** Setting
    `GOOGLE_GEMINI_BASE_URL` makes the agent infer a `gateway` method its own
    validator has no case for, and an explicitly configured method is what takes
    precedence over that inference. Every deployment behind a gateway sets that
    variable, so this is the difference between a build that works and one that
    cannot take a single turn.
    """
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-not-a-real-key")
    session_id = _open(client, {"acme": {"type": "stdio", "command": "npx"}})
    assert _auth(tmp_path, session_id) == {"selectedType": "gemini-api-key"}


def test_a_provider_selector_outranks_the_key(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order is the agent's own (GP-54), and reversing it breaks Vertex.

    A deployment can set both -- the selector says which product, the key is
    read by one of them -- so choosing by key first would name `gemini-api-key`
    for a Vertex deployment and fail at the far end rather than here.
    """
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-not-a-real-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    session_id = _open(client)
    assert _auth(tmp_path, session_id) == {"selectedType": "vertex-ai"}


def test_an_environment_naming_nothing_gets_no_auth_block(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Absent, not guessed** (GP-54).

    A method written for an environment that names none would be this service
    inventing a credential channel, and the failure it buys is a refusal at the
    gateway naming neither the endpoint nor the credential. Writing nothing
    leaves the agent's own message, which names the three variables.
    """
    _clear_auth_env(monkeypatch)
    session_id = _open(client)
    assert _auth(tmp_path, session_id) is None
    assert "security" not in _settings_json(tmp_path, session_id)
