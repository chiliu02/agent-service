# `gemini-python` — the guide for someone integrating against it

**Read this before writing a client, and read §3 before deploying one.** This
build satisfies the same specification as `claude-python` and `codex-python`, and
differs from both in ways a client must act on — every one of them published on
`GET /v1/capabilities`, and every one of them measured rather than assumed.

**A condition of every non-snapshot release** (user, 2026-08-09). A build that
ships without this document is a build whose consumer has to read its source.

| You want | Go to |
|---|---|
| To run it | [§1](#1-what-it-is-and-how-to-run-it) |
| To generate a client | [§2](#2-the-openapi-document-and-how-to-use-it) |
| To not be surprised | **[§3](#3-things-that-will-surprise-you)** |
| To know how it differs from the other two builds | [§4](#4-how-this-build-differs-and-where-to-read-it-at-runtime) |
| To know what is actually proven | [§5](#5-tested-expected-and-the-difference) |
| To know what is yours | **[§6](#6-your-responsibilities-not-this-services)** |

**What it is built on, and it is not an SDK.** The target is **Gemini CLI in
headless mode** — `gemini -p "<prompt>" -o stream-json`, pinned to
`@google/gemini-cli@0.54.4`. There is no Python SDK for it and no Python package
at all: the agent is a **Node program this service spawns once per turn**, and
everything below follows from that.

**Not the Gemini API and not the Gemini Enterprise Agent Platform.** The first is
a model endpoint with no agent loop; the second hosts the agent for you, which
puts it outside this platform's scope — every target here runs locally, in our own
container.

**One other document, beside this one.** `gemini-python-references.md` carries
every measurement with its controls, every clause this build cannot satisfy and
why, the CLI survey, the tool policy and the container. Its entries are numbered
and the code cites those numbers; **a `GP-nn` below is one of them.**

---

## 1. What it is, and how to run it

```bash
cp .env.example .env          # set GEMINI_API_KEY and WORKSPACE_HOST_PATH
docker compose up -d --build --wait
curl -s localhost:8000/healthz
```

**`--wait` is not optional.** A plain `docker compose up -d` reports `Started`
and returns 0 for a container that has already exited 3. `restart: "no"` keeps a
misconfigured container dead and inspectable rather than looping.

### 1.1 Boot gates — three ways it refuses to start, all exit 3

| Gate | Refuses when | Turn it off with |
|---|---|---|
| credentials | none of `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_GCA` is set | `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` |
| mounts | `AGENT_SERVICE_WORKSPACE_DIR` is not on a mounted filesystem | `AGENT_SERVICE_REQUIRE_MOUNTS=false` |
| schema | a database is configured and is at the wrong migration | — fix the database |

Each names its own remedy in the log. **Exit 3 means configuration**, and is
distinct from a crash and from a turn failing.

**One route the credential gate cannot see** (`GP-07`): the agent also reads an
auth method from `<home>/.gemini/settings.json`, so a deployment with a mounted
home carrying an earlier login is already authenticated with no variable set.
Such a deployment must start with `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`.

### 1.2 Before you start a container: `PrebootSpec` in the document

```bash
docker inspect --format '{{json .Config.Labels}}' <image>
```

gives three labels. `com.npf.agent-service.impl` and `.document-version` name
the published document `<impl>-<document-version>.json`;
`.schema-revision` repeats one value the document already pins, and is there for
the case where the document cannot be reached at all. Its
`components.schemas.PrebootSpec` states the credential variables, the provider
selectors, `model_api`, `endpoint_source`, `ca_bundle_source`, the schema
revision, `auth_enforced` and the listen address — each pinned with `const`.

**Nothing is executed and no image is needed to read most of it**: if you
already know which build you are provisioning, the document alone answers.
`version` and `impl.version` are the only fields left open, because they move
on the implementation stream — read those from the image tag or from
`GET /v1/capabilities`.

**This was the `agent-service-spec` command until 0.19.0.** It printed the
same facts from inside the image, which meant a provisioner had to pull and run
one to answer a question it asks while deciding whether to pull at all.

**The container runs as uid 1000, gid 1000, and you need that number before the
container exists.** Published as `PrebootSpec.runs_as`, `const`-pinned, so it is
readable from the document with nothing running.

**Chown the bind-mount source to it before you start.** Docker creates a missing
mount point as `root:root 0755` and the agent is not root, so the mount is
read-write and the first thing the agent writes fails — with nothing naming the
cause. The image's own `Config.User` says `agent`, a **name**, which means nothing
on a host filesystem and resolves to a number only by running the container, which
is after the directory had to be right.

**The mode is yours to choose; the owner is not.** That is the whole reason the
number is published rather than left to a convention.

---

## 2. The OpenAPI document, and how to use it

`GET /openapi.json`, and the same document is published at
`spec/openapi/gemini-python-<version>.json`. They are
byte-equal; generate your client from either.

**Every implementation serves the same document**, and since 2026-08-12 every one
of them lists its operations in the same order, so a diff between two builds shows
only what actually differs. What a build may add is a status code or a response
header; what it may not do is lack or contradict anything in the shared core
(`core-<version>.json`).

**Fourteen operations.** Sessions and turns, one-shot query, interrupt, and two
history routes.

**Errors are RFC 7807 problem documents** with `content-type:
application/problem+json`, including the ones the framework produces — a 404 for
an unknown path and a 422 from validation. **Branch on `type` and `status`, never
on `title` or `detail`**: those are prose and prose is allowed to change.

**A 422 names the fields and never the values.** `errors` is an array of
`{loc, msg, type}`: `loc` is the path to what was rejected
(`["body", "options", "permission_mode"]`) and is the part to act on, `type` is
the machine-readable failure kind and is what to branch on, `msg` is prose and
may change. **`input` is deliberately absent** — the framework's own error echoes
the offending value, a malformed body can carry your MCP bearer token, and an
error body is the thing most likely to be logged by whatever sits in front.

---

## 3. Things that will surprise you

### 3.1 `sdk_session_id` identifies a TURN, not a conversation

**On this build it changes on every turn of a resumed session** (`GP-34`,
`GP-11`). The durable resume mechanism is `--session-file`, and the agent mints a
new conversation id each time it reads one.

So:

- **route on it, never key on it.** A relay may use it to associate a response
  with a request; a client that stores it as "the conversation" will find it stale
  after the next turn.
- **`session_id` — this service's own — is the stable handle.** It is what every
  path takes and what a client should persist.
- **`allow_supplied_sdk_session_id` is `false` here**, and a request that supplies
  one is refused with `400 sdk-session-id-unsupported` rather than accepted and
  answered with a different id. The other two builds accept it; this one cannot
  honour it past the first turn, so it declines rather than pretending.

`GET /v1/sessions/{sid}` reports the most recent one, and every id a session has
ever issued is accepted by `options.resume` (`GP-35`) — because the client most
likely to resume is the one whose connection dropped, and it is holding an old id.

### 3.2 A refusal looks exactly like success

**A turn that declined to do the work still exits 0 and reports
`status: "success"`** (`GP-18`). There is no field that distinguishes "did it"
from "decided not to". `is_error` is false for both, because only the agent's own
envelope may set it and the envelope says success.

If your client needs to know whether work happened, read the `tool_use` events.
Which leads to:

### 3.3 `usage.tool_calls` undercounts, and the events are the truth

**Measured: a turn carrying a `tool_use` and a `tool_result` reported
`tool_calls: 0`** (`GP-43`). The counter appears to count successful registered
calls only. **Do not use it to decide whether a turn used tools** — count the
events.

Related and harmless but confusing: the model sometimes calls `update_topic`, a
tool the CLI does not register, and gets `tool_not_registered` back. It is not
your policy denying it and adding it to `allowed_tools` would do nothing. It costs
1.6–9.1 seconds when it happens.

### 3.4 Cost is always `null`, and that is not a bug

**This agent reports no monetary figure at all** (`GP-16`) — tokens and latency
only. `total_cost_usd` and `turn_cost_usd` are `null` on every session and every
turn, forever. **`0.0` would read as *free***, which is why they are null.

**Budget accordingly**: a turn costs roughly **7,000 input tokens before your
prompt is read** (`GP-44`) — the agent's system prompt and tool declarations.
Three prompts of 3 to 9 words measured 7,072 / 7,076 / 7,082 input tokens. **Turn
count predicts spend here, not prompt length**, so a chatty client that sends many
tiny turns pays far more than one that batches.

`model_usage` is **per turn** on this build, so summing it across a session is
correct — the opposite of the Claude build, where it accumulates.

### 3.5 There is no cancel verb, so interrupt is a kill

Neither the CLI nor its ACP mode registers a cancel method (`GP-02`).
`POST /v1/sessions/{sid}/interrupt` therefore **kills the agent's process group**.
Expect no final event beyond what already reached you, and expect
`stop_kind: "interrupted"` with no result text.

A consequence: **the wall clock is mandatory rather than defensive.** Turns on
this agent can fail to terminate — nine trials of one prompt produced five that
never ended (`GP-18`) — so `AGENT_SERVICE_TURN_TIMEOUT_S` is the only thing that
ends such a turn, and it answers `504 turn-timeout` rather than a 200 with a flag.

### 3.6 The default model is `"auto"`, which is a routing policy and bills twice

**`capabilities.default_model` reports the literal string `"auto"`** when no model
is configured (`GP-15`), because that is what the agent reports and it is not a
model id. A turn under `auto` names **two** models in its usage block (`GP-16`).

**Set `AGENT_SERVICE_MODEL` if that matters to your bill.** The models that
actually ran are only knowable from the final `result` event.

### 3.7 The tool boundary is a generated policy file, and the shell is never on

Every session gets an **admin-tier policy** written before its first turn: deny
`*`, then allow exactly the tools that session may use (`GP-19`, `GP-21`).

**`run_shell_command` is refused whatever you ask for** (`always_disallowed_tools`).
An unrestricted shell voids every other rule, because the agent writes files with
it instead of the tool that was denied (`GP-20`).

**`permission_enforcement` reports `"none"`, and that does not mean unconfined.**
The field asks whether *this service* inspects each tool call in-process; it does
not — the policy is loaded by the agent when the session opens. All three builds
report `"none"` and mean three different things (`GP-52`). Read
`always_disallowed_tools`, `default_allowed_tools` and the `sandbox` pair beside
it.

**A consequence worth planning around: the boundary is fixed when the session
opens.** It cannot be narrowed mid-turn.

### 3.8 MCP servers are per session, and the workspace cannot add its own

Send them in `options.mcp_servers` on `POST /v1/sessions`. All three transports
work — `stdio`, `sse`, `http` — with arbitrary headers (`GP-46`).

**`strict_mcp_config` is `true` and `false` is refused** (`GP-48`). A
`.gemini/settings.json` inside your mounted workspace merges into the session's
own, so without a control any repository could add servers — subprocesses — that
nobody asked for. This build passes an allow list naming exactly the servers you
sent, on every turn, including when you sent none. Non-strict is not a behaviour
it can produce, so it declines rather than accepting a flag that would change
nothing.

**Allowing a server allows every tool on it.** The policy rule is
`mcpName = <server>, toolName = "*"`. There is no way to permit one tool of a
server through this API today.

**Server names may not contain an underscore.** The agent names an MCP tool
`mcp_<server>_<tool>` and splits on the first `_` after `mcp_`, so an underscore
makes the name unaddressable by a policy rule (`GP-28`). A name with one is
refused with `400 mcp-server-unsupported`.

**Your response must BEGIN within 60 seconds.** Published as
`mcp.tool_call.request_timeout_s` (`GP-65`), and it is the bound most likely to
catch you: a server that thinks in silence and then replies with one JSON body is
cut off at a minute however short the rest of its work. **Open an SSE stream
immediately** — that clears it, and comment frames are enough to keep it clear.
Measured at 60.2 s against this image, with no proxy anywhere in the path.

**A tool call is abandoned after 600 seconds, and progress will not save it.**
Published as `mcp.tool_call.total_timeout_s` (`GP-64`), and it is **wall clock**:
the timer runs from the call to its answer and nothing restarts it. There is no
request bound and no idle bound on this build — that one figure is the whole of
it, and it is the shortest ceiling of the three builds.

**The `progressToken` you receive is not a promise.** The agent sends one on
every call and uses it to drive its own display; the flag that would let a
`notifications/progress` restart the timer is never passed, so
`mcp.tool_call.progress_resets_idle` is **`false`** rather than null. Emitting
progress here is harmless and buys nothing. If your tool needs to be held open
for longer than 600 s, no MCP-level behaviour on this build will do it.

**Bounded again by the turn.** The tool call lives inside one, and this build's
turn timeout defaults to 600 s as well — so the two figures coincide and neither
is slack in the other.

**And nothing in `mcp.tool_call` describes what sits BETWEEN this container and
your server.** A proxy or gateway enforcing time-to-first-byte cuts off exactly
the same shape of tool for a different reason, so responding at once is worth
doing even where no build publishes a bound. It costs nothing and it is the only
half of this you control.

### 3.9 History needs a database; continuity does not

**These are different volumes and different failures** (`GP-49`):

| | needs | losing it costs |
|---|---|---|
| `options.resume`, multi-turn sessions | the `transcripts` volume | **continuity** — every resume becomes a fresh conversation |
| `GET /v1/sessions/{sid}/transcript`, `GET /v1/runs/{run_id}` | `AGENT_SERVICE_DATABASE_URL` | **history** — the routes answer `404 persistence-disabled` |

Unlike the Claude build, **this one cannot resume out of the database.** The rows
are a record and never a source: durable resume reads a `--session-file` from
disk. So a deployment that wants conversations to survive a container restart
needs the volume, with or without a database.

**Two different 404s, and branch on `type`:** `persistence-disabled` means history
is off here; `session-not-found` and `run-not-found` mean no such id.

### 3.10 `system_prompt` REPLACES the agent's framing, and nothing you send suppresses the workspace's own files

**The string form is honoured**, written into the session's own home and read by
the agent through its `GEMINI_SYSTEM_MD` variable (`GP-66`). It is **session
scoped**: send it on `POST /v1/sessions` and every turn of that session uses it.
The Claude preset object — `{"type": "preset", …}` — names a preset this agent
does not have and is refused by type, published as
`{field: "system_prompt", types: ["object"]}`.

**It is a replacement, not an addition.** What you send stands in for the
agent's entire built-in prompt: its safety rules, its tool protocol, its
workflows. Three words of instruction give you an agent with three words of
framing, and its tool use will show it. If you want the built-in behaviour plus
your own, restate what you need — there is no append form here.

**It was accepted and applied to nothing until 2026-09-02.** If you tested this
build before that date and concluded the field did nothing, you were right.

**And it suppresses nothing.** This build refuses `setting_sources` outright, so
there is no request that stops the agent reading what is on disk beside it:

| On disk | Can a request supply it? | Can a request switch it off? |
|---|---|---|
| `GEMINI.md` context files in your mounted workspace | no | **no** — they are read every turn, and they are appended *after* your `system_prompt` |
| `.gemini/settings.json` in your mounted workspace | no | only for MCP, via the server allow list (§3.8) |
| Skills, subagents, custom commands | no | no |

**So the workspace you mount is part of the request whether you meant it or
not.** A repository carrying a `GEMINI.md` instructs this agent on every turn of
every session that runs against it. If a session must be reproducible, control
what you mount — that is the only lever this build gives you. The three builds
are compared field by field in the platform's `capability-divergence.md`, §3.1.

### 3.11 Sessions expire

`limits.session_idle_ttl_s` (default 1800) is published **and enforced** — an idle
session is closed and its `sid` becomes a `404`. Size your reconciliation window
from that number.

---

## 4. How this build differs, and where to read it at runtime

**Read `GET /v1/capabilities` rather than branching on which image you have.**
Every difference below is published there.

| Field | Here | Why it differs |
|---|---|---|
| `allow_supplied_sdk_session_id` | **`false`** | the agent mints a new id per turn (§3.1) |
| `default_model` | `"auto"` unless configured | a routing policy, not a model (§3.6) |
| `total_cost_usd` | always `null` | no monetary figure exists (§3.4) |
| `always_disallowed_tools` | `["run_shell_command"]` | an unrestricted shell voids the policy (§3.7) |
| `mcp.transports` | all three, `http_headers: "any"` | wider than the Codex build's |
| `strict_mcp_config` | `true`, and `false` refused | the workspace merge (§3.8) |
| `sandbox.confines_writes_to_workspace` | `false` | this service does not itself enforce it |
| `effort_levels`, `setting_sources` | `[]` | no equivalent on this agent |
| `unsupported_options` | `effort`, `setting_sources`, `max_budget_usd`, `max_turns` | each refused with a 400, never accepted and ignored |

**An option in `unsupported_options` is really refused.** Publishing a refusal
that does not happen is the same defect as an option accepted and dropped, and
this build has been on both sides of it.

---

## 5. Tested, expected, and the difference

| | |
|---|---|
| **Proven against a running container** | all fourteen operations; multi-turn resume carrying context; SSE streaming arriving incrementally; interrupt ending a turn within ~50 ms of the kill; MCP tools called for real; the workspace's own MCP server blocked; a real turn recorded to Postgres and read back |
| **Proven without an agent** | 117 unit tests, and the platform conformance suite — **78 passed with no database, 79 with one, 0 failed** |
| **Expected but NOT measured** | `plan` permission mode's exact semantics; whether `GOOGLE_GEMINI_BASE_URL` actually reaches a non-Google endpoint (the variable is measured, the redirect is not — `GP-03`, `GP-42`); behaviour under concurrent load; memory and pid ceilings, which are inherited from another build's measurements and are a ceiling rather than a fit |
| **Known not to work** | `--sandbox` inside a container (`GP-31`, exit 44). The container is the sandbox |

**Everything is pinned to `@google/gemini-cli@0.54.4`** and there is no stability
contract over its flags. The Dockerfile verifies the installed version at build
time, so a drifted registry breaks the build rather than a turn.

---

## 6. Your responsibilities, not this service's

- **Network isolation first, then a relay, then a token.** `AGENT_SERVICE_AUTH_TOKEN`
  puts bearer auth on `/v1`; `/healthz` never requires it, because the container
  healthcheck reads it. Auth is the third control, not the first.
- **Use a per-instance token, never one shared across a fleet.** The service pops
  it out of its environment so the agent does not inherit it — but the agent runs
  as the same uid and `/proc/<pid>/environ` still carries the original value
  (`GP-51`). A token this service holds is obtainable by anything that can take
  one turn.
- **The workspace is yours and the agent can write to it.** Mount a scratch
  directory or a checkout you can throw away; the boundary is the container plus
  the tool policy, not the mount.
- **Nothing here defends against prompt injection**, which arrives through a
  perfectly authorised call and is the likeliest adversary.
- **Back up the `transcripts` volume** if conversations matter (§3.9).
