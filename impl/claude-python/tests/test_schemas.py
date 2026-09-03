import pytest
from pydantic import ValidationError

from agent_spec.openapi.schemas import (
    SessionMode,
    AgentEvent,
    Deployment,
    Health,
    Problem,
    QueryRequest,
    RunOptions,
    RunResponse,
)


def test_query_request_requires_a_prompt() -> None:
    with pytest.raises(ValidationError):
        QueryRequest()


def test_run_options_are_all_optional() -> None:
    opts = RunOptions()
    assert opts.model is None
    assert opts.allowed_tools is None
    assert opts.max_turns is None


def test_query_request_defaults_options() -> None:
    req = QueryRequest(prompt="hi")
    assert isinstance(req.options, RunOptions)


def test_permission_mode_is_NO_LONGER_constrained_by_the_schema() -> None:
    """0.19.0: the constraint moved from the model to the build, on purpose.

    It was a closed `Literal` of six values -- all six the Claude Agent SDK's
    own enum, adopted as the specification's because this was the first
    implementation. Every other build then had to accept values it could not
    honour. Each build declares its own set on `/v1/deployment` now, so the
    shared model cannot validate: there is no set here to validate against.

    **The refusal did not disappear, it moved**, and
    `test_an_undeclared_permission_mode_is_refused` is where it lives. This test
    exists so that a future reader finding an unconstrained string does not
    "fix" it back into a union.
    """
    RunOptions(permission_mode="dontAsk")
    RunOptions(permission_mode="a-mode-some-future-build-declares")


def test_effort_is_constrained() -> None:
    RunOptions(effort="high")
    with pytest.raises(ValidationError):
        RunOptions(effort="turbo")


def test_agent_event_allows_null_content() -> None:
    event = AgentEvent(seq=1, type="system", subtype="init", content=None)
    assert event.content is None
    assert event.raw is None


def test_agent_event_type_is_constrained() -> None:
    with pytest.raises(ValidationError):
        AgentEvent(seq=1, type="bogus")


def test_max_turns_boundary() -> None:
    RunOptions(max_turns=1)
    with pytest.raises(ValidationError):
        RunOptions(max_turns=0)


def test_timeout_s_boundary() -> None:
    RunOptions(timeout_s=1)
    with pytest.raises(ValidationError):
        RunOptions(timeout_s=0)


def test_max_budget_usd_boundary() -> None:
    RunOptions(max_budget_usd=0.01)
    with pytest.raises(ValidationError):
        RunOptions(max_budget_usd=0)


def test_query_request_prompt_min_length() -> None:
    QueryRequest(prompt="x")
    with pytest.raises(ValidationError):
        QueryRequest(prompt="")


def test_run_response_limit_hit_is_constrained() -> None:
    RunResponse(limit_hit="turns")
    RunResponse(limit_hit="budget")
    RunResponse(limit_hit=None)
    with pytest.raises(ValidationError):
        RunResponse(limit_hit="bogus")
    # "timeout" is deliberately not a valid value (M1, final review): a
    # timed-out run raises RunTimeout, which becomes a 504 Problem document
    # or an in-band event: error, never a RunResponse -- so this field can
    # never actually carry it, and offering it in the OpenAPI enum would let
    # clients code an unreachable branch.
    with pytest.raises(ValidationError):
        RunResponse(limit_hit="timeout")


def test_health_status_is_constrained() -> None:
    fields = {
        "credentials_configured": True,
        "auth_required": False,
        "workspace_dir": "/tmp",
        "database_configured": False,
        "database_usable": None,
    }
    Health(status="ok", **fields)
    with pytest.raises(ValidationError):
        Health(status="bogus", **fields)


def test_the_database_fields_are_required_so_absence_is_never_ambiguous() -> None:
    """`database_usable` is nullable but NOT optional.

    `null` has to mean "no database is configured" and nothing else. If the
    field could simply be missing, a client could not tell that from "this
    service is too old to say", which is the ambiguity AS-17a rejects for
    `SessionRecord.sdk_session_id`.
    """
    with pytest.raises(ValidationError):
        Health(status="ok", credentials_configured=True, workspace_dir="/tmp")

    schema = Health.model_json_schema()
    assert "database_configured" in schema["required"]
    assert "database_usable" in schema["required"]


def test_capabilities_instantiation() -> None:
    caps = Deployment.from_flat(
        # Required and with NO default, deliberately: a build that does not say
        # what its `sdk_session_id` is an id of cannot construct this at all,
        # which is the point of the field.
        sdk_session_id_scope="conversation",
        credential_sources=["ANTHROPIC_API_KEY"],
        provider_selectors=["CLAUDE_CODE_USE_BEDROCK"],
        max_sessions=8,
        require_credentials=True,
        require_mounts=True,
        auth_required=False,
        allow_mcp_servers=True,
        allow_supplied_sdk_session_id=True,
        # AS-32 (0.19.0): both required, so a build cannot ship an extension
        # without saying whether it has it.
        query_reports_sdk_session_id=False,
        query_consumes_a_session_slot=False,
        # Required for the same reason, and it is the general case of the two
        # above: a build states which `RunOptions` fields it refuses rather than
        # leaving a caller to find out from a 400.
        unsupported_options=[],
        # What confines the AGENT's tools, and which MCP servers a build can
        # express. Required for the same reason as the fields above: the two
        # builds differ on both, and a client sending an `sse` server or an
        # Agent that shells out must read the difference rather than discover it
        # from a 400 or from a tool that never works.
        sandbox={"network_access": True, "confines_writes_to_workspace": False},
        # `behaviour.mcp_tool_call` is REQUIRED and `server_name_pattern` is
        # not, which is the same distinction the rest of this payload draws: a
        # build that enforces no name pattern has nothing to say, while a build
        # that cannot state what ends a long tool call must fail to construct
        # this rather than leave a client to discover it by holding one open
        # until it dies.
        #
        # **The two used to be one object.** What a caller may EXPRESS is here;
        # how long the call may run is behaviour, and lives beside the other
        # timers a client designs around.
        mcp={
            "transports": ["stdio", "sse", "http"],
            "http_headers": "any",
        },
        strict_mcp_config=True,
        spec={"document_version": "0.14.0"},
        impl={"name": "claude-python", "version": "0.14.0"},
        sdk={"name": "claude-agent-sdk", "version": "1.0.0"},
        sdk_version="1.0.0",
        permission_modes=[SessionMode(id="default", name="Default", description="d")],
        effort_levels=["medium"],
        setting_sources=["project"],
        default_model="claude-sonnet-5",
        default_allowed_tools=["Read"],
        always_disallowed_tools=["AskUserQuestion"],
        # **Two maps and the tool-call timers moved**: a ceiling on a request
        # and a figure the service enforces are different claims, so a
        # constructor that could satisfy the model with one of them would be
        # letting the split go untested.
        accepts_limits={"max_allowed_turns": 50},
        behaviour_limits={"session_idle_ttl_s": 1800},
        mcp_tool_call={"request_timeout_s": 60, "idle_timeout_s": 300,
                       "total_timeout_s": 100000, "progress_resets_idle": True},
        # Both required (0.19.0), on the same reasoning as the fields above: a
        # build that cannot say how to aggregate its own numbers, or whether it
        # reports money at all, should fail to construct this payload rather than
        # answer with a reassuring value nobody measured.
        model_usage_scope="cumulative",
        reports_cost_usd=True,
        # Required, and an OBJECT rather than a nullable string: `header: null`
        # means two different things depending on `measured`, and a consumer
        # acts differently on each.
        llm_correlation={"header": "x-claude-code-session-id", "measured": True},
        workspace_dir="/workspace",
        reference_dirs=["/workspace/refs"],
        permission_enforcement="none",
    )
    # **Dotted through the groups**, which is the change: `sdk` answers who is
    # running and `default_model` answers how this instance was configured, and
    # the payload now says so rather than leaving both at the top level.
    assert caps.service.sdk.name == "claude-agent-sdk"
    assert caps.service.sdk.version == "1.0.0"
    assert caps.service.sdk_version == "1.0.0"
    assert caps.config.default_model == "claude-sonnet-5"


def test_problem_instantiation() -> None:
    problem = Problem(title="Bad Request", status=400)
    assert problem.type == "about:blank"
    assert problem.detail is None
