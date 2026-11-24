# Contributing

Thanks for looking. This repository has a few conventions that are unusual
enough to be worth reading before you write code — most of them exist because
something went wrong once and the note is the fix.

## Set up

You need **[uv](https://docs.astral.sh/uv/)** and **Python 3.13+**. Docker is
optional for the fast checks and required for the full run. `impl/gemini-python`
additionally needs **Node**, because its agent is a Node CLI.

```bash
git clone <this repo>
cd agent-service
git config core.hooksPath .ci/hooks     # git never installs hooks by itself
```

That one `git config` is not optional on a fresh clone — without it the
pre-commit hook is inert.

## Run the checks

One runner drives everything:

```bash
uv run --no-project python .ci/ci.py          # all six stages
uv run --no-project python .ci/ci.py --fast   # the four that need no Docker
```

`--no-project` is required and is not a style choice: the platform root is not
a uv project (`pyproject.toml` belongs to each implementation), so a plain
`uv run` walks *up* out of the repository looking for one. `.ci/ci.py` is
stdlib-only and needs an interpreter and nothing else.

Run it **from the repository root**. It resolves the platform root as its own
parent's parent, so paths work from anywhere, but `--no-project` is easiest to
get right from the top.

| Stage | Proves | Needs |
|---|---|---|
| `freeze` | no released document was edited after its tag | git |
| `links` | every relative link and `#anchor` in the docs resolves | — |
| `references` | every citation in a code comment names a real entry | — |
| `unit` | the in-process suites, plus the conformance document tier | Docker\* |
| `container` | the conformance suite against a real container, with a database and without | Docker |
| `gates` | the boot gates — a misconfigured image exits 3 | Docker |

\* `unit` uses Docker only to start a Postgres when
`AGENT_SERVICE_TEST_DATABASE_URL` is unset. `--fast` passes `-m "not postgres"`
and needs no daemon.

The pre-commit hook runs `--fast --fail-fast`, about 30 s. The full run is
minutes and is deliberately not in the hook: a hook slow enough to be bypassed
gets bypassed.

**Nothing in CI can spend money.** Every pytest invocation carries
`-m 'not live'`, and no stage passes `-m live` or unsets it. The paid tier stays
a command you type by hand. Debug against
`impl/gemini-python/tests/fake_cli_agent.py` first — it needs no credential and
emits the real stream shapes.

## The conventions that will trip you up

### One specification, three implementations, and the code does not generalise

`spec/` is the product. `impl/` is what satisfies it. The three builds front
three different *products* — the Claude Agent SDK, the OpenAI Codex SDK, and
Gemini CLI headless, which ships no SDK at all — with different tool loops,
session lifecycles and sandbox models. What generalises is the specification,
the conformance suite and `/v1/capabilities`. **Do not refactor two builds
together because their code looks similar**; that similarity has not survived
contact with a third build before.

`impl/common/agent-spec/` is shared and **names no build**. If something you
want to put there needs to know which agent is running, it belongs in the build.

### A code comment may cite exactly one document, by ID

A comment in `impl/<build>/` may name an entry in
`impl/<build>/docs/<build>-references.md` — `CP-nnn`, `CX-nn`, `GP-nn` — and
nothing else. Not a path, not a plan, not another build's document.
`impl/common/` and `spec/conformance/` cite **nothing**: they are shared, so any
document either could name is the wrong one for one of its readers.

The `references` stage enforces this and will fail your commit. It exists
because 50 of 170 citations were already dead when the rule was written.
Executable code is exempt — a path in code either resolves or fails a test; a
path in prose resolves to nobody.

**An ID is permanent.** A superseded entry is struck through and kept, never
renumbered, so a citation in an old commit still resolves.

### Versions are not yours to cut

Snapshots are free — `spec/openapi/*-<version>-snapshot.json` is never frozen
and you may iterate on it at will. **A release is a maintainer decision.**
Moving `spec/VERSION` to a bare number, bumping a `pyproject.toml` version, or
building and tagging an image all need agreement first.
[`docs/versioning.md`](./docs/versioning.md) is the whole process; the short
version is that **the git tag is the freeze**, and `freeze` checks on every run
that a released tag still points where the manifest says.

### Keep the divergence table current

[`docs/capability-divergence.md`](./docs/capability-divergence.md) is the only
place the three builds are shown side by side, so it goes stale in a way nothing
else catches. Update it **in the same change** that moves a published capability
value, adds a field to `Capabilities`, changes which `RunOptions` a build
refuses, or changes how a build honours one.

A row earns its place by being a difference a client must *act* on. That test
governs **adding** a row, not removing one — a row nobody is known to branch on
is annotated as such and kept, because a deleted row decays into somebody
starting three containers to find out.

## Pull requests

- **Branch off `main`.** Get `.ci/ci.py` green before you open the PR — at
  minimum `--fast`, and the full run if you touched anything container-shaped.
- **Say what changed and why in the commit message.** This repository's log is
  written as declarative sentences that state the *meaning* of the change, not
  the mechanics — `git log --oneline` is worth a read before your first commit.
  The reasoning belongs in the commit and the code, not in a plan document.
- **Add the test with the fix.** Every build has a unit suite; behaviour a
  client can observe belongs in `spec/conformance/` instead, where all three
  builds are held to it.
- **Touching a published capability?** Regenerate the affected documents and
  update the divergence table in the same commit.

## Reporting bugs and security issues

Bugs and features: open an issue. Include the build and version —
`GET /v1/capabilities` reports `impl.name` and `impl.version`.

**Security: do not open a public issue.** See [`SECURITY.md`](./SECURITY.md),
which also explains why "the agent ran a command I did not expect" is the
product working rather than a vulnerability.

## Code of conduct

By participating you agree to the
[Code of Conduct](./CODE_OF_CONDUCT.md).
