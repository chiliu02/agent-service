# agent-service

**An HTTP contract for driving a local coding agent, and three implementations
that satisfy it.**

You give it a workspace and a prompt over HTTP; it runs a real coding agent
against that workspace in a container and streams back what happened — messages,
tool calls, token usage, cost. Multi-turn sessions, resumable, optionally
persisted to Postgres.

The point is that **the same thirteen `/v1` operations drive three different
agents**. Swap the image and your client does not change:

| Build | Agent | Notes |
|---|---|---|
| [`impl/claude-python`](./impl/claude-python/) | [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) | The reference build |
| [`impl/codex-python`](./impl/codex-python/) | OpenAI Codex SDK | Sandboxes every turn; the only one whose agent cannot reach the network |
| [`impl/gemini-python`](./impl/gemini-python/) | Gemini CLI headless | **No SDK exists** — the agent is a Node program spawned per turn |

Where they genuinely cannot behave identically, they say so at runtime on
`/v1/capabilities` rather than differing silently.
[`docs/capability-divergence.md`](./docs/capability-divergence.md) is the
side-by-side.

> [!IMPORTANT]
> **A request is not the agent's whole input.** Each agent also reads
> configuration from disk inside its container — memory files, skills,
> subagents, commands, plugins, settings — and **no `RunOptions` field on any
> build can supply that.** `setting_sources` switches it off on
> `claude-python`, switches off half of it on `codex-python`, and does not
> exist on `gemini-python`, where the workspace you mount is read on every
> turn. Treat the container's disk as part of the deployment.
> [`docs/capability-divergence.md` §3.1](./docs/capability-divergence.md#31-ambient-configuration--no-build-lets-the-api-replace-it-and-the-document-never-said-so)
> is the table.

> [!WARNING]
> **This service exists to give a coding agent a shell, and it is not
> hardened.** Authentication is optional and **off by default** on all three
> builds. All three publish `permission_enforcement: "none"`, and it means three
> different things across them. What confines the agent is the container and
> your mount layout — nothing else.
>
> Do not put an unauthenticated instance on a network you do not control.
> [`SECURITY.md`](./SECURITY.md) has the minimum for anything beyond your own
> machine.

## Quickstart

You need Docker, and an API key for whichever agent you want to run. Using the
reference build:

```bash
git clone <this repo> && cd agent-service/impl/claude-python
cp .env.compose.example .env      # then edit: WORKSPACE_HOST_PATH, REFERENCE_HOST_PATH
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

docker compose up -d --build --wait
```

`--wait` matters: plain `up -d` reports `Started` and returns 0 for a container
that has already exited 3.

```bash
curl -s localhost:8000/v1/capabilities | jq '{impl, auth_required, sandbox}'
curl -s localhost:8000/v1/query -H 'content-type: application/json' \
  -d '{"prompt":"What files are in the workspace? Summarise in one line."}'
```

Interactive docs are at `http://localhost:8000/docs`.

**Two things that will bite you first**, both deliberate refusals rather than
crashes — the container exits **3** if either is wrong:

- **A missing mount.** Docker silently *creates* a missing bind-mount source and
  starts anyway, so the service checks instead. `mkdir -p` before `up`.
- **A missing credential.** The log message names the problem, the fix, and the
  escape hatch.

**Chown the workspace to `1000:1000` first.** Docker creates a missing mount
point as `root:root`, and the agent is not root. The uid is `const`-pinned in
each build's OpenAPI document as `PrebootSpec.runs_as`.

### The API in one screen

| | |
|---|---|
| `POST /v1/query`, `/v1/query/stream` | one-shot: prompt in, result or SSE out |
| `POST /v1/sessions` | start a multi-turn session |
| `POST /v1/sessions/{id}/messages`, `/messages/stream` | a turn in that session |
| `POST /v1/sessions/{id}/interrupt` | stop a turn in flight |
| `GET /v1/sessions/{id}/transcript` | what was said, if persistence is on |
| `GET /v1/capabilities` | **read this first** — what this build can and cannot do |

## Why three builds and not one with three modes

The value here is that it wraps **the agent** — session lifecycle, the tool loop,
permission plumbing — not the model API. Those differ per *product* far more than
the models do: different tool loops, different session lifecycles, different
sandbox models, and one target that ships no SDK at all. What generalises is the
interface contract, the conformance suite and `/v1/capabilities`. The code does
not, and trying to share it is how you get an abstraction shaped like whichever
SDK arrived first.

**The third build is the evidence.** `gemini-python` wraps a target with no SDK —
a Node CLI spawned once per turn — and joining it to the platform removed
**nothing** from the shared core. The conformance suite needed two new entries in
one probe table and no new clause. What it cost was eleven fixes *in the new
build*, which is the arrangement working as intended: the specification bends the
implementation, never the reverse.

**It is not about language.** All three targets are drivable from Python. A build
is separate because its subject is separate.

**A target must run LOCALLY, in our own container.** A managed cloud agent
runtime — one that hosts the agent for you — is out of scope whatever its
capabilities.

## What is here

| | |
|---|---|
| [`spec/`](./spec/) | **The product.** Three directories — the HTTP contract, the DDL, the conformance suite — and exactly one version, the current one. **A release is a git tag**: `release-<version>` names an immutable commit, and CI checks on every run that every tag still points where the manifest says. |
| [`impl/`](./impl/) | The three builds. Each has its own guide under `impl/<build>/docs/`, written for a client author. |
| [`impl/common/`](./impl/common/) | `agent-spec/` is the specification rendered as pydantic models, plus the database layer — it **names no build, and must not**. `db/` is the Alembic tree that generates `spec/database/`; `web/` is a dev console. |
| [`.ci/ci.py`](./.ci/ci.py) | Everything this repository can check for free, in one command. [`docs/ci.md`](./docs/ci.md) is what it does and why. |
| [`docs/`](./docs/) | Platform-level: CI, versioning, plans, security posture, capability divergence, the database model, running locally, deploying remotely. |

## Running the checks

```bash
uv run --no-project python .ci/ci.py          # freeze, links, references, unit, container, gates
uv run --no-project python .ci/ci.py --fast   # ... the four that need no Docker
```

`--no-project` is required: the platform root is not a uv project —
`pyproject.toml` belongs to each implementation — so a plain `uv run` walks *up*
out of the repository looking for one. `ci.py` is stdlib-only, which is what will
let one runner drive an implementation that is not Python at all.

There is a pre-commit hook, and git does not install it for you:

```bash
git config core.hooksPath .ci/hooks
```

**Nothing in CI can spend money.** Every pytest invocation carries
`-m 'not live'`, and no stage passes `-m live` or unsets it.

## Contributing

[`CONTRIBUTING.md`](./CONTRIBUTING.md) — including the three conventions that
will catch you out: `--no-project` is not optional, a code comment may cite
exactly one document by ID, and versions are not a contributor's to cut.

Security issues: **[`SECURITY.md`](./SECURITY.md)**, not a public issue. It also
explains why "the agent ran a command I did not expect" is the product rather
than a vulnerability.

## License

[Apache-2.0](./LICENSE).
