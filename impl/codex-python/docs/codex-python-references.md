# `codex-python` — references

**The one document this build's code cites, and it cites it by ID.** A comment
says `(CX-07)` and nothing else: no path, no heading, no section number.

**Why.** 170 code citations in this repository pointed at 14 documents; 50 were
unusable one hour after a directory move and nothing in CI noticed. 49 of them
depended on heading text nobody verified. An ID does not rot, and a document
that cannot be linked to cannot be linked *wrongly*.

## The rules

1. **Code cites this file, by ID, and nothing else.** Not the todo, not the
   plans, not another build's document. A temp document is never a citation
   target: it is written to be superseded and code outlives it.
2. **This file links to nothing.** Where an outside document is worth naming, it
   is named in prose and anything load-bearing is restated here. That is the
   rule the outbox already keeps, generalised.
3. **Each entry is complete.** Somebody holding only this file can act
   correctly.
4. **The comment stays short.** A sentence that changes what a maintainer does
   stays in the code; everything behind it lives here.
5. **An ID is permanent.** Superseded entries are struck through and kept, never
   renumbered — a stale ID in old code must still resolve.

**Every claim is measured unless it says otherwise**, and where a measurement
has a control, the control is stated: *the command failed* and *the command was
blocked* look identical without one.

**This file absorbed four documents on 2026-08-10** — the measurements, the
divergences, the SDK survey and the container notes. They no longer exist
separately.

---

# A. The SDK, and what it is

## CX-26 — the app-server is a subprocess, not a daemon

`app-server --listen stdio://`, spawned as a child with pipes. **No port, no
daemon, no network listener** — structurally identical to the Claude build
spawning its bundled CLI, so the container model, the security posture and the
lifecycle carry over unchanged and nothing new is exposed.

`CodexConfig` carries the levers this service needs: `codex_bin`, `cwd`, `env`,
`launch_args_override`, `config_overrides`.

## CX-27 — streaming is the primitive; `run()` is sugar

`TurnHandle.stream()` is the primitive and `run()` is `stream()` collected, with
a full async variant. The README implied the reverse by showing only
`thread.run(prompt)`, and that doubt was the only argument for a TypeScript
port. **It does not exist**, which is why this build is Python.

`TurnHandle.interrupt()` maps straight onto the interrupt route.
`TurnHandle.steer()` sends additional input to an active turn and **this service
has no equivalent and no clause covering it**.

## CX-28 — the package is `openai-codex`, and a lookalike exists on PyPI

Import `openai_codex`, published from `github.com/openai/codex`. **`openai-codex-sdk`
is NOT official** — a third party whose PyPI page lists *OpenAI* as author, a
self-declared field that proves nothing. `codex-sdk-py` and `acodex` are also
third party.

It bundles a CLI binary (`openai-codex-cli-bin`, pinned `0.144.4`), the same
shape as the Claude SDK, so the build guard against a silently-empty bundle
applies here too.

## CX-29 — there is no monetary figure anywhere in the SDK

`TurnResult` carries `usage: ThreadTokenUsage | None` — `last` and `total`
breakdowns plus `model_context_window` — and **`grep -ri "usd\|cost"` over the
whole package returns one false positive and nothing else.**

`last`/`total` is per-turn and cumulative, the same distinction the
specification draws between `turn_cost_usd` and `total_cost_usd`.

**This measurement is what justifies the nullable cost field**; it is not an
inference from documentation. See CX-12 for the consequence.

## CX-20 — the app-server does not read the credential from its environment

Measured: it reads neither `OPENAI_API_KEY` nor `CODEX_API_KEY`, even when both
are exported into its process. Without `login_api_key()` its account is `None`
and every turn reaches the API with no `Authorization` header — **a 401 that
looks like a bad key and is not one**, which is why it was believed for a day.

So this service performs the login itself, writing into the auth store under
`CODEX_HOME`. The published credential names work, but through the service
rather than through the SDK. A key the app-server rejects therefore fails at
session open rather than at the first turn, which is one clear failure instead
of a session that exists and can never do anything.

## CX-30 — connecting needs no credential, and that differs from the Claude build

The client starts and `account()` returns `None` with
`requires_openai_auth=True`. Connect is **0.53 s**.

The Claude build cannot start at all without a credential. So
`require_credentials` is genuinely a *policy* here rather than a necessity, and
`/healthz` reporting `credentials_configured` stays the honest live answer.

# B. The sandbox

## CX-01 — the sandbox is bubblewrap, and it needs `seccomp=unconfined`

Codex confines the agent with **bubblewrap**, vendored inside the CLI package
and not on `PATH`. Bubblewrap builds a **user namespace**, and Docker's default
seccomp profile refuses `unshare(CLONE_NEWUSER)` to a process without
`CAP_SYS_ADMIN`.

**Without `seccomp=unconfined` the sandbox cannot start and every shell command
the agent runs dies** with `bwrap: No permissions to create a new namespace`.
Fail closed — nothing runs unsandboxed — but nothing runs.

Measured, one `docker run` per row:

| Container security | Result |
|---|---|
| Docker defaults | ✗ no namespace |
| `--cap-drop ALL` | ✗ same |
| `--security-opt no-new-privileges` | ✗ same |
| `--cap-drop ALL --cap-add SYS_ADMIN` | ✗ further, then `pivot_root: Operation not permitted` |
| **`--cap-drop ALL --security-opt seccomp=unconfined`** | **✓** |
| `--privileged` | ✓ |

**`cap_drop: ALL` is not the cause** and `cap_add: SYS_ADMIN` is the reflex fix
that does not work — weaker *and* more dangerous. Inside the container:
`CapEff: 0`, `NoNewPrivs: 1`, `Seccomp: 2`, and
`/proc/sys/user/max_user_namespaces` is 62835, so the kernel is not the
obstacle.

## CX-02 — the sandbox confines writes to the workspace

`workspace_write` permits writes inside `/workspace` and refuses everything
outside it, measured against `/codex-home`.

**The control is what makes that evidence**: before the turn, as `uid=1000`,
`/codex-home`, `/home/agent` and `/workspace` are all writable. Every target a
probe later failed to write was writable absent the sandbox.

## CX-03 — the sandbox blocks egress in every mode this service can reach

`read_only` and `workspace_write` both prevent the agent's shell from opening a
socket. **Control: `curl` from the container, outside the sandbox, returns
`HTTP:200`** — so the block is the sandbox, not the image, a proxy or DNS.
`sandbox_workspace_write.network_access=true` switches it on; this build leaves
it alone and publishes the fact as `capabilities.sandbox.network_access`.

The generated schema already defaulted it to `false`. **A default in a schema is
a claim about a field, not a measurement of a container** — the distinction a
different config key failed the same day, validating perfectly and changing
nothing.

## CX-63 — the sandbox stops the shell and not the model's web tool, which is ON by default

**CX-03 is exact and it is narrower than it reads.** Measured 2026-09-02 against
image `0.19.0` on `gpt-5-mini`, by `spike/probe_web_search.py`:

| Turn | Config | Result |
|---|---|---|
| search | **no override** | `WebSearchThreadItem`, live quote from a fetched page |
| search | `tools.web_search=true` | indistinguishable from the first |
| fetch a URL | `tools.web_search=true` | opened the URL, returned that page's body text |
| shell `curl` | `tools.web_search=true` | `curl: (6) Could not resolve host` — `HTTP:000` |

**Web search is on with no configuration at all**, so `tools.web_search` is not a
switch this build throws — the first turn sends nothing and still searches. The
binary agrees: `codex features list` reads `search_tool = removed`, so it stopped
being gated rather than staying off.

**Search and fetch are ONE tool.** The action union is
`search | open_page | find_in_page | other`, so `open_page` is the fetch and
there is no second key to look for.

**The evidence for the fetch is a canary the model could not have recalled.** The
probe asked for `example.com`, whose text every model has memorised as
*illustrative examples*; the turn returned *for use in documentation examples
without needing permission*, which is the page's current wording. A memorised
answer would have been the old one.

**The fourth turn is the control and it is why the other three are worth
having**: in the same configuration that had just read two web pages, the shell
could not resolve a hostname. The hosted tool runs on the provider's side and its
result arrives over the app-server's own connection, which is not under
bubblewrap — or no turn could reach the API at all.

**There is no off switch reachable from configuration.** `tools.web_search=false`
changed nothing — both turns under it searched and one fetched. `web_search_mode`
accepted the value `"__probe__"` without complaint, so it is not an enum this
path enforces; the binary carries `allowed_web_search_modes` inside a
requirements struct beside `allow_managed_hooks_only` and `allow_remote_control`,
which is managed policy decided somewhere other than a `-c` override.

**So `capabilities.sandbox.network_access: false` must not be read as *this build
cannot reach the web*.** It says the sandboxed shell has no socket, which is
true; a turn still has an outbound channel with model-chosen URLs and query
strings, and nothing in this service inspects it.

**Untested, and named rather than assumed**: whether pointing the endpoint at a
provider that does not offer the hosted tool removes it.
`modelProvider/capabilities/read` answered `webSearch: true` in both
configurations, and that is the provider's answer rather than this container's.

# C. Approvals

## CX-04 — an approval mode with no approver is self-approval

`ApprovalMode.auto_review` means *ask for approval*, and `/v1` has no approval
channel — no callback, no prompt, no `can_use_tool` hook. The only reviewer
available is the model, reviewing its own request.

**Measured**: under `read_only` + `auto_review` the agent said *"I need your
approval to write to /workspace. Proceed?"*, and 300 ms later an
`item/autoApprovalReview` with `decision_source: "agent"` recorded *"Auto-review
returned a low-risk allow decision."* Exit 0, and the file landed on the host
bind mount. **`plan` was not read-only; it was read-only until the agent decided
otherwise.**

**Every `permission_mode` maps to `deny_all`.** The sandbox is the only axis, and
a test fails if `auto_review` ever returns.

The visible cost is that `acceptEdits` and `dontAsk` resolve to the same pair.
They only ever differed by a review nobody performed.

## CX-05 — `deny_all` denies the escalation, not the work

A `workspace_write` + `deny_all` session writes inside the workspace normally and
is refused outside it. Measured, because a fix that denied everything would be
no better than the defect it replaced.

## CX-06 — this service is the approver for MCP tool calls, and asks about nothing else

An MCP tool call is an **escalation**, so `deny_all` denies every one, and the
SDK's public `ApprovalMode` offers only *deny everything* or *let the model
decide*.

The third option is `ApprovalsReviewer.user`, which routes the request to the
**host**. The policy is **granular** — `mcp_elicitations` only — so shell
commands and file changes never escalate and stay under the sandbox. **This
narrows what can escalate; it does not widen it.**

The request arrives as **`mcpServer/elicitation/request`**, carrying
`serverName`, `tool_params` and `_meta.codex_approval_kind: "mcp_tool_call"`.
Its reply is MCP's own elicitation shape, **`{"action": "accept"}`** — *not* the
`{"decision": …}` the SDK's default handler uses for a Codex command approval.
Answering with the wrong one leaves the call refused and looking like a denial;
that cost a turn to discover.

**The SDK's default handler accepts every command execution and file change it
is asked about**, so a build that set `reviewer=user` and forgot to replace it
would be strictly worse than one that never asked.

The policy approves calls to servers **this caller configured** and declines
everything else, including a server inherited from `CODEX_HOME`'s own config.

## CX-07 — reaching `reviewer=user` uses two SDK privates, guarded

`AsyncCodex.thread_start` derives the reviewer from a two-value enum, and
`AsyncCodexClient.__init__` takes no `approval_handler`. Both are reached
directly, **only when a session actually configured MCP servers** — a session
without them touches nothing private.

`assert_sdk_shape()` checks every name reached for and runs as an ordinary test,
so an SDK bump fails in CI rather than silently denying MCP in production. The
handler runs on the client's reader **thread**, so it is a plain callable that
must never block and never raise.

# D. MCP

## CX-08 — MCP is configured through `--config`, not through the SDK

The Codex Python SDK has no MCP API at all. `CodexConfig.config_overrides`
becomes `--config key=value` on the binary before `app-server`. The TOML shape
was captured by running `codex mcp add` against a scratch `CODEX_HOME` rather
than guessed:

```toml
[mcp_servers.acme]
command = "npx"
args = ["-y", "@acme/mcp"]
[mcp_servers.acme.env]
A = "b"

[mcp_servers.remote]
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "MCP_TOKEN"
```

Measured end to end: the app-server loads the servers, launches them inside the
container under bubblewrap, and the tool reaches the model.

## CX-09 — two transports and one header, published as `capabilities.mcp`

**No `sse`** — `codex mcp add --url` is streamable HTTP and there is no second
URL form. **`http` carries a bearer token and no other header**, named by
`bearer_token_env_var` rather than carried, so the value travels in the
app-server's environment rather than its argv.

**That keeps it out of the process table and not out of the agent's reach**: the
agent runs as the same user and can read its own environment. What this buys is
audience, not secrecy — the same conclusion the Claude build reached about argv,
by a different route.

Anything else is a 400 naming the transport or the header.

# E. Options, and what is refused

## CX-10 — a published option that nothing applies is the defect this build shipped twice

`SERVICE_ENFORCED` named three options and **enforced none**. Then
`unsupported()` was written, unit-tested six ways, imported — and **called by
nobody**, so six fields were silently dropped while the documentation recorded
that callers were told.

**A unit test of a helper cannot see that nothing calls the helper.** Both are
why refusals are asserted through the route rather than through the function.

## CX-11 — `timeout_s` is enforced here; `max_turns` and `max_budget_usd` are refused

`timeout_s` is a wall-clock deadline taken at turn entry; a turn that outlives it
is **interrupted** and answers 504. It is enforced where the turn handle lives,
because a deadline that expires must *stop the turn* — otherwise the app-server
spends tokens on a turn nobody awaits while the lock is already free, which is
two turns on one conversation.

`max_budget_usd` is unenforceable in principle here (CX-29). `max_turns` has
countable proxies and none is the quantity the other SDK's `max_turns` bounds —
**a limit whose unit differs per implementation is worse than one a caller is
told it cannot have.**

Three consequences found by tests rather than by reading: a timed-out turn was
going to be recorded `timed_out: false`; it would have left the *previous* turn
standing as the session's last, which is misattribution rather than omission;
and `RunTimeout` was referenced without being imported, so the first real
timeout would have been a `NameError`.

## CX-12 — this build cannot price a turn, so cost is `null` and never `0.0`

`total_cost_usd` is `null` on every turn and every session, forever.

`null` means *this build cannot report it*, never *free*. `turns` in the same
response disambiguates: `turns: 0` with `null` is "nothing ran"; `turns: 3` with
`null` is "this build does not price". The specification made the field nullable
for exactly this build, and schema revision `d3f9a0c15e27` made the column
nullable so a stored row records *unpriced* rather than *free*.

## CX-13 — `token_usage` reads `usage["last"]` with snake_case keys

The counts are `input_tokens`, `output_tokens`, `cached_input_tokens`,
`reasoning_output_tokens`, nested under **`last`** — `total` is the thread's
running sum and reporting it would inflate every turn after the first.

**This read camelCase at the top level for a whole release**, so every turn
published five nulls while the numbers sat beside them in the raw pass-through.
`.get` degrading to `null` is what hid it: a wrong key was indistinguishable
from an absent one. **No fallback to the top level**, deliberately.

`cache_write_tokens` is `null` for a real reason: Codex has no such counter, so
a cache write is a charge this API cannot show.

## CX-14 — `setting_sources` honours `user` and `project`; `local` is refused by value

Codex reads a project document (`AGENTS.md`) from the thread's `cwd`, and
`project_doc_max_bytes=0` suppresses it — **measured, with the control run
first**, because a knob that switches off something never on proves nothing.

`user` is always on and not selectable. `local` has no equivalent and is refused
with a 400 naming it — **by value, not by field**, which is why
`unsupported_options` does not name `setting_sources`.

**Omitted is not empty.** An omitted field takes the deployment's default (the
project doc IS read); an explicit `[]` asks for no project doc and gets it.

## CX-31 — the permission mapping is written out, and `full_access` is unreachable

Six `permission_mode` values map onto Codex's two independent axes. The table is
written value by value rather than computed, because it is a safety decision.

`full_access` disables the sandbox entirely and **no value in this vocabulary
means that** — a deployment wanting it must say so in its own configuration
rather than let a caller reach it through a per-request field.
`bypassPermissions` maps to the workspace sandbox: the name promises more than
it delivers here, which is recorded rather than fixed.

`effort: max` has no equivalent and maps to `xhigh`, the highest Codex offers —
a narrowing of one step rather than a refusal, because failing a caller for
asking for more effort than the SDK can express helps nobody.

# F. Identity, lifecycle and capacity

## CX-15 — the thread id exists at creation, so `sdk_session_id` is never null here

Codex mints a **UUIDv7** at `thread_start()`. The specification says `null`
means *not known yet*, and this build knows — so the `201` carries it, where the
Claude build reports `null` until the first turn.

Two consequences, both published: `POST /v1/query` sends the `x-sdk-session-id`
header (`query_reports_sdk_session_id`), and that route opens a real throwaway
session so it consumes a slot and can answer 429
(`query_consumes_a_session_slot`).

## CX-16 — a caller-supplied `sdk_session_id` is refused, never adopted-and-replaced

`thread_start()` takes no id parameter and Codex offers no override. Accepting
the field and returning a different id would break the one guarantee supplying
it provides, and break it silently. A 400 with a named problem `type`, refused
before the cap is touched and before any subprocess starts.

**Not a defect and not a temporary gap.** The clause was written from a CLI that
accepts one.

## CX-17 — resume needs the rollout, which lives in `CODEX_HOME`

A thread that has taken **no turn** has no rollout and cannot be resumed — the
same semantics the Claude CLI has, arrived at independently.

A conversation survives a container restart **only if `CODEX_HOME` is on a
volume**. Measured: restart with the volume kept and `options.resume` continues
the conversation; `down -v` and the identical request is a 400.

`GET /v1/sessions` is empty after a restart and that is correct: the registry is
in memory, `session_id` is this process's handle, and the conversation is
`sdk_session_id`. **A consumer wanting continuity keeps that id** — without a
database the `201` was the only place it appeared.

## CX-18 — resuming a conversation that is gone is its own refusal

The SDK raises `InvalidRequestError` for a malformed request *and* for a resume
target it cannot load, and both answered `400 "Invalid request"`. **"The history
is gone" and "your request is wrong" are acted on differently** — the first says
open a new session, the second says fix the body.

Translated at the one call site that can raise it, with a named problem `type`.

## CX-19 — `pids_limit` binds long before `mem_limit`, and `max_sessions` knows neither

Measured: **~20 MiB and ~30 processes per session.**

| sessions | 0 | 4 | 8 | 12 | 16 |
|---|---|---|---|---|---|
| memory | 52 | 172 | 240 | 320 | 402 MiB / 2048 |
| pids | 2 | 135 | 246 | 357 | **485 / 512** |

A container carries about **16 sessions** whatever `max_sessions` says, and the
two are configured independently. Exceeding it produced
`500 "Unhandled error" / BlockingIOError` — the unclassified case — and is now a
**503**, retryable, declared under AS-33.

`max_sessions` defaults to 4 in compose and 8 in code. `mem_limit: 2048m` is a
ceiling rather than a fit: its job is to turn an unbounded container into a
diagnosable exit 137 rather than an arbitrary host-level OOM elsewhere.

**The boot says so now** (2026-08-10). `process_capacity_warning()` reads
`/sys/fs/cgroup/pids.max` — cgroup v2, then v1 — and logs a warning when
`max_sessions` exceeds `(limit − 5) / 30`, naming both numbers and the 503 the
operator will otherwise meet.

**A warning and never a gate**, which is the platform's own rule rather than a
preference: *report what can recover, refuse what cannot*. Exceeding the process
cap is recoverable without a restart — somebody closes a session — and it
already has a named answer. A gate would refuse a boot that is about to become
correct, which is the argument that settled the schema-revision gate in the
other direction. **And 30 pids is an average**: an agent running a parallel
build spends far more, so a refusal would turn a conservative estimate into a
policy.

`process_limit()` answers `None` for three different situations — not in a
container, a cgroup v1 host laid out differently, and a container started with
no `pids_limit` (the file reads `max`) — and all three mean the same thing here:
nothing to compare, so nothing claimed. It is called from the lifespan, so it
never raises.

## CX-21 — the default model is one measured to answer

**`default_model` is `gpt-5.1` since 2026-08-10** (user). It was `gpt-5-codex`,
and on the key this was measured with **every codex-family model returns 404
from `/v1/responses`** while `gpt-5.1`, `gpt-5-mini` and `gpt-4.1-mini` answer
200 — and all appear in `GET /v1/models`, so listing proves nothing about the
Responses API.

**Measured twice, a day apart, same answer, and the three that answer 200 are
the control**: a run where everything 404s is indistinguishable from a bad key,
an expired account or a proxy in the way.

| | |
|---|---|
| `gpt-5-codex` | 404 Model not found |
| `gpt-5.1-codex` | 404 Model not found |
| `gpt-5.1-codex-mini` | 404 Model not found |
| `gpt-5.1` · `gpt-5-mini` · `gpt-4.1-mini` | 200 |

`spike/probe_models.py` is the probe, and it is the answer for an operator
rather than for this repository: it honours `OPENAI_BASE_URL`, so a deployment
points it at its own endpoint and its own key. A 404 is free and a 200 is capped
at 16 output tokens.

**What the old default cost a caller, measured through this build's own session
— and it is not an exception.** The turn completes as `status: "failed"` after
**30.5 s**, because the app-server retries the 404 five times, twice. So:
`is_error: true`, `outcome_recorded: true`, and `terminal_reason` carrying
*"unexpected status 404 Not Found: Model not found gpt-5-codex, url:
https://api.openai.com/v1/responses, request id: …"*. Legible, and half a minute
spent retrying something that can never succeed.

**Why it moved, since the entry argued the other way for a day.** The case for
keeping `gpt-5-codex` was that one account is not a population and codex-family
models are the pairing this SDK is built around. The case that won is this
build's own rule about empty lists and guessed values: **a default nobody here
has ever seen work is a guess, and one measured twice is not.** The failure it
produced was not a graceful degradation either — it was every unqualified turn
failing after 30 s.

**What this does NOT claim.** `gpt-5.1` is not asserted to be the better model
for coding work, and a key entitled to codex models should probably use one:
`AGENT_SERVICE_DEFAULT_MODEL` is the deployment's lever and `options.model` the
caller's. What changed is which way the default fails on a key nobody has
checked — silently working versus 30 s of retries.

`capabilities.default_model` publishes the value, so a consumer reads the change
rather than inferring it, and the OpenAPI document is untouched: the field
carries no default in the schema — regenerated and diffed rather than assumed.

**Proved end to end with one paid turn through `/v1/query`, no model named, so
the default is what answered** (2026-08-10, user authorised): `result: "READY"`,
`is_error: false`, `subtype: "completed"`, **3.9 s**, `token_usage` populated
(12,916 in / 5 out). **3.9 s against the old default's 30.5 s failure is the
whole of the change**, measured on the same key an hour apart. It also satisfies
AS-34 on a real payload rather than a fixture.

**A probe against `/v1/responses` is not this measurement.** That one says the
endpoint serves the model; this one says a turn through this service, with the
app-server, the sandbox and the container in the path, comes back with an
answer. The 200s were already known when the default moved, and they were not
sufficient.

## CX-32 — a turn is exclusive, and the SDK does not enforce it

`AsyncThread.turn()` would happily start a second turn on one thread. The
per-session lock is this service's, and it is what makes a concurrent turn a 409
rather than two turns interleaving on one conversation.

## CX-33 — the registry lock is never held across an `await`

It guards the cap check-and-reserve, the lookup and the stale scan, and nothing
else. Holding it across `open()` would let one slow app-server spawn block
`close()` and the reaper for every other session — destroying the one lever an
operator has while something is wedged. `create()` reserves a slot before
opening so the cap stays watertight, and reconciles with synchronous statements
rather than a second `await` on a contended lock.

# G. The container

## CX-34 — one process, two directories, and only one of them is gated

`/workspace` is read-write and **must** be bind-mounted; `/codex-home` is
read-write from a named volume.

Without the workspace mount everything the agent writes is discarded when the
container stops and nothing notices — a misconfiguration, so the service exits
3. Without the `codex-home` mount everything **works**; threads and the auth
store simply do not outlive the container, which is a deployment choice and not
refused.

`CODEX_HOME` is set explicitly in the Dockerfile rather than left under `$HOME`:
**a path chosen on purpose can be mounted; one inherited gets mounted by
accident or not at all.** It holds SQLite in WAL mode, an `installation_id` that
survives restarts, unpacked skills, and **the auth store** — which is why it is
a named volume rather than a host bind by default: a directory on the host
holding a live API key is a thing an operator has to remember they created.

Observed after real turns: three SQLite databases (`goals`, `logs`, `memories`,
each with `-shm`/`-wal`), `sessions/` rollouts, `shell_snapshots/`, `skills/`.
**It holds agent state named `memories` and `goals`** — persisting across
sessions and containers, in a place no part of `/v1` reads or exposes. Not a
defect; not predictable from the specification either.

## CX-35 — there is no reference mount, and that is not an omission

A Codex thread takes a `cwd` and nothing else — no `add_dirs` equivalent — so a
second mount would be visible to `docker exec ls` and invisible to the agent.
`reference_dirs` publishes `[]`, which is the honest answer, and
`AGENT_SERVICE_REFERENCE_DIRS` is read from nowhere: a consumer that sets it
gets no error and no effect.

## CX-36 — the build guard fails the build rather than the first turn

The Dockerfile refuses to build unless the Codex runtime is present, executable,
plausibly sized and runs on this libc — asked of the SDK's own resolver, never
of a hardcoded path, so it cannot drift from what the service executes.

`rg` is checked because the service never sets `codex_bin`, so the SDK puts
`codex-path/` on the agent's `PATH` and that is where its search tool comes
from. A missing `rg` surfaces as the agent reporting it cannot find anything —
a model problem to look at, a packaging problem in fact.

The published wheel set has **no sdist**, so a missing platform tag fails
resolution loudly rather than silently building from source.

## CX-37 — the image size number in `docker images` is not the image

Disk usage is reported as ~828 MB because Docker Desktop's containerd store
counts the unpacked snapshot *and* the compressed blobs. The dominant real
component is the Codex runtime: **298,553,392 bytes** for the `codex` binary
alone, plus a code-mode host and `rg`. Do not quote 828 MB to anyone sizing a
registry.

Idle: **51.7 MiB, 1–2 pids**. Cold start ~2 s to the first successful
`/healthz`.

## CX-38 — shutdown is one budget, and the compose number is derived from it

**This entry said the opposite until 2026-08-10**, when the budget was built:
`close_all()` closed every session in turn with nothing bounding the sweep, so
`stop_grace_period: 60s` was a bound imposed from outside rather than derived.

Now:

```
stop_grace_period (100s) >= --timeout-graceful-shutdown (30s, Dockerfile CMD)
                            + Settings.shutdown_budget_s (60s)
                            + margin (10s)
```

Docker sends SIGTERM, waits, then SIGKILLs. Two budgets run sequentially inside
that window and only the first is uvicorn's — the request drain, then the
lifespan shutdown. `test_the_compose_grace_period_follows_the_shutdown_budget`
reads all three out of the three files that own them and fails if they stop
agreeing.

**60 s is itself a derivation, not a preference.** The SDK's close is already
bounded — `stdin.close()`, `terminate()`, `wait(timeout=2)`, `kill()` on any
exception, then two 0.5 s thread joins — so one close costs at most ~3 s. A
container carries about 16 sessions before `pids_limit` binds (CX-19).
16 × 3 = 48 s, and 60 leaves the margin. **What had no bound was N of them
adding up**, not any one of them.

Inside the budget: sequential, LIFO, each close given a **fair share** of what
is left (`remaining / still to attempt`) rather than a fixed slice, so a close
that returns early hands its time to the rest and one wedged session cannot
cost the healthy ones their clean teardown. One `Exception` does not stop the
sweep; a `BaseException` aborts it, because widening that catch would swallow
the shutdown telling it to stop.

**There is no force-kill phase, where the Claude build has one, and that is the
SDK's doing rather than an omission.** `AsyncCodexClient.close()` is
`asyncio.to_thread` around a synchronous close: cancelling ends the *task* at
once and leaves the thread running regardless, there is no handle on the
subprocess to kill, and the SDK's own close already ends in `proc.kill()`. So
an overrun close is cancelled and abandoned with no grace period for an
acknowledgement that cannot arrive — spending budget on it would only take time
from the sessions after it.

**Only a close that RETURNED deregisters a session.** It used to pop on failure,
which made a subprocess that may still be alive indistinguishable from one that
shut down cleanly. `list()` after a sweep names exactly what is not known to
have gone, and the one summary line — logged always, at ERROR when anything is
left — names them.

## CX-39 — the credential gate cannot see a login in the auth store

`login_api_key()` writes into `CODEX_HOME`, so a mounted volume carrying an
earlier login is already authenticated with no variable set. Such a deployment
must start with `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, and the gate's own
message says so.

All boot gates exit **3** — an orchestrator can tell that from a crash — and
each names what to do.

# H. Where this build cannot satisfy a clause

## CX-22 — `context_usage` and `reference_dirs` are empty because there is nothing to fill them

Codex exposes no context-window control request, so `context_usage` is `null`
rather than invented. `GET /v1/sessions/{sid}` therefore issues no live request
and **cannot fail because the agent is wedged** — the opposite of the Claude
build, where that route is the one that talks to the subprocess.

`reference_dirs` is `[]` — see CX-35.

## CX-23 — `permission_enforcement: "none"` means something different here

Codex enforces by **sandbox** rather than by an in-process hook, and the
specification's vocabulary has no member for that. `none` is honest: no
in-process write-confinement is wired up. The sandbox is reported per request
through `permission_mode` instead.

## CX-24 — errors never carry an SDK message by default

A JSON-RPC error from the app-server can carry a path, a command line or model
output, and this service is unauthenticated by default. The class name is safe;
the message is not, so it is used only where the class is one this build chose.

`UNCLASSIFIED_TITLE` is distinctive on purpose: its presence in a log means the
error table has a gap rather than that the service misbehaved. **It has meant
exactly that twice** — CX-13 and CX-19.

The problem `type` URIs this build sets: persistence-disabled,
sdk-session-id-unsupported, unsupported-options, resume-target-not-found,
session-capacity-exhausted. **Branch on `type` and `status`, never on `title` or
`detail`.**

## CX-43 — a named `type` for every 400, because Studio has to match a sentence otherwise

`POST /v1/sessions` answers 400 for several unrelated reasons — a limit above
this build's cap, an option it cannot honour, request validation — and a status
code plus prose means matching a sentence. **The sentence is the part that is
allowed to change.** So each reason carries its own `type` URI, which is what a
client branches on. Owed to Agent Studio and delivered in 0.19.0.

## CX-44 — every status a route can produce is declared, and absence means unreachable

`errors.py` could once produce three statuses the document did not declare, and
one of them — 503 — was declared by **neither** implementation, so the
document-to-document comparison that found the other two was structurally
incapable of finding it.

The rule (AS-33): a build declares every status its own error mapping can reach
on that route, and **absence means unreachable**. Reachability is a fact about
source rather than about HTTP, which is why the test that pins it lives in this
build's suite and not in the specification's.

## CX-42 — `auth_required` was published while nothing enforced it

The build read `AGENT_SERVICE_AUTH_TOKEN`, published `auth_required` from it on
`/healthz` and `/v1/capabilities`, and **had no middleware**. Setting the token
produced an API that answered every unauthenticated request while both status
surfaces said it was protected.

**The interim fix was a boot gate that refused to start when the token was set**
— a service that will not boot is better than one that lies about being
protected — with no escape hatch, because there is no legitimate way to enforce
a token the build does not read.

Bearer auth exists now: `/v1` protected, `/healthz` exempt so the container
healthcheck still works, constant-time compare, 401 as a problem document. The
gate is gone; the test written to fail on the day it became unnecessary did
exactly that, on the run that implemented it.

**Three things before relying on it.** It is the **third** control — network
isolation and a relay remove more risk, both are the consumer's, and the
platform's security posture gives the order. The token is **readable by the
agent**: the app-server subprocess inherits this process's environment and runs
as the same uid, so it must be per-instance and must buy nothing but this
instance. And it authenticates a *caller*, not a *user* — nothing is scoped by
it.

## CX-45 — the auth module is a second copy on purpose, guarded by the suite

It is ~40 lines the **specification** determines rather than the SDK — scheme,
protected prefix, the 401's shape, `/healthz`'s exemption — and the shared
package's own rule is that two hand-maintained copies of a spec-determined thing
is *"a specification violation that ships, not a duplication that annoys"*. By
that reasoning it belongs in `agent_spec`.

**What stops it is that package's guard**: pydantic and nothing else, and this
module imports FastAPI. The `db/` half got in under an extra, so the precedent
exists — but restructuring the shared package has been the user's call both
times it happened (2026-08-07, 2026-08-08), and taking it unilaterally to save
forty lines is not the trade.

**So the drift is guarded where that same rule says it should be**: the
specification's auth suite asserts the contract over HTTP against any build
publishing `auth_required: true`. One suite, both builds, and a divergence
between the copies fails it. That is a better guarantee than a shared import,
because it also covers an implementation that is not Python.

## CX-46 — the models are imported from `agent_spec`, not redeclared

AS-24 requires every implementation to serve the **same** document. The pydantic
models that generate it are shared for exactly that reason; redeclaring them per
build would make byte equality aspirational. Everything else that looks
duplicated between the two builds is left visible on purpose — it is evidence
about what the specification determines, and the specification's suite is what
holds it together.

## CX-25 — a failed turn is reported honestly

An upstream failure comes back as HTTP **200** with `is_error: true`,
`subtype: "failed"` and the upstream message in `terminal_reason`, including the
request id. Nothing is swallowed and nothing is dressed up as a service failure
it was not. Retries are visible in the event stream as `will_retry: true`
followed by one `will_retry: false`.

## CX-40 — AS-24 is satisfied, and how that was reached is worth keeping

The served document once differed from the published one by 151 keys present
only in the published, 19 differing and 7 only in the served. **The 151 were an
unbuilt feature, not a divergence** — persistence, which this build then gained
— and spending that number as evidence about the specification's core boundary
would have been wrong.

What remained was prose plus a few status codes, and it closed in four steps:
the supplied-id clause became conditional, this build gained persistence, it
declared the statuses it can actually produce, and the document became
per-implementation. **The last step was not a relaxation** — byte equality
still holds; it names the right pair.

## CX-41 — a conformance suite written against one SDK is not neutral

Four assertions in the boot-gate tier named Anthropic's environment variables
and were invisible until a second image existed. A clause forbidding
`/v1/query` from declaring a response header generalised one SDK's timing into a
prohibition on giving a consumer *more*.

The general fix is that a clause two builds cannot both satisfy becomes
conditional on a published capability rather than forked — **which is what lets
one suite measure two implementations without either being the reference.**

## CX-47 — nothing configured logging, so every INFO this build wrote was dropped

**Measured 2026-08-10 in a container**, and found only because CX-38's summary
line was written and then looked for: uvicorn's `LOGGING_CONFIG` names the
`uvicorn*` loggers and leaves the root logger with no handler, so every record
from `agent_service.*` met Python's last-resort handler — **WARNING and above to
stderr, the rest discarded.** The boot's capacity warning appeared; the
`close_all` summary and the reaper's line, both INFO, produced nothing at all.

`main.py` calls `basicConfig` now, at `AGENT_SERVICE_LOG_LEVEL` (default
`INFO`). **`basicConfig` and not `dictConfig`**: it adds a root handler only
when root has none, so it defers to an existing configuration, where
`dictConfig` closes every handler in the process on its way past — uvicorn's
included. The `uvicorn` logger carries `propagate=False`, so its lines are not
duplicated.

**The level is normalised and validated where it is read**, because `logging`
matches level names case-sensitively: `AGENT_SERVICE_LOG_LEVEL=info` would
otherwise abort the boot with `Unknown level: 'info'` from inside `basicConfig`,
naming neither the variable nor the alternatives.

**And the entrypoint resolves `Settings` ONCE and passes it to `create_app()`,
which is load-bearing rather than tidy.** `from_env()` pops
`AGENT_SERVICE_DATABASE_URL` out of `os.environ` — a security requirement, since
the agent inherits this process's environment and can run shell commands — so
the *second* call in a process returns `database_url=None`. Reading the log
level from one `Settings` and letting `create_app()` build its own would have
switched persistence off in production while every test went on passing: the
tests pass settings in explicitly and never take the second read. Pinned by
`test_from_env_POPS_the_database_url` and
`test_the_entrypoint_resolves_settings_ONCE`.

## CX-48 — `stop_kind` is derived in `agent-spec`; this build passes `status` and nothing else

**0.19.0.** *Why did this turn end* was spread over seven fields — three
verbatim SDK strings and four typed flags. `stop_kind` is one closed word beside
them, and the three strings are unchanged: the `token_usage`-beside-`usage`
pattern, applied a second time.

**This build's whole contribution is `outcome.status`.** Codex has a
first-class terminal status, so the facts handed to
`agent_spec.openapi.stop_kind.derive_stop_kind` are exact rather than inferred:
`completed` maps to `end_turn`, `interrupted` and `failed` are read off the same
field, and `timed_out` comes from the deadline this build imposes. **Anything
else falls through to `other` rather than being guessed at here** — a mapping
invented in an adapter is a mapping nobody can check.

**The derivation is shared on purpose.** Two builds deriving this
independently would move the disagreement one layer up, where it is harder to
see, and defeat the field. The specification decides the word; a build supplies
facts.

**Where it is worth most is the stored record.** A `SessionRecord` fetched later
has no status code, so the 504 that announced a timeout is long gone —
`stop_kind: "timed_out"` beside `timed_out: true` is the same fact in the
vocabulary a client branches on.

**Purely additive:** +42 leaves on this build's published document, **nothing
removed**, one description changed (`limit_hit`, which now names its
`stop_kind` equivalents).

## CX-49 — the permission modes are declared, and the map is the single source

**0.19.0.** The specification's `permission_mode` stopped being a closed union
of one SDK's enum; each build now publishes `capabilities.permission_modes` as
`{id, name, description}` objects and refuses an id it did not declare.

**`session_modes()` is derived from `_PERMISSION_MODES` rather than typed out
beside it.** A mode declared and not applicable, or applicable and not declared,
is precisely the defect the change exists to remove — so the ids come from the
map itself and a test fails if any of them has no description.

**The descriptions say what happens HERE.** Every mode on this build denies
escalation and only the sandbox moves, which is not what these ids mean on the
SDK they came from. `bypassPermissions` is declared and is **not a widening**:
Codex's full-access sandbox stays unreachable from any mode, so the id promises
more than it delivers here and the description says that rather than leaving a
caller to find out.

**`PermissionModeUnsupported` is new and has to be.** The shared `Literal`
refused an unknown value with a 422 before this module ran; an opaque string
would otherwise reach `_PERMISSION_MODES[mode]` as a `KeyError` and become a 500
for a request that is merely wrong. It maps to the same problem `type` as every
other "this build cannot honour what you sent", because the caller's remedy is
the same: read `capabilities.permission_modes`.

**One test went vacuous and that is the lesson worth keeping.**
`test_every_permission_mode_in_the_spec_is_mapped` looped over
`typing.get_args(PermissionMode)`. When that type became `str`, `get_args`
returned `()`, the loop body stopped running, and the test kept passing while
checking nothing. It is driven from `session_modes()` now and asserts the list
is non-empty first — **a check whose subject can silently empty is not a check**.

---

# I. History that must not be re-litigated

**These were believed, acted on, and disproved.** They are kept because the
belief is what explains the code.

- **`total_cost_usd: 0.0` was defended as correct here.** The reading was that
  the field is a non-nullable floor, so a build that prices nothing reports
  zero. That reading was one version out of date: the field had been made
  nullable for exactly this case, and `0.0` reads as *free*.
- **"The environment variables carry the credential."** They are published, they
  are exported, and the app-server ignores them. See CX-20.
- **"`plan` is read-only."** It was, until the agent approved itself. See CX-04.
- **"`unsupported()` reports refusals to the caller."** It reported them to
  nothing for a whole release. See CX-10.
- **"Codex's sandbox is Landlock plus seccomp, so `cap_drop: ALL` is fine."**
  Three of those four claims were wrong. See CX-01.
- **"The marginal cost of a session is memory."** It is processes. See CX-19.

## CX-50 — `thread-id` on the agent's own model requests equals our `sdk_session_id`, measured in the container

**Measured 2026-08-12, and it cost nothing.** `spike/compose.sink.yaml` puts a
sink — a socket that records the request and answers `401` — where the model
endpoint would be, and `spike/probe_codex_sink.py` drives one turn through
`/v1` and compares what arrived against what the API reported.

**Why a compose stack rather than a probe script.** The question is about the
**app-server**, which is what this build drives, and it does not start on a
Windows developer machine. It also has to be a real turn through `/v1`, because
the claim is not *some header carries an id* — it is that a header carries **the
exact string this service reports**. Nothing short of the whole path can show
that.

### What arrived

```
POST /v1/responses
thread-id:               019ff493-adf4-7f50-b98a-cb0cadb078b5
session-id:              019ff493-adf4-7f50-b98a-cb0cadb078b5
x-client-request-id:     019ff493-adf4-7f50-b98a-cb0cadb078b5
x-codex-window-id:       019ff493-adf4-7f50-b98a-cb0cadb078b5:0
x-codex-turn-metadata:   {"installation_id":…,"session_id":…,"thread_id":…,"turn_id":…}
authorization:           Bearer <the key>
originator:              codex_python_sdk
```

`POST /v1/sessions` reported `sdk_session_id:
019ff493-adf4-7f50-b98a-cb0cadb078b5`. **Three headers equal it byte for byte**
— `thread-id`, `session-id` and `x-client-request-id` — and two more contain it.

### Why `thread-id` is the one published

`llm_correlation.header` names one header, and the three are not equally safe:

| header | why not / why |
|---|---|
| `x-client-request-id` | names a **request**. It equals the thread id today; a version that made it per-request would break a gateway silently and look like nothing changed |
| `session-id` | equal, but the word means something else on the `/v1` surface — **our** `session_id` is a different string, and a consumer reading both would have two "session ids" that are not the same id |
| **`thread-id`** | **names what the value IS here.** `sdk_session_id` on this build *is* the Codex thread id, minted at `thread_start()`, so the header and the field are the same concept and will move together |

### Two things worth carrying

**The key rides in `Authorization: Bearer`**, unlike the Gemini build, which
uses `x-goog-api-key`. A gateway fronting more than one build cannot assume
either.

**`originator` was `codex_python_sdk` here and `codex_exec` from the CLI**, which
is the fact that justified refusing to publish this a day earlier. The header set
happened to be the same, but that was not knowable in advance from a different
front end, and the whole point of the field is that it is measured rather than
inferred.

### Reproducing it

    uv run --no-project python spike/probe_codex_sink.py

Free — the sink refuses before any model is consulted, so the dummy key in the
overlay is never load-bearing. What it costs is an image build.

## CX-51 — the extra CA comes from `SSL_CERT_FILE` alone, and it REPLACES the root store

**Measured 2026-08-14, free.** A private certificate authority, a TLS sink
serving a certificate it signed, one turn per arm — redirected the only way this
build can be, through `-c model_providers.*` overrides rather than the ambient
environment.

| Variable set to the PEM | Requests reaching the sink |
|---|---|
| *(none — the control)* | **0** |
| `NODE_EXTRA_CA_CERTS` | **0** |
| `SSL_CERT_FILE` | 6 |
| `REQUESTS_CA_BUNDLE` | **0** |

**`NODE_EXTRA_CA_CERTS` does nothing here and the Claude build honours it**,
which is the trap: one variable set fleet-wide looks like it works until it
reaches this image. The failure is also not an HTTP error — the connection is
refused inside the container before anything is sent, so the terminator's access
log has no line to correlate with and the symptom is a turn that failed at a
gateway that never saw it.

### It REPLACES rather than adds, and that is the load-bearing half

With `SSL_CERT_FILE` pointing at the private authority **only**, this build could
no longer reach the real API: *"invalid peer certificate: UnknownIssuer"*. The
runtime is a 298 MB Rust binary at `codex_cli_bin/bin/codex` and the variable
sets its root store rather than extending it.

**So a deployment cannot have both a privately-signed gateway and a public host
on this build through this variable.** For a container that only ever talks to
its gateway that is harmless; for one reaching an MCP server over public TLS it
is fatal, and it should be read from `ca_bundle_source` rather than discovered.
The Claude build ADDS under the same name, which is why the field publishes
`replaces_default_trust` rather than a name alone.

### The value is a FILE, never a directory

Pointing the variable at the directory holding the PEM refused the handshake
exactly as an unset variable does — indistinguishable from a wrong name, which is
why `shape` is published beside it.

`ca_bundle_source: {variable: "SSL_CERT_FILE", shape: "file",
replaces_default_trust: true}`.


## CX-52 — `impl` is published BEFORE boot as well as on `/v1/capabilities`

**Asked for by the consumer, 2026-08-14, and accepted as asked**: the same
`{name, version}` object, in a second place, with no change to
`/v1/capabilities` and no new field invented.

### Why the runtime copy was not enough

`GET /v1/capabilities` needs a **running** container, and two things a
provisioning consumer does happen strictly before there is one:

* the environment the container is **created** with, and
* a file written between `docker create` and `docker start` — a certificate
  authority among them, which cannot be added afterwards because the runtime
  reads its trust store once at startup.

`credential_sources` and `endpoint_source` are on this surface for exactly that
reason. **`impl` was the same kind of fact on the wrong side of the line**, and
it was already being computed and published twice — on `/v1/capabilities`, and
in the released document filenames `<impl>-<version>.json`.

### The two substitutes are both worse, and that is the argument

An image **tag** is a string an operator typed. A configured **provider** is a
field an operator chose. Either can disagree with what is actually running
inside the image; `impl.name` is the image's own statement about itself and
cannot.

### One value, not two copies

`impl.version` and the top-level `version` are the same local in one function, so
they cannot drift, and the conformance suite asserts they are equal. The name
comes from `IMPLEMENTATION_NAME`, which is what `/v1/capabilities` publishes —
so all three surfaces have one source.

**`document_version` is deliberately NOT inside `impl`.** It is the contract's
version rather than this build's, and the two have been free to differ since
they were split; nesting it under a build-identity object would imply otherwise.

## CX-53 — `effort_levels` published `max`, and this build cannot deliver it

**Found 2026-08-14** by reading the three builds' request surfaces against each
other rather than against a document, and fixed the same day.

### The mismatch

`RunOptions.effort` is `low … max`. Codex's `ReasoningEffort` stops at `xhigh`
and has no `max`, so `_EFFORT` maps `max -> xhigh`: a narrowing of one step.
**That mapping is correct and stays** — failing a caller for asking for more
reasoning than an SDK can express helps nobody, and refusing would be a worse
answer than delivering the most there is.

**What was wrong is that `/v1/capabilities.effort_levels` published the whole
vocabulary, `max` included.** So a client optimising for the most reasoning
available read `max` from the capability, sent it, and received `xhigh` with
nothing anywhere saying so. The turn succeeds, which is what makes it hard to
notice.

### Why not `unsupported_options`

`values` on an `UnsupportedOption` means **refused with a 400**, which is how
`gemini-python` publishes its refusal of `strict_mcp_config: false`. Listing
`{field: "effort", values: ["max"]}` here would therefore have promised a
refusal this build does not make and should not make — the same defect wearing
the opposite coat, and a behaviour change for every caller currently sending
`max`.

### The published list is "what is delivered exactly"

`HONOURED_EFFORT_LEVELS` is the identity half of the mapping table —
`{level for level, mapped in _EFFORT.items() if level == mapped}` — so `max`
drops out because it is the one entry that is not itself.

**Nothing about behaviour changed.** `max` is still accepted and still maps to
`xhigh`. A client that validates against the published list now simply has no
reason to send it, and one that sends it anyway is served exactly as before.

**Derived rather than typed out beside the table**, so a level that starts or
stops being honoured exactly cannot come to disagree with what is advertised.

## CX-54 — the interrupt was wired to the deadline and not to the consumer leaving

**Found and fixed 2026-08-14** while giving the three builds one stated
behaviour for a client disconnect.

### The asymmetry

`CodexSession.send` enforces the turn deadline itself and, on `TimeoutError`,
**interrupts the turn before reporting it** — the docstring is explicit about
why: *"without the interrupt the app-server would go on spending tokens on a
turn nobody is waiting for, and `turn_lock` would already be free for the next
one."*

Every word of that applies to a **cancelled** turn, and `asyncio.CancelledError`
was not caught. A dropped SSE consumer — a closed browser tab, a relay releasing
its upstream, a client that gave up — cancelled the await, sent no interrupt, and
left the app-server working.

**The `finally` made it unrecoverable.** `self._turn = None` runs on the way out,
so `SessionEntry.interrupt()` afterwards has no handle to act on. The turn could
not be stopped by anything short of closing the session.

### Shielded, and that is not decoration

The interrupt is being sent *from* the cancellation it reacts to, so a plain
`await turn.interrupt()` is cancelled again before the request leaves the
process. `asyncio.ensure_future` starts it and `asyncio.shield` lets this frame
stop waiting while the inner task runs to completion.

`contextlib.suppress(BaseException)` is deliberately wider than the timeout
branch's `Exception`: the shielded await raises `CancelledError`, which is a
`BaseException`, and swallowing it here is what lets the explicit `raise` below
propagate the original cancellation unchanged.

### Tested for free

`_HangingTurn` already existed for the deadline case — a turn handle that never
produces an event and records its interrupt — so the cancellation case needs no
credential and no app-server either. The test cancels a live `send` and asserts
the interrupt arrived; without the branch it does not.

## CX-55 — a relative `CODEX_HOME` is resolved against the WORKSPACE, not against us

**Found 2026-08-14**, and it had been making this build look unsupported on
Windows. It is not: the app-server runs natively on Windows and OpenAI documents
its own sandbox modes there. The defect was ours.

### What happens

`Settings.codex_home` defaults to **`./codex-home`** — a relative path. This
module created it (`mkdir`) relative to the SERVICE's working directory, which
is where it exists, and then passed the same relative string to the app-server:

```
env = {"CODEX_HOME": codex_home}
```

**The app-server is started with `cwd` set to the WORKSPACE**, so it resolves
that relative path against a directory that is not the one just created, finds
nothing, and exits:

```
Error: CODEX_HOME points to "codex-home", but that path does not exist
```

Which the SDK surfaces as `TransportClosedError: Codex process closed stdout` —
an error naming neither the path nor the cause, and the reason this was
misdiagnosed as a platform limitation rather than a bug.

### Why the container never saw it

The Dockerfile sets `CODEX_HOME` to an absolute path on purpose, which is
already recorded as a deliberate choice. So every containerised run resolved
correctly and every local run with the default did not — the exact split that
makes a defect look like an environment problem.

### The fix, and the half that was already right

`Path(codex_home).resolve()` before both the `mkdir` and the environment entry.
The neighbouring comment already explains that the directory **must exist
because the app-server will not create it** — measured 2026-08-07 — so the
"create it" half was handled and the "say where it is" half was not. Both are
needed and they fail identically.

**This build works on Windows.** Verified end to end after the fix: session
created, real turn taken, `result: "codex on windows works"`.

## CX-56 — `content` was null on every event, and the text was reachable only through `raw`

**Found 2026-08-14 by rendering a turn**, which is the only thing that finds it:
every suite passed, the document was served correctly, and the turn returned the
right answer. A console reading `AgentEvent.content` showed an empty
conversation.

### Why it happened

`AgentEvent.content` was declared `list[dict] | None` with **no description**,
under a model docstring that calls it *"One SDK message, normalized"*. Nothing
said what the field was for, so this build left it unset and put everything in
`raw`, where the text sits at `raw.item.text`. The Claude and Gemini builds
filled it with text blocks. All three readings were defensible against a field
that documented nothing.

### What it cost a client

A consumer following the specification reads `content`. On this build that is
`null` for every event of every turn, so the conversation is invisible — while
`raw` holds it in a shape that is this SDK's and no other's. That is the
*accepted and silently ignored* defect class inverted: not an input taken and
dropped, but an output the contract promises and this build never produced.

### What is filled, and what is not

**Text only.** Codex reports its tool loop as items, and this mapping already
reports them as `assistant` with the item kind in `subtype` — inventing
`tool_use` blocks would guess at a block shape the specification does not define
and that the other builds fill from their own SDKs. A conversation renders from
the words; an item's `text` is where those are.

**`None` rather than `[]` when there is nothing.** An `init` frame and a
rate-limit notice have no content, which is a different fact from content that
came back empty — the same rule `total_cost_usd` and `Health.database_usable`
already follow.

## CX-57 — `model_api` names the agent TARGET, and the consumer maps it to a vendor API

**Agent Harness asked for a field on the pre-boot surface naming the model API
this build speaks, 2026-08-15.** The field is published. **Its values are the
target family — `codex` — and not the vendor API they proposed** (user,
2026-08-16), so a consumer relaying to a vendor maps `codex` to the
OpenAI API on their own side.

### What they asked for, and what was traded

Their proposal was `openai`, on the argument that the API and the build are two
facts that travel together today and are free to stop. **That argument is sound
and it was not the decision taken.** What it would have bought is one fewer
mapping in their gateway; what it costs is a field whose values are a vendor's
vocabulary rather than this platform's.

**The cost of the choice is theirs to carry and they were told plainly**: a
consumer keying an endpoint by vendor API needs `codex` -> OpenAI, and
that mapping lives in their code.

### Why it is NOT a restatement of `impl.name`

`impl.name` is `codex-python` and carries the implementation language. **`model_api`
carries the family and deliberately does not.** A second build driving the same
target in another language publishes the same `codex` here and a different
`impl.name` there — so a consumer keying behaviour to the target keys on this
field, and one keying to a specific program keys on that one.

That distinction is the whole reason the field is not redundant, and it is what a
reader should check before proposing to merge the two.

### What it does NOT claim

`model_api` describes the target reached through this build's own
`credential_sources` and `endpoint_source`. **A provider selector in use is
outside it**: `PROVIDER_SELECTOR_ENV_VARS` is empty on this build -- no measured equivalent -- so the answer has no second branch here.

### Surface and cost

**Pre-boot, and asserted not to be on `/v1/capabilities`** — the question is asked
before a container is created, which is the same argument `credential_sources` and
`endpoint_source` sit here under. The conformance suite carries that assertion
beside the other pre-boot-only fields.

**No document version moves.** ~~The pre-boot specification is not in the OpenAPI
document at all, so this is an implementation change and nothing else.~~
**Superseded by CX-59 (0.19.0):** the pre-boot facts ARE in the OpenAPI document
now, as `PrebootSpec`, and `model_api` is pinned there with `const`. The sentence
above was true when written and the reasoning it rests on is what changed.

## CX-58 — an image publishes BOTH things it was built against, and the DDL was the missing one

**An image depends on two published artifacts and could only name one.**
`document_version` was on the pre-boot surface; the Alembic head it requires was
baked into the binary, gated the boot, and appeared nowhere a consumer could
read. Published since 2026-08-16 as `schema_revision`.

### The two streams do not predict each other

`spec/VERSION` moves when the HTTP surface or a clause changes; the schema moves
when a migration lands. Neither can be derived from the other, so an image
naming one of them leaves the other unanswerable. **Agent Harness declares
exactly this pair as two Maven dependencies** — the spec artifact at test scope,
the schema artifact executing inside their image — and an image has no pom, so
the pre-boot surface is where it says the same thing.

### The question it answers, and when it is asked

*Will this image accept my database?* Before 2026-08-16 the only way to find out
was to create a container and read the refusal, because the gate that compares
the baked revision against a live database runs at boot. **A database is chosen
before a container is created**, which puts the question on the same side of the
line as `credential_sources` — and off `/v1/capabilities`, where the conformance
suite now asserts it does not appear.

### It cost a module split, and the split is the point

The value lives beside the boot gate that enforces it, and **importing that
module pulls SQLAlchemy**. Two things cannot afford that: the pre-boot facts,
which were a command that had to answer in an image whose service cannot start
until 0.19.0 and are read at import to build the document's `PrebootSpec` now,
and the standing constraint that a build with no database configured never
imports a database stack — pinned by a fresh-interpreter test, because `sys.modules` is already
poisoned once any other test has run.

So the constant moved to an import-free leaf module, and the gate re-exports it.
**Still exactly one definition**: the alternative was a copy per build,
test-pinned to the original, which is a copy either way. A fresh-interpreter test
asserts the pre-boot specification imports no database code, which is what stops
the convenient import from creeping back.

### Identical on all three builds, deliberately

They migrate one database between them, so three images disagreeing about the
revision is a defect rather than a divergence — which is why this is **not** a
row in the capability-divergence table. The boot gate exists to catch exactly
that disagreement.

**No document version moves.** ~~The pre-boot specification is not in the OpenAPI
document, and nothing in `spec/` changed for this.~~
**Superseded by CX-59 (0.19.0):** `schema_revision` is pinned in the document's
`PrebootSpec` component, so it is part of `spec/` now and moving it needs a
document version.

## CX-59 — the pre-boot facts moved INTO the document, and the command was removed

**`agent-service-spec` is gone as of 0.19.0.** Every fact it printed is published
in this build's own OpenAPI document as `components.schemas.PrebootSpec`, with the
values pinned by `const` — `credential_sources`, `model_api`, `endpoint_source`,
`ca_bundle_source`, `provider_selectors`, `auth_enforced`, `schema_revision`,
`impl.name` and `listen`.

### Why the command was the wrong surface

**The consumer resolves the specification at BUILD time and loads an image at
RUNTIME.** Every decision these facts inform is made before a container exists:
the environment it is created with, a certificate written between create and
start, and the database it is pointed at. Requiring `docker run` to read them put
a runtime dependency in front of a build-time question — and the answer was
reachable from no path under `spec/`, which is the only tree the consumer was
told to depend on.

That is the same circularity the command itself was invented to cut, one level
up: the command existed because `/v1/capabilities` needs a running service, and
then the command needed a running container.

### `const` per build, and no enum anywhere

Each build states its own value, so nothing predicts how many builds will exist.
A closed set in a shared file would carry the half we know and imply the half we
do not, and a fourth build breaking no rule would falsify it. `const` is a real
constraint a validator enforces and a generator emits as a literal type.

`core-<version>.json` intersects the three documents, so the eleven-field shape
survives into the core and the per-build values drop out of it.

### Two fields are deliberately left open

`version` and `impl.version` carry no `const`. They move on the implementation
stream — a build bumps several times between two documents — and pinning either
would break AS-24 the first time one did. Read them from the image tag or from
`GET /v1/capabilities`.

### What replaced the command as the entry point

`docker inspect` carries `com.npf.agent-service.impl` and
`.document-version`, which together name the document holding everything else.
Nothing is executed. `ci.py`'s label check compares the labels against that
document, and the conformance suite's boot-gate tier reads the same pair.

### What this breaks, and it is not small

**AS-25's command no longer exists, and ST-1 in the signed 0.5.1 instrument runs
it.** That clause is frozen and cannot be edited, so a consumer implementing it
literally gets a container that fails to start. The notice went to Agent Harness
when this shipped. This is the first removal of a published surface rather than a
widening of one, and it needed a version because of that.

### The rule it creates

**A published document now ASSERTS these values, so moving one requires a new
document version rather than a rebuild.** Before this, the pre-boot surface could
change with nothing moving anywhere, which is how it drifted out of the
specification's reach.

## CX-60 — this build imposes no bound on an MCP tool call, and that is measured rather than assumed

Published as `mcp.tool_call` at document version 0.19.0, with **all four values
`null`**:

| Published | Value |
| --- | --- |
| `request_timeout_s` | `null` |
| `idle_timeout_s` | `null` |
| `total_timeout_s` | `null` |
| `progress_resets_idle` | `null` |

### Two pieces of evidence, because "no timeout" is the claim that is easiest to get wrong

**The resolved config, printed by the binary itself.** `codex mcp get <name>
--json` against a throwaway `CODEX_HOME` renders a streamable-HTTP server with
`"startup_timeout_sec": null, "tool_timeout_sec": null`. That is the *resolved*
view rather than the file handed in, which is the distinction that matters: a
default applied during parsing would show up here.

**No tool-call timeout message exists in the binary.** The only MCP timeout it
can emit names the handshake — *timed out handshaking with MCP server after* —
and there is no counterpart for a call. A timer that can expire has an error to
raise; this one has none.

**`tool_timeout_sec` is a per-server key and this build does not write it.** The
`mcp_servers.<name>.*` overrides carry the transport, the URL or command, and the
headers this build is allowed to carry, and nothing about time.

### Why `progress_resets_idle` is null rather than true

There is no timer of any kind here, so the question has no answer in this build. `true` would
claim a mechanism that is not there and `false` would claim a restriction that is
not there either. **`null` is the third answer**, and it means the same thing the
other three nulls do: no bound of that kind exists here.

### The boundary on the claim

**`null` is a statement about this client, not about the world.** Nothing in the
agent gives up on a held call; a proxy, a load balancer or a kernel between the
container and the server is free to, and this build would report that as a
transport failure rather than as a timeout. The run's own `timeout_s` still
applies and is the ceiling a caller actually controls.

## CX-61 — the 422 answered a shape this build's own document did not describe

**Reported by Agent Harness on 2026-08-19 and fixed the same day.** They sent one
request — `POST /v1/sessions` with `options` a string — and got a body no
consumer could have predicted from the published document.

| | |
| --- | --- |
| Declared, all three builds | `422` → `HTTPValidationError`, `detail` an **array** of `{loc, msg, type, input}` |
| Answered, this build | a `Problem`: `detail` a **string**, three undeclared properties, **no `loc`** |
| Answered, the other two | the declared shape |

### The decision that produced it was right about `input` and wrong about `loc`

The handler existed on purpose, with this reasoning: *"the errors are NOT echoed:
they quote the offending input, and this service is unauthenticated by default."*
**That half stands and is now enforced in one place.** A malformed body can carry
a caller's own MCP bearer token, and an error body is the thing most likely to be
logged by whatever sits in front.

What it got wrong was throwing away `loc` with `input`. `loc` names the field; it
is the only part a client can act on, and without it a caller diffs their own
request against the document to find out what was rejected.

**And it answered with a shape its own document did not describe**, which is the
defect regardless of which shape is better.

### Three artifacts disagreed, and the fix moved all three builds

Two builds satisfied the declaration and contradicted **their own consumer
guides**, which said errors — *including a 422 from validation* — are RFC 7807
problem documents. So the guides were right about the intent, the documents were
right about two builds, and no two of the three agreed.

Fixing only this build would have left the other two lying to their own readers.
So the shared `ValidationProblem` is what every build now returns and declares:
`type`, `title`, `status`, `detail`, and `errors` of `{loc, msg, type}` — the
field names a client needs, and never the values. `agent_spec.openapi.validation`
holds the handler and the declaration together, because either alone recreates
this defect.

### Why nothing caught it

**Every tier was green throughout.** AS-24 compares the served document to the
published one and both were equally wrong. AS-31 compares the three documents to
the core and all three declared the same thing. AS-33 asserts a build declares
every status it can produce, and this build did. **No clause compared a declared
response body to what the wire actually carried**, and the conformance suite
gained one the same day.

## CX-62 — a read-only mount nested under the workspace survives the sandbox, and the sandbox adds three of its own

**Measured 2026-08-28** against `agent-service-codex-python:0.19.0`, with
`spike/probe_nested_ro_mount.py`. The question came from Agent Harness, which
masks subtrees of one worktree — `src/test` read-only for a developer persona,
`src/main` read-only for a tester — so that a deny list, rather than a
convention, decides what each agent may edit.

**The mask holds.** Under `workspace_write`, one shell command in one turn:

```
touch: cannot touch '/workspace/src/test/ESCAPED.txt': Read-only file system
MASK:HELD
CONTROL:WRITABLE
```

**The control is the load-bearing half.** A sandbox that refused both writes
would have produced `MASK:HELD` and meant nothing by it. `CONTROL:WRITABLE` is
what makes the first line evidence — and the host bind mount agrees:
`src/main/CONTROL.txt` appeared there, `src/test/ESCAPED.txt` never did, so the
write that succeeded was a real one and not an overlay swallowing both.

**Why it holds** — `/proc/self/mountinfo`, read from inside the sandbox, with
the device and root columns kept:

```
621 572 0:67 …/ws            /workspace           ro,nosuid,nodev,noatime
622 621 0:67 …/ws/src/test   /workspace/src/test  ro,nosuid,nodev,noatime
635 621 0:67 …/ws            /workspace           rw,nosuid,nodev,noatime
636 635 0:67 …/ws/src/test   /workspace/src/test  ro,nosuid,nodev,noatime
637 635 0:97 /               /workspace/.git      ro,nosuid,nodev,relatime
638 635 0:107 /              /workspace/.agents   ro,nosuid,nodev,relatime
639 635 0:117 /              /workspace/.codex    ro,nosuid,nodev,relatime
```

Bubblewrap re-binds the whole workspace **read-only** first (621) and the bind
is **recursive**, so the nested mount comes with it (622, a child of 621). The
workspace-write grant is then a second read-write bind on top (635) — **and the
nested read-only mount is re-applied over that one too** (636, a child of 635).
The mask is preserved in both layers rather than surviving by accident in one.

**The sandbox adds three masks of its own**, and they are the part nobody asked
about. `/workspace/.git`, `/workspace/.agents` and `/workspace/.codex` are
remounted read-only from devices that are not the workspace bind — in a
workspace that contained no `.git` at all, so the target is synthesised when it
is absent. With a real one present:

```
. .. MARKER
GIT:REAL-CONTENT-VISIBLE
touch: cannot touch '/workspace/.git/W': Read-only file system
GIT:READONLY
```

So it is the **real** directory, readable and not writable — not an empty mask.

**The consequence is a caller's, not this build's: the agent cannot commit from
a sandboxed shell on this build**, whatever the container's mount table says.
That is Codex's policy and this service neither sets it nor can override it
through any `RunOptions` field; `capabilities.sandbox.confines_writes_to_workspace`
is `true` here and `false` on the other two builds, which is the published
signal that the answer differs. It is worth stating because the obvious workaround
for a masked workspace — mount the tree read-only and one subdirectory writable —
is usually rejected on the grounds that it would make `.git` read-only, and on
this build `.git` is read-only either way.

**Not measured**: `read_only` mode, which cannot write anywhere and so cannot
distinguish the two answers, and whether the three remounts are configurable.
Neither is reachable from this service's request surface.

---

## CX-64 — `workspace_subdir` was concatenated, not resolved: `..` walked out of the workspace

**Found 2026-09-03** by writing the field's description and checking what each
build actually does with it. The Claude build resolves and checks; this one did
neither.

### What it was

```python
cwd = self._settings.workspace_dir
if workspace_subdir:
    cwd = cwd / workspace_subdir
```

No containment check, no existence check. `workspace_subdir: "../../etc"`
started the thread outside the caller's workspace, and a misspelled directory
failed later inside the agent, where a caller cannot tell a missing directory
from a broken agent.

**Not a container escape.** The sandbox still confines writes and the mount is
still the boundary — the agent could not write outside `workspace_dir` whatever
its cwd. What it could do was start somewhere nobody asked for, silently.

### Why it matters more here than the working directory alone suggests

**The thread's `cwd` is where Codex reads `AGENTS.md` from** (CX-14). So an
unchecked `workspace_subdir` moved the agent's **ambient configuration** as well
as its working directory: point it at a sibling directory and the agent picks up
that directory's project document, on a build where `setting_sources` exists
precisely so a caller can control whether that document is read at all.

### What it is now

`resolve_workspace()` in `options.py`, three checks, refusing with a 400 that
names the field:

| Value | Answer |
|---|---|
| omitted | the workspace root |
| an existing directory under the root | that directory |
| anything resolving outside the root | **400** — "resolves outside the workspace root" |
| a directory that does not exist | **400** — "does not exist … this service does not create it" |

**The directory is never created.** It is caller-supplied per request, and
creating one from request input would litter the caller's mounted workspace —
the same reasoning the Claude build's own resolver carries.

**Three tests, including the control**: the escape, the missing directory, and an
existing `sub/` that must still open a session. Without the third, a resolver
that refused everything would pass.
