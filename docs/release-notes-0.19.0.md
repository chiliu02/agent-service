# DRAFT — the delivery README for 0.19.0

**Nothing here is agreed and this is not a delivery.** It is the text intended
for `spec/releases/0.19.0/README.md`, written before the cut so that step 5 of
the process is a review rather than a first draft. It is superseded the moment
that file exists.

**Filenames appear as code rather than as links**, because the files it names do
not exist yet and a link to one would resolve to nothing. Step 5 turns them into
links.

**The delta below was computed** against `spec/0.18.0/openapi-0.18.0.json`
and the three `0.19.0-snapshot` documents on 2026-08-18, not recalled. §3 carries a value corrected on 2026-08-19.

---

# 0.19.0 — delta from 0.18.0 — ONE BREAKING CHANGE, and a new file shape

**Read §1 before moving a pin.** One published leaf is re-typed and one published
surface is gone. Everything else in this release is additive.

| | |
|---|---|
| Documents | `openapi-0.19.0-claude-python.json`, `openapi-0.19.0-codex-python.json`, `openapi-0.19.0-gemini-python.json` |
| Core | `core-0.19.0.json` |

## 1. What breaks

### 1.1 One document per implementation, and the filename changed

Every release through 0.18.0 shipped one `openapi-<version>.json`. **This one
ships three, named `<impl>-<version>.json`, plus a computed
`core-<version>.json`.**

`<impl>` is `capabilities.impl.name` verbatim — `claude-python`, `codex-python`,
`gemini-python` — so a client that has the image knows which document to read
without a mapping table. **A client that composes a filename from a version
alone breaks here** and is the one thing to check before moving a pin.

`core-<version>.json` is the intersection of the three: what every build answers,
and what AS-31 is measured against. Read it when you want the part of the surface
that does not depend on which image you have.

### 1.2 `capabilities.permission_modes` is re-typed — the one breaking leaf

```diff
- "permission_modes": {"type": "array", "items": {"type": "string"}}
+ "permission_modes": {"type": "array", "items": {"$ref": "#/components/schemas/SessionMode"}}
```

`SessionMode` is `{id, name, description}`. **The id you were reading is now
`.id`.** The vocabularies themselves did not shrink; the third build introduces
four ids of its own, which is why a bare string could no longer carry a mode that
needs to be shown to a human.

**On the way in, `RunOptions.permission_mode` widened** from a closed six-member
enum to an opaque string. That is a widening — anything you sent before is still
accepted — and it exists because a closed enum in a shared document cannot carry
one build's vocabulary without predicting the next build's.

### 1.3 The `agent-service-spec` command is gone — AS-23 removal

The pre-boot facts it printed are now `components.schemas.PrebootSpec` in each
build's own document, every value pinned by `const`:
`credential_sources`, `model_api`, `endpoint_source`, `ca_bundle_source`,
`provider_selectors`, `auth_enforced`, `schema_revision`, `impl.name`, `listen`.

**They need no container.** The entry point is `docker inspect` → the two labels
→ that build's document. `version` and `impl.version` stay unpinned on purpose:
they move on the implementation stream, and pinning either would break AS-24 on
the next build bump.

## 2. What is added — all of it optional to adopt

Nine new **required** properties on `Capabilities`, which is a widening on
output: a client that ignores them is where it was before.

| | |
|---|---|
| `mcp` | which transports and header shapes a build can express, the server-name rule, and `tool_call` — see §3 |
| `sandbox` | `{network_access, confines_writes_to_workspace}` — what confines the agent's own tools inside the container |
| `unsupported_options` | `[{field, types?, values?}]` — the `RunOptions` fields and values this build refuses with 400 |
| `llm_correlation` | `{header, measured}` — how the agent's own model traffic joins to a session, for a gateway sitting in front of it |
| `model_usage_scope` | `cumulative` / `per_turn` / `not_reported`. **Read it before you sum `model_usage`** |
| `reports_cost_usd` | whether a money figure exists at all on this build |
| `sdk_session_id_scope` | `conversation` or `turn` — one build's id names a turn |
| `query_reports_sdk_session_id`, `query_consumes_a_session_slot` | what `/v1/query` costs and reports |

Two more are optional: `turn_token_overhead` and `usage_counts_tool_calls`.

New named schemas, all reachable from `Capabilities`: `LlmCorrelation`, `Mcp`,
`McpToolCall`, `PrebootSpec`, `Sandbox`, `SessionMode`, `TokenUsage`,
`UnsupportedOption`. **No path was added or removed** — the fourteen `/v1`
operations are unchanged.

## 3. `mcp.tool_call`, and the number to plan against is 600

Added at this consumer's request on 2026-08-18. Four keys saying what bounds an
MCP tool call that runs for minutes:

| | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `request_timeout_s` | 60 | null | **60** |
| `idle_timeout_s` | 300 | null | null |
| `total_timeout_s` | 100000 | null | **600** |
| `progress_resets_idle` | true | null | **false** |

`null` means *this build imposes no bound of that kind* — not *unmeasured*.

**The ceiling across the three is 600 s and it belongs to `gemini-python`.** It
is wall clock, and progress does not move it: that agent sends a `progressToken`
on every call and uses it only for its own display. **A deadline above 600 s
cannot be had from any MCP-level behaviour on that build.**

**Two of the three cut off a call that has not begun answering** -- claude-python
and gemini-python, both at 60 s -- so the recipe is not optional: respond with SSE
at once, and emit `notifications/progress` well inside 300 s.

## 4. What the consumer does

1. **Compose the document filename from `impl.name`**, or read `core-0.19.0.json`
   if you only want what all three answer.
2. **Read `permission_modes[].id`** where you read `permission_modes[]`.
3. **Stop calling `agent-service-spec`.** Read `PrebootSpec` from the document
   named by the image's two labels.
4. Nothing else. Every other change is a widening.
