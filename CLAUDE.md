# agent-service — working notes for Claude

**One repository, one specification, one CI runner, and — since 2026-08-11 —
THREE implementations.** `agent-service` fronts a **local coding agent** over
HTTP. Each implementation is a separate build rather than a mode of another, and
what generalises is the specification, the conformance suite and
`/v1/capabilities`; the code does not.
`docs/plan-8-design.md` (removed 2026-08-19; not carried in this repository) is the structure and the
migration, [`docs/plans.md`](./docs/plans.md) Plan 8 is why.

**The third build is what tested the claim, and it held.** Adding
`gemini-python` — a Node CLI with no SDK at all, spawned per turn — cost the
shared core **zero** leaves. The conformance suite needed two new entries in one
probe table and no new clause. What it did need was eleven fixes *in the new
build*, which is the arrangement working as designed: the specification bends the
implementation, never the reverse.

**The reason is NOT language, and this file used to say it was.** The chosen
targets — the Claude Agent SDK, the **OpenAI Codex SDK** and **Gemini CLI
headless** — are all drivable from Python. What forces separate builds is that
they are different *products*: different tool loops, different session
lifecycles, different sandbox models, and one of them ships no SDK at all. A
build is separate because its subject is separate, not because of its syntax.

**The criterion for a target is that it runs LOCALLY, in our own container.** A
managed cloud agent runtime — one that hosts the agent for you — is out of
scope, whatever its capabilities. That is what rules out the Gemini Enterprise
Agent Platform and anything shaped like it.

**Three directories at the root, and that is on purpose.** `spec/` is what this
repository sells, `impl/` is what satisfies it, `docs/` is everything written
about either. Tooling is hidden in `.ci/` because it is not the product.

```
spec/                    THE PRODUCT -- the CURRENT version's documents, and
                         nothing else. Every released version is in its
                         `release-<version>` git tag: THE TAG IS THE FREEZE, and
                         the spec jar, the schema jar and the three images are
                         all built from it
spec/openapi/            the HTTP contract -- one document per implementation
spec/database/           the DDL, one file per Alembic revision. A SEPARATE
                         STREAM: it moves when a migration lands
spec/conformance/        the suite that judges a build against the specification
impl/claude-python/      the Claude Agent SDK build. The only one DELIVERED
impl/codex-python/       the OpenAI Codex SDK build
impl/gemini-python/      Gemini CLI headless, spawned per turn -- no SDK exists
impl/common/agent-spec/  the shared models AND the database layer. Names no
                         build, and must not
impl/common/db/          the Alembic tree -- the GENERATOR of spec/database/,
                         and operator tooling: no image ships it
impl/common/web/         the dev console. A tool, not a deliverable
docs/                    platform-level: ci, versioning, plans, dev-todo, open questions,
                         security posture, capability divergence, database model,
                         running locally, deploying remotely, and how a client
                         derives RunOptions (and its form) from /v1/capabilities
impl/<build>/docs/       that build's OWN documents, beside its code (user,
                         2026-08-10): the consumer guide, and the references file
                         that is the only document its code may cite. They lived
                         under docs/<build>/ for a day and came back
docs/to-agent-harness/   the outbox (see The channel, below). Tracked in the
                         DEVELOPMENT repository and removed by the export that
                         builds the public one -- it names a third party's
                         estate. Absent if you are reading this on GitHub
.ci/ci.py                ONE runner. `uv run --no-project python .ci/ci.py`
.ci/bundle.py            builds the two Maven artifacts from a release tag
.ci/images.py            builds and tags the three images. Both are RELEASE
                         tooling: neither is a stage, and neither runs in CI
.ci/hooks/pre-commit     core.hooksPath target -- see below
.github/                 workflow + templates. Runs `--fast` only: the container
                         stages are minutes of runner time and stay local
```

**This file is platform-level: the boundary, the channel, and how the CI is
driven.** Anything that is true because of a particular agent, its SDK or its
container is in that build's own `CLAUDE.md` — **read the one for the tree you
are working in**, and it outranks nothing here:
[`impl/claude-python/CLAUDE.md`](./impl/claude-python/CLAUDE.md),
[`impl/codex-python/CLAUDE.md`](./impl/codex-python/CLAUDE.md),
[`impl/gemini-python/CLAUDE.md`](./impl/gemini-python/CLAUDE.md).

## Commands

```bash
uv run --no-project python .ci/ci.py          # ALL of it: freeze, links, references, unit, container, gates
uv run --no-project python .ci/ci.py --fast   # ... the first four only, no Docker at all
```

**`--no-project`, and it is not optional.** The platform root is not a uv
project — `pyproject.toml` belongs to the implementation — so a plain `uv run`
here walks *up* out of the repository looking for one. `ci.py` is stdlib-only
and needs an interpreter and nothing else, which is also what will let one
runner drive an implementation that is not Python at all.

`ci.py` runs every `uv`/`docker` command with the implementation directory as
its working directory. Its own working notes are in
[`docs/ci.md`](./docs/ci.md); **read that before changing any of it.**

**Run it from the repository root, not from inside `.ci/`.** It resolves the
platform root as its own parent's parent and addresses git, `spec/` and `impl/`
from there, so the paths are the same wherever you invoke it from — but the
`uv run --no-project` above is what keeps uv from walking up out of the
repository, and that is easiest to get right from the root.

**A fresh clone needs one command before the hook runs**, because git never
installs hooks by itself:

```bash
git config core.hooksPath .ci/hooks
```

## Check before claiming (user, 2026-08-14)

**[`docs/running-locally.md`](./docs/running-locally.md) is the file, and it is
written as a list of things claimed before they were checked.** Read it before
running any build by hand, and before concluding that something "does not work
on this platform".

Three that cost real time, each cheap to have verified:

- **`codex-python` runs on Windows natively.** It was declared unsupported on
  the strength of a `TransportClosedError` and a note about bubblewrap, which is
  the *Linux* sandbox. The actual defect was a relative `CODEX_HOME` resolved
  against the workspace (`CX-55`).
- **An error suppressed by `2>/dev/null` is not evidence of absence.** "No local
  images" was Docker being unreachable, because a cleanup step had killed
  `com.docker.backend` — found by asking *what is listening on 8081*, which is
  Nexus. **Never pick a port this repository documents, and never kill by
  port** — kill the PID you recorded, or the container by name.
- **When a browser and curl disagree, suspect the browser's connection state.**
  Six abandoned SSE streams exhausted the per-origin limit and looked exactly
  like a broken transport; the raw timings were 1.7 s to headers throughout.

**Debug against `fake_cli_agent.py` before spending anything** — it needs no
credential and emits the real stream shapes. And **check a key against the
provider** before blaming this code; a `401` is not a defect here.

## Keep `docs/capability-divergence.md` current (user, 2026-08-14)

**It is the only place the three builds are shown side by side, so it goes stale
in a way nothing else catches.** Three OpenAPI documents describe three payload
*shapes* and say nothing about how the values differ; a consumer deciding whether
to sum `model_usage` cannot answer that from any of them, and would otherwise
have to start three containers to find out.

**It covers BOTH halves of the contract** since 2026-08-14, when
`options-divergence.md` was merged into it: §2 is what the service publishes, §3
is what a caller may send and which builds refuse what. They were split by
request surface versus response surface, which is an implementation distinction
and not a reader's — and the split is what let one of them rot for six days while
the other was maintained.

**Update it in the same change that moves a published capability value** — not
afterwards, and not when someone notices. It is a snapshot with the versions it
was written against in its own header, and the running service stays the
authority; what is owed is that the snapshot never contradicts the code.

The trigger is any of these:

- a value in a `_capabilities_payload` / `build_capabilities` changes, or a new
  field joins `Capabilities`;
- a build starts or stops refusing a `RunOptions` field, or its
  `permission_modes`, `limits`, `mcp` or `sandbox` answer moves;
- a build changes how it *honours* a `RunOptions` field even without refusing it
  — §3's rows say what a field does per build, not merely whether it is accepted;
- **a fourth build arrives** — a column, not a rewrite;
- an implementation version bumps in a way that moves any row, in which case the
  header's version list moves with it.

**A row earns its place by being a difference a client must ACT on.** That is
AS-32, and it is the same test `unsupported_options` is held to: a field whose
value is inert is noise in that table.

**That test governs ADDING a row and not removing one** (user, 2026-08-15,
adopting Agent Harness's position). **Inert to one client is not inert.**
Harness is a gateway and a fleet manager; a client rendering transcripts or
billing per model branches on a different half of the table, and neither of them
is the reader the table is for on its own. **So mark rather than delete** — a
row nothing is known to branch on is annotated as such and kept, which decays
safely. A deleted row decays into somebody starting three containers.

Their own counter-example is the one that settles it: `model_usage_scope` reads
inert to Harness only because nothing of theirs reads `model_usage` **yet**, and
they hold the row as a written constraint on the code that eventually will —
*sum on gemini, difference on claude, skip on codex*. Deleting it would remove
the warning immediately before the work that needs it.

**A marking is a claim about consumers, so it carries its date and its source.**
"No known consumer branches on this" means *nobody has told us they do*, which
is not *nobody does*, and an unmarked row is never evidence that somebody does.

## Code cites ONE document per build, by ID (user, 2026-08-10)

**A comment may name `impl/<build>/docs/<build>-references.md`'s entries and
nothing else.** Not a todo, not a plan, not another build's document, and never a path.

| Tree | May cite |
|---|---|
| `impl/claude-python/` | `CP-nnn` |
| `impl/codex-python/` | `CX-nn` |
| `impl/gemini-python/` | `GP-nn` — **and `spike/` counts**, which caught eight dead citations on its first day |
| `impl/common/`, `spec/conformance/` | **nothing** — shared and neutral, so any document either names is the wrong one for one of its readers |

**`.ci/ci.py`'s `references` stage enforces it**, over comments and docstrings in
`.py`, and over `#` comments in compose files and Dockerfiles. It fails a
path-shaped citation, an ID with no entry, and a references file that links out.
`AGENTS.md`, `CLAUDE.md` and `README.md` are exempt: the first two are files the
*product* reads and the third sits beside the code, so none of them is reachable
by a path that can rot.

**Executable code is exempt on purpose.** A path in code either resolves or
fails a test; a path in prose resolves to nobody. That is not a hypothetical —
**50 of 170 citations were already dead** when this rule was written, 31 of them
bare filenames that had never resolved from anywhere, and one directory move
produced most of the rest. Log messages are exempt for the same reason plus a
second: their reader is outside the tree, where a repository-relative path is
the only thing they can act on.

**A references file links to nothing and each entry is complete.** A reader
holding only that one file can never hit a dead end — which is the same property
the outbox rule already demands of `docs/to-agent-harness/`. **An ID is
permanent**: a superseded entry is struck through and kept, never renumbered, so
a stale ID in an old commit still resolves.

**The entry carries the evidence; the comment stays short.** If a comment needs
two entries to make sense, split the entries rather than lengthening the
comment.

## Never publish a version without asking (user, 2026-08-07, revised 2026-08-09)

**[`docs/versioning.md`](./docs/versioning.md) is the full process** — the three
streams, snapshot vs release, the cut, the image, and the mistake that produced
it. Read it before touching a version or an image. What follows is the rule
itself.

**Snapshots are yours; releases are the user's.** The rule is the **`-snapshot`
suffix**, and it is a suffix on a FILENAME — there are no version directories.
`spec/` holds three directories, one per kind of artifact (`openapi/`,
`database/`, `conformance/`), and exactly one version: whatever `spec/VERSION`
says. Every earlier release lives in its `release-<version>` tag and nowhere in
the working tree.

| | Permission |
|---|---|
| `spec/openapi/<impl>-<version>-snapshot.json` — never frozen, regenerate at will | **none needed.** Iterate freely |
| Renaming those to a bare version, or moving `spec/VERSION` to one | **ask, every time** |
| **Creating or pushing a `release-<version>` tag** | **ask.** THE TAG IS THE FREEZE — this is the most gated thing here, because a tag is the one thing that cannot be superseded, only moved |
| Adding a row to `spec/README.md`'s released-versions table | **ask** — the row *is* the claim that a version was delivered, and `freeze` checks it on every run |
| Any `pyproject.toml` version | **ask** |
| Building or tagging an image, or publishing a Maven artifact | **ask** |

**Agent Studio may test a snapshot** (user, 2026-08-09), so `spec/` is
visible to them — it is simply never frozen. Testing before cutting is how a defect
gets found while the number can still change. **A snapshot handed to them must say
it can change under them**, because it has no hash, no manifest row and no notice
obligation.

**A version exists because a consumer will adopt it — not to record that work
happened.** Of the eighteen cut so far, Studio uses **four**: 0.5.1 (signed),
0.10.0, 0.15.0, 0.18.0. The rest are bookkeeping, and each cost a delivery
directory, a hand-written README, a manifest row and a hash that nobody will
read.

**A DELIVERED IMAGE FREEZES THE DOCUMENT, and that is what the old rule missed.**
The rule used to say an undelivered document is editable in place, which is true
of documents and silent about images. 0.18.0 was cut and editable until an image
was tagged and announced in the same session; from that moment editing the
document would have broken AS-24 for the exact image the consumer was told to
pull, and a tag is never moved. **So publish the image and the document as one
decision.** `versioning.md` §6 is the whole story.

**Check whether a change actually touches the document before assuming it needs a
document version.** `limits` is a free-form map, so three of four fields owed to
Studio turned out to need only an implementation bump.

**The pre-boot facts USED TO BE the other half of that sentence, and are not any
more** (0.19.0). They were a command inside the image — `agent-service-openapi` —
which meant they could move with nothing moving in `spec/`, and that is exactly
how they drifted out of the specification's reach: a consumer told to depend only
on paths under `spec/` could not reach them from any of them. They are now
`components.schemas.PrebootSpec` in each build's own document, pinned with
`const`, and the command is removed. **So moving one of those values now needs a
document version**, which is the point rather than the cost — see `CP-148`,
`CX-59` and `GP-63`.

**And when a release is warranted, its README is a migration note, not an
essay.** What changed, what breaks, what the consumer does. The reasoning
belongs in the commit message and the code.

## Never write outside this directory

**Rule (user, 2026-08-06). No exceptions, and it outranks any task in this
file.** Do not create, modify, move or delete a file outside
`agent-service/`. Do not commit, stage or otherwise change git state in another
repository.

**This includes the Agent Studio repo**, and being its provider is not a licence
— *especially* not, because the whole relationship runs on each side owning its
own tree.

### The channel (user, 2026-08-07)

**The consumer is Agent Harness**, renamed from Agent Studio on 2026-08-10, and
the outbox was renamed with it (user). **The old name is NOT swept from the
repository**: it is what they were called when every earlier thread was written,
and rewriting those would falsify the record. Frozen delivery directories and
the signed bundle could not be edited even if it were desirable. So *Agent
Studio* in a document dated before the rename is correct, not stale.

| Direction | Path | You may |
|---|---|---|
| **Out** — to Agent Harness | `docs/to-agent-harness/` *(this repo)* | **write** |
| **In** — from Agent Harness | `docs/to-agent-service/` *(their repo)* | **read only** |

**Write outbound documents into `docs/to-agent-harness/`.** That is the one place
in this repo they read, and writing there is not a violation — it is inside
this directory. They read it where it sits; you still do not copy anything
anywhere.

**It is tracked HERE and removed by the export, and the rule above is
unchanged** (user, 2026-08-21). This repository is public at
`github.com/chiliu02/agent-service`, and the outbox is not in it — the threads
carry *their* internal infrastructure (registry addresses, a Maven host,
compose paths on their machines), and a provider does not publish a consumer's
estate.

**But the removal is a step in publishing, not a state of this tree.** The
export builds a separate two-commit history on the `public` branch and drops the
outbox there. Ignoring it here instead was tried and is wrong twice over: a new
thread would silently never be committed, and the private record — which is the
whole point of keeping it — would stop growing with nobody noticing.

**So keep writing replies there exactly as before, and keep committing them.**
Nothing about "writing to the outbox is publishing" below is softened: they
still read it where it sits.

**The two paths are mirror images, and that is the point of the shape.** Each
side keeps the other's mailbox under its own `docs/`, named for the recipient —
so a path says which repository it is in *and* which direction it flows, and
neither side ever has to reach into the other's tree to find one. The outbox
lived at the repository root for a day (Plan 8 step 2 promoted it) and came back
here on 2026-08-07.

**Their inbox path is theirs to name.** `docs/to-agent-service/` is in their
repository and this rename does not touch it; if they rename it, this table
follows rather than leads.

**Read `docs/to-agent-service/` in Studio's repo for their messages.** Read-only,
always. Do not create, edit or delete anything there, including a reply — a reply
goes in your outbox.

**Reply naming (user, 2026-08-07).** A thread is one base name and an
incrementing suffix, alternating sides:

| File | Written by |
|---|---|
| `a.md` | them (their inbox) |
| `a.1.md` | **you** (your outbox) |
| `a.2.md` | them |
| `a.3.md` | you |

So a reply keeps the base name of the document it answers and adds the next
number. Do not invent a new base name for a reply — a new base name starts a new
thread, which is what you do when raising something rather than answering.

Still true, in the shape `spec/` has now: a delivery is a `release-<version>`
tag, and **unagreed work does not go in `spec/` at all** — `spec/draft/` was
removed with the rest of the version directories on 2026-08-19, and `spec/`
holds only `openapi/`, `database/` and `conformance/`. Unagreed work is a
`docs/` document until it is agreed. The outbox is for correspondence — asks, replies,
corrections — and Studio's inbox README states the rule its own side follows,
which is worth matching: **every link in a document there resolves inside that
directory**, so a reader holding only the folder never hits a dead end. Name
outside documents in prose rather than linking to them, and restate anything
load-bearing.

**Writing to the outbox is publishing.** Studio reads it where it sits; there is
no send step and no chance to take it back. Treat a file appearing there as
having been read.

### Stop when it is settled (user, 2026-08-07)

**A topic ends the moment both sides agree, or one side accepts. Do not reply
again.** An acceptance is the last word on a thread, not an invitation to
acknowledge the acceptance.

- **You accept** → say so, say what will be done, stop. No "thanks", no
  restatement, no closing courtesy that needs answering.
- **They accept** → nothing further is owed. Do not confirm receipt.
- **Both agree** → the thread is closed even if some detail remains
  interesting. Interesting is not a reason to keep writing.

**A genuinely new question is a new thread**, with a new base name — not a
trailing question inside an acceptance, which reopens what it just closed. If a
sub-question would change what gets built, decide it from what they already said
and state the decision; they will correct it if it is wrong. Every extra round
costs both sides a read of a document that says nothing new.

The counter-case, so this is not read as "never write twice": a thread reopens
when a *fact* changes — a measurement lands, something ships, something turns out
to be wrong. That is new information, not a further round on settled ground.

### Five rounds, then escalate (user, 2026-08-07)

**Scope a topic so it converges in at most five rounds, counting both sides.
If it has not closed by the fifth, stop and tell the user.** Do not open a sixth.

**The thread suffix is the counter**, which is the point of the naming scheme:

| File | Round |
|---|---|
| `a.md` | 1 |
| `a.1.md` | 2 |
| `a.2.md` | 3 |
| `a.3.md` | 4 |
| `a.4.md` | **5 — last** |

Reaching `.4` unclosed is the signal, not a suggestion. Escalate with what is
agreed, what is not, and which specific question is holding it — the user is
being asked to break a deadlock, not to read the thread.

**Small and precise is what makes five enough**, so the work is in the scoping,
not in the rationing:

- **One decision per thread.** A document that settles three things needs all
  three to converge before any of them can close.
- **Split rather than bundle.** A new base name is cheap; a thread that cannot
  close because one of its parts is contested is not.
- **State a position, not a menu.** Options invite a round of choosing. Decide
  from what the other side has already said, say what was decided, and let them
  correct it — one round instead of two.
- **Carry the evidence with the claim.** A round spent asking "how do you know
  that" is a round spent on nothing.

**Measured against this rule, the threads so far:** the two Studio raised closed
at round 2, which is what the shape should look like. `llm-provider-and-auth`
closed at round 3 — but it covered nine separate matters and converged only
because both sides accepted nearly everything. **Had any one of the nine been
contested it would have blocked the other eight**, and that is the failure this
rule prevents. It should have been three or four threads.

This is a correction. On 2026-08-06 three files were copied into
`…/vscode/scala/agent-studio/` without asking — `docs/llm-provider-and-auth.md`
twice and `docs/schema/openapi-0.8.0.json` once. Nothing broke, and that is not
the point: a provider that writes into the consumer's tree makes "who changed
this" unanswerable from either side, which is precisely what a signed contract
and a per-version delivery directory exist to keep answerable.

**Reading outside is still fine and is worth doing.** Studio's
`docs/adr/*.md` were read to write `spec/draft/llm-provider-and-auth.md` §4,
and that is what turned a set of recommendations into confirmation of decisions
Studio had already made, plus one real interface gap (ADR-0023 needing an MCP
route, which became 0.8.0). Read freely; write nothing. Read-only git in another
repo (`git -C … log`, `status`, `show`) is reading.

**Do not "undo" a past violation by reaching out again.** Deleting or reverting a
file already sitting in another repo is another write outside this directory.
Report what is there and let the user decide.

**The rule is reciprocal — the same one is set on the Agent Studio side**
(user, 2026-08-06). So it holds in both directions: nothing arrives in this tree
from Studio either, and **the user is the only channel between the two repos**.
Two consequences worth having in mind:

- A file here that you did not write and git does not explain came from the
  user. Ask rather than assume it is stale or a mistake.
- "Studio already has X" is never safe to assume from having produced X. It is
  delivered when the user says it is delivered.

