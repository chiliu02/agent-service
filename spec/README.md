# `spec/` — one version, and it is the current one

**Three directories, one per kind of artifact** (user, 2026-08-19):

| | |
|---|---|
| `openapi/` | the HTTP contract — one document per implementation, plus the computed core. **`spec/VERSION` and nothing else**: there are no version directories |
| `database/` | the rendered DDL, one file per Alembic revision. **A different stream**: it moves when a migration lands, not when the document does, and three implementations share it |
| `conformance/` | the suite that judges an implementation against the specification, and the one fixture it needs that is not a delivery |

**`openapi/` is a name with a history and this is not that history.** There was a
`spec/openapi/` until 2026-08-08, collapsed because every document
existed twice — a canonical there and a delivery copy elsewhere — with a sha256
table and a byte comparison kept in step for nothing else. This holds one copy
and there is nothing to compare it against.

**`0.19.0` through `0.24.0` are the releases**, and `spec/openapi/` carries
whatever `spec/VERSION` says. It holds a bare version only in the one commit a tag
names; main moves on to the next snapshot immediately after.
Eighteen versions were cut before them under an older process and none of them is a release under this one;
their documents are not carried in the working tree, nor in this repository's
history. **Agent Harness depends on `>= 0.19.0` from now on** (user,
2026-08-19), which is what makes that safe.

## The lifecycle

| State | Where | Editable |
|---|---|---|
| current, in flight | `openapi/<impl>-<version>-snapshot.json` | **yes** — a snapshot is never frozen |
| cut | the same files, renamed to a bare version, in one commit | no — and the commit is tagged |
| released | `release-<version>` | **never** |

**THE TAG IS THE FREEZE.** A release is an immutable commit named
`release-<version>`, and the spec Maven package, the schema Maven package and the
three implementation images are all **built from that tag**. A directory can be
edited; a tag cannot, and the one way to change what a release means is to move
the tag — which the table below is here to catch.

**Main is always a `-snapshot`.** The bare state exists at exactly one commit,
the one the tag names, and the next commit moves `spec/VERSION` on to the next
snapshot. So a bare version in this directory means a cut is in progress, and
`ci.py`'s `freeze` stage says so rather than failing.

## Released versions

**`freeze` checks this table on every run**: a tag that no longer points at the
commit recorded here has been moved, and that is now the only way a released
version can change. Git makes the rest impossible.

| Version | Tag | Commit |
|---|---|---|
| `0.19.0` | `release-0.19.0` | `979450d68f8262a0a5d250ab5735e4f80a24b35b` |
| `0.20.0` | `release-0.20.0` | `f7dbd5bda5bb9d715764a61525e141d1d175ac5e` |
| `0.21.0` | `release-0.21.0` | `59c491353b421cb483fd7332ed45e874f3e4d53e` |
| `0.22.0` | `release-0.22.0` | `a872f1f3159af69116d88feed6f9563bc0ea7149` |
| `0.23.0` | `release-0.23.0` | `ec7614d3b68fe9e27672f989c69161d6afc6d992` |
| `0.24.0` | `release-0.24.0` | _(filled in when the tag is made)_ |

**The row is written in the commit AFTER the one the tag names**, and it cannot be
otherwise: it carries the commit's own hash. So the tag's tree does not contain
its own row, and `freeze` reads the row from the working tree rather than from the
tag — which is the direction that matters, since what it guards against is the tag
moving afterwards.

---

# `0.24.0` — what a deployment must keep for a resume to work

**Additive. Nothing breaks.** One field joins `behaviour` on all four documents
and two builds declare one more response code. The core did not shrink, the DDL
is untouched at `d3f9a0c15e27`, and no existing field was removed, renamed or
re-typed.

| | |
|---|---|
| Documents | `openapi/claude-python-0.24.0.json`, `openapi/codex-python-0.24.0.json`, `openapi/gemini-python-0.24.0.json`, `openapi/pi-python-0.24.0.json` |
| Core | `openapi/core-0.24.0.json` — the intersection of all four, and it **gained** a leaf |
| Images | **all four at implementation `0.24.0`** — see §4 |
| Database | **`agent-service-database` stays at `1.3.0`** — no migration landed |

## 1. What is added

**`behaviour.resume_durability`**, a required string naming the one thing a
deployment must keep for `options.resume` to work after a restart or a container
replacement. Four values:

| value | keep |
|---|---|
| `database` | the configured database; the conversation is reconstructed from it |
| `store_volume` | this service's own conversation store. A configured database is a record and **never** a source |
| `agent_local` | the agent's own on-disk state inside the container. **A container replacement loses it** unless that path is mounted |
| `none` | nothing outlives the process |

**It is resolved per DEPLOYMENT, not only per build.** `claude-python` answers
`database` when one is configured and `agent_local` when none is, so the same
image gives two different honest answers.

| Build | value |
|---|---|
| `claude-python` | `database`, or `agent_local` with no database configured |
| `codex-python` | `agent_local` — the `CODEX_HOME` rollout. **A configured database does not change this** |
| `gemini-python` | `store_volume` — the transcripts volume |
| `pi-python` | `store_volume` — the session store volume, **not** `workspace_dir` |

**`limits.session_idle_ttl_s` does not bound any of this.** It closes an idle
session; a resume opens a new one.

## 2. What changed in an existing field

**`RunOptions.resume`'s description stops asserting a mechanism.** It said *"with
a database configured the conversation survives a service restart"*, which is
true of `claude-python` and false of the other three. It now points at
`behaviour.resume_durability`. **Prose only — the field's type, name and
behaviour are unchanged.**

## 3. What changed in behaviour, which is not visible in the document

**`options.resume` now works on `gemini-python` and `pi-python`.** It was
accepted and applied to nothing on both: each answered `201` to a resume of an id
it had never issued, and opened a fresh conversation. Both now resolve an id
through an on-disk index that outlives a `DELETE` and the idle sweep.

**`POST /v1/sessions` declares `404` on those two builds** — problem type
`resume-target-not-found`, for an `options.resume` naming a conversation this
deployment does not have.

**One divergence to design around:** the same condition is a **400** on
`codex-python` and a **404** on `gemini-python` and `pi-python`. Same problem
`type`; each build matches its own existing resume surface.

**`pi-python` refuses one more case:** a conversation created under one
`working_directory` and resumed under another. The agent finds it and then asks
interactively whether to fork, which a non-interactive turn cannot answer.

## 4. Implementation versions are aligned from this release

**All four images are `0.24.0`**, including builds whose code barely changed and
a young build that would otherwise be at `0.2.0`. From this release an
implementation's `x.y` mirrors the document's, so an image tag is readable
without a lookup. `0.23.0` was the last release of the older scheme, where the
three mature builds were at `0.22.0` and `pi-python` at `0.2.0`.

## 5. What a consumer does

**Nothing is required.** If you rely on `options.resume`, read
`behaviour.resume_durability` from `GET /v1/deployment` and make sure the path it
names is on a volume that survives your cutover. If you deploy `gemini-python` or
`pi-python`, handle `404` from `POST /v1/sessions` as *no such conversation*
rather than as a malformed request.

---

# `0.23.0` — the mode you get by omitting `permission_mode`

**Additive. Nothing breaks.** One field joins `accepts` on all four documents.
The core did not shrink, the DDL is untouched at `d3f9a0c15e27`, and no existing
field was removed, renamed or re-typed.

| | |
|---|---|
| Documents | `openapi/claude-python-0.23.0.json`, `openapi/codex-python-0.23.0.json`, `openapi/gemini-python-0.23.0.json`, `openapi/pi-python-0.23.0.json` |
| Core | `openapi/core-0.23.0.json` — the intersection of all four, unchanged in size |
| Images | claude, codex and gemini at implementation `0.22.0`; **pi-python at `0.2.0`** |
| Database | **`agent-service-database` stays at `1.3.0`** — no migration landed |

## 1. What is added

**`accepts.default_permission_mode`**, a required string naming the permission
mode a session runs under when a request omits `RunOptions.permission_mode`. Its
value is always one of `permission_modes[].id`, and a conformance clause asserts
both halves.

**`default` the id and *the default* are not the same thing**, which is the whole
reason the field exists:

| Build | value | |
|---|---|---|
| `claude-python` | `dontAsk` | *never prompt; deny anything not pre-approved* |
| `codex-python` | `dontAsk` | *writes inside the workspace and never pauses* |
| `gemini-python` | `default` | prompts for approval, which headless means the agent decides — **not deterministic** |
| `pi-python` | `default` | its only mode |

**The two `dontAsk` builds point in opposite directions.** On `claude-python`,
`dontAsk` is more restrictive than the mode called `default`. On `codex-python`
it is less — `default` there is a read-only sandbox. So the same value is the
shipped default on both and means something different on each.

**It is deployment-settable on two builds and a constant on two.**
`claude-python` and `codex-python` read `AGENT_SERVICE_DEFAULT_PERMISSION_MODE`,
so two containers of one image can answer differently and the value belongs to
the container rather than the tag. `gemini-python` and `pi-python` move it only
at a release.

**`GET /v1/schemas/run-options` carries it too**, as
`properties.permission_mode.default`.

## 2. What breaks

**Nothing.** The field is additive, and it is required only in the sense every
other published capability is: the service always sends it. A client that ignores
it behaves exactly as it did at `0.22.0`.

## 3. What a consumer does

**Nothing is required.** Move your version constant and the payload gains a field.

**If you offer *use the build's own* as a permission choice**, this is the field
that says what that choice means, and it is the only place the answer exists.
Read it per container rather than per image.

**If you generate a form from `GET /v1/schemas/run-options`**, stop preselecting
the head of the `oneOf` — on the two `dontAsk` builds that is the wrong mode.
`properties.permission_mode.default` is now correct.

**Asked for by Agent Harness (2026-09-07)**, after a worker registered with no
permission mode read, planned and delegated correctly and then had every write
denied outright, with the denial surfacing nowhere but the agent's own prose.

---

# `0.22.0` — a fourth build, and nothing else moves

**Additive. Nothing breaks.** If you do not intend to run `pi-python`, moving a
pin to `0.22.0` costs one constant: the three documents you already read are
unchanged in every field a client acts on, the core did not shrink, and the DDL
is untouched at `d3f9a0c15e27`.

| | |
|---|---|
| Documents | `openapi/claude-python-0.22.0.json`, `openapi/codex-python-0.22.0.json`, `openapi/gemini-python-0.22.0.json`, **`openapi/pi-python-0.22.0.json`** |
| Core | `openapi/core-0.22.0.json` — **still the intersection of every build**, now four |
| Images | claude, codex and gemini at implementation `0.21.0`; **pi-python at `0.1.0`**, its first |

## 1. What is added

**A fourth implementation, `pi-python`**, fronting the Pi coding agent. It serves
the same thirteen `/v1` operations, the same `Deployment` payload and the same
error vocabulary as the other three, and **the shared core lost nothing** to its
arrival.

**It is the first build here that fronts more than one vendor** — Anthropic,
OpenAI, Google and thirty-odd others, chosen per request — and that is where all
its differences come from.

## 2. What breaks

**Nothing.** No field was removed, renamed or re-typed; no status code changed;
the DDL did not move. The three existing documents differ from `0.21.0` only in
their own version strings.

## 3. What a consumer does

**Running the other three:** update your version constant and nothing else.

**Considering `pi-python`:** read `impl/pi-python/docs/pi-python-guide.md`
first. Four things decide whether it fits, and none is visible in an OpenAPI
document:

- **`model_api` is `pi` and maps to no vendor API.** The vendor is in the
  request's own `model`, as `provider/id`.
- **`endpoint_source` is `HTTPS_PROXY`, not a base URL**, and the per-provider
  base-URL variables that package appears to carry **redirect nothing** —
  measured, with a control. A proxy can move traffic; it cannot let a gateway
  swap a credential or count tokens. **Set `AGENT_SERVICE_PROVIDER_GATEWAYS`
  instead** if you need to front it, and a provider with no entry is then refused
  with a 400 rather than reaching its vendor directly.
- **MCP tool calls are cut at 60 seconds by a bound nothing clears** — not
  responding immediately, not sending progress. And the expiry **cancels
  nothing**: a tool that started work goes on doing it while the agent is told it
  timed out. Work that can exceed a minute must be startable and pollable.
- **There is no sandbox.** The container is the entire boundary, and
  `working_directory` confines nothing.

**Cost is reported here.** `reports_cost_usd` is `true` and `model_usage_scope`
is `per_turn`, so sum across turns. `max_budget_usd` is nevertheless refused: the
figure arrives as each model call ends, so enforcing it would mean discarding the
answer you paid for. Enforce between turns.

---

# `0.21.0` — the first call moves, and the payload stops answering four questions at once

**Breaking, and the break is on the route every client calls first.** Read §1
before moving a pin. Everything else is additive.

| | |
|---|---|
| Documents | `openapi/claude-python-0.21.0.json`, `openapi/codex-python-0.21.0.json`, `openapi/gemini-python-0.21.0.json` |
| Core | `openapi/core-0.21.0.json` |
| Images | all three at implementation version `0.20.0` |

## 1. What breaks

**`GET /v1/capabilities` is `GET /v1/deployment`.** No alias, no redirect. Half
of what that payload carried was never a capability — `workspace_dir`,
`max_sessions` and the boot gates describe how an *instance* was configured — and
the name is what made `limits` a map nobody could read.

**The payload is four groups. Every field moved; none was removed.**

| Group | Answers |
|---|---|
| `service` | who is answering — `spec`, `impl`, `sdk`, `sdk_version` |
| `config` | how this instance is set up — `workspace_dir`, `default_model`, `max_sessions`, `auth_required`, the gates, `credential_sources`, `provider_selectors` |
| `accepts` | what a caller may send — the vocabularies, `unsupported_options`, `mcp`, `limits` |
| `behaviour` | what it does and reports — `sandbox`, `model_usage_scope`, `llm_correlation`, `query_*`, `mcp_tool_call`, `limits` |

**Two objects were CUT along that line, and this is the half that fails
silently.** A moved *route* answers `404`; a moved *key* answers nothing at all.

| Was | Is |
|---|---|
| `limits.default_*`, `limits.max_allowed_*` | **`accepts.limits.*`** — ceilings on a request |
| `limits.session_idle_ttl_s`, `limits.turn_timeout_s` | **`behaviour.limits.*`** — what the service enforces |
| `mcp.tool_call.*` | **`behaviour.mcp_tool_call.*`** |

**`RunOptions.workspace_subdir` is `working_directory`**, no alias. The old name
described the value's shape rather than its purpose; the shape is in the field's
description now — relative to `workspace_dir`, must stay under it, must already
exist.

**An unknown `RunOptions` property is a `422` naming the key**, where it used to
be accepted and ignored. This is what makes the rename above fail loudly.

### The AS-23 analysis, because a release must state it

The core lost **94 leaves** and gained 112. Every loss is one of the three
changes above, and nothing else moved:

| Lost | What |
|---|---|
| 87 | the `Capabilities` component, replaced by `Deployment` and its four groups |
| 3 | the `/v1/capabilities` path |
| 2 | `Mcp.tool_call` and its `required` entry |
| 2 | `RunOptions.workspace_subdir` |

## 2. What is added

**`GET /v1/schemas/run-options`** — the `accepts` group rendered as JSON Schema
2020-12: refused fields removed *and* forbidden by name, vocabularies as enums,
ceilings as `maximum`, MCP server names as `propertyNames.pattern`.
Self-contained `$defs`, served as `application/schema+json`. Validate a request
against it or feed it to a form renderer instead of reimplementing the
narrowing. A conformance clause asserts it agrees with `accepts`.

**Descriptions on twenty-eight published fields that had none**, including the
three-layer tool story: a tool name comes from the agent's built-ins, from the
MCP servers *you* send, or from the container's disk — and an unrecognised name
is dropped rather than refused, in both `allowed_tools` and `disallowed_tools`.

## 3. What a consumer does

1. **`/v1/capabilities` → `/v1/deployment`**, and dot the field you were reading
   through its group — §1's table.
2. **Re-find `session_idle_ttl_s` and `mcp.tool_call`.** These do not error; they
   return nothing.
3. **Rename `workspace_subdir` → `working_directory`** in any request you send.
4. Optionally, adopt `GET /v1/schemas/run-options` and delete your own narrowing.

---

# `0.20.0` — one option starts working, one refusal is new, and one truth is finally written down

**Nothing breaks.** Every change is additive or is prose, and a client pinned to
`0.19.0` can move without touching code — with one exception worth ten seconds of
reading, in §1.

| | |
|---|---|
| Documents | `openapi/claude-python-0.20.0.json`, `openapi/codex-python-0.20.0.json`, `openapi/gemini-python-0.20.0.json` |
| Core | `openapi/core-0.20.0.json` |
| Images | all three at implementation version `0.19.1` |

## 1. The one thing to check

**`gemini-python` publishes a new `unsupported_options` entry**, and it is
type-scoped:

```json
{"field": "system_prompt", "types": ["object"]}
```

**A client that compares `entry.field` alone will read this as "the whole field
is refused" and stop sending a string that works.** The published algorithm has
always been `field matches && (types is null || types contains jsonTypeOf(v))`;
this is the second field to exercise it, after `codex-python`'s identical entry
for the same reason. Refused: the Claude preset object. Honoured: the string.

## 2. What is added

**`gemini-python` honours `options.system_prompt`.** On `0.19.0` that field was
accepted, answered `201` and was read by nothing — if you sent one to that image,
the agent never saw it. The string form now reaches the agent, session-scoped:
send it on `POST /v1/sessions` and every turn of that session carries it.

**It REPLACES the agent's own framing on every build that takes a string** —
safety rules, tool protocol, workflows — rather than adding to it. Only
`claude-python`'s preset object form (`{"type": "preset", "preset":
"claude_code", "append": "…"}`) keeps the built-in prompt and appends.

## 3. What is documented that was true all along

**No `RunOptions` field on any build can supply the agent's ambient
configuration.** Memory files (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`), skills,
subagents, slash commands, plugins and settings are read from the container's
disk. The API's only lever is `setting_sources`, and it is a **switch over what
loads**, never a way to send it:

| | `claude-python` | `codex-python` | `gemini-python` |
|---|---|---|---|
| Supply it in a request | **no** | **no** | **no** |
| Suppress what is on disk | **yes, fully** (`setting_sources: []`, the default) | **partly** — the project document only | **no** — the field is a `400` |

**A `system_prompt` is not a substitute**: it replaces framing and suppresses
nothing, and on `gemini-python` the workspace's context files are appended after
it. MCP is the one ambient input every build can both supply and shut out.

This is in the documents themselves now, in the `setting_sources` and
`system_prompt` descriptions, because it is not derivable from a payload shape:
**the workspace you mount is part of every request.**

## 4. What a consumer does

1. **Read `unsupported_options` with `types`**, not `field` alone — §1.
2. **Re-read `/v1/capabilities`** after moving an image: all three implementation
   versions moved to `0.19.1` and `gemini-python`'s payload changed.
3. **Treat the mounted workspace as configuration**, not just as data — §3.
4. Nothing else.

---

# `0.19.0` — the first release. What a consumer does

**Read §1 before moving a pin.** One published leaf is re-typed and one published
surface is gone. Everything else is additive.

| | |
|---|---|
| Documents | `openapi/claude-python-0.19.0.json`, `openapi/codex-python-0.19.0.json`, `openapi/gemini-python-0.19.0.json` |
| Core | `openapi/core-0.19.0.json` |
| Maven | `com.npf:agent-service-openapi:0.19.0`, `com.npf:agent-service-database:1.3.0` |

## 1. What breaks

**One document per implementation, and the filename is `<impl>-<version>.json`.**
Every release through 0.18.0 shipped one `openapi-<version>.json`. A client that
composes a filename from a version alone breaks here. **Resolve the path from
`index.json` instead** — the filename has moved twice and a resolver that follows
`documents.<version>.<name>.path` absorbed both without a line changing.

**`capabilities.permission_modes` is re-typed** from `string[]` to
`SessionMode[]` — `{id, name, description}`. **The id you were reading is now
`.id`.** On the way in, `RunOptions.permission_mode` widened from a closed enum to
an opaque string, which is a widening: anything you sent before is still accepted.

**The `agent-service-spec` command is gone.** Its facts are
`components.schemas.PrebootSpec` in each build's own document, every value pinned
by `const`. Read them with `docker inspect` → the two labels → that build's
document. No container starts.

**A `422` is now an RFC 7807 problem document** — `application/problem+json`,
carrying `errors: [{loc, msg, type}]` — where two of the three builds previously
answered with the framework's `HTTPValidationError`. `loc` names the field and
`type` is what to branch on. **`input` is deliberately absent**: a malformed body
can carry a caller's own MCP bearer token.

## 2. What is added

Nine new required properties on `Capabilities`, which is a widening on output:
`mcp`, `sandbox`, `unsupported_options`, `llm_correlation`, `model_usage_scope`,
`reports_cost_usd`, `sdk_session_id_scope`, `query_reports_sdk_session_id` and
`query_consumes_a_session_slot`. `turn_token_overhead` and
`usage_counts_tool_calls` are optional.

**Read `model_usage_scope` before you sum `model_usage`** — it is `cumulative` on
one build, `per_turn` on another and `not_reported` on the third.

**`mcp.tool_call` says what bounds a long tool call.** The ceiling across the
three builds is **600 s**, it belongs to `gemini-python`, it is wall clock, and
progress does not move it. Two of the three cut off a call that has not begun
answering, so **respond with SSE at once**.

**`PrebootSpec.runs_as`** — `{uid: 1000, gid: 1000}`, `const`-pinned. Chown a
bind-mount source to it *before* starting the container: Docker creates a missing
mount point as `root:root` and the agent is not root.

## 3. What a consumer does

1. **Resolve document paths from `index.json`**, never by composing a filename.
2. **Read `permission_modes[].id`** where you read `permission_modes[]`.
3. **Stop calling `agent-service-spec`**; read `PrebootSpec` from the document.
4. **Handle the `422` as a problem document** if you parsed the framework shape.
5. Nothing else. Every other change is a widening.
