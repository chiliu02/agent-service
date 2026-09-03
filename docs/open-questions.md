# Open Design Questions

Companion to [`design.md`](../impl/claude-python/docs/claude-python-references.md). Each item below is a call I made in the
spec that has a real trade-off and is cheap to reverse now, expensive later. We
work through them one at a time; record the outcome on the **Decision** line and
update `design.md` to match.

Status legend: `OPEN` — not yet discussed · `DECIDED` — settled, spec updated.

---

## Q1. System prompt default

**Status:** ✅ DECIDED — `None`, per-request override

**What it controls.** `ClaudeAgentOptions.system_prompt` accepts three shapes:

| Value | Effect |
|---|---|
| `None` | Bare agent. Minimal instruction; tools available but little guidance on how to use them. |
| `"a string"` | Your own system prompt, entirely replacing the default. |
| `{"type": "preset", "preset": "claude_code", "append": "..."}` | Loads Claude Code's own full system prompt — tool-use conventions, coding standards, defensive behaviors — optionally with your text appended. |
| `{"type": "file", "path": "..."}` | Loads a prompt from disk. |

This is the single biggest behavioral lever in the whole configuration. The same
prompt with the same tools produces noticeably different agent behavior across
these three.

**Spec currently says.** Default `None`, per-request override to anything else.

**Argument for `None` (current).** You see what the SDK does on its own, with
nothing hidden. When you later add a task-specific workflow you will be writing
your own system prompt anyway, so starting from bare is the honest baseline.

**Argument for the `claude_code` preset.** The SDK is marketed as "Claude Code as
a library" — the preset *is* the product. Defaulting to `None` means the first
thing you observe is an unrepresentative, under-instructed agent, and you may
misattribute its weaknesses to the SDK.

**Recommendation.** `None`, because the goal is understanding the SDK's parts
rather than getting the best out-of-box behavior — but this is close to a coin
flip and worth a deliberate choice.

**Decision (2026-07-31): `None`, as recommended — and this is what shipped.**
There is no `default_system_prompt` field on `Settings`; `options.py` reads
`req.system_prompt` per request and passes `None` through when it is omitted.
Recorded rather than chosen: the code has answered this since Plan 1, the
Decision line simply never caught up.

---

## Q2. Ambient configuration (`setting_sources`)

**Status:** ✅ DECIDED — `[]`, set explicitly on every call

**What it controls.** By default the SDK loads Claude Code's filesystem
configuration from `.claude/` in the working directory **and** `~/.claude/` —
which means your global `CLAUDE.md`, your installed skills, and your plugins would
apply to every request this service serves. `setting_sources` restricts which
sources load; `[]` loads none.

**Spec currently says.** Default `[]` (load nothing ambient), per-request override.

**Argument for `[]` (current).** A service should be reproducible. Silent
inheritance of a personal `~/.claude/CLAUDE.md` makes API responses depend on
machine state, which is confusing while learning and wrong in production.

**Argument for loading them.** Seeing how skills and `CLAUDE.md` actually reach
the agent is itself a thing worth learning, and it is currently invisible if the
default is off.

**Trap found by the spike** ([`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md) F8).
Setting `options.skills` while `setting_sources` is unset makes the SDK **silently
default `setting_sources` to `["user", "project"]`**, so the CLI can discover
installed skills. Choosing "no ambient config" therefore is *not* achieved by
leaving the field alone — it must be set explicitly, or enabling skills later
quietly reintroduces your `~/.claude` and the project's `.claude`.

Also unverified: whether `setting_sources=[]` (which emits `--setting-sources=`
with an empty value) is honoured by the CLI as "load nothing". Tracked as L4.

**Recommendation.** Keep `[]` as the default and set it **explicitly and always**,
and make `setting_sources` a first-class per-request option that shows up
prominently in `/docs` so it is easy to experiment with. Best of both.

**Decision (2026-07-31): `[]`, set explicitly on every call — as recommended,
and this is what shipped.** `default_setting_sources = []`, and `options.py`
passes `setting_sources=list(setting_sources)` unconditionally rather than
omitting the key, which is the "explicitly and always" half of the
recommendation. Pinned by `test_setting_sources_is_always_explicit`.

---

## Q3. The `raw` field on every event

**Status:** ✅ DECIDED — on by default, suppressible per request

**What it controls.** Each normalized `AgentEvent` carries a `raw` key holding the
complete dataclass-to-dict conversion of the underlying SDK message, alongside the
tidied `content` list.

**Spec currently says.** Included, on by default, suppressible by config flag.

**Cost.** Verbose. A run with a handful of tool calls could produce tens of KB of
JSON, and the interesting fields get buried.

**Benefit.** It is the fastest possible way to learn the real message shapes —
you read them off live responses instead of the docs, and nothing is lost to a
normalization bug.

**Alternatives.**
1. On by default, config flag to disable (current).
2. Off by default, opt in per request via `?include_raw=true`.
3. On for the blocking endpoint, off for SSE (where volume hurts most).

**Recommendation.** Option 1 now, flip to option 2 once the shapes are familiar.

**Decision (2026-07-31): option 1 — included, on by default, suppressible.**
`include_raw_events = True`, overridable per request via `options.include_raw`.
The recommendation's "flip to option 2 once the shapes are familiar" is NOT
taken and is not scheduled: `raw` is what makes an SDK upgrade's wire changes
visible, and it costs nothing when a caller opts out.

---

## Q4. Workspace pinning

**Status:** ✅ DECIDED — option 1, pin plus validated subdir

**What it controls.** `ClaudeAgentOptions.cwd` — where the agent starts. The spec
pins it to `./workspace`, with an optional validated `workspace_subdir` on each
request.

**Important caveat.** With `Bash` enabled this is **convenience, not containment**.
The agent starts in `./workspace` but can `cd` anywhere the service process can
reach. Treating the pin as a security boundary would be a mistake.

**Alternatives.**
1. Pin to `./workspace` + validated subdir (current).
2. Allow an absolute `cwd` per request, so you can point the agent at real
   projects on this machine.
3. Pin, and add a separate allowlist of project roots that requests may select.

**Recommendation.** Start with option 1. Option 2 becomes attractive the moment
you want the agent to work on an actual repository, and it is a small change —
but it also removes the last bit of friction in front of `Bash`, so it should be
a conscious step rather than a default.

**Decision (2026-07-31): option 1 — pin to the workspace root plus a validated
`workspace_subdir`.** Shipped: `options.py` calls
`resolve_workspace(settings, req.workspace_subdir)`. Option 2 (absolute `cwd`
per request) stays rejected for the reason given above — it removes the last
friction in front of `Bash`, and Q8's container boundary is what makes the pin
unnecessary for containment rather than what makes option 2 safe.

---

## Q5. Guardrails: turns, budget, timeout

**Status:** ✅ DECIDED — balanced defaults with hard caps ($2/$10, 30/200 turns,
600/1800 s)

**Spec currently says.** `max_turns=20`, `max_budget_usd=1.0`,
`request_timeout_s=600`. All three overridable per request (budget and turns
downward *and* upward, unless we decide to cap).

**Trade-off.** `max_budget_usd` is a hard stop enforced by the SDK. A genuinely
long agentic run — a multi-file refactor, a deep research task — will hit $1 and
terminate mid-work, which looks like a bug if you have forgotten the limit is
there. Too high, and an accidental loop is expensive.

**Sub-questions.**
- Is $1 per run the right starting ceiling?
- Should a request be allowed to raise the limit above the configured default, or
  only lower it?
- 20 turns: generous enough for exploratory tasks, or immediately limiting?
- 600s wall clock: interacts with the budget cap — whichever hits first wins.

**Measured cost, from the spike** ([`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md)):

| Run | Cost |
|---|---|
| Trivial one-file read, **cold cache** | **$0.157** |
| Same work, warm cache | $0.027 – $0.051 |

The default model turned out to be `claude-opus-5[1m]`, and ~23k tokens of system
prompt + tool definitions are written to cache on every cold start. That is a
**per-run floor almost independent of task size**.

**So `max_budget_usd = 1.0` buys about six cold runs.** Far tighter than intended
— a single real agentic task could exhaust it. The limit is not wrong, but it must
be set with this floor in mind, and it interacts directly with Q7: pinning a
cheaper default model moves the floor several-fold more than any budget tweak.

Also relevant: **prompt caching does most of the cost work**, so per-request option
variation that changes the cached prefix silently multiplies spend. An argument for
keeping the resolved options prefix as stable as possible across requests.

**Decision: balanced defaults with hard caps.** Each limit becomes two config
values — the default applied when a request says nothing, and a ceiling a request
may not exceed.

| Limit | Default | Hard cap | Config keys |
|---|---|---|---|
| Budget (USD, per run) | `2.00` | `10.00` | `default_max_budget_usd`, `max_allowed_budget_usd` |
| Turns | `30` | `200` | `default_max_turns`, `max_allowed_turns` |
| Wall clock (s) | `600` | `1800` | `default_request_timeout_s`, `max_allowed_timeout_s` |

Requests may set any value **up to** the cap — so a deliberately expensive run is
possible without editing config, while a runaway stays bounded. A request
exceeding a cap is a 400 naming the limit, not a silent clamp: silently running
something cheaper than asked would make results inexplicable.

At the Q7 default (`claude-sonnet-5`, ~$0.09 cold floor) a $2 budget is roughly
20× the cost of merely starting — enough headroom for real multi-step work while
still stopping a loop quickly.

**Reporting is part of the decision.** A budget or turn stop must be
distinguishable from a crash: surface `ResultMessage.subtype`, `stop_reason`, and
`terminal_reason` in the response, and set an explicit `limit_hit` field naming
which ceiling ended the run. The spike showed a normal completion carries
`terminal_reason: "completed"`, giving a clean baseline to compare against.

The three limits interact — whichever binds first wins — so all three, plus which
one fired, belong in the response and in the `runs` table.

---

## Q6. Service-level authentication

**Status:** ✅ DECIDED and **SHIPPED in 0.11.0** — a bearer token over `/v1`,
`AGENT_SERVICE_AUTH_TOKEN`, **optional and off by default**, with
`AGENT_SERVICE_REQUIRE_AUTH` to make it mandatory and `auth_required` published
on `/v1/deployment` so a caller knows before it sends. `/healthz` is
deliberately outside it: the container healthcheck reads it, and an
authenticated container whose healthcheck could not run would be permanently
unhealthy.

**This entry said "⏸ DEFERRED — no auth; `127.0.0.1` only" until 2026-08-14**,
which was true when written and had been false since 0.11.0. It is corrected
rather than rewritten, because the deferral is the reason the shape is what it
is. What is left is not a service question at all — a browser has nowhere safe
to keep a token that grants shell execution in that container, which is a
console design question and is recorded under dev-todo item 3.

**Worked up in full in
[`security-posture.md`](./security-posture.md) (2026-08-07)**, which answers
"what is production ready" as an ordered list and is the document to read before
building anything here. Three things from it that change how this question looks:
**authentication is third**, the first item is not in this service at all
(Studio's ADR-0017 network isolation, measured unbuilt), and **the largest
residual risk — prompt injection — is one no authentication reduces.**

Gates Plan 6, and now [Q17](#q17-how-should-an-llm-provider-endpoint-reach-the-sdk) too

**A second candidate client, added 2026-08-06.** This question is deferred specifically so it is designed against a real client rather than half-built against none, and the web console was the only candidate. Q17 is a second, and it wants something different: a console needs an origin and a session, while an endpoint passthrough needs per-caller identity strong enough to decide **whose credential is in play**. Designing against both is a better constraint set than either alone — and note Q17 records that auth is necessary there but not sufficient.

**What it controls.** Whether the HTTP API itself requires a credential. The spec
currently has none — anything that can reach the port gets an agent with `Bash`,
i.e. shell execution as the service user.

**Alternatives.**
1. No auth; document binding to `127.0.0.1` only (current).
2. Shared-secret header (`X-API-Key`) checked by a FastAPI dependency. ~15 lines,
   shows up in the OpenAPI spec as a security scheme.
3. No auth, but bind to localhost *in code* rather than by documentation, so it
   cannot be accidentally exposed by a stray `--host 0.0.0.0`.

**Recommendation.** Options 2 and 3 together are cheap and make the service safe
to leave running. Option 1 alone relies on you remembering the docs, which is the
kind of thing that goes wrong exactly once.

**Decision (2026-07-31, user): DEFERRED, and localhost-only is the answer for
now.** No authentication ships: no token, no TLS, bound to `127.0.0.1`. That is
adequate for the only deployment that exists — a single operator on one machine
— and inadequate for every deployment anyone has since proposed.

**This is the gate, and it is worth being explicit about what it blocks.** Plan
6 (web console) names authentication a hard prerequisite, and is not buildable
until this is answered. Revisit when it becomes real, not before — an auth scheme
designed against no client is a guess.

---

## Q7. Default model

**Status:** ✅ DECIDED — pin `claude-sonnet-5`

**What it controls.** `ClaudeAgentOptions.model`. The spec leaves it `None`, so
the SDK/CLI chooses.

**Argument for leaving it unset.** Fewer moving parts; you inherit whatever the
SDK considers current, and it keeps working across SDK upgrades.

**Argument for pinning.** Reproducibility — the same request gives comparable
behavior and cost over time. Pinning also makes the cost figures in responses
interpretable, since you know what rate applies. Candidate: `claude-opus-5`.

**What the spike revealed.** Leaving `model` unset does **not** get a modest
default: the CLI selected **`claude-opus-5[1m]`** — Opus 5 with the 1M context
window. That is the most expensive routine option, chosen by nobody, and it set
the $0.157 cold-run floor measured in Q5.

Every run also billed a second model: `claude-haiku-4-5` (~500 input tokens,
~$0.0006), used internally by the CLI. `model_usage` is therefore always a map,
and "which model ran this?" has no single answer.

This turns Q7 from a reproducibility question into the **primary cost lever**.
Pinning `claude-sonnet-5` or `claude-haiku-4-5` would cut the per-run floor
several-fold, since that floor is dominated by ~23k cache-creation tokens priced
at the chosen model's rate.

**Recommendation.** Pin an explicit default — and pin something cheaper than Opus
unless there is a reason not to. Suggested: `claude-sonnet-5` as the service
default with per-request override, so exploratory runs are affordable and the
expensive model is a deliberate choice. Report the resolved value in
`/v1/deployment` so it is never a mystery, and set Q5's budget against the
measured floor for whatever is chosen.

**Decision: `claude-sonnet-5`**, pinned explicitly in config, overridable per
request.

Rationale: ~$0.09 cold-run floor against Opus's measured $0.157 (~$0.06 while
intro pricing runs to 2026-08-31), with near-Opus quality on the coding and
agentic work this service is for. Opus stays one request field away for hard
tasks. Pinning also makes cost figures interpretable and run-to-run comparisons
meaningful, which an inherited default does not.

Note `claude-haiku-4-5` continues to appear in `model_usage` regardless — the CLI
uses it internally for auxiliary work.

---

## Q8. Mount mode: read-only vs. writable workspace

**Status:** DECIDED — two mounts (writable `/workspace` + read-only `/reference/*`)

**Context.** Deployment is a Linux container with a host directory bind-mounted as
the workspace (see [`deployment.md`](../impl/claude-python/docs/claude-python-references.md)). The mount can be writable
(`/workspace`) or read-only (`/workspace:ro`). This is a sharper version of Q4:
in a container the mount mode *is* the real boundary, where the `cwd` pin was not.

**What each mode permits.**

| | Writable | Read-only (`:ro`) |
|---|---|---|
| `Read`, `Glob`, `Grep` | Yes | Yes |
| `Write`, `Edit` | Yes | No — fails on every write |
| `git log` / `diff` / `status` | Yes | Mostly — see caveat |
| `git add` / `commit` / `stash` / `checkout` | Yes | No |
| Agent damages your working tree | Possible | Not possible |

**Read-only caveat.** Git is not purely a reader. `git status` writes index
metadata, `git log` may touch `.git` under some configurations, and anything
touching refs or the object store fails outright. A read-only mount gives a
*partially* working git, which can be more confusing than no git at all.

**Alternatives.**
1. **Writable.** Full capability; the agent can commit its work, which also gives
   you a natural review and undo mechanism (`git diff`, `git reset`). Risk: it can
   also `reset --hard`, delete branches, or rewrite history.
2. **Read-only.** The agent becomes an analysis tool. Zero risk to your files, at
   the cost of losing `Write`/`Edit`/`commit` and half of git.
3. **Writable, but only ever point it at a scratch clone.** Full capability, and
   the blast radius is a throwaway copy. Costs a `git clone` before each session.
4. **Two mounts:** a writable scratch directory plus a read-only mount of a
   reference repository the agent may consult but not modify.

**Interaction with the rest of the design.** If read-only is chosen, drop `Write`
and `Edit` from `default_allowed_tools` — otherwise the agent will repeatedly
attempt writes, fail, and burn turns and budget working around a wall it cannot
see. Whatever is decided here should be reflected in the tool defaults.

**Recommendation.** Option 3, at least at first: mount writable so you see the
agent's full capability including commits, but point it at a scratch clone rather
than a repository you care about. Move to a real repo once you have watched enough
runs to trust the guardrails.

**Decision: Option 4 — two mounts.** A writable scratch workspace plus one or more
read-only reference repositories.

| Mount | Mode | SDK mapping | Purpose |
|---|---|---|---|
| `/workspace` | read-write | `cwd` | Where the agent works: writes, edits, commits |
| `/reference/<name>` | read-only | entry in `add_dirs` | Real code the agent may read but never modify |

Full toolset stays enabled — `Write` and `Edit` are meaningful because `/workspace`
is writable — and code you care about is protected by the mount flag rather than by
trust.

> **Follow-up (2026-07-31).** This decides *what* the mounts are; nothing verified
> they exist, and both ways of getting it wrong were silent. See
> [Q14](#q14-verifying-the-mounts-are-actually-there). "One or more read-only
> reference repositories" is honoured by the code — `add_dirs` and
> `workspace_description()` iterate the whole list, with no cap — but
> `compose.yaml` expresses only **one**, derived from `REFERENCE_NAME` so the
> mount target and the env var cannot drift. Several requires `docker run`, which
> trades that drift-proofing for the count.

**Three consequences, all folded into `design.md` and `deployment.md`:**

1. **`add_dirs` is the enabling mechanism, and it is easy to miss.** The SDK scopes
   file access to `cwd` plus `ClaudeAgentOptions.add_dirs`. A mounted-but-unlisted
   directory is invisible to `Read` / `Glob` / `Grep`. Two mounts therefore require
   two config settings, not one.
2. **`cwd` is not caller-selectable.** It must be a writable location, so it is
   always `/workspace` (optionally a validated subdirectory). Reference mounts are
   read-only and can never be `cwd`.
3. **The agent must be *told* the reference mounts exist.** Mounting and
   allow-listing a directory does not make the agent look there — nothing in the
   prompt mentions it. This needs an explicit description injected into the system
   prompt. See Q9.

**Read-only git caveat, carried forward.** Git is not a pure reader: it writes
index metadata during `status`, and anything touching refs or the object store
fails outright on a `:ro` mount. Read-side inspection of a reference repo
(`log`, `show`, `diff` against committed state) generally works; expect
`status` to warn or fail. If full git behaviour on a reference repo turns out to
matter, the answer is a second *writable* clone, not relaxing the flag.

---

## Q9. Telling the agent what is mounted where

**Status:** ✅ DECIDED — generated description, on by default

**The problem.** After Q8 the container has a writable `/workspace` and one or more
read-only `/reference/<name>` directories, and `add_dirs` grants access to them.
None of that appears in the agent's prompt. Absent an explicit statement, the agent
has no reason to look outside its working directory, and will behave as though the
reference repositories do not exist. Worse, it may attempt to write to one, fail,
and spend turns working around a constraint nobody explained to it.

So the mount layout has to reach the model as *text*. The question is how.

**Alternatives.**

1. **Config-driven system prompt append.** The service generates a short block from
   the mount configuration and appends it to whatever system prompt is in effect:

   ```
   /workspace  — your working directory, read-write.
   /reference/acme-api — read-only reference copy of the acme-api repository.
                         You may read and search it; you cannot modify it.
   ```

   Always present, always accurate, zero caller effort. Costs a few dozen tokens
   per request and couples the prompt to deployment config.

2. **Caller's responsibility.** The service says nothing; whoever writes the
   request describes the layout in `system_prompt`. Keeps the service neutral, but
   is silently wrong whenever the caller forgets — the failure mode is an agent
   that quietly ignores half its inputs.

3. **A `CLAUDE.md` in the workspace.** Write the description into
   `/workspace/CLAUDE.md`. Idiomatic for Claude Code — but it only works if
   `setting_sources` loads project settings, which Q2 currently turns off. It also
   puts a service-managed file inside a directory the agent can edit.

4. **Expose it as a tool.** A `describe_workspace` custom tool the agent may call.
   Precise and demonstrates `@tool`, but the agent has to think to call it, and it
   is a poor fit for information needed before the first action.

**Interaction with other questions.** Option 1 is the only one that works
regardless of Q1 (system prompt default) and Q2 (`setting_sources`), because it
appends to whatever is in effect rather than depending on a particular
configuration. Option 3 is only viable if Q2 flips to loading project settings.

**Recommendation.** Option 1, generated from the same config that produces `cwd`
and `add_dirs` so the description cannot drift from reality. Make it suppressible
per request (`include_workspace_description: false`) so you can observe the
difference — watching the agent ignore a reference mount it was never told about is
a genuinely instructive experiment.

**Decision (2026-07-31): tell it, generated from the mounts, on by default —
and this is what shipped.** `include_workspace_description = true`, and
`options.workspace_description()` builds the text from `workspace_dir` and every
entry in `reference_dirs`, appending it to whatever system prompt the request
supplies (`_apply_description` handles the `None`, string and preset-with-append
shapes).

Generated rather than hand-written because the two must not drift: a mounted
directory the prompt does not mention is one the agent will not look in, which
is the failure this question was raised for. One line per reference directory,
so multiple mounts are described without anyone maintaining a list.

---

## Q10. Should the agent have database access?

**Status:** ✅ DECIDED — option 1, no database access

**Not to be confused with persistence.** Storing runs and transcripts (Part A) is
service-side and needs nothing from the agent. Q10 is the separate question of
whether the *agent* gets a tool to query Postgres during a run.

**Alternatives.**

1. **No database access.** The agent has the filesystem and web tools; the database
   is purely the service's business. Simplest, and removes the entire credential
   surface described below.
2. **In-process `@tool` + `create_sdk_mcp_server`.** A `sql_query` tool backed by a
   dedicated read-only pool with a statement timeout and row caps. The agent sends
   SQL text and receives rows; it never sees a connection string. Doubles as the
   worked example of custom tools, which is directly on the learning goal.
3. **External MCP server** (`npx` stdio or HTTP). Least code, but hands the
   connection string to a third-party process and adds a subprocess per session.

**The constraint that colours all of this.** With `Bash` enabled the agent can read
the service's environment, so a read-write `DATABASE_URL` there is effectively
agent-readable regardless of what role Part B uses. Mitigations exist (pop the
variable from `os.environ` after loading; separate roles) but none are watertight
while `Bash` is on. The honest position: **assume the Postgres instance is reachable
by the agent, and do not store anything in it the agent must never see.**

**Sub-question if enabled:** may the agent read the persistence tables — its own
transcripts, and other runs'? Self-inspection is genuinely interesting and is also
a leak path between runs. Suggested default: no.

**Recommendation.** Option 1 for now; the stated need is persistence, which does not
require it. Add option 2 later as a deliberate exercise in custom tools, when there
is real data worth querying.

**Decision (2026-07-31): option 1 — no database access, and the code already
enforces it.** `AGENT_SERVICE_DATABASE_URL` is **popped from `os.environ`** in
`get_settings()` precisely so the agent's subprocess cannot inherit it. That is
not tidiness and not a coincidence: the subprocess has `Bash`, so anything left
in the environment is readable by the agent.

The sub-question ("may the agent read its own transcripts?") is answered by the
same mechanism — no, because there is no credential to reach them with. If that
is ever wanted it needs a deliberate, separately-credentialed path, not the
removal of this one.

---

## Q11. Persistence scope and retention

**Status:** ✅ DECIDED — indefinite retention

**Answered:** there are now **two** retention surfaces, not one, and they need
separate policies because they have separate owners.

| | A.1 `events` (+ `raw`) | A.2 `transcript_entries` |
|---|---|---|
| Written by | this service, via the queue writer | the SDK, on its own schedule |
| Prunable by us | yes, it is our schema | yes, but only if we implement `SessionStore.delete` |
| Pruned today | **no** | **no** — and the SDK never deletes unless `delete` is implemented |

`delete` was deliberately left unimplemented in `db/session_store.py`: the SDK
probes for the method at runtime, so leaving it off keeps deletion an explicit
decision rather than something that quietly starts happening the moment a
retention window is configured.

`stream_event` rows are already load-shed under pressure (they are the first
thing the writer drops), which bounds the worst case but is not a retention
policy — it is a backpressure policy that happens to reduce volume.

**Still open:** the actual windows, and whether `raw` stays on by default (Q3).
Both want real volume data, which needs a live deployment rather than a guess.

**What to store.** The schema has three tables: `sessions`, `runs`, `events`. The
first two are small and unambiguous. `events` is the transcript, and its size is
dominated by two things:

- **The `raw` column** (full SDK message dump) — ties directly to Q3. If `raw`
  stays on by default, a busy run produces a lot of JSONB.
- **`stream_event` rows** (token-level deltas, only when
  `include_partial_messages` is set). High volume, and fully reconstructible from
  the assistant message that follows.

**Options.**

1. **Everything, including `raw` and stream events.** Maximum learning value —
   you can replay and inspect anything after the fact. Largest storage.
2. **Everything except `stream_event` rows.** Keeps full message-level transcripts,
   drops the token-delta noise. Probably the sweet spot.
3. **Metadata only** — `sessions` and `runs`, no `events`. Cost and outcome
   tracking without transcripts. Small, but loses the thing that makes this
   interesting.

**Retention.** Nothing currently deletes anything. Options: keep indefinitely (fine
at learning scale); a `DELETE FROM runs WHERE started_at < now() - interval 'N
days'` job; or retain `runs` forever and prune `events` on a shorter clock.

**Privacy note.** Transcripts contain whatever the agent read — including file
contents from the mounted repositories. The `events` table is as sensitive as the
most sensitive thing in `/workspace` or `/reference`. That matters for backups and
for Q10's sub-question.

**Recommendation.** Option 2, indefinite retention, revisit when the table gets
inconveniently large. Decide Q3 first — it determines whether `raw` is mostly
populated or mostly null.

**Decision (2026-07-31, user): indefinite retention — option 2, as
recommended.** No pruning ships, which is what the code already does by
omission: nothing deletes rows.

Recorded so the absence is a decision rather than an oversight. When it starts
to matter, `events` is the table to look at first and `stream_event` rows are
the first thing to drop — they are token deltas, reconstructible from the
assistant message that follows, and are already the first thing the writer
sheds under pressure (`db/writer.py`'s drop policy). `runs` and `sessions` are
small and low-frequency; keep them.

---

## Q12. `ClaudeAgentOptions.sandbox` — use the SDK's own sandboxing?

**Status:** ✅ DECIDED — not used; settled from the SDK source, not a probe
[`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md) F3

**What was found.** The SDK exposes a `sandbox` option that appears on no
documentation page we read. It is delivered to the CLI by merging into the
`--settings` JSON:

```
SandboxSettings:
  enabled, autoAllowBashIfSandboxed, excludedCommands,
  allowUnsandboxedCommands, network, ignoreViolations,
  enableWeakerNestedSandbox

SandboxNetworkConfig:
  allowedDomains, deniedDomains, allowManagedDomainsOnly,
  allowUnixSockets, allowAllUnixSockets, allowLocalBinding,
  allowMachLookup, httpProxyPort, socksProxyPort
```

**Why it could matter a great deal.** The design's security reasoning rests on the
container being the only boundary and `Bash` being unconstrained inside it. If
this delivers OS-level filesystem and network confinement, several earlier
conclusions get better:

- `Bash` stops being the thing every other decision works around.
- `autoAllowBashIfSandboxed` hints at a supported "sandboxed, therefore
  auto-approve" posture — possibly a better default than `dontAsk` + allowlist.
- `network.allowedDomains` would constrain egress at the agent level, which is
  finer-grained than the container-level restriction discussed in
  `deployment.md`.
- **`enableWeakerNestedSandbox`** implies sandbox-inside-a-container is an
  anticipated configuration — exactly our deployment.

**Why it is not a decision yet.** Three unknowns, all needing a live test:

1. Does it work on **Windows**? OS sandboxing is typically seatbelt (macOS) or
   bubblewrap/seccomp (Linux); a Windows no-op is plausible.
2. Does it work **nested inside a container**, and what does "weaker" cost?
3. It is **undocumented**, so it may be unstable across SDK versions and carries
   no compatibility promise.

**Recommendation.** Test it during implementation (L5) before deciding anything.
If it works in the container, revisit Q4, Q6, and the `deployment.md` egress
section — it is the kind of finding that simplifies several decisions at once. If
it does not, nothing changes; the container remains the boundary. **Do not depend
on it while it is undocumented** — treat it as defense in depth, never as the sole
control.

> **⚠️ Corrected (2026-07-31) — answered from the SDK source, not from a live
> probe.** L5 was authorised and turned out not to be needed for the first two
> unknowns: `claude_agent_sdk/types.py` now carries a full `SandboxSettings`
> docstring that settles them, and it also reverses this question's premise.
>
> 1. **Windows?** No. `enabled: Enable bash sandboxing (macOS/Linux only).
>    Default: False`. The plausible no-op is stated behaviour.
> 2. **Nested in a container?** Yes, on Linux, via
>    `enableWeakerNestedSandbox: Enable weaker sandbox for unprivileged Docker
>    environments (Linux only). **Reduces security.**` So the option this
>    question read as encouraging ("sandbox-inside-a-container is anticipated")
>    is the SDK flagging a downgrade, not endorsing the deployment.
> 3. **Undocumented?** No longer. It was undocumented at spike time; on the
>    pinned SDK 0.2.128 it has a docstring, an example, and named attributes.
>
> **The premise that actually breaks.** This question hoped `sandbox` would give
> OS-level filesystem and network confinement and thereby soften Q4, Q6 and the
> egress discussion. The docstring says the opposite, in bold:
>
> > **Important:** Filesystem and network restrictions are configured via
> > permission rules, not via these sandbox settings — Read deny rules, Edit
> > allow/deny rules, WebFetch allow/deny rules.
>
> `sandbox` confines **bash commands**, not the agent. `Bash` remains the thing
> every other decision works around, and none of Q4, Q6 or the egress position
> changes.
>
> **What is still unmeasured**, and is the only part a probe could add: whether
> `enabled` + `enableWeakerNestedSandbox` actually confines bash inside *this*
> container. Worth doing only if bash confinement specifically becomes the goal
> — and note the service has no way to set it today, since `RunOptions` does not
> expose `sandbox` and `options.py` never sets it.

**Decision (2026-07-31): not used. `sandbox` is narrower than this question
assumed, and does nothing on the platform this is developed on.**

---

## Q13. Scoped permission rules in `allowed_tools`?

**Status:** ✅ ANSWERED — **no, they are not enforced.** See
[`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md) L7.

**Result.** With `allowed_tools=["Bash(git status:*)"]` and
`permission_mode="dontAsk"`, the agent ran both `git status --short` *and*
`git log --oneline`. `permission_denials` was empty. The scoped entry behaved as a
grant of the entire `Bash` tool.

> **⚠️ Superseded (2026-07-26).** The `allowed_tools`-is-coarse finding below still
> holds, but the conclusion drawn from it — that `can_use_tool` becomes the
> service's policy layer — does not. Five live probes found `can_use_tool` never
> fires under any configuration this service actually uses; the `PreToolUse` hook
> is the mechanism that works. See `spike-findings.md`, "Permission enforcement —
> measured, not guessed".

**Consequence — the decision this forces.** `allowed_tools` is a coarse capability
switch: it cannot express which paths a tool may touch (L3) or which commands it
may run (L7). The only mechanism that sees actual tool input and can decide per
invocation is **`can_use_tool`**. It is therefore promoted from an optional extra
to **the service's primary policy layer**, and the spec's `default_allowed_tools`
should be understood as "which capabilities exist", never "what they may do".

`disallowed_tools` remains the way to remove a capability outright.

<details>
<summary>Original question, kept for context</summary>

**Status when raised:** OPEN — raised by the L3 result

**The problem it would solve.** L3 established that `allowed_tools=["Read"]`
approves *every* read at *any* path, and that neither `cwd` nor `add_dirs`
constrains where a tool may operate. Inside the container that is tolerable, but
it means the service has **no in-SDK way to say "read here, not there"** — for
instance to keep the agent out of `/reference` on a write, or to permit
`git status` while refusing `git push`.

**The hypothesis.** Claude Code's permission system supports scoped rules such as
`Bash(git status:*)` and `Read(./src/**)`. `ClaudeAgentOptions.allowed_tools` is a
`list[str]` that is passed through to the CLI, and the SDK's own skills logic
already writes entries in the scoped form `Skill(name)` — so the field plainly
accepts more than bare tool names.

**Unknown:** whether path/command scoping is honoured by the CLI when supplied
this way, and what the matching semantics are (glob? prefix? relative to `cwd`?).

**Why it matters.** If scoped rules work, the service gains a real,
declarative, per-request permission layer: pin writes to `/workspace`, allow a
safe subset of `git`, deny everything else — enforced by the agent runtime rather
than by hoping the mount catches it. It would meaningfully improve Q4, Q6, Q8, and
the `default_allowed_tools` design.

If they do not, the honest position is that **the mount and the container are the
only enforcement**, and the allowlist is a coarse capability switch.

**Test (L7).** Cheap: set `allowed_tools=["Bash(git status:*)"]`, ask the agent to
run `git status` and then `git log`, and see whether the second is denied and shows
up in `ResultMessage.permission_denials`.

**Recommendation.** Run L7 before finalizing tool defaults — it is one API call and
could reshape several decisions.

</details>

> **⚠️ Superseded (2026-07-26).** "Use `can_use_tool`" no longer holds — five live
> probes found it never fires under any configuration this service actually uses.
> See `spike-findings.md`, "Permission enforcement — measured, not guessed". The
> mechanism that actually works is the `PreToolUse` hook (`permission_enforcement=
> "hook"`).

**Decision: answered by L7 — scoping is not enforced; use `can_use_tool`.**

---

## Q14. Verifying the mounts are actually there

**Status:** ✅ DECIDED (2026-07-31) — verify at boot; `require_mounts` defaults
**true**, and the non-container run opts out.

**Context.** [Q8](#q8-mount-mode-read-only-vs-writable-workspace) decided *what*
the two mounts are. Nothing checked they exist. Both ways of getting it wrong were
silent:

- A missing `-v …:/workspace`. The `workspace_dir` validator calls
  `mkdir(parents=True, exist_ok=True)`, so the service created the directory
  itself, booted, reported healthy — and everything the agent wrote was discarded
  when the container stopped.
- An `AGENT_SERVICE_REFERENCE_DIRS` entry that does not match its mount target.
  `reference_dirs` was resolved and never checked, so the path was accepted and
  then invisible to `Read`/`Glob`/`Grep` while `docker exec ls` showed the files
  at the real path. This is the failure `compose.yaml` designs out by deriving
  both from one `REFERENCE_NAME`; typing them separately makes it representable
  again, which is exactly what the `docker run` path does.

**Docker will not do this for you — measured, and against expectation.** On
Docker Desktop for Windows:

| Mechanism | Missing host path |
|---|---|
| `-v host:/x` | creates it, container starts |
| `--mount type=bind,source=…` | creates it, container starts |
| compose `bind: {create_host_path: false}` | creates it, container starts |

`--mount` *is* stricter than `-v` on Linux Docker Engine. That difference does not
reach this platform, so a host-side guard was not available.

**Decision.** `verify_mounts()` mirrors `verify_credentials()` exactly — gated on
a `Settings` field, raised from the lifespan before `start_reaper()` and outside
the `try`, so uvicorn exits `STARTUP_FAILURE`. Measured against the built image:
`MissingMounts`, `Application startup failed. Exiting.`, **exit 3** — with a
message naming both the problem and the fix, and the escape hatch
(`AGENT_SERVICE_REQUIRE_MOUNTS=false`). Both mounted correctly → running,
`/healthz` ok.

**Why the two directories are checked differently.** `workspace_dir` must be
*under* a mount point; `Path.exists()` cannot answer the question, because
existing is precisely the state the bug produces. Bare `os.path.ismount(path)` is
too strict — `-v host:/data` with `AGENT_SERVICE_WORKSPACE_DIR=/data/ws` is a
legitimate layout — so the check walks up, stopping before the anchor: a
container's `/` is itself a mount, and counting it would make the check pass for
every path and quietly do nothing. A reference directory need only **exist**; the
service never creates one, so existence already separates a good config from a
typo, and demanding a mount point would reject naming a subdirectory of one.

**Sub-question, ANSWERED (2026-07-31, user): the code default is now `true`.**
It shipped `false` so a plain checkout would keep working. The cost was that the
guard shipped switched off and only `compose.yaml` turned it on, so a
hand-rolled `docker run` got none of it — and that is exactly the deployment
least likely to remember a flag. Inverted: the container gets the check for
free, and everything else opts out with
`AGENT_SERVICE_REQUIRE_MOUNTS=false`.

**The cost is real and is paid up front, not hidden.** `uv run uvicorn ...` on a
checkout now exits 3 until the opt-out is set, because `./workspace` is an
ordinary directory. `.env.example` carries it uncommented, the README quick
start says so, and the suite sets it via one session-scoped autouse fixture in
`conftest.py` rather than in fourteen modules.

**Auto-detection was considered and rejected.** Keying this off `/.dockerenv` or
`/proc/1/cgroup` would spare the checkout its opt-out, but detection that fails
inside a real container turns the guard silently off — which is precisely the
class of failure `verify_mounts` exists to remove. An explicit flag cannot fail
silently.

---

## Q15. Async runtime: asyncio service, anyio SDK

**Status:** ✅ DECIDED (2026-07-31) — no change; recorded because the evidence
now exists.

**Context.** The service is asyncio because FastAPI and uvicorn are. **The Claude
Agent SDK is anyio** — read from its installed source: `anyio.open_process`,
`TextReceiveStream`/`TextSendStream`, `anyio.Lock`, `anyio.CancelScope`. So every
call into the SDK crosses a runtime boundary, and the SDK's own `close()` comments
on where that bites.

**What the difference actually is.** Measured in one process
(`docs/conversations/learning-async-python.md` Part 14, probe
`spike/async/anyio_probe.py` — named rather than linked because that directory
is untracked, so the primer is not in a clone):

```
asyncio.timeout : ran 0.272s past a 0.05s deadline, raised=None
anyio scope     : exited after 0.064s, cancelled_caught=4, scope.cancel_called=True
```

asyncio delivers a cancellation **once** — swallow it and the deadline vanishes
silently. anyio treats a cancelled scope as a **state** and re-raises at every
checkpoint until you leave it. Structured concurrency also removes the
unsupervised-task class of bug entirely.

**What it would mean here.** Roughly half of `sessions.py`'s hardest code exists to
compensate for those two asyncio properties. Specifically: `_acquire_lock_now`'s
`asyncio.timeout(0)` trick is `lock.acquire_nowait()`; `_finalize_live_turn`'s
catch-log-return shape *is* `anyio.move_on_after` natively; and the
abandoned-turn problem — a generator holding `self._lock` with no task that will
ever release it — is much harder to produce under a task group.

**Why not to act on it.** The SDK's source records the trap in a half-migration:

> an anyio shield only defers cancellation that *originates from an anyio cancel
> scope*. A raw asyncio cancellation (`asyncio.wait_for` / `asyncio.timeout`
> firing, a bare `task.cancel()`, loop shutdown) is still delivered at the next
> await in here

So adopting anyio inside `sessions.py` while uvicorn still cancels in asyncio
terms buys the seam without the benefit. A whole-service move means leaving
FastAPI, which is not on the table.

**The question, stated narrowly.** Not "should we migrate" — no. It is whether any
of the three `sessions.py` simplifications above is worth doing *in asyncio terms*
now that we know what shape they want, and whether the boundary deserves a note in
`implementation-notes.md` at the call sites rather than only in the SDK's source.

**Decision (2026-07-31): no change, and this stays a note rather than a task.**
The three shapes are already correct in asyncio terms — `timeout(0)`,
catch-`TimeoutError`-and-return, and the aclose-first dance are each the right
construction for the runtime actually in use, and each is covered by tests and
by `implementation-notes.md`. Knowing that anyio expresses them more directly
does not make the asyncio versions wrong; it makes them *explicable*, which is
what Part 14 records. Reopen only if the service ever leaves FastAPI.

---

## Revisions from the container decision

Deciding on containerized deployment changed the premises of two earlier
questions. **Both have since been decided — Q4 as "pin plus validated subdir",
Q6 as the optional bearer token shipped in 0.11.0** — and this section is kept
because the premises it changed are what made those answers the right ones.
Corrected 2026-08-14; it read "both are still OPEN" long after neither was:

- **Q4 (workspace pinning).** The caveat that "the cwd pin is convenience, not
  containment" no longer applies — the container boundary is real. The pin drops
  to defense-in-depth, and allowing a caller-specified path *within the mount* is
  now low-risk. Q8 supersedes most of what Q4 was protecting against.
- **Q6 (service auth).** `Bash` now means a shell in a disposable container with
  only the mounted directory attached, not a shell as your user on your machine.
  The recommendation is unchanged (bind to `127.0.0.1` in code, plus a shared
  secret) but the consequence of getting it wrong is smaller.

---

## Q16. Does an unmigrated schema need its own problem document?

**Status:** ✅ DECIDED (2026-08-06) — **No.** A readiness check, not a new
`type`. Nothing shipped for this question; it closes a door.

**What it controls.** Whether `errors.to_problem` grows a branch — beside
`PersistenceDisabled`, the one non-default `type` in the module — for "the
database is configured but its schema was never created", so a history route
answers something specific instead of the fallthrough 500.

**Where it came from.** Covering the history routes for conformance turned up a
service pointed at a database with no tables: it boots, reports healthy, and
fails on the first history request. Migrations do not run on startup (a claim
`persistence.md` made for months and which was corrected the same day), and the
image carries no `migrations/`, so this is the *default* first experience of
enabling persistence rather than an exotic state.

### The measurement that decided it

Every database misconfiguration was driven against a real container. They are
indistinguishable from outside:

| Misconfiguration | Boots? | `GET /healthz` | First history request | Write path |
|---|---|---|---|---|
| Schema never migrated | yes, container **healthy** | `{"status":"ok"}` | 500 `ProgrammingError` | every batch discarded |
| Host unresolvable | yes, container **healthy** | `{"status":"ok"}` | 500 `gaierror` | every batch discarded |
| Wrong password | yes, container **healthy** | `{"status":"ok"}` | 500 `InvalidPasswordError` | every batch discarded |

`Persistence.__init__` builds an engine and never connects; nothing touches the
database until something reads or writes. So there is no check anywhere — not at
boot, not in `/healthz` — for any of these.

### Why no

1. **It is not a distinct condition, it is one of three.** Classifying the
   schema case alone would name whichever failure happened to be measured first
   and leave the other two in the fallthrough. That is exactly the trap avoided
   one commit earlier, when the `str(exc)` leak was fixed at the fallthrough
   rather than in a SQLAlchemy branch — a `ProgrammingError` was never the
   problem, it was the first unclassified exception anyone looked at.
2. **The precedent does not transfer.** `PersistenceDisabled` earned its own
   `type` for a stated reason: two 404s that need *different actions from a
   client* — "try another id" versus "no id will ever work". Every entry in the
   table above needs the **same** action from a client, which is none. The
   distinction is operator-actionable, not client-actionable, and the operator's
   channels are the log and the health endpoint.
3. **It would be information for the wrong audience.** There is no
   authentication on this API. Telling an anonymous caller which of an
   operator's three database mistakes is in force is the same class of
   disclosure that was just deliberately removed from unclassified 500s. Doing
   that again, one exception narrower, would be inconsistent within a week.
4. **It would dress the least important symptom.** The read route's 500 is
   cosmetic next to what the write path is doing: `RunRecorder` must never
   raise, so `QueueWriter` catches, counts and discards. In all three states
   every session and event is being thrown away — one ERROR per batch in the
   log — while `/healthz` says `ok` and the caller sees 201s. **A prettier 404
   on the read side would make a service that persists nothing look better, not
   work better.**

### What follows instead

The real defect is that a configured subsystem can be entirely unusable while
the service reports healthy. Two candidates, both broader than this question and
both still open in [`dev-todo.md`](./dev-todo.md) §0:

- **`/healthz` reports the database.** Covers all three states, and the case a
  boot gate cannot: a database that fails *after* boot. Costs a round trip on a
  route that is already a healthcheck.
- **A boot gate**, symmetrical with `require_credentials` and `require_mounts`,
  whose docstrings already make this argument — "an operator finding out
  immediately is worth more than a service that starts and cannot work". The
  same accepted cost applies: a database blip at the wrong moment turns a
  restart into a crash-loop.

**Reversibility.** Cheap to revisit. If a caller ever demonstrates it can act
differently on "schema missing" than on "database unreachable", this decision is
one branch in `to_problem` away from being reversed. Nobody has.

---

## N1. Note (not a question): `ResultMessage` field set

**Status:** ✅ RESOLVED by the spike — see
[`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md) F1

Every field the response model wanted exists, plus four the spec did not
anticipate: `permission_denials`, `model_usage` (per-model tokens, cache hits and
`costUSD`), `terminal_reason`, and `api_error_status`. The `runs` table and the
response schema have been updated; the cost/usage portion is **no longer
provisional**.

The spike also corrected three things the docs got wrong or omitted — a six-member
message union including `RateLimitEvent`, a six-member content-block union, and
non-uniform `session_id`. Details in the findings document.

<details>
<summary>Original note, kept for context</summary>

The published Python API reference documents `ResultMessage` as carrying `type`,
`subtype`, and `result`. The additional fields the response model wants — total
cost in USD, token usage, wall-clock and API duration, turn count, session id —
are visible in SDK examples but not enumerated in the reference page.

**Plan.** Read the field set off the installed `claude_agent_sdk` package during
implementation and shape the response model to match, rather than guessing.
`serialization.py` reads them defensively (`getattr` with fallback), so an SDK
version that renames or drops a field degrades to a missing key instead of a 500.

Until that check happens, the cost/usage/duration portion of the documented
response schema is **provisional**.

</details>

---

## Q17. How should an LLM provider endpoint reach the SDK?

**Status:** ✅ DECIDED (2026-08-07) — **no. Not required by this consumer, and
it would be declined if offered.** Nothing built, and nothing is pending.

**The answer came from Agent Studio, not from this side**, which is the only way
this question could have been closed: it asks what a consumer needs, and the one
consumer says it needs nothing. *Studio is the endpoint* — a container's
`ANTHROPIC_BASE_URL` points at Studio's gateway and nothing else ever needs to,
and which upstream that gateway relays to is resolved inside Studio's own
process, per request, from Studio's configuration. A second LLM provider changes
that resolution and changes nothing about a container.

The end-user case §"the constraint" worries about does not arise either: a Studio
User who wants to spend their own account already has BYO, which is a persisted
property resolved at egress rather than a request field.

**What stands regardless.** The constraint below is not retired by this closing —
it is the condition on any future reopening. A caller-supplied URL with a
service-supplied credential remains the shape that gets refused, and the
undertaking not to build one costs nothing today, which is the best time to make
a commitment that will cost something later.

The measured SDK facts below stay useful whatever happens: they are what any
implementation of this would have had to start from.

---

*Original statement, kept because the reasoning is what a reopening would need:*

**What it controls.** Whether this service accepts an LLM endpoint — a base URL,
and possibly a credential for it — as a first-class input, and if so whether that
is a property of the container or of the session.

**Where it came from.** Agent Studio has a concept it called an **"LLM Provider"**
— **renamed "LLM Endpoint" on 2026-08-07**, which changes nothing here: the
concept never had a field in this API, and this question is closed anyway. The
old term is kept in the text below because it is what the exchange used —
carrying a URL that agent-service would pass to its SDK in order to reach a
model. On the Studio side it is currently a **placeholder** — almost everything
about it is undecided.

**What this service does today — measured, not assumed (2026-08-06):**

- `config.py` has **no base-URL setting**. `ANTHROPIC_BASE_URL` appears in `src/`
  exactly once, as a comment in `runner.py` recording probe C3.
- `options.py` builds `ClaudeAgentOptions` with 15 fields and sets **no `env`**.
- `contract.py` publishes `version`, `credential_sources`, `provider_selectors`.
  None of them is a URL.

So a deployment that needs an endpoint override sets it in the **container's
environment, out of band**. It works — the SDK subprocess inherits this process's
environment — but it is invisible to `/v1/deployment`, absent from the signed
contract, and unvalidated. That is the same gap the credential contract (AS-1,
AS-25) was built to close for keys, still open for endpoints.

**It is buildable per-session.** The pinned SDK has
`ClaudeAgentOptions.env: dict[str, str]`, and this service does not use it. Read
from the installed SDK 0.2.128, so nobody needs to re-probe for it.

### The constraint that decides the design

**If the caller supplies the URL and the service supplies the credential, this is
a credential-exfiltration endpoint.** Point it at a host you control and collect
the deployment's API key from the outgoing auth header.

**Q6 does not remove this.** Authentication changes *anyone who can reach the
port* into *any authorized caller* — a real reduction, and not sufficient. If
Studio's end users are the authorized callers, a user supplying an endpoint that
receives the deployment's key is still exfiltration, performed by someone who
logged in. The unconfined `Bash` tool is not an argument that it is moot either:
`Bash` already reaches the network, but it does **not** hold the service's
credential, and this would hand it over.

Two shapes survive that constraint:

- **Caller supplies both** URL and credential. Their key, their endpoint. The
  service forwards and stores neither.
- **Container-scoped**, set by whoever provisions the container, exactly as
  credentials work now. `/v1/deployment` would grow a report of which
  endpoint variables the build reads, extending the AS-25 pre-flight check from
  keys to endpoints.

### Why nothing is built

Studio's term is a placeholder, so there is no client to design against — the
same rule that keeps [Q6](#q6-service-level-authentication) deferred rather than
half-built. Anything published here is frozen by AS-24 whether or not it survives
contact with what Studio eventually decides.

**What 0.7.0 did do** is refuse to make it worse: `provider_selectors` was
**not** renamed to free the word "provider" (four clauses and a shipped Studio
code path depend on it), and its description now states that "provider" there
means the cloud that *hosts* the model, that the list carries no URL, and that
the agent-SDK axis is `sdk.name`. See `plans.md` Plan 8.
