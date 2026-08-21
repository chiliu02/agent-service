# Deploying to a remote Linux Docker host

A runbook for getting this service onto another machine's Docker.

**Every command below is parameterised.** Set these once in the shell you are
working from and the rest is copy-paste:

```bash
REMOTE_USER=you                       # the account on the target machine
REMOTE_HOST=docker-host.example       # hostname or IP the target answers on
AGENT_ROOT=/home/$REMOTE_USER/agentspace/agent1
```

| | Value |
|---|---|
| Target | `$REMOTE_USER@$REMOTE_HOST`, Linux |
| Workspace (read-write) | `$AGENT_ROOT/wrk` |
| Reference (read-only) | `$AGENT_ROOT/ref` |
| Reference mount name | `ref` → `/reference/ref` |

Nothing about the shape depends on those values. For a second agent, repeat the
whole thing with `agent1` → `agent2` in `AGENT_ROOT` and a different published
port.

## Don't ship the image

Measured on this repo:

| | Size |
|---|---|
| Built image | **753 MB** |
| Docker build context (after `.dockerignore`) | **2.1 MB** |
| `git archive` of the source | **624 KB** |

So build on the far side. `docker save | docker load` moves 753 MB (roughly
400–500 MB gzipped — half the image is the SDK's bundled `claude` binary, which
compresses poorly) and buys nothing unless you need byte-identical layers.

**Check the architecture once.** This repo's daemon is `linux/amd64`. If the
target differs, add `--platform linux/amd64` to `docker build`, or build natively
there. Most x86 laptops and servers are amd64, so this is usually a no-op.

---

## Route A — SSH context (recommended, and the one to use repeatedly)

One-time setup, then every `docker` command can target the remote from here.

### A1. Key-based SSH (once per machine pair)

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519    # skip if you have a key
ssh-copy-id $REMOTE_USER@$REMOTE_HOST                  # asks for the password once
ssh $REMOTE_USER@$REMOTE_HOST 'echo ok; docker version --format "{{.Server.Version}}"'
```

Both must be run **interactively** — they prompt. In Claude Code, prefix with
`!` so they run in your terminal.

### A2. Create the context

```bash
docker context create remote --docker "host=ssh://$REMOTE_USER@$REMOTE_HOST"
docker --context remote info --format '{{.OperatingSystem}} / {{.Architecture}}'
```

### A3. Create the mount directories **before** building

```bash
ssh $REMOTE_USER@$REMOTE_HOST "mkdir -p $AGENT_ROOT/{wrk,ref}"
```

Not optional — see [Why the container may exit 3](#why-the-container-may-exit-3).

### A4. Build remotely

```bash
docker --context remote build -t agent-service .
```

Uploads the 2.1 MB build context, builds there. Roughly 45 s cold, seconds when
layers are cached.

### A5. Run it

```bash
docker --context remote run -d --name agent-service \
  -p 127.0.0.1:8000:8000 \
  -v $AGENT_ROOT/wrk:/workspace \
  -v $AGENT_ROOT/ref:/reference/ref:ro \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e AGENT_SERVICE_REFERENCE_DIRS='["/reference/ref"]' \
  -e GIT_AUTOCRLF=input -e GIT_FILEMODE=true \
  --init --stop-timeout 100 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --memory 1536m --pids-limit 512 \
  agent-service
```

---

## Route B — no SSH key: carry an archive

Everything runs on the target machine. Nothing here needs key auth.

### B1. Make the archive (on this machine)

```bash
git archive --format=tar.gz --prefix=agent-service/ -o temp/agent-service-src.tar.gz HEAD
```

~627 KB, 146 files, no `.venv`, no `.git`, no `.env`. It lands in `../temp`, which
is gitignored, so a stale archive can never be committed by accident.

**It archives `HEAD`, not your working tree** — commit first, or the copy you
carry across will be missing your latest edits. Re-run after any commit. Move it
by whatever means you have: `scp`, a USB stick, a shared folder.

### B2. On the target machine

```bash
mkdir -p $AGENT_ROOT/{wrk,ref}
tar xzf agent-service-src.tar.gz && cd agent-service
docker build -t agent-service .
```

Then the same `docker run` as [A5](#a5-run-it), without the `--context remote`.

---

## Verify

```bash
docker --context remote ps --filter name=agent-service
ssh $REMOTE_USER@$REMOTE_HOST 'curl -s localhost:8000/healthz; echo'
ssh $REMOTE_USER@$REMOTE_HOST 'curl -s localhost:8000/v1/capabilities' | python -m json.tool | head -20
```

`healthz` should report `"credentials_configured": true`. The mounts are proven
by the container having started at all — `require_mounts` refuses otherwise.

**The port is bound to `127.0.0.1` on the remote**, so it is not reachable from
this machine. That is deliberate: there is no authentication and the agent has
unconfined `Bash`. To use it from here, tunnel rather than republish:

```bash
ssh -N -L 8000:127.0.0.1:8000 $REMOTE_USER@$REMOTE_HOST
# then http://127.0.0.1:8000/docs works locally
```

The web console works over that tunnel too — `python impl/common/web/serve.py` on this
machine, pointing at the forwarded port.

---

## Updating after a code change

```bash
docker --context remote build -t agent-service .        # or Route B's archive
docker --context remote stop agent-service              # up to 100 s with live sessions
docker --context remote rm agent-service
# ... then the A5 run command again
```

`stop` genuinely can take a while: `stop_grace_period`/`--stop-timeout` is 100 s,
derived from a 30 s request drain plus a 60 s `close_all()` budget plus margin. A
stop with sessions mid-turn was measured at 42.4 s. An idle stop is ~3.4 s.

---

## Troubleshooting

### Why the container may exit 3

Two causes, both deliberate refusals rather than crashes:

1. **No credential.** Set `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`, or a
   `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY` provider flag).
2. **A mount is missing.** `require_mounts` defaults **true**, so the service
   refuses to start when `/workspace` is not on a mounted filesystem, or when an
   `AGENT_SERVICE_REFERENCE_DIRS` entry does not exist.

```bash
docker --context remote logs agent-service | tail -20
```

The message names the problem, the fix, and the escape hatch
(`AGENT_SERVICE_REQUIRE_MOUNTS=false`).

**Docker will not catch a bad path for you.** Measured: `-v`, `--mount
type=bind`, and compose's `create_host_path: false` all *create* a missing host
directory and start the container anyway. That is why the service checks
instead — and why `mkdir -p` comes before `run`.

### The reference directory is invisible to the agent

`/reference/ref` appears **twice** in the run command — as the mount target and
inside `AGENT_SERVICE_REFERENCE_DIRS`. If they disagree, the container now
refuses to start. Before `require_mounts` it started fine and the directory was
simply invisible to `Read`/`Glob`/`Grep` while `docker exec ls` showed the files.

### Two Linux-only settings that fail silently

`GIT_AUTOCRLF=input` and `GIT_FILEMODE=true` are in the A5 command for a reason.
The defaults are correct for a Windows host and wrong on Linux, and neither
complains: one rewrites the mounted repo's line endings into history on the
agent's first `git add -A`, the other hides real permission changes.

### `docker --context remote` hangs or asks for a password

Key auth is not set up — redo [A1](#a1-key-based-ssh-once-per-machine-pair).
`docker context rm remote` starts over.

### Nothing bounds memory unless you say so

`--memory 1536m --pids-limit 512` are in the run command deliberately. Measured:
~110 MiB and ~17 pids per session on a ~250 MiB warm baseline, so the default
`max_sessions` projects to ~1.1 GiB unbounded.

---

## Using compose instead

`compose.yaml` carries all of the above as configuration, and derives the mount
target and the env var from one `REFERENCE_NAME` so they cannot drift.

```bash
docker --context remote compose up -d --build --wait
```

Two cautions:

- **`.env` is interpolated locally, resolved remotely.** `WORKSPACE_HOST_PATH`
  and `REFERENCE_HOST_PATH` must be paths that exist on the *target*.
- **Use `--wait`.** Plain `up -d` reports `Started` and returns 0 for a container
  that has already exited 3.

Compose expresses exactly one reference mount. For several, use `docker run`
with repeated `-v` and a JSON array — see the README's *Without compose* section.
