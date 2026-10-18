# agent-service {{VERSION}} — the contract, and what a document cannot tell you

**Everything in this bundle is generated from the running services and verified
against them.** Nothing here points outside this artifact.

    {{COORDINATES}}

**Two artifacts, because they are consumed differently.** This one is read by
tests and never ships in a runtime image; the DDL is executed at boot and does,
so it is `com.npf:agent-service-database` and versions on its own cadence -- a
document-only fix here must not move a dependency carrying executable SQL.

| Resource in this artifact | What it is |
|---|---|
| `/agent-service/spec/{{VERSION}}/claude-python-{{VERSION}}.json` | the Claude Agent SDK build |
| `/agent-service/spec/{{VERSION}}/codex-python-{{VERSION}}.json` | the OpenAI Codex SDK build |
| `/agent-service/spec/{{VERSION}}/gemini-python-{{VERSION}}.json` | the Gemini CLI build |
| `/agent-service/spec/{{VERSION}}/core-{{VERSION}}.json` | what all three guarantee |
| `/agent-service/index.json` | every file above, with its sha256 |

## Resolve a path from `index.json`. Never compose a filename

**`documents.<version>.<name>.path` and `schema.<revision>.path` are the
supported way in**, and the table above is orientation rather than an interface.
Compose a name yourself and it will work until it does not.

**The failure is silent, and that is the whole reason this paragraph exists.** A
consumer reported it in 2026-08-19: a document that is *not* on their classpath is
a legitimate answer in their code -- it means *this image was built against a
version we do not carry* -- so a name that stops resolving raises nothing. Every
image would have gone quietly from verified to unverifiable, with their build
still green, and the pre-boot facts they read before `docker create` would have
gone from published to absent without an error anywhere. A guard that skips when
no `PrebootSpec` is found reads a renamed file exactly as it reads an old
artifact.

**Filenames have moved twice** -- `openapi-<version>.json` to
`openapi-<version>-<impl>.json` in 0.19.0's development, and to
`<impl>-<version>.json` before it was cut. A resolver that follows `path`
absorbed both without a line changing.

**`index.json` describes THIS artifact and nothing else.** A hash is worth having
because it is checkable against bytes that are present, so the schema artifact
carries its own index over its own DDL rather than this one vouching for files it
does not contain.

---

## 1. Which document to generate a client from

**Generate from `core-{{VERSION}}.json` if your client must work against every
build.** It is the intersection of the three, computed from them rather than
authored, so anything in it is something all three really serve.

**Generate from a build's own document if you target one build.** Its extra
status codes and response headers are real and the core omits them.

The three documents are **structurally identical** — same paths, same methods,
same `operationId`s, same request and response schemas, and since this version
the same *order*, so a textual diff between two of them shows only what actually
differs. Where they differ is prose and additions, never contradiction.

---

## 2. Read the capability example before you assume anything

**Each document carries its own build's real `/v1/capabilities` payload** as the
example on that operation. That is the fastest way to see how the three differ
without starting anything:

```
                          claude-python      codex-python     gemini-python
allow_supplied_sdk_...    true               false            false
always_disallowed_tools   [AskUserQuestion]  []               [run_shell_command]
sandbox.confines_writes   false              TRUE             false
sandbox.network_access    true               FALSE            true
turn_token_overhead       null               null             7000
usage_counts_tool_calls   null               null             FALSE
```

**Every field in those examples is what a live instance returns**, except the
ones that depend on the deployment — `workspace_dir`, `limits`, `max_sessions`,
`require_credentials`, `require_mounts`, `auth_required`, `allow_mcp_servers`,
`default_model`, `reference_dirs`, `impl` — which show that build's defaults.
Each build has a test comparing its published example against a live payload, so
the values cannot quietly go stale.

---

## 3. The five things a schema cannot tell you

### 3.1 `permission_enforcement: "none"` is published by all three and means three different things

The field answers one question: *does the service inspect each tool call
in-process before it runs?* All three answer no. **That is not a statement that
the agent is unconfined**, and the two builds whose rows look most alike are the
furthest apart:

| build | what actually confines the agent |
|---|---|
| claude-python | the container. **A shell is in its default tool list** |
| codex-python | an OS-level sandbox around every turn, with no network |
| gemini-python | a tool policy the agent loads at session open. **A shell is refused whatever you ask for** |

**Read `always_disallowed_tools` and the `sandbox` pair beside this field.** A
decision made on `permission_enforcement` alone treats all three as equivalent.

A dimension is missing and known to be missing: *when* the boundary is fixed. A
policy loaded at session open cannot be narrowed mid-turn; an in-process check
can refuse a call as it happens. Both report through this one field today.

### 3.2 `sdk_session_id` does not mean the same thing on every build

**Read `sdk_session_id_scope`, which every build publishes.** The value looks
identical either way, so this cannot be inferred from a response:

| build | `sdk_session_id_scope` |
|---|---|
| claude-python | `conversation` |
| codex-python | `conversation` |
| gemini-python | **`turn`** |

Where it is `turn` the agent mints a new id on every turn of a resumed session:
route on it, **never key on it**. Where it is `conversation` a client may key on
it, though it can still move under an explicit fork or resume — stable is not
immutable. The service's own `session_id` is the stable handle everywhere, and is
what every path takes.

`allow_supplied_sdk_session_id` tells you whether a build accepts one from you.
Where it is `false`, sending one is a `400` rather than being accepted and
answered with a different id.

### 3.3 A refusal can be indistinguishable from success

On at least one build a turn that declined to do the work still returns a
success envelope: `is_error` false, `stop_kind` `end_turn`, no field separating
"did it" from "decided not to". **If that distinction matters, read the
`tool_use` events** rather than the outcome — and note `usage_counts_tool_calls`,
because where it is `false` the usage block's own tool counter reports zero on a
turn that made a call.

### 3.4 Cost is not comparable across builds, and is sometimes absent entirely

`total_cost_usd` is **`null` forever** on the builds whose agent reports no
monetary figure — which is not the same as free. `model_usage` is **cumulative
for the connection on one build and per turn on another**, and the two are
indistinguishable from the payload, so summing it is correct on one and
double-counts on another. Prefer `token_usage`, whose scope the specification
fixes.

Where `turn_token_overhead` is non-null, treat it as a floor: that many input
tokens are spent before your prompt is read, so **turn count predicts spend
rather than prompt length** and a client sending many small turns pays far more
than one that batches.

### 3.5 Two 404s mean different things, and you must branch on `type`

Every error is RFC 7807. On the history routes:

- `type` ending `persistence-disabled` — this deployment has no database, so
  there is no stored history at all.
- `type` ending `session-not-found` or `run-not-found` — history is on and that
  id was never recorded.

**Branch on `type`, never on the status code**, and never on `title` or
`detail`, which are prose and change.

---

## 4. The database, if you run the persistence tier

**The DDL is the other artifact**, `com.npf:agent-service-database`, and it carries
**every revision the specification has shipped** rather than only the newest --
an operator mid-migration has to be able to name a revision that is not the head.
Each is named by its revision and hashed in that artifact's own `index.json`, so
the bytes can be verified before they are executed.

It is part of the specification exactly as the OpenAPI document is.

**Persistence is optional on every build**, and `/healthz` distinguishes the
three states: `database_configured: false` with `database_usable: null` means
none is configured; `usable: false` means one is configured and not answering.

**A database is history, never continuity, on some builds.** Where a build
resumes a conversation from an on-disk transcript rather than from the database,
losing the database costs you the record and losing the volume costs you the
conversation. The build's own `/v1/capabilities` and its operations
documentation say which it is.

---

## 5. Everything load-bearing here is also a field

**Prose drifts and no test catches it**, so nothing in this file is the only home
for something a client must act on. The comparison in §2 is read from the
capability example inside each document, and each build has a test comparing that
example against a live payload. `turn_token_overhead` and `usage_counts_tool_calls`
were prose in an earlier draft of this file and are now published fields for
exactly this reason.

**The last exception closed on 2026-08-12**: §3.2's claim used to be prose only,
and is now `sdk_session_id_scope` on every build. **Nothing in this file is now
the sole home for anything a client must act on** — if you find something that
is, it is a defect and we would like to hear about it.

## 6. What this bundle does not contain

**No code, no client, and no dependencies** — resources only.

**No per-build operational guidance.** How to run a container, which flags it
needs and what its boot gates check belong to whoever ships that image, and
travel with it rather than with the contract.

**This is a `-SNAPSHOT`, and Maven's meaning of that is ours too**: it can
change under you, it carries no hash and no manifest row, and no notice is owed
before it moves. A cut release drops the suffix and gains all three.
