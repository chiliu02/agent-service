# CI — `ci.py`, and why there is no CI service

Companion to the deployment notes in
[`claude-python-references.md`](../impl/claude-python/docs/claude-python-references.md). This is the
reference for everything the repository checks automatically: what runs, what
each stage proves, every setting it uses, and the parts that look simplifiable
and are not.

**One runner for the whole platform.** `.ci/ci.py` runs every `uv`/`docker`
command with an implementation directory as its working directory; git and the
documentation stages run from the platform root.

**Three lists, different lengths, on purpose.** Plan 8 step 7 arrived one stage
at a time rather than all at once, and is now complete:

| Constant | Contents | Used by |
|---|---|---|
| `IMPL` | `impl/claude-python` | `freeze` (the version and the migration tree), and `_run`'s default working directory |
| `UNIT_IMPLS` | `claude-python`, `codex-python`, `gemini-python`, `common/agent-spec` | `unit` — a directory with no `pyproject.toml` or no `tests/` is skipped with a printed line |
| `CONTAINER_IMPLS` | `claude-python`, `gemini-python`, `codex-python` | `container` and `gates` — all three since 2026-08-12, when the Gemini build gained persistence |

A directory can still be in one list and not the next, and `common/agent-spec`
is what that looks like: it has a suite worth running — ~1,200 lines and 25
tests since the persistence layer moved into it — and **must never join
`CONTAINER_IMPLS`**, because there is no image to build from it. `UNIT_IMPLS` is
listed explicitly rather than globbed for exactly that reason: a glob of
`impl/*` would try to containerise it.

**It lives in `.ci/`, and resolves `ROOT` as its own parent's parent.** It sat
at the repository root until 2026-08-07 and moved so that the root shows three
directories — `spec/`, `impl/`, `docs/` — and nothing else. **That `ROOT` line
is the one thing in this file to be careful with**: every path here is built
from it, so an off-by-one does not fail loudly. It would address `.ci/impl` and
`.ci/spec` and a git repository that is not there, and the stages would report
everything as *missing* rather than as *broken*.

Adopted 2026-08-06, closing [`dev-todo.md`](./dev-todo.md) item 1. Numbers in
this document are **measured on this host** (Windows 11 + Docker Desktop/WSL2)
unless they say otherwise.

---

## The decision: no CI service, no remote

This repository had **no git remote** when the call was made — `git remote -v`
was empty — and the call was to keep it that way and drive the same stages from
one local command.

**It has one now, and that is a fact rather than a reversal** (measured
2026-08-13): `gitea` at `http://localhost:3000/harness/agent-service.git`, the
forge in the `agent-harness-infra` compose project, with `main` pushed to it.
**Nothing about the decision below has changed** — there is still no CI service,
no runner and no job, and `ci.py` is still the only thing that runs the stages.
What changed is that the trigger this section names at the end has fired, so the
question is open rather than answered.

The item was originally written as "add a CI job", which was misleading: with no
remote there was no job to add, only infrastructure to adopt. **With a remote
there is now a job that could be added**, and it is a decision nobody has taken.
What the current arrangement buys and costs:

| | |
|---|---|
| **Buys** | Nothing to authenticate to. No secret to store anywhere. No queue, no runner, no third party holding a repository whose documented capability is arbitrary shell execution. |
| **Costs** | It only runs when you run it. The pre-commit hook is the partial answer; it deliberately carries only the fast half. |

Revisit this if the repository ever gains a remote. **It has** — see above — so
this is now a live question rather than a standing instruction, and the answer is
the user's. Nothing in `ci.py` assumes a local machine except the pre-commit hook
and the Docker socket, so the stages themselves would port to a runner on that
forge unchanged. The *buys* column is what would be spent: a runner on that host
would hold a repository whose documented capability is arbitrary shell execution.

---

## Running it

```bash
uv run --no-project python .ci/ci.py                  # all six stages, 3m58s
uv run --no-project python .ci/ci.py --fast           # freeze + links + references + unit, no Docker
uv run --no-project python .ci/ci.py --stages freeze,container
uv run --no-project python .ci/ci.py --fast --fail-fast     # what the hook runs
uv run --no-project python .ci/ci.py --fast --serial-unit   # one suite at a time, streaming
```

Install the pre-commit hook (once per clone):

```bash
git config core.hooksPath .ci/hooks
```

### Flags

| Flag | Effect |
|---|---|
| `--stages a,b` | Run a subset. Unknown names are an error, not a silent skip. |
| `--fast` | `freeze` + `links` + `references` + `unit`, and `unit` gets `-m "not postgres and not live"`. Needs no Docker daemon. |
| `--fail-fast` | Stop at the first failing stage. Unreached stages print as `n/a`. |
| `--serial-unit` | Run `unit`'s suites one at a time, streaming, as it did before 2026-08-17. Roughly doubles the stage. For watching a suite make progress, or reading a hang against the others. |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Every stage that ran passed. |
| `1` | At least one stage failed. |
| `2` | A Docker-requiring stage was asked for and `docker` is not on `PATH`. |

---

## The six stages

Run in the order listed. **Not fail-fast by default** — knowing that `freeze` and
`container` are both broken is worth more than one run per defect, and no stage's
setup depends on an earlier one having *passed* (`gates` needs the image
`container` builds, and checks for it rather than assuming).

| Stage | Proves | Needs | Measured |
|---|---|---|---|
| `freeze` | every release tag still resolves to its recorded commit; `spec/` carries one version | git | 1–9 s |
| `links` | every relative link and `#anchor` in the documentation resolves | nothing | <0.1 s |
| `references` | no code comment names a document; every `CP-`/`CX-`/`GP-` ID resolves | nothing | 1–2 s |
| `unit` | **every implementation's** in-process suite, and the specification's document tier | Docker¹ | 20 s under `--fast`; 40–60 s by default (86 s / 89 s with `--serial-unit`) |
| `container` | **every** implementation's image builds; the conformance suite against a real container, both deployments | Docker | 63–75 s |
| `gates` | a misconfigured image exits 3, **for every image** | Docker | 21–41 s |

Ranges, not single values, over two full runs. `gates` is the widest because
each of its eight cases is a container start; `freeze` is fast when git's index
is warm and several seconds when it is not. Treat them as orders of magnitude —
nothing here asserts a performance budget.

**`container` and `gates` have outgrown their ranges** — one full run on
2026-08-17 measured 110.9 s and 42.3 s against the 63–75 s and 21–41 s above,
which is what took the whole run to 3m58s. That is a third image and more boot
cases since the ranges were taken, not a regression, and it is recorded here as
an observation rather than a re-measurement: one run is not a range. **`unit`'s
row is the one that was re-measured**, on both sides of the change below.

**`and not live` is load-bearing and costs money if dropped.** A command-line `-m` REPLACES the one in `addopts`, so a bare `-m "not postgres"` re-selects the two tests in `test_live.py` that spend real money. Measured 2026-08-08. Nothing was ever spent -- those tests carry a second guard and pytest does not load `.env` -- but that is accidental safety, and the pre-commit hook runs exactly this invocation. `test_suite_integrity.py::test_the_ci_runner_never_re_selects_the_paid_tests` is the regression guard.

**`unit` loops over `UNIT_IMPLS` since 2026-08-07**, when `codex-python` gained
its first tests. `impl/common/` is deliberately not in that list -- it is assets
and clients, not an implementation -- and the list is explicit rather than a glob
of `impl/*` for exactly that reason. A directory with no `pyproject.toml` or no
`tests/` is skipped with a printed line, so an implementation that silently
stopped being collected is visible rather than merely absent.

¹ Only because `agent_spec.db.testing` starts a Postgres when
`AGENT_SERVICE_TEST_DATABASE_URL` is unset. `--fast` adds `-m "not postgres"` and
needs no daemon.

### `freeze` — a published document is never edited in place

This is AS-24 of the signed interface contract. Until this stage existed the rule
held because it was *remembered*.

**THE TAG IS THE FREEZE, since 2026-08-19, and this stage was rewritten around
that.** It used to walk git history for a content commit after a freeze point —
a lot of machinery defending a weak position, because a directory *can* be
edited and the walk could only notice afterwards. Now `spec/` carries the
current version alone and every delivered version lives in its
`release-<version>` tag. Git makes the bytes immutable, so there is nothing to
watch, and **the one remaining way a delivered version can change is a MOVED
TAG**.

Three checks on the openapi stream:

1. **Every recorded release tag still resolves to its recorded commit.** The
   rows come from `spec/README.md`, parsed **by shape rather than by position** —
   three cells with a 40-character sha1 last — so the table survives the README
   being rewritten around it. **A missing tag is a failure, not a warning**: a
   row is a claim that a version was delivered, and if the tag is gone either
   the claim is false or the tag was deleted. Both need a person.
2. **`spec/openapi/` carries exactly one version.** Two would mean a cut left a
   file behind, and a consumer reading the directory could not tell which is the
   specification.
3. **A bare `spec/VERSION` must be tagged.** Main is always a `-snapshot`; the
   bare state exists at exactly one commit, the one the tag names. A bare
   version anywhere else is a cut that was never tagged — and an artifact built
   there would claim to be a release while coming from an unnamed commit.

**The DDL keeps the old machinery**, unchanged, because its stream did not move.
`spec/database/agent-service-<revision>.sql` is named by Alembic revision, a
revision's DDL is written once, and the file at the current head is still in
flight until a new revision appears. Two checks per file: no content commit
after it was frozen, and the working tree still matches what git has.

**`git diff`, not a byte comparison**, and that is deliberate. Git for Windows
sets `core.autocrlf=true` globally and `.gitattributes` here is narrow enough to
say nothing about `spec/database/`, so a blob's bytes and the working tree's
bytes legitimately differ on this host. `git diff` applies the same filters git
itself would, which is the comparison that means *unchanged*.

**Why the collapse.** Every document existed twice: a canonical under
`snapshots/openapi/` and a delivery copy under `snapshots/<version>/`, with the
sha256 table and a byte-comparison employed for nothing but keeping the two
identical. Sixteen files and the `Canonical`-is-a-path branch of
`_check_bundle_copies` went away together; those rows now read `frozen`, meaning
the file *is* the artifact and its hash is the whole check.

**The DDL deliberately did not collapse into versions.** A document belongs to
one version; the DDL is named by Alembic revision and most versions change no
schema. Filing it under versions would make the platform's schema reachable only
by knowing which release shipped it. **It is a separate stream** — it moves when
a migration lands, not when the document does — and all three implementations
share it.

**This paragraph used to say the DDL "describes this implementation's database",
and Plan 9 is the correction.** Persistence is a feature of `agent-service`, not
of any agent SDK — the tables store what `/v1` returns — so a second
implementation persisting the same API needs the same schema, not one of its
own. Step 1 (2026-08-08) gave the DDL its own version stream; step 2 moved the
file to what is now `spec/database/` and left the Alembic tree behind at
`impl/common/db/` as its generator.

**Check 1 follows renames, and that is Plan 8's doing** (step 1, 2026-08-07).
It used to read `git log --format=%H -- <path>` and require exactly one commit
— which stops meaning anything the moment a published file moves. Moving the
implementation into `impl/claude-python/` renamed all sixteen: *before* the
migration commit a plain `git log` on the new path returned nothing at all
("not committed"), and *after* it returned the migration commit and reported
every one of them as freshly published, resetting the horizon the check exists
to hold.

`--follow` crosses the rename and `--numstat` is what tells a move from an edit,
measured on a rename this repository already had:

```
C 4da161e9
0    0    docs/contract/{ => 0.5.1}/openapi-0.5.1.json
C b7be5fc
2360 0    docs/contract/openapi-0.5.1.json
```

A pure rename adds and deletes nothing. So the rule is now *exactly one commit
with a nonzero line count anywhere in the followed history*, which is what
"written once and never edited" always meant and is insensitive to where the
file lives.

**`-M100%` is load-bearing, and this stage going red is what found it.** At
git's default similarity threshold `--follow` walks off the file. The published
documents are successive versions of one OpenAPI surface and are therefore
near-identical, so git read the *addition* of `openapi-0.9.0.json` as a rename
of `openapi-0.8.0.json`, that as a rename of 0.7.0, and so on back to the commit
that created `schema/` — nine of the sixteen files reported between two and six
"content commits" and failed. At 100% only a byte-identical move is followed,
which is what a move is and what a new version of a document is not.

**Check 2 compares against HEAD**, not against the publishing commit, for the
same reason: after a rename the file does not exist at that commit under this
path, so the old comparison would have had nothing to diff against and would
have passed silently.

**One consequence, and it is inherent:** the migration commit itself cannot
satisfy this stage, because the stage's subject is committed history and the
rename is not committed yet. Plan 8 step 1 was committed with `--no-verify` and
the full run was done immediately afterwards. Any future step that moves a
published file is in the same position.

**The in-flight file is exempt in each directory, and the two directories read
different streams for it.**

| Stream | Named by | Read from |
|---|---|---|
| `spec/openapi/<impl>-<version>.json` | the DOCUMENT version | `spec/VERSION` (Plan 8 step 5) |
| `spec/database/agent-service-<revision>.sql` | the **Alembic revision** | the migration tree's head (Plan 9 step 1) |

**Nothing is named by the build version any more.** `schema/` was, and it was
the wrong stream for a schema several implementations share:
`agent-service-0.16.0.sql` means nothing once `codex-python` is at 0.3.0. Measured
before changing it — **thirteen published DDL files held two distinct bodies**,
one per revision, and eleven were an unchanged schema re-emitted under a new
build version with a new timestamp in the header. Now there is one file per
revision, and `test_every_published_ddl_names_a_real_revision` asserts that set
equality in both directions.

`_alembic_head()` **parses** the revision files rather than importing Alembic,
because this runner is stdlib-only on purpose — it has to be able to drive an
implementation that is not Python. The head is the revision that is nobody's
`down_revision`; more than one head is a loud failure, not a guess.

**Dropping the timestamp from the header is what makes the DDL checkable at
all.** With it, every regeneration was a diff and the only safe habit was not to
run the generator; without it, re-running produces a byte-identical file unless
the schema really changed — which is why
`test_the_published_sql_schema_matches_the_migrations` can now compare the whole
file instead of only the body.

Exemption is needed at all because the file whose name matches is the one being
cut, and it is edited right up until release. It freezes the moment its own
stream moves on, with no action from anyone: a new `spec/VERSION`, or a new head
revision, is what promotes the previous file from in-flight to frozen.

**One edge this creates, and it is the cost of publishing per revision:** a
*historical* revision's DDL added for the first time is not exempt and has no
commit yet, so `freeze` reports it as "not committed" until the commit lands.
That is the same `--no-verify`-then-verify position as a move, and it happened
once, on the step-1 commit itself. (Written without a worked example on purpose — one would go
stale at the next bump, which is the failure this whole stage exists to catch.)
The other edges are already pinned by tests:
`impl/claude-python/tests/test_api_meta.py` (served `info.version` ==
`spec/VERSION`, `deployment.service.impl.version` == `pyproject.toml`,
and the published file == what the app serves) and
`spec/conformance/conftest.py` (`spec/VERSION` == published file).

**`git diff`, not a byte comparison.** Git for Windows sets `core.autocrlf=true`
globally and `.gitattributes` here says nothing about either directory
(`git check-attr text -- spec/0.5.1/openapi-0.5.1.json` →
`unspecified`), so a blob's bytes and the working tree's bytes legitimately
differ on this host. `git diff` applies the same filters git itself would.

**In `spec/<version>/`**, every delivery copy. The pairs are read
from the sha256 table in `spec/README.md` rather than restated in the
script — a second list is a second thing to keep in step, which is the failure
mode that table already had. Rows are matched by *shape* (a `|`-delimited line
whose third cell is 64 hex characters), so a row that loses its hash stops being
read rather than being read wrong.

| Check | On failure |
|---|---|
| Each copy matches the sha256 recorded beside it | **FAIL** — whichever side moved, the table is lying about the file next to it |
| A copy whose canonical is a **path** is byte-identical to it | **FAIL** — both ends are frozen, so this is an edit in place, not a stale copy |

A row whose canonical cell reads **`frozen`** has nothing to compare against: the
copy *is* the delivered artifact and is never refreshed in place, so its recorded
hash is the whole check. It is still fully protected — editing it fails with both
hashes printed.

**A third check existed and was removed on 2026-08-07**, and the reason is worth
keeping because the reasoning was right and the application was wrong. It
compared a copy against a *living* canonical and reported `STALE` rather than
failing, so that ordinary drift in `spike-findings.md` would not fire a
failure. But the only row it governed was inside `spec/0.5.1/` — the
**signed bundle**, which this repository's own rule says is written once and
never edited, and which Agent Studio invoked against its own interest the same
week. So the check was asking for an edit that must not happen, and from the
moment probe M2 landed it said so on every run.

**A check that fires when nothing is wrong gets ignored, and then so does the one
above it** — the exact failure the `STALE`-not-`FAIL` design was meant to avoid,
arrived at by the design itself. Refreshing before a bundling is still correct; it
happens into the *new* version's directory.

> **This reversed a documented decision** (user, 2026-08-06).
> `spec/README.md` said those copies are *"not enforced by a test,
> deliberately: code here does not read from `docs/`, so no assertion may depend
> on a file in this directory."* **That sentence still stands** and is why no
> test checks them. `ci.py` is not a test: it asserts nothing about the service
> and cannot make `tests/` depend on `docs/`. What was superseded is only the
> sentence after it — that the hashes *"are only as current as the last person to
> run `sha256sum`"*.

### `links` — every relative link and `#anchor` resolves

Scans `README.md`, `CLAUDE.md` and everything under `docs/` **at four levels** —
the platform root and each of the three builds. All four, because a build's
documents live beside its code and the two `docs/` trees link across the
boundary, which is exactly the class of link a move breaks. It also scans
`spec/`, named explicitly since Plan 8 step 2 moved it out of `docs/`; the
outbox came back under `docs/` on 2026-08-07 and needs no entry of its own.
Checks two things per link: the file exists, and — for a `#fragment` into a
`.md` file — a heading slugifies to it. Costs nothing; runs in `--fast` and
therefore in the hook.

**A build with no entry in `_LINK_LEVELS` is not scanned, and the stage passes
anyway** — which has now been the same defect twice. `codex-python` went
unscanned for its whole existence until it was noticed; `gemini-python` then
repeated it exactly, unscanned from 2026-08-11 to 2026-08-21. Nothing reports
this, because a stage that reads fewer files simply passes faster. **Add the row
in the commit that creates the build.**

**Why it exists.** These documents cross-reference each other constantly; that
is the house style and it is what makes the reasoning followable. So a moved
file breaks readers silently. Three moves happened in two days —
`spec/` into per-version directories, `llm-provider-and-auth.md` into
`draft/` — each repaired by hand and "verified" with a throwaway script retyped
from memory.

**One of those scripts was wrong, and that is the real reason.** Its slug regex
was `[^a-z0-9 -]`, which drops underscores. GitHub's keeps them. So
CP-090` was
compared as `maxbudgetusd…` and reported dead — it was not, and five documents
link to it correctly. **Every anchor containing an underscore was a false
positive**, and the report of a "pre-existing dead anchor" that followed was
simply wrong. `_slug()` keeps `_` and says why.

**Fenced and inline code are stripped before scanning, not filtered after.**
`docs/spike-findings.md` contains a probe transcript reading
`AssistantMessage[model=…](tool_use(PowerShell …))`, which no regex can tell
from a link. The ad-hoc checker reported it and it was waved away as a false
positive — the habit that makes a checker worthless. Stripping code blocks
removes the class rather than the instance.

**External links are deliberately not checked.** `http(s)` needs the network, is
slow, and fails for reasons unrelated to this repository. A stage that goes red
because a third party had an outage stops being read.

**It covers the signed bundle, and that is a feature.**
`spec/0.5.1/` cannot be edited (AS-24), so if a link inside it breaks,
the fix is to put back whatever moved — not to touch the document. This stage
forces that rather than leaving it to someone noticing.

Verified against a probe file carrying a missing target, a dead anchor, a valid
underscore anchor, a fenced fake link and an inline-code fake link: **2 failures
reported, exit 1, and the three decoys neither failed nor counted.**

### `references` — code cites one document per build, by ID

**Three builds since 2026-08-11**, when `gemini-python` gained a references file
of its own (`GP-nnn`). It is registered in `_REFERENCE_DOCS` and scanned in
`_SCANNED` **even though it has no `src/` yet** — it is probes and evidence, and
the citations that rotted were all written before anyone thought of them as
load-bearing. Adding it turned up eight document-name citations in its own probe
docstrings, which is the rule working as intended on its first day.

**Adding a fourth build is three edits**: a row in `_REFERENCE_DOCS`, a row in
`_SCANNED`, and the prefix in `_REF_ID`/`_REF_HEADING`. The two regexes are
separate because one matches a citation anywhere in a line and the other is
anchored to a heading.

**Added 2026-08-10 (user), and it is the only stage that reads prose in code.**
`links` reads markdown and citations live in comments, so for as long as this
repository existed nothing looked at them. When someone finally did: **170
citations, 50 of them unusable** — 31 bare filenames that resolved from nowhere,
19 paths broken by a directory move, and 49 heading anchors nothing had ever
verified.

**Three failures:**

* a **path-shaped** citation in a comment or docstring — a `.md` of any shape;
* an **ID with no entry** in that build's references file;
* a **references file that links out** — rule 2 is that it links to nothing, so
  a reader holding only that file cannot reach a dead end.

**What it reads, and what it deliberately does not.** Comments (`tokenize`) and
docstrings (`ast`) in `.py`; `#` comments in `*.yaml` and `Dockerfile`, because
`compose.yaml` cited a document eleven times. **Not string literals** — a path in
executable code either resolves or fails a test, and a path in a *log message* is
aimed at an operator outside this tree, for whom a repository-relative path is
the only actionable form. That exemption has one known cost, recorded in
`dev-todo.md` §0a: four pydantic field descriptions name a document and pydantic
publishes descriptions into `/openapi.json`, so three dead paths are currently
*in the contract*. They are fixed at the next cut rather than now, because
editing one breaks AS-24 for an image a consumer is testing.

**`_SCANNED` is the whole policy.** A build's tree cites that build's file;
`impl/common/` and `spec/conformance/` cite **nothing at all** — the first is
shared by every build and the second measures every one of them, so any document
either names is the wrong one for at least one of its readers. That is the same neutrality failure four
boot-gate assertions committed by naming one SDK's environment variables.

**`AGENTS.md`, `CLAUDE.md` and `README.md` are exempt.** The first two are files
the *product* reads at runtime — naming one is naming a feature, the way `.env`
is — and the third sits beside the code and moves with it. None can be reached by
a path that rots.

### `unit` — the in-process suite

`uv run pytest` in `impl/claude-python/`. `agent_spec.db.testing` supplies its own
Postgres: an already-running server if `AGENT_SERVICE_TEST_DATABASE_URL` is set,
otherwise a testcontainer, otherwise those tests skip.

**Then a second `uv run pytest`, in `spec/conformance/`, and it is not
optional.** That package used to be collected by the run above and skip itself
for want of `AGENT_SERVICE_TEST_BASE_URL` — except for its **document tier**,
which reads published JSON, needs no service, and contains the negative control.
Plan 8 step 3 moved the package out of the implementation's `testpaths`, so
without this second run the document tier would execute only in `container`,
i.e. only on a machine with Docker. *A negative control that needs a container
is a negative control nobody runs* — the exact failure it exists to prevent.

Both runs happen even if the first fails: two broken things are two facts, and
one run per defect is what this file deliberately avoids.

#### The suites run concurrently (2026-08-17)

**This stage was 94% of the pre-commit hook, and it was the sum of five
independent processes rather than the longest of them.** Nothing about *what*
runs changed — same commands, same markers, same working directories — only how
many are in flight at once.

Measured on this host, `--fast`:

| | Serial | Concurrent |
|---|---|---|
| `claude-python` (552 tests) | 33.0 s | 44.1 s → **20.2 s** with all three on xdist (below) |
| `codex-python` (184) | 32.5 s | 37.0 s → **17.3 s** |
| `gemini-python` (143) | 16.7 s | 20.0 s → **13.7 s** |
| `common/agent-spec` (40) | 0.7 s | 1.0–1.4 s |
| `spec/conformance` (42) | 0.1 s | 0.1 s |
| **stage** | **86–87 s** | **48 s**, then **21 s** mean with xdist (17.7–27.1) |
| **whole `--fast` run** | **92.9 s** | **57.4 s**, then **~28 s** |

**Each suite gets slower and the stage gets much faster**, which is the shape to
expect and worth stating so nobody reads the 44 s as a regression. The stage
cannot go below its longest suite, so `claude-python` is now the floor and the
remaining 4 s is what five pytest startups cost against each other.

**Outside `--fast` the gain is much smaller — 89 s serial against 79 s
concurrent — and that is not a disappointment, it is the same fact.** The
default run adds `claude-python`'s Postgres tests, which start a testcontainer,
so the long pole grows and everything else still finishes inside it. A stage is
only ever as fast as its slowest member.

**The default run is also the noisy one — 55 s and 79 s on two runs of the same
tree** — and the variance is the testcontainer, not the concurrency. Do not read
a fast default run as evidence about anything below; `--fast` is the mode with a
stable number, which is also the mode the hook uses.

#### Two suites run on xdist, and the two are wired differently

**`pytest-xdist` is a dev dependency of `claude-python` and `codex-python`**,
and `ci.py` passes `-n 4` to both — but under different conditions, which is the
part to get right:

| Build | `-n` passed | Because |
|---|---|---|
| `codex-python`, `gemini-python` | **always** (`UNIT_XDIST_ALWAYS`) | nothing is shared: no database, no `conftest.py`, no session- or module-scoped fixture in `tests/`, and every session takes its agent state and workspace from a per-test `tmp_path` |
| `claude-python` | **only under `--fast`** | its Postgres tests share one server and one schema, and `--fast` is the branch that just deselected them |
| `common/agent-spec` | never | 1 s in total; there is nothing to split |

**The asymmetry is deliberate and is not tidiable into one rule.** A build
gets unconditional workers by having nothing to contend over, which is a
property of that build's tests rather than of the runner.

##### `claude-python`: the pairing is the safety argument

`-n` is passed only on the branch that has just passed `-m "not postgres"`, and
that pairing must not be loosened:

> **The Postgres tests are not safe to distribute.** They share one server and
> one schema and isolate themselves with a `drop_all`/`create_all` per test.
> `conftest.py`'s `postgres_server` fixture says so in as many words. Splitting
> them across workers does not fail cleanly — it fails as flakes.

So `-n` is attached to the marker rather than to the build, and its default run
stays single-process. Verified by stubbing the runner and printing every command
in both modes: `claude-python` carries `-n` under `--fast` and not otherwise,
`codex-python` carries it in both.

**Neither build puts it in `addopts`.** For `claude-python` that is the same
safety point — a developer typing `uv run pytest` gets the Postgres tests *and*
no workers, the combination that is always correct. For `codex-python` it is
milder: the runner should be the thing that decides how much of the machine to
take, since it is the thing running five suites at once.

Measured alone, 2026-08-17, at `-n` 1 / 4 / 6 / 8:

| | 1 | 4 | 6 | 8 |
|---|---|---|---|---|
| `claude-python` | 33.0 s | 14.3 s | 14.3 s | 10.5 s |
| `codex-python` | 37.1 s | 11.6 s | 9.7 s | 9.1 s |
| `gemini-python` | 16.4 s | 6.3 s | 6.5 s | — |

**Why 4 and not 8, which is the interesting half.** Each suite drops below the
next-slowest one well before the workers stop helping, and **a stage can never
go below its longest member** — so the extra workers buy the stage nothing and
are spent on contention. That is measured, not argued: dropping `claude-python`
from 6 to 4 made the *stage* faster rather than slower (41–46 s → 35.7–37.0 s),
because the workers had been competing with `codex-python` for the cores it
needed to be the pole.

For `claude-python` there is a second reason to stay low. It asserts budgets by
letting them elapse, and roughly a dozen of those assertions are *upper* bounds,
the tightest `elapsed < 0.05`; every worker makes a scheduling stall likelier.
Twelve consecutive stage runs, no flakes. `codex-python` has one such assertion
(`elapsed < 1.0` against a 0.3 s budget) and correspondingly more headroom.

##### The stage is CPU-bound now, and `gemini-python` is the evidence

**This started wait-bound and no longer is, which is the fact that governs every
further attempt.** The first two builds gained hugely because their cost was
elapsed budgets and per-test subprocess lifecycle — sleeping workers need no
core. By the time all three are distributed, 4 workers per build sit on a
14-core host and the cores are the constraint.

`gemini-python` was added last and measures the transition exactly:

| | Suite alone | In the stage | Stage total |
|---|---|---|---|
| before | 16.4 s | 18.9 s | **21.2 s** mean (20.1–23.4, n=7) |
| after | **6.3 s** | 13.7 s | **21.3 s** mean (17.7–27.1, n=12) |

**A 10 s win on the suite became NO measurable win on the stage at all.** The
per-suite numbers say where it went: the other two slowed to pay for it —
`claude-python` 18.4 → 20.2 s, `codex-python` 13.0 → 17.3 s.

> **This corrects a smaller sample that said otherwise.** Four runs against six
> gave 20.6 s → 19.5 s and were read as a ~1 s gain; at n=7 and n=12 the two
> means are 21.2 s and 21.3 s. **The run-to-run spread is ±3 s, several times
> any effect being looked for**, so a handful of runs here can show a gain, a
> loss, or nothing. Anyone re-measuring this needs a dozen runs per arm before
> the number means anything — which is itself a reason not to tune this further.

**It is in `UNIT_XDIST_ALWAYS` for consistency across the three builds** (user,
2026-08-17), not for the clock, and that is recorded here so nobody re-runs the
experiment expecting the earlier builds' result.

**So: adding a fourth build to that tuple, or raising `UNIT_XDIST_WORKERS`, is
not where the next gain is.** The remaining costs are the ~7 s outside `unit` —
`freeze` (3–5 s, dominated by `git log --follow` over 19 published files) and
`references` (1.5 s) — and the real waiting the suites still do, which would
mean making the courtesy-interrupt and turn-timeout budgets injectable so the
tests stop sleeping a real second each. Both are work; neither is a flag.

**Why the suites are safe to overlap, checked rather than assumed.** Each is a
separate process with its own virtualenv. **None binds a socket** — every suite
drives its app through an in-process ASGI transport at `http://test` — so there
is no port to collide on. Everything a suite writes or spawns comes from a
per-test `tmp_path`. The one genuinely shared resource is the Postgres that
`agent_spec.db.testing` starts outside `--fast`, and no other suite has a database.

**Where the time actually goes, since it is not compute.** The slow tests are
the ones asserting a *budget*, and they assert it by waiting: courtesy-interrupt
windows, turn timeouts, shutdown budgets. `codex-python` is the extreme — its
session fixture spawns and tears down a real app-server per test, which is 13.4 s
of teardown across the 20 tests in one module. That is why `UNIT_MAX_WORKERS` is
not sized against CPU count: sleeping processes do not need a core each.

**Output is held per suite and printed in `UNIT_IMPLS` order**, never in
completion order, so two runs of a green tree produce the same transcript and a
failure is always in the same place. `_run_captured` holds it; nothing parses,
filters or reformats it, which is what keeps `_run`'s rule — *show pytest's own
report, not one this file re-rendered* — intact. That rule is about the bytes
being unmodified, not about when they arrive, and concurrent children streaming
into one terminal would break it far worse than delay does. `stderr` is merged
into `stdout` at the pipe rather than concatenated afterwards, so a warning
printed between two test lines stays between them.

**Every suite is submitted before any result is read**, which is what preserves
the property the serial loop had: a suite is never skipped because an earlier one
failed, because there is no earlier one. Verified by stubbing the runner so
`claude-python` fails — all five still ran and the stage returned false.

Measured 2026-08-07: **570 passed, 2 skipped, 6 deselected** in the
implementation and **20 passed, 34 skipped, 5 deselected** in the conformance
project — 590/36/11 between them, which is what the single run reported before
the split.

### `container` — every image, and the suite where it is expected to pass

Loops over `CONTAINER_IMPLS`. Per implementation: build the image once, then run
the suite in each deployment it has — default stack, full teardown, persistence
stack where there is one.

**Every image is BUILT, including one whose suite does not run**, and separating
the two is the point. `gates` needs the image; a Dockerfile is the thing most
likely to rot unnoticed; and a build failure is a failure of this stage whichever
implementation it belongs to.

#### The label check — do the image's labels agree with the image?

**Runs for every build, immediately after it is built**, before the redirect
check. Two `docker` invocations, no service, no credential, no network.

An image is built against **two** published artifacts — an OpenAPI document and a
DDL revision — and states both on its pre-boot surface, from the constants the
code enforces. Since 2026-08-16 it also carries them as labels, so `docker
inspect` answers without starting anything and a consumer can check an image
against the two dependencies they already hold.

**That makes the labels a copy**, and the check is what keeps a copy honest:
`docker image inspect` against the published document the labels themselves name,
on `impl`, `document-version` and `schema-revision`. It compared against
`docker run --rm <image> agent-service-openapi` until 0.19.0, when that command was
removed; nothing was lost, because AS-24 already asserts a running service serves
exactly its published document and `PrebootSpec` is now part of it. The failure
message names the Dockerfile rather than only the mismatch, **because the
published document is the authority
and the label is the thing that is wrong**.

Hand-written labels rather than build args, deliberately: a build arg leaves the
label empty for anyone running a plain `docker build`, and the drift a constant
risks is exactly what this check removes — the same bargain `EXPECTED_REVISION`
already takes.

#### The redirect check — does a turn actually leave through the published variable?

**Runs for every build, before the conformance passes, including a build whose
live tier is blocked.** Free: no credential, no tokens, nothing reaches a
provider.

The stage starts the freshly built image as a plain container — not compose, since
no compose file passes an endpoint variable through and adding one to a product
file to make a test possible is the wrong direction — with:

- `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` and `AGENT_SERVICE_REQUIRE_MOUNTS=false`
- the build's own `credential_env_var` set to a **dummy that is shaped like a real
  key**, because at least one CLI refuses a malformed value before making any
  request and would pass this check for the wrong reason
- the build's own `endpoint_env_var` pointed at a stdlib `ThreadingHTTPServer` on
  this machine, reached through `host.docker.internal`

It then creates a session over `/v1`, posts one message, and **asserts on the
sink rather than on the turn**: the turn is expected to fail, because the sink
answers `401`. A request arriving proves three things at once — the variable moved
the endpoint, the agent selected an auth method, and the service's own generated
session files were accepted by the agent.

**The names come from `Containerised`, not from the image.** This check exists to
catch a build whose published `endpoint_source` has stopped working; asking the
build under test which variable to use would let it answer with whichever one it
happens to honour.

**Why it exists.** `gemini-python:0.0.2` could not take a single turn behind a
gateway and shipped anyway: setting `GOOGLE_GEMINI_BASE_URL` made its CLI infer an
auth type its own validator rejects, so it exited before opening a socket. Nothing
here could have caught it — the unit suites drive a stand-in binary with no auth
to reject, the conformance suite takes no turn, and every live probe ran against
the provider directly, which is the one path where the defect does not exist. The
consumer found it in a deployment. This is the missing rung between *the fake
binary accepted our argv* and *a real turn costs money*.

The wait ends at the first request rather than running out, so a healthy build
costs a few seconds and only a broken one pays `REDIRECT_TURN_TIMEOUT_S`.

#### The live tier can be blocked, and the reason is printed on every run

`Containerised.live_tier_blocked_by` is `None` when the live conformance tier is
expected to pass, and otherwise a sentence saying why it is not run. Today
exactly one entry carries one:

> **`codex-python`** — AS-13/14/15/20 and AS-24. Measured 2026-08-08: **37
> passed, 9 failed, 3 skipped**. Eight failures are the supplied-`sdk_session_id`
> cluster (`AsyncCodex.thread_start()` takes no id, so the field is refused with
> 400 and the thread id is known at creation rather than null). The ninth is
> AS-24: the served document is not byte-identical to
> `spec/openapi/openapi-0.16.0.json` — 151 keys only in the published
> one, 19 differing, 7 only in the served one.
> `impl/codex-python/docs/`codex-python-references.md` has all of it.

**The 151 are an unbuilt feature, not a divergence.** They are `StoredEvent` and
its neighbours, and *persistence is a feature of `agent-service`, not of the
agent SDK* (`docs/history/plan-9-design.md` (removed 2026-08-19; not carried in this repository) §1) — the Claude SDK has no
database either. They come back when this build implements it, and Plan 9 makes
the schema the platform's so it does not invent a second one. Do not read that
number as evidence about the core boundary.

**This is not a mute button and must not become one.** The failures are real and
recorded; what is missing is a decision — the core/extension split, Plan 8 step 6
— which needs a version and is the user's to make. The image is still built, and
`gates` still runs the whole boot-gate tier against it on every run.

**Printed, not filed**, because a tier that is silently not running is
indistinguishable from one that passes. The line appears in the `container`
stage's output whether or not anyone reads this document.

#### Why two passes where there are two

Builds the image once, then runs the suite twice: default stack, full teardown,
persistence stack. Only `claude-python` has both today — the Codex build's
history routes answer 404 with `type: .../persistence-disabled` by construction,
so a database pass would boot a Postgres nothing connects to.

**Running it twice is not thoroughness.** Across the whole conformance package,
`spec/conformance/test_contract_persistence.py` is the *only* module that skips
on which stack is in front of it — two tests want no database, three want one,
everything else is stack-independent. One of those three,
`test_an_unrecorded_id_is_a_PLAIN_404_not_the_disabled_one`, is a **negative
control**, and its own docstring makes the argument: this API answers 404 for two
conditions a client must act on differently — *"history is off here"* versus
*"no such id"* — and tells them apart by the problem `type`. Against a stack with
no database only the first is reachable, so an implementation that hard-coded the
disabled URI onto every 404 would pass. The database pass is what refuses it.

`test_contract_meta.py` also branches on the deployment *without* skipping
(`database_usable` must be `null` when unconfigured and a bool when configured),
so a single stack silently exercises one arm of it and nothing says so.

Measured, 45 collected either way:

| Stack | Result |
|---|---|
| default, no database | **43 passed, 3 skipped** |
| `--profile persistence` | **44 passed, 2 skipped** |

One more than before Plan 8 step 3 in each stack, and it is the same test:
`test_suite_integrity.py`'s guard on the document tier moved into this package
with the suite, so it is now collected here too. It was 42/3 and 43/2.

**Migrations are applied by the script, before the service starts.** Nothing in
the service runs them — `grep alembic src/` returns nothing and the image copies
no `alembic.ini` and no `migrations/`; CP-084 corrected the opposite
claim on 2026-08-06. An unmigrated database boots healthy and reports
`database_usable: false`, which is exactly the state the conformance fixture
*skips* on, so getting this wrong yields a green run that tested nothing. Order
is: `up postgres` → `alembic upgrade head` from the host → `up agent-service`.

Three consequences that are easy to "tidy" and must not be:

- **`compose.ci.yaml` publishes a host port for Postgres** where `compose.yaml`
  deliberately does not. Out-of-band migration means reachable from the host.
- **Teardown passes `-v`.** A surviving `agentsvc-ci_agent-db` volume would carry
  a migrated schema into the next run and make the migration a no-op.
- **The two passes are separated by a full teardown, not a restart.** The service
  reads `AGENT_SERVICE_DATABASE_URL` once at startup — `get_settings()` *pops* it
  from `os.environ` there — so switching deployments means a new container.

### `gates` — the half a running service cannot reach

Every other conformance test asks a live service what it does, which can never
check AS-2's actual claim: a service that exited 3 is not one anything can talk
to. `spec/conformance/test_boot_gates.py` starts deliberately misconfigured
containers and reads the exit code.

It needs `AGENT_SERVICE_TEST_IMAGE`, which the module refuses to default —
this machine carries other `agent-service` tags that boot without a credential
and serve older versions, and a default silently measured the wrong one. `ci.py`
passes each implementation's `<project>-agent-service` and checks the image
exists first, so the failure is a sentence rather than `docker: no such image`
buried in a subprocess.

**It loops where `container` may not**, and that asymmetry is the interesting
part: the boot-gate tier is the genuinely implementation-neutral half of the
specification — exit 3, a refusal naming a credential the image itself
publishes, a socket on every IPv4 interface — so it is the one tier a second
image can be held to today.

Measured 2026-08-08:

| Image | Result |
|---|---|
| `agentsvc-ci-agent-service` (claude) | **10 passed** |
| `agentsvc-ci-codex-agent-service` | **9 passed, 1 skipped** |

The skip is AS-3: that build publishes no provider selectors, so the clause has
no subject. **It passed only after four assertions in the module stopped naming
Anthropic's variables** — a fixture requiring `provider_selectors` to be
non-empty (which contradicted the very test it fed, and failed at collection,
taking all ten tests with it), the AS-2 refusal assertion, the near-miss probe
and the empty-value probe. All four were defects in the suite rather than in
either build, and all four were invisible until a second image existed.

---

## Settings — the complete list

Everything is a constant at the top of `ci.py`. There is no config file
and nothing is read from the ambient environment.

| Name | Value | Why |
|---|---|---|
| `PROJECT` | `agentsvc-ci` | Namespaces every container, network and volume away from a stack you already have up. Also what `down -v` scopes to. The Codex stack uses `agentsvc-ci-codex`, so two can be up at once. |
| `CI_HOST_PORT` | `8100` | **Not 8000.** `compose.yaml` publishes `127.0.0.1:8000` and the CI stack has to run beside it. The Codex entry uses `8110`, matching its own `compose.ci.yaml` default. |
| `CI_PG_PORT` | `15432` | The out-of-band migration route. Not any port the developer docs suggest (`55433`), and — since 2026-08-19 — **below 49152**, outside the Windows dynamic range where Hyper-V reserves blocks. The previous value, `55440`, landed inside a reservation (`55365-55464`) and compose could not bind Postgres at all: the stage failed with `ports are not available` before a test ran. Those reservations move across a reboot, so a port inside that range is a stage that fails on a schedule nobody controls. |
| `CI_PG_PASSWORD` | `ci-not-a-secret` | Throwaway, loopback-only, in a volume destroyed at the end of the run. |
| `CI_TEMP` | `temp/ci/` | Per `CLAUDE.md`: every temporary directory goes under `temp/`. The **platform root's** `temp/`, not the implementation's — this is the runner's scratch. Gitignored. |
| `IMPL` | `impl/claude-python` | The **reference** implementation: `freeze` reads `schema/` and the migration tree from it, and it is `_run`'s default working directory. Not the only one — see the three lists above. |
| `CONTAINER_IMPLS` | two `Containerised` records | Name, compose project, host port, whether it has a persistence profile, and whether the live tier runs. A record and not four parallel dicts, because a per-field dict keyed by name is the shape one field drifts out of silently. |

**There is no `IMAGE` constant any more.** Compose builds `<project>-<service>`
and there are two projects, so the name is `Containerised.image`. `gates` needs
it by name for the reason that module refuses to default it.
| `CONFORMANCE` | `spec/conformance` | The acceptance suite, its own uv project since step 3. Every pytest run against it uses this as the working directory instead of `IMPL`. |
| `BOOT_GATES` | `test_boot_gates.py` | Relative to `CONFORMANCE`, and named only so `container` can `--ignore` it and `gates` can run just it. |

### The generated env file

Written to `temp/ci/env.<impl>.nodb` and `temp/ci/env.<impl>.db` on every run,
never edited by hand:

```
WORKSPACE_HOST_PATH=<abs>/temp/ci/workspace-<impl>   # forward slashes, always
REFERENCE_HOST_PATH=<abs>/temp/ci/reference-<impl>
AGENT_SERVICE_REQUIRE_CREDENTIALS=false
AGENT_SERVICE_REQUIRE_MOUNTS=true
CI_HOST_PORT=8100                                # the implementation's own
CI_PG_PORT=15432
POSTGRES_PASSWORD=ci-not-a-secret
AGENT_SERVICE_DATABASE_URL=                      # or postgresql://…@postgres:5432/agent
```

**One file shape for every implementation, and the extra keys are deliberate.**
The Codex compose file names neither `REFERENCE_HOST_PATH` nor
`POSTGRES_PASSWORD`, and compose ignores an env-file entry nothing interpolates.
Writing the union keeps `_write_env_file` from branching on which build it is
serving — which is the branch that would eventually write the wrong port into
the right file. The mount directories *are* per-implementation, so two stacks up
at once never hand the same host directory to two unconfined agents.

Four things about it are load-bearing:

- **`--env-file` REPLACES the ambient `.env`, it does not add to it.** Compose
  reads a `.env` beside `compose.yaml` automatically, and yours holds a real
  `ANTHROPIC_API_KEY` and mount paths pointing at a real repository. A CI run
  must not boot an unconfined-`Bash` container over your working tree, and must
  not hold a key it could spend.
- **`ANTHROPIC_API_KEY` is absent, not empty.** Compose passes
  `${ANTHROPIC_API_KEY:-}` through, so absent and empty reach the container
  identically; absent is written this way so reading the file tells you the
  container has *no* credential rather than a blank one. The same holds for
  `OPENAI_API_KEY` and `CODEX_API_KEY` — no name is written, so no CI container
  of either image can spend anything.
- **`AGENT_SERVICE_REQUIRE_MOUNTS` stays `true`.** The two directories really
  exist, so the gate should pass — and if a future change breaks how mounts are
  passed, this run is what notices.
- **Forward slashes on Windows.** Compose's interpolation eats backslashes; this
  is recorded in `.env.compose.example` too.

### `compose.ci.yaml`

An overlay, **never used alone**, and there is now one per containerised
implementation. `compose.yaml` stays untouched: it is the file the security
comments describe and the file `tests/test_config.py` reads, so the CI stack
differs from the real one by exactly what is in the overlay.

| Service | Override | Note |
|---|---|---|
| `agent-service` | `ports: !override ["127.0.0.1:${CI_HOST_PORT}:8000"]` | **`!override` is required.** Compose *concatenates* sequence fields on merge, so a plain list would add a second publish and leave the developer port bound as well — the collision the overlay exists to avoid. Needs Compose ≥ 2.24; measured against v5.3.1. |
| `postgres` | `ports: ["127.0.0.1:${CI_PG_PORT}:5432"]` | Claude only. No `!override` needed — `compose.yaml` gives this service no `ports` at all. |

`impl/codex-python/compose.ci.yaml` has **only the first row**: that stack has no
Postgres to publish a port for, so the out-of-band migration route the second row
exists to open does not apply. Its default is `8110` rather than `8100` because a
full run has both stacks up in sequence against ports the previous teardown may
not have released.

Both keep the `127.0.0.1:` prefix that `compose.yaml` calls its most important
line. Neither answers on any other interface.

### `impl/.dockerignore` — one file, at the context root

**It is at `impl/`, not inside an implementation, because that is where docker
reads it.** Both compose files set `context: ..` — `pyproject.toml` names
`../common/agent-spec` as a path dependency and a path outside the context
cannot be COPYed — and docker reads `<context>/.dockerignore`.

**This was found by measuring, on 2026-08-08, and it had been broken since Plan 8
step 1 moved the context up on 2026-08-07.** The file was
`impl/claude-python/.dockerignore` and was silently unread for a day. A one-line
probe Dockerfile against `impl/`:

```
#4 [internal] load .dockerignore
#4 transferring context: 2B done          <- an EMPTY ignore list
#6 transferring context: 792.05MB 30.2s
```

792 MB and 30 s per build, and — the part that matters — the operator's real
`.env` crossing to the daemon on every build. It never reached a *layer*, because
each Dockerfile COPYs named paths only; but the opening rule of the file it
replaces was that the context must not carry a secrets file, and that had stopped
being true. After the move: **15.18 kB.**

---

## Nothing here can spend money

Four independent reasons, any one of which would be enough:

1. `pyproject.toml` sets `addopts = "-m 'not live'"`, so every pytest invocation
   deselects the paid tier.
2. No stage passes `-m live` or unsets that filter, and `--stages` cannot reach
   one that does.
3. The CI container is booted with **no `ANTHROPIC_API_KEY` at all**.
4. `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` — measured: sessions spawn the CLI
   without authenticating, and only *turns* need a key.

Running the paid tier stays a command you type by hand:
`uv run --env-file .env pytest -m live`.

---

## The pre-commit hook

`.ci/hooks/pre-commit` runs `ci.py --fast --fail-fast`. **About 28 s to pass**
(measured 2026-08-17), ~1 s to reject.

**It was 93 s until 2026-08-17**, and 94% of that was one stage. Three changes,
all in `unit`: the five suites now run concurrently (93 → 57 s), then
`claude-python` (57 → 44 s) and `codex-python` (44 → 28 s) went onto xdist. The
hook is the reason any of it mattered — it stands between you and every commit,
and the whole argument for keeping the container stages out of it is that a hook
slow enough to be bypassed gets bypassed.

**Tracked, and installed by `core.hooksPath` rather than copied into
`.git/hooks`.** That directory is not version-controlled, so a hook living there
is invisible in review, absent from a fresh clone, and unrecoverable if the
checkout is thrown away.

```bash
git config core.hooksPath .ci/hooks   # once per clone; git never does this itself
git config --unset core.hooksPath     # off again
git commit --no-verify                # skip it for one commit
```

**`--fail-fast` is about the hook, not about correctness.** A deliberate run
stays non-fail-fast on purpose. A hook is the opposite case: it stands between
you and every commit, and the gap between rejecting in 3 s and rejecting in 45 s
is the difference between fixing the problem and reaching for `--no-verify`.
Measured, by staging a `freeze` violation and committing:

| | Time to block |
|---|---|
| without `--fail-fast` | **45.4 s** — `unit` ran anyway with the answer already known |
| with `--fail-fast` | **1.1 s** |

Measured 2026-08-08, and the first row is the one that moves: it is whatever a
full `--fast` run costs, so it read ~93 s before `unit` became concurrent and
~57 s after. **The argument does not depend on the number** — the point is that
the flag makes rejection independent of the suite's length, which is exactly why
it is the hook's and not a deliberate run's.

**It tests the working tree, not the index.** The strictly correct version
stashes unstaged changes around the run, which can lose work when the hook or the
stash pop fails — a bad trade for a check this cheap. Where that differs: edit a
published `schema/` file and *don't* stage it, and the hook blocks a commit that
is itself fine. Arguably right, since the file is wrong on disk either way, but
it will not be obvious in the moment.

**It exits 0 when `uv` is not on `PATH`**, rather than failing every commit on a
machine that cannot run it. This is not hypothetical politeness — it matters if
this repository is ever mounted as the agent's `/workspace`. `core.hooksPath`
lives in `.git/config`, which is *inside* the mount, so the container's git would
run this hook; and `uv` is **absent from the runtime image** (measured:
`docker run --entrypoint sh <image> -c 'command -v uv'` → nothing; `git` is
present). CP-082 measured that a hook referencing a missing tool
**blocks the commit**. The guard is what stops that.

### `.gitattributes` exists because of this hook

```
.ci/hooks/* text eol=lf
```

`git add` warned on the tracked hook: *"LF will be replaced by CRLF the next time
Git touches it."* The working copy was fine; the **next clone** would not have
been. Git for Windows sets `core.autocrlf=true`, and a CRLF `#!/bin/sh` fails as
`/bin/sh^M: bad interpreter: No such file or directory`. CP-082
measured the container's variant of the same failure, where the message is the
even less helpful `fatal: cannot exec '.git/hooks/pre-commit': No such file or
directory`.

**Scoped to `.ci/hooks/*`, not `* text=auto`.** The repository-wide form is
the better general fix — `.env.compose.example` recommends it, and it would make
the container's `GIT_AUTOCRLF` variable unnecessary — but it renormalises every
tracked file, and files frozen by AS-24 are the wrong thing to rewrite in
passing. Widen it deliberately, in its own commit, not as a side effect.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `127.0.0.1:8100 is already in use` | Another `ci.py` run, not your local stack — 8100 is this script's own port. The preflight check refuses rather than colliding. |
| `docker is not on PATH` (exit 2) | Use `--fast`, or `--stages freeze,unit`. |
| `migrations failed; the conformance run would only skip` | The out-of-band migration could not reach `127.0.0.1:15432`. Check the `postgres` container came up healthy; a failure here is caught deliberately, because the alternative is 45 green tests that skipped the ones that matter. |
| `no image agentsvc-ci-agent-service` | `gates` was run without `container`. Run `container` first, or `docker compose -f compose.yaml -f compose.ci.yaml -p agentsvc-ci build`. |
| `<file> has N commits that changed it` | A published document was edited in place. The content change needed a new version number, not an edit. A *move* does not count — `_content_commits` reads pure renames as `0 0` and skips them. |
| `<file> is not committed` | Either it really is untracked, or it was moved in a commit that has not been made yet. `freeze` reads committed history and cannot see a staged rename; see the note under `freeze` above. |
| A commit is blocked and the staged diff looks fine | The hook tests the working tree. Look for an *unstaged* edit to something under `schema/`. |

---

## Recheck when these change

| If you change… | Recheck |
|---|---|
| `compose.yaml`'s `ports` line | that implementation's `compose.ci.yaml` `!override` — a plain list would silently republish the developer port |
| `compose.yaml`'s service names | `Containerised.image` in `ci.py` (`<project>-<service>`) and `gates` |
| adding an implementation with a Dockerfile | `CONTAINER_IMPLS` in `ci.py` — a new entry needs its own compose project, its own host port, and an honest `live_tier_blocked_by` |
| a `build:` `context:` in any compose file | whether `impl/.dockerignore` is still at the context root. An ignore file one directory below the context is read by nothing and fails silently |
| whether a blocked live tier is still blocked | delete the `live_tier_blocked_by` string and run it. That field is a record of a pending decision, not a permanent exemption |
| whether the service applies migrations | the `container` stage's ordering, and whether `compose.ci.yaml` still needs a Postgres port |
| the released-versions table in `spec/README.md` | `freeze`, which reads it **by shape**: three cells with a 40-character sha1 last. Keep that shape and the table can be rewritten around freely; lose it and every release silently stops being checked |
| **where a published document lives** | **five surviving `_version_dir`/`version_dir` functions** — `spec/conformance/conftest.py`, `.ci/bundle.py`, and the three generators. Since 2026-08-19 every one of them returns `spec/openapi/` unconditionally and ignores its `version` argument, which is what the `# noqa: ARG001` on each is recording. They are kept as functions rather than inlined so that a future scheme has one obvious place per tree to change |
| which conformance tests are stack-conditional | whether `container` still needs two passes; today exactly one module is |
| `pyproject.toml`'s `addopts` | the "nothing can spend money" claim above, which rests on it |
| `agent_spec.db.testing`’s resolution order | `unit`'s Docker dependency and what `--fast` actually skips |
| adding a unit suite that binds a real port, writes outside `tmp_path`, or wants a fixed container name | whether `unit` can still run its suites concurrently. Today none does, which is the whole basis for overlapping them — a suite that does needs either a per-suite allocation or `UNIT_MAX_WORKERS = 1` |
| adding a test to `claude-python` that shares state across tests, or making a Postgres test run without the `postgres` marker | `UNIT_XDIST_WORKERS`. `-n` is passed only alongside `-m "not postgres"`, and a shared-state test that escapes that marker gets distributed and flakes rather than failing |
| `conftest.py`'s `postgres_server` scope or its `drop_all`/`create_all` isolation | whether the Postgres tests are still undistributable. If they become worker-safe, `-n` can leave the `--fast` branch — which is what would make the *default* run faster too |
| where an implementation lives, or adding a second | `IMPL` in `ci.py`, `_LINK_LEVELS` in the `links` stage, `_SCANNED` and `_REFERENCE_DOCS` in `references`, and the canonical column of the sha256 table |
| renaming or moving a references file | `_REFERENCE_DOCS` in `ci.py`. Nothing else — that is the point of the indirection, and the file it names is the only document any comment may reach |
| adding a document under `docs/<build>/` | whether it should exist at all. Two do (a runbook and a primer, neither cited by code); a third that code wants to cite is an entry in the references file instead |
| `spec/VERSION` | `agent_service/versions.py`'s `DOCUMENT_VERSION`, which repeats it because a container cannot read that file. `test_api_meta.py` fails if they drift |
| `spec/conformance/pyproject.toml`'s `testpaths` | the `container` and `gates` stages, which pass no path and rely on it |
| adding a no-service test to the conformance suite | nothing — `unit`'s second run already covers it. Adding one that *needs* a service is the case to check: it must request one of `_LIVE_FIXTURES` or it will fail there |
| moving a published `schema/` file again | nothing in `freeze` — `_content_commits` follows renames. But the commit that moves it still cannot pass the hook; use `--no-verify` and run the full check after |
| adding an Alembic revision | nothing — `_alembic_head()` reads the tree. But the new head needs its DDL generated (`dump-schema.py --sql-only`), and the *previous* head stops being exempt the moment the new one lands |
| the format of a revision file's `revision = ` line | `_REVISION_RE` in `ci.py`. It tolerates both quote styles and Alembic's `Union[...]` annotation; a template change that breaks it makes `freeze` raise rather than pass |

---

## What is deliberately not done

- **No CI service and no remote.** Above.
- **The full run is not in the hook.** Minutes in a hook is what gets a hook
  bypassed, and `--no-verify` as a habit costs you the fast half too.
- **No stash-around-the-run in the hook.** See above; it can lose work.
- **The paid tier is not reachable from `ci.py` at all** — not behind a flag, not
  behind an environment variable. It is a command you type.
- **`freeze` does not check `spec/`'s other two bundle files.** The
  contract instrument and the sign-off are prose, have no canonical copy
  elsewhere, and no hash is recorded for them.
