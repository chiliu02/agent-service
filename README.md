# agent-service

**An HTTP contract for driving a local coding agent, and the implementations
that satisfy it.** One repository, one conformance suite, one CI runner — and
**three implementations**, each fronting a different agent.

**The third one is the evidence the design works.** `gemini-python` wraps a
target with no SDK at all — a Node CLI spawned once per turn — and joining it
to the platform removed **nothing** from the shared core. What it cost was
eleven fixes in the new build, which is the arrangement working as intended:
the specification bends the implementation, never the reverse.

> ⚠️ The service each implementation ships is **not hardened**, and how far
> from hardened differs per build. Authentication is optional and off by
> default on all three; what confines the agent is not the same in any two of
> them, and `permission_enforcement: "none"` is published by all three while
> meaning three different things. Read the build's own guide — and
> `always_disallowed_tools` beside that field — before running one anywhere but
> a machine you would hand to a stranger.

## What is here

| | |
|---|---|
| [`spec/`](./spec/) | **The product.** One directory per released version, written once and never edited; the manifest at the top of its README is checked by CI on every run. |
| [`impl/claude-python/`](./impl/claude-python/) | The [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) build. **The only one delivered as a release.** [Operations](./impl/claude-python/docs/claude-python-operations.md) runs it; the [guide](./impl/claude-python/docs/claude-python-guide.md) is for a client author. |
| [`impl/codex-python/`](./impl/codex-python/) | The OpenAI Codex SDK build. Sandboxes every turn, and is the only one whose agent cannot reach the network. Its [guide](./impl/codex-python/docs/codex-python-guide.md). |
| [`impl/gemini-python/`](./impl/gemini-python/) | Gemini CLI headless — **no SDK exists**, so the agent is a Node program spawned per turn. Its [guide](./impl/gemini-python/docs/gemini-python-guide.md). |
| [`impl/common/agent-spec/`](./impl/common/agent-spec/) | The shared models and the database layer. **Names no build, and must not.** |
| [`ci.py`](./.ci/ci.py) | Everything this repository can check for free, in one command. [`docs/ci.md`](./docs/ci.md) is what it does and why. |
| [`docs/to-agent-harness/`](./docs/to-agent-harness/) | The outbox — correspondence with the consumer. |

## Why three builds and not one with three modes

The value of this service is that it wraps **the agent** — session lifecycle,
the tool loop, permission plumbing — not the model API. Those differ per
product far more than the models do: different tool loops, different session
lifecycles, different sandbox models, and one target that ships no SDK at all.
What generalises is the interface contract, the conformance suite and
`/v1/capabilities`; the code does not.

**The criterion for a target is that it runs LOCALLY, in our own container.** A
managed cloud agent runtime — one that hosts the agent for you — is out of
scope whatever its capabilities.

**It is not about language.** All three targets are drivable from Python, and
this file used to say language was the reason. A build is separate because its
subject is separate.

[`docs/plans.md`](./docs/plans.md) Plan 8 is the reasoning;
`docs/plan-8-design.md` (removed 2026-08-19; in `git log`) is the target structure and
the migration into it, measured step by step.

## Running the checks

```bash
uv run --no-project python .ci/ci.py          # freeze, links, unit, container, gates
uv run --no-project python .ci/ci.py --fast   # ... the three that need no Docker
```

`--no-project` because the platform root is not a uv project — `pyproject.toml`
belongs to the implementation. `ci.py` is stdlib-only, which is what will let
one runner drive an implementation that is not Python at all.

There is a pre-commit hook and git does not install it for you:

```bash
git config core.hooksPath .ci/hooks
```
