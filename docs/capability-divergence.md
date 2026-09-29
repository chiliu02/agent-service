# How the four builds differ, field by field

**Same shape, different values — and that split is the design rather than an
accident.** All four implementations answer the identical `Capabilities` model
from `impl/common/agent-spec`, serve the same thirteen `/v1` operations, and
share one conformance suite. A client parses one payload whichever image it has.
What it *reads out of* that payload diverges on nearly everything behavioural.

**The fourth column arrived 2026-09-07 and cost this document a column, exactly
as the rule said it would.** It cost the conformance suite nothing at all: the
document tier went 42 to 51 passing with no edit, because it discovers a build
by its published document rather than by name. What the fourth build DID cost is
two new sections — [§9](#9-mcp-on-pi-python-is-a-proxy-tool-and-that-changes-what-allowed_tools-can-say)
and [§10](#10-the-question-a-fourth-build-raised-about-the-field-itself) — and both
are cases where a row could not carry the whole answer.

**The payload is FOUR GROUPS since 2026-09-03, and the route is
`/v1/deployment`.** It was `/v1/capabilities`, flat, and answering four
unrelated questions at once:

| group | answers | this document |
|---|---|---|
| `service` | who is answering — contract, build, agent underneath | §2's first rows |
| `config` | how THIS instance is set up: `workspace_dir`, `default_model`, `max_sessions`, the gates | deployment-dependent, so mostly *not* tabulated here |
| `accepts` | what a caller may send | **[§3](#3-what-a-caller-may-send)** |
| `behaviour` | what it does and reports | **[§2](#2-what-the-service-publishes)** |

Half of what it carried was never a capability — `workspace_dir` and
`max_sessions` are configuration — which is what made the old name mislead.
**`accepts` is also served as a schema**, at `GET /v1/schemas/run-options`: the
same narrowing a validator can run, with a conformance clause asserting the two
agree.

**Two objects were cut along the group line**, and both are why the split was
worth doing: `limits` mixed ceilings on a request with figures the service
enforces (`accepts.limits` / `behaviour.limits`), and `mcp` mixed transports a
caller may express with timeouts a server author must design around
(`accepts.mcp` / `behaviour.mcp_tool_call`).

**Both halves of the contract are here.** [§2](#2-what-the-service-publishes)
is what a caller **reads** — the `/v1/deployment` response. [§3](#3-what-a-caller-may-send)
is what a caller **sends** — `RunOptions`, and which builds refuse which fields.
The two were separate documents until 2026-08-14; `options-divergence.md` was
merged in when [§5](#5-the-four-decisions-dev-todo-item-7) closed the open item
that had kept it a decision backlog rather than a reference.

**There are TWO published surfaces, not one, and the second is cheaper to read
than the first.** `/v1/deployment` needs a running container; the pre-boot
facts are in each build's own OpenAPI document, as the `PrebootSpec` component
with every value pinned by `const` — so they need no port, no credential, no
service and no image, and they diverge on the fields that decide how the
container is *created*. It is the end of [§2](#2-what-the-service-publishes),
and it is there because the consumer asked on 2026-08-14: a reader with a real
question about trust roots was finding a thorough table that did not mention
them.

**This document is a snapshot, and the running service is the authority.** It was
written against document version `0.19.0-snapshot` and implementation versions
**claude-python 0.18.13**, **codex-python 0.0.18**, **gemini-python 0.0.8**.
The **pi-python** column was added on **2026-09-07** against document
`0.22.0-snapshot` and **pi-python 0.0.1**, every value read out of that build's
`build_capabilities` on the day it was written.
[§3](#3-what-a-caller-may-send)'s `system_prompt` row, the new
[§3.1](#31-ambient-configuration--no-build-lets-the-api-replace-it-and-the-document-never-said-so)
and [§6](#6-three-defects-these-passes-found--all-fixed) were re-read from the
code on **2026-09-02**, against document `0.20.0-snapshot` and implementation
versions **claude-python 0.19.0**, **codex-python 0.19.0**, **gemini-python
0.19.1** — the last of which is that day's bump, and the row it moved is the
`system_prompt` one.
The **`default_permission_mode`** rows in [§2](#2-what-the-service-publishes) and
[§3](#3-what-a-caller-may-send) were added on **2026-09-08** against document
`0.23.0-snapshot`, when the field was first published on all four builds. It is
the row this table was arguably always missing: two builds resolve an omitted
`permission_mode` to a mode that is **not** the one called `default`, and the
four answers split two-and-two in a way no reader could have guessed from the
`permission_modes` row above.
Every value below is read from the source rather than from a delivery document,
and a build bump can move any of them. **`GET /v1/deployment` on the container
in front of you is what a client acts on** — this file exists so a reader can see
the four side by side without starting four containers, which is the one thing
four OpenAPI documents cannot show.

The values live in
[`impl/claude-python/src/agent_service/api.py`](../impl/claude-python/src/agent_service/api.py)
(`_capabilities_payload`),
[`impl/codex-python/src/agent_service/api.py`](../impl/codex-python/src/agent_service/api.py)
(`_capabilities_payload`, and `options.py` for the request side) and
[`impl/gemini-python/src/agent_service/capabilities.py`](../impl/gemini-python/src/agent_service/capabilities.py)
and
[`impl/pi-python/src/agent_service/capabilities.py`](../impl/pi-python/src/agent_service/capabilities.py)
(`build_capabilities` in both). The shared model is in
[`impl/common/agent-spec/src/agent_spec/openapi/schemas.py`](../impl/common/agent-spec/src/agent_spec/openapi/schemas.py).

---

## 1. What is identical

The convergence is real, and it is where the product's value sits:

- **One `Capabilities` model**, one set of thirteen `/v1` operations, one error
  vocabulary, one session lifecycle, one set of boot gates.
- **One conformance suite** in `spec/conformance/`, which judges each build
  against the specification rather than against itself.
- **One shared core** across the four OpenAPI documents. Adding the third build
  removed **zero** leaves from it, and cost the specification no new clause —
  two new entries in one probe table. The eleven fixes it did cost all landed
  inside the new build. **The fourth removed zero leaves and cost the suite not
  even that**: publishing a document was the whole of registering it.

- **One event surface**, since 2026-08-14. `AgentEvent.content` carries
  normalised text blocks on all three, and `type` is the authoritative
  discriminator.

That is the claim the repository makes. The third build tested it; the fourth
is the first to have cost nothing to add.

### The event surface was NOT identical until 2026-08-14, and nothing said so

Worth keeping, because it is the sharpest example of what this document is for.
`AgentEvent.content` was declared with **no description** under a model docstring
calling it *"One SDK message, normalized"*, and the three builds read that
differently: claude and gemini filled it with text blocks, **codex left it unset**
and carried the text at `raw.item.text` — a shape belonging to one SDK. A client
reading the field the specification names saw an empty conversation for a turn
that had succeeded, on one build of three.

**The SSE frame name diverged too, in the other direction**: claude and codex
name each frame by the event's `type`, gemini names every frame literally
`event`. So dispatching on the frame name renders nothing on gemini, and reading
`content` rendered nothing on codex — each build the odd one out in a different
half.

Neither was visible to any consumer: SSE frame names are not in an OpenAPI
document at all, and an undescribed field cannot be got wrong. Both suites
passed throughout; the turns were correct throughout. **It was found by
rendering a conversation**, which is the only thing that could have found it.

Now: `content` is described and filled by all four, and `type` is documented as
authoritative with **the frame name explicitly NOT contract** — a client reads
`type` from the payload and ignores the `event:` line. `CX-56` is the codex
half; dev-todo item 12 is the whole of it.

## 2. What the service publishes

Every row is a difference a client must act on. That is the AS-32 test — a field
whose value is inert does not belong here, and `strict_mcp_config`'s absence from
the Codex build's `unsupported_options` is that test being applied.

**That test admits a row; it does not evict one** (2026-08-15). A row nothing is
known to branch on is **marked `°` and kept**, never deleted:

> `°` — **no consumer has told us it branches on this.** Not *nobody does*: the
> only client that has reported is Agent Harness, on 2026-08-14, and it is a
> gateway and a fleet manager. A client rendering transcripts or billing per
> model reads a different half of this table.

**`model_usage_scope` is why the rule changed.** It is marked below and it is the
row Harness holds as a written constraint on code it has not written yet — *sum
on gemini, difference on claude, skip on codex*. Deleting it would have removed
the warning immediately before the work that needs it. **A row costs a line; a
missing row costs an experiment**, and that asymmetry is the same one that
justifies the whole document.

| Field | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| `sdk.name` | `claude-agent-sdk` | `openai-codex` | `gemini-cli` — **no SDK exists**, a Node CLI spawned per turn | `pi-coding-agent` — **an SDK EXISTS and this build does not use it.** It is TypeScript; this build is Python and drives the binary, so the row is neither of the two shapes above |
| `model_usage_scope` `°` | `cumulative` | `not_reported` | `per_turn` | `per_turn` — **checked, not assumed**: two calls in one run reported 2,150 then 2,095 input tokens, so the second is not a running total |
| `reports_cost_usd` `°` | **true** | false | false | **true**, on every provider — USD from the agent's own catalogue, summed over the run's model calls |
| `sdk_session_id_scope` `°` | `conversation` | `conversation` | **`turn`** | `conversation` — measured across two processes on three providers |
| `allow_supplied_sdk_session_id` | **true** | false | false | **true** — `--session-id` is echoed back verbatim |
| `query_reports_sdk_session_id` `°` | false | true | true | true — the id exists **before the first model call**, so even a keyless failure reports one |
| `query_consumes_a_session_slot` `°` | false | **true** | false | false |
| `llm_correlation.header` `°` | `x-claude-code-session-id` | `thread-id` | **null**, `measured: true` | **null**, `measured: false` — and the difference from the column to its left is the whole point of that flag: gemini looked and found nothing, this build has not looked |
| `sandbox.network_access` | true | **false** (bubblewrap) — **the agent's SHELL only.** Its hosted web tool searches and fetches pages regardless, on by default, with no switch this service controls (measured 2026-09-02, `CX-63`) | true | true — **and there is no sandbox at all here**, so this is not a claim about a shell but about the whole agent |
| `sandbox.confines_writes_to_workspace` | false | **true** | false | false — and here it is *there is no sandbox* rather than *the service does not enforce one*. The agent's own docs: **"Pi does not include a built-in sandbox"** |
| `permission_enforcement` `°` | `none` by default, `hook` available | `none` | `none` | `none`, and here it is the literal truth rather than a vocabulary mismatch: there is no in-process confinement of any kind to describe |
| `permission_modes` | `default`, `acceptEdits`, `plan`, `dontAsk`, `auto`, `bypassPermissions` | the same six | **`default`, `auto_edit`, `yolo`, `plan`** | **`default` alone.** No per-operation approval exists headless: trust is binary and project-level, and the agent's own docs name plan mode among the things it omits. `plan` is OMITTED, not mapped |
| `default_permission_mode` | **`dontAsk`** — *never prompt; deny anything not pre-approved.* An agent under it reads, plans and delegates, then cannot write, **and nothing outside the agent's own prose says so**: there is no approval channel on `/v1`, so a denied prompt is logged nowhere | **`dontAsk`** — the same id and the **opposite direction**: here `default` is a read-only sandbox and `dontAsk` writes inside the workspace, so the shipped default is the *more* permissive of the two | **`default`** — the guessable answer, and the one that is not deterministic. `GP-18` measured nine trials of one prompt: wrote once, declined three times, failed to terminate five. A caller wanting a writing agent sends `auto_edit` | **`default`** — the only mode there is. *One mode* and *this is the mode you get* are still two claims, and a client should not have to infer the second |
| `effort_levels` `°` | full vocabulary | **all but `max`** — the one level it cannot deliver exactly | **empty** | **empty, although the agent HAS a dial.** `--thinking` takes seven levels, but per MODEL — so a flat list meaning *delivered exactly* cannot state it. See [§10](#10-the-question-a-fourth-build-raised-about-the-field-itself) |
| `setting_sources` | full vocabulary | **`user`, `project`** | **empty** | **empty** — for a different reason from gemini's. This build CAN suppress, more finely than any other, but per *kind* (context files, skills, extensions, prompt templates) where the field is per *layer*. The two do not map |
| `default_allowed_tools` | operator-configured | **empty, and fixed** — this build governs by SANDBOX, not by tool list, and refuses `allowed_tools` with a 400 (corrected 2026-09-02; the column read *operator-configured*, which no setting on this build makes true) | five read/write/search tools, **no shell**. A constant here, not a setting | six read/write/search tools, **neither shell** — this agent has `bash` AND `powershell`, and no sandbox to confine either |
| `always_disallowed_tools` | `AskUserQuestion` | none | **`run_shell_command`** | `ask_question` — the same hazard as claude's, under the agent's own name: it exists to ask a human, and there is none |
| `mcp.transports` | `stdio`, `sse`, `http` | **`stdio`, `http`** | all three | **`stdio`, `http`** — built 2026-09-07 at the consumer's request. `sse` is absent because the adapter folds it into HTTP as a fallback rather than offering it as a choice. **`stdio` measured through the image; `http` accepted and not yet driven** |
| `mcp.http_headers` | `any` | **`bearer_only`** | `any` | `any` |
| `mcp.server_name_pattern` | null | null | **a real pattern** | **a real pattern, and a different one** — no underscore, because the proxy addresses a tool as `<server>_<tool>` and `a_b_c` is otherwise ambiguous |
| `mcp.tool_call.request_timeout_s` | **60** | null | **60** | **null** — nothing here is cleared by responding, so this is the wrong timer for this build. See `total_timeout_s` |
| `mcp.tool_call.idle_timeout_s` | **300** | null | null | null |
| `mcp.tool_call.total_timeout_s` | 100000 | null | **600** | **60**, measured — and it is the ONLY bound here. Nothing clears it: no response, headers at once, and headers plus data every 20 s were all cut at ~61 s |
| `mcp.tool_call.progress_resets_idle` | **true** | null | **false** | **false**, measured rather than assumed: ticks were delivered at 20, 40 and 60 s and the call died anyway |
| `strict_mcp_config` | operator-configured default | true | **true, and refuses `false`** | **true, and refuses `false` — structurally.** `--mcp-config` names this service's own file, so the adapter's six-file precedence chain, two of whose paths sit inside the caller's mounted workspace, never runs. Non-strict is not a behaviour this build has |
| `limits` | turns + budget + timeout + idle TTL | **timeout + idle TTL only** | turn timeout + max sessions + idle TTL | turn timeout + max sessions + idle TTL |
| `turn_token_overhead` `°` | — | — | **7000** | **550** — an order of magnitude under gemini, measured with tools off and every ambient source suppressed; roughly 1,150–1,400 with the default tool set on |

### `sandbox.confines_writes_to_workspace` — on codex-python the sandbox rebuilds the mount table, and adds three masks

**Measured 2026-08-28 against all three `0.19.0` images**, prompted by Agent
Harness, which masks subtrees of one worktree with nested read-only bind mounts
so that a developer persona cannot edit the tests and a tester cannot edit the
sources. One layout throughout: `/workspace` bound read-write, `/workspace/src/test`
bound read-only over it.

**A read-only mount nested under the workspace survives on all three builds.**
The masked write fails with `Read-only file system` while an unmasked write in
the same command succeeds — and on `codex-python`, where the agent's shell runs
inside a second namespace, the write that succeeded reached the host bind mount
rather than an overlay. So the partition a caller builds from mounts is one all
three honour.

| | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| nested read-only mask | **held** | **held** | **held** | **not measured** |
| unmasked write (the control) | writable | writable | writable | **not measured** |
| `/workspace/.git` | **writable** | **read-only** | **writable** | **not measured** |
| `/workspace` mount lines seen by the agent | 2 — what Docker created | **7** | 2 — what Docker created | **not measured** |

**What differs, and what a caller must act on, is what `codex-python` adds.**
Bubblewrap re-binds the workspace read-only, recursively — which is what carries
the nested mount in — then grants writes with a second read-write bind and
**re-applies the nested read-only mount over that one too**. On top of it, three
masks nobody asked for: `/workspace/.git`, `/workspace/.agents` and
`/workspace/.codex` are remounted **read-only**, the real directories rather than
empty ones, and synthesised when absent. So **the agent cannot commit from a
sandboxed shell on `codex-python`**, whatever the container's mount table says,
and no `RunOptions` field reaches the decision. The other two leave `.git` exactly
as the mount table left it — measured in the container's own namespace, which is
the only one they have, and which is what the published `false` asserts.

**This is the row's whole point.** A caller partitioning a worktree by mounts
gets the same answer from all three; a caller expecting the agent to commit its
own work gets a different one from `codex-python`, and the published boolean is
the only advance warning of it. CX-62 carries the mount table and the commands.

### `mcp.tool_call` — three timers, and no two builds are stopped by the same one

**Added 0.19.0, asked for by Agent Harness on 2026-08-18**, which hosts an MCP
server whose first tool holds the call open until another agent replies. Before
this the four values were reachable only by holding a call open until it died,
and the same mistake produced three different outcomes — a named timeout, a bare
transport error, and a success — which reads as three defects rather than one
difference.

**`gemini-python`'s `request_timeout_s` was published as `null` for a day, and
the consumer corrected it** (2026-08-19). Five separate reads of that agent's
bundle each said it imposes no such bound; a paid live call against the published
image, with no proxy variables set, gave up after **60.2 s**. The mechanism is
still not located and the value is published on the behaviour, which is the right
order. It is also the sharpest example of what this whole document is for: a
table assembled from source reads had a row that a single turn refuted.

They are not interchangeable, and a server clears them by different means:

| | Cleared by | Which build it stops |
|---|---|---|
| `request_timeout_s` | **responding** — SSE headers stop the clock | **claude-python AND gemini-python**, both at 60 s |
| `idle_timeout_s` | **a frame that counts** — see the flag below | claude-python, at 300 s |
| `total_timeout_s` | **nothing.** It expires while the call is healthy | gemini-python at 600 s, and **pi-python at 60 s** |

**Respond at once or two of the four builds cut you off** — and on a third,
responding does not save you at all. A server that buffers its whole answer and
replies with one JSON body is refused at a minute on claude-python and
gemini-python; opening an SSE stream immediately clears the bound on both, and
may then take 300 s between frames on claude-python and 600 s in total on
gemini-python.

**`pi-python` is the exception and it is the strictest build here.** Its 60 s is
a TOTAL bound: measured, a call is cut at about a minute whether the server never
answers, answers headers immediately, or answers headers and then sends data
every twenty seconds. **There is no way to hold a call open on that build.** A
tool that needs longer must return promptly and be polled, which is a different
design rather than a different timeout — and it is the one row here that has been
published wrong twice, first as `null` and then as a `request_timeout_s` that an
unclosed socket had faked.

**And the expiry CANCELS NOTHING**, which is the half that costs a server author
more than the number does. No notification is sent; the socket is dropped. So a
tool that has started work goes on doing it while the agent is told it timed out —
observed on our own stalling server, and reported independently by Agent Harness
about their `run_command`, which runs an agent-supplied command for up to ten
minutes and on this build is abandoned at one *while the command continues*.

**A server written for this build must expect to finish work nobody is listening
for.** Treating a dropped connection as a cancellation is wrong here; not
treating it as one leaks.

**The ceiling across the three that have MCP is 600 s and it belongs to gemini-python.** That
is wall clock: its agent applies the bundle's default to `tools/call` and never
passes the flag that would let a progress notification restart it, so emitting
progress there buys nothing. It sends a `progressToken` on every call anyway, to
drive its own display — which is exactly the shape a client mistakes for a
promise. **A short measurement on that build cannot tell the two apart**, and
publishing `progress_resets_idle: false` is what does.

**claude-python's idle timeout is transport-dependent and the published figure is
the strict one.** `stdio` gets 1800 s, `sse` and `http` get 300 s. A published
value is never more generous than the strictest transport in `transports`, so a
client planning against 300 is never surprised; the `stdio` generosity is
recorded here rather than in a field.

**codex-python's four nulls are `no bound`, not `not measured`** — the same
convention `server_name_pattern` uses. Its resolved MCP server config carries
`tool_timeout_sec: null` and its binary has no tool-call timeout message at all;
the only MCP timeout it can raise names the handshake. `progress_resets_idle` is
null there for the same reason: with no timer of any kind, `true` claims a mechanism
that is absent and `false` claims a restriction that is absent.

**Bounded again by the run, and that bound is already in `limits`.** A tool call
lives inside a turn, so the effective ceiling is the smaller of `total_timeout_s`
and the request's own `timeout_s` — capped by `limits.max_allowed_timeout_s`,
which is 1800 on claude-python and codex-python. On gemini-python the turn
default is 600 and so is the tool-call cap, which is a coincidence of two
figures rather than slack in either.

**No lever moves any of this per request.** `McpServer` carries no `timeout`
field on any variant on any build. claude-python's agent reads `MCP_TOOL_TIMEOUT`
and `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` from the environment and this service
sets neither, so they are an operator's surface and not a caller's.

### Before the container boots — the pre-boot facts diverge too

```
<impl>-<version>.json  ->  components.schemas.PrebootSpec
```

**No port, no credential, nothing running — and since 0.19.0 no image either.**
AS-25 and AS-29 put these facts on a surface a provisioner can read before
`docker create`; they were an `agent-service-spec` command inside the image
until 0.19.0 and are now `const`-pinned in each build's own document, which is
an artifact a consumer already resolves at build time. These fields differ per
build:

| Pre-boot field | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| `model_api` | `claude` | `codex` | `gemini` | **`pi` — the first value here that names NO vendor.** The other three map to one API each; this is one agent in front of thirty-plus providers chosen per request, so the consumer reads the request's own `model` for the vendor |
| `ca_bundle_source.variable` | `SSL_CERT_FILE` | `SSL_CERT_FILE` | **`NODE_EXTRA_CA_CERTS`** | `NODE_EXTRA_CA_CERTS` — Node's, like gemini's, and for the same reason: the runtime reads it, not the agent |
| `ca_bundle_source.replaces_default_trust` | false | **true** | false | false |
| `endpoint_source` | `ANTHROPIC_BASE_URL` | `OPENAI_BASE_URL` | `GOOGLE_GEMINI_BASE_URL` | **`HTTPS_PROXY` — not a base URL, because there is no single one to name.** This agent has one per PROVIDER, which is exactly the list the field's *singular* wording exists to avoid. The proxy is the only provider-agnostic redirect |
| `credential_sources` | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` | `OPENAI_API_KEY`, `CODEX_API_KEY` | `GEMINI_API_KEY` | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` — **the three measured end to end, and SHORTER than what the agent accepts.** A gate listing all thirty is a list nobody maintains |
| `provider_selectors` | Bedrock / Vertex / Foundry switches | **empty** — no measured equivalent | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_GCA` | **empty, and not for codex's reason.** Selection here is a per-request FLAG, so the choice lives in `RunOptions.model` rather than in the container's environment |

**`model_api` is IN CODE AND NOT YET IN A PUBLISHED IMAGE** (2026-08-16). Agent
Harness asked for it on 2026-08-15 and it is built in all three, but the images
delivered today -- `0.18.11`, `0.0.16`, `0.0.6` -- predate it, so a consumer
reading a running container will not find the field. **Absent and wrong differ**:
an image too old to publish it has never stated its API, and the inference from
`credential_sources` remains correct on all three in the meantime. This row moves
to unqualified when the images are cut.

**`pi-python` has NO image at all**, so its `model_api` is reachable only from
its published document -- which is where the value belongs anyway, and is the
whole point of `PrebootSpec`. It is also the one value here a consumer cannot
map to a vendor: see the row above.

**It names the TARGET FAMILY, and a consumer maps it to a vendor API** (user,
2026-08-16) -- **except on `pi-python`, where there is no vendor to map to** and
the request's own `model` carries it instead. Agent Harness proposed `anthropic` / `openai` / `gemini` so their
gateway could key an endpoint directly; the values published are the family, so
that mapping -- `claude` -> Anthropic, `codex` -> OpenAI -- lives on their side.
**They were told, and it is a row a client must act on**, which is what earns it
a place here.

**It is not a restatement of `impl.name`.** That field carries the implementation
language (`claude-python`) and this one does not, so a second build driving the
same target in another language would publish the same `model_api` and a different
`impl.name`. What it does NOT describe is a provider selector in use -- engaging
Bedrock or Vertex moves the transport and the auth, which is what
`provider_selectors` is published for.

**`schema_revision` is published pre-boot and is deliberately NOT a row above**
(2026-08-16). All four builds report `d3f9a0c15e27` and always will: they
migrate one database between them, so two images disagreeing about the revision
is a **defect** the boot gate exists to catch, not a divergence a client chooses
between. A row here would invite the reading that it varies by build.

**What a client does with it is compare, not branch.** It is the second half of
the pair an image is built against — `document_version` being the first — and it
is what lets a consumer check an image against the schema artifact they already
depend on without starting a container.

**Why these cannot wait for `/v1/deployment`.** Two things a provisioner does
happen strictly before a container can answer anything: choosing the environment
it is created with, and writing the CA file between `docker create` and
`docker start` — a runtime reads its trust store once at startup, so that file
cannot be added afterwards. A consumer that reads only the capability table
learns the CA variable one container too late.

**`replaces_default_trust` is the row that will cost someone a day.** It is
`true` on exactly one build, it is not inferable from anything else, and while
that variable is set that container **cannot verify a public host** — harmless
for a container that only ever talks to one privately-signed gateway, and not
harmless the day it needs an MCP server over public TLS.

**One variable set fleet-wide covers two builds of three and fails silently on
the third**: `SSL_CERT_FILE` does nothing on gemini-python, and the failure is a
refused connection inside the container rather than an HTTP error a gateway's
access log can be correlated with.

**A note about prose, since a consumer landed on the wrong document over it.**
The per-implementation `<impl>-<version>.json` carry the full field
descriptions; `core-<version>.json` is the structural intersection and carries
**none** — 0 of its 32 schemas have a description. So: *if you need the
reasoning, read a per-implementation document; `core` is shape only.*

## 3. What a caller may send

`RunOptions` has sixteen fields. **Four transfer cleanly and are worth naming
first, because a uniform field is a result rather than an absence:** `model`,
`timeout_s`, `include_partial_messages` and `include_raw` mean the same thing on
all four. `timeout_s` is uniform in *effect* because this service enforces it
rather than any SDK — though the two builds check its ceiling at different
moments, below.

**`resume` was the fifth and it was not true**, which is worth stating rather
than quietly correcting. Until 2026-09-08 `gemini-python` and `pi-python` read
the field nowhere at all: both answered `201` to a resume of an id they had
never issued and opened a fresh conversation, and the description they inherited
from the core — *continue a previous conversation*, and *with a database
configured the conversation survives a service restart* — was false in both
halves on those builds, where the database is a record and never a source. **The
consumer found it by asking what the field does rather than whether it is
accepted.** It is now wired on all four, over four unrelated mechanisms: an SDK
session id, a `thread_resume(thread_id)`, a `--session-file`, and a `--session
<id>` against a service-owned session directory. **What still diverges is the
refusal and the durability**, both rows below.

**`include_raw` joined that list on 2026-09-03** and `working_directory` left it
the same day, both by measurement rather than by design change.

**One row below is no longer only a row.** Durability was the question a
consumer could not answer from any document, so on 2026-09-08 it became
`behaviour.resume_durability` — a published value each build resolves at
deployment time, not prose. The row stays because it puts the four side by side
and names what each value costs; **the running service is the authority, and it
can disagree with this table for the same image in two deployments.**

The twelve that diverge:

| Field | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| `permission_mode` | six declared ids | the same six, mapped onto two internal axes | **four different ids** | **one id, `default`** |
| `permission_mode` **omitted** | **`dontAsk`**, deployment-settable | **`dontAsk`**, deployment-settable | **`default`**, a build constant | **`default`**, a build constant |
| `allowed_tools` | honoured — a per-**tool** grant, and **not a boundary**: `["Read"]` permits reading any path | **refused, 400** — governs by sandbox instead | honoured, and it **generates the policy file that is the boundary** | honoured, as `--tools`. **Not a boundary**: with no sandbox, a granted shell is the whole container. Neither built-in shell is granted by default |
| `disallowed_tools` | honoured | **refused, 400** | honoured — **subtracted from the effective allow set**, never written as a deny rule | honoured, and subtracted from the effective allow set for the same reason: the default grant contains `write`, so denying it alone must still remove it |
| `effort` | full vocabulary including `max` | `max` accepted and mapped to `xhigh`, and **no longer published** as available | **refused, 400** — no equivalent exists | **refused, 400 — although an equivalent DOES exist.** The only row in this table where a build refuses a capability its agent has, and §10 is why |
| `setting_sources` | full vocabulary | `user` and `project` only; other values refused per value | **refused, 400** | **refused, 400** — the switches exist but are per kind, not per layer |
| `max_turns` | enforced, and published in `limits` | **refused, 400** | **refused, 400** — the documented exit code was never reproduced | **refused, 400** — one invocation runs the agent's whole loop and no flag caps it |
| `max_budget_usd` | enforced against a figure that does not move for an interrupted turn | **refused, 400** | **refused, 400** — the agent reports no monetary figure at all | **refused, 400 — BECAUSE the figure is exact.** It arrives as each model call ends, so enforcing it means killing mid-loop and discarding the answer already paid for. A client sums `total_cost_usd` between turns instead, which is what publishing it is for |
| `system_prompt` | string **and** preset-object form. The string REPLACES Claude Code's own prompt; `{type: preset, preset: claude_code, append: "…"}` keeps it and adds to it | string only, mapped to `base_instructions`, which **replaces** the agent's framing; **the object form is refused by type** | string only, written to a file the agent reads through `GEMINI_SYSTEM_MD`, which **replaces** the built-in prompt entirely; object refused by type. **Wired 2026-09-02** — it was published, accepted and applied to nothing before that (`GP-66`) | string only, as `--system-prompt`, which **replaces** the built-in framing; object refused by type. **`--append-system-prompt` exists and is NOT wired** — it is the object form's keep-and-add semantics, but the object names another agent's preset, so there is nothing to keep |
| `mcp_servers` | honoured unless an operator turns MCP off | honoured; two transports, bearer-only headers | honoured; refused **per server**, not per field | honoured when the image carries the adapter, refused **per server** otherwise. **Whole-or-nothing**: granting MCP grants one proxy tool called `mcp`, so `allowed_tools` cannot name an individual MCP tool — see §9 |
| `strict_mcp_config` | operator-configured default | accepted | **`false` refused, `true` honoured** | **`false` refused, `true` honoured** |
| `working_directory` `NEW` | validated, then the agent's `cwd`. **Not confinement** — cwd and `add_dirs` restrict nothing | validated as of 2026-09-03 (`CX-64`); it is the thread's cwd, **and where `AGENTS.md` is read from** | honoured as of 2026-09-03 (`GP-68`), **and it is also a BOUNDARY**: the agent's own guard refuses a file tool outside the directory it started in | validated, then the agent's `cwd`. **NOT a boundary** — unlike gemini, this agent has no guard and no sandbox, so a subdirectory chooses where it starts and confines nothing |
| `allowed_tools` — unknown name | **accepted and dropped**, no 400 | n/a — the field is refused outright | **accepted and dropped**, no 400 | unmeasured |
| `resume` — an id that cannot be continued `NEW` | the SDK's own failure; a slow store fails the resume rather than starting fresh | **400** `resume-target-not-found`. A thread that took no turn has no rollout and cannot be resumed at all | **404** `resume-target-not-found` — same type, different status, matching this build's existing resume surface | **404** `resume-target-not-found`, and **it is two refusals**: an id that resolves to nothing, and one whose conversation was created under a different `working_directory`, which the agent resolves against and this build refuses at creation naming both directories |
| `resume` — how long an id stays resumable `NEW` | **`behaviour.resume_durability: "database"`** when one is configured, `"agent_local"` when not — measured with the CLI's own transcript deleted and the process replaced | **`"agent_local"`** — the `CODEX_HOME` rollout, and a configured database does NOT move it: there is no session-store seam here | **`"store_volume"`** — the `transcripts` volume. The database is a record, never a source | **`"store_volume"`** — the session store, which is NOT `config.workspace_dir`. `limits.session_idle_ttl_s` bounds a SESSION and not a conversation on any build: a resume opens a new one |

**A refusal is a 400 naming the field, never a silent drop.** That rule is the
one this platform has broken twice and corrected twice, and it cuts both ways:
publishing a field as refusable that a caller cannot send is the same defect
wearing the opposite coat — which is why `reference_dirs` is *not* in
gemini-python's `unsupported_options` despite being unwired.

### 3.0 Tool names — three sources, and an unknown one is dropped in silence

**Measured on 2026-09-03 across all three builds**, and it changes what a client
should render rather than only what it should expect.

**A name can come from three places, and only the first is publishable:**
**built-ins** (a property of the agent binary, its version and the *platform* —
one build advertises 31 while publishing 8); **MCP tools** named from the servers
in *this* request (`mcp__<server>__<tool>` on one build, `mcp_<server>_<tool>` on
another); and **skills, subagents and plugins** the agent reads from the
container's disk — §3.1's problem again, in the tool surface.

**An unrecognised name is accepted and dropped.** `allowed_tools: ["__nope__"]`
answers `201` on both builds that take the field, and a misspelled
`disallowed_tools` entry denies nothing. `always_disallowed_tools` is the same
behaviour with a published name attached: it is a **filter, not a refusal**.

So `default_allowed_tools` is a *default grant*, never a vocabulary to validate
against — and the honest schema keyword for the published names is `examples`,
not `enum`. **And `allowed_tools` grants permission, not visibility**: the model
is told about tools it may not use, attempts one, and is denied, which spends a
turn and shows up in `RunResponse.permission_denials`.

### 3.1 Ambient configuration — NO build lets the API replace it, and the document never said so

**State it once, plainly: on all four builds, the agent reads configuration
from disk inside the container, and `RunOptions` cannot supply that
configuration.** Not on any build, not in any field, not in any combination.
The HTTP contract can send *one block of prompt text* and, on two builds, a
*switch* over what gets loaded from disk. It cannot send a memory file, a skill,
a subagent, a slash command, a plugin, a hook or a settings file.

**This has been true since the first build and was written down nowhere**, which
is the part that misleads. An OpenAPI document describes the shape of a payload;
it is silent about a second input the agent has and the caller does not control.
A client author reading three documents end to end would conclude that
`RunOptions` is the whole request — and the agent they get is `RunOptions` **plus
whatever is on the container's disk**.

Two different questions, and they have different answers per build:

| | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| **SUPPLY it by request** — send memory, skills, subagents, commands, plugins, hooks | **no** | **no** | **no** | **no** |
| **SUPPRESS what is on disk** | **yes, fully** — `setting_sources: []`, and it is the server default (measured, `CP-060`) | **partly** — `setting_sources` without `project` suppresses `AGENTS.md`; `CODEX_HOME`'s own `config.toml` is read whatever you send, and `local` is a 400 | **no** — `setting_sources` is refused outright; a `GEMINI.md` or `.gemini/settings.json` in the mounted workspace is read on every turn | **yes, fully — but NOT by the API.** This build suppresses everything on every turn, by construction, and refuses the field. So the *deployment* is reproducible and the *request* still cannot change what is read |

**Per kind, and the empty column is the point:**

| Ambient input | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| Memory file (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`) | on/off only | on/off only (project layer) | **neither** | **neither** — and always OFF: `--no-context-files` on every invocation |
| Skills | **neither** — the SDK's `skills` is a name filter over what is on disk, never a definition | no concept | **neither** — `${AgentSkills}` interpolates what is on disk | **neither**, and always off. Worth knowing where they come FROM: `~/.agents/skills/`, outside the relocatable agent directory, so the image masks that path as well as passing `--no-skills` |
| Subagents | **neither** by API. The SDK accepts inline definitions; no `RunOptions` field carries them | no concept | **neither** | no concept |
| Slash commands, output styles, plugins | **neither** | **neither** (`CODEX_HOME` prompts) | **neither** | **neither** — prompt templates and extensions exist and are both switched off |
| Hooks | **neither** — server-side only, via `permission_enforcement` | n/a | n/a | n/a |
| Settings files (permissions, env) | partly — `allowed_tools`, `disallowed_tools`, `permission_mode`; scoped rules are not enforced | governed by sandbox instead | `allowed_tools` generates the policy file, which IS the boundary | partly — `allowed_tools` and `disallowed_tools` become `--tools` / `--exclude-tools`, which is a grant and not a boundary |
| MCP servers | **fully** — `mcp_servers`, and `strict_mcp_config: true` (the default here) shuts out `.mcp.json` | **fully** | **fully** — and `--allowed-mcp-server-names` is the one channel the workspace cannot override (`GP-47`) | **fully** — `--mcp-config` names this service's own file, so no path in the mounted workspace is read at all |

**MCP is the exception that proves the rest, on all four.** It is the one
ambient input a caller can both supply and suppress, and it got there by being
built that way deliberately — a repository registering a server means a
subprocess nobody asked for. `pi-python` was the exception to the exception for a
day, and is not any more.

**What stays different on that build is the GRANULARITY, not the control**:
supplying and suppressing both work, and `allowed_tools` cannot reach inside to
an individual MCP tool, because there is one proxy tool where the others have
many. [§9](#9-mcp-on-pi-python-is-a-proxy-tool-and-that-changes-what-allowed_tools-can-say)
is the shape and why the consumer asked for it anyway.

**A system prompt is not a substitute, and reading it as one is the trap.**
`system_prompt` replaces the agent's own framing on every build (see the row
above); it does not become memory, it does not register a skill, and on
gemini-python the ambient context files are still appended after it (`GP-66`).

**What a client should do with this:** treat the container's disk as part of the
deployment, not part of the request. Provision the workspace and the image
deliberately, and if a session must be reproducible, use claude-python with
`setting_sources: []` — that is the only combination in the table where the API
can state what the agent will *not* read.

## 4. The four that will catch someone

### `token_usage` — the same five names, and `input_tokens` does not mean the same thing

**Every build fills the object and two of the four include the cached half in
`input_tokens`.** The field is the specification's own spelling, so a client
reads one shape whichever image answered — and then sums it, which is where the
divergence bites:

| | claude-python | codex-python | gemini-python | pi-python |
|---|---|---|---|---|
| `input_tokens` | **excludes** the cache counts | **includes** `cache_read_tokens` (provider convention, not measured here) | **includes** `cache_read_tokens` (measured) | **excludes** the cache counts (measured) |
| `cache_read_tokens` | reported | reported | reported | reported |
| `cache_write_tokens` | reported | **null — no counter exists** | **null — no counter exists** | reported |
| `reasoning_output_tokens` | **null — not separated** | reported | **null — counted, then dropped by the CLI's own stream conversion** | reported — **but only on some providers.** openai and google send it on every turn; anthropic only when the model actually thought. **A divergence INSIDE one build**, which no other column here has |
| Prompt total for the turn | `input + cache_read + cache_write` | `input_tokens` | `input_tokens` | `input + cache_read + cache_write` |

So `input_tokens + cache_read_tokens` is the right prompt figure on **two**
builds and **double-counts on the other two** — and the split is not the one a
reader would guess from which vendor is underneath, which is the whole reason
this table exists. The arithmetic is verifiable on gemini
from the payload itself — the raw block carries `input` and `cached` beside
`input_tokens`, and `input + cached == input_tokens` on every model row. On
claude the counts are disjoint by the SDK's own shape (a measured turn reported
`input_tokens: 1200` beside `cache_read_input_tokens: 15488`, which no
subset reading survives). **Codex is the one cell here that rests on the
provider's convention rather than on our own arithmetic**, and it is stated that
way rather than levelled up — the raw block is beside the named counts on that
build too, which is the check a client can run for itself.

**The two `null` pairs are exact mirror images**, which is the strongest
argument the nullable design has: claude reports a cache write and no reasoning
count, codex reports a reasoning count and no cache write. Neither is zero, and
publishing zero would show a premium-billed cache write as free.

**One caveat about the delivered tag.** `gemini-python:0.0.5` publishes all five
counts as `null` on every turn — the mapper was never written, and the consumer
found it on 2026-08-14 by reading the raw block sitting beside it. **Fixed in
`0.0.6`**, built and verified against the tag on 2026-08-15; `GP-60` is the
entry. The row above describes `0.0.6`, and a consumer still on `0.0.5` reads
five nulls.

### `model_usage_scope` — three answers, one payload shape

The sharpest divergence in either table, because the shape is identical in all
three cases and only the *meaning* differs:

- **claude**: `cumulative`. `model_usage` accumulates over the connection while
  `usage` is per turn, so summing across a session multiplies the real figure by
  roughly the turn count.
- **gemini**: `per_turn`. Each turn reports its own figures, so summing is
  correct here and wrong there.
- **codex**: `not_reported`. `model_usage` is null on every turn and every
  session; the SDK has no per-model figure and deriving one would give it a scope
  it does not have.

*Sum it*, *difference it* and *skip it* are three different instructions for the
same key. A client cannot infer which applies and must read the field.

`turn_cost_usd` is a separate matter on the Claude build: it is already
differenced by the service, so one response carries per-turn money beside
cumulative tokens.

### `permission_enforcement` — `none` on all four, meaning four things

The field is `Literal["none", "hook"]`, a vocabulary written for a build with an
in-process `PreToolUse` hook. Two of the four confine the agent by means that
vocabulary has no member for, and the fourth is not confined in-process at all:

| Build | What actually confines a turn |
|---|---|
| claude-python | an in-process hook when configured; `none` by default, and `Bash` is unconfined — the container and its mount split are the boundary |
| codex-python | the **sandbox** — `read_only` / `workspace_write`, reported per request through `permission_mode` |
| gemini-python | a **generated admin-tier policy file**, preflighted keylessly before a session may use it |
| pi-python | **nothing in-process.** The agent has no sandbox and its own documentation says so; the tool allowlist is a grant rather than a boundary, and the container is the whole of it |

So all four answer `none` truthfully to the question the field actually asks —
*is there in-process write confinement* — and on three of them **that does not
mean the agent is unconfined.** On `pi-python` it very nearly does: the container
and its mount split are the only boundary there is, which is why that column
states it rather than leaving it to be inferred from a shared `none`.

### `llm_correlation` — two headers and one measured absence

All three answers were measured on the wire against a local sink, not read from
anyone's documentation: `x-claude-code-session-id` on claude, `thread-id` on
codex, and on gemini **null with `measured: true`** — the request arrived and not
one header carried the session id the agent had just reported on its own `init`
event. A gateway fronting that build must attribute spend some other way, and a
null that has been measured is a different fact from a null nobody checked.

## 5. The four decisions (dev-todo item 7)

**Item 7 asked four questions and was blocked on "a second implementation
actually serving traffic".** Three serve traffic as of 2026-08-13, all three
having taken real turns through the full path. The questions are answered below
from what shipped, and **the item is closed.**

### `permission_mode` should NOT become two axes — superseded, not rejected

The question was whether to split the field into a `sandbox` axis and an
`approvals` axis, on the grounds that Claude has one axis of six, Codex has two
independent axes, and Gemini has one axis of four.

**Overtaken by what shipped on 2026-08-11.** Each build now declares its own
`{id, name, description}` objects on `/v1/deployment`, `permission_mode` is an
opaque string, and a build refuses an id it did not declare with a 400. Gemini
publishes four ids that are **not** in the specification's original six and is
correct to. So the vocabulary stopped being shared, which is the thing the
two-axis redesign was trying to fix — and a shared two-axis vocabulary would
re-impose exactly the coupling that failed. **AS-32 answered it: publish the
difference, do not average it away.**

### `effort` keeps `max`

The question was whether to drop `max` from the enum because Codex has no
equivalent. **Keep it.** `effort_levels` is per-build and published, so a caller
reads what a build offers rather than inferring it — gemini publishes an empty
list and refuses the field outright, which is the vocabulary working. The one
gap this leaves is codex's silent narrowing, recorded in [§6](#6-two-defects-this-pass-found).

### `allowed_tools` survives, and the argument for dropping it was wrong

The 2026-08-08 case for deprecating it was that *"two of them are moving away
from tool lists toward sandboxes"*. **That premise is now false.** Gemini-python
moved the other way: a caller's `allowed_tools` generates the admin-tier policy
file, and that policy — not the approval mode — is the only thing that reliably
confines a turn on that build. Deprecating the field would remove the strongest
control one of the four has.

It means something different on each build, and each difference is published:
claude's per-tool grant that is explicitly not a boundary, codex's 400, gemini's
policy, and pi's grant over an agent with no sandbox underneath it at all.
**Keep it.**

### `max_budget_usd` stays published

The question was whether publishing an unenforceable limit is worse than not
publishing one. **Keep it.** Two of three refuse it in `unsupported_options` and
`reports_cost_usd` says which build can price at all, so a caller has two
machine-readable answers before it sends anything. Removing a field is the
breaking kind of change under AS-23 and would buy nothing those two do not
already deliver — the same conclusion 0.16.0 reached when it made
`SessionRecord.total_cost_usd` nullable rather than removing it.

### And `config_options` does not supersede this

`acp-review.md` §8.3 argues ACP's `config_options` — a positive list an agent
declares, rather than a negative list of refusals bolted onto a fixed
`RunOptions` — is a better answer than item 7 has. **It is, and it is not a
reason to keep the item open.** Adopting it is a breaking redesign of the request
surface, ACP was implemented and removed from gemini-python for unrelated
reasons, and `unsupported_options` plus per-build `permission_modes` already
delivered most of the value. It is a design note for a future major version, not
a blocker on a closed question.

## 6. Three defects these passes found — all fixed

Each was surfaced by refreshing the request-side table against the code rather
than against a document, and none is recorded anywhere else.

**~~`gemini-python` accepts `system_prompt` and never reads it.~~ FIXED
2026-09-02, the day it was found.** Same shape as the `disallowed_tools` defect
below, on the same build, and it survived four months longer because nothing
about a system prompt fails loudly: the field was published in the document, was
**not** in `unsupported_options`, and no module read it — the build consumed six
`RunOptions` fields and that was the whole list. A caller sent framing, got a
`201`, and was served an agent that had never seen it.

**The string form now reaches the agent through `GEMINI_SYSTEM_MD`** — written
into the session's own HOME at provisioning, passed as an absolute path so the
switch form cannot resolve inside the caller's writable workspace — and the
preset object is refused by type, exactly as codex-python refuses it. Verified
by a live turn with a control: `ready` without it, `ready ZEBRA-7788` with it.
**The first live run failed**, because both ends were wired and the line joining
them was not; the unit tests covered each end and not the seam. `GP-66`.

**~~`gemini-python` accepts `disallowed_tools` and never reads it.~~ FIXED
2026-08-14, the day it was found.** The field was in neither
`unsupported_options` nor any module: a caller sending
`disallowed_tools: ["write_file"]` and no `allowed_tools` got the default
allow-list — **which contains `write_file`** — so a tool the caller asked to deny
stayed available for the whole session. Exactly the *accepted and silently
ignored* defect the platform treats as its worst kind, on the build whose own
notes describe correcting it elsewhere.

**Honoured rather than refused**, because the policy engine expresses it
natively: the caller's list is subtracted from whichever allow set is in force,
in `_permitted`. **Subtracting is required rather than stylistic** — a rule
denying a tool by name removes it from the model's context and the agent reaches
for the shell to do the same work, while under deny-`*` an absent name is simply
never allowed. Two tests cover it, both verified to fail without the change: the
default-list case that actually bit, and the caller-sent-both case. The entry is
`GP-57`.

**~~`codex-python` publishes `max` in `effort_levels` and narrows it to
`xhigh`.~~ FIXED 2026-08-14.** The narrowing is deliberate and stays — refusing a
caller for asking for more effort than the SDK can express helps nobody — but it
was invisible, so a client optimising for maximum reasoning could not tell it had
not got it.

**The `unsupported_options` route was considered and rejected**: `values` means
*refused with a 400*, so publishing `{field: "effort", values: ["max"]}` would
have promised a refusal this build does not make, and changed behaviour for every
caller currently sending `max`. Instead `effort_levels` now publishes what the
build delivers **exactly** — derived as the identity half of the mapping table,
so it cannot drift — and `max` drops out on its own. Behaviour is unchanged.
`CX-53`.

## 7. Each build in one line

- **claude-python** — the only one that refuses almost nothing, and the least
  confined: `Bash` is unrestricted and the container is the whole boundary.
- **codex-python** — the most confined, and the only one with no network from the
  agent's shell. It refuses the most `RunOptions` fields, publishes the fewest
  `limits` (only what it actually enforces), and its `/v1/query` opens a real
  session, so it can answer 429 where the others cannot.
- **gemini-python** — no SDK at all. A different permission vocabulary, no effort
  dial, **no setting sources at all — so nothing a caller sends can stop the
  mounted workspace's `GEMINI.md` or `.gemini/settings.json` being read**, the
  shell permanently denied, an MCP server-name
  pattern the others do not need, and ~7,000 input tokens of overhead before the
  prompt is read, which makes turn *count* rather than prompt length the thing
  that predicts spend.
- **pi-python** — the only one in front of **more than one vendor**, which is
  where most of its column comes from: `model_api` names no API, `endpoint_source`
  is a proxy because there is no single base URL, and the shape of `usage` itself
  differs **between providers inside this one build**. It prices a turn exactly
  and *refuses* `max_budget_usd` because the price arrives too late to enforce;
  it has the thinnest permission vocabulary of the four (one mode) and no sandbox
  whatever; it adopts a caller-supplied session id and keeps it stable across
  turns; and at ~550 tokens of overhead it is an order of magnitude cheaper per
  turn than gemini-python. It is also the only build with MCP refused outright.

## 8. What this means for a client

**Read `/v1/deployment` instead of branching on which image you have.** That is
AS-32, and every difference above is published rather than left to be discovered
from a 400 or from a figure that quietly disagrees with the bill.

Two failure modes the specification treats as the same defect, wearing opposite
coats:

- **An option accepted and silently ignored.** The Codex build shipped this
  twice — publishing four `limits` figures it applied none of — and
  gemini-python's `disallowed_tools` was a third instance, fixed 2026-08-14,
  its `system_prompt` a fourth, fixed 2026-09-02.
- **An option published as refusable that can never be sent.** The Gemini build
  listed `reference_dirs` in `unsupported_options`, promising a 400 that could
  never happen; it is a capability field, not a `RunOptions` one. The honest
  statement of an unwired `--include-directories` is `reference_dirs: []`.

The conformance suite caught the second. Both are the same drift: a published
capability that disagrees with what the code does.

**And a third, which no clause catches yet: a second input the document does not
mention at all.** Every field above is about what a caller *sends*. The agent
also reads its own configuration off the container's disk — memory files,
skills, subagents, commands, plugins, settings — and **no `RunOptions` field on
any build can supply that, while only claude-python can fully switch it off.**
[§3.1](#31-ambient-configuration--no-build-lets-the-api-replace-it-and-the-document-never-said-so)
is the table. A client that treats its request as the whole input is wrong on
all four builds, and nothing in an OpenAPI document would have told it.

**`pi-python` is the one build where the deployment is reproducible and the
request still cannot change it.** Every invocation suppresses context files,
skills and extensions by construction, so nothing on the container's disk reaches
a turn — and `setting_sources` is refused, so a caller cannot ask for any of it
back. That is a better *outcome* than the other three and the same *contract*:
the API still supplies nothing.

## 9. MCP on `pi-python` is a PROXY tool, and that changes what `allowed_tools` can say

**Measured 2026-09-07 against a real stdio server**, with the model made to
repeat a string it could not have invented. It worked — and the build **refused
the field anyway for one day**, until Agent Harness answered that they wanted it
in exactly this form. It is built. This section is the shape it has and why that
shape is a difference a client must act on.

`pi install npm:pi-mcp-adapter` puts 42 packages inside the agent directory,
registers a `--mcp-config` flag, and honours an `mcp.json`. Then:

```
tool_execution_start  toolName "mcp"  args {"server": "spikeserver"}
tool_execution_end    -> "spikeserver (1 tools (lazy: not connected yet ...))"
tool_execution_start  toolName "mcp"  args {"tool": "spikeserver_magic_word"}
tool_execution_end    -> "MAGIC-WORD-FROM-MCP"
```

**The agent sees ONE tool, called `mcp`.** It never sees `magic_word`, and there
is no `mcp__spikeserver__magic_word` for anything to name. Three consequences a
client must act on, and the first is why the field is refused rather than shipped:

- **`allowed_tools` cannot govern an individual MCP tool here.** It can permit or
  deny `mcp` — every server, every tool, or none. [§3.0](#30-tool-names--three-sources-and-an-unknown-one-is-dropped-in-silence)
  says a tool name can come from three places and that MCP names come from the
  servers in *this* request; that sentence has no `pi-python` column, because the
  names do not exist to be granted against.
- **And granting MCP means adding one name, `mcp`, to the allowlist.** Forgetting
  it is silent: the servers register, the adapter loads, and the model reports —
  helpfully, at exit 0, having spent money — that no such tool exists.
- **Discovery costs turns.** Three, to answer one question — discover the server,
  list its tools, call one — where a build with real tool names takes one.
- **Servers are lazy.** Nothing is spawned until a tool is actually called, which
  is better than the hazard `strict_mcp_config` exists to guard against.

**The timers were measured on 2026-09-07 and are no longer null.**
`request_timeout_s` is **60** here as on claude-python and gemini-python: a
server that sends no response headers is cut at about a minute, and one that
opens its stream immediately is not — 268 s and still open when the observation
ended. The remaining two nulls mean *no bound observed up to 268 s*.

**That is the row a consumer hosting a slow tool must act on**, and it is why
this section stopped being about a refusal and became about a shape.

## 10. The question a fourth build raised about the FIELD itself

**`effort_levels` is empty on `pi-python` although the agent has a thinking
dial**, and that is the only row in [§2](#2-what-the-service-publishes) where a
build gives up a capability its agent demonstrably has. It is here rather than in
a build's own notes because the obstacle is the field's shape, not the build's.

`--thinking` takes `off, minimal, low, medium, high, xhigh, max`. But the dial is
per **model**: asked with no model configured, the agent answers `["off"]`, and
its own model catalogue marks thinking yes/no per entry. The field means *levels
this build delivers **exactly***, and a level silently mapped onto another is not
listed — so:

- publishing the full vocabulary claims exact delivery for models that ignore it;
- publishing an intersection across reachable models is narrower than the truth
  for most requests **and depends on which credentials a deployment holds**,
  which is not a build fact and cannot go in a deployment-invariant document;
- refusing the field is accurate and throws away a real capability.

The build took the third. **The same shape threatens `accepts.limits` and
`config.default_model`** on any future target that fronts more than one vendor,
and this is the first one that does.

**One thing this same build settled in the specification's favour**, so the
pressure is narrower than it first looked: `RunOptions.model` did **not** need a
companion `provider` field. The agent's own `--model` accepts `provider/id`
— measured, `anthropic/claude-haiku-4-5` with no provider flag billed anthropic
and answered — so a qualified model string is self-contained and the shared core
was untouched.
