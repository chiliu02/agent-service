# `claude-python` — running and deploying it

**The operator's document: how to run this build, what to mount, and what will
bite you.** For writing a *client* against it, read
[`claude-python-guide.md`](./claude-python-guide.md) instead; for the evidence
behind any claim here, [`claude-python-references.md`](./claude-python-references.md).

**This was `README.md` until 2026-08-11.** That file mixed three audiences —
operator, client author and maintainer — and rotted where the tree moved under
it: it sent readers to `scripts/ci.py`, `tests/dbharness.py` and
`impl/claude-python/schema/`, none of which had existed since Plan 8 and Plan 9.
The operator half is here, the client half is in the guide, the maintainer half
is in `CLAUDE.md` beside the code, and the dead paths are fixed.

---

## ⚠️ Read before running

The agent has `Bash` enabled by default and **can run arbitrary shell commands as
the service process**. Neither `cwd` nor `add_dirs` restricts which files a tool
may touch — verified, not assumed (CP-L3/L7 in the references file).

- **[Run it in a container](#run-it-in-a-container)** with only the directories
  you intend mounted. Outside a container the agent can read anything the process
  can read. `../compose.yaml` is the shipped, measured way to do that; the
  read-only reference mount was verified to be a kernel boundary (`EROFS`), not a
  convention the agent cooperates with.
- **Bind to localhost only.** There is no authentication on the API by default —
  none, at all. Anyone who can reach the port can create a session and run shell
  commands. See [why the port is bound to `127.0.0.1`](#why-the-port-is-bound-to-127001),
  and [`../../../docs/security-posture.md`](../../../docs/security-posture.md)
  for the threat model and what "production ready" means for a multi-user
  deployment.
- **`max_budget_usd` is not a spend cap, and this service cannot make it one.**
  It is enforced inside the CLI against the same cumulative figure
  `total_cost_usd` reports — and that figure **does not move for an interrupted
  turn**, which nonetheless runs real inference. Measured: with
  `max_budget_usd=0.05`, eight consecutive start-then-interrupt turns advanced it
  by **$0.000649** and the budget never tripped; six ordinary turns on the same
  connection then tripped it at $0.0585. A caller who can call
  `POST /v1/sessions/{id}/interrupt` can spend without limit under any value set
  here, and **you cannot see it happening from the API.** Budget at the account or
  organisation level.
- **In-process write confinement is opt-in and off by default.**
  `Settings.permission_enforcement` defaults to `"none"` — no in-process control
  is wired up at all, and the container/mount boundary is the *only* thing between
  the agent and the rest of the filesystem. This is deliberate. An earlier version
  of this warning claimed `policy.py`'s `can_use_tool` callback confined
  `Write`/`Edit` to the workspace; live verification found that false under this
  service's own defaults — `default_allowed_tools` grants `Write`/`Edit` as whole,
  unscoped entries, and the installed SDK auto-approves a whole-tool entry before
  `can_use_tool` is ever consulted (`CanUseToolShadowedWarning`). A forced live
  write outside the workspace actually created the file, with `permission_denials`
  coming back empty. Five follow-up probes confirmed `can_use_tool` never fires
  under *any* configuration this service would realistically use, so it is **not
  offered as an enforcement mode at all.**

  `AGENT_SERVICE_PERMISSION_ENFORCEMENT=hook` attaches a `PreToolUse` hook
  instead, which the same probes confirmed *does* fire and *does* block an
  out-of-workspace write — but even with it on, the container is the recommended
  boundary, not a fallback. **The hook confines `Write`/`Edit`/`NotebookEdit`
  only — `Bash` is enabled by default and is NOT confined by it, so a shell
  redirect (`echo x > /etc/foo`) walks straight past it.**
  `GET /v1/deployment` reports which mode is actually live.

## Quick start, without a container

```bash
uv sync
cp ../.env.example ../.env      # then add your ANTHROPIC_API_KEY
uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8000
```

**`.env.example` sets `AGENT_SERVICE_REQUIRE_MOUNTS=false`, and a checkout needs
it.** The mount guard is on by default so a container gets it without anyone
remembering a flag; outside one there is nothing to check, because `./workspace`
is an ordinary directory the service creates on first run. Without the opt-out
this command exits 3.

**The service refuses to start without credentials** and exits non-zero rather
than booting and failing on the first turn. Set `ANTHROPIC_API_KEY` (or
`ANTHROPIC_AUTH_TOKEN`, or `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY`).

**A `.env` is found by walking up from `main.py`'s own directory**, not the
process working directory — so it works for an editable checkout and **does not**
work for an installed package or a container, where these must be passed as real
environment variables. Measured: with a valid key in `./.env` and the package
importable from elsewhere, the service refused to boot and exited 3.

To start without credentials — for `/docs`, `/openapi.json` or
`/v1/deployment` — set `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`. Credentials
that disappear *after* boot do not stop a running service; `GET /healthz` reports
`credentials_configured` live.

Then open <http://127.0.0.1:8000/docs>, or:

```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H 'content-type: application/json' \
  -d '{"prompt": "List the files here and summarise what this project is"}'

curl -N -X POST http://127.0.0.1:8000/v1/query/stream \
  -H 'content-type: application/json' \
  -d '{"prompt": "Find every TODO comment"}'
```

## Run it in a container

**This is the recommended way to run it.** The container is the boundary the
warning above assumes; outside one, the agent's `Bash` tool reaches everything the
process can.

```bash
cp ../.env.example ../.env                  # if you have not already
cat ../.env.compose.example >> ../.env      # appends the container-only variables

# Edit .env and set three things (Windows: FORWARD slashes):
#   ANTHROPIC_API_KEY=sk-ant-...
#   WORKSPACE_HOST_PATH=C:/path/to/scratch-or-repo   -> /workspace, READ-WRITE
#   REFERENCE_HOST_PATH=C:/path/to/a/reference-repo  -> /reference/<name>, READ-ONLY

docker compose up -d --build --wait
curl -s http://127.0.0.1:8000/healthz
```

`<name>` is `REFERENCE_NAME`, **commented out** in `.env.compose.example` and
defaulting to the literal string `reference` — so if you change nothing, the
read-only mount is at **`/reference/reference`**, and that is the path to give the
agent. Uncomment it to name the mount after the repo (`REFERENCE_NAME=acme-api` →
`/reference/acme-api`). The mount target and the `add_dirs` entry both come from
that one variable, so they cannot drift apart.

Cold build ~43 s (753 MB image; half of it is the SDK's 262 MiB bundled binary),
healthy about 1.3 s after start.

### Things that will bite you, all measured

- **A credential is required or the container does not start.** With no
  `ANTHROPIC_API_KEY` it prints the message naming what to set, **exits 3** in
  0.93 s, binds no port, and stays down — `compose.yaml` sets `restart: "no"` on
  purpose, so `docker compose ps` shows `Exited (3)`. **The trap: plain
  `docker compose up -d` reports `Started` and returns 0 for a container that is
  already dead.** Use `--wait`, which returns 1.
- **A `.env` in your working directory is not read by the service.** Compose reads
  `.env` *beside `compose.yaml`* to interpolate the file, and passes the keys
  listed under `environment:` in as **real environment variables** — that is how
  the credential reaches the container, and it is the only way. Nothing inside the
  container loads a `.env` at all. Mounting one will not work. Only the keys named
  in `environment:` cross the boundary.
- **`docker compose ps` and `logs` fail too until both mount paths are set.** The
  volumes use `${VAR:?…}`, so every subcommand errors with `required variable
  WORKSPACE_HOST_PATH is missing a value` before showing anything — including the
  read-only ones you reach for when something is wrong. Easy to walk into, because
  `.env` already exists and works for the non-container run; the missing step is
  `cat .env.compose.example >> .env`.
- **Mount the repository *root*, not a subdirectory.** Mounting a `src/`
  subdirectory leaves `.git` outside the container and every git command fails
  with *"not a git repository"*.
- **On a Linux or WSL2 host, change two variables.** `GIT_AUTOCRLF=input` and
  `GIT_FILEMODE=true`. The defaults are correct for a Windows host and wrong on
  Linux, and neither fails loudly — one rewrites the mounted repo's line endings
  into history on the agent's first `git add -A`, the other hides real permission
  changes.
- **Bind mounts on Windows are slow, by a lot.** `git status` on a 5,000-file
  repo: **23,545 ms on the bind mount vs 42 ms** on the container's own
  filesystem — 561×, or 223× with the line endings fixed. Move a large repo into
  the WSL2 filesystem and mount from there.
- **`docker compose stop` can legitimately take a while.** `stop_grace_period` is
  100 s, derived from a 30 s request drain plus a 60 s `close_all()` budget plus
  margin. A stop with live sessions mid-turn was measured at 42.4 s, exit 143. An
  idle stop is ~3.4 s.
- **The first turn on a session costs ~3× the second** — $0.105 then $0.034,
  measured — because of a ~37k-token tool/skill preamble that `allowed_tools`
  cannot shrink. Size `max_budget_usd` accordingly; one sized from steady-state
  turn costs trips on turn one.
- **Nothing bounds container memory unless you set it.** ~110 MiB and ~17 pids per
  session on a ~250 MiB warm baseline, so `max_sessions: 8` projects to ~1.1 GiB
  with no `mem_limit`.
- **The CLI writes a `⚠` line to the service's own stderr, once per session:**

  ```
  ⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source
    is set and takes precedence over your claude.ai login · Unset it to load your
    organization's connectors
  ```

  **Informational and expected** when authenticating with an API key, which is
  what this service is designed for — but it is written to stderr with a warning
  glyph and no level prefix, so a log aggregator that classifies by stream or by
  `⚠` will file it as an error, once per session, forever. It is the CLI's output,
  not this service's logging, so `AGENT_SERVICE_LOG_LEVEL` does not suppress it.

### Without compose — configuring the mounts on `docker run`

Everything above is reachable from a plain `docker run`, which is what you need
if you are driving the image from Docker Desktop or want **more than one**
reference directory (`compose.yaml` hardcodes a single mount). The two
directories are not symmetric, and both fail quietly when you get them wrong.

- **`/workspace` needs the mount only.** The Dockerfile bakes in
  `AGENT_SERVICE_WORKSPACE_DIR=/workspace`.
- **`/reference/<name>` needs the mount *and* `AGENT_SERVICE_REFERENCE_DIRS`, and
  the two must name the same path.** There is no default — `reference_dirs`
  starts empty.

`compose.yaml` sets no `image:`, so `docker compose build` tags the image
`<project>-agent-service`. Build your own tag if you are going to run it by hand:

```bash
docker build -t agent-service .

docker run -d --name agent-service \
  -p 127.0.0.1:8000:8000 \
  -v C:/path/to/scratch-or-repo:/workspace \
  -v C:/path/to/a/reference-repo:/reference/myref:ro \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e AGENT_SERVICE_REFERENCE_DIRS='["/reference/myref"]' \
  -e AGENT_SERVICE_REQUIRE_MOUNTS=true \
  --init \
  --stop-timeout 100 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --memory 1536m --pids-limit 512 \
  agent-service
```

Several reference directories, which compose cannot express:

```bash
  -v C:/repo-a:/reference/a:ro -v C:/repo-b:/reference/b:ro \
  -e AGENT_SERVICE_REFERENCE_DIRS='["/reference/a","/reference/b"]'
```

**Four ways this goes wrong without saying so:**

- **The value is parsed as JSON, not as a path.** Measured: `'["/reference/a"]'`
  works; `/reference/a` and `/reference/a,/reference/b` both raise
  `SettingsError: error parsing value for field "reference_dirs"` at startup. That
  one at least fails loudly.
- **A mount target and an env var that disagree produce no error at all.** The
  `reference_dirs` validator resolves paths and nothing else — no existence check.
  The directory is then invisible to `Read`/`Glob`/`Grep` and the agent reports it
  does not exist, while `docker exec ls` shows the files. This is the mistake
  `compose.yaml` designs out by deriving both from `REFERENCE_NAME`.
- **Forgetting `-v …:/workspace` is worse, because it looks like it worked.** The
  `workspace_dir` validator calls `mkdir(parents=True, exist_ok=True)` (measured),
  so the service *creates* an empty `/workspace` in the container's writable
  layer, boots cleanly, reports healthy — and everything the agent writes is
  discarded when the container goes.
- **`.env` does not cross the boundary.** Real `-e` variables are the only route.

**Two flags in that command are not decoration:**

- **`--init`.** Without an init at PID 1, grandchildren the agent's `Bash` tool
  backgrounds reparent to PID 1 and stay there: **3 orphans → 3 permanent
  zombies**, versus 0 with it. The agent subprocess itself is reaped either way —
  that part of the folklore was measured false.
- **`--stop-timeout 100`.** Docker's default grace period is far below
  `close_all()`'s 60 s budget — a three-session mid-turn shutdown was measured at
  16.2 s in the lifespan alone. Leave it at the default and Docker SIGKILLs
  partway through, leaving CLI subprocesses behind. Compose's
  `stop_grace_period: 100s` is derived from `shutdown_budget_s`, not guessed.

**Neither Docker nor compose will check the host paths for you.** Measured on
Docker Desktop for Windows: `-v`, `--mount type=bind`, *and* compose's long syntax
with `bind: {create_host_path: false}` **all silently create a missing host
directory** and start the container anyway.

**So the service checks instead**, which is why `AGENT_SERVICE_REQUIRE_MOUNTS` is
in the command above. With it on, a workspace that is not on a mounted
filesystem, or a `AGENT_SERVICE_REFERENCE_DIRS` entry that does not exist, refuses
the boot the same way a missing credential does — named problem, named fix,
**exit 3**, no port bound:

```
agent_service.config.MissingMounts: This service refuses to start because a required
directory is not mounted:
  - AGENT_SERVICE_WORKSPACE_DIR=/workspace is not on a mounted filesystem. It exists
    only because this service created it, so anything the agent writes there is
    discarded when the container stops. Mount it: -v /host/path:/workspace
To start anyway -- for a docs-only boot, or a test harness -- set
AGENT_SERVICE_REQUIRE_MOUNTS=false.
```

It defaults to **false** so a plain checkout still works; the container turns it
on. `workspace_dir` must be *under* a mount point rather than merely exist, since
existing is exactly what the bug produces; a reference directory need only exist,
because this service never creates one.

Also dropped by a minimal `docker run`, in rough order of how much you will miss
them: `mem_limit`/`pids_limit`, `CLAUDE_CONFIG_DIR=/tmp/claude-config`, the
`GIT_AUTHOR_*` / `GIT_COMMITTER_*` identity variables, and the healthcheck.

### Why the port is bound to `127.0.0.1`

`compose.yaml` publishes `127.0.0.1:8000:8000`, never `8000:8000`, and that is not
stylistic. `Bash` is enabled by default, `permission_enforcement` is `"none"`, and
**there is no authentication on the HTTP API by default** — so anyone who can open
a TCP connection to port 8000 can create a session and run arbitrary shell
commands inside the container. The bare `"8000:8000"` form publishes on every host
interface and hands that to anyone on the network. Verified: with the shipped
binding the LAN and WSL addresses refuse the connection and only loopback answers.
If you need it reachable from elsewhere, put an authenticating proxy in front and
leave this line alone.

Already in place, and measured to cost nothing: `cap_drop: [ALL]`,
`no-new-privileges:true`, a non-root `agent` user, and a root-owned `/app` the
service cannot modify. Deliberately **not** done: egress restriction (the
container can reach anything; note it would also disable `WebSearch`/`WebFetch`)
and any form of remote git access — a token or SSH key placed in this container is
readable by any command the agent runs.

## Persistence (optional, off by default)

With no `AGENT_SERVICE_DATABASE_URL` the service runs fully and stores nothing.
That is a supported configuration, not a degraded one: no engine is created, and
`agent_service.db` is never even imported.

**If you turn it on, watch `GET /healthz`.** It reports `database_configured` and
`database_usable`, and the second is the one that matters: **migrations do not run
on startup** — nothing in the service ever ran them, and the image carries no
migration tree — so the normal first state of a new deployment is a database with
no tables. The service boots anyway, returns 201s, and **discards every row**,
which is why the probe queries a real table rather than checking the connection.

`status` stays `"ok"` and the container stays healthy while this is `false`, on
purpose: persistence is optional, the container healthcheck reads the status code,
and a database outage must not restart a service whose agent side works. **Alert
on `database_usable`, not on the status code.**

```bash
uv run alembic upgrade head    # or -x url=postgresql://... for a remote one
curl -s http://127.0.0.1:8000/healthz    # database_usable: true

docker compose --profile persistence up -d      # opt-in; needs POSTGRES_PASSWORD
```

Set the URL and it records **two different things, for two different readers**:

| | What it is | Who reads it |
|---|---|---|
| `sessions` / `runs` / `events` | Normalized `AgentEvent` rows, a shape this service owns and keeps stable | You, and any UI or report |
| `transcript_entries` | The CLI's own JSONL transcript, mirrored via the SDK's `SessionStore` | The CLI, to **resume** a conversation |

They are not alternatives. The first is queryable but the CLI cannot resume from
it; the second makes a session survive a restart but is an **internal SDK format
that this service never parses** and neither should you.

**What is NOT stored, on purpose:**

- **Nothing while the database is down.** Records are queued and dropped rather
  than blocking a turn; `stream_event` frames go first. A turn never fails because
  persistence failed.
- **No credentials.** `AGENT_SERVICE_DATABASE_URL` is removed from the process
  environment at startup, because the agent's subprocess inherits that environment
  and has `Bash`. `ANTHROPIC_API_KEY` **cannot** be hidden this way — the
  subprocess authenticates with it.
- **Nothing is ever deleted.** Retention is yours.

**`sessions.total_cost_usd` is a floor, not the figure.** It mirrors the SDK's
running total, which an interrupted turn does not move. Do not build a spend
report on it.

## Web console

A browser client for everything above, at `../../common/web/`. Two files, no build
step, no dependencies beyond the standard library.

```bash
uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8000   # the service
python ../common/web/serve.py                                        # the console
# -> http://127.0.0.1:8080/
```

`serve.py` serves the page **and proxies the API**, so the browser sees a single
origin. Pass `--target` / `--port` to point it elsewhere.

**Why a proxy rather than CORS on the service.** A page on any other origin can
issue requests but cannot read the responses, so the console has to be same-origin
to work at all. The two ways there are a `CORSMiddleware` on the service or a
proxy in front of it — and this service has no auth by default and an unconfined
`Bash` tool, so widening its origin policy for a development page is not a trade
to make quietly. The proxy leaves `src/` untouched and binds `127.0.0.1` only.

What it does: **Sessions** (create with options, list, PATCH model/permission
mode, delete); **Turns** streamed over SSE with **Abort** (drops the connection,
exercising the service's own disconnect path) and **Interrupt** (a real control
request); **Chat / Events**, the same stream rendered as a conversation view or as
the raw `AgentEvent` log, both always populated so switching mid-turn loses
nothing; **One-shot**; **History**, the stored transcript and run routes, which
answer 404 with `type: …/persistence-disabled` when there is no database;
**OpenAPI**, the route list plus an ad-hoc request builder.

FastAPI's own `/docs` is still there and is better for schema detail. What it
cannot do is stream: both streaming routes are `POST` with a JSON body, so
`EventSource` is unusable and Swagger's try-it will sit on a turn until it ends.

**It is a development tool.** Not served by the service, not covered by tests, and
the conversation is lost on reload.
[Plan 6](../../../docs/plans.md) describes the shape a real console would take and
the two blockers in front of it.

## Deploying to another machine

[`../../../docs/deploy-remote.md`](../../../docs/deploy-remote.md) — SSH context,
or an archive if you have no key. Short version: build on the far side, because
the build context is 2.1 MB and the image is 753 MB.
