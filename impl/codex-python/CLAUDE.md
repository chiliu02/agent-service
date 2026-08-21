# impl/codex-python — working notes for Claude

The **OpenAI Codex SDK** implementation: an HTTP wrapper over `openai-codex`, in
Python, shipped as a container. `docs/codex-python-guide.md` is the front door a
consumer reads; `docs/codex-python-references.md` is **the only document this
build's code may cite**, by ID. This file is only the things that are easy to get
wrong and are not visible from the tree.

**This file was written on 2026-08-11, long after the build.** `claude-python`
has had one since Plan 8 step 1, when the repository's single `CLAUDE.md` was
split one-per-level and the implementation half went with the code. This build
was created afterwards and never got the equivalent, so everything below already
existed — in the references file, where it is cited by ID from code rather than
read on the way in. **Nothing here is new; it is the entry point that was
missing.**

**The platform's rules are one level up.** The boundary rule ("never write
outside this directory"), the Agent Harness channel, thread naming and the
escalation rule are in [`../../CLAUDE.md`](../../CLAUDE.md), and they outrank
anything here. So does its warning about the CI runner: `ci.py` lives at the
platform root and `../../docs/ci.md` is its reference.

**Paths below are relative to this directory** unless they start with `../`.

## Read before running anything

- **`uv run pytest -m live` spends real money** — real turns against a real
  model. `pyproject.toml` sets `addopts = "-m 'not live' -q"` so the default run
  is free; **do not add `-m live` to "be thorough", and do not remove that marker
  filter.** Ask first. A bare `-m "not postgres"` on the command line *replaces*
  `addopts` rather than composing with it, which is exactly how the Claude
  build's paid tests were silently re-selected for weeks.
- **The container needs `seccomp=unconfined` or the agent cannot run a single
  shell command** (CX-01). Codex confines the agent with **bubblewrap**, which
  builds a user namespace, and Docker's default seccomp profile refuses
  `unshare(CLONE_NEWUSER)`. It fails closed — nothing runs unsandboxed — but
  nothing runs. **`cap_drop: ALL` is not the cause and `cap_add: SYS_ADMIN` is
  the reflex fix that does not work**, being weaker *and* more dangerous.
- **The service refuses to boot when misconfigured and exits 3** (CX-34, CX-39).
  That is deliberate, and each gate names what to do. The workspace mount is
  required; `/codex-home` is not.
- **`uv run pytest` here needs no Docker and no Postgres**, unlike the Claude
  build, whose suite starts a Postgres container when it can.
- **This suite distributes cleanly, and the Claude build's does not.**
  `pytest-xdist` is a dev dependency since 2026-08-17 and `ci.py` passes `-n 4`
  **unconditionally** here — where the Claude build gets it only alongside
  `-m "not postgres"`, because its Postgres tests share one server and one
  schema. Nothing here is shared: no database, no `conftest.py`, no session- or
  module-scoped fixture in `tests/`, and every session takes its `CODEX_HOME`
  and workspace from a per-test `tmp_path`. **Keep it that way** — a
  session-scoped fixture added here would break the CI quietly, as flakes.
  Measured: 37.1s at `-n 1`, 11.6s at 4, 9.7s at 6, 9.1s at 8. What the workers
  remove is process lifecycle (CX-19), not compute — `test_sessions.py` opens
  and closes a real app-server per test, 13.4s of teardown across 20 tests.

## Commands

```bash
uv sync                                  # uv, not pip/venv
uv run pytest                            # no API calls, no cost, no container
uv run pytest -n 4                       # ... in ~12s instead of ~37s
uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8000

docker compose up -d --build --wait      # needs WORKSPACE_HOST_PATH in .env
docker compose --profile persistence up -d postgres
```

**The CI is not run from here.** One runner for the whole platform, at the root:

```bash
cd ../..
uv run --no-project python .ci/ci.py         # freeze, links, references, unit, container, gates
uv run --no-project python .ci/ci.py --fast  # ... no Docker at all
```

It runs every `uv`/`docker` command *with this directory as the working
directory*, so what it executes is what the block above executes. This build is
in **both** `UNIT_IMPLS` and `CONTAINER_IMPLS` — the latter since 2026-08-08,
when it gained a Dockerfile — so `container` and `gates` build and boot this
image too.

## Code cites `CX-nn`, and nothing else

**A comment names an entry of `docs/codex-python-references.md` and nothing
else** — no path, no heading, no section number, not another build's document.
`ci.py`'s `references` stage enforces it over comments and docstrings in `.py`,
and over `#` comments in compose files and Dockerfiles.

**An ID is permanent.** A superseded entry is struck through and kept, never
renumbered. **Change the code, update the entry.** The references file itself
links to nothing, so a reader holding only it never hits a dead end.

## House rule: measured, not assumed

Every non-obvious claim is either **measured by a live probe** or **read from the
installed SDK source**, and claims that were once asserted and later disproved
are kept as explicit corrections, because the fact that they were wrong is
load-bearing. **Section I of the references file is exactly that list**, and it
is the first thing to read before re-arguing anything:

- *"The environment variables carry the credential."* They are published, they
  are exported, and **the app-server ignores them** (CX-20).
- *"`plan` is read-only."* It was, **until the agent approved itself** (CX-04).
- *"`unsupported()` reports refusals to the caller."* It reported them to nothing
  for a whole release (CX-10).
- *"Codex's sandbox is Landlock plus seccomp, so `cap_drop: ALL` is fine."*
  Three of those four claims were wrong (CX-01).
- *"The marginal cost of a session is memory."* **It is processes** (CX-19).

Probes go in `spike/` and are written up as numbered entries, each with its own
`CX-nn`.

## Gotchas — the ones that are invisible from the tree

- **The credential does not reach the SDK through the environment** (CX-20). The
  app-server ignores `OPENAI_API_KEY`; **this service performs `login_api_key()`
  at session open** using whichever variable is set. So the variables are where
  the service reads a key from, not a mechanism the SDK honours.
- **A login can exist that the boot gate cannot see** (CX-39). `login_api_key()`
  writes into `CODEX_HOME`, so a mounted volume carrying an earlier login is
  already authenticated with no variable set. Such a deployment must start with
  `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, and the gate's own message says so.
- **This service is the approver, and reaching that uses two SDK privates**
  (CX-06, CX-07). `assert_sdk_shape()` checks every name reached for and runs as
  an ordinary free test, so **an SDK bump fails in CI rather than silently
  denying MCP in production.** The handler runs on the client's reader *thread*,
  so it must never block and never raise. Before it existed,
  `permission_mode: "plan"` approved *itself* and wrote to the workspace.
- **`pids_limit` binds long before `mem_limit`** (CX-19). Measured ~20 MiB and
  **~30 processes** per session: at 16 sessions the container is at 485 of 512
  pids and only 402 of 2048 MiB. **A container carries about 16 sessions
  whatever `max_sessions` says**, and the two are configured independently.
  Exceeding it is now a retryable **503**.
- **Resume needs the rollout, which lives in `CODEX_HOME`** (CX-17). A thread
  that has taken no turn cannot be resumed at all, and a conversation survives a
  restart **only if `CODEX_HOME` is on a volume**. `GET /v1/sessions` is empty
  after a restart and that is correct — the registry is in memory.
- **`CODEX_HOME` is set explicitly in the Dockerfile rather than left under
  `$HOME`** (CX-34): a path chosen on purpose can be mounted; one inherited gets
  mounted by accident or not at all.
- **Cost is `null`, never `0.0`** (CX-12, CX-29). There is no monetary figure
  anywhere in the SDK, and `0.0` reads as *free* — which is why the field was
  made nullable. `total_cost_usd: 0.0` was defended as correct here once and it
  was wrong.
- **A caller-supplied `sdk_session_id` is refused, never adopted-and-replaced**
  (CX-16), and the thread id exists at creation, so it is **never null** here
  (CX-15) — the opposite of the Claude build's shape.
- **`max_turns` and `max_budget_usd` are refused; `timeout_s` is enforced**
  (CX-11). A published option that nothing applies is the defect this build
  shipped **twice** (CX-10) — if you add an option, apply it or refuse it.
- **The auth module is a second copy on purpose** (CX-45), guarded by the suite,
  and **the models are imported from `agent_spec` rather than redeclared**
  (CX-46) — AS-24 requires every implementation to serve the same document and
  two hand-maintained copies cannot stay byte-identical.
- **Two version numbers, and they are not the same number.** `DOCUMENT_VERSION`
  is the specification's and must equal `../../spec/VERSION`;
  `IMPLEMENTATION_VERSION` is this build's, must equal `pyproject.toml`'s
  `version`, and is what an image tag carries. `src/agent_service/versions.py`
  is deliberately import-free, because `agent_service.spec` runs in an image
  whose service cannot start.
- **`openai-codex` is the package, and a lookalike exists on PyPI** (CX-28).

## Where things are

- `docs/codex-python-guide.md` — **the front door for anyone integrating against
  this build**, and a condition of every non-snapshot release (user,
  2026-08-09).
- `docs/codex-python-references.md` — the one document code may cite; sections
  A–I, from the SDK through the sandbox, approvals, MCP, options, lifecycle, the
  container, where this build cannot satisfy a clause, and the history that must
  not be re-litigated.
- `src/agent_service/` — the service. **A comment cites a `CX-nn` ID and never a
  path.**
- `spike/` — throwaway probe scripts, committed on purpose as evidence, plus
  `mcp_echo_server.py`, which exists so the MCP questions could be answered
  against a real server.
- **There is no `README.md` here**, unlike the Claude build. The guide is the
  document that would otherwise be one.

**One level up**, because they are the platform's:
`../../docs/ci.md`, `../../docs/plans.md`, `../../docs/dev-todo.md` (read its
"Do not 'fix' these" section first), `../../docs/open-questions.md`,
`../../docs/security-posture.md`, and the contract at `../../spec/`. The outbox
is at `../../docs/to-agent-harness/` — tracked in the development
repository, and removed by the export that builds the public one.
