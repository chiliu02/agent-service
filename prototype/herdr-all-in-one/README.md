# herdr-all-in-one: one image, four agent CLIs, Herdr, and agent-service's core API

**A prototype, and separate from agent-service.** No file outside this directory
uses it, `ci.py` and `images.py` do not know it exists, it has no `pyproject.toml`
and it imports nothing from `impl/`. It is never tagged, released or pushed.
It is stdlib Python and shell, plus psycopg in its own venv for the database.

**The question it answers (user, 2026-11-16):** can one container, built on Agent
Harness's toolchain image, run Claude Code, Codex, Gemini CLI and Pi under Herdr,
and serve **what Agent Harness calls today** through Herdr's socket API? Live
output is watched by a Herdr client over SSH instead of an SSE stream.

**Answer: yes, for all four CLIs**, with the limits listed below. Measured
2026-11-16 against Herdr 0.9.5, Claude Code 2.1.325, Codex 0.146.0, Gemini CLI
0.66.0 and Pi 1.4.0, first against an in-container stub model and then
**against the real provider APIs** (see "With real models" below).

## What is in it

| File | What it is |
|---|---|
| `Dockerfile` | `FROM localhost:5000/agent-harness-toolchain:0.1.0`, plus `openssh-server`, `tini` and `ripgrep`. Herdr 0.9.5 is pinned by sha256, and the four CLIs are pinned by version. Herdr's own `integration install` is run for claude, codex and pi. Runs as uid 1000 (`ubuntu`) |
| `entrypoint.sh` | Writes each CLI's config (Codex provider and hook trust, Pi `models.json`, Gemini `settings.json`, Herdr with update and manifest checks off). Starts the stub model, then a **non-root sshd** on 2222, then `herdr server`, then the shim on 8080 |
| `make_openapi.py`, `openapi.json` | **This prototype's own OpenAPI document**, `0.34.0-herdr.1`. The generator reads agent-service's core document `0.34.0-snapshot` (read only) and applies the changes listed under "The document" below. `--check` fails when `openapi.json` is stale |
| `shim.py` | Serves **`openapi.json`'s routes and shapes**, and the document itself at `/openapi.json`, using only Herdr's socket: `workspace.create`, `agent.start`, `agent.prompt` (with server-side wait), `agent.wait`, `agent.get`, `agent.read`, `agent.send_keys`, `pane.close`, `workspace.close`, `ping` |
| `gemini_session_hook.py` | A Gemini `SessionStart` hook. Herdr has no Gemini integration, so this reports the session id and transcript path (see "The Gemini gap" below) |
| `usage.py` | Per-turn `usage`, `model_usage`, `cost_usd` and `context_usage`, read from each CLI's own transcript (see "Usage and context" below) |
| `store.py` | Writes `sessions`, `runs`, `events` and `transcript_entries` in **agent-service's own schema** (Alembic `d3f9a0c15e27`). Optional: without `AGENT_SERVICE_DATABASE_URL` the shim keeps its ledger in memory |
| `stub_llm.py` | Answers in Anthropic Messages, OpenAI Responses and Gemini shapes, and forwards nothing. Each reply is `PROTO-REPLY-<n> <prompt words>` |
| `probe.py` | Drives the shim through Harness's relay sequence, once per CLI |
| `check_openapi.py` | Checks every answer against `openapi.json`: the status is declared for that operation and the body validates against its schema. Takes turns, so run it against the stub |
| `run-local.sh` | Builds the image, starts Postgres with `spec/database/agent-service-d3f9a0c15e27.sql` applied unchanged (the file is only read), starts the container, and seeds four worktrees |
| `.gitattributes` | LF for everything: a CRLF shebang makes `tini` fail with "No such file or directory" |

```sh
ssh-keygen -t ed25519 -N '' -f ./id_proto
./run-local.sh ./id_proto.pub                # API on :18480, ssh on :12222
python probe.py http://localhost:18480       # all four CLIs
ssh -i ./id_proto -p 12222 ubuntu@localhost  # then: herdr      (the full TUI, same server)
docker exec -it herdr-proto-db psql -U postgres agent_service   # the saved rows
```

**Real models.** `PROTO_STUB=0 ./run-local.sh …` passes `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` and `GEMINI_API_KEY` through by name from the calling shell.
Values are never put in the image or a file. With no `*_BASE_URL` set, each CLI
calls its vendor directly, and Pi uses the Anthropic key (`PROTO_PI_MODEL`,
default `claude-sonnet-4-5`). For agent-gateway, also set `ANTHROPIC_BASE_URL`,
`OPENAI_BASE_URL` and `GOOGLE_GEMINI_BASE_URL`. **That route has not been
run**, because no agent-gateway was deployed locally.

## Results against what Harness calls today

Harness's relay calls eight operations (`OutpostRelay`). Probe run 7, after the
fixes in the next section. **17 pass, 0 fail, 0 gaps for each CLI:**

| Harness call | Route | claude | codex | gemini | pi |
|---|---|---|---|---|---|
| `answers` | `GET /v1/deployment` | ✅ | ✅ | ✅ | ✅ |
| `open` | `POST /v1/sessions` | ✅ 6–8 s | ✅ | ✅ | ✅ |
| `turn` | `POST .../messages/stream` | **501**, as designed | 501 | 501 | 501 |
| `turn` (instead) | `POST .../messages` with `run_id` | ✅ reply read from the transcript | ✅ from the transcript | ✅ from the transcript | ✅ from the transcript |
| `run` | `GET /v1/runs/{run_id}` | ✅ `ended` | ✅ | ✅ | ✅ |
| `transcript` | `GET .../transcript` | ✅ `user`, `assistant`, `result` | ✅ | ✅ | ✅ |
| duplicate `run_id` | `409 .../run-id-in-use` | ✅ | ✅ | ✅ | ✅ |
| `interrupt` | `POST .../interrupt` (Esc via `agent.send_keys`) | ✅ `stop_kind=interrupted` | ✅ | ✅ | ✅ |
| `close` | `DELETE /v1/sessions/{sid}` | ✅ | ✅ | ✅ | ✅ |
| `resume` | `options.resume` = `sdk_session_id` | ✅ | ✅ | ✅ (via the hook below) | ✅ |
| `freeTokens` | `context_usage` → `Free space` | ✅ of 200 000 (table) | ✅ of 258 400 (**from the rollout**) | ✅ of 1 048 576 (table) | ✅ of 200 000 (table) |
| usage | `RunResponse.usage`, `model_usage` | ✅ | ✅ | ✅ | ✅, **with `turn_cost_usd`** |
| `token_usage` | the spec's five counters, one convention | ✅ | ✅ | ✅ | ✅ |
| `agent_id` | `SessionRecord.agent_id`, `sessions.agent_id`, `transcript_entries.agent_id` | ✅ | ✅ | ✅ | ✅ |
| persistence | rows in `transcript_entries`, `runs`, `events` | ✅ | ✅ | ✅ | ✅ |
| after a restart | `GET /v1/runs/{run_id}` from Postgres | ✅ `ended`, with result and usage | ✅ | ✅ | ✅ |
| one agent per worktree | second `POST /v1/sessions` on the same `cwd` | ✅ 409 | ✅ | ✅ | ✅ |

**SSH (measured):**

- A key logs in as uid 1000 and sees the **same** server: the agent the API
  started appears in `herdr agent list`.
- `herdr remote-api-bridge` over SSH (what `herdr --remote` spawns) answers
  `ping` with protocol 22.
- Root login and password login are refused.
- `herdr agent attach` needs a TTY (`ssh -t`).
- **Not run here:** the interactive `herdr --remote` TUI from a workstation,
  because this session has no terminal.

## What it took, and what each fix says about Herdr

| Symptom | Cause | Fix in this prototype | What it says |
|---|---|---|---|
| Claude pane `blocked` at start | Claude's "Detected a custom API key — use it?" dialog | Pre-approve the key in `.claude.json` `customApiKeyResponses`, beside `hasTrustDialogAccepted` | **Herdr got it right**: `live_blocked_form` matched |
| Codex turn refused, `agent_blocked` | "Update available 0.146.0 → 0.169.0" dialog | `check_for_update_on_startup = false` | Herdr got it right. `agent.prompt` refuses a blocked agent instead of typing into the dialog |
| Codex turn failed, but Herdr said **`idle`** | "Hooks need review", caused by **Herdr's own integration hook** | Pre-seed `[hooks.state."…session_start:0:0"] trusted_hash` | **Herdr got it wrong**, with `rule: none`. That is the failure `herdr-tui.md` §4 predicts: an unknown dialog reads as `idle`. The adapter has to make every first-run dialog impossible, not rely on detection |
| Session reported `idle` before the dialog drew | `agent.start` for codex returns `launch_pending` | Wait for `interactive_ready` and no `launch_pending`, then 2 s of quiet | Readiness needs two fields, not the status |
| Gemini turn took ~117 s | The stub answered Gemini's model-router call with prose. The router wants JSON and retried 5 times with backoff | The stub answers JSON when `responseMimeType` asks for it | Herdr was **right** throughout: the screen said "This is taking a bit longer" |
| Reply text missing or wrong | The socket gives screen text only. Box drawing, status lines and the echoed prompt mix with the reply | Read the agent's **own transcript**, found from the session id Herdr's integration reports on `agent.get` (`agent_session.kind = "id"`), from the byte offset at turn start. Fall back to a screen diff | The socket alone yields a lossy reply. The id it reports is what makes the transcript reachable |

## With real models (2026-11-16)

**17 of 17 for each CLI against the vendors' own APIs**, with keys checked
against each provider first (HTTP 200 on each `/models`). Every reply is
`PROTO-REPLY hello` and every resume is `PROTO-REPLY resumed`, both as asked:

| | Claude Code | Codex | Gemini CLI | Pi |
|---|---|---|---|---|
| Model that ran (from its transcript) | `claude-opus-5-5`, the CLI's default | `gpt-5` | `gemini-3.8-flash`, picked by Gemini's router | `claude-sonnet-4-5` |
| First turn | 4.8 s | 7.2 s | 10.8 s | 20.1 s |
| `token_usage` (in / out / cache read / cache write / reasoning) | 2 / 13 / 0 / **16 812** / 0 | 8 704 / 201 / 0 / 0 / **128** | 4 533 / 70 / 0 / null / **65** | 10 / 53 / 0 / 1 573 / **41** |
| `context_usage` free | 183 186 of 200 000 | 249 696 of **258 400** | 1 044 043 of 1 048 576 | 198 417 of 200 000 |
| `turn_cost_usd` | null | null | null | **0.006724** |
| Interrupt, resume, transcript rows saved | ✅ ✅ 31 | ✅ ✅ 13 | ✅ ✅ 7 | ✅ ✅ 6 |

What the real run showed that the stub could not:

- **Claude's own prompt is about 16.8k tokens, and it goes to the cache.**
  `input_tokens: 2` beside `cache_creation_input_tokens: 16812`. A reader that
  ignores the cache counters is off by four orders of magnitude, which is why
  `token_usage` uses one convention.
- **`model_usage` names the model that ran, not the one asked for.** Gemini's
  router chose `gemini-3.8-flash`. No `model` was sent for Claude, so the CLI
  default `claude-opus-5-5` ran, which costs the most of the four. A Harness
  session would send `model`.
- **Reasoning counts are real on three CLIs**, Pi included: 41 on a
  `claude-sonnet-4-5` turn. Pi writes the counter only when the model thinks.
- **An interrupted turn's `result` was screen junk** on Codex and Pi: the CLI's
  "interrupted" notice, or Pi's banner. When the transcript has no reply, the
  result is now `null` (`events`: `assistant` subtype `none`).
- **No new dialog appeared with a real key.** The pre-seeded trust, API-key
  approval, update check and hook trust were enough on every CLI.

## The Gemini gap, and why it is not fixed through the socket

**Herdr 0.9.5 keeps no agent session for Gemini, however it is reported.**
`pane.report_agent_session` and `pane.report_agent` both answer `{"type":"ok"}`
for a Gemini pane, and `agent.get` still shows no `agent_session` (measured,
with source `proto:gemini` and with `herdr:gemini`). Herdr keeps a session only
for the agents it has built-in session support for.

**So the session comes from Gemini itself.** Gemini CLI 0.66.0 runs a
`SessionStart` hook (`hooksConfig.enabled`, user-level `settings.json`), and its
input carries `session_id` and `transcript_path`. The hook still sends the
report to Herdr, which is harmless and would work if a later Herdr kept it. It
also writes `/tmp/proto-agent-sessions/<pane>.json`, which the shim reads. With
that in place, resume works by id, and the reply is read from Gemini's chat
JSONL (`~/.gemini/tmp/<worktree>/chats/session-*.jsonl`), not from the screen.

**On resume, Gemini's hook reports a path that does not exist.** It names the
file for the new start time (`session-…T07-41-<id8>.jsonl`), while Gemini
appends to the original file (`…T07-40-<id8>.jsonl`). The shim uses the reported
path only when the file exists. Otherwise it takes the newest
`session-*-<first 8 of the id>.jsonl`.

**This is the one place the prototype is not socket-only for identity.** It is
the same kind of data Herdr's own integrations use for the other three CLIs: the
agent's own hook, reporting its own session.

## Usage and context: from each CLI's own transcript

**Herdr's socket carries no usage at all. Every CLI writes it per model call in
its own session file**, so `usage.py` reads the lines written since the turn's
starting byte offset:

| CLI | Record | Per turn | Context window |
|---|---|---|---|
| Claude | `type: assistant`, `message.usage`. Records repeat per `message.id`, so the last one per id counts | sum | not recorded, so a table: 200 000 |
| Codex | `payload.type: token_count`. `total_token_usage` is cumulative | difference across the turn | **`model_context_window`**, the only CLI that records it |
| Pi | `message.role: assistant`, `message.usage`, **with `cost`** | sum, plus `cost.total` | table |
| Gemini | `type: gemini`, `tokens` (input, output, cached, thoughts, tool) | sum; `thoughts` counted as output | table: 1 048 576 |

- **Usage is normalised** to `input_tokens`, `output_tokens`,
  `cache_read_input_tokens` and `cache_creation_input_tokens`, so a reader sums
  the same keys whatever the CLI. `model_usage` is keyed by the model the
  transcript names, which is the model that actually ran. That matters when a
  CLI substitutes one.
- **Context in use is the last call's prompt**: input plus cache for Claude and
  Pi, `last_token_usage.input_tokens` for Codex, `tokens.input` for Gemini.
  `context_usage.categories` has `Used` and `Free space`, which is the category
  Harness's `freeTokens` reads.
- **The windows table is a guess for three of the four CLIs.** Override it with
  `PROTO_CONTEXT_WINDOWS`, a JSON map from model-name prefix to tokens. A
  1M-context Claude model needs an entry.
- **Cost is reported only by Pi.** The other three record tokens, not prices, so
  `reports_cost_usd` is true only when the container's CLI is pi. Pricing the
  rest needs a rate table, which is Harness's (`ModelRate`) and not the agent's.
- **`token_usage` uses ONE convention for all four CLIs**, which no pair of the
  separate builds manages (`capability-divergence.md`, the `token_usage` table).
  `input_tokens` **excludes** the cache counts, so
  `input + cache_read + cache_write` is the prompt total whichever CLI ran.
  `output_tokens` **includes** reasoning. `/v1/deployment` says so with
  `behaviour.token_usage_input_includes_cache: false`.
- **A counter a CLI does not record stays `null`, never `0`:**

  | | claude | codex | gemini | pi |
  |---|---|---|---|---|
  | `cache_write_tokens` | `cache_creation_input_tokens` | `cache_write_input_tokens` | **null**, no counter | `cacheWrite` |
  | `reasoning_output_tokens` | `output_tokens_details.thinking_tokens` | `reasoning_output_tokens` | `tokens.thoughts` | `reasoning`, **only when the model thought**, so `null` on a turn that did not think (measured: 41 on a real claude-sonnet-4-5 turn) |

  So the Claude and Gemini cells differ from the SDK builds. The transcript
  records counters that the SDK and the CLI's JSON stream drop.
- **Checked with real models**: see "With real models" above.

## Saving to agent-service's database

**The schema is agent-service's, unchanged.** `run-local.sh` applies
`spec/database/agent-service-d3f9a0c15e27.sql` to a fresh Postgres, and the shim
writes through `AGENT_SERVICE_DATABASE_URL`, the variable the builds use:

| Table | What the prototype writes |
|---|---|
| `sessions` | one row per shim session: status, model as the transcript names it, `total_cost_usd` (pi), `total_turns`, **`agent_id`** |
| `runs` | one row per turn: prompt, `result_text`, `usage`, `model_usage`, `cost_usd`, `interrupted`, `timed_out`, `outcome_missing` |
| `events` | the run's `StoredEvent`s: `user`, `assistant` (subtype `transcript` or `screen`), `result`, `system/blocked` |
| `transcript_entries` | **the CLI's own transcript, line by line, verbatim** in `entry`. `session_key` is `<kind>-<worktree basename>/<agent session id>`. `uuid` is the record's own `uuid` or `id`, or `o<byte offset>` (Codex has neither). The unique `(session_key, uuid)` index makes a resync idempotent |

- **Synced after every turn and at close**, from the last byte copied. Measured
  after one probe pass: 96 rows across the four keys, matching the files.
- **`GET /v1/proto/agent-transcript/{sid}`** (prototype-only) returns the saved
  rows, so the agent's native record can be read without the container.
- **What survives a restart:** `GET /v1/runs/{run_id}` and
  `GET .../transcript` fall back to the database. A run with no finish row reads
  `lost`, which Harness's read-back already treats as "not recoverable". A live
  session does not survive, because its Herdr pane does not.
- **A database failure never fails a turn.** It is logged, and the agent-transcript
  route reports it as `store_error`.
- **`agent_id` comes from the container's `AGENT_ID`**, the variable Harness
  sets on every container it starts. It is read unprefixed and as opaque text,
  and absent is a normal deployment, all as the builds do. It goes into
  `SessionRecord.agent_id`, `sessions.agent_id` and `transcript_entries.agent_id`.
  That last table has no foreign key to `sessions`, so it is stamped on its own.
  One container serves one Harness agent, so one value covers all four CLIs.
- **What is not done:** nothing is ever deleted. The builds own their DDL through
  Alembic in `impl/common/db`; this prototype only applies the dumped file.

## The document: agent-service's core, and seven changes

**Not an agent-service build, and not in `spec/`** (user, 2026-11-16). The
prototype has its own document, `openapi.json`, version `0.34.0-herdr.1`.
`make_openapi.py` writes it from agent-service's core document `0.34.0-snapshot`,
which it only reads. **It keeps the core's paths, schemas and payload shapes**,
so a client written against agent-service needs as little change as possible.
The shim serves it at `GET /openapi.json`, and `/v1/deployment` reports its
version as `service.spec.document_version`. The changes are listed in the
document itself, under `info.x-changes-from-core`:

1. **Streaming:** `POST …/messages/stream` and `POST /v1/query/stream` answer
   only 501, type `https://agent-service.invalid/problems/streaming-not-supported`.
   The paths stay, so a generated client still compiles.
2. **`Behaviour` gains six fields**, all required: `streaming` (always false),
   `live_output` (new schema `LiveOutput`: SSH port, user and Herdr version),
   `agent_kinds`, `default_agent_kind`, `token_usage_input_includes_cache`
   (always false) and `result_source`. **The payload keeps the core's four
   groups**: the top-level `herdr` block that this prototype used to have is
   gone.
3. **`RunOptions` gains `agent_kind`**: claude, codex, gemini, pi, or null.
4. **`SessionRecord` gains an optional `herdr`** (new schema `HerdrPane`):
   where the agent is, for a client attached over SSH.
5. **Statuses the core does not declare on these routes.** `POST /v1/sessions`
   adds 409 `worktree-in-use` and 502 `herdr`. `POST /v1/query` adds 409 and 429,
   because it opens a real session. `PATCH /v1/sessions/{sid}` adds 409
   `session-busy` and 502.
6. **`Problem` and `ValidationProblem` declare their `title` property.** They
   already require it. The core document's normaliser removes every `title` key,
   and this property went with them.
7. **Two prototype-only routes**, tagged `prototype`:
   `GET /v1/proto/agent-transcript/{sid}` and `GET /v1/proto/socket-log`.

**Checked against the running container** with `check_openapi.py` (stub model,
2026-11-16): **85 of 85.** For every call, the status is declared for that
operation and the body validates against its schema. The calls cover every
route, the 400, 404, 409, 422 and 501 answers, a turn, PATCH and a turn after it
on each CLI, and the one-shot. `probe.py` (Harness's sequence) still passes
17 of 17 on each CLI.

**Against agent-service's own conformance suite** (`spec/conformance`, all three
tiers, stub model). It is not this prototype's judge: it reads agent-service's
documents. It is the strictest outside check available, though:

| | Before the document (2026-11-16) | With it |
|---|---|---|
| Worktree lock on (as shipped) | 72 pass, 39 fail or error | **97 pass, 15 fail or error** |
| Worktree lock off (`PROTO_WORKTREE_LOCK=0`) | 78 pass, 33 | **103 pass, 9** |

The 9 that remain are **by design**, and none of them is a shape this document
gets wrong:

- **4 are streaming:** AS-8 and AS-26, and AS-35's two checks on the stream route.
  Here it answers 501.
- **4 are document identity.** AS-24 and two AS-31 checks look this
  implementation's document up in agent-service's `spec/`, where it is not, on
  purpose. AS-22 counts the dots in a version: `0.34.0-herdr.1` has three.
- **1 is the suite's probe table:** it has no entry for `include_raw`, which this
  prototype refuses for `true`.

**The lock costs 6 more**: the suite opens many sessions on the default
directory, and one agent per worktree refuses all but the first.

**The 17 skips:** 15 are boot gates, which need the image under test and are
not part of this prototype. The other 2 are no-database refusals, which the
suite skips when a database is configured. They were measured by hand instead,
with a second shim started without `AGENT_SERVICE_DATABASE_URL`: `/healthz` says
`database_configured: false`, and both history routes answer 404
`persistence-disabled`, naming the variable.

## The gaps, and what Harness would see

- **Cost is pi-only.** See "Usage and context" above.
- **`stop_kind` is `interrupted`, `timed_out` or `null`, never `end_turn`.** A
  settled screen state does not prove how a turn ended. `outcome_missing: true`
  says so. Exact turn ends need the agents' own `Stop` hooks (`herdr-tui.md`
  §10.4), which this prototype does not install.
- **Options carried per CLI.** `effort`, `setting_paths`, `max_turns` and
  `max_budget_usd` are refused (400, `unsupported-options`) for every CLI, and so
  are `system_prompt` as an object and `include_raw: true`. All are listed in
  `accepts.unsupported_options`. `include_partial_messages` is accepted and
  inert, because there is no stream for it to shape. Tool lists,
  `setting_sources`, MCP and `strict_mcp_config` are Claude-only.
- **Permission modes are each CLI's own.** Claude: `default`, `acceptEdits`,
  `plan`, `bypassPermissions`, `dontAsk`. Gemini: `default`, `auto_edit`, `yolo`,
  `plan` (`--approval-mode`). Codex and Pi have one mode each,
  `bypassPermissions`, which is what they already do. **An omitted mode is
  `default` on Claude and Gemini, and that mode asks**, so a tool call holds
  the pane `blocked` until someone answers over SSH. An unattended Harness worker
  should send a mode that does not ask.
- **`PATCH /v1/sessions/{sid}` restarts the TUI.** A running TUI's options are
  fixed at launch, so a new `model` or `permission_mode` closes the pane and
  starts the CLI again, resuming its own conversation. It takes as long as
  opening a session, and answers 409 during a turn. Measured on all four CLIs:
  the model reads back, and the next turn keeps the same `sdk_session_id`.
- **History needs the database**, as in agent-service. Without
  `AGENT_SERVICE_DATABASE_URL`, `GET .../transcript` and `GET /v1/runs/{id}`
  answer 404 `persistence-disabled`. **Harness's read-back of a long turn
  therefore needs the database.**
- **One container serves eight sessions** (`PROTO_MAX_SESSIONS`), because each
  is a live TUI. Sessions idle for an hour (`PROTO_IDLE_TTL_S`) are closed.
- **`blocked` mid-turn is not tested.** The stub never asks for a tool, so no
  permission dialog was raised. The shim records a `system/blocked` event and
  keeps waiting, so a human over SSH can answer it. That path was not run.

## What changes on Agent Harness's side

**The contract is `openapi.json`, the core document with the seven changes
above.** The core's paths and schemas are all still there, so a client generated
from the core still compiles, and everything else Harness reads keeps its shape.
Harness would need four changes:

1. **`turn`:** on `501 …/streaming-not-supported`, or when
   `behaviour.streaming` is false, send `POST …/messages` with the same `run_id`
   and `on_disconnect: continue`. Then use the **read-back path Harness already
   has**: `GET /v1/runs/{run_id}` until `ended`, plus the transcript. Harness's
   60 s `send` timeout lands in the `Unreachable` branch that already reads back,
   so a long turn needs no new code.
2. **`Builds.places` and `RunOptions.of`:** a row for `herdr-all-in-one`. Its
   brief is `AGENTS.md`, with `CLAUDE.md` = `@AGENTS.md`, and its skills
   directory depends on the CLI. Send none of `setting_sources` and
   `setting_paths`.
3. **Which CLI a session gets:** `PROTO_AGENT` on the container (no request
   change), or `options.agent_kind`, which this document adds to `RunOptions`.
   `accepts` and `behaviour` describe `default_agent_kind`'s CLI only.
4. **Credentials per CLI:** the container needs every CLI's gateway variable
   at once, not one `credentialVariable`.

## Container constraints observed

- **3.78 GB**, against the toolchain's 2.27 GB.
- **`seccomp=unconfined` for the whole container**, because Codex's sandbox
  needs it, plus `pids-limit 512`.
- **SSH is full control.** Anyone with the key can drive every pane, including
  the panes the API started. One key per container, and treat it as a shell.
- **Detection rules are frozen** (`manifest_check = false`). Turning the remote
  check on (tested) changed nothing today: Gemini's newest remote manifest is
  still `2026.06.10.1`.
