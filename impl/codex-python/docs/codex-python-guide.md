# `codex-python` — the guide for someone integrating against it

**Read this before writing a client, and read §3 before deploying one.** This
build satisfies the same specification as `claude-python` and differs from it in
ways a client must act on — every one of them published on
`GET /v1/capabilities`, and every one of them measured rather than assumed.

**A condition of every non-snapshot release** (user, 2026-08-09). A build that
ships without this document is a build whose consumer has to read its source.

| You want | Go to |
|---|---|
| To run it | [§1](#1-what-it-is-and-how-to-run-it) — **it needs one unusual container flag** |
| To generate a client | [§2](#2-the-openapi-document-and-how-to-use-it) |
| To not be surprised | **[§3](#3-things-that-will-surprise-you)** |
| To know how it differs from the Claude build | [§4](#4-how-this-build-differs-and-where-to-read-it-at-runtime) |
| To know what is actually proven | [§5](#5-tested-expected-and-the-difference) |
| To know what is yours | **[§6](#6-your-responsibilities-not-this-services)** |

**What it is built on, and what it is NOT.** The target is the **OpenAI Codex
SDK for Python** — the *local coding agent*, peer of `claude-agent-sdk`:

- <https://learn.chatgpt.com/docs/codex-sdk>
- <https://github.com/openai/codex/tree/main/sdk>

**Not the OpenAI Agents SDK** (<https://openai.github.io/openai-agents-python/>),
which is a generic framework where the caller defines every tool and which ships
no coding agent at all. The distinction decides what this service can offer: an
agent that already knows how to read, edit and run code in a workspace.

**One other document, beside this one.** `codex-python-references.md` carries
every measurement with its controls, every clause this build cannot satisfy and
why, the API survey and the container. Its entries are numbered and the code
cites those numbers; **a `CX-nn` below is one of them.** This guide stays beside
the code because it is the one a consumer reads first.

---

## 1. What it is, and how to run it

An HTTP wrapper over the **OpenAI Codex SDK**, shipped as a container. Each
session is one `codex app-server` subprocess speaking JSON-RPC over stdio — not
a daemon and not a network listener.

### 1.1 It needs `seccomp=unconfined`, and that is not optional

```yaml
security_opt:
  - no-new-privileges:true
  - seccomp=unconfined      # <- without this the agent has no working shell
cap_drop:
  - ALL
```

**Codex's sandbox is bubblewrap, which needs a user namespace, and Docker's
default seccomp profile refuses one to a process without `CAP_SYS_ADMIN`.**
Without the flag the sandbox cannot start and **every shell command the agent
runs fails** with `bwrap: No permissions to create a new namespace` — fail
closed, so nothing runs unsandboxed, but nothing runs at all.

**`cap_drop: ALL` is not the cause** and dropping fewer capabilities does not
help: the same failure occurs under default Docker security. `cap_add:
SYS_ADMIN` is the reflex fix and **does not work** — it is both weaker and more
dangerous. Measured (CX-01).

### 1.2 Boot gates

Credentials (`OPENAI_API_KEY` / `CODEX_API_KEY`), mounts, and the schema
revision — all `exit 3` with a message naming the remedy, same as the other
build. The pre-boot facts — credential variables, `endpoint_source`,
`ca_bundle_source`, the schema revision and the listen address — are published
in this build's own OpenAPI document as `components.schemas.PrebootSpec`, each
pinned with `const`, so no container has to be started to read them. They were
an `agent-service-spec` command until 0.19.0.

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

**One caveat this build has and the other does not:** the credential gate cannot
see a login already sitting in `CODEX_HOME`. A deployment reusing an
authenticated volume must start with `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`.

## 2. The OpenAPI document, and how to use it

**This service serves exactly `codex-python-<version>.json`, byte for
byte** — AS-24, checked against a running container on every CI run. Generate
your client from the published file.

**The document is per-implementation and differs from the Claude build's in
prose only.** AS-31 guarantees the structure: every path, method, `operationId`,
parameter, request body, component schema and shared response schema is
identical, checked against a published `core-<version>.json`. The prose differs
because each build describes what it actually does.

**Never branch on the image tag.** Everything a client must act on is on
`GET /v1/capabilities` — §4 is the list for this build.

**Errors are RFC 7807** with `content-type: application/problem+json`, including
framework 404s and 422s. **Branch on `type` and `status`, never on `title` or
`detail`.** The `type` URIs this build sets:

| `type` | Means |
|---|---|
| `…/problems/persistence-disabled` | a history route with no database configured — not "no such session" |
| `…/problems/sdk-session-id-unsupported` | you supplied a conversation id; this build cannot adopt one |
| `…/problems/unsupported-options` | a `RunOptions` field or MCP server this deployment cannot honour |
| `…/problems/resume-target-not-found` | the conversation you asked to resume is gone |
| `…/problems/session-capacity-exhausted` | the **container** is out of process slots — see §3.5 |

**A 422 names the fields and never the values.** `errors` is an array of
`{loc, msg, type}`: `loc` is the path to what was rejected
(`["body", "options", "permission_mode"]`) and is the part to act on, `type` is
the machine-readable failure kind and is what to branch on, `msg` is prose and
may change. **`input` is deliberately absent** — the framework's own error echoes
the offending value, a malformed body can carry your MCP bearer token, and an
error body is the thing most likely to be logged by whatever sits in front.

## 3. Things that will surprise you

### 3.1 The agent cannot reach the network — and that is the opposite of the other build

`capabilities.sandbox` reports `network_access: false` and
`confines_writes_to_workspace: true`. **The agent's shell cannot open a socket
at all**: no package install, no `curl`, no API call from a command. Measured in
every permission mode, with the container itself returning `HTTP:200` as the
control.

**The Claude build is the mirror image** — `true`/`false`, an unconfined shell
with the container as the only boundary. **The same Agent behaves differently on
the two builds**, which is why the field exists. Read it; do not assume.

### 3.2 Every permission mode refuses escalation, and `plan` really is read-only

All six `permission_mode` values map to `ApprovalMode.deny_all`, and the sandbox
does the whole job. `plan` and `default` are read-only; the rest permit writes
inside the workspace and refuse everything outside it.

**This was not true before 2026-08-09**, and the reason is worth knowing because
it explains why the mapping looks blunt: three modes used an approval mode whose
reviewer was **the model itself**, so `plan` was read-only until the agent
decided otherwise. Measured — it asked "Proceed?" and approved itself 300 ms
later (CX-17).

### 3.3 Cost is always `null`, and that is not a bug

**This build cannot price a turn.** The SDK reports no monetary figure at all,
so `total_cost_usd` is `null` on every session and every turn, forever.

`null` means *this build cannot report it*, never *free*. `turns` in the same
response disambiguates: `turns: 0` with `null` is "nothing ran"; `turns: 3` with
`null` is "this build does not price". **`max_budget_usd` is refused with a 400**
rather than accepted and ignored — a budget cannot be enforced against a number
that does not exist.

Token counts **are** reported: `token_usage` carries input, output, cache-read
and reasoning counts. `cache_write_tokens` is `null` because Codex has no such
counter, which means a cache write is a charge this API cannot show you.

### 3.4 `sdk_session_id` exists at creation, which the specification did not expect

Codex mints the thread id at `thread_start()`, so the `201` already carries it —
where the Claude build reports `null` until the first turn. AS-15 says `null`
means *not known yet*, and this build knows.

Two consequences: **`POST /v1/query` sends the `x-sdk-session-id` header** here
and not on the other build (`query_reports_sdk_session_id`), and **`/v1/query`
consumes a session slot** and can answer 429 (`query_consumes_a_session_slot`).

**A caller-supplied `sdk_session_id` is refused with 400.** The SDK offers no way
to set it, and accepting the field while returning a different id would break the
one guarantee supplying it provides. `allow_supplied_sdk_session_id` is `false`;
read it before sending one.

### 3.5 `max_sessions` is not the cap that binds

Measured on the shipped container: **~20 MiB and ~30 processes per session.**

| sessions | 0 | 4 | 8 | 12 | 16 |
|---|---|---|---|---|---|
| memory | 52 | 172 | 240 | 320 | 402 MiB / 2048 |
| pids | 2 | 135 | 246 | 357 | **485 / 512** |

**`pids_limit` binds long before `mem_limit`** — at 16 sessions memory is 20% of
its budget and processes are at 95% of theirs. So a container carries about **16
sessions**, whatever `max_sessions` says, and the two are configured
independently.

Exceeding it answers **503 `…/problems/session-capacity-exhausted`**, which is
retryable: closing a session clears it. **A 429 means you asked for more than
`max_sessions`; a 503 means the deployment is out of room.** Do not conflate
them.

### 3.6 The default model changed, and codex-family models may not answer

**`default_model` is `gpt-5.1` as of 2026-08-10.** It was `gpt-5-codex`, and on
the key this was measured with — twice, a day apart — **every codex-family model
returns 404 from `/v1/responses`** while `gpt-5.1`, `gpt-5-mini` and
`gpt-4.1-mini` answer 200. All of them appear in `GET /v1/models`, so listing
proves nothing.

Read the value from `capabilities.default_model` rather than assuming either
one.

**If your key is entitled to codex models, name one** — `options.model` per
request, or `AGENT_SERVICE_DEFAULT_MODEL` for the deployment. Nothing here says
`gpt-5.1` is the better model for coding work; it is the one measured to
respond.

**A model this endpoint will not serve is not a 400.** The turn takes about
**30 s** — the app-server retries the 404 five times, twice — and comes back
`is_error: true`, `outcome_recorded: true`, with the 404 and the model's name in
`terminal_reason`.

### 3.7 Resume needs the volume, and the session list will look empty

A conversation survives a container restart **only if `CODEX_HOME` is on a
volume** — that is where the rollout lives. Measured: restart with the volume
kept and `options.resume` continues the conversation; destroy the volume and the
same request is a 400.

**`GET /v1/sessions` is empty after a restart and that is correct.** The registry
is in memory; `session_id` is this process's handle. The conversation is
`sdk_session_id`, and **keeping it is yours** — without a database the `201` was
the only place it appeared.

### 3.8 `permission_enforcement: "none"` here does not mean unconfined

**All three implementations publish `"none"`, and it means something different on
each.** The field answers one question: does the service inspect each tool call
in-process before it runs. This build does not — **the sandbox does**, which is a
stronger boundary than an in-process check would be, and it still reports
`"none"`.

So the value cannot be compared across builds on its own. What separates them is
published beside it: this build reports `sandbox.confines_writes_to_workspace:
true` and `network_access: false`, which neither of the others does. The Claude
build reports `none` with a shell in its default tool list and the container as
the only boundary. The Gemini build reports `none` with a tool policy its agent
loads when the session opens, and refuses `run_shell_command` whatever the caller
asks for.

**Read `always_disallowed_tools`, `default_allowed_tools` and the `sandbox` pair
together** — that is where the difference is legible, and this field alone will
tell you the three are the same when they are not.

## 4. How this build differs, and where to read it at runtime

**Every row is a published capability. None of it requires knowing which image
you have.**

| Capability | Here | Claude build |
|---|---|---|
| `sandbox.network_access` | `false` | `true` |
| `sandbox.confines_writes_to_workspace` | `true` | `false` |
| `allow_supplied_sdk_session_id` | `false` | `true` |
| `query_reports_sdk_session_id` | `true` | `false` |
| `query_consumes_a_session_slot` | `true` | `false` |
| `mcp.transports` | `["stdio", "http"]` — **no SSE** | all three |
| `mcp.http_headers` | `"bearer_only"` | `"any"` |
| `mcp.tool_call` | four nulls — **no bound on a tool call** | 60 s to respond, 300 s between frames |
| `setting_sources` | `["user", "project"]` — **no `local`** | all three |
| `unsupported_options` | seven entries | empty |
| `total_cost_usd` | always `null` | a number when the SDK prices it |

### 4.1 MCP

**Works, and was measured end to end**: a session configured with a stdio server
takes a turn and the tool's output reaches the model. Two limits:

- **No `sse`.** Codex has streamable HTTP and no SSE transport. An `sse` server
  is a 400 naming the transport.
- **`http` carries a bearer token and no other header.** An `Authorization:
  Bearer …` is forwarded; anything else is a 400 naming the header. The token
  travels in the app-server's environment rather than its argv — which keeps it
  out of the process table and **not** out of the agent's reach.

An MCP tool call is an escalation, and this service is the approver: it approves
calls to servers **this caller configured** and denies everything else. It is
asked about MCP tool calls only — never shell commands or file changes, which
stay under the sandbox.

**Nothing here abandons a tool call.** All four values of `mcp.tool_call` are
`null` (`CX-60`), and that is *no bound* rather than *not measured*: the agent's
resolved server config carries `tool_timeout_sec: null`, and the binary has no
tool-call timeout message at all — the only MCP timeout it can raise names the
handshake. So a tool that waits on a human or on a queue is not cut off by this
build, and that is the most permissive of the three.

**It is still a statement about this client and not about the world.** A proxy,
a load balancer or a kernel between this container and your server is free to
give up, and this build reports that as a transport failure rather than as a
timeout. **The bound you actually control is the request's own `timeout_s`**,
capped by `limits.max_allowed_timeout_s` — 1800 s here.

### 4.2 `setting_sources`

`user` is always on and not selectable. **`project` is selectable** and controls
whether the agent reads the project document (`AGENTS.md`) from the
workspace — measured. `local` has no equivalent and is refused **by value** with
a 400 naming it, which is why `unsupported_options` does not name the field: the
field is honoured, one of its members is not.

**It is a SWITCH, and there is no field that SENDS ambient configuration.** No
request can put a project document, a custom prompt or a profile into this
container: `AGENTS.md` comes from the workspace you mounted and everything else
from `CODEX_HOME`, which is read whatever you send. `system_prompt` is not the
missing lever either — its string form **replaces** the agent's own framing via
`base_instructions` and suppresses nothing on disk. So the container's disk is
part of the deployment, not part of the request; provision the workspace
deliberately. The three builds are compared in the platform's
`capability-divergence.md`, §3.1, and this build sits in the middle of them:
`claude-python` can switch its ambient input off entirely, `gemini-python` has
no switch at all.

## 5. Tested, expected, and the difference

| | |
|---|---|
| **Proven on every CI run** | boot gates against a real image, the whole HTTP surface against a running container with and without a database, AS-24, AS-31, and the negative control |
| **Proven with real turns** | the paid conformance tier, 7 of 7; MCP end to end; the sandbox's filesystem and network confinement; resume across a restart; the project-doc switch |
| **Measured once, with a control, and written down** | the references file, entry by entry. **Every negative result there has a control**, because "the command failed" and "the command was blocked" look identical without one |
| **NOT measured** | whether §3.6 is this key or every key. Nothing else load-bearing |

**Two things this build got right that are worth trusting.** A failed turn is
reported honestly — HTTP 200 with `is_error: true` and the upstream message in
`terminal_reason`, nothing swallowed. And the sandbox failure in §1.1 is **fail
closed**: when bubblewrap cannot start, the command does not run, rather than
falling back to running unsandboxed.

## 6. Your responsibilities, not this service's

**1. Set `seccomp=unconfined` or accept an agent with no shell.** §1.1. This is
the one thing most likely to make a working deployment look broken.

**2. Decide whether that trade is acceptable to you.** It exchanges Docker's
syscall filter for the agent's own sandbox. The reasoning is in
CX-01 — the short version is that the hardened alternative is
not safer, it is non-functional.

**3. Any secret this container holds is readable by the agent.** An MCP bearer
token is in the app-server's environment, and the agent runs as the same user.
Out of the process table is not out of reach. **Scope the credential and use a
per-instance auth token.**

**4. Size the container by processes, not memory.** §3.5. If you raise
`max_sessions`, raise `pids_limit` with it — roughly 30 per session — or the cap
you advertise is not the cap you have.

**5. Mount `CODEX_HOME` on a volume if conversations must outlive the
container**, and keep `sdk_session_id` yourself. §3.7.

**6. Migrating the database is yours.** The image ships no migration tree; a
revision mismatch is `exit 3` in either direction.

**7. Read `/v1/capabilities` rather than assuming.** §4 is a table of ten
differences from the other build, all published. A client that assumes is the
failure AS-32 exists to prevent — and on this build it will be wrong ten times.
