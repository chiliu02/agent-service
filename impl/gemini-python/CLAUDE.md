# impl/gemini-python — working notes for Claude

**The third implementation, and it serves the specification.** The target is
**Gemini CLI headless**, driven from Python — no SDK exists, and the agent is a
Node program this service spawns (`GP-41`). All thirteen `/v1` operations are
built, the image builds and boots, and the platform's conformance suite runs
against it in CI: **78 passed, 4 skipped, 0 failed**, with the shared core over
three documents losing **zero** leaves.
`docs/gemini-python-references.md` beside this file is the evidence and **the
only document this build's code may cite**.

**Nothing here has been delivered.** No image is tagged, no release is cut, and
the consumer has been told nothing about this build. That is a decision, not an
oversight — see *What is not built* at the end.

**Read `GP-41` before anything else.** This build is **CLI-only**: every turn,
every session and every event comes from `gemini -p … -o stream-json`, and
listing, deletion and interrupt come from our own store and a process kill.

**ACP was implemented and removed** (GP-01 is struck through and kept). It cannot
resume (GP-38), its tool stream is not richer (GP-40), and its permission channel
is a question this service would ask itself and answer from the policy file it
had just written. Do not reintroduce it without one of GP-41's two triggers.

**The platform's rules are one level up.** The boundary rule ("never write
outside this directory"), the Agent Harness channel, thread naming and the
escalation rule are in [`../../CLAUDE.md`](../../CLAUDE.md), and they outrank
anything here. So does its warning about the CI runner: `ci.py` lives at the
platform root and `../../docs/ci.md` is its reference.

**Paths below are relative to this directory** unless they start with `../`.

## Read before running anything

- **The live probes SPEND MONEY, and the cost is not where you think.** The spike
  that produced this directory was estimated at "cents" and cost about **10 USD**.
  The estimate was made from prompt sizes; the prompts were never the cost. **A
  turn that cannot finish is the expensive one** — see `GP-18` and `GP-32`. Ask
  before running the live set.
- **Run the free probe first.** `spike/probe_gemini_cli.py` needs no credential,
  no turn and no container, and a large fraction of what decides this build's
  shape is free — the ACP method table, the handshake catalogues, every exit code
  that does not need a turn, and policy validation (`GP-32`).
- **Every live probe pins `-m gemini-3.1-flash-lite` and caps each run at 60
  seconds.** Do not remove either to "be thorough". The unpinned default is
  `auto`, which bills **two** models per turn (`GP-16`); the cap is what stops a
  non-terminating turn from spending for as long as you let it.
  `GEMINI_PROBE_MODEL` overrides the model when a finding is genuinely about the
  model rather than the interface.
- **Running the CLI writes to `$HOME/.gemini/`**, outside this repository, and
  there is no override (`GP-13`). That is the tool's own behaviour, not ours, but
  know it before wondering where a session went.

## Commands

```bash
# the service. Free: nothing spawns until a turn is taken
uv run pytest                       # 77 tests, no agent, no key, no container
uv run pytest -n 4                  # ... in ~6s instead of ~16s. What CI passes
uv run uvicorn agent_service.main:app
uv run python scripts/dump-openapi.py   # publishes the document AND recomputes the core

# the agent under test -- NOT committed, and .gitignore'd
npm install --no-save @google/gemini-cli@0.54.4

# free: costs nothing, needs nothing
uv run --no-project python spike/probe_gemini_cli.py node_modules

# free: does a policy file validate? no key, no turn, no tokens (GP-26)
node_modules/.bin/gemini --list-sessions --admin-policy <file>

# THESE SPEND MONEY -- ask first
GEMINI_API_KEY=... uv run --no-project python spike/probe_gemini_cli_live.py node_modules
GEMINI_API_KEY=... uv run --no-project python spike/probe_gemini_policy_live.py node_modules
GEMINI_API_KEY=... uv run --no-project python spike/probe_gemini_mcp_live.py node_modules

# needs Docker, not a key
docker build -f spike/sandbox-probe.Dockerfile -t gemini-sandbox-probe .
```

`.env` here holds `GEMINI_API_KEY` and is gitignored by the platform root's rule.

**The CI is not run from here**, and all six of its stages now touch this
directory:

```bash
cd ../..
uv run --no-project python .ci/ci.py --fast   # freeze, links, references, unit
uv run --no-project python .ci/ci.py          # ... and container + gates, which need Docker
```

**`container` builds this image, boots it, and runs `spec/conformance/` against
it** — since 2026-08-11, when `CONTAINER_IMPLS` gained a `Containerised` record
(`agentsvc-ci-gemini` on host port **8120**, `persistence=True` since
2026-08-12, so the suite runs TWICE — once with no database and once with one).
`gates` then
starts it with each boot gate deliberately unsatisfied and asserts it exits 3.

**That suite is judged against the specification, not against this build, and it
found eleven defects my own 77 tests did not** — a wrong path parameter
(`session_id` where the contract says `{sid}`), four operationIds FastAPI had
derived from function names, three missing operations, ten operations declaring
no error responses, and a `429` published against a route that consumes no
session slot. **Do not treat a green `uv run pytest` as done.**

## Code cites `GP-nnn`, and this directory is already scanned

**A comment names an entry of `docs/gemini-python-references.md` and nothing
else** — no path, not another build's document, not a todo. `ci.py`'s
`references` stage enforces it over comments and docstrings in `.py`, and over
`#` comments in compose files and Dockerfiles.

**It applies to `spike/` too, and it caught eight defects on its first day** —
probe docstrings citing `.md` filenames, exactly the rot the rule exists for.
Do not reintroduce them: cite `GP-18` rather than naming a spike document.

**An ID is permanent.** A superseded entry is struck through and kept, never
renumbered. **Change the behaviour, update the entry.**

## House rule: measured, not assumed

Every non-obvious claim is either **measured by a live probe** or **read from the
installed bundle**, and claims that were once asserted and later disproved are
kept as explicit corrections, because the fact that they were wrong is
load-bearing. This directory has three of them and each cost something:

- the ACP method table was read from a symbol table and **half of it is not
  implemented** (`GP-02`);
- `--approval-mode` was read as fail-closed from its plumbing and **a turn says
  otherwise** (`GP-18`);
- the folder-trust gate was read as a silent degradation and **it is a hard
  refusal** (`GP-08`, and exit `55` in `GP-06`).

**Ask the binary, not the bundle** — and where the published documentation and
the binary disagree, the binary wins. It has been wrong twice so far (`GP-22`,
`GP-29`).

## Gotchas — the ones that are invisible from the tree

- **This suite is distributed, and it is the easiest of the three to keep that
  way — so keep it that way.** `pytest-xdist` is a dev dependency since
  2026-08-17 and `ci.py` passes `-n 4` unconditionally. Nothing here is shared:
  no database, no `conftest.py`, no session- or module-scoped fixture in
  `tests/`, and no wall-clock assertion anywhere — the Claude build has a dozen
  of those and a shared Postgres, which is why it gets workers only alongside
  `-m "not postgres"`. **A session-scoped fixture added here would break the CI
  as flakes rather than as a failure.** Measured: 16.4s at `-n 1`, 6.3s at 4.
  **It bought the `unit` stage nothing measurable** — 21.2s mean before (n=7),
  21.3s after (n=12), against a ±3s spread — because that stage is CPU-bound
  once all three builds have workers, so these come out of the other two's
  share. The entry is for consistency across the builds, not for the clock.
  `../../docs/ci.md` has the numbers, including why a handful of runs here
  proves nothing either way.
- **Set `GEMINI_CLI_TRUST_WORKSPACE=true`. Do NOT use `--skip-trust`** (`GP-08`).
  The CLI offers them as alternatives and they are not: under the flag the agent
  gets **no MCP servers at all**, silently, with nothing on stderr. An untrusted
  folder otherwise refuses the whole run with exit `55`. Several probes here
  still pass `--skip-trust` because they predate the finding and do not touch
  MCP; the *build* must not copy them.
- **`--resume` works exactly once and then deletes the transcript** (`GP-10`).
  Not a race and not a bug you can retry around: the resume writes a stub with no
  resumable content, and cleanup deletes every file sharing its 8-character short
  id — which is the real transcript. **`--session-file` is the only durable
  resume** (`GP-11`), it mints a new `session_id` each run, and it cannot be
  combined with `--session-id` or `--resume`. So a caller-supplied
  `sdk_session_id` and durable resume are mutually exclusive here.
- **`--approval-mode` is not a boundary and does not reliably terminate**
  (`GP-18`). Nine trials of one prompt: one write, three do-nothing finishes,
  five that never ended. **The Policy Engine is the boundary** (`GP-19`), and it
  also removes the non-determinism.
- **Deny `*` and allow explicitly. Never deny a tool by name** (`GP-20`) — the
  agent routes around it through the shell, because a denied tool is removed from
  its context rather than refused.
- **One bad enum value discards the WHOLE policy file, and the run proceeds with
  no policy, exit 0** (`GP-25`). The likeliest typo is `auto_edit`, which is what
  `--approval-mode` itself spells — the policy field wants `autoEdit`.
  **Preflight every policy file keylessly and refuse to start if it is rejected**
  (`GP-26`), and generate the TOML from a typed structure rather than templating
  strings.
- **A refusal looks like success.** A run that declined to do the work still
  exits `0` with `result.status: "success"` (`GP-18`), and the JSON envelope is on
  stdout when it worked, stderr when it failed, and **plain text — not JSON** when
  it failed early (`GP-09`).
- **There is no interrupt verb.** `session/cancel` is not registered (`GP-02`),
  so `POST /v1/sessions/{sid}/interrupt` means killing the subprocess, and a
  wall-clock timeout is mandatory rather than a refinement.
- **`--sandbox` cannot start inside our container** (`GP-31`), exit `44`. Do not
  "fix" it by mounting the host's docker socket: that hands the agent the host's
  container runtime, a strictly worse boundary than the one it adds. The
  container is the sandbox; the policy is the tool boundary inside it.
- **Popping a secret stops a CHILD inheriting it and hides nothing** (`GP-51`).
  `/proc/<pid>/environ` keeps the value for the life of the process and the agent
  runs as the same uid, so it can read the service's. The auth token and the
  database URL are popped anyway — it removes the common accident, not the
  determined reader — and the rule that follows is **per instance, never per
  fleet**. Do not check this with `docker exec`: that starts a new process from
  the container's configured environment and answers a different question.
- **A database is HISTORY; the `transcripts` volume is CONTINUITY** (`GP-49`).
  They are different volumes and different failures, and the Claude build blurs
  them because its SDK can resume out of Postgres. This one cannot: `Persistence`
  is built with no `session_store_factory`, and nothing reads a row back into a
  turn.
- **The `transcripts` volume IS the resume mechanism**, not a log. `--session-file`
  is the only durable resume (`GP-11`), so a caller's `options.resume` reads a
  file from that volume; dropping it silently turns every resume into a fresh
  conversation. `homes` beside it is scratch — one directory per session holding
  its own `HOME` and its generated policy (`GP-39`), and closing a session
  deletes it while **keeping** the transcript.
- **The base image is Node, so uid 1000 is already taken.** `node:22-slim` ships
  a `node` user at 1000; the Dockerfile therefore *renames* it
  (`usermod --login agent … node`) rather than creating one, which would fail.
- **A `.gemini/settings.json` in the WORKSPACE merges into the session's own**
  (`GP-46`), and the workspace is caller-supplied and agent-writable -- so a
  repository can register MCP servers, meaning subprocesses, that nobody asked
  for. `--allowed-mcp-server-names` is the only control a workspace cannot
  override, and **it is passed on every turn, including when the caller sent no
  servers** (`GP-47`). Removing it in that case looks like a harmless
  optimisation and is the whole vulnerability.
- **`system_prompt` is an ENV VAR and a FILE, and it was wired to nothing until
  2026-09-02** (`GP-66`). There is no `--system-prompt`: the agent reads
  `GEMINI_SYSTEM_MD`, which **replaces** the built-in prompt entirely. Pass the
  **absolute path**, never the `1` switch form — that resolves
  `.gemini/system.md` against the working directory, which is the caller's
  writable workspace. The field was published, accepted and read by no module
  for four months, which is the *accepted and silently ignored* defect this file
  attributes to the Codex build, shipped here. **Both ends had unit tests and
  the seam did not**: a live turn is what caught it.
- **A custom system prompt suppresses NO ambient input.** `renderFinalShell`
  appends the context files in both branches, and this build refuses
  `setting_sources`, so a `GEMINI.md` in the mounted workspace reaches every
  turn whatever a caller sends. It is the only one of the three builds with no
  lever at all over its ambient configuration — `../../docs/capability-divergence.md`
  §3.1 is where the three are compared.
- **Everything is pinned to `@google/gemini-cli` 0.54.4** and there is no
  stability contract over the flags or over which ACP methods are registered.
  `GP-33` is the recheck order for an upgrade, cheapest first. The Dockerfile
  verifies the installed version at **build** time, so a drifted npm registry
  breaks the build rather than a turn.

## Where things are

- `src/agent_service/` — **twelve modules**, and the split is by what each one
  answers to:
  - `api.py` — all thirteen `/v1` operations. **The document is generated from
    it**, so a function name, a tag and a declared response are contract, not
    style.
  - `cli.py` — `CliRunner`, the argv and environment for a turn, the exit-code
    table, and `StreamingTurn`, which yields events as the agent emits them
    (measured: first event at +1.53s of a 4.77s turn, not buffered to the end).
  - `policy.py` — generates the admin-tier TOML from a typed structure and
    **preflights it keylessly** before any session can use it (`GP-26`).
  - `persistence.py` — **the whole cost of a database to this build**: one
    function mapping a `TurnResult` to the platform's `RunOutcome`. Everything
    below the seam is `agent_spec.db`.
  - `auth.py` — a bearer token over `/v1`, by PREFIX rather than per route.
    `/healthz` is deliberately outside it: the container healthcheck reads it,
    and an authenticated container whose healthcheck could not run would be
    permanently unhealthy.
  - `mcp.py` — the session's `settings.json` and the allow list. **Two layers,
    and the policy is the stronger one**: it denies every server the request did
    not name, which is why `strict_mcp_config: false` is refused rather than
    accepted (`GP-48`).
  - `registry.py` — a session is a directory, a policy file, a transcript path
    and a lock; never a live process (`GP-41`). Sweeps the idle TTL on every
    operation, because `session_idle_ttl_s` is published.
  - `capabilities.py`, `config.py`, `spec.py`, `versions.py`, `main.py` — what is
    published and what is required to boot. **`spec.py` is no longer a command**
    (`GP-63`): it was `agent-service-openapi` until 0.19.0, and its facts are now
    `components.schemas.PrebootSpec` in this build's own document, pinned with
    `const`, so a consumer reads them from `spec/` instead of by running a
    container.
- `Dockerfile`, `compose.yaml`, `compose.ci.yaml` — `node:22-slim` pinned by
  digest with uv-provided Python, `cap_drop: ALL`, no `seccomp=unconfined`, and
  the port bound to `127.0.0.1`. **Both boot gates are passed through** rather
  than hardcoded, so compose can start an image that is meant to refuse.
- `tests/` — **117, none of which spend anything.** `fake_cli_agent.py` is a
  stand-in binary that emits real stream-json shapes, which is what lets the turn
  and streaming routes be tested without a credential.
- `scripts/dump-openapi.py` — publishes this build's document into
  `spec/<version>/` and **recomputes the shared core across every
  build's document**. It refuses a core that shrinks, except on a `-snapshot`.
- `docs/gemini-python-guide.md` — **what a client author reads first**: the
  boot gates, the eleven things that will surprise them, the capability table
  and what stays their responsibility.
- `docs/gemini-python-references.md` — **66 entries, `GP-01`–`GP-66`**, seeded
  2026-08-11 from five spike documents. It links to nothing and every entry is
  complete: a reader holding only that file can act correctly.
- `spike/` — **ten probes**, committed on purpose as evidence:
  - **free entirely** — `probe_gemini_cli.py`, which answers everything the
    binary can answer without a credential, and
    `probe_gemini_mcp_config.py`, which settled where MCP servers may be
    registered and found the workspace merge (`GP-46`) using `gemini mcp list`
    alone;
  - **free half, paid half** — `probe_gemini_mcp_live.py`,
    `probe_gemini_modes_live.py` and `probe_gemini_system_prompt_live.py` run
    their keyless checks and stop when `GEMINI_API_KEY` is unset, which is how
    the policy-validation findings stay reproducible for nothing. The last of
    them drives the HTTP surface rather than the binary, because what it checks
    is that a REQUEST reaches the agent (`GP-66`), and its two turns are a
    control pair;
  - **paid** — `probe_gemini_cli_live.py`, `probe_gemini_acp_live.py`,
    `probe_gemini_sessions_live.py`, `probe_gemini_policy_live.py`,
    `probe_gemini_shell_policy_live.py`.

  Beside them, `mcp_spike_server.py` is a dependency-free stdio MCP server that
  exists so the MCP question could be answered with a real one, and
  `sandbox-probe.Dockerfile` needs Docker and no key.
- `node_modules/` and `temp/` — **gitignored**. The agent under test is someone
  else's bundle, pinned in each probe's own constant and printed at run time so a
  version mismatch is visible rather than assumed.
- **The narrative** — five spike documents at `../../docs/history/gemini-python/`, kept
  for how the findings were reached. **Nothing here depends on them**: everything
  load-bearing is restated in the references file, which is why code may not
  cite them.

## What is not built, and what is published about it

**Every gap below is published on `/v1/capabilities` rather than left for a
consumer to discover.** That is AS-32, and it is also the correction of a defect
the Codex build shipped twice: an option accepted and quietly ignored. Where this
build cannot do a thing, it says so, and where a caller can ask for that thing it
**refuses with a 400** rather than accepting the field.

| Not built | What is published |
|---|---|
| **One tool of an MCP server** | nothing, and this is the honest gap. The policy rule is `mcpName = <server>, toolName = "*"`, so allowing a server allows every tool on it — measured, including a decoy `delete_everything` (`GP-48`). The narrow rule shape exists but no `RunOptions` field carries it |
| **`strict_mcp_config: false`** | refused with `strict-mcp-config-required`, because this build cannot produce non-strict behaviour: the tool policy denies every server the request did not name, so the flag would change an argv and nothing else (`GP-48`) |
| **A budget, an effort dial, setting sources, a turn limit** | refused in `unsupported_options`, each with an entry behind it |

**`reference_dirs` is deliberately NOT in that list.** It is a capability field,
not a `RunOptions` one — a caller cannot send it, so this build cannot refuse it,
and publishing it promised a 400 that could never happen. The honest statement of
an unwired `--include-directories` is `reference_dirs: []` in the capability
itself. The conformance suite caught it; it is the same defect as an option
accepted and ignored, wearing the opposite coat.

**The consumer guide exists** since 2026-08-12 —
`docs/gemini-python-guide.md`, the front door a client author reads, and a
condition of every non-snapshot release. It describes what was built rather than
what was planned, which is why it waited for the code.

**Nothing is delivered, and delivering is the user's call** — an image tag, a
a `release-<version>` tag or a bare `spec/VERSION` all need asking, and
`../../docs/versioning.md` is why. The one thing owed to the consumer on the day
this ships is `allow_supplied_sdk_session_id: false` (`GP-34`), which the other
two builds do not share.
