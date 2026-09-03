# Changelog

The HTTP specification's versions. **[`spec/README.md`](./spec/README.md) is the
authority** — it carries the released-versions table that CI verifies on every
run, and each release's migration note. This file is the reader-facing summary.

**Three streams move independently**, which is why a single version number here
would mislead:

| Stream | Versioned by | Where |
|---|---|---|
| The **document** — the HTTP contract | `spec/VERSION` | `spec/openapi/` |
| The **DDL** | Alembic revision, not a version | `spec/database/` |
| Each **implementation** | its own `pyproject.toml` | `impl/<build>/` |

An implementation can bump without the document moving. The document moving is
what needs a release.

**A release is a git tag.** `release-<version>` names an immutable commit, and
the spec package, the schema package and the three images are all built from it.
Main is always a `-snapshot`.

---

## Unreleased — `0.20.0-snapshot`

Prepared for public release: Apache-2.0, contributor and security policy, a
GitHub workflow running the four Docker-free stages. No change to the HTTP
surface.

Fixed: `impl/gemini-python/docs/` had never been scanned by the `links` stage —
unscanned from the day that build was added until it was found. Documentation
only; no runtime effect.

## 0.19.0 — the first release under this process

Tag `release-0.19.0`. Read §1 of [`spec/README.md`](./spec/README.md) before
moving a pin: one published leaf is re-typed, one published surface is gone, and
everything else is additive.

**Eighteen versions were cut before this one under an older process, and none of
them is a release under this one.** Their documents are in the git history and
are not carried in the working tree.

### Breaking

- **One document per implementation**, named `<impl>-<version>.json`, plus a
  computed `core-<version>.json`. Every release through 0.18.0 shipped a single
  `openapi-<version>.json`. **A client that composes a filename from a version
  alone breaks here** — resolve from the package's `index.json` instead. The
  filename has moved twice, and a resolver that follows
  `documents.<version>.<name>.path` absorbed both without a line changing.
- **`capabilities.permission_modes` is re-typed** from `string[]` to
  `SessionMode[]` (`{id, name, description}`). **The id you were reading is now
  `.id`.** Inbound, `RunOptions.permission_mode` widened from a closed enum to
  an opaque string — a widening, so anything you sent before is still accepted.
- **The `agent-service-spec` command is gone.** Its facts are
  `components.schemas.PrebootSpec` in each build's own document, every value
  pinned by `const`. Read them with `docker inspect` → the two labels → that
  build's document. No container starts.
- **A `422` is now an RFC 7807 problem document** (`application/problem+json`,
  carrying `errors: [{loc, msg, type}]`) where two of three builds previously
  answered with the framework's `HTTPValidationError`. `loc` names the field and
  `type` is what to branch on. **`input` is deliberately absent**: a malformed
  body can carry a caller's own MCP bearer token.

### Added

Nine required properties on `Capabilities` — a widening on output: `mcp`,
`sandbox`, `unsupported_options`, `llm_correlation`, `model_usage_scope`,
`reports_cost_usd`, `sdk_session_id_scope`, `query_reports_sdk_session_id`,
`query_consumes_a_session_slot`. `turn_token_overhead` and
`usage_counts_tool_calls` are optional.

Two of those are worth acting on immediately:

- **Read `model_usage_scope` before you sum `model_usage`.** It is `cumulative`
  on one build, `per_turn` on another and `not_reported` on the third — so the
  same arithmetic is right on one and wrong on the other two.
- **`mcp.tool_call` says what bounds a long tool call.** The ceiling across the
  three builds is **600 s**, it belongs to `gemini-python`, it is wall clock,
  and progress does not move it. Two of the three cut off a call that has not
  begun answering, so **respond with SSE at once**.
  [`docs/capability-divergence.md`](./docs/capability-divergence.md) has the
  per-build table and which timer stops which build.

**`PrebootSpec.runs_as` is `{uid: 1000, gid: 1000}`**, `const`-pinned. Chown a
bind-mount source to it *before* starting the container: Docker creates a
missing mount point as `root:root`, and the agent is not root.

No path was added or removed — the fourteen operations are unchanged: thirteen
under `/v1`, plus `/healthz`.

### For a consumer

1. Resolve document paths from `index.json`, never by composing a filename.
2. Read `permission_modes[].id` where you read `permission_modes[]`.
3. Stop calling `agent-service-spec`; read `PrebootSpec` from the document.
4. Handle the `422` as a problem document if you parsed the framework shape.
5. Nothing else. Every other change is a widening.

---

## Before 0.19.0

Eighteen versions, cut under a process that made a version a directory rather
than a tag. They are reachable through `git log` and are not carried in the
working tree. [`docs/versioning.md`](./docs/versioning.md) records what changed
about the process and why — including the mistake that produced it.
