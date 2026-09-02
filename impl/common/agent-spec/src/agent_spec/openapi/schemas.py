"""Pydantic models for the HTTP surface. These generate the OpenAPI spec."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

#: **An OPAQUE mode id. Each build declares its own set and this type does not
#: enumerate them** (0.19.0).
#:
#: It was a closed `Literal` of six values -- `default`, `acceptEdits`, `plan`,
#: `bypassPermissions`, `dontAsk`, `auto` -- and **all six are one SDK's enum**,
#: the Claude Agent SDK's, adopted wholesale as the specification's. The cost
#: was not hypothetical: every build had to ACCEPT all six whatever it could
#: honour, so both shipped builds published all six from the same shared list
#: while one of them was mapping six Anthropic-shaped values onto a sandbox and
#: an approval mode, with one value deliberately unreachable. A third agent adds
#: a seventh entry that two builds must refuse.
#:
#: **So a build declares what it has** -- `Capabilities.permission_modes` is a
#: list of `SessionMode` objects with an id, a name and a description -- and a
#: caller reads that list rather than a union. A build refuses an id it did not
#: declare with a 400; nothing here validates it, because there is no set here
#: to validate against.
#:
#: This is what AS-32 already says about every other difference: publish it,
#: do not average it away.
PermissionMode = str

#: Ids every build SHOULD use where it has an equivalent, so that one payload
#: keeps working against more than one implementation.
#:
#: **Deliberately two.** Agent Harness asked for the set to be kept if it is
#: cheap and named these as the ones worth keeping stable: `plan`, a read-only
#: run that is useful without any interactive approver, and `default` beside it.
#: Anything more is a union growing back under a different name.
#:
#: **A build that has no equivalent simply does not declare the id.** It must
#: never map one of these onto something that does not mean it -- an honest gap
#: is a 400 a caller can read, and a dishonest mapping is a turn that does
#: something the caller did not ask for.
WELL_KNOWN_PERMISSION_MODES: tuple[str, ...] = ("default", "plan")
#: Why a turn ended, as a CLOSED set every implementation maps onto.
#:
#: **This exists because the answer was previously spread over seven fields.**
#: `subtype`, `stop_reason` and `terminal_reason` are each an SDK's own spelling
#: passed through verbatim, and `is_error`, `interrupted`, `timed_out` and
#: `limit_hit` are typed flags that each carry one part of the answer. A client
#: could reconstruct most endings from the flags and had to match vendor prose
#: for the rest -- a refusal, a token ceiling, an ordinary end of turn.
#:
#: **The three strings stay exactly as they are.** This is the `token_usage`
#: beside `usage` pattern: a named, closed field for a client to branch on, with
#: the verbatim vendor value still there for a human reading a log.
#:
#: `other` is the escape hatch and is REQUIRED to exist: a closed set with no
#: escape forces an implementation to lie when its SDK grows an ending nobody
#: has mapped yet.
StopKind = Literal[
    "end_turn",
    "max_turns",
    "max_budget",
    "max_tokens",
    "refusal",
    "interrupted",
    "timed_out",
    "error",
    "other",
]

#: What a build's `sdk_session_id` is an id OF, which is not the same on every
#: build and cannot be inferred from the value.
#:
#: **Requested by Agent Harness (2026-08-12), and the `endpoint_source`
#: precedent**: a sentence in correspondence that a client must act on becomes a
#: published field, because prose drifts and no test catches it.
SdkSessionIdScope = Literal["turn", "conversation"]

#: How to aggregate `model_usage` across the turns of one session.
#:
#: **Requested by Agent Harness (2026-08-12), and the one field in that request
#: that changes a client's CORRECTNESS rather than its convenience**: the field
#: has the same name, shape and type on every build, so a scanner that learns the
#: rule from one and applies it to another double-counts or under-counts with
#: nothing in the payload to warn it.
#:
#: `"not_reported"` exists because neither of the other two is right for a build
#: that emits `model_usage: null` on every turn. *Sum it* and *difference it* are
#: both wrong instructions there; *skip it* is the correct one.
ModelUsageScope = Literal["per_turn", "cumulative", "not_reported"]

EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
SettingSource = Literal["user", "project", "local"]
EventType = Literal["system", "assistant", "user", "result", "stream_event", "rate_limit", "unknown"]


class SessionMode(BaseModel):
    """One permission mode a build actually honours.

    **The id is the contract; the name and description are for a human.** A
    client branches on `id` and never on the prose, which is the same rule
    `unsupported_options` learned when a sentence appeared where an identifier
    was expected and no client could match it.
    """

    id: str = Field(
        min_length=1,
        examples=["plan"],
        description=(
            "What a caller sends as `options.permission_mode`. Stable for a "
            "given build; `default` and `plan` are well-known across builds "
            "that have an equivalent."
        ),
    )
    name: str = Field(
        min_length=1,
        examples=["Plan"],
        description="Short human label. Never branch on it.",
    )
    description: str = Field(
        min_length=1,
        examples=["Read and reason; change nothing."],
        description=(
            "What this mode actually permits ON THIS BUILD -- not what the id "
            "suggests elsewhere. Two builds may honour the same id by "
            "different mechanisms, and this is where that is said."
        ),
    )


class McpStdioServer(BaseModel):
    """An MCP server this service SPAWNS AS A SUBPROCESS.

    It starts with the session, before any prompt, and appears in no turn's
    events -- unlike a tool call, which is the agent's own decision and is
    recorded. Operators who need every process start attributable to a turn set
    `AGENT_SERVICE_ALLOW_MCP_SERVERS=false`, published as
    `Capabilities.allow_mcp_servers`.
    """

    type: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1, examples=["npx"])
    args: list[str] | None = Field(default=None, examples=[["-y", "@acme/mcp"]])
    env: dict[str, str] | None = Field(
        default=None,
        description=(
            "Environment for the SPAWNED SERVER's process only -- it cannot "
            "reach the agent's CLI. **Treat as credential material** in logs "
            "and storage. This service never logs it."
        ),
    )


class McpSseServer(BaseModel):
    """An MCP server reached over SSE. No subprocess."""

    type: Literal["sse"]
    url: str = Field(min_length=1, examples=["https://mcp.example.com/sse"])
    headers: dict[str, str] | None = Field(
        default=None,
        description=(
            "Sent to `url` on every request. The other position ADR-0023 "
            "substitutes a secret into. Never logged by this service."
        ),
    )


class McpHttpServer(BaseModel):
    """An MCP server reached over HTTP. No subprocess."""

    type: Literal["http"]
    url: str = Field(min_length=1, examples=["https://mcp.example.com/mcp"])
    headers: dict[str, str] | None = Field(
        default=None,
        description="Sent to `url` on every request. Never logged by this service.",
    )


#: The SDK also has `McpSdkServerConfig` -- `{type: "sdk", name, instance}` --
#: and it is deliberately ABSENT here rather than rejected with a message.
#: `instance` is a live in-process `McpServer` OBJECT, so the shape cannot cross
#: an HTTP boundary at all: there is nothing a caller could send that would
#: become one. Omitting it from the union means the OpenAPI document says so and
#: a generated client cannot express it, which is a better answer than a runtime
#: error for a request that could never have worked.
McpServer = McpStdioServer | McpSseServer | McpHttpServer


class RunOptions(BaseModel):
    """Per-request overrides. Every field falls back to server config when omitted."""

    model: str | None = Field(
        default=None, min_length=1, examples=["claude-sonnet-5"],
        description=(
            "Omit to use the server default. An empty string is rejected "
            "rather than treated as omission."
        ),
    )
    resume: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Continue a previous conversation. This is the **SDK** session "
            "id (`sdk_session_id`), NOT the service-side `session_id`.\n\n"
            "With a database configured the conversation survives a service "
            "restart; without one, only while the CLI's on-disk transcript "
            "remains. Resumes a CONVERSATION, not an in-flight stream -- a "
            "turn interrupted by a disconnect is not resumable."
        ),
    )
    system_prompt: str | dict[str, Any] | None = Field(
        default=None,
        description=(
            'A plain string, or a preset object such as '
            '{"type": "preset", "preset": "claude_code", "append": "..."}.\n\n'
            "**The string form REPLACES the agent's own framing** -- its "
            "safety rules, its tool protocol, its workflows -- on every build "
            "that accepts it; the preset object is the only form that keeps "
            "them and appends, and not every build has one (read "
            "`unsupported_options` for `{field: system_prompt, types: "
            '["object"]}`).\n\n'
            "**It is NOT a substitute for ambient configuration.** It does not "
            "become a memory file, register a skill or define a subagent, and "
            "it suppresses nothing the agent reads from disk -- on at least one "
            "build the workspace's context files are appended after it. See "
            "`setting_sources`."
        ),
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description=(
            "Grants a tool capability, **by whatever names the build's own "
            "agent gives its tools** -- they differ between builds, so read "
            "`default_allowed_tools` and `always_disallowed_tools` for the "
            "vocabulary this one accepts.\n\n"
            "NOT a path or command restriction: a read tool named here permits "
            "reading any path, and a scoped syntax some agents accept -- "
            "`Bash(git status:*)` on one of them -- is not enforced here. Path "
            "and command policy is applied server-side."
        ),
    )
    disallowed_tools: list[str] | None = Field(
        default=None, description="Removes a capability outright. AskUserQuestion is always included."
    )
    permission_mode: PermissionMode | None = None
    effort: EffortLevel | None = None
    setting_sources: list[SettingSource] | None = Field(
        default=None,
        description=(
            "Which ambient on-disk agent configuration to load, for a build "
            "that has any. Server default is none, and a build with no such "
            "concept publishes an empty list and refuses the field.\n\n"
            "**A SWITCH over what is already on the container's disk -- never a "
            "way to send that configuration.** The agent reads memory files, "
            "skills, subagents, commands, plugins and settings from inside its "
            "own container, and NO field of `RunOptions` can supply any of "
            "them on any build. This field is the only lever over that input, "
            "it is coarse, and two of the three builds do not have all of it: "
            "one refuses the field outright, so what its workspace carries is "
            "read on every turn whatever a caller sends. Treat the container's "
            "disk as part of the deployment rather than part of the request."
        ),
    )
    max_turns: int | None = Field(default=None, ge=1)
    max_budget_usd: float | None = Field(
        default=None,
        gt=0,
        description=(
            "**NOT A SPEND CAP. It cannot bound what a session costs.** It "
            "is enforced by the CLI against its cumulative figure, and that "
            "figure does not move for an INTERRUPTED turn -- so a caller that "
            "can interrupt turns can spend without limit under any value set "
            "here. The only effective control is an account- or "
            "organisation-level budget."
        ),
    )
    timeout_s: int | None = Field(default=None, ge=1)
    workspace_subdir: str | None = Field(
        default=None, description="Relative path under the workspace root to use as cwd."
    )
    include_partial_messages: bool = False
    include_raw: bool | None = Field(
        default=None, description="Include the full SDK message dump on each event."
    )
    mcp_servers: dict[str, McpServer] | None = Field(
        default=None,
        description=(
            "MCP servers for this run, keyed by server name. Omit for none.\n\n"
            "Three transports: `stdio` (this service spawns a subprocess -- read "
            "`McpStdioServer` first), `sse` and `http` (no subprocess). The SDK's "
            "fourth shape, `sdk`, is absent on purpose: it carries a live "
            "in-process object and cannot cross an HTTP boundary.\n\n"
            "**Refused with 400 when the deployment sets "
            "`AGENT_SERVICE_ALLOW_MCP_SERVERS=false`.** Check "
            "`Capabilities.allow_mcp_servers` before relying on this field, the "
            "same way `credential_sources` is checked before injecting a key.\n\n"
            "`env` on a stdio server and `headers` on an http/sse one are the "
            "two positions a caller substitutes credentials into. Neither is "
            "ever logged by this service."
        ),
        examples=[{"acme": {"type": "http", "url": "https://mcp.example.com/mcp"}}],
    )
    strict_mcp_config: bool | None = Field(
        default=None,
        description=(
            "When true, ONLY the servers in `mcp_servers` are used and every "
            "other source the CLI would consult is ignored -- project "
            "`.mcp.json`, user and global settings, plugin-provided servers.\n\n"
            "**This service defaults it to TRUE**, which is not the SDK's "
            "default of false. The reason is the workspace: it is mounted from "
            "the host and is WRITABLE BY THE AGENT, so a `.mcp.json` sitting in "
            "it -- committed by someone else, or written by a previous turn -- "
            "would otherwise add servers this caller never asked for and cannot "
            "see in its own request. The contract is that what you sent is what "
            "runs. Set false to opt into the CLI's own discovery.\n\n"
            "Note this service already passes `setting_sources` explicitly "
            "(default `[]`). Whether that alone suppresses `.mcp.json` is "
            "**not measured** -- this flag does not depend on the answer."
        ),
    )


class QueryRequest(BaseModel):
    prompt: str = Field(min_length=1, examples=["List the files in this directory"])
    options: RunOptions = Field(default_factory=RunOptions)


class AgentEvent(BaseModel):
    """One SDK message, normalized.

    No session_id: it is not uniformly available across message types, so it is
    reported once per run on RunResponse instead.
    """

    seq: int
    type: EventType = Field(
        description=(
            "What kind of message this is, from a closed set the specification "
            "owns. **This is the authoritative discriminator and the SSE frame "
            "name is NOT** -- the `event:` line of a streamed frame is an "
            "implementation detail that differs between builds, so a client "
            "reading it instead of this field works on some and silently "
            "renders nothing on others. Neither streaming route can be consumed "
            "with `EventSource` anyway, since both are POST."
        )
    )
    subtype: str | None = None
    content: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "The message's content, NORMALISED, as a list of blocks. Each block "
            "is an object with a `type` discriminator; a block of type `text` "
            "carries its string in `text`. This is what a client renders a "
            "conversation from -- `raw` is the originating SDK's own payload "
            "and its shape differs per build. **`null` means this event carries "
            "no renderable content** (an `init` frame, a rate-limit notice), "
            "never that the content was dropped. Where an implementation has "
            "text to report it fills this, so that a caller reading only this "
            "field sees the whole conversation on every build."
        ),
    )
    raw: dict[str, Any] | None = None


class TokenUsage(BaseModel):
    """Named token counts for one turn, filled by every implementation.

    **0.19.0, and it exists because `usage` cannot serve this purpose.** `usage`
    is a verbatim SDK pass-through, so its keys are whichever SDK produced it --
    `cache_creation_input_tokens` on one build, `cachedInputTokens` on another.
    A consumer wanting "how many tokens did this turn cost" had to write one
    scanner per implementation and update it whenever a third appeared. This
    object is the specification's own spelling, and `usage` stays untouched
    beside it so the raw numbers remain reachable when the two disagree.

    **Every field is a nullable integer, and `null` means NOT REPORTED -- never
    zero.** The distinction is not pedantry: a build that cannot count cache
    writes reporting `0` would show a 1.25x charge as free, which is exactly the
    misleading total this object was asked for to prevent. Same rule as
    `total_cost_usd` since 0.16.0 and `Health.database_usable`.

    **The object itself is always present.** A `null` object could not be told
    apart from "this implementation does not report token counts", and that
    ambiguity is what AS-17a rejects.

    Scope is THIS run, matching `usage` and not `model_usage`.
    """

    input_tokens: int | None = Field(
        default=None, description="Prompt tokens for this turn. `null` if not reported."
    )
    output_tokens: int | None = Field(
        default=None, description="Generated tokens for this turn. `null` if not reported."
    )
    cache_read_tokens: int | None = Field(
        default=None,
        description=(
            "Prompt tokens served from cache -- the cheap half of the cache pair. "
            "`null` if not reported."
        ),
    )
    cache_write_tokens: int | None = Field(
        default=None,
        description=(
            "Prompt tokens written to cache -- the **expensive** half, typically "
            "billed at a premium.\n\n"
            "**`null` on an implementation whose SDK has no such counter**, which "
            "is not the same as zero: on such a build a cache write is a charge "
            "you cannot see from this API. It is reported as `null` rather than "
            "omitted precisely so that gap is visible."
        ),
    )
    reasoning_output_tokens: int | None = Field(
        default=None,
        description=(
            "Generated reasoning tokens, where the SDK reports them separately "
            "from `output_tokens`. `null` on an implementation that does not "
            "distinguish them -- which does not mean none were generated."
        ),
    )


class RunResponse(BaseModel):
    session_id: str | None = Field(
        default=None,
        description=(
            "The SDK's OWN conversation id for this run -- NOT a handle you "
            "can put in a `/v1/sessions/{session_id}` path. That path takes "
            "`SessionRecord.session_id`, this service's registry handle, "
            "which is a different string: feeding this one back is a 404 "
            "(measured). The two identifiers have shared a name since Plan 1 "
            "and the name is kept as-is because it already ships; "
            "`sdk_session_id` below carries the same value under a name that "
            "says which id it is, and is what new code should read."
        ),
    )
    sdk_session_id: str | None = Field(
        default=None,
        description=(
            "The same value as `session_id` above, under an unambiguous "
            "name. Matches `TurnRecord.sdk_session_id` on `SessionRecord."
            "last_turn`, so one name means one identifier across every "
            "surface that reports the SDK's id."
        ),
    )
    outcome_recorded: bool = Field(
        default=True,
        description=(
            "False when the run ended without the agent's own terminating result "
            "(the agent process crashed, exited early, or was killed). The "
            "events list may still "
            "be populated, but result, cost and usage are unavailable — this is "
            "not the same as a successful run that produced no output."
        ),
    )
    result: str | None = None
    is_error: bool = Field(
        default=False,
        description="The agent reported failure. A successful HTTP call can carry is_error=true.",
    )
    interrupted: bool = Field(
        default=False,
        description=(
            "True when this turn was stopped by an explicit interrupt request. "
            "The SDK reports an interrupted turn with is_error=true and "
            "subtype='error_during_execution' -- identical in shape to a real "
            "failure -- so this flag is the only reliable way to tell a "
            "deliberate stop from a crash."
        ),
    )
    stop_kind: StopKind | None = Field(
        default=None,
        description=(
            "WHY THE TURN ENDED, as a closed set every implementation maps "
            "onto. Read this rather than the three strings below, which are "
            "each an SDK's own vocabulary passed through verbatim and differ "
            "between builds for the same ending. Null only when the build "
            "cannot tell -- never as a substitute for 'other', which means the "
            "build knows the ending and has no mapping for it. Derived from "
            "the same facts as `interrupted`, `limit_hit` and `is_error` and "
            "guaranteed not to contradict them; where two could apply the "
            "order is interrupted, timed out, guardrail, error, then whatever "
            "the SDK reported."
        ),
    )
    subtype: str | None = Field(
        default=None,
        description=(
            "The SDK's own terminal subtype, verbatim. Build-specific: do not "
            "branch on it, read `stop_kind`."
        ),
    )
    stop_reason: str | None = Field(
        default=None,
        description=(
            "The SDK's own stop reason, verbatim. Build-specific: do not "
            "branch on it, read `stop_kind`."
        ),
    )
    terminal_reason: str | None = Field(
        default=None,
        description=(
            "The SDK's own free-text description of the ending, verbatim -- an "
            "error message where there was one. For a human reading a log, not "
            "for a client to match on."
        ),
    )
    limit_hit: Literal["turns", "budget"] | None = Field(
        default=None,
        description=(
            "Which guardrail ended the run, if any. Never 'timeout': a timed-out "
            "run raises RunTimeout, which surfaces as a 504 Problem document "
            "(/v1/query) or an in-band event: error (/v1/query/stream), not a "
            "RunResponse -- so this field would never actually carry that value. "
            "Kept beside `stop_kind`, which reports the same two endings as "
            "'max_turns' and 'max_budget'."
        ),
    )
    num_turns: int | None = None
    total_cost_usd: float | None = Field(
        default=None,
        description=(
            "Cost in USD from the SDK. **Its scope depends on the "
            "endpoint.** On `POST /v1/query` it is that run's cost. On a "
            "session turn it is the CUMULATIVE cost of every turn so far, "
            "growing monotonically -- not the cost of the turn just taken. "
            "Read `turn_cost_usd` for that.\n\n"
            "`null` when the SDK reported a successful turn it attributed no "
            "cost to. Missing rather than zero, because such a turn did run."
        ),
    )
    turn_cost_usd: float | None = Field(
        default=None,
        description=(
            "What THIS turn cost, in USD. On a session turn it is the "
            "difference against the previous turn; on `POST /v1/query` it "
            "equals `total_cost_usd`.\n\n"
            "**`null` means nobody can say**, and it is not 0.0: the run "
            "produced no result, the result carried no price, or the turn was "
            "interrupted, **or the agent reports no monetary figure at all** -- on such a build every cost field is null forever, which is not the same as free. `0.0` is reserved for a turn that "
            "genuinely cost nothing."
        ),
    )
    duration_ms: int | None = None
    usage: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Token counts for THIS run, **passed through from the underlying "
            "agent verbatim and unnormalised**. The keys, and whether a key "
            "means what its name suggests, are that agent's -- one build's "
            "counter for tool calls is measured to report zero on a turn that "
            "made one.\n\n"
            "**Zeros mean the agent reported nothing, not that nothing "
            "happened**: a turn that failed or was interrupted still consumed "
            "tokens on every build measured.\n\n"
            "Read `token_usage` instead for figures with a meaning the "
            "specification defines, and read this only when you know which "
            "implementation answered."
        ),
    )
    token_usage: TokenUsage = Field(
        default_factory=TokenUsage,
        description=(
            "The specification's own named token counts for this run, filled by "
            "every implementation. **Always present**; each field is nullable, "
            "and `null` means not reported rather than zero. `usage` above stays "
            "a verbatim SDK pass-through -- this is the shape a consumer reads "
            "without knowing which implementation answered."
        ),
    )
    model_usage: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Per-model usage, when the agent reports any. **A map, or null "
            "on a build whose agent reports no per-model breakdown at all.**\n\n"
            "**ITS SCOPE IS PER BUILD AND YOU MUST NOT ASSUME EITHER ANSWER.** "
            "On one implementation this is CUMULATIVE for the connection, so "
            "summing across turns multiplies the real figure; on another it is "
            "PER TURN, so summing is the correct thing to do. The two are "
            "indistinguishable from the payload. **Read the implementation's "
            "own guide before aggregating it**, and prefer `token_usage`, "
            "whose scope the specification fixes.\n\n"
            "A build may also report more models than the one requested -- an "
            "internal router or summariser -- so a key here is not evidence "
            "that the caller selected that model."
        ),
    )
    permission_denials: list[Any] | None = None
    events: list[AgentEvent] = Field(default_factory=list)


# THE PUBLISHED DOCSTRINGS BELOW ARE DELIBERATELY SHORT, and the reasoning that
# used to be in them is here instead. Pydantic publishes a model docstring and a
# Field description straight into the OpenAPI document, so anything written
# there is read by a consumer trying to use the API -- version archaeology,
# internal rationale and this repository's own decisions are noise at that
# altitude, and they were most of the bytes. `#` comments are not published;
# this is where they belong.
#
# `Sdk` (0.7.0) exists because a bare `sdk_version` string answers "what
# version" and not "of what". This service is to front Codex, Gemini and other
# agent SDKs, and those are separate implementations rather than modes of this
# one: the SDK's language decides the implementation's language.
#
# Two fields and no more, deliberately. An implementation name, a language, a
# spec version and per-extension flags were all considered and left out -- no
# second implementation exists yet, and anything published here is frozen by
# AS-24 whether or not it survives contact with the first one that does.
#
# NOT CALLED A "PROVIDER": that word is taken by `provider_selectors`, meaning
# the cloud that HOSTS the model. Both are about reaching a model; this is about
# which SDK does the reaching. Agent Studio also called an endpoint an "LLM
# Provider" until they renamed it "LLM Endpoint" on 2026-08-07, which is why
# older published documents cite a term that no longer exists on their side.
class Sdk(BaseModel):
    """The agent SDK this build wraps, and its version."""

    name: str = Field(
        description=(
            "The distribution name of the agent SDK this build wraps, e.g. "
            "`claude-agent-sdk`. **This is the axis on which implementations "
            "differ** -- a Codex or Gemini build is a different service image "
            "reporting a different name here, not this image in another mode."
        ),
        examples=["claude-agent-sdk"],
    )
    version: str = Field(
        description=(
            "The installed version of that SDK. Same value as the deprecated "
            "top-level `sdk_version`, read from the same place."
        ),
        examples=["0.2.128"],
    )


# `Spec` and `Impl` are the two halves of one join: what this build PROMISES and
# what it IS. Added together in 0.12.0 as `Contract`/`Implementation` and renamed
# in 0.14.0 -- a breaking change, because both are required properties and the
# old names were removed rather than deprecated. They match the platform's two
# product directories, `spec/` and `impl/`.
#
# `Spec` carries one field on purpose. The core/extension split of the document
# is designed and not drawn; the boundary is a prediction until a second
# implementation tests it, and AS-24 freezes a published guess. When it is
# drawn, `core_version` and a list of extensions are additive beside it.
#
# Not to be confused with `agent_service.spec`, the pre-boot module: that
# answers "which environment variables will this image read, and where will it
# listen", readable before the service exists. This answers "which interface
# document does it promise", and needs the service running.
class Spec(BaseModel):
    """The interface document this build implements."""

    document_version: str = Field(
        description=(
            "The version of the interface document this build implements. Also "
            "what `GET /openapi.json` reports as `info.version`, and what names "
            "the published `openapi-<version>.json`.\n\n"
            "**Not this build's version** -- read `impl.version` for that. Two "
            "implementations in different languages serve the same document and "
            "report the same value here."
        ),
        examples=["0.16.0"],
    )


class Impl(BaseModel):
    """Which build this is, and at what version."""

    name: str = Field(
        description=(
            "The implementation's name, e.g. `claude-python`. Distinct from "
            "`sdk.name`: two implementations could wrap the same SDK from "
            "different languages."
        ),
        examples=["claude-python"],
    )
    version: str = Field(
        description=(
            "This build's version, and the tag its image is published under. "
            "See `spec.document_version` for the interface it implements."
        ),
        examples=["0.16.0"],
    )


class Sandbox(BaseModel):
    """What the agent's own tools are confined by, beyond the container.

    **AS-32, and it is the difference a tool-using Agent notices first.** The
    two implementations are not comparable here and nothing published said so:
    one runs its shell inside a sandbox that blocks egress, the other runs it
    unconfined and relies on the container being the boundary. **The same Agent
    -- one whose capability is *install this package* or *call this API from a
    shell command* -- works on one build and fails on the other.**

    **This describes the AGENT's tools, not the service.** The service reaches
    the model API regardless; what is confined is what the agent can do with a
    shell.
    """

    network_access: bool = Field(
        description=(
            "Whether the agent's own shell commands can reach the network.\n\n"
            "**`false` means a tool cannot open a socket at all** -- no package "
            "install, no `curl`, no API call from a command. It is not a "
            "statement about this service, which reaches the model API either "
            "way, and not about the container, which may well have egress.\n\n"
            "**`true` is not a weaker service, it is a different boundary.** A "
            "build reporting `true` may be relying on the container and its "
            "network policy for confinement, which is a deployment's decision "
            "rather than a defect -- read it as *the agent is not stopped here* "
            "rather than as *this build is unsafe*."
        ),
        examples=[False],
    )
    confines_writes_to_workspace: bool = Field(
        description=(
            "Whether the agent's writes are confined to the workspace by "
            "something inside the container.\n\n"
            "**`false` does not mean the agent may write anywhere a caller "
            "cares about** -- the container's mount layout is still the "
            "boundary, and on a build with no in-container sandbox that is the "
            "only one. It means no second mechanism is enforcing it, so a "
            "process that escapes the intended paths is not stopped again on "
            "its way out."
        ),
        examples=[True],
    )


class McpToolCall(BaseModel):
    """What holds an MCP tool call open on this build, and what ends it.

    **AS-32, and the failure it prevents is the quiet kind.** A client whose MCP
    tool deliberately runs for minutes -- waiting on a human, on another agent,
    on a queue -- gets three different outcomes from one mistake across three
    builds: a named timeout, a bare transport error, and a success. Nothing in
    the other `mcp` fields says which, and an experiment can only report what a
    client happened not to exceed.

    **THREE timers rather than two, because each build is bounded by a different
    one.** They are not interchangeable and a server satisfies them by different
    means: `request_timeout_s` is cleared by *responding*, `idle_timeout_s` by
    *continuing to say something*, and `total_timeout_s` by nothing at all -- it
    expires while the call is perfectly healthy. Publishing only the first two
    would describe one build and misdescribe another.

    **`null` means this build imposes no bound of that kind**, on the convention
    `server_name_pattern` already sets rather than the null-means-unmeasured rule
    the nullable measurements follow. It is a statement about THIS BUILD's
    client: null does not promise a network path, a proxy or a kernel will wait
    forever, only that nothing in the agent gives up.

    **Every value is what a caller gets, with no lever to move it.** `McpServer`
    carries no `timeout` field on any variant, so there is no per-request
    override; where an agent reads an environment variable for one of these, it
    is the operator's surface and not the caller's, and this service does not set
    it.

    **A value is never more generous than the strictest transport in
    `transports`.** One build's idle timeout is six times longer over `stdio`
    than over `sse`/`http`; the shorter number is the one published, so a client
    planning against it is never surprised by a transport it did not test.
    """

    request_timeout_s: int | None = Field(
        description=(
            "How long the client waits for the response to **begin**, or `null` "
            "for no bound.\n\n"
            "**Satisfied by responding, not by finishing.** On a streaming "
            "transport the clock stops the moment the server sends its SSE "
            "headers -- the request has been served and what follows is governed "
            "by `idle_timeout_s` and `total_timeout_s`. A server that buffers "
            "its whole answer and replies with one JSON body is the shape this "
            "bound refuses.\n\n"
            "**Where a build publishes a number it is a floor rather than a "
            "setting**: the agent takes the larger of it and any override, so it "
            "can be raised and never lowered."
        ),
        examples=[60, None],
    )
    idle_timeout_s: int | None = Field(
        description=(
            "How long the call may go **between frames** once the response has "
            "begun, or `null` for no bound.\n\n"
            "**An SSE comment is not a frame that counts** on the build that "
            "publishes a number here -- its own error names what does: *no "
            "response or progress*. A keepalive-only stream therefore dies at "
            "exactly this figure while looking healthy on the wire, which is the "
            "most expensive way to discover the difference.\n\n"
            "Read it together with `progress_resets_idle`, which says whether "
            "`notifications/progress` is one of the frames that counts."
        ),
        examples=[300, None],
    )
    total_timeout_s: int | None = Field(
        description=(
            "**Wall clock for the whole call, regardless of activity**, or "
            "`null` for no bound.\n\n"
            "**This is the deadline, and it is the only one of the three a "
            "well-behaved server cannot satisfy by behaving well.** Responding "
            "at once and emitting progress throughout clears the other two and "
            "does nothing to this one. A client that needs a call held longer "
            "than this figure cannot get it from any MCP-level behaviour on this "
            "build.\n\n"
            "**Bounded again by the run.** A tool call lives inside a turn, so "
            "the effective ceiling is the smaller of this and the request's own "
            "`timeout_s` -- itself capped by `limits.max_allowed_timeout_s`. On "
            "one build the two figures coincide, which is not slack."
        ),
        examples=[100000, 600, None],
    )
    progress_resets_idle: bool | None = Field(
        description=(
            "Whether `notifications/progress` restarts `idle_timeout_s`.\n\n"
            "**`null` is a third answer and not a missing one**: it means this "
            "build has no bound of any kind, so there is nothing for progress to "
            "reset and neither `true` nor `false` states it honestly. Where any "
            "of the three timers exists, this is a boolean.\n\n"
            "**`false` is the value that costs a client something, and it is not "
            "the same as *progress is ignored*.** A build may ask for progress -- "
            "sending a `progressToken` on every call -- and use it only to drive "
            "its own display while a flat `total_timeout_s` runs underneath. "
            "Emitting progress there buys nothing, and a client that measured a "
            "short call and concluded otherwise has published a coincidence as a "
            "promise."
        ),
        examples=[True, False, None],
    )


class Mcp(BaseModel):
    """What a build can express of `RunOptions.mcp_servers`.

    **AS-32, and `allow_mcp_servers` is not enough on its own.** That boolean
    says whether MCP servers are accepted at all; this says which of them are.
    A client whose Agent's capability is an `sse` server needs to know before it
    sends one, and the difference is a build fact rather than a deployment
    setting -- one SDK has three transports and another has two.
    """

    transports: list[Literal["stdio", "sse", "http"]] = Field(
        description=(
            "The `McpServer.type` values this build can reach. **A server of any "
            "other type is a 400**, named and refused before a session exists, "
            "rather than configured and silently unreachable.\n\n"
            "`http` is streamable HTTP. A build listing `http` and not `sse` has "
            "no SSE transport at all -- the two are different protocols and one "
            "does not stand in for the other."
        ),
        examples=[["stdio", "sse", "http"], ["stdio", "http"]],
    )
    http_headers: Literal["any", "bearer_only", "none"] = Field(
        description=(
            "What an `http` or `sse` server's `headers` may contain. `any` "
            "forwards every header; **`bearer_only` accepts exactly one, "
            "`Authorization: Bearer ...`, and refuses anything else with a "
            "400**; `none` cannot send headers at all.\n\n"
            "**`bearer_only` is a real limit and not a security posture**: it is "
            "what the underlying agent runtime can carry. A caller whose MCP "
            "server authenticates with an API-key header cannot use it on such a "
            "build, and finding that out from this field is cheaper than finding "
            "it out from a tool that never works."
        ),
        examples=["any", "bearer_only"],
    )
    server_name_pattern: str | None = Field(
        default=None,
        description=(
            "A regular expression every key of `RunOptions.mcp_servers` must "
            "match on this build. **A name that does not match is a 400 before "
            "a session exists**, not a server that quietly never answers.\n\n"
            "**`null` means this build enforces no pattern of its own**, on the "
            "convention `limits` already sets -- what is absent there is a limit "
            "the build does not impose. It is deliberately NOT the "
            "null-means-unmeasured rule the nullable measurements follow, "
            "because this is a statement about THIS SERVICE's check: null does "
            "not promise the underlying agent accepts every name, only that "
            "nothing here refuses one.\n\n"
            "**Requested by Agent Harness (2026-08-12), and the failure is a "
            "stored-capability one.** A consumer that stores a server "
            "definition once and sends it to whichever build an Agent runs on "
            "has nothing to validate against at storage time, so a name that "
            "works on two builds and is refused by the third fails at session "
            "create -- long after the author who could fix it has gone. A "
            "pattern moves that refusal to publish time.\n\n"
            "One build publishes `^[^_]+$` because its agent parses an MCP tool "
            "name as `mcp_<server>_<tool>` by splitting on the first underscore, "
            "so a server whose name contains one can never be addressed."
        ),
        examples=["^[^_]+$", None],
    )
    tool_call: McpToolCall = Field(
        description=(
            "What holds an MCP tool call open on this build, and what ends it. "
            "**AS-32**: a deliberately long tool call succeeds on one build, "
            "fails with a named timeout on another and fails with a bare "
            "transport error on a third, and the difference is a build fact a "
            "client must act on before it offers a server rather than after.\n\n"
            "**Requested by Agent Harness (2026-08-18)**, which hosts an MCP "
            "server whose first tool holds the call open until another agent "
            "replies -- so a long call is the feature rather than an edge case, "
            "and the deadline it must choose has to be a number."
        ),
    )


class LlmCorrelation(BaseModel):
    """How an agent's own model traffic can be joined to a session, if at all.

    **A property of the AGENT BINARY rather than of this service**, on the
    `endpoint_source` precedent: only the side that can put a proxy in front of
    the agent is positioned to measure it, and a client otherwise hard-codes one
    vendor's header name and gets nothing from the others.

    **What it is for.** A deployment that puts a gateway between the container
    and the model endpoint sees the AGENT's requests, not this service's, so it
    can attribute spend to a session only by reading a correlation id off the
    agent's own request.

    **Two fields because there are three answers, and one nullable string can
    only carry two.** This was proposed as a bare `llm_correlation_header:
    string | null` and the measurement is what refuted it: one build sends a
    header, one provably sends none, and one has not been measured through the
    interface it actually drives. *Sends none* and *not looked* are different
    instructions to a consumer -- the first says stop, the second says this may
    yet be worth measuring -- so the shape has to distinguish them.
    """

    header: str | None = Field(
        description=(
            "The HTTP header the agent sends on its own model-API requests "
            "whose value equals `sdk_session_id`, or `null` for none.\n\n"
            "**Read `measured` first.** `null` with `measured: true` is a "
            "finding: this agent sends no such header and a gateway must "
            "attribute its spend some other way. `null` with `measured: false` "
            "is an absence of knowledge and promises nothing in either "
            "direction.\n\n"
            "**Where it is a string, the equality is measured on the wire** and "
            "not inferred from a name that looks right. A header carrying some "
            "id is useless to a gateway unless it is the same string this "
            "service reports."
        ),
        examples=["x-claude-code-session-id", None],
    )
    measured: bool = Field(
        description=(
            "Whether this build has actually watched the agent's traffic.\n\n"
            "**`true` means a request was captured** -- the endpoint variable "
            "was pointed at a local sink, a turn was taken, and the headers "
            "were read. It is what makes `header: null` a finding rather than a "
            "gap.\n\n"
            "**`false` means nobody has looked**, and this service will not "
            "fill the field in from a vendor's documentation. A build can be "
            "here because the measurement is not yet done or because the "
            "interface it drives could not be exercised where the probe runs."
        ),
        examples=[True],
    )


class UnsupportedOption(BaseModel):
    """One `RunOptions` field a build refuses, and optionally only in some shapes.

    **This was a bare string until Agent Studio pointed out that it could not be
    acted on** (2026-08-09). Six of seven entries were field names and the
    seventh was `"system_prompt (preset form)"`, so the obvious client --
    `if (unsupported_options.contains(fieldName))` -- never matched
    `system_prompt`. Publishing a difference in a form nobody can branch on is
    precisely what AS-32 exists to prevent, so the entry became a structure
    rather than a sentence.

    **`values` is the same defect found a second time** (Agent Harness,
    2026-08-12). A build refuses `strict_mcp_config: false` and honours `true`;
    the field takes one JSON type, so `types` cannot express it and listing the
    field alone would promise a 400 for the value that works. It was therefore
    listed nowhere and was invisible to the one mechanism built for exactly this
    -- which the consumer found by asking rather than by being told.

    The three keys are read together, and each null is *no constraint of that
    kind*::

        refused = field matches
                  && (types  is null || types.contains(jsonTypeOf(v)))
                  && (values is null || values.contains(v))
    """

    field: str = Field(
        description=(
            "The `RunOptions` property name, exactly as it appears in a request. "
            "**An identifier and never prose**, so a client can compare it "
            "directly against the key it was about to send."
        ),
        examples=["max_turns"],
    )
    types: list[Literal["string", "number", "boolean", "object", "array"]] | None = Field(
        default=None,
        description=(
            "**Absent means the field is refused whatever it contains.** Present "
            "means only those JSON types are refused and the others are "
            "honoured -- `system_prompt` with `[\"object\"]` on a build that "
            "takes the string form and has no equivalent for the preset "
            "object.\n\n"
            "Types are named as JSON names the request itself uses, so the "
            "check is `types is null || types.contains(typeof value)` and needs "
            "no knowledge of any SDK.\n\n"
            "**An absent key and an explicit `null` mean the same thing**, and a "
            "reader must accept both. This service always emits the key -- "
            "presence with `null` is the convention the whole document follows, "
            "for the reason `Health.database_usable` gives: an absent field "
            "cannot be told apart from one a build is too old to send."
        ),
        examples=[["object"], None],
    )
    values: list[Any] | None = Field(
        default=None,
        description=(
            "**Absent means the field is refused whatever it contains** -- the "
            "same rule `types` follows, so every entry written before this key "
            "existed keeps the meaning it had. Present means only these VALUES "
            "are refused and every other value of the field is honoured.\n\n"
            "**The case it exists for**: a build that implements "
            "`strict_mcp_config` and can only ever run strict refuses `false` "
            "and honours `true`. The field takes one JSON type, so `types` "
            "cannot say that, and naming the field alone would promise a 400 "
            "for the value that works.\n\n"
            "**Read this beside the matching capability, never instead of it.** "
            "`Capabilities.strict_mcp_config` is the server-side DEFAULT and "
            "says nothing about which values are accepted; this says which are "
            "refused. Two different questions.\n\n"
            "Values are compared as JSON, so a reader needs no knowledge of any "
            "SDK. **An absent key and an explicit `null` mean the same thing**, "
            "on the convention the whole document follows."
        ),
        examples=[[False], None],
    )


class Capabilities(BaseModel):
    spec: Spec = Field(
        description=(
            "Which interface document this build implements. Two "
            "implementations satisfying the same document report the same "
            "value here."
        )
    )
    impl: Impl = Field(
        description="Which build this is. Read this, not `info.version`."
    )
    sdk: Sdk = Field(
        description=(
            "Which agent SDK this build wraps, and its version. Supersedes "
            "`sdk_version`, which cannot say WHICH SDK."
        )
    )
    sdk_version: str = Field(
        deprecated=True,
        description=(
            "**Deprecated: read `sdk.version` instead.** Still emitted and "
            "still correct -- the same value from the same source."
        )
    )
    permission_modes: list[SessionMode] = Field(
        description=(
            "The permission modes THIS BUILD honours, each with an id, a short "
            "name and a description of what it actually permits. **Read this "
            "rather than assuming a vocabulary**: it was a list of strings "
            "taken from one SDK's enum, which every implementation had to "
            "accept whether or not it could honour them. A build declares only "
            "what it has, and refuses an undeclared id with 400. `default` and "
            "`plan` are well-known ids a build uses where it has an "
            "equivalent, so one payload can work against more than one "
            "implementation; a build with no equivalent omits them rather than "
            "mapping them onto something that does not mean the same thing."
        )
    )
    effort_levels: list[str]
    setting_sources: list[str]
    default_model: str
    default_allowed_tools: list[str]
    always_disallowed_tools: list[str]
    limits: dict[str, float] = Field(
        description=(
            "Figures this build ENFORCES, by name. A number here is a promise "
            "about behaviour, not a measurement: `turn_timeout_s` is enforced "
            "by ending the turn, `max_sessions` by refusing a create.\n\n"
            "**Free-form on purpose** -- a build publishes the ones it has, and "
            "a name absent here is a limit this build does not impose. Measured "
            "characteristics that nothing enforces do NOT belong here; see "
            "`turn_token_overhead`."
        )
    )
    turn_token_overhead: float | None = Field(
        default=None,
        description=(
            "Approximate input tokens a turn costs BEFORE the caller's prompt "
            "is counted -- the agent's own system prompt and tool "
            "declarations.\n\n"
            "**Published because it changes how a client should batch.** Where "
            "this is large, TURN COUNT predicts spend rather than prompt "
            "length, and a client sending many small turns pays far more than "
            "one that batches. A measured example: three prompts of three to "
            "nine words costing 7,072, 7,076 and 7,082 input tokens.\n\n"
            "**`null` means this build has not measured it**, never that the "
            "overhead is zero. Approximate by nature: it moves with the agent's "
            "version and its tool set."
        ),
    )
    usage_counts_tool_calls: bool | None = Field(
        default=None,
        description=(
            "Whether a tool-call count in `usage` can be trusted to mean what "
            "it says.\n\n"
            "**`false` is a real answer and one build measures it**: a turn "
            "carrying both a `tool_use` and a `tool_result` reported zero, "
            "because the counter counts only calls that reached a registered "
            "tool. A client deciding whether a turn used tools must count "
            "`tool_use` EVENTS on such a build.\n\n"
            "`null` means unmeasured rather than reliable, because `usage` is a "
            "verbatim pass-through and no build owes it a meaning it never "
            "promised."
        ),
    )
    model_usage_scope: ModelUsageScope = Field(
        description=(
            "How to aggregate `model_usage` across the turns of ONE session. "
            "**The shape is identical either way, so this cannot be inferred "
            "from a response** -- same field name, same type, same nesting on "
            "every build.\n\n"
            '`"per_turn"`: each turn reports its own figures. **Sum them** to '
            "get a session total.\n\n"
            '`"cumulative"`: each turn reports the running total for the agent '
            "connection. **Difference consecutive turns** to get a turn's own "
            "figures; summing double-counts every earlier turn.\n\n"
            '`"not_reported"`: this build emits `model_usage: null` on every '
            "turn and every session. **Skip it** -- neither of the other "
            "instructions is right, and a scanner looking for a key that is "
            "never there records nothing rather than something wrong.\n\n"
            "**This is about `model_usage` and NOT about the cost fields.** On a "
            "`cumulative` build `turn_cost_usd` is already differenced by this "
            "service while `model_usage` is a verbatim pass-through that is "
            "not, so one response can carry per-turn money beside cumulative "
            "tokens. That asymmetry is the reason the field exists.\n\n"
            "**Required with no default**, on the same reasoning as "
            "`sdk_session_id_scope`: a build that cannot say what its numbers "
            "are scoped to should fail to construct this payload rather than "
            "answer with a reassuring value nobody measured."
        ),
        examples=["per_turn"],
    )
    reports_cost_usd: bool = Field(
        description=(
            "Whether this build's agent reports a monetary figure at all.\n\n"
            "**`false` distinguishes *never priced* from *not priced yet*, "
            "which `null` alone cannot.** The cost fields are nullable for both "
            "reasons -- a build whose agent reports tokens and latency and no "
            "currency answers `null` permanently and by nature, while a build "
            "that does price a turn answers `null` only until it has. A client "
            "hides a column for the first and shows it empty for the second, "
            "and could not tell them apart from a response.\n\n"
            "`false` says `total_cost_usd` and `turn_cost_usd` are `null` on "
            "every session and every turn of this build, permanently and not by "
            "configuration. `0.0` would read as *free*, which is why those "
            "fields are null rather than zero."
        ),
        examples=[True],
    )
    workspace_dir: str
    reference_dirs: list[str]
    credential_sources: list[str] = Field(
        description=(
            "The environment variables this build accepts as a credential for ITS "
            "OWN agent -- each build wraps a different vendor, so the names here are that vendor's -- in the order it checks them. Check against this "
            "before starting a container.\n\n"
            "**This is what the BOOT GATE accepts**, which is a presence check "
            "on these names -- not a claim about every credential the bundled "
            "CLI could authenticate with. A credential supplied by any other "
            "route does not satisfy it and the service refuses to start."
        )
    )
    provider_selectors: list[str] = Field(
        description=(
            "Environment variables that select a cloud provider instead of "
            "supplying a credential. **Setting one satisfies the boot gate and "
            "authenticates nothing by itself** -- the credential then comes "
            "from that provider's own chain (AWS, GCP, Azure), which this "
            "service does not inspect. Published separately from "
            "`credential_sources` so that injecting one is not mistaken for a "
            "way to deliver a key.\n\n"
            "**\"Provider\" here means the cloud that HOSTS the model** -- "
            "Bedrock, Vertex, Foundry. It does NOT mean which agent SDK this "
            "build wraps; that is `sdk.name`.\n\n"
            "**Selectors only, and no URL.** This API has no endpoint "
            "override. A deployment that needs one sets it in the container's "
            "environment, where this service can neither see nor report it."
        )
    )
    max_sessions: int = Field(
        description=(
            "The concurrent-session cap. `POST /v1/sessions` answers 429 once "
            "this many are open, and this is the same value that request's "
            "message is formatted from -- so it is the denominator for "
            "\"N of M sessions\", whose numerator is `GET /v1/sessions`. "
            "Previously reachable only by scraping the prose of a 429."
        )
    )
    require_credentials: bool = Field(
        description=(
            "Whether this build refuses to BOOT when none of "
            "`credential_sources`/`provider_selectors` is set (exit 3). True is "
            "the default. False means the service will start without a "
            "credential -- for docs-only use -- and fail on the first turn "
            "instead."
        )
    )
    auth_required: bool = Field(
        description=(
            "Whether `/v1` requires a bearer credential.\n\n"
            "**It authenticates the caller to this instance and is not an "
            "identity.** This service does not know which user is behind a "
            "request, and nothing is scoped by the token.\n\n"
            "**Use a per-instance token.** A token this service holds is "
            "readable by the agent it runs, so one shared across a fleet is "
            "readable by anyone who can take a single turn."
        )
    )
    allow_mcp_servers: bool = Field(
        description=(
            "Whether `RunOptions.mcp_servers` is accepted. True is the default. "
            "**False makes a request carrying MCP servers a 400** rather than "
            "silently dropping them, so check this before relying on the "
            "field -- the same pre-flight `credential_sources` exists for.\n\n"
            "An operator turns this off for ATTRIBUTION, not for capability: a "
            "`stdio` server is a subprocess spawn, and on a build whose agent "
            "has a shell tool that agent already spawns whatever it likes. The "
            "difference is that a tool call is the agent's decision and lands "
            "in the transcript, while a stdio server starts with the session, "
            "before any prompt, and appears in no turn's events.\n\n"
            "**On a build with no shell the argument is stronger, not weaker**: "
            "there a stdio server is the only way a caller can cause a process "
            "to start at all."
        )
    )
    sdk_session_id_scope: SdkSessionIdScope = Field(
        description=(
            "What `sdk_session_id` is an id OF on this build. **The value looks "
            "identical either way, so this cannot be inferred from a "
            "response.**\n\n"
            '`"conversation"`: it identifies the conversation and is stable '
            "across ordinary turns, so a client may key on it. It may still "
            "change under an explicit fork or resume on some builds -- stable "
            "is not immutable.\n\n"
            '`"turn"`: **it identifies ONE TURN.** A build whose agent mints a '
            "new id each time it resumes reports this. Route on it if you like; "
            "**never key on it**, because the next turn of the same "
            "conversation answers with a different value.\n\n"
            "**`session_id`, this service's own, is the stable handle on every "
            "build** and is what every path takes. This field exists so a "
            "client that also wants the agent's id knows what it is holding."
        ),
        examples=["conversation"],
    )
    llm_correlation: LlmCorrelation = Field(
        description=(
            "How a gateway can join THIS BUILD'S AGENT's model traffic to a "
            "session -- the header it sends, and whether anyone has looked.\n\n"
            "**Requested by Agent Harness (2026-08-12) as the highest-value of "
            "four**, because it is the one that blocks a feature rather than "
            "risking a wrong number: a gateway that is the model endpoint for "
            "every container has one vendor's header name compiled in and no "
            "way to discover the others."
        )
    )
    allow_supplied_sdk_session_id: bool = Field(
        description=(
            "Whether `POST /v1/sessions` accepts a caller-supplied "
            "`sdk_session_id`. **Check this before sending one** -- the same "
            "pre-flight `allow_mcp_servers` and `credential_sources` exist "
            "for.\n\n"
            "| Value | `POST /v1/sessions` with `sdk_session_id` |\n"
            "| --- | --- |\n"
            "| `true` | adopts it and returns it on the 201, before any model "
            "call |\n"
            "| `false` | **400** with a problem document saying why |\n\n"
            "**`false` is never a silent drop.** A build that took the field "
            "and returned a different id would break the one guarantee "
            "supplying it provides -- that the caller's id names the "
            "conversation -- and would break it invisibly.\n\n"
            "It is `false` when the underlying SDK mints its own conversation "
            "id with no way to override it. Such a build still reports an "
            "`sdk_session_id`; it simply chooses the value. Reading this field "
            "is how a caller decides whether to generate an id or to take the "
            "one it is given."
        )
    )
    query_reports_sdk_session_id: bool = Field(
        description=(
            "Whether `POST /v1/query` sends the `x-sdk-session-id` response "
            "header.\n\n"
            "**AS-32, and the reason this field exists rather than being left to "
            "a document diff.** A relay routing on the SDK's conversation id can "
            "read it off the header when this is `true` and must scan the body "
            "when it is `false` -- which is a branch in the caller, so it is "
            "published where a running caller reads it.\n\n"
            "It is `true` on a build whose SDK assigns the conversation id when "
            "the session opens, and `false` where the id arrives with the first "
            "turn -- by which time a one-shot response has already been "
            "committed. The two session turn routes send the header on every "
            "build and are not covered by this field."
        )
    )
    query_consumes_a_session_slot: bool = Field(
        description=(
            "Whether `POST /v1/query` counts against `max_sessions` while it "
            "runs, and can therefore answer **429**.\n\n"
            "**AS-32.** A caller needs to know whether its one-shot traffic "
            "competes with its sessions for the same cap, and whether a "
            "retry-on-429 path is reachable on this route at all. `true` on a "
            "build that implements the one-shot as a real throwaway session."
        )
    )
    unsupported_options: list[UnsupportedOption] = Field(
        description=(
            "`RunOptions` fields this deployment cannot honour. Sending one is a "
            "**400**, never a silent drop.\n\n"
            "**AS-32, and it is the general case the two booleans above are "
            "special cases of.** A field the caller sets and nothing acts on "
            "produces a request that succeeds while doing something other than "
            "what it says -- the agent runs without the tools or the budget the "
            "caller believes it has, and the failure surfaces as an agent that "
            "is inexplicably bad at its job. That is the failure this list "
            "exists to convert into a refusal a caller can read in advance.\n\n"
            "**Empty means every `RunOptions` field is honoured**, which is the "
            "value a build serves when its SDK covers the whole surface. A "
            "non-empty entry is either a build fact (the SDK has no equivalent "
            "and this service cannot supply one) or a deployment setting -- "
            "`mcp_servers` appears here exactly when `allow_mcp_servers` is "
            "`false`, and the two never disagree.\n\n"
            "Options this service enforces ITSELF are absent from this list "
            "even when the SDK has no equivalent -- what the caller asked for "
            "happens, and by what means is not the caller's business."
        ),
        examples=[
            [],
            # **The key is shown even when null, because that is what is sent.**
            # Agent Studio noticed the earlier example omitting it while every
            # response carried `"types": null` -- harmless under the rule above,
            # and an example that shows a shape the service never emits is the
            # kind of thing that ends up in somebody's test fixture.
            [
                {"field": "max_turns", "types": None},
                {"field": "system_prompt", "types": ["object"]},
            ],
        ],
    )
    sandbox: Sandbox = Field(
        description=(
            "What confines the AGENT's own tools inside the container. **AS-32**: "
            "the two implementations differ here and an Agent that shells out "
            "notices immediately.\n\n"
            "Distinct from `permission_enforcement`, which is about how a "
            "request's `permission_mode` is applied. This is about what exists "
            "to apply it with."
        )
    )
    mcp: Mcp = Field(
        description=(
            "Which MCP servers this build can express, beyond whether it takes "
            "them at all (`allow_mcp_servers`). **AS-32**: the two builds differ "
            "here and a client must act on the difference before it sends a "
            "server, not after."
        )
    )
    strict_mcp_config: bool = Field(
        description=(
            "The server-side default for `RunOptions.strict_mcp_config`. **True "
            "here, which is NOT the SDK's default of false**: the workspace is "
            "agent-writable, so a `.mcp.json` in it would otherwise add servers "
            "the caller never sent."
        )
    )
    require_mounts: bool = Field(
        description=(
            "Whether this build refuses to BOOT when `workspace_dir` is not on "
            "a mounted filesystem, or a `reference_dirs` entry does not exist "
            "(exit 3). True is the default. Published for the same reason as "
            "`require_credentials`: if a boot check can fail, a caller that "
            "starts containers is better off knowing what it checks than "
            "discovering it from an exit code."
        )
    )
    permission_enforcement: Literal["none", "hook"] = Field(
        description=(
            "Whether THIS SERVICE inspects each tool call in-process before it "
            "runs. That is the only question this field answers.\n\n"
            '**"none" does NOT mean the agent is unconfined, and two builds '
            "reporting it do not confine alike.** It means there is no "
            "in-process per-call check. A build may still confine by the "
            "container alone, by an OS-level sandbox around each turn, or by a "
            "tool policy the agent loads when a session opens -- none of those "
            "is an in-process hook, so every one of them reports `none`.\n\n"
            '"hook": this service inspects each call and can refuse it while '
            "the turn is running. Even then the coverage may be partial: a "
            "hook that confines file writes need not confine a shell, and a "
            "shell redirect bypasses such a hook entirely.\n\n"
            "**Do not compare two builds on this field alone.** Read it with "
            "`sandbox.confines_writes_to_workspace`, `sandbox.network_access`, "
            "`default_allowed_tools` and `always_disallowed_tools` -- that is "
            "where the difference shows. Two builds can both report `none` "
            "while one enables a shell by default and the other refuses one "
            "whatever the caller asks for.\n\n"
            "**A second dimension is missing, and known to be missing**: WHEN "
            "the boundary is fixed. A policy the agent loads at session open "
            "cannot be narrowed mid-turn; an in-process check can. Both report "
            "through this single field today."
        )
    )


class Health(BaseModel):
    status: Literal["ok"]
    credentials_configured: bool
    workspace_dir: str
    auth_required: bool = Field(
        description=(
            "Whether `/v1` requires `Authorization: Bearer <token>`. **This "
            "route never does**, so it is always answerable — the container "
            "healthcheck reads it, and an authenticated service whose "
            "healthcheck could not run would be permanently unhealthy.\n\n"
            "`false` means the deployment serves `/v1` to anyone who can reach "
            "the port, on a service whose documented capability is arbitrary "
            "shell execution. That is a supported configuration for a "
            "single-operator loopback deployment and nothing else. Put network "
            "isolation and a relay in front of it before a token."
        )
    )
    database_configured: bool = Field(
        description=(
            "Whether `AGENT_SERVICE_DATABASE_URL` is set. Persistence is "
            "optional; `false` is a normal, supported deployment in which the "
            "history routes answer 404 with "
            "`type: .../persistence-disabled`."
        ),
    )
    # Required AND nullable, deliberately: the field is ALWAYS present, and
    # `null` means "no database configured" rather than "this service did not
    # tell you". Optional-with-a-default would let a client read absence as
    # either, which is the ambiguity AS-17a rejects for
    # `SessionRecord.sdk_session_id`.
    database_usable: bool | None = Field(
        description=(
            "Whether this service can actually query its database right now, "
            "or `null` when none is configured. Probed per request against a "
            "real table, so it covers an unreachable host, a rejected "
            "credential AND a schema that was never migrated -- the last of "
            "which a `SELECT 1` would miss and which is the default first state "
            "of a deployment that enables persistence, because migrations do "
            "not run on startup.\n\n"
            "**`status` stays `ok` when this is `false`.** The service is up "
            "and serving agent traffic; persistence is an optional subsystem "
            "and its failure is deliberately not allowed to stop turns. What it "
            "does mean is that rows are being **discarded** -- the writer "
            "cannot raise into a turn, so it counts and drops -- and that the "
            "history routes will answer 500. Alert on this field, not on the "
            "status code."
        ),
    )


class Problem(BaseModel):
    """RFC 7807 problem document."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


class ValidationFailure(BaseModel):
    """One thing wrong with a request body, and **never the value that was wrong.**

    `loc` is what a client acts on: it names the field. `input` -- which the
    framework's own error carries -- is deliberately absent, and that is the
    whole reason this model exists rather than the framework's.
    """

    loc: list[str | int] = Field(
        description=(
            "The path to the offending field, framework order: `[\"body\", "
            "\"options\", \"permission_mode\"]`. **This is the field a client "
            "needs** -- a 422 that says only *something was wrong* makes the "
            "caller diff their own request against the document."
        ),
        examples=[["body", "options", "permission_mode"]],
    )
    msg: str = Field(
        description="Prose, and it may change. Do not branch on it.",
        examples=["Input should be a valid string"],
    )
    type: str = Field(
        description=(
            "The framework's machine-readable failure kind -- `string_type`, "
            "`missing`, `model_attributes_type`. Stable enough to branch on, "
            "and it is what to branch on rather than `msg`."
        ),
        examples=["string_type"],
    )


class ValidationProblem(Problem):
    """A 422, as an RFC 7807 problem document that names the fields.

    **This replaced the framework's `HTTPValidationError` on 2026-08-19**, and
    the interesting part is that three artifacts disagreed before it: two builds
    RETURNED the framework's shape, all three DECLARED it, and all three guides
    said errors -- *including a 422 from validation* -- are problem documents.
    So the documents and the guides contradicted each other and one build
    contradicted its own document.

    **Why not simply conform to what was declared.** The framework's error
    carries `input`: the offending value, echoed back. A malformed body can
    contain a caller's own MCP bearer token, this service is unauthenticated by
    default, and an error body is the thing most likely to be logged by whatever
    sits in front. One build refused to echo it for exactly that reason and was
    right to; what it got wrong was doing so while its document promised
    otherwise, and withholding `loc` along with `input`.

    **So this carries `loc`, `msg` and `type`, and never `input`.** A client
    learns which field was wrong, which is what a client needs, and the value
    stays out of the response.
    """

    errors: list[ValidationFailure] = Field(
        description=(
            "Every failure in the request, not just the first. Empty is not "
            "expected: a 422 with nothing here would say less than the status "
            "already says."
        ),
    )


SessionStatus = Literal["idle", "running", "closed"]


class SessionCreate(BaseModel):
    """Create a session. Options are fixed for the session's lifetime except
    for model and permission_mode, which PATCH can change."""

    options: RunOptions = Field(default_factory=RunOptions)
    title: str | None = Field(default=None, max_length=200)
    sdk_session_id: str | None = Field(
        default=None,
        description=(
            "**The SDK conversation id to use**, assigned by the caller "
            "instead of by the CLI. Must be a UUID, and is returned on the 201 "
            "so the mapping exists before the first model call.\n\n"
            "NOT the service-side `session_id`, which is minted here and "
            "returned as `SessionRecord.session_id`.\n\n"
            "**Rejected with 400 alongside `options.resume`** -- the CLI "
            "refuses that combination.\n\n"
            "**Must be unused by a TURN.** An id whose conversation has "
            "already taken a turn in the same workspace is refused. Creation "
            "alone does not consume it: a create that timed out, or that "
            "succeeded and was closed without a turn, leaves the id reusable.\n\n"
            "**Retrying a create that timed out:** reconcile with "
            "`GET /v1/sessions` matching on `sdk_session_id`. If a session "
            "holds your id the create succeeded and you lost the response; if "
            "none does, retry with the SAME id."
        ),
        examples=["7ad25f07-08d4-4b3a-9f21-2b6a1c7d3e55"],
    )
    session_id: str | None = Field(
        default=None,
        deprecated=True,
        description=(
            "**Deprecated alias for `sdk_session_id`. Use that instead.**\n\n"
            "Sending both is accepted only when they are equal; otherwise the "
            "request is rejected rather than one being silently preferred."
        ),
    )

    @model_validator(mode="after")
    def _one_sdk_session_id(self) -> SessionCreate:
        """Fold the deprecated alias into `sdk_session_id`, or refuse.

        Two names for one value can disagree, and picking a winner silently is
        how a caller ends up with a session under an id it did not choose --
        which is precisely what it supplied an id to avoid.
        """
        # Read through `__dict__` rather than the attribute: pydantic raises a
        # DeprecationWarning on every access of a deprecated field, and this
        # module's own validator firing it would put a warning on requests that
        # did nothing wrong.
        alias = self.__dict__.get("session_id")
        if alias is None:
            return self
        if self.sdk_session_id is not None and self.sdk_session_id != alias:
            raise ValueError(
                "session_id and sdk_session_id are two names for one value and "
                f"they disagree ({alias!r} vs {self.sdk_session_id!r}); "
                "send sdk_session_id alone"
            )
        self.sdk_session_id = alias
        return self


class TurnRequest(BaseModel):
    prompt: str = Field(min_length=1, examples=["What did we just look at?"])


class SessionUpdate(BaseModel):
    """Both fields optional; omitted fields are left unchanged.

    Two other permissive behaviours are DELIBERATE and left as they are
    (follow-up item 9): `{"bogus": 1}` is accepted, because no model in this
    module sets `extra="forbid"`, and `{"model": null}` is indistinguishable
    from omitting the field, because pydantic gives both the same default --
    so a caller cannot reset a session to the server default. Both are
    properties of how this whole schema module behaves rather than of this
    model, and changing either here alone would make one model inconsistent
    with every other. Pinned in tests/test_session_schemas.py so they are a
    recorded decision, not an accident.
    """

    model: str | None = Field(
        default=None, min_length=1,
        description=(
            "An empty string is rejected rather than forwarded (follow-up "
            "item 9). Unlike the two permissive behaviours above, forwarding "
            "it is not harmless: it issues a real `set_model` control request "
            "to the agent with a meaningless argument."
        ),
    )
    permission_mode: PermissionMode | None = None


class InterruptResult(BaseModel):
    """What an interrupt request actually did.

    Interrupting is idempotent and never an error: a turn can end between a
    caller deciding to stop it and the request arriving, which is a race no
    client can avoid. Hence 200 rather than 409 -- and a body rather than a
    bare 204, which would report success for a request that did nothing.
    """

    interrupted: bool = Field(
        description=(
            "True only if a control request was genuinely sent to the agent. "
            "False means there was nothing to interrupt -- not an error. This "
            "is NOT implied by `status`: a turn abandoned mid-drain (the usual "
            "result of a dropped SSE connection) leaves the session `idle` "
            "while the agent process is still producing, and interrupting it "
            "does send a real control request."
        )
    )
    status: SessionStatus = Field(
        description=(
            "The session's status immediately AFTER the request. A turn can "
            "end while the control request is in flight, so this may differ "
            "from the status the request arrived to find."
        )
    )


class ContextUsage(BaseModel):
    """Raw passthrough of ClaudeSDKClient.get_context_usage().

    Categories are reported by the CLI (System tools, Skills, Messages,
    Autocompact buffer, Free space, ...) and their exact set is not part of
    any contract, so they are carried through unmodelled.
    """

    categories: list[dict[str, Any]] = Field(default_factory=list)


class TurnRecord(BaseModel):
    """What became of a session's most recent turn.

    A NESTED model rather than flat `last_turn_*` fields on `SessionRecord`,
    for one reason that decides it: a session that has never taken a turn must
    be able to say so unambiguously. Nested, that is `last_turn: null`. Flat,
    the only available answer is every field being falsy at once -- and
    `last_turn_interrupted: false` is a claim about a turn that does not
    exist, indistinguishable from a real turn nobody interrupted.

    Deliberately NOT a `RunResponse`. This is a record fetched later, so it
    carries no `events` (already streamed, and unbounded) and no `result`
    text: "what became of the turn" is answered by the flags below, while the
    output belongs to whoever took the turn. `GET /v1/sessions` returns a list
    of these records, and the model's prose output is not something to hand
    out by the pageful to anyone enumerating sessions.
    """

    sdk_session_id: str | None = Field(
        default=None,
        description=(
            "The SDK's OWN conversation id for this turn -- what the CLI "
            "reports on its init and result messages. Named `sdk_session_id`, "
            "never a bare `session_id`, because that name already denotes the "
            "registry handle on `SessionRecord`: the two are different "
            "identifiers and `POST /v1/sessions/{this value}/messages` is a "
            "404. Measured."
        ),
    )
    outcome_recorded: bool = Field(
        default=False,
        description=(
            "False when the turn ended without a terminating ResultMessage -- "
            "abandoned mid-drain (the usual result of a dropped SSE "
            "connection), timed out, or the agent process died. Everything "
            "below except `interrupted` and `timed_out` is then null or "
            "false because the SDK never reported it, not because it was "
            "measured to be so."
        ),
    )
    interrupted: bool = Field(
        default=False,
        description=(
            "This turn was stopped by an explicit interrupt request. The SDK "
            "reports an interrupted turn identically to a crash "
            "(is_error=true, subtype='error_during_execution'), so this flag "
            "is the only way to tell them apart."
        ),
    )
    timed_out: bool = Field(
        default=False,
        description=(
            "This turn exceeded its time budget and was force-ended. Present "
            "HERE but deliberately absent from `RunResponse`: a turn that "
            "times out on the wire is a 504 and the status code says so, but "
            "on a record fetched afterwards the status code is long gone -- "
            "possibly to a different caller entirely -- and a timeout is "
            "otherwise indistinguishable from any other "
            "`outcome_recorded: false` ending."
        ),
    )
    is_error: bool = Field(
        default=False, description="The agent reported failure. See `interrupted`."
    )
    subtype: str | None = None
    stop_kind: StopKind | None = Field(
        default=None,
        description=(
            "WHY THE TURN ENDED, as a closed set every implementation maps "
            "onto -- read this rather than the SDK-specific strings beside "
            "it. Null only when the build cannot tell; 'other' when it "
            "knows and has no mapping. Never contradicts `interrupted`, "
            "`timed_out`, `limit_hit` or `is_error`."
        ),
    )
    stop_reason: str | None = None
    terminal_reason: str | None = None
    limit_hit: Literal["turns", "budget"] | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    turn_cost_usd: float | None = Field(
        default=None,
        description=(
            "What this turn cost, in USD: the SDK's cumulative figure for it "
            "minus the previous turn's. Null means nobody can say (no "
            "ResultMessage, one carrying no price, an ABORTED turn whose "
            "cumulative did not move, or a SUCCESSFUL turn the SDK attributed "
            "nothing to), which is not 0.0. "
            "See `RunResponse.turn_cost_usd`."
        ),
    )


class SessionRecord(BaseModel):
    session_id: str
    sdk_session_id: str | None = Field(
        default=None,
        description=(
            "The SDK's conversation id for this session, or null when it is not "
            "known yet. Populated at creation when the caller supplied "
            "`session_id` on `POST /v1/sessions`; otherwise the CLI mints it at "
            "the first turn and this stays null until then (measured: the id "
            "does not exist before the first turn). "
            "Distinct from `session_id` above, which is this service's registry "
            "handle and the value used in `/v1/sessions/{sid}` paths."
        ),
    )
    agent_id: str | None = Field(
        default=None,
        description=(
            "The `AGENT_ID` of the container that created this session, or "
            "`null` when it was started without one.\n\n"
            "**Provenance, not authorisation.** This service neither parses it "
            "nor enforces anything with it. It exists because a caller may run "
            "many agents against ONE shared database, where every row belongs "
            "to somebody and nothing said which -- so a session the caller's "
            "own bookkeeping missed is not untidy, it is one nobody can be "
            "shown to own.\n\n"
            "**Nullable but not optional**: the field is always present, so "
            "`null` means \"that container had no `AGENT_ID`\" and can never "
            "mean \"this service did not tell you\". Same rule as "
            "`Health.database_usable`.\n\n"
            "**It cannot be set by a caller.** The value is a process constant "
            "read from the environment at startup; there is no request field "
            "for it to arrive through, which is structural rather than "
            "validated. `POST /v1/sessions` accepts no `agent_id`."
        ),
        examples=["agent-7f3c9a1e"],
    )
    title: str | None = None
    status: SessionStatus
    created_at: float
    last_used_at: float
    turns: int = Field(
        description=(
            "Turns that reached a result. A turn that timed out, failed or was "
            "abandoned mid-drain is not counted; one whose result was produced "
            "but never delivered (the client hung up on the last frame) is."
        )
    )
    total_cost_usd: float | None = Field(
        description=(
            "The SDK's running total for this session's connection, assigned "
            "verbatim and never summed. **A floor on what the session cost, "
            "not the figure** -- an interrupted turn does not move it, and a "
            "turn the SDK attributed no cost to leaves it where it was. Read "
            "it as \"at least this much\".\n\n"
            "**`null` means this build cannot price a turn at all**, which is "
            "not the same as `0.0`. Some agent SDKs report token usage and no "
            "monetary figure; such an implementation reports `null` here for "
            "every session rather than a `0.0` that would read as free. "
            "Always present, so `null` can never mean \"not told\"."
        )
    )
    model: str | None = Field(
        default=None,
        description=(
            "The model this session is CURRENTLY configured with -- resolved "
            "at creation from the request or the server default, and updated "
            "by a successful PATCH. This is the read-back for PATCH: without "
            "it there is no way to confirm a model change took."
        ),
    )
    permission_mode: str | None = Field(
        default=None,
        description=(
            "The permission mode this session is currently configured with, "
            "resolved and updated exactly like `model`. A plain string rather "
            "than the `PermissionMode` enum on purpose: the server default is "
            "an unconstrained environment setting, and validating it here "
            "would turn an operator's config typo into a 500 on the one "
            "endpoint whose job is to report what a session looks like. "
            "\n\nOnly these two fields are echoed. Every other option is fixed "
            "for the session's lifetime, and `system_prompt` in particular "
            "carries caller-supplied content plus the server's own workspace "
            "layout -- not something to return from a list endpoint."
        ),
    )
    last_residue_discarded: int = Field(
        default=0,
        description=(
            "How many stale messages the LAST turn discarded before it "
            "started. Non-zero means a previous turn was abandoned with "
            "messages still in flight on the SDK's connection-scoped buffer "
            "(spike case S3): they would otherwise have been read as this "
            "turn's own -- one caller's turn attributed to another -- so they "
            "were dropped. Reset at the top of every turn, so it always "
            "describes the most recent one and never a stale count from an "
            "older abnormal turn."
        ),
    )
    last_turn: TurnRecord | None = Field(
        default=None,
        description=(
            "What became of the most recent turn. NULL means this session has "
            "never taken one -- not that the last turn reported nothing. This "
            "is how a caller whose stream dropped asks what happened to the "
            "turn it lost: `turns` and `total_cost_usd` do not move for an "
            "abandoned turn, so without this a session that lost a turn looks "
            "exactly like one that never took any."
        ),
    )
    context_usage: ContextUsage | None = Field(
        default=None, description="Populated on the detail endpoint only."
    )


class SessionList(BaseModel):
    sessions: list[SessionRecord] = Field(default_factory=list)


# --- stored history (plan-03 Task 5) ----------------------------------------
# Distinct from `AgentEvent`, which is the STREAMING shape. These carry storage
# identity (`id`, `run_id`, `at`) that the live stream has no use for, and omit
# `raw`, which can be large and is subject to Q3. Two shapes on purpose: the
# wire format of the stream is fixed by plan-03's global constraints, and a
# stored row should be free to gain columns without changing it.


class StoredEvent(BaseModel):
    """One recorded SDK message."""

    id: int = Field(description="Storage sequence. Stable, and usable as a pagination cursor.")
    run_id: str
    seq: int = Field(description="Position within its own run, as the driver counted it.")
    at: datetime
    type: str
    subtype: str | None = None
    content: Any | None = None


class TranscriptPage(BaseModel):
    """One page of a session's transcript, oldest first."""

    session_id: str
    events: list[StoredEvent]
    next_after: int | None = Field(
        default=None,
        description=(
            "Pass as `after` to fetch the next page. `null` means this is the last "
            "page -- NOT that the session has ended, which is `status` on the record."
        ),
    )


class StoredRun(BaseModel):
    """One recorded run or turn, as stored.

    Wider than `RunResponse`: it carries `duration_api_ms`, `errors` and
    `api_error_status`, which are diagnostic detail a stored row wants and a
    streaming caller does not.
    """

    run_id: str
    session_id: str | None = Field(
        default=None,
        description="The service-side session id, or null for a one-shot /v1/query run.",
    )
    sdk_session_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    prompt: str
    result_text: str | None = None
    result_subtype: str | None = None
    stop_kind: StopKind | None = Field(
        default=None,
        description=(
            "WHY THE TURN ENDED, as a closed set every implementation maps "
            "onto -- read this rather than the SDK-specific strings beside "
            "it. Null only when the build cannot tell; 'other' when it "
            "knows and has no mapping. Never contradicts `interrupted`, "
            "`timed_out`, `limit_hit` or `is_error`."
        ),
    )
    stop_reason: str | None = None
    terminal_reason: str | None = None
    limit_hit: str | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    cost_usd: float | None = Field(
        default=None,
        description=(
            "What this run cost. `null` means nobody can say -- NEVER 0.0, which "
            "would claim the run was free. An interrupted turn is unattributed, "
            "not free."
        ),
    )
    usage: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None
    permission_denials: Any | None = None
    errors: Any | None = None
    api_error_status: int | None = None
    is_error: bool | None = Field(
        default=None,
        description="The AGENT reported its task failed. Distinct from a machinery failure.",
    )
    interrupted: bool = False
    timed_out: bool = False
    outcome_missing: bool = Field(
        default=False,
        description=(
            "The run never produced the agent's own terminating result: a crash, "
            "a killed process, an abandoned "
            "consumer, or a timeout. A real state, distinct from a clean finish."
        ),
    )
