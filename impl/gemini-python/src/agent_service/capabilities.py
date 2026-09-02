"""`GET /v1/capabilities` — every difference a client must act on, published.

**AS-32: a caller reads this rather than branching on which image it has.** So
every divergence this build carries has to appear here, and each value below is
a measurement or a decision with an entry behind it, never a plausible default.

**The three that will surprise someone porting a client:**

* `allow_supplied_sdk_session_id` is **false** (GP-34). Neither interface accepts
  a caller's id on the durable resume path, so refusing is the honest answer and
  a 400 says why.
* `permission_enforcement` is **`"none"`, and it means something different here**
  than the vocabulary suggests. The field is `Literal["none", "hook"]` -- a
  shape written for a build with an in-process `PreToolUse` hook. This build
  enforces with a generated admin-tier policy (GP-19), which is neither value.
  `"none"` is the truthful answer to the question the field actually asks -- *is
  there in-process write confinement* -- and the Codex build reached the same
  place from a different direction. **It does not mean the agent is unconfined.**
* `sandbox.confines_writes_to_workspace` is **false**, and that is deliberate
  conservatism. The agent's own guard refuses a file tool that leaves the
  workspace and the shell is not on the default allowlist, so writes are in
  practice confined -- but **this service does not itself enforce it** since ACP
  was removed (GP-41), and a capability is a promise about what the service
  does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from functools import lru_cache

from agent_spec.openapi.examples import DEPLOYMENT_DEPENDENT  # noqa: F401
from agent_spec.openapi.schemas import (
    Capabilities,
    Impl,
    LlmCorrelation,
    Mcp,
    McpToolCall,
    Sandbox,
    Sdk,
    SessionMode,
    Spec,
    UnsupportedOption,
)

from agent_service.config import (
    CREDENTIAL_ENV_VARS,
    PROVIDER_SELECTOR_ENV_VARS,
    Settings,
)
from agent_service.mcp import (
    MCP_HTTP_HEADERS,
    MCP_TOOL_CALL_REQUEST_TIMEOUT_S,
    MCP_TOOL_CALL_TOTAL_TIMEOUT_S,
    MCP_TRANSPORTS,
    SERVER_NAME_PATTERN,
)
from agent_service.versions import (
    DOCUMENT_VERSION,
    IMPLEMENTATION_NAME,
    IMPLEMENTATION_VERSION,
)

#: The version every measured fact in this build is pinned to. Reported when the
#: binary cannot be asked, so a wrong answer is visible rather than absent.
PINNED_AGENT_VERSION = "0.54.4"

#: **The `--approval-mode` vocabulary, which is NOT the policy field's** (GP-25).
#: A caller sends these; `policy.FLAG_MODES` maps them to the spelling a `modes`
#: rule needs, and the two differ by an underscore that voids a whole file.
PERMISSION_MODES: tuple[SessionMode, ...] = (
    SessionMode(
        id="default",
        name="Default",
        description=(
            "Prompts for approval, which in headless means the agent decides for "
            "itself. NOT a boundary: across nine trials of one prompt it wrote "
            "once, declined three times and failed to terminate five times. The "
            "generated tool policy is what actually confines a turn."
        ),
    ),
    SessionMode(
        id="auto_edit",
        name="Auto edit",
        description="Auto-approves edit tools. Deterministic, unlike `default`.",
    ),
    SessionMode(
        id="yolo",
        name="YOLO",
        description=(
            "Auto-approves every tool. **Also switches OFF the agent's built-in "
            "shell redirection guard**, so this build always denies redirection "
            "with an explicit policy rule instead."
        ),
    ),
    SessionMode(
        id="plan",
        name="Plan",
        description="Read-only mode, as the agent defines it. Unmeasured here.",
    ),
)

#: What a session may use when the caller names nothing. **Not everything**, and
#: pointedly not the shell: an unrestricted `run_shell_command` voids every other
#: rule in the policy, because the agent writes files with it instead of the tool
#: that was denied (GP-20).
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "read_file",
    "write_file",
    "list_directory",
    "glob",
    "grep_search",
)

#: Refused whatever a caller asks for, for the reason above.
ALWAYS_DISALLOWED_TOOLS: tuple[str, ...] = ("run_shell_command",)

#: `RunOptions` fields this build refuses with a 400 rather than accepting and
#: ignoring. **A published option that nothing applies is the defect the Codex
#: build shipped twice**; refusing loudly is the corrected shape.
UNSUPPORTED_OPTIONS: tuple[UnsupportedOption, ...] = (
    # No equivalent exists on this agent -- not a gap in the wrapper.
    UnsupportedOption(field="effort"),
    UnsupportedOption(field="setting_sources"),
    # **`reference_dirs` is NOT here, and that was a mistake the conformance
    # suite corrected.** It is a CAPABILITY field, not a `RunOptions` one, so a
    # caller cannot send it and this build cannot refuse it -- publishing it
    # promised a 400 that could never happen, which is the same defect as an
    # option accepted and ignored, wearing the opposite coat. The agent's
    # `--include-directories` is unwired, and the honest statement of that is
    # `reference_dirs: []` in the capability itself.
    # The agent reports tokens and latency and no monetary figure at all
    # (GP-16), so a budget cannot be enforced and must not be accepted.
    UnsupportedOption(field="max_budget_usd"),
    # Exit 53 is documented as the turn limit and was never reproduced, so this
    # build will not promise to honour it.
    UnsupportedOption(field="max_turns"),
    # **`strict_mcp_config` is back, and only for the value it refuses.** It came
    # off this list when both it and `mcp_servers` became honoured -- strict mode
    # is the `--allowed-mcp-server-names` flag (GP-47) -- and listing the field
    # then would have promised a 400 for `true`, which works. So the refusal was
    # expressible nowhere and was invisible to the one mechanism a client has for
    # exactly this, which the consumer found by asking rather than by being told.
    # `values` is what makes it sayable: `false` is refused (GP-48), `true` is
    # honoured, and a client reads which is which instead of inferring it.
    UnsupportedOption(field="strict_mcp_config", values=[False]),
    # **The preset OBJECT only, and the string form is honoured** (GP-66).
    # `system_prompt` was published, accepted and applied to nothing until
    # 2026-09-02 -- the exact defect the note above names, shipped by this build
    # rather than the Codex one. The string now reaches the agent through
    # `GEMINI_SYSTEM_MD`; the Claude preset object names a preset this agent does
    # not have, so it is refused by TYPE rather than by field.
    UnsupportedOption(field="system_prompt", types=["object"]),
    # **`mcp_servers` still must NOT appear here**, and for a different reason: a
    # server this build cannot express is refused per SERVER rather than per
    # field, so the field is supported and that particular server is not.
)


@lru_cache(maxsize=1)
def agent_version(binary: str) -> str:
    """`gemini --version`, asked once. Falls back to the pinned version.

    **A local exec: no API call and no cost.** The fallback is the pinned string
    rather than `"unknown"` so that a mismatch between what this build measured
    and what is installed is visible in the payload.
    """
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        return PINNED_AGENT_VERSION
    reported = proc.stdout.strip().splitlines()
    return reported[-1].strip() if reported else PINNED_AGENT_VERSION


def build_capabilities(settings: Settings) -> Capabilities:
    """The payload, assembled from measurements and decisions."""
    return Capabilities(
        spec=Spec(document_version=DOCUMENT_VERSION),
        impl=Impl(name=IMPLEMENTATION_NAME, version=IMPLEMENTATION_VERSION),
        sdk=Sdk(name="gemini-cli", version=agent_version(str(settings.gemini_binary))),
        sdk_version=agent_version(str(settings.gemini_binary)),
        permission_modes=list(PERMISSION_MODES),
        # The agent has no equivalent of an effort dial; an empty list is the
        # truthful answer and `effort` is refused above.
        effort_levels=[],
        setting_sources=[],
        # **"auto" is a routing POLICY, not a model** (GP-15). The opening event
        # of a turn reports this literal string, and the models that actually ran
        # are known only from the final usage.
        default_model=settings.model or "auto",
        default_allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
        always_disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
        # Figures this build ENFORCES. A number here is a promise about
        # behaviour: the turn timeout is enforced by killing the process, which
        # is the only way to end a turn on this agent (GP-02).
        limits={
            "turn_timeout_s": float(settings.turn_timeout_s),
            "max_sessions": float(settings.max_sessions),
            # A consumer sizes a reconciliation window from this, so it is
            # enforced rather than advertised: `Registry` sweeps on every
            # operation.
            "session_idle_ttl_s": float(settings.session_idle_ttl_s),
        },
        # **~7,000 input tokens before the prompt is read** (GP-44), measured
        # over three prompts of three to nine words: 7,072 / 7,076 / 7,082.
        # Published because it changes how a client should batch -- turn COUNT
        # predicts spend here, not prompt length. Approximate by nature: it
        # moves with the agent's version and its tool set.
        turn_token_overhead=7000.0,
        # **FALSE, and measured** (GP-43): a turn carrying both a `tool_use` and
        # a `tool_result` reported `tool_calls: 0`, because the counter counts
        # only calls that reached a registered tool. A client deciding whether a
        # turn used tools must count the events.
        usage_counts_tool_calls=False,
        # **"per_turn", and it is the OPPOSITE of the Claude build** (GP-16). The
        # agent reports each turn's own figures, so summing across a session is
        # correct here and double-counts there. The shape is identical either
        # way, which is why a client cannot infer this and must read it.
        model_usage_scope="per_turn",
        # FALSE: the agent reports tokens and latency and no monetary figure at
        # all (GP-16), so both cost fields are null on every session and every
        # turn, permanently and by nature. `0.0` would read as *free*.
        reports_cost_usd=False,
        workspace_dir=str(settings.workspace_dir),
        reference_dirs=[],
        credential_sources=list(CREDENTIAL_ENV_VARS),
        provider_selectors=list(PROVIDER_SELECTOR_ENV_VARS),
        max_sessions=settings.max_sessions,
        require_credentials=settings.require_credentials,
        # **True when a token is configured, and it is really enforced** --
        # `auth.py` installs middleware over `/v1`. Publishing `true` from a
        # setting nothing checks is the defect the Codex build had to correct in
        # the consumer's favour, and `auth_enforced` in the pre-boot
        # specification is what lets a caller tell the two apart before there is
        # a service to ask.
        auth_required=settings.auth_token is not None,
        allow_mcp_servers=settings.allow_mcp_servers,
        # **"turn", and it is the reason this build refuses a supplied id**
        # (GP-34). The agent mints a new conversation id on EVERY turn of a
        # resumed session, so the value identifies the turn that produced it.
        # A client may route on it; keying on it is wrong here and right on the
        # other two, which is exactly why the scope is published.
        sdk_session_id_scope="turn",
        # **A MEASURED ABSENCE, which is why `measured` is true beside a null**
        # (GP-53). The endpoint variable was pointed at a local sink and a turn
        # was taken: the request arrived, and not one of its headers carried the
        # `session_id` the agent had just reported on its own `init` event. The
        # nearest thing is a privileged-user id, which is a different UUID and
        # not a session. A gateway fronting this build must attribute spend some
        # other way; there is nothing here to read.
        llm_correlation=LlmCorrelation(header=None, measured=True),
        allow_supplied_sdk_session_id=False,
        # The opening event of a turn carries the agent's id, so a one-shot query
        # can report one -- but it is that TURN's id and not a durable handle.
        query_reports_sdk_session_id=True,
        # A one-shot turn is its own process and holds no registry slot.
        query_consumes_a_session_slot=False,
        unsupported_options=list(UNSUPPORTED_OPTIONS),
        sandbox=Sandbox(
            network_access=True,
            confines_writes_to_workspace=False,
        ),
        # **All three transports, and any header** (GP-46). Read from the
        # settings schema in the bundle and then confirmed against the binary --
        # each was registered and listed with its own type. `headers` is declared
        # as an unrestricted string map, which is why this is `"any"` where the
        # Codex build can carry a bearer token and nothing else.
        # `server_name_pattern` is the CONSTANT the request validator gates on,
        # not a copy of it -- a published pattern that disagreed with the actual
        # refusal is the drift AS-32 exists to prevent (GP-28).
        mcp=Mcp(
            transports=list(MCP_TRANSPORTS),
            http_headers=MCP_HTTP_HEADERS,
            server_name_pattern=SERVER_NAME_PATTERN,
            # **TWO timers, and the first one was published as `null` for a day
            # on the strength of a bundle read** (GP-64, corrected by GP-65).
            # The response must BEGIN within 60 s -- measured at 60.2 s against
            # this image, with no proxy variables set -- and the whole call must
            # finish within 600 s regardless of activity.
            #
            # `progress_resets_idle` is FALSE rather than null because the agent
            # sends a `progressToken` on every call and the flag that would make
            # it hold the call open is never passed -- so progress arrives, is
            # displayed, and buys nothing.
            tool_call=McpToolCall(
                request_timeout_s=MCP_TOOL_CALL_REQUEST_TIMEOUT_S,
                idle_timeout_s=None,
                total_timeout_s=MCP_TOOL_CALL_TOTAL_TIMEOUT_S,
                progress_resets_idle=False,
            ),
        ),
        # **True, and it is the DEFAULT rather than merely available** (GP-47).
        # A `.gemini/settings.json` in the workspace merges into the session's
        # own (GP-46), and the workspace is mounted from the host and writable by
        # the agent -- so without strict mode a repository could add servers the
        # caller never sent. `--allowed-mcp-server-names` is argv, which no
        # settings file can override.
        strict_mcp_config=True,
        require_mounts=settings.require_mounts,
        permission_enforcement="none",
    )




def reference_capabilities() -> Capabilities:
    """This build's capabilities under its OWN DEFAULTS, for the document.

    **Published as the `example` on `GET /v1/capabilities` so that the document
    alone shows what this build actually answers** -- an OpenAPI document
    otherwise describes the SHAPE of the payload and says nothing about its
    values, so a consumer holding three documents cannot see how the three
    builds differ without starting three containers.

    **It must be deployment-invariant, and that is the whole design
    constraint.** AS-24 requires the running service to serve exactly the
    published document, so an example built from a live `Settings` would make
    every deployment's document differ from the published one the moment an
    operator changed a port or a cap. So: defaults only, and a binary path that
    does not exist, which makes `agent_version` fall back to the pinned constant
    rather than shelling out to whatever is on the developer's PATH.

    The fields in `DEPLOYMENT_DEPENDENT` are therefore illustrative here. Every
    other field is a fact about the BUILD and is exactly what a live instance
    returns -- pinned by a test, so the example cannot drift.
    """
    return build_capabilities(
        Settings(
            # **`PurePosixPath`, not `Path`, and it is not pedantry.**
            # `str(Path("/workspace"))` is `\workspace` on Windows and
            # `/workspace` on Linux, so a document generated on a developer's
            # machine baked in a path the container could never reproduce and
            # AS-24 failed in CI -- the published document said one thing and
            # the running service said another.
            workspace_dir=PurePosixPath("/workspace"),
            agent_home_root=PurePosixPath("/var/lib/agent-service/homes"),
            transcript_store=PurePosixPath("/var/lib/agent-service/transcripts"),
            # Deliberately absent: `agent_version` falls back to the pinned
            # version instead of probing, so the document is reproducible on any
            # machine.
            gemini_binary=Path("agent-not-probed-for-the-published-example"),
        )
    )
