"""`GET /v1/deployment` — every difference a client must act on, published.

**AS-32: a caller reads this rather than branching on which image it has.** So
every divergence this build carries has to appear here, and each value below is
a measurement or a decision with an entry behind it, never a plausible default.

**The four that will surprise someone porting a client:**

* `reports_cost_usd` is **true** (`PI-17`), and this is the second build of four
  that can say so. Cost arrives in USD on every model call, on every provider.
* `permission_modes` holds **`default` and nothing else** (`PI-22`). Pi has no
  per-operation approval in headless mode at all: trust is binary and
  project-level, and plan mode is named on its own usage page as one of the
  things it deliberately omits. `plan` is OMITTED rather than mapped onto
  something that does not mean the same thing.
* `allow_supplied_sdk_session_id` is **true** (`PI-14`) -- `--session-id` is
  echoed back verbatim -- where two of the other three builds refuse.
* `mcp` is **whole-or-nothing** (`PI-45`). Servers are honoured, but the agent
  sees one PROXY tool rather than the server's own tool names, so
  `allowed_tools` can permit or deny all MCP and nothing finer. Agent Harness
  asked for it in that form knowing the cost, which is why it is built.
* `effort_levels` is **empty even though the agent has a thinking dial**
  (`PI-23`), which is the one place this build gives up a real capability. The
  dial is per MODEL, and this field is a flat list meaning *delivered exactly*.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath

from agent_spec.openapi.examples import DEPLOYMENT_DEPENDENT  # noqa: F401
from agent_spec.openapi.schemas import (
    Deployment,
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
from agent_service.mcp import MCP_TRANSPORTS, SERVER_NAME_PATTERN
from agent_service.versions import (
    DOCUMENT_VERSION,
    IMPLEMENTATION_NAME,
    IMPLEMENTATION_VERSION,
)

#: The version every measured fact in this build is pinned to. Reported when the
#: binary cannot be asked, so a wrong answer is visible rather than absent.
PINNED_AGENT_VERSION = "0.85.1"

#: **What an omitted `permission_mode` resolves to** (`PI-51`). It is the only
#: mode this build has, and it is still named rather than left as a literal
#: `or "default"` in two places: the fact is now published as well as applied,
#: and a third copy is where a build acquiring a second mode would drift.
DEFAULT_PERMISSION_MODE = "default"

#: **One mode, and the list is short because the agent is** (`PI-22`).
PERMISSION_MODES: tuple[SessionMode, ...] = (
    SessionMode(
        id="default",
        name="Default",
        description=(
            "The agent's only mode. Pi has no per-operation approval in "
            "headless use: its trust gate is binary and project-level, and "
            "non-interactive runs skip it entirely. What confines a turn here "
            "is the tool allowlist and the container -- nothing else."
        ),
    ),
)

#: What a session may use when the caller names nothing. **Not everything**, and
#: pointedly not either shell (`PI-24`): Pi has `bash` AND `powershell` built in,
#: has no sandbox of its own, and its own documentation says so -- so a shell is
#: unrestricted access to the container. A caller may still ask for one through
#: `allowed_tools`; it is not the default.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "ls",
    "grep",
    "find",
)

#: Refused whatever a caller asks for. **`ask_question` blocks a headless turn**
#: (`PI-25`): it exists to put a question to a human, there is no human, and Pi's
#: own examples show it being excluded for exactly this reason. The Claude build
#: refuses `AskUserQuestion` for the same reason under a different name.
ALWAYS_DISALLOWED_TOOLS: tuple[str, ...] = ("ask_question",)

#: `RunOptions` fields this build refuses with a 400 rather than accepting and
#: ignoring. **A published option that nothing applies is this platform's oldest
#: defect**; refusing loudly is the corrected shape.
UNSUPPORTED_OPTIONS: tuple[UnsupportedOption, ...] = (
    # **The one refusal that gives up a capability the agent has** (`PI-23`).
    UnsupportedOption(field="effort"),
    # Pi's suppression switches are per KIND -- context files, skills,
    # extensions, prompt templates -- and this field's vocabulary is per LAYER:
    # user, project, local. The two do not map onto each other, so honouring it
    # would mean choosing which lie to tell (`PI-19`).
    UnsupportedOption(field="setting_sources"),
    # **Refused despite `reports_cost_usd: true`, and the pairing is the point**
    # (`PI-26`). One invocation runs the agent's whole loop, so cost is known
    # only as each model call ends -- by which time the work is done. Enforcing
    # a budget would mean killing mid-loop and discarding the answer the caller
    # is paying for. A client sums `total_cost_usd` across turns instead, which
    # is what publishing the figure is for.
    UnsupportedOption(field="max_budget_usd"),
    # Same shape, same reason: the agent decides its own loop and there is no
    # flag to cap it (`PI-26`).
    UnsupportedOption(field="max_turns"),
    # **`mcp_servers` is NOT here, and the distinction is AS-24's** (`PI-45`).
    # Whether this deployment accepts servers depends on whether its image
    # carries the adapter, and `unsupported_options` is in the published
    # DOCUMENT -- a field that moved in and out of it per deployment would make
    # every deployment's document differ from the published one. A deployment
    # without the adapter refuses with a NAMED 400 and publishes
    # `allow_mcp_servers: false`, which is the same shape the gemini build uses.
    #
    # **`strict_mcp_config` IS here, and only for the value it refuses.** This
    # build passes `--mcp-config` naming its own file, so the adapter's six-file
    # precedence chain never runs and non-strict is not a behaviour it can
    # produce. `true` is honoured; `false` is refused.
    UnsupportedOption(field="strict_mcp_config", values=[False]),
    # **The preset OBJECT only; the string form is honoured** (`PI-20`). The
    # string reaches the agent as `--system-prompt` and replaces its framing.
    # The Claude preset object names a preset this agent does not have.
    UnsupportedOption(field="system_prompt", types=["object"]),
)


@lru_cache(maxsize=1)
def agent_version(binary: str) -> str:
    """`pi --version`, asked once. Falls back to the pinned version.

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


def build_capabilities(settings: Settings) -> Deployment:
    """The payload, assembled from measurements and decisions."""
    version = agent_version(str(settings.pi_binary))
    return Deployment.from_flat(
        spec=Spec(document_version=DOCUMENT_VERSION),
        impl=Impl(name=IMPLEMENTATION_NAME, version=IMPLEMENTATION_VERSION),
        # **A real SDK exists and this build does not use it** (`PI-11`). It is
        # TypeScript; this build is Python and drives the binary. The name is
        # the agent's, which is what a client keys on.
        sdk=Sdk(name="pi-coding-agent", version=version),
        sdk_version=version,
        permission_modes=list(PERMISSION_MODES),
        default_permission_mode=DEFAULT_PERMISSION_MODE,
        effort_levels=[],
        setting_sources=[],
        # **Provider AND model, because Pi addresses a model as both** (`PI-10`).
        # A bare id is ambiguous across a 30-provider catalogue, so the published
        # default carries the provider when one is configured.
        default_model=_default_model(settings),
        default_allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
        always_disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
        accepts_limits={},
        behaviour_limits={
            "turn_timeout_s": float(settings.turn_timeout_s),
            "max_sessions": float(settings.max_sessions),
            "session_idle_ttl_s": float(settings.session_idle_ttl_s),
        },
        # **~550 input tokens before the prompt is read** (`PI-28`), measured
        # with tools off and every ambient source suppressed; roughly 1,150-1,400
        # with the default tool set on. An order of magnitude under the Gemini
        # build's 7,000, and published for the same reason: it changes how a
        # client should batch.
        turn_token_overhead=550.0,
        # **FALSE**: the per-turn usage object carries tokens and cost and no
        # tool-call count at all. `get_session_stats` has one, but that is a
        # session figure on an interface this build does not drive (`PI-11`).
        usage_counts_tool_calls=False,
        # **"per_turn", checked rather than assumed** (`PI-16`). Two model calls
        # in one run reported 2,150 and 2,095 input tokens -- the second is not a
        # running total -- so summing is correct here.
        model_usage_scope="per_turn",
        # **TRUE, on every provider** (`PI-17`).
        reports_cost_usd=True,
        workspace_dir=str(settings.workspace_dir),
        reference_dirs=[],
        credential_sources=list(CREDENTIAL_ENV_VARS),
        provider_selectors=list(PROVIDER_SELECTOR_ENV_VARS),
        max_sessions=settings.max_sessions,
        require_credentials=settings.require_credentials,
        auth_required=settings.auth_token is not None,
        # **Deployment-dependent** (`PI-43`): true when the image carries the
        # adapter. A plain checkout has no adapter, so a developer sees `false`
        # and a refusal naming the reason rather than a route that half-works.
        allow_mcp_servers=settings.mcp_adapter_path is not None,
        # **"conversation"** (`PI-13`): the id survives across processes and a
        # second one resumed the conversation with it on all three providers.
        sdk_session_id_scope="conversation",
        # **"store_volume"** (`PI-53`). The conversation is the `.jsonl` under
        # this service's own session store, which `--session-dir` points the
        # agent straight at, and the id-to-directory index sits beside it. A
        # configured database records runs and is never read back into a turn.
        resume_durability="store_volume",
        # **A null that has NOT been measured, and `measured: false` says so**
        # (`PI-29`). The Gemini build published a measured absence here by
        # pointing its endpoint variable at a sink and reading the headers. This
        # build's redirect is a proxy and that experiment has not been run, so
        # the honest report is "nothing known" rather than "nothing there".
        llm_correlation=LlmCorrelation(header=None, measured=False),
        # **TRUE** (`PI-14`), where the Codex and Gemini builds refuse.
        allow_supplied_sdk_session_id=True,
        # The opening event carries the id before the first model call (`PI-21`).
        query_reports_sdk_session_id=True,
        # A one-shot turn is its own process and holds no registry slot.
        query_consumes_a_session_slot=False,
        unsupported_options=list(UNSUPPORTED_OPTIONS),
        # **Both true to type, and Pi says so itself** (`PI-30`): *"Pi does not
        # include a built-in sandbox"*, and *"A partial in-process sandbox would
        # be easy to misunderstand as a security boundary"*. The container is the
        # entire boundary. This is not conservatism about an unmeasured guard --
        # there is no guard.
        sandbox=Sandbox(
            network_access=True,
            confines_writes_to_workspace=False,
        ),
        # **`stdio` and `http`, both measured** (`PI-46`). `sse` is absent
        # because the adapter folds it into its HTTP transport as a fallback
        # rather than offering it as a choice, so listing it would name a
        # transport a caller cannot select.
        #
        # **`server_name_pattern` forbids the underscore, and that is not
        # cosmetic** (`PI-45`): the proxy addresses a tool as `<server>_<tool>`,
        # so an underscore in a server name makes the pair ambiguous.
        mcp=Mcp(transports=list(MCP_TRANSPORTS), http_headers="any",
                server_name_pattern=SERVER_NAME_PATTERN),
        # **60 s TOTAL, cleared by nothing, and this value has been wrong
        # twice** (`PI-49`). It published `null`; then `request_timeout_s: 60`
        # on a reading that turned out to be an artifact; it is
        # `total_timeout_s: 60`.
        #
        # Three shapes measured against a server that stalls on purpose, and all
        # three are cut at about a minute:
        #
        #   no response at all              -> 61.6 s, 63.6 s
        #   headers at once, body never     -> 61.9 s
        #   headers AND data every 20 s     -> 61.5 s, ticks delivered throughout
        #
        # So responding does not clear it and a frame that counts does not reset
        # it, which is exactly the specification's definition of the third timer:
        # *cleared by nothing; it expires while the call is healthy*.
        #
        # **The client's own error is the authority, not the socket.** The
        # earlier wrong reading came from `res.on("close")` not firing until the
        # agent process exited, which looked like a call still open at 268 s
        # while the adapter had already answered `Failed to call tool: Request
        # timed out`. A tool result is evidence; an unclosed socket is not.
        #
        # **This is the row Agent Harness must act on**: their held tool cannot
        # be held here. A call that needs longer than a minute has to return
        # promptly and be polled.
        mcp_tool_call=McpToolCall(
            request_timeout_s=None,
            idle_timeout_s=None,
            total_timeout_s=60.0,
            progress_resets_idle=False,
        ),
        # **Structural rather than a setting** (`PI-45`): `--mcp-config` names
        # this service's own file, so the adapter's six-file precedence chain --
        # which includes two paths inside the caller's mounted workspace --
        # never runs. `false` is refused because it is not a behaviour this
        # build can produce.
        strict_mcp_config=True,
        require_mounts=settings.require_mounts,
        # **"none", and here it is the literal truth rather than a vocabulary
        # mismatch.** The other builds answer `none` because their enforcement
        # has a different shape; this one has no in-process write confinement of
        # any kind to describe.
        permission_enforcement="none",
    )


def _default_model(settings: Settings) -> str:
    """The published default, carrying its provider when one is configured.

    **`"unset"` rather than a guess when neither is configured** (`PI-10`). Pi
    with no `--provider` and no `--model` picks from whatever credentials it
    finds, which is a deployment fact this service cannot state in advance --
    and naming a plausible model would be a promise about which vendor is billed.
    """
    if settings.provider and settings.model:
        return f"{settings.provider}/{settings.model}"
    return settings.model or settings.provider or "unset"


def reference_capabilities() -> Deployment:
    """This build's capabilities under its OWN DEFAULTS, for the document.

    **Published as the `example` so that the document alone shows what this
    build actually answers** -- an OpenAPI document otherwise describes the
    SHAPE of a payload and says nothing about its values, so a consumer holding
    four documents cannot see how the builds differ without starting four
    containers.

    **It must be deployment-invariant, and that is the whole design
    constraint.** AS-24 requires the running service to serve exactly the
    published document, so an example built from a live `Settings` would make
    every deployment's document differ from the published one the moment an
    operator changed a cap.
    """
    return build_capabilities(
        Settings(
            # **`PurePosixPath`, not `Path`, and it is not pedantry.**
            # `str(Path("/workspace"))` is `\workspace` on Windows, so a document
            # generated on a developer's machine would bake in a path the
            # container could never reproduce and AS-24 would fail in CI.
            workspace_dir=PurePosixPath("/workspace"),
            agent_dir_root=PurePosixPath("/var/lib/agent-service/agent-dirs"),
            session_store=PurePosixPath("/var/lib/agent-service/sessions"),
            # Deliberately absent: `agent_version` falls back to the pinned
            # version instead of probing, so the document is reproducible on any
            # machine.
            pi_binary=Path("agent-not-probed-for-the-published-example"),
        )
    )
