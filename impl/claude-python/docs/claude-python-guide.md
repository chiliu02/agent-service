# `claude-python` — the guide for someone integrating against it

**Read this before writing a client.** It is the front door: what the service
is, how to drive it, **what will surprise you**, which behaviour is measured and
which is merely intended, and what remains your responsibility rather than
this service's.

**A condition of every non-snapshot release** (user, 2026-08-09). A build that
ships without this document is a build whose consumer has to read its source.

| You want | Go to |
|---|---|
| To run it | [§1](#1-what-it-is-and-how-to-run-it) |
| To generate a client | [§2](#2-the-openapi-document-and-how-to-use-it) |
| To not be surprised | **[§3](#3-things-that-will-surprise-you)** — read this one |
| To know what is actually proven | [§4](#4-tested-expected-and-the-difference) |
| To know what is yours | **[§5](#5-your-responsibilities-not-this-services)** |

**Where everything else is.** Running and deploying this build — mounts, the
container, the boot gates, persistence — is `claude-python-operations.md` in this
directory. Every other claim, the reasoning per source location and the measured
evidence, is in one file, `claude-python-references.md`, also here. It has 143
numbered entries and the code cites those numbers; **a `CP-nnn` below is one of
them**.

**There is no `README.md` for this build as of 2026-08-11.** It mixed the
operator, the client author and the maintainer in one file, and rotted where the
tree moved under it. Its operator half became the operations document, its
client-facing half is in §3 here, and its maintainer half is in `CLAUDE.md`
beside the code.

---

## 1. What it is, and how to run it

An HTTP wrapper over the **Claude Agent SDK**, shipped as a container. One
process, one workspace, sessions that hold a CLI subprocess each.

```bash
docker compose up -d --build --wait     # needs WORKSPACE_HOST_PATH + REFERENCE_HOST_PATH
curl -s localhost:8000/v1/deployment
```

**It refuses to boot rather than start wrong**, and every refusal is `exit 3`
with a message naming the remedy:

| Gate | Fires when |
|---|---|
| Credentials | no `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` |
| Mounts | the workspace is not on a real mount |
| Schema revision | persistence is configured and the database is at a different Alembic revision, **in either direction** |

**`exit 3` is not a crash and an orchestrator can tell the difference.** Do not
add a restart loop around a configuration error; it will loop forever.

**Read the pre-boot facts before booting — from the specification, not from a
container.** They are published in this build's own OpenAPI document:

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
`GET /v1/deployment`.

**This was the `agent-service-spec` command until 0.19.0**, which a
provisioner had to run against an image. The command is gone: it put a runtime
dependency in front of a question asked at build time.

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

**Mounts, `docker run`, limits and persistence are in
`claude-python-operations.md`.** This document assumes something is already
running.

### The surface, at a glance

Orientation only — **`/openapi.json` is the contract** and §2 is how to use it.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/query` | Run to completion; returns the result plus every message |
| `POST` | `/v1/query/stream` | Same, as Server-Sent Events |
| `POST` | `/v1/sessions` | Open a multi-turn session |
| `GET` | `/v1/sessions` | List live sessions |
| `GET` | `/v1/sessions/{sid}` | Session detail, including context-window usage and `last_turn` |
| `PATCH` | `/v1/sessions/{sid}` | Change model or permission mode mid-session |
| `DELETE` | `/v1/sessions/{sid}` | Close a session and free its subprocess |
| `POST` | `/v1/sessions/{sid}/messages` | Send one turn, wait for the result |
| `POST` | `/v1/sessions/{sid}/messages/stream` | Send one turn, stream it |
| `POST` | `/v1/sessions/{sid}/interrupt` | Ask a running turn to stop |
| `GET` | `/v1/deployment` | Resolved defaults, vocabularies, and what this build *requires* |
| `GET` | `/healthz` | Liveness, plus a live report on credentials and the database |

With persistence configured, `GET /v1/sessions/{sid}/transcript` (paginated) and
`GET /v1/runs/{run_id}` read the record back. **Continue a conversation by passing
`options.resume` the `sdk_session_id`**, not the service-side `session_id` — §3.3.

## 2. The OpenAPI document, and how to use it

**The service serves exactly the document published for its version and
implementation** — `spec/openapi/claude-python-<version>.json`.
Byte for byte. That is AS-24, and the conformance suite checks it against a
running container on every CI run.

**So generate your client from the published file, not from a running service.**
They are the same bytes, and the published one is the artifact with a hash and a
manifest row behind it.

**Three things about it that are easy to get wrong:**

- **`info.version` is the DOCUMENT's version, not the build's.** Read
  `deployment.service.impl.version` for the build and `deployment.service.spec.document_version`
  for the contract. They are different streams and they diverge.
- **The document is per-implementation since 0.19.0.** A second build serves a
  document that differs from this one — in **prose only**, guaranteed by AS-31
  against a published `core-<version>.json`. Every path, method, `operationId`,
  parameter, request body, component schema and shared response schema is
  identical across builds.
- **Never branch on which image you have.** Anything a client must act on is on
  `GET /v1/deployment` (AS-32). If you find yourself diffing two documents or
  checking an image tag, that is a defect on this side and worth reporting.

**Read these capabilities before your first request**, because they change what
a correct client does:

| Field | Why |
|---|---|
| `unsupported_options` | `RunOptions` fields this deployment refuses with 400. `[{field, types?}]`; `types` absent means the whole field |
| `mcp` | which MCP transports and header shapes this build can express, and — in `tool_call` — what bounds a tool call that runs for minutes. See §3.8 |
| `sandbox` | what confines the agent's own tools — see §3 |
| `allow_supplied_sdk_session_id` | whether you may supply your own conversation id |
| `setting_sources`, `permission_modes`, `effort_levels` | the vocabularies this build honours |
| `limits` | figures this build **enforces**. A number here is a promise about behaviour, not a configuration dump |

**Errors are RFC 7807 problem documents** with `content-type:
application/problem+json` — including the ones the framework produces, like a
404 for an unknown path or a 422 from validation. Where two errors share a
status and mean different things, they carry a distinct `type` URI. **Branch on
`type` and `status`, never on `title` or `detail`**: those are prose and prose is
allowed to change.

**A 422 names the fields and never the values.** `errors` is an array of
`{loc, msg, type}`: `loc` is the path to what was rejected
(`["body", "options", "permission_mode"]`) and is the part to act on, `type` is
the machine-readable failure kind and is what to branch on, `msg` is prose and
may change. **`input` is deliberately absent** — the framework's own error echoes
the offending value, a malformed body can carry your MCP bearer token, and an
error body is the thing most likely to be logged by whatever sits in front.


### 2.1 The payload a client reads first is FOUR GROUPS, at a new route

**`GET /v1/deployment`, renamed from `/v1/capabilities` on 2026-09-03**, and the
old route is gone rather than redirected. Half of what it carried was never a
capability -- `workspace_dir` and `max_sessions` are configuration -- and the
name misled accordingly.

| Group | Answers | Examples |
|---|---|---|
| `service` | who is answering | `spec.document_version`, `impl.version`, `sdk` |
| `config` | how THIS instance is set up | `workspace_dir`, `default_model`, `max_sessions`, `auth_required` |
| `accepts` | what you may send | `permission_modes`, `unsupported_options`, `limits` (ceilings) |
| `behaviour` | what it does and reports | `sandbox`, `model_usage_scope`, `mcp_tool_call`, `limits` (enforced) |

**Two objects were cut along that line.** `limits` used to mix ceilings on your
request with figures the service enforces on its own -- read `accepts.limits`
before sending a number and `behaviour.limits` when planning around one. The MCP
tool-call timers left `mcp` for `behaviour.mcp_tool_call`, because they bound how
long your server may take rather than what you may configure.

**`accepts` is also served as a JSON Schema**, at `GET /v1/schemas/run-options`:
the published `RunOptions` already narrowed by this deployment, self-contained,
`application/schema+json`. Validate a request against it, or feed it to a form
renderer, instead of reimplementing the narrowing. The two shapes are checked
against each other by the conformance suite, so they cannot drift.

## 3. Things that will surprise you

**This section is the reason the document exists.** Everything here is
deliberate, measured, and has bitten somebody.

### 3.1 The agent's shell is not confined

`deployment.behaviour.sandbox` reports `network_access: true` and
`confines_writes_to_workspace: false`, and both are honest rather than
flattering. **The agent's `Bash` tool is unconfined**: the container and its
mount split are the only boundary. It can reach the network and it can write
outside the workspace.

**`permission_enforcement` defaults to `"none"`**, which means exactly what it
says: no in-process control is applied, and the container is the enforcement.
`permission_mode` is passed to the SDK, and the measured behaviour is that
`can_use_tool` never fires under the configurations this service uses — five
live probes (CP-066).

**All three implementations publish `permission_enforcement: "none"`, and it
means something different on each.** The field answers one question — does the
service inspect each tool call in-process before it runs — so a build confined by
a sandbox, and a build confined by a tool policy its agent loads at session open,
both answer `"none"` exactly as this one does. **Do not read the three as
equivalent.** This build's `"none"` is the least confined of them: its default
tool list includes a shell. The Codex build sandboxes each turn and reports
`sandbox.confines_writes_to_workspace: true` with no network; the Gemini build
refuses `run_shell_command` whatever the caller asks for. Read
`always_disallowed_tools`, `default_allowed_tools` and the `sandbox` pair beside
this field — that is where the difference is visible.

**So do not expose this beyond localhost.** The controls have an order —
network isolation first, then a relay, then authentication (CP-133) — and the
first two are yours rather than work in this repository.

### 3.2 Cost is a floor, not a total

- **`total_cost_usd` is cumulative for the connection**, not per turn. Summing
  it across turns multiplies the real figure.
- **An interrupted turn does not move it.** A caller that can interrupt can
  spend without limit under any `max_budget_usd`. That option is **not a spend
  cap** and its own description says so.
- **`null` means this build could not price it**, never *free*. A zero-turn
  session reports `null`; `turns` in the same response tells you whether that
  means "nothing ran" or "this build cannot price at all".
- `turn_cost_usd` is the differenced per-turn figure and is the one you usually
  want.

**A UI showing `total_cost_usd` as "cost" next to an interrupt button will
mislead its user.**

### 3.3 Two identifiers, and they are not interchangeable

`session_id` is this service's path handle. `sdk_session_id` is the SDK's
conversation id. **Feeding one where the other belongs is a 404**, measured.

- `options.resume` takes the **SDK** id.
- `x-sdk-session-id` on a response is the SDK id, so a relay can route without
  parsing the body.
- On this build `sdk_session_id` is **null until the first turn** — the CLI does
  not mint it earlier. `null` means *not known yet*, never *not told*.

### 3.4 Interrupt and streaming behave in ways that look like bugs

- **`POST .../interrupt` returns 200 with a body, never 204 and never 409.**
  `interrupted` says whether a control request actually went out, which is not
  the same as the session being busy.
- **Interrupting nothing is not an error.** A turn can end between your decision
  and the call arriving.
- **An interrupted turn returns `result: ""`, not null.** That is what the SDK
  returns and this service passes it through unaltered; `interrupted: true` is
  the discriminator.
- **The two streaming routes differ on a first-advance failure.**
  `/v1/query/stream` returns 200 with an in-band `event: error`; the session
  stream returns a real 504. The one-shot commits its response before the first
  message exists and cannot do otherwise.

### 3.5 The session lifecycle answers with status codes, not flags

**A session holds one live agent subprocess**, so context carries across turns —
turn 2 can refer to what turn 1 read without reading it again. That has costs a
client has to handle:

| Situation | You get |
|---|---|
| more than `max_sessions` open at once | **429** — `GET /v1/sessions` is the numerator, `deployment.config.max_sessions` the denominator |
| a second concurrent turn on one session | **409**, never a queue — the SDK would otherwise accept it silently and two callers could receive each other's turns |
| a turn exceeding `timeout_s` (default 600 s) | **504**, not a 200 with a flag. It bounds each turn, not the session's lifetime |
| `PATCH` after the session is closed | **409**, except an empty `PATCH {}`, which touches nothing and stays 200 |
| a run stopped by `max_turns` or `max_budget_usd` | **200** — check `limit_hit`, which is `"turns"` or `"budget"` |

**Idle sessions are closed after `AGENT_SERVICE_SESSION_IDLE_TTL_S`** (default
1800 s). `DELETE` when you are done rather than relying on it.

**Read `outcome_recorded` before reading `result` or any cost field.** `false`
means the message stream ended without a terminating result — the agent process
crashed or exited early — and those fields are *unavailable*, which is not the
same as a run that succeeded and produced no output.

**`GET /v1/sessions/{sid}` reports `last_turn`, and it is how you ask what became
of a turn whose stream dropped.** `turns` and `total_cost_usd` do not move for an
abandoned turn, so without it a session that lost one looks exactly like a session
that never took any. `null` means "never taken a turn"; otherwise it carries
`outcome_recorded`, `interrupted`, `timed_out`, `sdk_session_id` and that turn's
`turn_cost_usd`. **It is a record of what happened, not a replay** — no result
text, no events.

**`last_residue_discarded` counts messages dropped before the last turn started.**
Non-zero means an earlier turn was abandoned with output still in flight, and
those messages were discarded so they could not be read as the new turn's own.

**`PATCH` echoes only `model` and `permission_mode`, and they are the read-back** —
what the SDK actually took, not what you asked for. Omitted fields are never
forwarded, because the SDK reads a null model as "use the default" and forwarding
one would silently reset it.

**Single worker only.** The session registry lives in process memory; more than
one uvicorn worker routes follow-up turns to a process that has never heard of the
session.

### 3.6 Supplying your own conversation id, if the build allows it

`POST /v1/sessions` accepts a caller-supplied `session_id` (a UUID) and returns it
as `sdk_session_id` on the 201 — **so the mapping exists before the session makes
its first model call**, rather than being null until the first turn. Check
`deployment.accepts.allow_supplied_sdk_session_id` first.

**It is rejected with 400** when it is not a UUID, or when it is sent together
with `options.resume`. The id must be unused: the CLI refuses one that already has
a transcript in that workspace.

**Both turn endpoints also return the id as an `x-sdk-session-id` response
header**, so a proxy or relay recovers it without parsing a body or scanning an
SSE stream. It is the same string the CLI sends the model API as
`x-claude-code-session-id` (measured), which is what makes it usable for joining
gateway traffic to a session. Present on the first turn including streaming;
absent only when no id was ever seen. There is no counterpart on
`/v1/query/stream`, which commits its 200 before the first message arrives.

### 3.7 Disconnecting kills the turn

A dropped consumer connection interrupts the run. That is deliberate — it is
what stops one caller's messages ending another caller's turn — and it means
**a browser is not a safe direct client**: page reload, laptop sleep, a
backgrounded tab. Put something durable in front of it.

### 3.8 A long MCP tool call is bounded three ways, and only one of them forgives you

If your MCP tool answers in a second this does not concern you. If it waits on a
human, another agent or a queue, read `mcp.tool_call` before you write it
(`CP-149`). Three timers, and a server clears each by different means:

| | Here | Cleared by |
|---|---|---|
| `request_timeout_s` | **60 s** | **responding.** SSE headers stop this clock; a buffered single JSON body does not |
| `idle_timeout_s` | **300 s** | a frame that counts — see below |
| `total_timeout_s` | **100000 s** | **nothing.** It expires while the call is healthy |

**An SSE comment is not a frame that counts.** The CLI's own error names what is:
*no response or progress*. So a keepalive-only stream looks perfectly healthy on
the wire and dies at exactly five minutes. `mcp.tool_call.progress_resets_idle`
is `true` here, and `notifications/progress` is what it means.

**So the recipe is: open the stream at once, then emit progress well inside
300 s.** That clears all three, and 100000 s is not a ceiling anybody reaches.

**Published as the strictest transport.** `idle_timeout_s` is 300 for `sse` and
`http`; a `stdio` server actually gets 1800 s. The published figure is never more
generous than any transport this build lists, so planning against 300 is safe on
all of them.

**The values are yours to read and not to set.** `McpServer` carries no `timeout`
field, and the two environment variables the agent honours are the operator's
surface — this service sets neither.

### 3.9 You can switch ambient configuration OFF, and you cannot send it

`setting_sources` decides which on-disk configuration the agent loads inside the
container: `user` is `~/.claude/settings.json` there, `project` is
`<workspace>/.claude/settings.json`, `local` is `.claude/settings.local.json`.
**The server default is `[]` — none — and this service always sends the field
explicitly**, which is measured to work: a `CLAUDE.md` in the workspace reached
the model under `["project"]` and did not under `[]` (`CP-060`).

**Enabling a source is not just settings keys.** It brings that layer's whole
ambient configuration — `CLAUDE.md` memory, skills, subagents, slash commands,
plugins. And the workspace is mounted from your host and **writable by the
agent**, so `project` and `local` trust whatever a previous turn or another
committer put there.

**Nothing in `RunOptions` can SUPPLY any of it.** There is no field for a memory
file, a skill, a subagent, a command or a plugin, and `system_prompt` is not a
substitute: its string form replaces Claude Code's own prompt, and the preset
object appends to it, but neither registers a skill or becomes memory. What this
build gives you that the other two do not is the ability to say, in the request,
that the agent will read **none** of it. The comparison is in the platform's
`capability-divergence.md`, §3.1.

## 4. Tested, expected, and the difference

**This codebase distinguishes the two everywhere and you should read it that
way.** A claim is either measured by a probe or read from the installed SDK
source; where it is neither, the text says so.

| | |
|---|---|
| **Proven on every CI run** | the boot gates against a real image, the whole HTTP surface against a running container, AS-24 byte equality, AS-31 structural identity to the core, and the negative control — a real `0.2.0` document that must fail |
| **Proven with real turns, deliberately** | the `x-sdk-session-id` header on a first streaming turn, SSE framing with a terminal `done`, cost typing, the session record agreeing with its own last turn, and AS-34 |
| **Measured once and written down** | the references file, entry by entry: what the SDK does with ids (CP-071), what an interrupt costs (CP-070), whether an MCP secret is readable by the agent — **it is**, CP-075, and see §5 |
| **Expected but NOT measured** | anything the documents mark as such. They are marked because the distinction has been wrong before |

**The suite that matters to you is `spec/conformance/`**, which imports nothing
from this implementation and talks only HTTP. If you want to know whether a
clause holds for the container you are running, point it at your own URL.

## 5. Your responsibilities, not this service's

**1. The credential is yours to scope.** The agent runs as a process this
service starts, with `Bash`, and it can read the environment. **Any secret this
container holds is readable by the agent** — including an MCP secret you inject
and including the bearer token protecting `/v1`. Measured (CP-075): the whole
MCP configuration reaches the CLI as one argv. **Use a per-instance token and a
scoped key.**

**2. Network isolation is yours.** §3.1 — this service confines nothing inside
the container. If the agent must not reach your internal network, that is a
network policy, not a setting here.

**3. Authentication is optional and off by default.** `AGENT_SERVICE_AUTH_TOKEN`
enables bearer auth on `/v1`; `AGENT_SERVICE_REQUIRE_AUTH` refuses to boot
without one. It authenticates *the caller to this instance* and is **not an
identity** — this service does not know which user is behind a request and
nothing is scoped by the token.

**4. Prompt injection arrives through an authorised call.** No control here
reduces it. A tool result may contain attacker-influenced file contents, and the
console rendering agent output is a second-order vector.

**5. Migrating the database is yours, and the container will not do it.** The
image ships no migration tree on purpose. Apply the published DDL or the Alembic
tree out of band; a mismatch is `exit 3` in either direction.

**6. Keeping `sdk_session_id` is yours if you want continuity.** Without a
database, the `201` is the only place it appears.

**7. Reading `/v1/deployment` is yours.** Every difference between builds and
deployments is published there. A client that assumes instead of reading is the
failure AS-32 exists to prevent.
