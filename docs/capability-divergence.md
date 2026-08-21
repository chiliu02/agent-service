# How the three builds differ, field by field

**Same shape, different values — and that split is the design rather than an
accident.** All three implementations answer the identical `Capabilities` model
from `impl/common/agent-spec`, serve the same fourteen `/v1` operations, and
share one conformance suite. A client parses one payload whichever image it has.
What it *reads out of* that payload diverges on nearly everything behavioural.

**Both halves of the contract are here.** [§2](#2-what-the-service-publishes)
is what a caller **reads** — the `/v1/capabilities` response. [§3](#3-what-a-caller-may-send)
is what a caller **sends** — `RunOptions`, and which builds refuse which fields.
The two were separate documents until 2026-08-14; `options-divergence.md` was
merged in when [§5](#5-the-four-decisions-dev-todo-item-7) closed the open item
that had kept it a decision backlog rather than a reference.

**There are TWO published surfaces, not one, and the second is cheaper to read
than the first.** `/v1/capabilities` needs a running container; the pre-boot
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
Every value below is read from the source rather than from a delivery document,
and a build bump can move any of them. **`GET /v1/capabilities` on the container
in front of you is what a client acts on** — this file exists so a reader can see
the three side by side without starting three containers, which is the one thing
three OpenAPI documents cannot show.

The values live in
[`impl/claude-python/src/agent_service/api.py`](../impl/claude-python/src/agent_service/api.py)
(`_capabilities_payload`),
[`impl/codex-python/src/agent_service/api.py`](../impl/codex-python/src/agent_service/api.py)
(`_capabilities_payload`, and `options.py` for the request side) and
[`impl/gemini-python/src/agent_service/capabilities.py`](../impl/gemini-python/src/agent_service/capabilities.py)
(`build_capabilities`). The shared model is in
[`impl/common/agent-spec/src/agent_spec/openapi/schemas.py`](../impl/common/agent-spec/src/agent_spec/openapi/schemas.py).

---

## 1. What is identical

The convergence is real, and it is where the product's value sits:

- **One `Capabilities` model**, one set of fourteen `/v1` operations, one error
  vocabulary, one session lifecycle, one set of boot gates.
- **One conformance suite** in `spec/conformance/`, which judges each build
  against the specification rather than against itself.
- **One shared core** across the three OpenAPI documents. Adding the third build
  removed **zero** leaves from it, and cost the specification no new clause —
  two new entries in one probe table. The eleven fixes it did cost all landed
  inside the new build.

- **One event surface**, since 2026-08-14. `AgentEvent.content` carries
  normalised text blocks on all three, and `type` is the authoritative
  discriminator.

That is the claim the repository makes, and the third build is what tested it.

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

Now: `content` is described and filled by all three, and `type` is documented as
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

| Field | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `sdk.name` | `claude-agent-sdk` | `openai-codex` | `gemini-cli` — **no SDK exists**, a Node CLI spawned per turn |
| `model_usage_scope` `°` | `cumulative` | `not_reported` | `per_turn` |
| `reports_cost_usd` `°` | **true** | false | false |
| `sdk_session_id_scope` `°` | `conversation` | `conversation` | **`turn`** |
| `allow_supplied_sdk_session_id` | **true** | false | false |
| `query_reports_sdk_session_id` `°` | false | true | true |
| `query_consumes_a_session_slot` `°` | false | **true** | false |
| `llm_correlation.header` `°` | `x-claude-code-session-id` | `thread-id` | **null**, `measured: true` |
| `sandbox.network_access` | true | **false** (bubblewrap) | true |
| `sandbox.confines_writes_to_workspace` | false | **true** | false |
| `permission_enforcement` `°` | `none` by default, `hook` available | `none` | `none` |
| `permission_modes` | `default`, `acceptEdits`, `plan`, `dontAsk`, `auto`, `bypassPermissions` | the same six | **`default`, `auto_edit`, `yolo`, `plan`** |
| `effort_levels` `°` | full vocabulary | **all but `max`** — the one level it cannot deliver exactly | **empty** |
| `setting_sources` | full vocabulary | **`user`, `project`** | **empty** |
| `default_allowed_tools` | operator-configured | operator-configured | five read/write/search tools, **no shell** |
| `always_disallowed_tools` | `AskUserQuestion` | none | **`run_shell_command`** |
| `mcp.transports` | `stdio`, `sse`, `http` | **`stdio`, `http`** | all three |
| `mcp.http_headers` | `any` | **`bearer_only`** | `any` |
| `mcp.server_name_pattern` | null | null | **a real pattern** |
| `mcp.tool_call.request_timeout_s` | **60** | null | **60** |
| `mcp.tool_call.idle_timeout_s` | **300** | null | null |
| `mcp.tool_call.total_timeout_s` | 100000 | null | **600** |
| `mcp.tool_call.progress_resets_idle` | **true** | null | **false** |
| `strict_mcp_config` | operator-configured default | true | **true, and refuses `false`** |
| `limits` | turns + budget + timeout + idle TTL | **timeout + idle TTL only** | turn timeout + max sessions + idle TTL |
| `turn_token_overhead` `°` | — | — | **7000** |

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
| `total_timeout_s` | **nothing.** It expires while the call is healthy | gemini-python, at 600 s |

**Respond at once or two of the three builds cut you off**, which is the single
most actionable line in this section. A server that buffers its whole answer and
replies with one JSON body is refused at a minute on both; a server that opens an
SSE stream immediately clears the bound on both and may then take 300 s between
frames on claude-python and 600 s in total on gemini-python.

**The ceiling across the three is 600 s and it belongs to gemini-python.** That
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

| Pre-boot field | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `model_api` | `claude` | `codex` | `gemini` |
| `ca_bundle_source.variable` | `SSL_CERT_FILE` | `SSL_CERT_FILE` | **`NODE_EXTRA_CA_CERTS`** |
| `ca_bundle_source.replaces_default_trust` | false | **true** | false |
| `endpoint_source` | `ANTHROPIC_BASE_URL` | `OPENAI_BASE_URL` | `GOOGLE_GEMINI_BASE_URL` |
| `credential_sources` | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` | `OPENAI_API_KEY`, `CODEX_API_KEY` | `GEMINI_API_KEY` |
| `provider_selectors` | Bedrock / Vertex / Foundry switches | **empty** — no measured equivalent | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_GCA` |

**`model_api` is IN CODE AND NOT YET IN A PUBLISHED IMAGE** (2026-08-16). Agent
Harness asked for it on 2026-08-15 and it is built in all three, but the images
delivered today -- `0.18.11`, `0.0.16`, `0.0.6` -- predate it, so a consumer
reading a running container will not find the field. **Absent and wrong differ**:
an image too old to publish it has never stated its API, and the inference from
`credential_sources` remains correct on all three in the meantime. This row moves
to unqualified when the images are cut.

**It names the TARGET FAMILY, and a consumer maps it to a vendor API** (user,
2026-08-16). Agent Harness proposed `anthropic` / `openai` / `gemini` so their
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
(2026-08-16). All three builds report `d3f9a0c15e27` and always will: they
migrate one database between them, so three images disagreeing about the revision
is a **defect** the boot gate exists to catch, not a divergence a client chooses
between. A row here would invite the reading that it varies by build.

**What a client does with it is compare, not branch.** It is the second half of
the pair an image is built against — `document_version` being the first — and it
is what lets a consumer check an image against the schema artifact they already
depend on without starting a container.

**Why these cannot wait for `/v1/capabilities`.** Two things a provisioner does
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

`RunOptions` has sixteen fields. **Six transfer cleanly and are worth naming
first, because a uniform field is a result rather than an absence:** `model`,
`resume`, `timeout_s`, `workspace_subdir`, `include_partial_messages` and
`include_raw` mean the same thing on all three. `timeout_s` is uniform *because*
it is enforced by this service rather than by any SDK, and `resume` is uniform
despite three unrelated mechanisms underneath — an SDK session id, a
`thread_resume(thread_id)`, and a `--session-file`.

The other ten diverge:

| Field | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `permission_mode` | six declared ids | the same six, mapped onto two internal axes | **four different ids** |
| `allowed_tools` | honoured — a per-**tool** grant, and **not a boundary**: `["Read"]` permits reading any path | **refused, 400** — governs by sandbox instead | honoured, and it **generates the policy file that is the boundary** |
| `disallowed_tools` | honoured | **refused, 400** | honoured — **subtracted from the effective allow set**, never written as a deny rule |
| `effort` | full vocabulary including `max` | `max` accepted and mapped to `xhigh`, and **no longer published** as available | **refused, 400** — no equivalent exists |
| `setting_sources` | full vocabulary | `user` and `project` only; other values refused per value | **refused, 400** |
| `max_turns` | enforced, and published in `limits` | **refused, 400** | **refused, 400** — the documented exit code was never reproduced |
| `max_budget_usd` | enforced against a figure that does not move for an interrupted turn | **refused, 400** | **refused, 400** — the agent reports no monetary figure at all |
| `system_prompt` | string **and** preset-object form | string only; **the object form is refused by type** | string |
| `mcp_servers` | honoured unless an operator turns MCP off | honoured; two transports, bearer-only headers | honoured; refused **per server**, not per field |
| `strict_mcp_config` | operator-configured default | accepted | **`false` refused, `true` honoured** |

**A refusal is a 400 naming the field, never a silent drop.** That rule is the
one this platform has broken twice and corrected twice, and it cuts both ways:
publishing a field as refusable that a caller cannot send is the same defect
wearing the opposite coat — which is why `reference_dirs` is *not* in
gemini-python's `unsupported_options` despite being unwired.

## 4. The four that will catch someone

### `token_usage` — the same five names, and `input_tokens` does not mean the same thing

**Every build fills the object and two of them already include the cached half
in `input_tokens`.** The field is the specification's own spelling, so a client
reads one shape whichever image answered — and then sums it, which is where the
divergence bites:

| | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `input_tokens` | **excludes** the cache counts | **includes** `cache_read_tokens` (provider convention, not measured here) | **includes** `cache_read_tokens` (measured) |
| `cache_read_tokens` | reported | reported | reported |
| `cache_write_tokens` | reported | **null — no counter exists** | **null — no counter exists** |
| `reasoning_output_tokens` | **null — not separated** | reported | **null — counted, then dropped by the CLI's own stream conversion** |
| Prompt total for the turn | `input + cache_read + cache_write` | `input_tokens` | `input_tokens` |

So `input_tokens + cache_read_tokens` is the right prompt figure on one build
and **double-counts on the other two.** The arithmetic is verifiable on gemini
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

### `permission_enforcement` — `none` on all three, meaning three things

The field is `Literal["none", "hook"]`, a vocabulary written for a build with an
in-process `PreToolUse` hook. Two of the three confine the agent by means that
vocabulary has no member for:

| Build | What actually confines a turn |
|---|---|
| claude-python | an in-process hook when configured; `none` by default, and `Bash` is unconfined — the container and its mount split are the boundary |
| codex-python | the **sandbox** — `read_only` / `workspace_write`, reported per request through `permission_mode` |
| gemini-python | a **generated admin-tier policy file**, preflighted keylessly before a session may use it |

So all three answer `none` truthfully to the question the field actually asks —
*is there in-process write confinement* — and **none of them means the agent is
unconfined.**

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
`{id, name, description}` objects on `/v1/capabilities`, `permission_mode` is an
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
control one of the three has.

It means something different on each build, and each difference is published:
claude's per-tool grant that is explicitly not a boundary, codex's 400, gemini's
policy. **Keep it.**

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

## 6. Two defects this pass found — one fixed, one open

Both were surfaced by refreshing the request-side table against the code rather
than against the 2026-08-08 document, and neither is recorded anywhere else.

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

- **claude-python** — the only one that prices a turn, the only one that adopts a
  caller-supplied session id, the only one that refuses almost nothing, and the
  least confined: `Bash` is unrestricted and the container is the whole boundary.
- **codex-python** — the most confined, and the only one with no network from the
  agent's shell. It refuses the most `RunOptions` fields, publishes the fewest
  `limits` (only what it actually enforces), and its `/v1/query` opens a real
  session, so it can answer 429 where the others cannot.
- **gemini-python** — no SDK at all. A different permission vocabulary, no effort
  dial, no setting sources, the shell permanently denied, an MCP server-name
  pattern the others do not need, and ~7,000 input tokens of overhead before the
  prompt is read, which makes turn *count* rather than prompt length the thing
  that predicts spend.

## 8. What this means for a client

**Read `/v1/capabilities` instead of branching on which image you have.** That is
AS-32, and every difference above is published rather than left to be discovered
from a 400 or from a figure that quietly disagrees with the bill.

Two failure modes the specification treats as the same defect, wearing opposite
coats:

- **An option accepted and silently ignored.** The Codex build shipped this
  twice — publishing four `limits` figures it applied none of — and
  gemini-python's `disallowed_tools` was a third instance, fixed 2026-08-14.
- **An option published as refusable that can never be sent.** The Gemini build
  listed `reference_dirs` in `unsupported_options`, promising a 400 that could
  never happen; it is a capability field, not a `RunOptions` one. The honest
  statement of an unwired `--include-directories` is `reference_dirs: []`.

The conformance suite caught the second. Both are the same drift: a published
capability that disagrees with what the code does.
