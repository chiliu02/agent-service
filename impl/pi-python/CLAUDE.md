# impl/pi-python — working notes for Claude

**The fourth implementation, and it serves the specification.** The target is
**Pi** (`@earendil-works/pi-coding-agent`, MIT, Node), driven from Python by
spawning `pi --mode json` once per turn (`PI-11`). All thirteen `/v1` operations
are built, the shared core lost **zero** leaves, and the conformance suite's
document tier picked this build up with **no suite edit at all** — publishing a
document is the whole of what registering a fourth implementation costs.

**The image builds and the container tier passes**: 95/96 conformance tests in
both deployments, both boot gates exiting 3, and the endpoint-redirect check
green. It found two defects nothing free could have — read `PI-39` and `PI-40`
before trusting any part of this build that only unit tests cover.

`docs/pi-python-references.md` beside this file is the evidence and **the only
document this build's code may cite**.

**This build IS delivered, and this file said the opposite until 2026-09-18.**
It is in every release from `0.24.0`, its document ships in the tag, and
`agent-service-pi-python` images are pushed and announced — Agent Harness drives
`0.27.0` by digest against all three of its published providers. **A delivered
image freezes the document it was built against**, so a change that moves a
published value here needs a document version like anywhere else.

The sentence that used to stand here — *"no image is tagged, no release is cut,
and the consumer has been told nothing about this build"* — was true when the
build was new and was left behind by four releases. **It is recorded rather than
deleted because it is the failure mode this file is most prone to**: the notes
that describe a build's standing go stale silently, while the notes that describe
its code fail a test.

**Read `PI-11` before anything else.** This build is CLI-driven: every turn is
its own process, and interrupt is a process kill. Pi also offers a **JSONL RPC
mode** with correlated requests, a real `abort` and `get_session_stats`, and a
**TypeScript SDK**. Both were measured; neither is used. The upgrade path is
written down rather than implied.

**The platform's rules are one level up.** The boundary rule ("never write
outside this directory"), the Agent Harness channel, thread naming and the
escalation rule are in [`../../CLAUDE.md`](../../CLAUDE.md), and they outrank
anything here. So does its warning about the CI runner: `ci.py` lives at the
platform root and `../../docs/ci.md` is its reference.

**Paths below are relative to this directory** unless they start with `../`.

## Read before running anything

- **The whole investigation that produced this build cost 0.0209 USD**, across
  ten turns on three provider keys. That is not luck: every live run pinned a
  cheap model, capped its own wall clock, and suppressed the ambient config that
  would otherwise have inflated every prompt. Keep it that way — the spike for
  another build in this repository was estimated at "cents" and cost about 10.
- **Run the free probe first.** `spike/probe_pi_cli.py` needs no credential, no
  turn and no container, and a large fraction of what decides this build's shape
  is free: the flag catalogue, the RPC dispatch table, the keyless credential
  gate, agent-home containment, and the licence.
- **The probe verifies every flag it reports by invoking it**, and that is not
  decoration. Its first version scraped flag-shaped tokens out of `--help` prose
  and reported `--plan` as an option this agent has. It does not
  (`PI-22`) — and that wrong finding was published before it was caught.
- **Running the agent writes to `PI_CODING_AGENT_DIR`**, which this build always
  sets. Unset, it writes to `~/.pi` (`PI-05`). Skills additionally load from
  `~/.agents/skills/`, which no variable relocates — the image masks it and
  every invocation passes `--no-skills` (`PI-19`).

## Commands

```bash
uv run pytest                       # 213 tests, no agent, no key, no container
uv run pytest -n 4                  # ... what CI passes
uv run uvicorn agent_service.main:app

uv run python scripts/publish_document.py   # regenerate the OpenAPI snapshot
uv run --no-project python spike/probe_pi_cli.py   # free, needs node_modules
```

`uv run pytest -m live` takes real turns and **spends money**. Ask first.

## What is different about this target, in one place

Four things shape almost every decision in this tree:

1. **It is one agent in front of thirty-plus providers**, chosen per request.
   That is why `model_api` is `pi` and names no vendor (`PI-06`), why
   `endpoint_source` is a proxy rather than a base URL (`PI-07`), and why the
   usage object's own keys differ between providers *inside this one build*
   (`PI-34`) — a divergence no other build in this repository has.
2. **It reports cost, in USD, on every model call** (`PI-17`). Only one other
   build can. It is also why `max_budget_usd` is *refused* rather than enforced
   (`PI-26`): the figure arrives as the work completes, so enforcing it would
   mean discarding the answer the caller paid for.
3. **It has no sandbox and says so** (`PI-30`). The container is the entire
   boundary, `working_directory` confines nothing, and neither built-in shell is
   granted by default (`PI-24`).
4. **Its permission story is the thinnest of the four** (`PI-22`). One mode,
   `default`. `plan` is omitted rather than mapped onto something else.

## What is NOT built, and why

- **MCP** (`PI-27`). It works — a real stdio server was driven end to end — but
  through a separate npm extension whose entire tool surface is one *proxy*
  tool, so `allowed_tools` cannot govern an individual MCP tool. That is a
  design question, not a wiring job. `mcp_servers` and `strict_mcp_config` are
  refused with a 400, and `allow_mcp_servers` is false, so a caller is told
  before asking rather than after.
- **`effort`** (`PI-23`). The agent has a thinking dial; it is per *model*, and
  the field is a flat list meaning *delivered exactly*. This is the one place
  the build gives up a capability the target has, and the alternative worth
  revisiting is a specification change rather than an implementation one.
- **The preset OBJECT form of `system_prompt`** (`PI-20`), which is
  keep-and-add semantics. The object names a preset belonging to another agent,
  so there is nothing to keep. **The flag it would have used,
  `--append-system-prompt`, IS wired since 2026-09-16** — to `setting_paths`,
  where it carries the caller's named instruction files (`PI-59`). The flag was
  never the obstacle; the preset was.
- ~~**A DELIVERED image.**~~ **Superseded 2026-09-18** — images are tagged,
  pushed and announced, and have been since `0.24.0`. What has not changed is
  that **building or tagging one is the user's call every time**, and that a
  delivered image freezes the document it was built against.
- **Anything on a Linux HOST.** The image is Linux and the container tier passes
  on it — but every measurement in the references file was taken from a
  **Windows host** driving Docker Desktop. Two builds here have already lost real
  time to a platform assumption nobody checked.
