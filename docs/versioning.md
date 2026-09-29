# Versioning and publishing

**Three version streams, one snapshot, and three irreversible acts.** This file
exists because every rule below was learned by getting it wrong once, and
because the cost of a mistake here is asymmetric: an internal number costs
nothing to change and a published one cannot be changed at all.

The three that cannot be taken back, in ascending order of reach: **a release
tag** ([§4](#4-cutting-a-release)), **a published image or Maven artifact**
([§5](#5-publishing-an-image)), and **a push to the public repository**
([§4a](#4a-exporting-to-the-public-repository)). All three need asking; see
[§3](#3-what-needs-permission-and-what-does-not).

It said "two kinds of directory" until 2026-08-21, which had been wrong since
2026-08-19: there are no version directories at all now. `spec/` holds one
version and every released one is a tag.

Written 2026-08-09, after 0.18.0 was frozen mid-iteration by an image
announcement — [§6](#6-the-mistake-that-produced-this-file) is that story.

Companion to [`ci.md`](./ci.md), which is what enforces most of it, and to
[`dev-todo.md`](./dev-todo.md) item 5, which is the release checklist this
generalises.

---

## 1. The three streams, and what each one names

They are independent. Reading one where another is meant publishes a file nobody
will look for.

| Stream | Source of truth | Names | Moves when |
|---|---|---|---|
| **Document** | `spec/VERSION` | `<impl>-<version>.json`, `core-<version>.json`, and `info.version` in every served document | the HTTP surface or a clause changes |
| **Implementation** | each `impl/*/pyproject.toml` | the **image tag**, and `deployment.service.impl.version` | that build changes, for any reason |
| **Schema** | the Alembic head revision | `agent-service-<revision>.sql` | a migration lands |

**`release-<version>` names the DOCUMENT stream and nothing else.** It is the
only stream with a *cut*: an implementation moves by image tag and the schema by
revision, and neither is tagged in git. So a `release-0.19.0` tag sitting beside
an image tagged `0.18.13` is not a contradiction -- they are different streams,
and the tag names the one `spec/VERSION` owns.

**Both numbers were 0.18.0 and that was a coincidence of timing** — the release
that split them moved both at once. They diverged for the first time on
2026-08-09: document `0.19.0-snapshot`, implementations `0.18.1` and `0.0.2`.
Nothing requires them to agree again, and a change that touches only a build
should move only that build's number.

### The image is where the streams meet (user, 2026-08-16)

**Independent streams still have to be paired somewhere, and the pairing is a
property of the IMAGE.** An image is built against one document and one DDL
revision; neither can be derived from the other, so it publishes both:

| Where | What it says | Authority |
|---|---|---|
| image labels — `docker inspect` | `com.npf.agent-service.document-version`, `.schema-revision`, `.impl` | **yes, since 0.19.0** — pinned by the `container` stage's label check, and the entry point now that no command prints these |
| `components.schemas.PrebootSpec` in that build's document | the pre-boot facts, every value `const`-pinned | **yes** — the same constants the code enforces |
| the availability note | image, digest, what moved | the human record |

**Not the tag, and not the OpenAPI document.** A tag can never be corrected once
published, so a spec version inside it becomes a lie the day the document moves.
A published document is frozen by `freeze` and AS-24, so a schema revision inside
it becomes a lie the day a migration lands — and the schema stream moves for
reasons the document knows nothing about. **Both are the same mistake: a moving
fact inside an immutable name.**

**What this buys the consumer.** Agent Harness depends on both artifacts — the
spec jar at test scope, the schema jar executing inside their image — and can now
check an image against them without starting it: `document_version` equals the
spec jar's `index.json` → `spec_version` (**the lowercase spelling**, not the
Maven coordinate, which reads `0.19.0-SNAPSHOT`), and `schema_revision` is one of
the keys in the schema jar's `index.json` → `schema`. That artifact carries every
revision and names no head on purpose, so the image naming its own revision is
what makes the pair checkable at all.

**The schema stopped being named by a build version for a reason worth keeping:**
`agent-service-0.16.0.sql` means nothing once a second implementation is at `0.0.2`.
Three builds cannot each name one shared schema. The revision is the stream that
moves exactly when the schema does.

## 1a. Every implementation ships a guide, and a release without one is not cut

**A condition of every non-snapshot cut** (user, 2026-08-09):
`impl/<build>/docs/<build>-guide.md` exists and is current -- so
`impl/codex-python/docs/codex-python-guide.md`, named for the build rather
than a bare `guide.md`, because these get opened side by side and two tabs
both called `guide` is a small tax paid every time for the version being cut.

It is the document a consumer reads before writing a client: how to run the
build, how to use its OpenAPI document, **what will surprise them**, which
behaviour is measured and which is merely intended, and what remains their
responsibility rather than the service's.

**The reason it is a gate rather than a nicety.** This platform's two builds
differ in ten published ways, and every one of them was discovered by somebody
measuring rather than reading. A consumer handed a frozen document and no guide
has to rediscover the same ten things, and the release process is the only
moment anybody is obliged to write them down.

**Currency is part of the condition.** A guide describing the previous version's
behaviour is worse than none, because it will be believed.

## 2. Snapshots and releases

**`spec/` carries one version and it is the current one** (user, 2026-08-19).
There are no version directories. A version is a `-snapshot` for its whole life
except at one commit -- the one the cut tags -- and every released version is
reachable only through its tag.

| State | Where | Editable | Permission |
|---|---|---|---|
| in flight | `spec/openapi/<impl>-<version>-snapshot.json` | **yes**, freely | none needed |
| cut | the same files, bare, in one commit | no | **ask** |
| released | `release-<version>` | **never** | **ask** |

**Agent Harness may test a snapshot**, so `spec/` is visible to them; it is
simply never frozen. Testing before cutting is how a defect gets found while the
number can still change. **A snapshot handed to them must say it can change under
them**, because it has no tag, no manifest row and no notice obligation.

### What replaced eighteen directories, and why it is stronger

Every version cut before 2026-08-19 lived in `spec/<version>/`, and
`freeze` protected them by walking git history for a content commit after the
version moved on. That was real work defending a weak position: **a directory can
be edited**, and the walk could only ever notice afterwards.

A tag names an immutable commit. The bytes cannot change at all, so there is
nothing to watch -- and the one remaining way to alter a released version is to
**move the tag**, which `spec/README.md` records well enough to catch. That table
is now the whole of what `freeze` guards on the document stream.

**The eighteen are not releases under this process.** `0.19.0` is the first, and
Agent Harness depends on `>= 0.19.0` from now on (user, 2026-08-19). Their
documents are not carried in the working tree, nor in this repository’s history.

## 3. What needs permission, and what does not

**Ask before**: moving `spec/VERSION` to a bare number, **creating or pushing a
`release-<version>` tag**, moving any `pyproject.toml` version, building or
tagging an image, publishing a Maven artifact, writing anything into
`docs/to-agent-harness/`, and **pushing anything to the public repository**
([§4a](#4a-exporting-to-the-public-repository)).

**The public push is the least reversible act in this file.** A tag can at least
be reasoned about; a commit that reaches a public GitHub repository can be
cloned, forked and indexed within minutes, and deleting it afterwards removes it
from exactly one of those places. Building the `public` branch locally needs no
permission — it is inspectable and costs nothing. Pushing it does.

**No permission needed**: creating or changing a `-snapshot` document, and
unagreed work anywhere under `docs/`. (It used to say `spec/draft/`; that
directory went with the rest of the version directories on 2026-08-19, and
`spec/` is now `openapi/`, `database/` and `conformance/` and nothing else.)

**A tag is the most permanent thing in this repository, so it is the most gated.**
An image tag can at least be superseded by a new one; a release tag *is* the
release, and every artifact is built from it. **Never move a release tag and
never delete one.** `freeze` records the commit each tag points at and fails if
one has moved, which is the only remaining way a release can change.

**Telling Agent Harness a snapshot is ready to test is still writing to the
outbox**, so that needs asking — the snapshot itself does not.

**The reason the release side is gated is not ceremony.** Eighteen document
versions were cut under the older process and **none of them is a release under
this one**; Agent Harness depends on `>= 0.19.0` from now on (user, 2026-08-19).
Each of those eighteen cost a directory, a hand-written README, a manifest row
and a hash that nobody read. A version exists because a consumer will adopt it,
not to record that work happened.

## 4. Cutting a release

**THE TAG IS THE FREEZE** (user, 2026-08-19). A release is an immutable commit
named `release-<version>`, and **every release artifact is built from it**: the
spec Maven package, the schema Maven package and the three implementation
images. Nothing is a release because it sits in a directory.

Everything below happens **after** the user says to cut, and in this order. **A
snapshot should have been tested first** — by this side, and by Agent Harness if
they want it — because that is what the snapshot is for.

1. **Rename the four documents in place**, dropping `-snapshot`:
   `spec/<impl>-<version>.json` and `spec/core-<version>.json`. `git mv`,
   so history follows.
2. **Set the version in all four places it is written**: `spec/VERSION`,
   `DOCUMENT_VERSION` in every implementation's `versions.py`, and
   `com.npf.agent-service.document-version` in every implementation's
   `Dockerfile`. **And bump every implementation's own version too** —
   `pyproject.toml` and `IMPLEMENTATION_VERSION` — because the release images are
   built from this commit and an image tag is never reused.

   **`freeze` fails the cut if you forget**, since 2026-08-19: while
   `spec/VERSION` is bare it refuses any implementation version the registry
   already holds as an image. So this is caught at step 7 — before the tag —
   rather than at step 9 by `.ci/images.py`, which is where it was caught the
   first time and is four steps and one irreversible tag too late.

   **This step did not say that until 0.19.0 was cut, and the cut is where it was
   found.** The tag carried the same implementation versions as the snapshot
   images already in the registry, so release images built from it would have had
   to push tags that were taken. `.ci/images.py` refused, which is the guard
   working; the procedure was what was wrong. **0.19.0 set all three
   implementations to `0.19.0`** (user), which is an alignment at one release
   rather than a merging of the streams: a later build-only change still moves an
   implementation number on its own. The label is a hand-written copy, so it moves in the same commit
   or not at all — the `container` stage compares it against the document, but
   only once an image exists, which is too late. The **schema** label moves on
   its own stream and is untouched by a document cut.
3. **Regenerate every document**, one command per implementation. The last one to
   run recomputes `core-<version>.json` over all of them.

   **The first two runs EXIT NON-ZERO with an AS-23 refusal, and that is
   expected** (Agent Harness, 2026-08-19, who hit it rehearsing this). Until every
   document has been regenerated the set is half bare and half snapshot, so
   `.info.version` and `PrebootSpec.document_version.const` differ across it and
   drop out of the intersection. The guard is right to refuse a shrinking core; it
   is comparing a half-migrated set.

   ```
   REFUSING to shrink the core: 2 leaf/leaves would be removed, ...
     .info.version
     .components.schemas.PrebootSpec.properties.document_version.const
   ```

   **Those two leaves and no others is the signature of the expected case.** It
   clears on the third run, when all three agree. **Anything else in that list is
   a real AS-23 breaking change** and needs a stated reason and a notice — so read
   the list rather than the exit code.
4. **The core-shrinkage check now applies.** It is skipped for a `-snapshot`,
   deliberately: a new implementation joining *should* narrow the intersection.
   At a cut a lost leaf is a **breaking change under AS-23** and needs a stated
   reason and a notice.
5. **Write the release notes into `spec/README.md`.** A migration note, not an
   essay: what changed, what breaks, what the consumer does.
6. **Add the manifest row** — version, tag, and the commit the tag will name.
   The commit is not known until step 8, so this row is completed there.
7. **Full CI green.** The commit carrying steps 1–5 cannot pass the pre-commit
   hook — the `git mv` is uncommitted, so `--follow` cannot cross it — so commit
   with `--no-verify` and run the full check immediately after. **This run is the
   only thing that checks the cut.**
8. **Tag it**, annotated, and fill in the manifest row with the commit it names:

   ```bash
   git tag -a release-<version> -m "..."
   git rev-parse release-<version>^{}     # -> the manifest row
   ```

   Then commit the completed row and **push the tag**. A tag that exists only
   locally is not a release.
9. **Build every artifact from the tag**, from a clean checkout of it rather than
   from the working tree — `git worktree add temp/cut release-<version>` is the
   cheapest way to be sure. §5 is the image half; the two Maven packages are the
   same rule.
10. **Bump main to the next snapshot**, immediately and in its own commit:
    `spec/VERSION`, the three `DOCUMENT_VERSION`s, the three labels, and the four
    filenames gain `-snapshot` again. **Main is always a `-snapshot`** — the bare
    state belongs to exactly one commit, the one the tag names, and `freeze`
    fails a bare version that is not tagged.

    **The next number is a decision, not a formula.** The next minor is the
    default; a breaking change or a patch is the user's call.

## 4a. Exporting to the public repository

**This repository is published at `github.com/chiliu02/agent-service`, and it is
NOT this history** (user, 2026-08-21). The public repository is built from the
orphan **`public`** branch, which carries **two commits**. **Never push `main`
there.**

| | `main` — here and on `gitea` | `public` → GitHub `main` |
|---|---|---|
| history | full | orphan, two commits |
| `docs/to-agent-harness/` | **tracked** | absent |
| `spec/README.md` manifest | `979450d…` | `1666f74…` |
| `release-0.19.0` resolves to | `979450d` | `1666f74` |

**The outbox is tracked here on purpose and removed by the export.** It is the
record of how this specification was negotiated, and this is where that record
lives; what keeps it out of a public tree is that the threads carry the
*consumer's* estate — registry addresses, a Maven host, compose paths on their
machines. Gitignoring it here was tried for one afternoon and reverted: a new
thread would silently never be committed, and the record would stop growing with
nobody noticing. **The removal is a step in publishing, not a property of this
tree.**

### Two tags with one name, and both are correct

`release-0.19.0` resolves to a different commit in each repository, and **this is
not a defect to be repaired.** `freeze` reads the manifest row from the working
tree and resolves the tag in whatever repository it is running in, so each
history names the commit it actually contains, and the check passes on both.

**What the tag guarantees is unchanged, and it was verified rather than
asserted**: `spec/` is byte-identical at both — `git diff` empty across the
directory, plus a per-file sha256 comparison of the four documents and
`VERSION`. That identity is the entire justification for the arrangement. What
differs at the public commit is outside `spec/`: no outbox, no `.mcp.json`, host
paths parameterised, `LICENSE` and `NOTICE` added.

**Artifacts published before 2026-08-21 were built from the original commit**,
which the public repository does not contain. A consumer verifying provenance
against the public tag finds the same `spec/` under a different hash. Say so if
it ever comes up; do not move either tag to make them agree.

### Routine update — new work on `main`, no new release

Commit 1 does not move. Rebuild commit 2 only:

```bash
git checkout public
git read-tree -u --reset main          # commit 2's tree becomes main's
git rm -r --cached docs/to-agent-harness
# re-add the outbox line to .gitignore on THIS branch only
# re-set the manifest row in spec/README.md to commit 1's hash  <-- SEE BELOW
git commit --amend                     # keep it at two commits
git push --force-with-lease github public:main
```

**`read-tree --reset` reverts everything, including anything that exists only on
this branch** — which is the whole point of it, and the trap. There is **exactly
one** such thing by design, and it must be re-applied every single time:

| Re-apply after every `read-tree` | Why it cannot live on `main` |
|---|---|
| **the whole released-versions block in `spec/README.md`** — the `release-<version>` row **and** the paragraph under it explaining that the tag names this history's root | the row names *this* history's commit and `main`'s correctly names a different one; the paragraph says "its commit is the root of this history", which is true there and false here |

**It is the block, not the row.** The hash and the note that explains it are one
edit — the second export re-applied the hash, read the diff, and caught the
paragraph being dropped. A hash with no explanation is worse than either half:
it is the exact thing a reader would otherwise report as a defect.

**Keep that list at one entry.** Anything else that turns out to differ belongs
on `main` instead, and the fix is to put it there rather than to lengthen this
table. That is not hypothetical: the first routine export silently reverted the
GitHub issue-template URLs, which had been edited on `public` alone and should
have been on `main` from the start. **A regression here is invisible** — the
export still builds, the stages still pass, and the wrong file is published.

**So diff the export against its predecessor before amending**, and read every
non-outbox path in it:

```bash
git diff --cached --name-status | grep -v to-agent-harness
```

Every line should be a change you made on `main` and intended to publish. A
`spec/README.md` in that list is expected; anything you do not recognise is the
trap above.

**`--force-with-lease`, never a bare `--force`.** Amending rewrites the tip, so
the push is non-fast-forward by construction; the lease is what stops it
clobbering something pushed from elsewhere.

### After a cut — rebuild both commits

1. `git checkout --orphan public <release-tag>` — commit 1 is the release tree.
2. Remove `docs/to-agent-harness/` and `.mcp.json` from the index, apply the
   host-path scrubs, add `LICENSE` and `NOTICE`. **Verify `spec/` still matches
   the tag byte for byte** before committing — `git diff --stat <tag> -- spec/`
   must be empty. Commit, then tag it locally as `public-release-<version>`.
3. `git read-tree -u --reset main` for commit 2, set the manifest row in
   `spec/README.md` to commit 1's **new** hash, commit.
4. **Verify in a throwaway clone**, and this step is not optional — see below.
5. Push:

   ```bash
   git push github public:main
   git push github public-release-<v>:refs/tags/release-<v>
   ```

   Git renames the tag on push, which is what keeps the local
   `release-<v>` — pointing at this history's own commit — intact.

### `freeze` cannot pass on `public` in this working tree

The manifest on that branch names the public commit while the local
`release-<version>` tag legitimately points at this history's. **That is the
arrangement working, not a failure**, so verify the export the only way that
means anything — a clone with only that branch, with the tag created under its
real name:

```bash
git clone --branch public --single-branch . /tmp/pubclone
cd /tmp/pubclone
git tag -d release-<v>; git tag -a release-<v> -m "<v>" <commit-1-sha>
uv run --no-project python .ci/ci.py            # all six stages
```

That is exactly what a consumer and the GitHub workflow see. Run the **full**
runner, not `--fast`: the container and gates stages are the half that proves the
images still build from the exported tree.

### Two gotchas that cost time

**`git checkout --orphan <tag>` writes the tag's OLD directory layout** into the
working tree alongside the current one. The outbox was reorganised into
`0.19.0/` after `release-0.19.0`, so this left 68 stale duplicates at the outbox
root — invisible to a file count, which looked plausible. **Diff the on-disk
paths against `git ls-tree main`**, not the totals, and delete only what is
absent from `main` and recoverable from the tag.

**There is no SSH key for GitHub on this host** — the only key is
`harness_e5470`, for gitea. The `github` remote is HTTPS and authenticates
through Git Credential Manager as `chiliu02`.

## 5. Publishing an image

**Built from the release tag, from a clean checkout of it** (user, 2026-08-19) --
not from the working tree, and not from main. An image built from a dirty tree
claims to be a release and is not one, and nothing in its labels would say so.

```bash
git worktree add temp/cut release-<version>      # INSIDE the repository
uv run --no-project python .ci/images.py --push  # run from temp/cut
```

**`temp/cut` and never `../cut`.** A sibling directory is outside
`agent-service/`, and the boundary rule in `CLAUDE.md` does not carve out an
exception for a worktree of this same repository. `temp/` is gitignored, so the
checkout leaves no trace in `git status` either.

**This is what pairs the streams.** An image already publishes the document
version and the schema revision it was built against; building it from the tag is
what makes those claims checkable rather than asserted -- the same bytes, by
construction.


**`.ci/images.py` does all four steps and is the thing to run** (user,
2026-08-19). Every step below was a shell line somebody retyped, and the one
actually forgotten was the newest: removing the push alias afterwards. The script
untags in a `finally`, so a push that fails does not leave one behind either, and
it **refuses to rebuild a version the registry already holds** — a rebuild after a
push moves the tag at the local end while the registry still serves the old
image, which was measured the day this was written.

```bash
uv run --no-project python .ci/images.py            # build + verify, free
uv run --no-project python .ci/images.py --push     # ... and publish. ASK FIRST
```

**An image is the outward-facing half and it is the user's to authorise.** In-repo
work being green is not a release.

1. **Build and tag `<image>:<implementation version>`.** Never `latest` — on this
   host `agent-service:latest` is a TypeScript port at `0.0.0` that boots and
   serves with no credential where these exit 3.
2. **Verify against the tag**, never against a CI image that happens to share a
   commit:
   - the **labels** resolve to a published document, and its `PrebootSpec`
     matches what the container reports. There is no `agent-service-spec`
     command to run any more -- it was removed in 0.19.0, and step 2 asked for
     its output until 2026-08-19
   - the credential gate exits **3**
   - the boot-gate conformance tier passes
   - the full conformance suite over HTTP passes, AS-24 included
3. **Push it to the local registry** as
   `host.docker.internal:5000/<image>:<version>` (see below), **and untag the
   push alias afterwards** (user, 2026-08-19):

   ```bash
   docker tag  <image>:<version> host.docker.internal:5000/<image>:<version>
   docker push host.docker.internal:5000/<image>:<version>
   docker rmi  host.docker.internal:5000/<image>:<version>    # the alias only
   ```

   **The prefix is an address, not part of the image's identity**, which is the
   whole of §3 of the note this repository already sent the consumer: the
   registry address belongs to the reader. A push needs the hostname *inside* the
   tag because there is no `docker push --to`, and once the push has happened the
   alias has done its job.

   **`docker rmi` on the alias removes the NAME and not the image**, because the
   bare tag still references it, and the copy in the registry is a separate
   object that is not touched. Verify both if unsure: `docker inspect` still
   resolves the bare tag, and the registry answers `200` for the manifest.

   **Left behind, they read as three images per build** in any tool that lists by
   tag, which is what they cost.
4. **Write the availability note** into `docs/to-agent-harness/`, naming the image
   **bare**, and carrying the agent-version row below.

**THE NOTE NAMES THE BUNDLED AGENT AND WHETHER IT MOVED** (Agent Harness,
2026-08-16). A row per build — `claude-agent-sdk`, `openai-codex`, `gemini-cli` —
with the version and a yes/no against the previous note. Their gateway counts
tokens by reading the model vendor's response as it passes, which is a wire this
specification does not describe and cannot: it is the vendor's, on a request our
service never makes. So the shape can move without anything here changing, and the
way they would otherwise find out is a build silently recording zeros — which is
how `gemini-python` was billed as free until 2026-08-14.

**Read it out of the built image, never off the pin.** Two of the three are floors
rather than pins, so a rebuild moves them with nothing in the tree changing:
`openai-codex>=0.1.0` resolved to **0.144.4** in `codex-python:0.0.18`, which no
diff of this repository would have told anyone. Only the image knows.
`/v1/deployment` already publishes the same two values as `sdk.name` and
`sdk.version`, so the note and a running container agree by construction.

**What is committed to is the version delta, not the wire.** Whether the vendor
changed a field name is a thing we often would not know; whether the agent moved is
a thing we can always check, and it is what sends either side looking. When we do
know the shape moved, the note says so in a sentence.

**ANNOUNCE THE BARE `<image>:<version>`, NEVER A REGISTRY-PREFIXED ONE** (Agent
Harness, 2026-08-15). A Docker reference contains its registry address, so
`host.docker.internal:5000/<image>:<version>` is not a longer spelling of the
image — it is a name only this laptop can resolve, and the agent containers run on
a Linux host that reaches the same registry by a different address. The registry
is the reader's coordinate and the reader is the only one who knows it; the
announcement carries the name and the digest, and §5's address table stays where a
reader can find it. The prefix belongs in the push command above and nowhere else.
Harness composes its own hub address onto a bare repository and **refuses** a
prefixed one, so a prefixed announcement is a line their side cannot accept as
written.

**A tag is never moved once published.** Two different images answering to one tag
is unanswerable from either side, which is the whole reason the rule exists. Every
fix takes the next implementation version, which is why twenty tags across the
three repositories carry twenty distinct digests.

### The registry is `host.docker.internal:5000` (user, 2026-08-13)

**One registry, three names, and only one of them works from both sides.** It is
the `agent-harness-registry` container — `registry:3.1`, from the
`agent-harness-infra` compose project, published on host port 5000, no auth.

| Name | Resolves from | Use it |
|---|---|---|
| `host.docker.internal:5000` | host **and** containers | **yes — this is the one** |
| `localhost:5000` | the host only | no |
| `registry:5000`, `agent-harness-registry:5000` | inside `agent-harness-infra_default` only | only from a compose service |

**`localhost` inside a container is the container**, which is why it is the wrong
default even though it works when you type it on the host. The consumers of these
images are compose services, so the name has to survive the trip into a container.
Measured 2026-08-13: `host.docker.internal:5000/v2/` answers `200` from the host,
and from a container on `agent-harness-infra_default` it resolves to the Docker
Desktop host gateway `192.168.65.254` and answers `200`.

**No daemon change is needed and that is not luck** — the Docker Desktop daemon
already carries `host.docker.internal:5000` in its insecure-registry list, so a
plain-HTTP push does not fail the HTTPS handshake. On a host without that entry
the push fails with *"server gave HTTP response to HTTPS client"*, and the fix is
the daemon's `insecure-registries`, not a change here.

**Verify a push by digest, never by the tag appearing.** The pushed digest must
equal the local image id:

```bash
docker tag <image>:<v> host.docker.internal:5000/<image>:<v>
docker push host.docker.internal:5000/<image>:<v>
curl http://host.docker.internal:5000/v2/<image>/tags/list
```

**Pushing is not publishing, and the permission rule is unchanged.** Building or
tagging an image still needs the user, and a delivered image still freezes its
document (§6). A push only puts an already-authorised image where the consumer
can reach it.

### The Maven repository is `host.docker.internal:8081` (user, 2026-08-13)

**Sonatype Nexus 3.70.5 OSS**, the `agent-harness-nexus` container from the same
`agent-harness-infra` compose project, on host port 8081. It takes the spec and
schema bundles that `.ci/bundle.py` builds.

| Repository | Takes |
|---|---|
| `…/repository/maven-releases` | a bare version — `agent-service-database:1.3.0` |
| `…/repository/maven-snapshots` | `-SNAPSHOT` — `agent-service-openapi:0.19.0-SNAPSHOT` |
| `…/repository/maven-public` | the group to **read** through; never a deploy target |

`maven-public` does front the two hosted repos — a deployed snapshot resolves
through it — even though the REST repository endpoint reports no members. **Do
not read that endpoint as the answer**; resolve a known path instead.

Same host-name rule as the registry: `agent-harness-nexus:8081` from a service on
`agent-harness-infra_default`, `host.docker.internal:8081` from the host.

**ANONYMOUS ACCESS IS DISABLED**, so *every* read needs a credential, not just a
deploy. `/service/rest/v1/security/anonymous` reports `"enabled": false`. The
repository browse page answers `200` without one, which is the trap: it is the
HTML index and not repository content, and a path under it answers `401`. **A
consumer given only a coordinate cannot resolve it** — they need a credential or
anonymous access has to be turned on, and that is the user's call.

**Deploying is `--deploy`, and `--release` is the gate.** `.ci/bundle.py` builds
with `mvn package`, `--install` reaches `~/.m2`, and `--deploy` reaches Nexus:

```bash
uv run --no-project python .ci/bundle.py --deploy --settings <settings.xml>
```

`-SNAPSHOT` publishes freely because Maven treats it as replaceable. **A bare
version is withheld unless `--release` is also passed**, prints `NOT PUBLISHING`,
and still builds its jar — so `--deploy` alone can never publish an immutable
coordinate. The two artifacts are gated independently.

**`--schema-snapshot` builds the schema as `1.n.0-SNAPSHOT`** (user,
2026-08-13), which is how it is published today. It appends a suffix and changes
nothing else: **the version is still the revision count and still does not track
`spec/VERSION`.** That separation is Agent Harness's own ask — bundled, a
document-only fix would move a dependency carrying DDL that executes inside their
image — and a suffix does not weaken it. What it buys is that a bare `1.n.0`,
which can never be re-cut, is written only when it is meant to be permanent.

The `server` ids a `settings.xml` must match are `agent-service-nexus-releases`
and `agent-service-nexus-snapshots`, and they are in the generated poms.
`agent-service-deployer` is the account: add and edit on the two hosted repos,
read on `maven-public` and `maven-central`, **no delete and no admin** — verified
by confirming it is refused the user list.

**Publishing an artifact is publishing.** It is the user's to authorise, exactly
like an image, and for the same reason: a consumer can adopt it and a released
coordinate is never re-cut.

**`agent-service-database:1.3.0` IS CUT** (user, 2026-08-15) — the first bare
coordinate this repository has published, on Agent Harness's request after their
2026-08-13 run created a schema from the artifact and booted all three builds
against it. Jar sha1 `b5152b122b2c531ab4dc019f58aa48e15ab199a1`, resolving from
`maven-releases` and through `maven-public`. **Never rebuild it**: the DDL in it is
byte-identical to the `1.3.0-20260812.155645-1` snapshot they exercised, and Nexus
refuses a redeploy of the coordinate anyway. Harness moves off `1.3.0-SNAPSHOT` and
drops `.changing()` on the strength of it. The next DDL revision is `1.4.0`. `agent-service-openapi`
stays `0.19.0-SNAPSHOT`.

**`studio-registry:5000` is GONE — never push there and never cite it again**
(user, 2026-08-13). That registry no longer exists. It is confirmed dead from this
host too: the `agent-harness-registry` container's aliases on
`agent-harness-infra_default` are `agent-harness-registry` and `registry`, and
`studio-registry` is not among them.

**Four delivered availability notes still tell Agent Harness to pull from it**, and
they are **not** rewritten — `codex-python-0.0.10-available.md` and its `.2`,
`images-0.19.0-snapshot-final.md`, and `gemini-python-0.0.1-available.md`. They are
published, so editing them would falsify a pull the consumer already performed or
failed to perform; the rule directly above about the old `agent-service-python`
name applies here for the same reason. **The correction goes in a new thread, not
into the old notes.** That thread is owed: every image the consumer has been
pointed at now sits behind a name that resolves nowhere.

**The Claude build's image is `agent-service-claude-python`** (user,
2026-08-10), matching `agent-service-codex-python`. Tag every new image under
that name.

**`agent-service-python` is the old name and is an alias, not a second image.**
It predates there being two Python builds, and three availability notes already
in Studio's hands tell them to pull it — 0.10.0, 0.11.0, 0.13.0, 0.18.0 and
0.18.4 exist under it. Those notes are published and stay true, so the old tags
stay on the daemon and are never moved; `0.18.4` now answers to both names and
they are the same image id. **The rename is forward-looking only** — do not
rewrite a delivered note to use the new name, because it would describe a pull
Studio did not perform.

## 6. The mistake that produced this file

**0.18.0 was cut, undelivered, and therefore editable — the normal path.** The
in-flight document is exempt from `freeze` precisely so it can be edited right up
until release.

Then, in one session, an image was built and tagged `agent-service-python:0.18.0`
and an availability note was published telling Studio to pull it and asserting
AS-24 held against `openapi-0.18.0.json`. **That announcement froze the document**,
and not through any rule about documents:

> Change the document now and the announced image serves something other than what
> the document says — AS-24 broken for the exact image the consumer was told to
> use. The only repair is rebuilding and moving the tag, which is forbidden.

**A delivered image pins the document as hard as AS-24 does.** The versioning rule
was written about documents and did not know that. Four owed fields then needed a
number, and it took a measurement to find that three of them touched no schema at
all and needed only an implementation bump.

**Two lessons, both encoded above.** Publish the image and the document as one
decision, since the first freezes the second. And when a change looks like it needs
a document version, check whether it actually touches the document — `limits` is a
free-form map, and the pre-boot spec is not in the document at all.

## 7. What the clauses require of these artifacts

| Clause | Requirement |
|---|---|
| **AS-23** | Removing anything published needs a notice. Adding does not |
| **AS-24** | A running service serves **exactly** the document published for its version and its implementation. Byte equality, never containment — it is what lets the document tier prove nine clauses with no service running |
| **AS-30** | An implementation with persistence conforms to the published DDL and does not migrate |
| **AS-31** | Every implementation's document is structurally identical to `core-<version>.json`. Prose may differ; status codes and headers may be **added** |
| **AS-32** | An extension a client must act on is published on `/v1/deployment`. Prose is the only difference a client may be required to ignore |
| **AS-33** | A build declares every status its own error table can produce on that route. **Absence means unreachable** |

**AS-31 through AS-33 are proposed and unagreed** as of 2026-08-09 —
`spec/draft/as-24-core-and-extension.md` is the argument, and they need
a release to become real.
