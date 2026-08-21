# impl/claude-python — working notes for Claude

The Claude Agent SDK implementation: an HTTP wrapper over
`claude-agent-sdk`, in Python, shipped as a container. **There is no `README.md`
for this build since 2026-08-11** -- it mixed three audiences and rotted where the
tree moved under it. `docs/claude-python-operations.md` runs and deploys it,
`docs/claude-python-guide.md` is what a client author reads, and this file is only
the things that are easy to get wrong and are not visible from the tree.

**The platform's rules are one level up.** The boundary rule ("never write
outside this directory"), the Agent Studio channel, thread naming and the
escalation rule are in [`../../CLAUDE.md`](../../CLAUDE.md), and they outrank
anything here. So does its warning about the CI runner: `ci.py` lives at the
platform root, and `docs/ci.md` there is its reference.

**Paths below are relative to this directory** unless they start with `../`.
**`docs/` means this directory's again** (user, 2026-08-10): it holds
`docs/claude-python-guide.md`, the front door a consumer reads first, and
`docs/claude-python-references.md`, the only document this build's code may
cite. Both moved out to the platform's `docs/claude-python/` on 2026-08-09 and
came back; that directory no longer exists. **A comment cites a `CP-nnn` ID and
never a path**, so this paragraph is background rather than something a comment
depends on. The platform's own docs — `ci.md`,
`plans.md`, `dev-todo.md`, `open-questions.md`, `security-posture.md` — are at
`../../docs/`, and the contract and the outbox are at `../../spec/` and
`../../docs/to-agent-harness/`.

**The same convention holds in the code**, and it is what made Plan 8 step 1
cheap: 79 of the 83 surviving path citations in comments cite a document that
moved *with* the implementation, so they never changed. The four that cite a
platform document gained a `../../`.

**Three did not, and the rule behind that one is worth knowing: a path that
reaches the published OpenAPI document cannot be rewritten at all.** Pydantic
publishes a model's docstring as its schema `description`, so `Sdk`'s docstring
and the `require_credentials` field description in `schemas.py` are *inside*
`../../spec/openapi/<impl>-<version>.json` — already delivered, already
hashed in `../../spec/README.md`, and frozen by AS-24. Editing one changes
`/openapi.json`, which `tests/test_api_meta.py` and the conformance tier both
catch immediately. It is also the right answer on its own terms: their reader is
outside the tree, where repo-root-relative is what they can act on. The same
goes for the no-token log warning `api.py` emits.

## Read before running anything

- **`uv run pytest -m live` spends real money** — ~$0.09 for the one-shot run plus
  ~$0.035 for the two-turn session, against the real API. `pyproject.toml` sets
  `addopts = "-m 'not live'"` so the default run is free; do not add `-m live`
  to "be thorough", and do not remove that marker filter. Ask first.
- **The service refuses to boot without credentials** and exits 3. That is
  deliberate. If you need `/docs`, `/openapi.json` or `/v1/capabilities` without a
  key, set `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` rather than working around it.
- **The agent's `Bash` tool is unconfined**, and there is no auth on the API. The
  operations document's opening warning is measured, not cautious boilerplate —
  read it before changing anything about permissions, mounts, or the bind address.

## Commands

```bash
uv sync                                  # uv, not pip/venv
uv run pytest                            # no API calls, no cost; STARTS A CONTAINER
uv run pytest -m "not postgres"          # ... and no container either
uv run pytest -m "not postgres" -n 4     # ... and ~14s instead of ~33s. SEE BELOW
uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8000
                                         # needs AGENT_SERVICE_REQUIRE_MOUNTS=false
                                         # (it is in .env.example); otherwise exits 3
docker compose up -d --build --wait      # needs WORKSPACE_HOST_PATH + REFERENCE_HOST_PATH in .env

# Reuse a server you already have instead of letting the harness start one:
docker run -d --name agentsvc-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=agent \
  -p 55433:5432 postgres:17-alpine
AGENT_SERVICE_TEST_DATABASE_URL=postgresql://postgres:dev@127.0.0.1:55433/agent uv run pytest

docker compose --profile persistence up -d postgres   # for the SERVICE, not the tests
```

**The CI is not run from here.** It is one runner for the whole platform, at the
platform root:

```bash
cd ../..                                 # or wherever the platform root is
uv run --no-project python .ci/ci.py         # ALL of it: freeze, links, unit, container, gates
uv run --no-project python .ci/ci.py --fast  # ... freeze + links + unit only, no Docker at all
```

It runs every `uv`/`docker` command *with this directory as the working
directory*, so what it executes is what the block above executes.

**`-n` NEVER GOES IN `addopts`, and never without `-m "not postgres"`.**
`pytest-xdist` is a dev dependency here since 2026-08-17, and it is deliberately
not switched on by default. The Postgres tests share **one server and one
schema** and isolate themselves with a `drop_all`/`create_all` per test, so
distributing them across worker processes does not fail cleanly — it flakes.
`conftest.py`'s `postgres_server` fixture says so where the fixture is.
`ci.py` passes `-n 4` on exactly one invocation: the `--fast` branch, which has
just deselected them.

**Why it is here at all**: this suite was the long pole of the platform's `unit`
stage, which runs all five suites concurrently, so the stage could never be
faster than this one. Measured alone — 33.0 s at `-n 1`, 14.3 s at 4, 10.5 s at
8. **4 rather than 8 on purpose**: the three large suites now finish within 6 s
of each other, so extra workers here buy the stage nothing and only make this
suite's timing assertions likelier to flake — a dozen of them are upper bounds,
the tightest `elapsed < 0.05`. `../../docs/ci.md` has the whole argument,
including why the Codex build gets `-n` unconditionally and this one does not.

**`uv run pytest` starts a Postgres container** when it can, and this is recent —
the Postgres-backed tests used to skip unless `AGENT_SERVICE_TEST_DATABASE_URL`
was set, so a machine with Docker and no variable exported silently skipped seven
files' worth of coverage and still reported green. `tests/dbharness.py` is the
whole story: env var first, then testcontainers, then skip. They are free either
way — unlike `live`, which is marker-deselected because it costs money.

**Compose's persistence Postgres is not reachable from the tests.** It publishes
no host port, on purpose; a `127.0.0.1` URL pointing at it cannot connect. That
command is for running the *service* against a database. (CLAUDE.md itself
advertised the impossible combination until 2026-07-30.)

`docker compose up -d` without `--wait` reports success even when the container
exits 3; see CP-086.

## House rule: measured, not assumed

This codebase's documentation convention is that every non-obvious claim is either
**measured by a live probe** or **read from the installed SDK source**. Claims that
were once asserted and later disproved are kept as explicit corrections, because
the fact that they were wrong is load-bearing.

So: do not write a confident claim about SDK behaviour into a comment, a document
or a probe write-up unless you verified it. If you cannot verify it, say so in the text. Probes
go in `spike/` and are written up as numbered cases (`S1`–`S6`, `L1`–`L7`, `M1`)
in the references file, each with its own `CP-nnn`.

## Where things are

- `docs/claude-python-guide.md` — **the front door for anyone writing a client**:
  the OpenAPI document, the session lifecycle, what will surprise them, what is
  measured versus intended, and what stays their responsibility. **A condition of
  every non-snapshot release** (user, 2026-08-09) -- a build that ships without it
  is a build whose consumer has to read its source.
- `docs/claude-python-operations.md` — **how to RUN it**: the security warning,
  mounts, compose and `docker run`, the boot gates, limits, persistence and the
  web console. This was `README.md` until 2026-08-11.
- `src/agent_service/` — the service. **A comment cites a `CP-nnn` ID and never
  a path** (user, 2026-08-10). **Change the code, update the entry.**
- `docs/claude-python-references.md` — **the one document
  code may cite.** 143 entries, each with a permanent ID: reasoning per source
  location, every probe result, the container, the design and persistence, all
  merged there on 2026-08-10 from five documents that no longer exist. It links
  to nothing, and no comment reaches past it; `ci.py`'s `references` stage fails
  a build that breaks either half.
  - CP-002 is "Recheck on SDK upgrade — the index"; **CP-006 is "Guards that are
    deliberately not test-killable" and is the one to read before deleting
    anything that looks uncovered** — three guards are intentionally unpinnable.
- `../../docs/deploy-remote.md`, and `learning-async-python.md` —
  deliberately *not* merged: a runbook and a primer, neither of them evidence,
  and no code cites either. **The primer is named rather than pathed** because it
  moved into the platform's `docs/conversations/` on 2026-08-13, which is
  untracked — it is on its author's disk and in no clone, so a path to it would
  resolve for one reader and dead-end for every other.
- `spike/` — throwaway probe scripts, committed on purpose as evidence.

**One level up**, because they are the platform's and a second implementation
would share them rather than copy them:

- `../../docs/ci.md` — what `../../ci.py` runs, every setting it uses, and the
  "Recheck when these change" index. **Read before touching CI, the compose
  overlay, or the pre-commit hook.**
- `../../docs/plans.md` — what shipped (plans 1–4, summarised) and what is
  designed and unbuilt (6, verbatim). Consolidated from eight `plan-*.md` files
  on 2026-07-31; the originals are in `git log`. **Plans 5 (multi-workspace
  router) and 7 (Projects) were removed as out of scope on 2026-08-06** — do not
  reintroduce them; `git show b7be5fc:docs/plans.md` has the text.
- `../../docs/dev-todo.md` — everything outstanding, in one place. **Its "Do not
  'fix' these" section is the one to read first**: eleven behaviours that look
  like defects and are decisions.
- `../../docs/open-questions.md`, `../../docs/security-posture.md`,
  `../../docs/plan-8-design.md`.

## Directories that look alike and are not

- **`workspace/`** — the agent sandbox root. Load-bearing: `config.py` defaults
  `workspace_dir` to `./workspace` and the container mounts it at `/workspace`.
  Not scratch space. `.gitignore` uses `workspace/*` + `!workspace/.gitkeep`
  deliberately — the directory form `workspace/` would stop git descending far
  enough for the negation to fire.
- **`temp/`** — scratch. **Every** temporary, probe, or repro directory goes under
  `temp/<name>/`, never at this directory's own root. Ignored the same way.
  (Root-level scratch dirs were cleaned up on 2026-07-29 after eleven empty ones
  accumulated.) The platform root has a `temp/` of its own, which is where
  `ci.py` writes its generated env files; they are separate on purpose.

## Gotchas

- **`../../ci.py` is the CI. There is no CI service and no git remote**, by
  decision (2026-08-06) — **`../../docs/ci.md` is the reference**; read it before
  changing any of this. Two parts of it
  are load-bearing and look like they could be simplified: the `container` stage
  runs the conformance suite **twice**, because only
  `test_contract_persistence.py` is stack-conditional and one of the three tests
  it skips without a database is a *negative control* for the two-kinds-of-404
  discriminator; and it applies migrations itself, before starting the service,
  because nothing in the service does — an unmigrated database is the exact
  state the conformance fixture skips on, so getting that wrong is a green run
  that tested nothing. It cannot spend money and the container it boots has no
  `ANTHROPIC_API_KEY` at all.
- **There is a pre-commit hook, installed by `core.hooksPath .ci/hooks`**,
  and both it and that path are the **platform's**: the tracked file is
  `../../.ci/hooks/pre-commit` and it runs
  `uv run --no-project python .ci/ci.py --fast --fail-fast` (~28 s to pass, ~1 s to
  reject; it was 93 s until `unit` gained concurrency and this suite and the
  Codex one gained xdist, all on 2026-08-17). A fresh clone needs that one `git config` command; git never installs
  hooks itself. `--no-verify` skips it. It tests the **working tree, not the
  index**, so an unstaged edit to a published `schema/` file blocks an
  otherwise-fine commit. `../../.gitattributes` exists solely to keep the hook LF
  — a CRLF checkout makes every hook die with `/bin/sh^M: bad interpreter` — and
  is deliberately scoped to `.ci/hooks/*` rather than `* text=auto`, which
  would renormalise the frozen files in `schema/`.
- **`compose.ci.yaml` is an overlay and is never used alone.** It exists so
  `compose.yaml` stays untouched — that file is what the security comments
  describe and what `tests/test_config.py` reads. It publishes a host port for
  Postgres, which `compose.yaml` deliberately does not; that is for the
  out-of-band migration and is scoped to a stack destroyed minutes later.
- **`schema/` holds the SQL only; the OpenAPI documents are the contract's.**
  Plan 8 step 4 moved them under `../../spec/`, because a second
  implementation in another language has to satisfy the same document and would
  not share this database. **They live one directory per version** —
  `../../spec/openapi/<impl>-<version>.json` — and there is no
  canonical `openapi/` directory, whatever `scripts/dump-schema.py`'s own
  docstring still says. `scripts/dump-schema.py` writes to both places in one
  run; `--out-dir` overrides both.
- **Both directories are committed and frozen.** Every file except the current
  `pyproject.toml` version must have exactly one commit that changed it and must
  match what git has — that is AS-24, and `../../ci.py`'s `freeze` stage is what
  enforces it, following renames so a move is not read as a republication.
  **`schema/` no longer exists in this directory at all** — Plan 9 moved the DDL
  to `../../spec/schema/`, so the old README's argument about whether to
  gitignore it is history. The same stage
  also checks `../../spec/`'s delivery copies against the sha256 table
  in that bundle's README — a reversal of a documented decision, narrow because
  `ci.py` is not a test. Its `spike-findings.md` arm was removed on 2026-08-07;
  see that README for why.
- **Pinned SDK: `claude-agent-sdk==0.2.128`.** Not a routine bump — the measured
  facts in the references file are tied to this version, and CP-002 is the
  "Recheck on SDK upgrade" index for exactly this.
- **TWO versions since 0.12.0, and they are not the same number.** Read
  `src/agent_service/versions.py` before touching either.
  `DOCUMENT_VERSION` is the **contract's** — it is what `create_app()` passes to
  FastAPI as `version=`, what `/openapi.json` advertises as `info.version`, what
  names `../../spec/openapi/<impl>-<version>.json`, and it must equal
  `../../spec/VERSION`. `IMPLEMENTATION_VERSION` is **this build's**, must
  equal `pyproject.toml`'s `version`, names `schema/agent-service-<revision>.sql` and
  the image tag, and is published at `capabilities.impl.version`. Both
  are `0.12.0` today because that is the release that split them; **nothing
  requires them to agree again**. `tests/test_api_meta.py` pins all four edges.
- **`.env` is found by walking up from `main.py`'s directory**, not the process
  cwd — so it works for an editable checkout and does *not* work for an installed
  package or a container, where real environment variables are required.
- **`model_usage` is cumulative for the connection; `usage` is per-turn.** Summing
  `model_usage` across turns multiplies the real figure by roughly the turn count.
- **Persistence is optional and off by default**, and every task keeps that path
  green. With no `AGENT_SERVICE_DATABASE_URL`, `agent_service.db` must never be
  imported — a fresh-interpreter test pins it, because an in-process
  `sys.modules` check passes regardless once other tests have imported it.
- **Two write paths with OPPOSITE failure contracts, and they look alike.**
  `RunRecorder` (A.1) must **never raise** — it runs inside `_send_impl`'s drain,
  where an exception mislabels a turn. `SessionStore.append` (A.2) **must raise**
  — the SDK catches, retries three times, then reports a `MirrorErrorMessage`, so
  swallowing makes a broken mirror look healthy.
- **`AGENT_SERVICE_DATABASE_URL` is popped from `os.environ` at startup**, in
  `get_settings()`. Not tidiness: the agent's subprocess inherits this process's
  environment and has `Bash`. `ANTHROPIC_API_KEY` cannot be hidden this way.
