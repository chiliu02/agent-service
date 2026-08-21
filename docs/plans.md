# Implementation Plans

One file, consolidated 2026-07-31 from eight — `plan-01-core-service.md`,
`plan-02-sessions.md`, `plan-02-followups.md`, `plan-03-persistence.md`,
`plan-04-container.md`, `plan-05-multi-workspace.md`, `plan-06-web-console.md`,
`plan-07-projects.md`.

**What was kept and what was cut.** Plan 6 is here **verbatim** — it is unbuilt,
so its own text is still the working document. Plans 1–4 are **summarised**: they
shipped, and their originals were largely full code listings written to be
implemented from, which the code and its tests now supersede. Nothing is lost —
`git log docs/plan-*.md` has every original, and the reasoning that outlived them
was already migrated into
[`implementation-notes.md`](../impl/claude-python/docs/claude-python-references.md),
[`spike-findings.md`](../impl/claude-python/docs/claude-python-references.md) and
[`deployment.md`](../impl/claude-python/docs/claude-python-references.md).

**Plans 5 and 7 were removed as out of scope (2026-08-06, user decision).** Plan 5
was the multi-workspace router — N single-workspace containers behind a
path-prefix reverse proxy; Plan 7 was Projects, a metadata layer on top of that
router, already rejected on 2026-07-31. Both are gone from this file, from
[`dev-todo.md`](./dev-todo.md) and from the documents that pointed at them, along
with `router-stack-evaluation.md`, which existed only to choose an implementation
language for the router. `git show b7be5fc:docs/plans.md` has the full text of
both if the question ever comes back.

**The checkboxes had drifted badly and are not reproduced.** Plans 1 and 2 shipped
with 72 and 56 boxes still unticked; plan 4 shipped with 18 of 38 unticked. The
service runs, the suite is green, and the artifacts exist — so the boxes recorded
nothing but the fact that nobody went back to tick them. Status below is stated
from what is actually in the tree.

Outstanding work is **not** here. It is in [`dev-todo.md`](./dev-todo.md), which
is the list to read if you want to know what to do next.

## Status at a glance

| Plan | State | Evidence |
|---|---|---|
| [1 — Core service](#plan-1--core-service) | ✅ shipped | `/v1/query`, `/v1/query/stream`, full OpenAPI |
| [2 — Multi-turn sessions](#plan-2--multi-turn-sessions) | ✅ shipped | `/v1/sessions/*`, registry, reaper, interrupt |
| [2 follow-ups](#plan-2-follow-ups) | ✅ done bar cosmetics | 15 numbered items closed; cosmetic list open |
| [3 — Persistence](#plan-3--persistence) | ✅ shipped | Postgres, Alembic, A.1 + A.2, opt-in |
| [4 — Container and deployment](#plan-4--container-and-deployment) | ✅ shipped | Dockerfile, compose, measured shutdown/reaping |
| [6 — Web console](#plan-6--web-console-sketch) | 🟨 sketch; partly overtaken | `impl/common/web/console.html` ships as a dev tool |
| 9 — Persistence schema becomes the platform's | 🟩 steps 1–4 shipped 2026-08-08; **step 5 needs a version** | DDL at `spec/schema/agent-service-<revision>.sql`, Alembic tree at `impl/common/db/`, `env.py` imports no implementation |
| [8 — Multi-implementation platform](#plan-8--multi-implementation-platform) | 🟨 steps 1–5 shipped; 7 in progress, 6 now unblocked | `impl/codex-python` is containerised and in CI; AS-24 measured failing, which is what step 6 was waiting for |
| 5 — Multi-workspace router | 🚫 **out of scope** (2026-08-06) | removed; see the note above |
| 7 — Projects | 🚫 **out of scope** (2026-08-06) | removed; had been rejected 2026-07-31 |

---

# Part I — Shipped

Summaries. The code is the specification now; these record what each plan was for
and what it decided, so a reader meeting the codebase can tell which decisions
were deliberate.

## Plan 1 — Core service

**Goal.** A FastAPI service exposing `claude_agent_sdk` one-shot runs over HTTP —
blocking and streaming — with a complete auto-generated OpenAPI spec.

**Architecture, and the one rule that still holds.** Three layers with a hard
boundary: `config`/`schemas`/`serialization`/`options`/`policy`/`runner` know
nothing about FastAPI; **`api.py` knows nothing about `claude_agent_sdk`**. That
boundary is still enforced — `runner.sdk_version()` exists precisely so `api.py`
never imports the SDK. The agent layer is exercised through a fake run factory, so
the entire HTTP surface is testable without spending money, which is why the
default suite costs nothing.

**Its eleven tasks**, in order: dependencies/settings/test harness · serialization
(SDK objects → JSON-safe dicts) · API schemas · options builder (limits, paths,
safe defaults) · policy (the real permission layer) · error mapping · the runner ·
FastAPI app with health and capabilities · `POST /v1/query` · `POST
/v1/query/stream` · live smoke test and README.

**What outlived the plan.** The normalization and error mapping it built are
reused unchanged by sessions — Plan 2 added lifecycle, not a second serialization
path. Its `aclosing` discipline in `runner.py` is written up in
[`implementation-notes.md`](../impl/claude-python/docs/claude-python-references.md).

## Plan 2 — Multi-turn sessions

**Goal.** Stateful conversations: create a session, send turns, stream or block on
each, interrupt a running turn, close it — backed by one long-lived
`ClaudeSDKClient` per session.

**Architecture.** Each session owns one `ClaudeSDKClient` (one CLI subprocess) in
an in-process registry, guarded by a per-session `asyncio.Lock`, reaped on idle
TTL.

**Its eight tasks**: session config and schemas · `AgentSession` lifecycle ·
`SessionRegistry` (collection, cap, reaper) · lifecycle endpoints · blocking turn ·
SSE turn · interrupt and PATCH controls · live smoke test and docs.

**The part worth knowing.** `AgentSession.close()`, `_finalize_live_turn()`,
`_acquire_lock_until()` and `_send_impl()`'s exception handlers took **seven fix
rounds plus a 1060-round adversarial fuzz** to stabilise. Reopen them only
deliberately, and re-run a fuzz *validated as discriminating* — run it against the
pre-fix code and confirm it fails there — before trusting a clean result. That
discipline is what caught the defects inspection missed.

## Plan 2 follow-ups

Items found during Plan 2 and deliberately deferred rather than fixed before
merge, each triaged at the final whole-branch review.

**All fifteen numbered items are closed**, plus two defects found during that work
that were never numbered: the `_closing` latch (a new turn could start underneath
a session being torn down) and `context_usage()` talking to a client `close()` was
already disconnecting.

| Items | Subject |
|---|---|
| 1, 2, 4 | `sessions.py` concurrency |
| 3, 5 | `registry.py` retry semantics and reap count |
| 15 | `registry.py` lock scoping |
| 6, 7, 9 | small API correctness |
| 8 | refuse to boot without credentials |
| 10 | PATCH mid-turn — probed live, spike case M1 |
| 11–14 | observability |

**Still open: the cosmetic list only** — moved to
[`dev-todo.md`](./dev-todo.md).

**Also carried forward: a "known and deliberate — do not fix" list.** Eleven
behaviours that look like defects and are decisions, including the 200-with-body
interrupt response, `total_cost_usd` being cumulative per connection, and
`timed_out` being absent from `RunResponse` but present on
`SessionRecord.last_turn`. That list is reproduced in `dev-todo.md` under
**Do not "fix" these**, because it is the half of a todo list that stops work
rather than starting it.

## Plan 3 — Persistence

**Goal.** Survive a restart. Every run, turn and message recorded in Postgres, in
a shape this service owns.

**Architecture: two independent write paths into one database, deliberately not
merged.** A.1 is normalized `AgentEvent` rows this service defines; A.2 is the
SDK's own `SessionStore` mirror, which is what makes a conversation resumable. They
have **opposite failure contracts** — `RunRecorder` must never raise (it runs
inside `_send_impl`'s drain, where an exception mislabels a turn); `SessionStore.
append` **must** raise (the SDK catches, retries three times, then reports a
`MirrorErrorMessage`, so swallowing makes a broken mirror look healthy). They look
alike and behave oppositely; see
[`implementation-notes.md`](../impl/claude-python/docs/claude-python-references.md).

**Its ten tasks**: the recorder seam with no database behind it · schema, engine,
migrations · the write path that cannot stall a turn · wire the recorder to the
database · reading it back · the `SessionStore` adapter (A.2) · resume from the
store · deployment · live verification · documentation.

**The global constraint that shaped everything.** No database round trip on the SSE
path, and **persistence is optional** — with no `AGENT_SERVICE_DATABASE_URL`,
`agent_service.db` must never be imported. A fresh-interpreter test pins that,
because an in-process `sys.modules` check passes regardless once another test has
imported it.

## Plan 4 — Container and deployment

**Goal.** Package the service as a Linux container with a bind-mounted host
workspace, so `permission_enforcement="none"` with `Bash` enabled has a real
boundary behind it.

**Why it was mostly verification.** `deployment.md` made a series of confident
claims about container behaviour; this project's consistent finding is that
unverified claims are wrong roughly every time they are checked. Every claim was
treated as a hypothesis with a test attached — and the exercise duly corrected
itself: **`init: true` keeps its place for the opposite reason it was given.** The
agent subprocess is a direct child of uvicorn and asyncio reaps it either way (0
zombies with `init` either on or off); what `init` actually buys is reaping
*orphaned grandchildren*, which is exactly what the agent's `Bash` tool produces —
3 permanent zombies without it, 0 with.

**Its eight tasks**: `.dockerignore` and build context · Dockerfile, and prove the
bundled native binary runs · compose, mounts and the read-only boundary · signals,
shutdown and subprocess reaping · git on a bind-mounted repo · credentials, boot
behaviour and the healthcheck · end-to-end smoke test · documentation.

**What it measured** now lives in [`deployment.md`](../impl/claude-python/docs/claude-python-references.md): the
shutdown-interval table (0 sessions → 0.046 ms; 3 wedged mid-turn → 16.23 s), the
zombie counts, exit 3 on a missing credential in 0.93 s, and the 561× bind-mount
penalty on Windows.

---

# Part II — Designed, not built

Verbatim. Still a working document.

## Plan 6 — Web console (sketch)

**Status: sketch, not an executable plan.** The other plan files decompose into numbered tasks
because their prerequisites exist. This one does not, because the two things it depends on —
message persistence and resumable streams — are unbuilt, and their design decides most of the
UI's shape. Decomposing now would be inventing tasks against an undecided foundation.

**Goal:** a browser console giving a separate chat window per live session.

Design input: [`persistence.md`](../impl/claude-python/docs/claude-python-references.md) (Part A is the missing piece).

**Where it would be served.** As originally written this was a feature of the Plan 5
multi-workspace router, which is out of scope as of 2026-08-06. With one service and one
workspace there is no separate component to hang it on: the console is served by this service,
alongside the API, or it stays what `impl/common/web/console.html` is today — a separate dev tool loaded from
disk. That is a decision for whoever picks this up, and it is **not the hard part**. The
dependency order is:

```
  message persistence  ->  resumable streams  ->  web console
     (plan-03, A.1)          (new; reopens a        (this file)
                              settled decision)
```

Built against today's API, a console works in a single uninterrupted tab and loses everything on
refresh. That will read as broken, and the fix is not in the UI layer.

### Blocker 1 — there is no transcript to render

**Verified.** `SessionRecord` (`schemas.py:438`) carries `turns` (a *count*), `total_cost_usd`,
`status`, `model` and timestamps. There is **no messages field**. `sessions.py:196` keeps
`last_turn: TurnResult | None` — the last one only. Conversation messages exist nowhere except
in-flight on the SSE stream.

Consequences for a chat UI:

- Reload the page and the conversation is empty, with a live cost figure above it.
- Open a session someone else started and there is nothing to show.
- No way to review what an agent did after the fact — which is most of why a console is useful.

[`persistence.md`](../impl/claude-python/docs/claude-python-references.md) Part A is exactly this work. It is designed and unbuilt.

**Rejected alternative:** hold the transcript in browser storage. It dies on cache clear, does
not follow the user to another device, and cannot show a session opened by anyone else. Those
are the main reasons to want a shared console, so this defeats the purpose.

#### Which half of Part A the console needs

`persistence.md` A.1 and A.2 both persist messages, and **the console needs A.1**:

- **A.1** — normalized `AgentEvent` rows, a shape this service owns. This is what the chat
  window renders and what cost/tool-usage views query.
- **A.2** — the SDK `session_store` mirror. Verified as the supported seam for conversation
  continuity, so the agent keeps context across restarts. But `SessionStoreEntry` is explicitly
  an opaque blob of an internal CLI union, guaranteeing only `type` (plus usually `uuid` and
  `timestamp`). **A console must not parse it** — doing so couples the UI to an internal format
  that can change under an SDK upgrade.

So A.2 is not a shortcut around this blocker. It is worth landing early anyway, because it is
cheap (one option on the object `options.py` already builds) and it makes sessions survive
container restarts — but the console still waits on A.1.

### Blocker 2 — disconnect currently kills the turn, and a browser disconnects constantly

Today a dropped SSE stream **interrupts the turn**. That is deliberate. `api.py` calls it "a
CORRECTNESS step, not a latency or cost optimisation": an abandoned turn's in-flight messages
land during the *next* turn's drain, and a stray `ResultMessage` among them ends it early,
attributing one caller's turn to another. It is also the only real brake on spend, given the
README's measurement that `max_budget_usd` does not move for an interrupted turn.

A browser is precisely the client that disconnects for benign reasons: page reload, laptop
sleep, backgrounded mobile tab, wifi blip. Under the current design every one of those discards
an in-flight agent run mid-work.

So a console requires:

1. **Turns survive consumer disconnect** — the opposite of today's rule, and
2. **A durable per-session event log**, replayable by `Last-Event-ID`, and
3. **A different answer to the cross-contamination problem** the interrupt currently prevents.

(3) is the hard one and must not be skipped. The interrupt is not just tidiness; removing it
without a replacement reintroduces one caller's messages ending another caller's turn.

This is the same conclusion the earlier streaming discussion reached — resume is a semantic
change, not a transport change — but the browser supplies a real justification for paying for
it. Note it touches `sessions.py` and `api.py`, not just the UI layer.

### Resolved cheaply — two things that need no new design

**Do not poll `GET /v1/sessions/{sid}`.** It is **not a lookup**. Its handler awaits
`session.context_usage()`, a live **control request** — the route's own `responses=` block
documents 502 when it cannot be delivered and 500 for the SDK's 60 s control timeout. A console
polling it per session on a timer would fire control requests at every live session
continuously. Use `GET /v1/sessions` for the session picker; call this only when a session is
explicitly opened.

**One turn at a time per session.** The session holds a lock and raises `SessionBusy`. Two tabs
on one session will collide. The UI must disable input while `status == "running"` and handle
losing the race — not assume it owns the session.

### Security — the position changes materially

Stated plainly because the current posture is documented as deliberate, and a console moves it.

Today: **no authentication at all**, bound to `127.0.0.1`, agent has unconfined `Bash`. A web
console is a browser origin — it implies cookies or tokens, CSRF protection, and almost
certainly binding beyond localhost. That puts a browser-reachable UI in front of an API whose
documented capability is running arbitrary shell commands as the service process.

**Authentication stops being optional.** It is a hard prerequisite here — this is Q6 in
[`open-questions.md`](./open-questions.md), deferred on the strength of localhost-only binding,
which a browser console is exactly the thing that ends.

**New risk that does not exist today: the console renders agent-produced text.** The agent emits
arbitrary strings, including markdown and HTML. Rendering them into a chat window is an
injection vector where the untrusted content is produced by the thing the user is talking to,
and where a tool result may contain attacker-influenced file contents. Sanitize; never render
raw HTML; treat agent output as untrusted regardless of how it looks.

### Smaller things to size before decomposing

- **Connection budget.** Each open console tab holds an SSE connection per session it is
  watching. N tabs × M sessions, all long-lived, against a service that runs `--workers 1`
  because `SessionRegistry` holds live `ClaudeSDKClient` objects in process memory.
- **Cost display.** `total_cost_usd` is a **floor, not the figure** (`schemas.py:451`, measured
  in `spike-findings.md` S6). A console showing it as "cost" will mislead, especially with an
  interrupt button next to it, since interrupted turns do not move it. Label it honestly.
- **Interrupt in the UI.** `POST /v1/sessions/{sid}/interrupt` exists. Worth exposing — but the
  README's measurement stands: a caller who can interrupt can spend without limit, and it is
  invisible from the API. A UI makes that button easy to press repeatedly.

### Open questions

- Does resume replay from persistence, or from a separate ring buffer of raw SSE frames? These
  are different artifacts — normalized messages versus verbatim frames — and the console needs
  the frames to redraw exactly what streamed.
- Is the console read-only for sessions it did not start, or fully interactive? Multi-user
  changes the locking story from "handle `SessionBusy`" to "show who holds the turn."
- Does a session need an owner at all once authentication exists?

### Before this becomes a real plan

Decide the resume semantics (Blocker 2) and land persistence (Blocker 1). Until both are
settled, task decomposition here would be speculative.

---

## Plan 8 — Multi-implementation platform

**Status: designed 2026-08-06, nothing moved.** **Structure and migration worked up in full in `docs/plan-8-design.md` (removed 2026-08-19; in `git log`) (2026-08-07)** — the target directory tree, the three couplings that decide the order, and seven steps each of which ends with `ci.py` green. Read that before moving anything. Two decisions taken (below); the
sequencing is written down so the first step is not "start moving files".

**The trigger.** `agent-service` is to front Codex, Gemini and other agent SDKs
as well as Claude's. Those SDKs are not all usable from Python — a TypeScript
port of this service already exists on the `docs/typescript-effect-port` branch,
and its image is already sitting on the build host under the tag
`agent-service:latest`.

### What actually generalises — and it is not the code

Three assets here are already implementation-independent, and they are the
product:

- **The interface contract.** Agent Studio talks HTTP and OpenAPI. It has never
  depended on this being Python.
- **The conformance suite.** `spec/conformance/` imports nothing from
  `agent_service`; it drives a running service over HTTP and reads the published
  document. It is already an acceptance suite for *any* implementation.
- **`/v1/capabilities`**, whose entire purpose is "ask what this deployment
  supports rather than assuming".

`src/agent_service/`, the SDK pin and `spike-findings.md` are one
implementation's private business.

### Why not one service in one language

The value of this service is that it wraps **the agent SDK** — session
lifecycle, the tool loop, permission plumbing, transcript mirroring — not the
model API. `implementation-notes.md` is a catalogue of measured SDK behaviours,
and that is the substance.

A single-language service means hand-rolling an agent loop against a raw HTTP API
for every provider whose SDK is not available in that language, which discards
precisely the thing being wrapped. **The implementation language follows the SDK.**

### Decision 1 — monorepo, contract promoted out (user, 2026-08-06)

```
agent-service/
  spec/                  the product; versioned independently
    openapi/                 core-<ver>.json + per-provider extensions
    contract-<ver>.md        the clause document
    conformance/             the black-box suite; stays Python
  impl/
    claude-python/           this repo. pins claude-agent-sdk
    codex-typescript/        pins the Codex SDK
  ci.py                      builds each impl, runs ONE suite against all
```

Monorepo and not one repo per implementation, for one reason: a contract change
and the implementation that satisfies it must land **atomically**. With separate
repos the first cross-repo bump reproduces the failure this project already had
once — a consumer left reading a spec that no longer describes anything — at N
times the scale. `spec/` is the seam; splitting it out later is a directory
move.

**The conformance suite stays Python even when testing a TypeScript service.**
It is a harness, not a library. Rewriting it per implementation would give each
implementation its own idea of what the contract says, which is the failure it
exists to prevent.

### Decision 2 — small core plus per-provider extensions (user, 2026-08-06)

**The contract as signed is Claude-shaped**, and this is the hard part.
`sdk_session_id`, `total_cost_usd` being cumulative *and* a floor, `model_usage`
being per-connection, the `permission_enforcement` modes, `MirrorErrorMessage` —
each is a measured fact about one SDK. Codex and Gemini will not share them.

Two resolutions rejected: a lowest common denominator (discards the measured SDK
behaviour that is most of the value) and one union document of mostly-nullable
fields (makes "required" indistinguishable from "not applicable here" — the exact
ambiguity AS-17a already rejects for `sdk_session_id`).

So: **one core document every implementation must satisfy, plus per-provider
extension documents**, with `/v1/capabilities` declaring which are live. Core is
small — create/delete session, send turn, stream events, transcript, `/healthz`,
`/v1/capabilities`. Anything cost-shaped or session-id-shaped is almost certainly
extension.

**The core boundary is a prediction until a second implementation tests it.**
Revising it when Codex or Gemini lands is the expected outcome, not a failure of
this plan. Draw it, then let evidence move it.

Consequences to accept now: `spike-findings.md` becomes one file per
implementation, and §8's tie-breaker — *"where this document and
`spike-findings.md` disagree about a measured fact, `spike-findings.md` is
correct"* — has to name **which** one.

### Three version streams, and merging them is the failure mode

Today `pyproject.toml`'s version **is** the API version, deliberately and
correctly for one implementation. That pun must break:

| Stream | Today | Owner |
|---|---|---|
| Contract version | v3.1 | `spec/` |
| Document version | 0.6.0 | `spec/`, one per surface |
| Implementation + SDK pin | this package + `claude-agent-sdk 0.2.128` | each impl |

`/v1/capabilities` is the join: each implementation declares which document
version it implements and what it is built on. Studio's rule is unchanged — never
assume, ask capabilities.

### Two naming collisions, to fix before they harden

- **"provider" is already taken.** `Capabilities.provider_selectors` means the
  *hosting* provider — Bedrock, Vertex, Foundry — for Claude. Calling Codex and
  Gemini "providers" collides with a field Studio has pinned. Pick another word
  (`agent`, `backend`, `engine`) first.
- **`Capabilities.sdk_version` is a singular top-level string**, which assumes
  one SDK. It has to become structured.

Neither can be renamed in place: both are in published documents, and AS-24
forbids editing those while AS-23 treats a rename as the breaking kind of change.
**Follow the 0.5.0 precedent** — `session_id` → `sdk_session_id` shipped the new
name, kept accepting the old one, and marked it deprecated.

### Sequencing

Ordered so nothing breaks Studio, and so the expensive step is last:

1. ~~**Fix the naming collisions**~~ **DONE in 0.7.0.** `Capabilities.sdk`
   (`{name, version}`) added and `sdk_version` deprecated but still emitted.
   `provider_selectors` was **not** renamed: four clauses and a shipped Studio
   code path depend on it, and Studio's own "LLM Provider" (renamed "LLM
   Endpoint" 2026-08-07, which affects nothing here — the word never entered
   this API) turned out to be a
   *placeholder*, so there was no live collision to buy a break with. Its
   description now states that "provider" there means the cloud that hosts the
   model, that the list carries no URL, and that the agent-SDK axis is
   `sdk.name`. The endpoint question is open as
   [Q17](./open-questions.md#q17-how-should-an-llm-provider-endpoint-reach-the-sdk),
   with the measured SDK detail in
   `spec/draft/llm-provider-and-auth.md` (removed 2026-08-19; in `git log`).
2. **Promote `spec/`** — move the documents and the conformance suite up,
   leave the Python implementation where it is. No behaviour change; `ci.py`
   learns the new paths. `freeze` follows the documents.
3. **Split core from the Claude extension document.** Design-heavy, no code.
4. **Build the second implementation** against core, publishing its own extension
   document and its own `spike-findings`. This is what validates step 3.
5. **`ci.py` loops over implementations**, keeping the two-stack conformance pass
   per implementation.

### Explicitly out of scope

**A gateway multiplexing implementations behind one endpoint.** Plan 5 (the
multi-workspace router) was removed as out of scope on 2026-08-06 and must not
return by the back door. A multi-*implementation* router is a different object,
but close enough that it needs a demonstrated need and its own decision. Until
Studio shows it requires a single URL, N containers with Studio choosing is
strictly simpler.

### Image naming — start now, it is already wrong

`agent-service:latest` on the build host is the **TypeScript port**
(`package.json`: `"version": "0.0.0"`), not this service, and it boots and serves
with **no credential** where this one exits 3. Two implementations, one
namespace, no version in the tag. Convention from here:
`agent-service-<impl>:<version>` — never `latest`, and never a bare
`agent-service`.
