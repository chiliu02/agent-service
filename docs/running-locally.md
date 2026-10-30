# Running and verifying the three builds by hand

**Written 2026-08-14, after a session that got several things wrong out loud.**
This file exists so the same mistakes are not repeated: each section below is a
thing that was *claimed* before it was *checked*, and what the check actually
found. The corrections are the point of the document, not an appendix to it.

**The rule this file is really about: check before claiming.** Every wrong claim
below was cheap to verify and expensive to leave standing — one of them sat in a
commit message, one was told to a consumer, and one nearly went into the release
notes as a platform limitation.

---

## 1. `codex-python` runs on Windows. It always did

**The wrong claim:** *"codex-python cannot take a turn locally on Windows; its
bubblewrap sandbox is Linux-only, so the container is its home."*

**The evidence it was based on:** a `TransportClosedError` at `POST /v1/sessions`,
plus this repository's own note that the container needs `seccomp=unconfined`
because bubblewrap builds a user namespace. That is a real note about Linux and
says nothing about Windows.

**What is actually true.** OpenAI documents Codex CLI as a first-class Windows
platform with its own sandbox settings — a `windows` table with `elevated` and
`unelevated` modes, rather than the `workspace-write` / `danger-full-access`
vocabulary used on Linux and macOS. Bubblewrap is the **Linux** mechanism, not a
universal requirement. There is also a Codex CLI installed under
`%LOCALAPPDATA%\Programs\OpenAI\Codex`, which should have been the first clue.

**The real defect, which was ours** (`CX-55`): `Settings.codex_home` defaults to
the *relative* `./codex-home`. The service created it relative to its own working
directory and then passed the same relative string to the app-server — which
starts with `cwd` set to the **workspace**, resolves it there, finds nothing, and
exits:

```
Error: CODEX_HOME points to "codex-home", but that path does not exist
```

The SDK reports that as `TransportClosedError: Codex process closed stdout`,
naming neither the path nor the cause. The container never hit it because its
Dockerfile sets an absolute `CODEX_HOME` deliberately — so the bug looked
exactly like a platform limitation, which is how it was misread.

**Fixed by resolving the path.** Verified end to end afterwards: session created,
real turn taken, `result: "codex on windows works"`.

**The lesson:** an error that names no cause is a reason to find the cause, not a
licence to guess one. Three isolated checks — `login_api_key`, `thread_start`,
and the same call with the service's own env — all passed on Windows *before*
the conclusion was drawn, and each one contradicted it.

## 2. Docker was not "missing images". Docker was dead, and I killed it

**The wrong claim:** *"no local images, so the demo has to run locally rather
than in containers."*

**What happened.** `docker images … 2>/dev/null | grep agent-service` returned
nothing and the redirect swallowed the real error, which was that the engine was
unreachable. All nine images were present the whole time.

**Why the engine was unreachable.** The dev console was started on port **8081**,
which `versioning.md` documents as **Nexus**. Ports published by Docker are held
on the host by `com.docker.backend`, so "what is listening on 8081?" answered
with Docker's backend process — and a cleanup step force-killed it by PID.

**Two rules that follow, and they are cheap:**

- **Never choose a port this repository documents.** Taken: `8081` Nexus, `5000`
  registry, `3000` gitea, `8000`/`8001` the compose files. Use something far
  away — `879x` was used after this and collided with nothing.
- **Never kill by port. Kill by the PID you recorded when you started the
  process**, or by container name. `netstat` answers with whoever holds the
  socket, which on Windows is frequently not your process.

**And never let `2>/dev/null` decide a fact.** A suppressed error became a
conclusion about what existed.

## 3. The console was not broken. Six abandoned streams were

**The wrong claim:** *"the console has a streaming bug — frames arrive for curl
but not for the browser."*

**What it actually was.** A browser allows about six connections per origin, and
an SSE turn holds one for its whole duration. Test runs that stopped polling
without aborting left streams open; the seventh request then queued behind them
and took minutes to deliver its first frame — indistinguishable from a service
that has stopped responding.

**Measured, once the right thing was measured:** a raw `fetch` through the same
proxy returned headers at **1.7 s** and finished at **3.5 s**. The transport was
never slow.

**Fixed in the console** — `send` now aborts any stream still open before
starting another, because a user can do exactly what the test harness did.

**The lesson:** when a browser and curl disagree, suspect the browser's
*connection state* before the server. And reload the page between runs — a fresh
page has a fresh connection pool.

## 4. Running each build locally, without containers

All three work on Windows. `.env` in each build directory holds its key.

```bash
# claude-python
cd impl/claude-python
AGENT_SERVICE_REQUIRE_MOUNTS=false \
AGENT_SERVICE_WORKSPACE_DIR=<abs path> \
AGENT_SERVICE_DEFAULT_MODEL=claude-haiku-4-5 \
  uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8791

# codex-python  (CODEX_HOME must resolve from the WORKSPACE -- see 1)
cd impl/codex-python
AGENT_SERVICE_REQUIRE_MOUNTS=false AGENT_SERVICE_WORKSPACE_DIR=<abs path> \
  uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8792

# gemini-python  (the npm shim is a shell script; Windows needs the .cmd)
cd impl/gemini-python
AGENT_SERVICE_REQUIRE_MOUNTS=false AGENT_SERVICE_WORKSPACE_DIR=<abs path> \
AGENT_SERVICE_GEMINI_BINARY=<abs>/node_modules/.bin/gemini.cmd \
AGENT_SERVICE_MODEL=gemini-3.1-flash-lite AGENT_SERVICE_TURN_TIMEOUT_S=120 \
  uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8793
```

**`node_modules/.bin/gemini` is not executable on Windows** — it is the POSIX
shim and produces `WinError 193: %1 is not a valid Win32 application`. Use
`gemini.cmd`. The container is Linux and uses the plain one, which is why this
only bites locally.

**Running the codex service locally populates `codex-home/`** with 65 vendor
skill files. It is gitignored, and since 2026-08-14 `ci.py`'s `references` stage
polices only files **git tracks** — before that, merely having run the service
turned the build red on someone else's vendor code.

## 5. Running them in containers

The images are in the local registry and are the right way to exercise
`codex-python`'s sandbox, which is the thing the container settings exist for.

```bash
docker run -d --name demo-codex \
  --security-opt seccomp=unconfined --cap-drop ALL \
  -p 127.0.0.1:8791:8000 -e OPENAI_API_KEY=... \
  -v "C:/abs/workspace:/workspace" \
  host.docker.internal:5000/agent-service-codex-python:0.0.15

docker run -d --name demo-gemini --cap-drop ALL \
  -p 127.0.0.1:8792:8000 -e GEMINI_API_KEY=... \
  -e AGENT_SERVICE_MODEL=gemini-3.1-flash-lite \
  -v "C:/abs/workspace:/workspace" \
  host.docker.internal:5000/agent-service-gemini-python:0.0.4
```

**`seccomp=unconfined` is required for codex and not for gemini**, and that
asymmetry is deliberate and already argued in the codex compose file.

**Remove them by name** — `docker rm -f demo-codex demo-gemini` — never by port.

## 6. The console, and how to test it for nothing

```bash
uv run --no-project python impl/common/web/serve.py --target http://127.0.0.1:8792 --port 8795
```

**Debug against `impl/gemini-python/tests/fake_cli_agent.py` first.** It needs no
credential, spends nothing, and emits the real `stream-json` shapes — including
the delta framing that the live agent uses. Every console fix in this session was
found against it and only *confirmed* with paid turns. Point
`AGENT_SERVICE_GEMINI_BINARY` at a `.cmd` wrapper that runs it, and drive
prompts like `tools`, `hang`, `exit:41` to reach the branches.

**The prompts the fake agent understands** are listed in its own docstring; it is
driven by the prompt text rather than by flags.

## 7. What a live turn costs, and how to keep it small

**Ask before running a live set.** The gemini spike was estimated at "cents" and
cost about **10 USD** — not from prompt size but from turns that never
terminated.

- **Pin a cheap model**: `claude-haiku-4-5`, `gemini-3.1-flash-lite`. Codex has
  no cost figure at all, so keep those turns short and few.
- **Cap the wall clock**: `AGENT_SERVICE_TURN_TIMEOUT_S`. A turn that cannot
  finish is the expensive one.
- **Only `claude-python` reports cost.** `reports_cost_usd` is false on the other
  two, so their spend is invisible rather than zero — plan by turn count, not by
  a number you can read back.

**Measured here:** one `claude-haiku-4-5` turn was `$0.0239`, dominated by 18,901
cache-creation tokens rather than by the four-word prompt.

## 8. Checking a key before blaming the code

Both of these answer in one call and cost nothing:

```bash
curl -s -o /dev/null -w "%{http_code}" -H "x-goog-api-key: $KEY" \
  https://generativelanguage.googleapis.com/v1beta/models          # gemini
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" \
  https://api.openai.com/v1/models                                  # openai
```

A `401` from the provider is a credential problem and not a defect in this
repository. That check turned a "gemini is broken" hour into a one-line answer:
the key was of the wrong type entirely, reported as
`ACCESS_TOKEN_TYPE_UNSUPPORTED`.

**Never print a key.** Length and a four-character prefix are enough to tell two
credentials apart.

## 9. `host.docker.internal` is a HOSTS-FILE ENTRY on the host, and it goes stale

**2026-08-15: Nexus and the registry both looked dead from the host, and both were
healthy.** `curl http://host.docker.internal:8081/...` hung for the full timeout
and returned `000`; `docker ps` showed `agent-harness-nexus` *Up 5 hours
(healthy)* with `0.0.0.0:8081->8081/tcp`.

**The name resolves two completely different ways depending on who asks**, and only
one of them is maintained:

| Asked from | Resolved by | Stale? |
|---|---|---|
| inside a container | Docker's embedded DNS → the host gateway `192.168.65.254` | **no**, always current |
| the host itself | `C:\Windows\System32\drivers\etc\hosts`, written by Docker Desktop | **yes** — it is a snapshot of the LAN address |

That day the hosts file said `192.168.1.10` and the laptop's actual address was
`192.168.1.42`. **A moved DHCP lease.** Containers never noticed, which is why
the CI is green and the compose stack works while a `curl` from the host times out.

**RESTARTING DOCKER DESKTOP DOES NOT REWRITE IT.** That was claimed here and it is
wrong: the block is stamped `# Added by Docker Desktop`, so it looks managed, but
the entry survived two full restarts unchanged at `192.168.1.10`. Docker Desktop
evidently writes it at install or on some network event it does not see on a plain
restart. **The repair is an elevated edit of the file**, and it sticks — the manual
`192.168.1.42` then survived a further restart without being clobbered.

**The durable fix is a DHCP RESERVATION, and it is the user's** (done 2026-08-15).
The entry is a snapshot of an address; pinning the address is what stops the
snapshot from rotting, and it turns the hosts edit into a one-time correction
rather than a chore that returns with every lease.

**Verified after both, with the documented commands verbatim**: a push to
`host.docker.internal:5000` reports *Layer already exists* and leaves the digest
identical, the tags list answers over that name, and the released `1.3.0` jar
resolves through `host.docker.internal:8081` — the address `bundle.py` holds in
`NEXUS_BASE` — at the published sha1.

**One trap while checking any of this: do not measure during a restart.** A raw-IP
probe that had answered `200` minutes earlier returned `000`, and the firewall was
half-investigated before the cause turned out to be Docker restarting underneath
the measurement. Wait for `docker ps` to list the containers as *Up* before
believing a connection failure.

**Diagnose it with `nslookup host.docker.internal` against the hosts file, not with
a port check.** `nslookup` reports *Non-existent domain* — the entry is in the
hosts file, not in DNS — so read the hosts file and compare it to `ipconfig`.
`localhost:8081` and `127.0.0.1:8081` answering in 8 ms while the same port on
`host.docker.internal` times out is the signature.

**Do not "fix" it by rewriting the documented address.** `host.docker.internal` is
still the right name to bake into a pom or a push command, because the consumers of
those are containers. For a one-off from the host, route around it at the command
line instead — a deploy can take
`-DaltDeploymentRepository=<id>::http://localhost:8081/repository/<repo>/`, which
changes no published byte, and that is how `agent-service-database:1.3.0` was cut.

**This is the same failure Agent Harness described** in
`the-registry-address-belongs-to-the-reader-not-the-image.md` — an address baked
into a name, moving underneath everything that recorded it. Theirs renamed every
image on every Host at once; ours only broke a `curl`.
