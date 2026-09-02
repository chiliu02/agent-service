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

**`0.19.0` is the first release and `0.20.0` is the second**; `spec/openapi/`
carries a bare version only in the one commit a tag names, and main moves on to
the next snapshot immediately after. Eighteen versions were cut
before it under an older process and none of them is a release under this one;
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

**The row is written in the commit AFTER the one the tag names**, and it cannot be
otherwise: it carries the commit's own hash. So the tag's tree does not contain
its own row, and `freeze` reads the row from the working tree rather than from the
tag — which is the direction that matters, since what it guards against is the tag
moving afterwards.

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
