# Dev TODO

Everything outstanding, in one place. Companion to [`plans.md`](./plans.md),
which records what shipped, and [`open-questions.md`](./open-questions.md), which
records decisions not yet made.

Created 2026-07-31 when the eight plan files were consolidated. Nothing here is
new work invented during that pass — every item is carried from a plan, a
follow-up list, an open question, or a gap this project measured and recorded.

**Reorganised 2026-08-06**: [open work](#open-work--by-priority) first, highest
priority at the top, then [Do not "fix" these](#do-not-fix-these), then
[Closed](#closed) — which is most of the file. Nothing was deleted in the move.
The closed items keep their outcomes, and several record that the original item
was wrong, which in this codebase is the half worth keeping.

**Consolidated 2026-08-14, ahead of the first release.** Six sections marked DONE
in their own headings were still sitting under *Open work* — 0a, 6, 0, 1, 1b and
2 — so a reader counting open items counted eleven where there were five. They
are now under [Closed](#closed) with their outcomes untouched, and the two index
tables, which had come to live **inside** item 0a rather than under the heading
they index, were lifted out to the top. **Byte-for-byte a reordering**: the file
is the same 1,821 lines it was, and nothing was rewritten in the move.

**Then six items were worked and closed the same day**, in the order the user
asked for: 10, 8, 11, 5, 2b, 4. Two were code defects found by reading the three
builds against each other rather than against a document (`GP-57`, `CX-53`); one
was already built and needed only two unfilled surfaces filled; three were stale
records whose work had shipped or which decline to act by their own terms.
**ONE item remains open** (2026-08-14): cutting 0.19.0, and it is the user's
decision. Everything else in this file is closed, including item 12 — found by
driving the web console against all three builds live rather than by any suite,
which is the kind of defect no suite here is shaped to catch.

**Item 13 was added and closed on 2026-08-15, and the consumer found it, not
us.** Same shape as 12 in the way that matters: every suite passed, the turn was
correct, and a field the specification names was published empty on one build of
three. It is the first defect here reported from outside.

**Read [Do not "fix" these](#do-not-fix-these) before starting anything.** Eleven
behaviours in this codebase look like defects and are decisions. That section is
the half of a todo list that stops work rather than starting it.

---

# Open work — by priority

**Nothing is owed to Agent Studio and nothing is promised.** Every ask has
shipped, the one measurement this side committed to has been run, and Q6 —
deferred since 2026-07-31 and the thing that gated everything else — was
answered in 0.11.0.

That is a different state from any earlier version of this file, and the useful
consequence is that priority is now mostly a choice rather than a queue.

### Open

| # | Item | Blocked on |
|---|---|---|
| 9 | Cutting `0.19.0` — **the first release** | **the user's decision, and nothing else is left.** Everything that needed no permission is done, and everything that needed permission and was given it is done: the three additions (`mcp.tool_call`, the `422` `ValidationProblem`, `PrebootSpec.runs_as`), the guides, the `spec/` restructure, both Maven artifacts published under their new coordinates, and three snapshot images built, verified against their tags and pushed. **Agent Harness is green on all of it** — 32 of 32 against the artifact, then **50 of 50 against each of the three images with nothing ignored**, which is the first time their live half has run at all. Their words: *cut when you are ready.* What remains is [`versioning.md`](./versioning.md) §4 steps 1–10, then release images from the tag via `.ci/images.py`. The release notes are drafted at [`docs/release-notes-0.19.0.md`](./release-notes-0.19.0.md), which is what §4 step 5 consumes |

### Closed

| # | Item | |
|---|---|---|
| ~~13~~ | ~~`gemini-python` published five `token_usage` nulls on every turn~~ | **fixed 2026-08-15** and built as `0.0.6`, the day after the consumer reported it — the mapper had never been written, and the fake agent's fixture was consistent with the bug. `GP-60` — [below](#13-gemini-python-published-five-token_usage-nulls-on-every-turn--fixed-2026-08-15) |
| ~~12~~ | ~~A conversation cannot be rendered from the document alone~~ | **done 2026-08-14.** `content` described and filled by all three; `type` documented as authoritative and the SSE frame name explicitly NOT contract. `CX-56`. Three documents regenerated, **computed core unchanged** — [below](#12-a-conversation-cannot-be-rendered-from-the-document-alone--done-2026-08-14) |
| ~~3~~ | ~~The web console (Plan 6)~~ | **closed 2026-08-14 as a dev tool** — rehydration done, disconnect decided, injection audited live, and a cost display that printed `$0.0000` for *cannot price* fixed — [below](#3-the-web-console--plan-6--closed-2026-08-14-as-a-dev-tool) |
| ~~2b~~ | ~~Multi-implementation platform (Plan 8)~~ | **all seven steps done** — 1–5 on 2026-08-07, and 6–7 confirmed 2026-08-14 **in a different shape than the plan drew**: one computed `core-<ver>.json` beside three whole per-build documents, not `spec/core/` + `spec/ext/` — [below](#2b-multi-implementation-platform--plan-8) |
| ~~5~~ | ~~Release mechanics have no owner~~ | **closed 2026-08-14** — superseded by `versioning.md` §5, and executed three times — [below](#5-release-mechanics--the-step-that-had-no-owner--closed-2026-08-14-it-has-one) |
| ~~4~~ | ~~Three small optional things~~ | **closed 2026-08-14 as a record** — both remaining entries decline to act by their own terms — [below](#4-small-and-genuinely-optional--closed-2026-08-14-as-a-record-not-as-work) |
| ~~11~~ | ~~`codex-python` publishes `max` effort and silently narrows it~~ | **fixed 2026-08-14** — publishes what it delivers exactly, behaviour unchanged, `CX-53`. **The one change in this pass that moved a published document** — [below](#11-codex-python-publishes-max-effort-and-silently-narrows-it--fixed-2026-08-14) |
| ~~8~~ | ~~Two defects ACP's design exposed~~ | **both closed 2026-08-14.** `PermissionMode` built 2026-08-11; `stop_kind` was already published and was unfilled on two surfaces — derived on read, no DDL revision, no document change — [below](#8-two-defects-acps-design-exposed--stop_reason-and-permissionmode--both-closed-2026-08-14) |
| ~~10~~ | ~~`gemini-python` accepts `disallowed_tools` and never reads it~~ | **fixed 2026-08-14**, the day it was found — honoured rather than refused, two regression tests, `GP-57` — [below](#10-gemini-python-accepts-disallowed_tools-and-never-reads-it--fixed-2026-08-14) |
| ~~7~~ | ~~`RunOptions` diverges across implementations~~ | **decided 2026-08-14** — all four questions answered from three shipped builds, and `options-divergence.md` merged into [`capability-divergence.md`](./capability-divergence.md) §5. The two defects the pass turned up became items 10 and 11, and both are closed |
| ~~0a~~ | ~~Three dead paths inside the PUBLISHED document~~ | done 2026-08-10 — [below](#0a-three-dead-paths-inside-the-published-document--done-2026-08-10) |
| ~~6~~ | ~~Rename `agent_service.contract`~~ | **done 2026-08-07, shipped as 0.15.0** — [below](#6-rename-agent_servicecontract--done-shipped-as-0150) |
| ~~0~~ | ~~The argv measurement~~ | run 2026-08-07 — [below](#0-the-argv-measurement--run-2026-08-07-promise-closed) |
| ~~1~~ | ~~Adopt CI~~ | done 2026-08-06 — [below](#1-adopt-ci--done-2026-08-06) |
| ~~1b~~ | ~~Two asks from Agent Studio~~ | both shipped 2026-08-07 — [below](#1b-two-asks-from-agent-studio--both-shipped) |
| ~~2~~ | ~~Authentication (Q6)~~ | shipped 0.11.0 — [below](#2-authentication--q6-shipped-in-0110-optional-off-by-default) |

## Do not "fix" these

Eleven behaviours that look like defects and are decisions. Carried from the Plan
2 follow-ups list unchanged.

- **`POST /v1/sessions/{sid}/interrupt` returns 200 with a body**, not 204 and not
  409. User decision. `interrupted` reports whether a control request actually
  went out, which is **not** the same as `status == "running"` — an abandoned turn
  on an idle session can fire a real interrupt.
- **`interrupt()` is a no-op when there is nothing to interrupt, and must not
  raise.** A turn can end between the caller's decision and the call arriving.
- **`timed_out` is absent from `RunResponse`** — a timed-out turn is a 504 and the
  status code carries the information. **Narrowed, not broken, by item 11:** it
  *is* present on `SessionRecord.last_turn`, because on a record fetched later the
  status code is long gone and a timeout is otherwise indistinguishable from any
  other `outcome_recorded: false` ending. Pinned by
  `test_get_reports_a_turn_that_timed_out`.
- **`total_cost_usd` is cumulative per connection** (measured, S6). The code
  assigns, never sums. Unchanged by item 14, which added `turn_cost_usd` as a
  separate differenced field rather than touching this one.
- **The two stream endpoints differ on a first-advance failure.**
  `/v1/query/stream` returns 200 with an in-band `event: error`; the session
  stream returns a real 504 problem document. Documented in the route
  description.
- **An interrupted turn returns `result: ""`, not null.** That is what the SDK
  returns, and passing it through unaltered is this service's contract.
  `interrupted: true` is the discriminator.
- **Repeated interrupts on a running turn all fire.** Consistent with SDK
  semantics; each is bounded by the SDK's 60 s control timeout.
- **A failed interrupt leaves the stamp.** It costs a missed courtesy, not a
  correctness gap, and the alternative aims a control request at a turn that no
  longer exists.
- **`permission_enforcement="none"` by default, with `Bash` enabled.** The
  container boundary is the only enforcement — which now exists (Plan 4), unlike
  when this was written. **Do not expose the service beyond localhost without
  Q6.**
- **Three guards are deliberately not test-killable.** See
  [`implementation-notes.md`](../impl/claude-python/docs/claude-python-references.md) §"Guards that are
  deliberately not test-killable" before deleting anything that looks uncovered.
- **`AGENT_SERVICE_DATABASE_URL` is popped from `os.environ` at startup.** Not
  tidiness: the agent's subprocess inherits this process's environment and has
  `Bash`. `ANTHROPIC_API_KEY` cannot be hidden the same way.


---

# Closed

Done, decided, or deliberately out of scope — kept with outcomes rather than
deleted.

## 13. `gemini-python` published five `token_usage` nulls on every turn — FIXED 2026-08-15

**Found by the consumer, not by us**, and reported against the delivered
`gemini-python:0.0.5` on 2026-08-14: a successful turn returned all five named
counts as `null` while the raw `usage` beside them carried
`input 7843 / output 39 / total 8824`.

**The mapper did not exist.** `_turn_response()` built its `RunResponse` without
passing `token_usage` at all, so the model default — five nulls — shipped from
this build's first turn. Not a wrong key and not a wrong nesting level, which is
what the Codex build's version of this defect was.

**What it says is false.** `null` is defined as NOT REPORTED, never zero and
never *not bothered*, so a build that has the number and publishes `null` is
making a claim about its own capability that is untrue. The shape stays valid
throughout, which is why no schema check and no document diff can see it.

### The fix

`input_tokens` ← `input_tokens`, `output_tokens` ← `output_tokens`,
`cache_read_tokens` ← `cached`. The other two stay `null` for measured reasons:
no cache-write counter exists on this target, and the agent's reasoning count
(`thoughts`) is dropped by the CLI's own conversion into the `result` event.
**It is deliberately not derived** as `total - input - output` — that expression
also absorbs `tool`, dropped by the same conversion, so it would publish a
reasoning figure inflated by tool tokens. `GP-60` carries the arithmetic.

### Why nothing here caught it, which is the half worth keeping

**The clause exists and it is LIVE.** AS-34 — *a count the build reports is
never published null* — would have failed on the first real turn, but it costs a
real turn against a real model, so it had never run against this build.

**The free suite could not have caught it either**, because the fake agent's
`result` event carried `total_tokens` and no per-direction counts: **a fixture
consistent with the bug.** That is the general lesson. A fake written from the
same understanding as the code tests the understanding, not the code. The fake
now emits the shape a real turn emits, and two tests pin the mapping — the
function against the measured payload, and the seam over HTTP.

**Three regression tests and a fourth in `test_api_turns.py`**, all verified to
fail without the change. The divergence it exposed — `input_tokens` includes the
cached half here and does not on claude — is now a row in
[`capability-divergence.md`](./capability-divergence.md) §4.

**Shipped as `0.0.6`** (user, 2026-08-15). Built from the `impl/` context,
verified against the tag rather than against a CI image: `agent-service-openapi`
answers with no credential and no mounts (`version` and `impl.version` both
`0.0.6`), the credential gate exits **3**, the boot-gate tier is **14/14**, and
the full conformance suite over HTTP is **79 passed, 4 skipped, 0 failed** with
AS-24 included. **Not pushed and not announced** — the registry push and the
availability note are a separate decision, and the delivered `0.0.5` publishes
nulls until one is made.

## 12. A conversation cannot be rendered from the document alone — DONE 2026-08-14

**All three steps taken, including the one that was left as a decision.**

1. **`content` is described** — what a block is, that `text` blocks carry `text`,
   that `raw` is the SDK's own shape beside it, and that `null` means *no
   renderable content* rather than *content dropped*. Additive; it moved
   `/openapi.json` on all three builds and the **computed core did not change**,
   so no shared leaf moved.
2. **`codex-python` fills it** (`CX-56`), for both halves of a conversation: an
   `agentMessage` carries `.text`, a `userMessage` carries a list of blocks in
   `.content`, and a caller reading only this field that saw the answers and not
   its own prompts would still be reading half a transcript. Blocks are rebuilt
   rather than passed through, because the SDK's carry keys of its own.
   Verified on a real turn: both sides arrive as `{"type": "text", ...}`.
3. **The SSE frame name is NOT contract** — decided rather than deferred. It is
   not expressible in an OpenAPI document, both streaming routes are POST so
   `EventSource` cannot consume them anyway, and making it contract would mean
   changing a build's wire output to no one's benefit. `AgentEvent.type` is
   documented as the authoritative discriminator and says so in its own
   description, which is where a client will actually read it.

**Tool blocks are deliberately not invented for codex.** It reports its tool
loop as items already surfaced as `assistant` with the kind in `subtype`;
manufacturing `tool_use` blocks would guess at a shape the specification does
not define. A conversation renders from the words.

**The console keeps its `raw.item.text` fallback**, and should: the delivered
`codex-python:0.0.15` image still has the old behaviour, and the console has to
work against what is deployed rather than only against what is built.


**Found 2026-08-14 by driving the web console against all three builds live**,
which is the only way it could have been found: every build passes the
conformance suite, serves the same document, and returns a correct answer. The
console showed an empty conversation for two of the three anyway.

**Two divergences, and each build is the odd one out in a different one:**

| | SSE frame name | `AgentEvent.content` |
|---|---|---|
| `claude-python` | the event's own `type` | text blocks |
| `codex-python` | the event's own `type` | **unset** — the text is at `raw.item.text` |
| `gemini-python` | **literally `event`**, with `type` in the payload | text blocks |

So a client dispatching on the SSE frame name renders nothing on gemini, and a
client reading `content` renders nothing on codex. **Both builds are behaving
reasonably**; nothing tells either of them what the field is for.

**Neither difference is visible anywhere a consumer can read it.** SSE frame
names are not in the OpenAPI document at all, and `AgentEvent.content` is
declared `list[dict] | None` with **no description** — while the model's own
docstring calls it *"One SDK message, normalized"*. That is the same defect
class as the `stop_reason` fragmentation item 8 closed: an undescribed field
that each build then fills by its own reading.

**`acp-review.md` §8.4 predicted exactly this** — *"tool calls are not
normalised at all here, so a console cannot render 'the agent is editing
`src/foo.py`' from our document alone"*. It is now demonstrated rather than
predicted, and by our own console.

**The console works today by knowing all three shapes**, which is precisely what
AS-32 exists to stop a client having to do: it dispatches on the payload's
`type` and falls back to `raw.item.text`. That is a workaround living in the one
client we control. A consumer writing their own has no way to discover any of
it.

**What a fix looks like, roughly in order of cost:**

1. **Describe `content`** — additive, no behaviour change, and it is the half
   that makes the rest arguable rather than a matter of taste.
2. **Make `codex-python` populate it**, so the field means one thing. This is
   the only change with a behaviour consequence, and it is a *widening*: a field
   that was null becomes filled.
3. **Decide whether the SSE frame name is contract.** It is not in the schema,
   so today it is accidentally per-build. Either state it, or state that a
   client must read `type` from the payload and ignore the frame name.

**Step 1 moves `/openapi.json`**, so it wants to ride with a cut rather than
land alone — the same reasoning that sequenced item 8.

**Not started, and deliberately not decided here.** Agent Harness has not been
told; whether this is a thread to them or a decision to take first is the
user's, because step 3 is a question about what the contract covers rather than
a defect to fix.

## 3. The web console — Plan 6 — CLOSED 2026-08-14 as a dev tool

**Closed against what it is, not against Plan 6.** `console.html` is a
development tool and the user's decision is that it stays one; Plan 6
describes a product, and that is a separate piece of work whenever it is
wanted. Everything below was either done, decided, or measured away.

| Was | Now |
|---|---|
| **Blocker 1** — no transcript to render for a live session | **done.** Selecting a session rehydrates its conversation from `GET /v1/sessions/{sid}/transcript`, through the **same renderer the live stream uses** — a rehydrated turn that formatted differently would be a second implementation of the hard part. With no database the pane says so, branching on the problem `type` rather than the status, because `persistence-disabled` and `session-not-found` are both 404 |
| **Blocker 2** — disconnect kills the turn | **decided, and it exposed two defects.** A turn does not survive a disconnect; it is cleaned up. `GP-59` and `CX-54` are what that turned up — two of three builds left the agent running and billing |
| **Authentication** — narrowed to a console design question | **answered by what it already is.** `serve.py` proxies same-origin, so the page holds no bearer token and has nowhere unsafe to keep one. That was the item's own conclusion; it needed no build |
| **Renders agent-produced text** | **audited and verified live.** All twelve `innerHTML` sites enumerated: agent-derived content reaches only one, escaped. Driven in a browser with an assistant turn carrying `<img src=x onerror=...>` and a tool name of `<b>evil</b>` — nothing injected, no handler fired, markup rendered as text |
| **Cost display must be labelled honestly** | **fixed, and it was worse than recorded.** The session list rendered `$${(s.total_cost_usd ?? 0).toFixed(4)}`, so a **null** cost printed as `$0.0000` — reading as *free* on the two builds that cannot price at all, which is the exact defect the API corrected by making the field nullable. It now reads `reports_cost_usd`, says "no cost reported" where there is none, and marks a real figure `≥` because it is a floor |

**Two more found while finishing it.** Every assistant turn was labelled
**"claude"** in a file that `impl/common/` serves for all three builds; it
reads `impl.name` now. And the turn-end line preferred `stop_reason`, a
vendor spelling, over `stop_kind`, the closed set every build maps onto —
it shows the typed one first and the raw one only when they disagree.

**Verified by running it**, not by reading it: a `gemini-python` service and
`serve.py` on a local port, driven in a browser. The original text follows.

`impl/common/web/console.html` ships today as a **development tool**: same-origin
via `impl/common/web/serve.py`, no auth, conversation lost on reload. It
deliberately does not attempt what Plan 6 describes.

**Both blockers changed shape on 2026-08-14 (user decision): the console is a
dev tool, so a turn does NOT survive a disconnect — it is cleaned up instead.**
That is the cheap half of blocker 2 and it removes the expensive half entirely:
no durable replayable event log, no `Last-Event-ID`, and — the part that made
this hard — **no need to replace the interrupt** that keeps one turn's output out
of the next. The interrupt stays; it just has to fire reliably.

**Which turned out to be a live defect on two of three builds, now fixed:**

- `gemini-python` released the stream lock on disconnect and **killed nothing**.
  The only `kill_process_tree` sat in `StreamingTurn`'s wall-clock branch, which
  is abandoned along with the generator — so a closed tab left a Node agent
  talking to the model on the caller's key, and the session stuck at `"running"`
  forever. `GP-59`.
- `codex-python` interrupted the turn on a deadline and **not on cancellation**,
  though its own docstring gives the reason for both. Worse, its `finally`
  cleared the turn handle, so nothing could stop the app-server afterwards
  either. `CX-54`.
- `claude-python` was already correct and is the reference: it flags whether the
  turn ended, interrupts **before** `aclose()` so the turn is stamped
  `interrupted=True`, and does it from a `BackgroundTask` because Starlette never
  calls `aclose()` on a body iterator.

**The session is deliberately NOT closed on disconnect** on any of them. A
disconnect is not a statement that the user is done — a backgrounded tab and a
closed one look identical — so a reload inside `session_idle_ttl_s` still finds
its conversation, and the idle reaper reclaims what is genuinely abandoned.

**Nothing about this is visible in any document**: no schema change, no
`/openapi.json` change, no AS-24 impact. Agent Harness already treats a client
disconnect as terminal — its own phase-0 finding measures the relay released in
218 ms and the upstream observing it after 440 ms — so this completes their model
rather than contradicting it. It reaches them when they pull an image carrying
it, which is worth a line in that availability note.

**What is left of the two blockers is ordinary console work**, restated below as
they were written.

- [ ] **Blocker 1 — there is no transcript to render for a *live* session.**
      Partly overtaken: plan-03 A.1 shipped, and `GET
      /v1/sessions/{sid}/transcript` exists. What is still missing is rehydrating
      an **open** session's conversation on page load. Requires
      `AGENT_SERVICE_DATABASE_URL`.
- [ ] **Blocker 2 — disconnect currently kills the turn, and a browser disconnects
      constantly.** Page reload, laptop sleep, backgrounded tab, wifi blip. Needs
      three things together: turns survive consumer disconnect · a durable
      per-session event log replayable by `Last-Event-ID` · **and a different
      answer to the cross-contamination problem the interrupt currently
      prevents.** The third is the hard one and must not be skipped — removing the
      interrupt without a replacement reintroduces one caller's messages ending
      another caller's turn.
- [x] ~~**Authentication stops being optional.**~~ **Narrowed, not removed, by
      0.11.0.** A credential now exists — `AGENT_SERVICE_AUTH_TOKEN`, bearer on
      `/v1`. What is left is the part a browser makes hard rather than the part
      the service was missing:
      - **A browser has nowhere safe to keep a bearer token.** In page source it
        is public; in `localStorage` it is readable by any script that gets onto
        the origin, which is the same origin rendering **agent-produced text**
        (the bullet below). The token is per-instance and grants shell execution
        in that container, so this is not a small leak.
      - **So the console probably must not hold one at all**, and instead be
        served by something that holds it server-side and proxies — which is
        what Studio's relay is, one layer up. Worth checking whether the console
        should be a client of *that* rather than of `/v1` directly.
      - The service-side half is done and this is now a **console design
        question**, not a missing capability.
- [ ] **The console renders agent-produced text** — a new injection vector where
      the untrusted content is produced by the thing the user is talking to, and a
      tool result may contain attacker-influenced file contents. Sanitize; never
      render raw HTML. *(The current dev console builds its DOM with
      `createTextNode` and sets no `innerHTML` from agent output, but this has not
      been audited as a security property.)*
- [ ] **Cost display must be labelled honestly.** `total_cost_usd` is a **floor,
      not the figure** (measured, S6) — an interrupted turn does not move it. A UI
      showing it as "cost" next to an interrupt button will mislead.

## 2b. Multi-implementation platform — Plan 8

**Steps 1–5 landed 2026-08-07.** The implementation is under
`impl/claude-python/`, `ci.py` is one runner at the platform root, and
`spec/` and `docs/to-agent-harness/` sit at the root beside it, with the
acceptance suite and the published OpenAPI documents now the contract's own. `agent-service` is
to front Codex, Gemini and other agent SDKs, and those SDKs are not all usable
from Python — a TypeScript port already exists on `docs/typescript-effect-port`.

Reasoning: [`plans.md` Plan 8](./plans.md#plan-8--multi-implementation-platform).
Target tree, the couplings, and the full argument for each step:
`docs/plan-8-design.md` (removed 2026-08-19; in `git log`). **The checklist below is the work; that
document is why.**

Two decisions taken (user): **monorepo with `spec/` promoted out** of the
Python tree, and **a small core document plus per-provider extensions** rather
than a union type or a lowest common denominator.

### The three facts that decide the order

Measured 2026-08-07, and worth having here rather than one click away, because
they are what makes the sequence non-obvious:

1. **104 path citations in code; 83 survive untouched.** 49 cite
   `implementation-notes.md`, 25 `spike-findings.md`, 9 others — all of which
   move *with* the implementation and so never change relative to anything.
   **Only the 21 citing `spec/` must be edited.** This is why the
   implementation moves down *before* the contract moves up; the other order puts
   all 104 in flight at once.
2. **A frozen signed artifact cites a path that will move, and cannot be fixed.**
   `spec/0.5.1/spike-findings.md:923` names `spec/history/…`.
   Editing it is what AS-24 forbids. **It stays wrong, deliberately** — it is
   prose, not a link, so the `links` stage never sees it, and the canonical copy
   stays correct.
3. **`ci.py` is both the obstacle and the verification.** It hardcodes `ROOT`,
   `CONFORMANCE`, `BOOT_GATES`, `BUNDLE_README` and a `docs/contract` join — and
   it is what proves each step landed. **Every step ends green or it was wrong.**

### Prerequisite — done

- [x] **Free the vocabulary** (0.7.0). `Capabilities.sdk {name, version}` added,
      `sdk_version` deprecated and still emitted. `provider_selectors` was
      deliberately **not** renamed: four clauses and a shipped Studio code path
      depend on it. Description-only sharpening instead.

### Migration — seven steps, mechanical until step 5

- [x] **1 · Move the implementation down** — **done 2026-08-07.** Everything but
      `docs/`, `ci.py` (promoted from `scripts/`), `.ci/hooks/`,
      `.gitattributes` and `.gitignore` is now under `impl/claude-python/`, with
      seven documents (`implementation-notes`, `spike-findings`, `deployment`,
      `persistence`, `design`, and also `deploy-remote` and
      `learning-async-python`, which are this container's and this codebase's).
      `spec/`, `docs/to-agent-harness/` and the platform-level docs stayed put.
      `CLAUDE.md` and `README.md` split in two, one of each per level.
      **Verified:** full run green — freeze 16, links 130/45, unit 590+36,
      container 42/3 and 43/2, gates 8.

      Three things the design did not predict, all recorded where they bite:

      - **`freeze` could not survive the move at all.** `git log -- <path>`
        stops at a rename: before the commit it says "not committed", after it
        says every file was published by the migration commit. Rewritten to
        `git log --follow --numstat`, where a pure rename is `0 0` and an edit
        is not — `docs/ci.md` §freeze has the measurement. **The migration
        commit itself cannot pass the hook** (its subject is committed history)
        and was made with `--no-verify`, with the full run immediately after.
      - **`--follow` alone is worse than useless here, and `-M100%` is the
        fix.** At git's default similarity threshold it walked off the file:
        successive versions of one OpenAPI surface are near-identical, so the
        *addition* of `openapi-0.9.0.json` read as a rename of 0.8.0, that as a
        rename of 0.7.0, back to the commit that created `schema/`. Nine of
        sixteen files reported 2–6 "content commits" and the stage failed. Found
        by running it, not by reading it.
      - **79 citations unchanged, not 83.** Four in impl code cited a document
        that stayed at platform level and gained a `../../`
        (`security-posture.md` ×3, `plans.md` ×1). **Three could not be touched
        at all**: pydantic publishes a model docstring as its schema
        `description`, so `Sdk`'s docstring and the `require_credentials`
        description in `schemas.py` are *inside* the delivered
        `openapi-0.11.0.json` and frozen by AS-24 — rewriting one changed
        `/openapi.json` and failed `test_api_meta.py` and the conformance tier
        on the same run. Repo-root-relative is also the right answer for them
        and for the log line `api.py` emits: their reader is outside the tree.
      - **The markdown link graph crosses the boundary in both directions**, 30
        links' worth. The `links` stage now scans both levels; it is what found
        every one of them.
- [x] **2 · Promote `spec/` and `docs/to-agent-harness/`** to the root — **done
      2026-08-07.** `BUNDLE_README`, the `ROOT / "docs" / "contract"` join, seven
      code citations (all comments and module docstrings, none published) and
      thirteen markdown links. **Verified:** `freeze` reports all seven delivery
      copies and 16 published files; `links` 130/45 with 0 broken; the only
      `docs/contract` strings left in the tree are two git transcripts, this
      checklist, and `plan-8-design.md` describing the pre-move state.

      - **The frozen citation was not fixed and the canonical was**, which is
        §3.3 working exactly as designed. `spec/0.5.1/spike-findings.md:923`
        still reads `docs/contract/history/…` and now points nowhere;
        `impl/claude-python/docs/spike-findings.md:923` was updated and is
        right. Nothing broke mechanically — it is backticked prose, not a link,
        so the `links` stage never sees it, and the manifest row for that file
        is `frozen`, so `freeze` compares it against nothing.
      - **`links` had to be taught the new location.** `spec/` and
        `docs/to-agent-harness/` left `docs/`, and the stage scanned `<level>/docs/**`
        — so it would have gone on passing while silently no longer reading the
        signed bundle, the one directory whose links cannot be repaired by
        editing it. Now named explicitly in `_LINK_LEVELS`.
      - **`spec/history/` was edited, `spec/<version>/` was not.**
        Three link targets and two labels in `history/`, which is provenance
        rather than a delivery directory. No claim changed; only where a link
        points.
- [x] **3 · Move the conformance suite** to `spec/conformance/` — **done
      2026-08-07**, with its own `pyproject.toml`: pytest, pytest-asyncio,
      httpx, and no implementation. **Verified:** both stacks 43/3 and 44/2,
      `gates` 8, and the `unit` stage 570/2/6 plus 20/34/5 — 590/36/11 between
      them, exactly what the single run reported before the split.

      - **"Imports nothing from `agent_service`" was true and not sufficient.**
        Two modules imported `tests.conformance.predicates` — the *package* it
        used to live in — which does not exist any more. Now relative imports,
        which is what a self-contained package should have had all along.
      - **The counts moved by one, and the reason is a test that had to
        follow.** `test_suite_integrity.py`'s second guard asserts that the
        document tier is collected and unskipped; after the move the
        implementation's pytest run no longer sees that package, so the
        assertion would have been made about nothing. It moved into the suite;
        the guard on the in-process suite stayed behind. Hence 43/44 rather than
        42/43.
      - **`unit` runs pytest twice now, and that is the real cost of the
        step.** The document tier — published JSON, no service, and the negative
        control — was reaching a bare checkout only because it happened to sit
        inside the implementation's `testpaths`. Left alone it would have run
        only in `container`, i.e. only with Docker, and a negative control that
        needs a container is a negative control nobody runs.
      - **One thread still reaches into the implementation**, deliberately:
        `conftest.py`'s `_IMPL` finds `schema/openapi-*.json` and the version to
        pin them to. Step 4 moves the documents to `spec/openapi/` and step
        5 gives the contract its own version; the constant goes with them.
- [x] **4 · Split `schema/`** — **done 2026-08-07.** Ten OpenAPI documents to
      `spec/openapi/`; the eight SQL files stay with the implementation.
      `dump-schema.py` writes to both in one run, `--out-dir` overriding both.
      **Verified:** `freeze` reports the same 16 files unchanged, from two
      directories; `links` 131/45; the rest of the run unmoved.

      - **The conformance suite now reaches into `impl/` for one thing only:**
        which version to pin the document tier to. The documents themselves are
        `../openapi/`, beside it. Step 5 takes the last thread.
      - **`test_the_published_spec_file_matches_this_version_of_the_app` stayed
        in the implementation and now reads out of it**, which is right: what it
        asserts is that *this app* agrees with *that document*. It is the one
        test in the implementation's suite that reads a platform-level file, and
        `docs/` is still off limits to all of them.
- [x] **5 · Split the version streams** — **done 2026-08-07, shipped as
      0.12.0.** `spec/VERSION` owns the document version;
      `agent_service/versions.py` holds `DOCUMENT_VERSION` and
      `IMPLEMENTATION_VERSION` and explains which is which;
      `Capabilities.contract` and `Capabilities.implementation` publish both.
      Additive — two new objects, nothing removed or re-typed, so not breaking
      under AS-23. **Verified:** full run green — freeze 18 published files,
      links 134/46, unit 571/2/6 + 20/34/5, container 43/3 and 44/2, gates 8.

      **The design left one thing open and it needed the user: what
      `info.version` means afterwards.** AS-24 keys the published filename off
      that field, so the answer is a contract-facing decision rather than an
      internal one. **Decided (user, 2026-08-07): `info.version` is the
      DOCUMENT's version.** That is what makes `spec/openapi/` one document
      set that every implementation serves, which is what §2's target tree and
      §4's `core-<ver>` naming both assume. AS-24 is unaffected — the served
      version still names the file; only what the number *means* changed.

      What it cost:

      - **`test_the_advertised_version_matches_the_package_version` was
        retired**, because it pinned exactly the pun being broken. Replaced by
        two: served `info.version` == `spec/VERSION`, and
        `capabilities.impl.version` == `pyproject.toml`.
      - **The conformance suite's last thread into `impl/` is gone.**
        `pinned_spec` read the Python package's version to decide which document
        to check; it now reads `spec/VERSION`. Nothing under
        `spec/conformance/` resolves a path into `impl/` any more.
      - **`freeze` reads a different version per directory** — `spec/VERSION`
        for `spec/openapi/`, `pyproject.toml` for the implementation's
        `schema/`. Reading one for both works today and is wrong the first time
        they diverge.
      - **`dump-schema.py` names the two artifacts from the two streams.** The
        OpenAPI file by the document version, the DDL by the build's.

      **Both numbers are 0.12.0 and that is a coincidence of timing** — this is
      the release that split them, so both moved at once. Nothing requires them
      to agree again.

      **Not done, and deliberately: the outward-facing half.** No image was
      built or tagged, and no availability note was written to
      `docs/to-agent-harness/` — writing there is publishing, and item 5 below plus
      the boundary rule both say the user is the channel.
- [x] **6 · Core/extension split of the document — DONE, in a different shape
      than this step drew** (confirmed 2026-08-14). There is no `spec/core/` and
      no `spec/ext/`. What shipped instead is **one computed `core-<ver>.json`
      beside three whole per-build documents** in the snapshot directory:
      `scripts/dump-schema.py` recomputes the core across every build's document
      on each publish and **refuses a core that shrinks** except on a
      `-snapshot`, which is the guarantee the directory split was meant to give.
      Adding the third build removed **zero** leaves from it. The original
      reasoning is kept below, including the measurement that opened the gate.

      **As written on 2026-08-08:** Core/extension split of the document.
      **THE GATE HAS OPENED, and it
      opened by measurement rather than by judgement** (2026-08-08). The
      instruction was *"do not start until step 7 is imminent"*, because the
      core boundary is a prediction until a second implementation tests it.
      **It has now been tested**, and the result is a number rather than an
      opinion: `codex-python` in a container serves a document that differs
      from `spec/openapi/openapi-0.16.0.json` in **151 keys present
      only in the published one, 19 differing, and 7 only in the served one** —
      so AS-24 fails, and it fails for reasons that cannot be fixed in either
      build.

      The three causes are different and only one of them is about prose:

      - **The 151 are an UNBUILT FEATURE and not a divergence** — corrected
        2026-08-08, hours after the sentence above them was written. They are
        `StoredEvent` and neighbours, and **persistence is a feature of
        `agent-service`, not of the agent SDK** (user, 2026-08-07;
        `docs/history/plan-9-design.md` (removed 2026-08-19; in `git log`) §1). The Claude SDK has no
        database either. They return the moment `codex-python` builds it, which
        is what Plan 9 exists to make cheap — so **this number must not be spent
        as evidence about the core boundary.**
      - **The 19** are route `summary`/`description` — each one a build
        describing what it actually does. Making them identical requires one
        document to be **wrong about the service serving it**, which is a worse
        failure than the one it fixes.
      - **The 7** are routes documenting a response the other build has not got.

      Full argument in `impl/codex-python/docs/`codex-python-references.md`. **This
      needs a decision and a version, both the user's.**

      **RE-MEASURED after 0.18.0 and after `codex-python` gained persistence, and
      the proposal is written** (2026-08-08):
      `spec/draft/as-24-core-and-extension.md` (removed 2026-08-19; in `git log`).
      **It inverts what the step assumed.** The delta against
      `spec/0.18.0/openapi-0.18.0.json` is **28 leaves only in the
      published document, 7 only in the served one, 19 differing — and all 19
      differing leaves are prose.** Every path, method, `operationId`, parameter,
      request body and component schema is identical, as is every response schema
      for every shared status code. **There was never a wide boundary to
      negotiate**; there is a narrow one, and it needed a measurement to see.

      What the proposal asks the user for: a version, and four smaller choices it
      recommends answers to. What it proposes:

      - **AS-24 keeps byte equality** and keys the document to the implementation
        (`<impl>-<version>.json`). Containment was rejected — it would
        break the transfer that lets nine clause predicates run on a bare
        checkout with no service, which is the cheapest half of the suite.
      - **A published core document**, prose omitted rather than neutralised, so
        nothing mistakes it for something servable.
      - **AS-32 — every behavioural extension is published on
        `/v1/capabilities`** (user, 2026-08-08). This generalises what 0.18.0
        did with `allow_supplied_sdk_session_id`, and what `auth_enforced` and
        `endpoint_source` do from the consumer's side. **Prose is the only
        difference a client may be required to ignore.**
      - **AS-33 — a build declares every status code its own error table can
        produce.** Without it, "may add status codes" absorbs the defects in
        `codex-python-references.md`, including a 503 *neither* build declares and
        one produces — which a document-to-document diff structurally cannot
        find.

      **Fix `codex-python` §10 before cutting the version**, or the first
      documents published under the new clauses include one that violates two of
      them.

      **BUILT AND GREEN 2026-08-09, on `0.19.0-snapshot`, and the cut is the
      user's.** Core 586 leaves, AS-31 zero failures on both builds, AS-24
      passing against a codex container, `live_tier_blocked_by` gone. The
      instruction above was followed and it was worth following: applying AS-32
      to `codex-python` turned up **a seventh difference the measurement could
      not see** — six `RunOptions` fields and `mcp_servers` that build accepted
      and ignored, one of them contradicting a boolean it published. **A field a
      build ignores leaves no trace in either document**, so no document diff
      would ever have found it; `unsupported_options` is the third AS-32 field
      and exists because of it. Written up as `codex-python-references.md`, and
      the defect underneath it is worth keeping: the helper that computed the
      list was unit-tested six ways and **called by nothing**.

      All four items owed to Studio from the 0.18.0 note are now built —
      `auth_enforced`, `endpoint_source`, `token_usage`, and the problem `type`
      on the supplied-id 400.
- [x] **7 · The second implementation — DONE, and there are now THREE**
      (confirmed 2026-08-14). `codex-python` and `gemini-python` both ship,
      both are containerised, `ci.py` carries `CONTAINER_IMPLS` and runs the
      conformance suite against every image, and all three took real turns
      against real keys on 2026-08-13. The note below is the state on
      2026-08-08, when only the second existed and its live tier was still
      failing; it is kept because the failures it lists are what step 6 fixed.

      **As written on 2026-08-08:** the second implementation, containerised —
      `impl/codex-python/` has a Dockerfile, `compose.yaml`, `compose.ci.yaml`
      and `.env.compose.example`, and `ci.py` now carries `CONTAINER_IMPLS`
      rather than a single `IMPL` for the container-shaped stages.

      **`gates` loops and passes; `container` builds but does not yet run the
      live tier**, and the split is the useful part: the boot-gate tier is the
      genuinely implementation-neutral half of the specification and it passes
      **9 of 10** against the Codex image (AS-3 skips — no provider selectors,
      so the clause has no subject). It passed only after **four** assertions in
      `test_boot_gates.py` stopped naming Anthropic's variables, all four
      invisible until a second image existed.

      The live tier is **37 passed, 9 failed, 3 skipped**, with every failure
      traced to step 6 above or to the supplied-`sdk_session_id` cluster
      already recorded. `ci.py` prints the reason on every run rather than
      filing it, because a tier that is silently not running is
      indistinguishable from one that passes.

      **Two of the bullets below were closed the same day and are corrected
      here rather than deleted, because the order they closed in is the useful
      part: the turn came first, and persistence was buildable only because
      Plan 9 had already made the schema the platform's.**

      Still open on this implementation, in rough order of value:

      - [x] ~~**Three limits are published and enforced by nothing, and two
        status codes are unreachable or undeclared**~~ — **all three closed
        2026-08-08**, documentation half first (user), written up as
        `impl/codex-python/docs/`codex-python-references.md`. `timeout_s` is now
        enforced with a deadline that **interrupts** the turn it abandons and
        answers 504; `max_turns` and `max_budget_usd` are refused and reported
        by `unsupported()` — the first is unenforceable in principle here (the
        SDK reports no monetary figure), the second has no agreed unit; and the
        four `limits` figures nothing applied were withdrawn from
        `/v1/capabilities`.

        **Three things the write-up did not predict, all found by tests:** a
        timed-out turn would have been recorded `timed_out: false`; it would
        have left the **previous** turn standing as the session's last, which is
        misattribution rather than omission; and `registry.py` referenced
        `RunTimeout` without importing it, so the first real timeout would have
        been a `NameError` rather than a 504.

        **And doing the documentation half first paid in a way the plan did not
        state:** it forced the per-route reachability check, which showed four
        of the thirteen "missing" status codes were never missing — declaring
        them would have been a second defect pointing the other way.
      - [x] ~~**No bearer auth**~~ — **shipped 2026-08-08.** Bearer on `/v1`,
        `/healthz` exempt so the container healthcheck still works,
        constant-time compare, 401 as a problem document. `verify_auth` refuses
        nothing now. It is a **second copy** of the Claude build's module:
        `impl/common/README.md` argues it belongs in `agent-spec`, that
        package's pydantic-only guard says otherwise, and restructuring
        `impl/common/` is the user's call — so the anti-drift guard is proposed
        as a clause the specification's suite asserts over HTTP instead.
      - [x] ~~**No MCP**~~ — **built 2026-08-09, and measured through `/v1`**: a
        session configured with a stdio MCP server takes a turn and the tool's
        output comes back as the result. `docs/`codex-python-references.md` §E.

        **The blocker was never configuration.** The servers reach the
        app-server through `--config` overrides and the tool reached the model
        on the first probe — and the call came back *"user rejected MCP tool
        call"*, because an MCP tool call is an **escalation** and every
        permission mode denies escalations. The two the SDK exposes are *deny
        everything* and *let the model approve itself*, and the second is the
        defect fixed the same morning.

        **The answer was a third reviewer the SDK does not expose.**
        `ApprovalsReviewer.user` routes the request to the host, so the service
        is the approver with a policy of its own — and the policy is
        **granular**: it is asked about `mcp_elicitations` and nothing else, so
        shell commands and file changes stay under the sandbox with no
        escalation path. It reaches two SDK privates, guarded by
        `assert_sdk_shape()` which runs as a free test rather than failing at
        the first turn.

        **Two limits, published as `capabilities.mcp` rather than left to a
        400:** no `sse` (that runtime has streamable HTTP only), and an `http`
        server carries a bearer token and no other header. The token travels as
        an environment variable rather than argv — better than the Claude
        build's `--mcp-config`, and still readable by the agent, which is M2's
        conclusion by another route.
      - [x] ~~**`setting_sources` is refused**~~ — **honoured 2026-08-09**, and
        it closed Agent Studio's whole thread. They asked one question: does
        this build have project-level configuration a session can be pointed at?
        **Measured yes** — Codex reads `AGENTS.md` from the thread's cwd and
        `project_doc_max_bytes=0` suppresses it, with the control run first.
        `user` is always on, `project` is selectable, `local` is refused by
        value. **`capabilities.setting_sources` already existed and this build
        was publishing all three while honouring none** — the same shape as
        `allow_mcp_servers: false` being advisory.
      - [x] ~~**Codex's sandbox is unverified under `cap_drop: ALL`**~~ —
        **measured 2026-08-09 with real turns** (user authorised the spend).
        `impl/codex-python/docs/`codex-python-references.md` is the write-up, and
        the question turned out to be the wrong question twice over.

        **`cap_drop: ALL` is not the variable.** The sandbox is **bubblewrap**,
        not Landlock plus seccomp; it needs a user namespace; and Docker's
        **default** seccomp profile gates that on `CAP_SYS_ADMIN`. So it fails
        identically with no hardening at all — **the Codex sandbox does not
        start in an ordinary Docker container**, and every shell command dies in
        `bwrap` before it runs. Fail-closed, so it is a functional hole rather
        than a security one. Only `seccomp=unconfined` fixes it; `cap_add:
        SYS_ADMIN` does not, which matters because that is the reflex fix.

        **The real finding was one layer up, and it was live.** With the sandbox
        able to start, `permission_mode: "plan"` — documented in `options.py` as
        *"read and reason, change nothing"* — wrote `BREACH` to the workspace.
        `ApprovalMode.auto_review` means *ask for approval*, **and this service
        has no approval channel**, so the agent asked "Proceed?" and then
        approved itself 300 ms later: `decision_source: "agent"`, *"Auto-review
        returned a low-risk allow decision."* **Fixed** — every mode is
        `deny_all`, the sandbox is the only axis, and a test fails if
        `auto_review` ever returns. Re-measured after the fix: refused, no file,
        and **no approval event proposed at all**.

        **`deny_all` was measured too, because a fix that denied everything
        would be no better:** `workspace_write` + `deny_all` wrote inside the
        workspace and was refused `/codex-home`. It denies the escalation, not
        the work.

      - [x] ~~**The sandbox's network behaviour is unmeasured**~~ — **measured
        2026-08-09: it blocks egress in every mode this service can reach.**
        `read_only` blocked, `workspace_write` blocked, and
        `sandbox_workspace_write.network_access=true` reached the network. The
        **control** — `curl` from the container, outside the sandbox — returned
        `HTTP:200`, which is what makes the other three rows mean anything: a
        blocked `curl` could otherwise have been a broken image, a proxy or DNS.

        The generated schema already said `network_access` defaults to false.
        **That is a claim about a field, not a measurement of a container** —
        the distinction `apps.*` failed hours earlier.

      - [x] ~~**AS-32 candidate: publish that the sandbox blocks egress**~~ —
        **done 2026-08-09 as a `sandbox` object** (user), once Studio's run
        finished and the hold expired. `{network_access, confines_writes_to_workspace}`:
        `false`/`true` on this build, `true`/`false` on the Claude one, where
        `Bash` is unconfined and the container is the only boundary.

        **The object rather than a boolean, following `mcp`**: there is a second
        member already, and the pair is what makes the two builds comparable
        rather than one of them looking deficient. `true` on the Claude build is
        not a weaker service, it is a different boundary — the field's own
        description says so, because a value a reader misreads as a defect is
        worse than no value.

        Conformance asserts **shape only**: every build must ANSWER, and proving
        `network_access: false` needs a paid turn that each implementation makes
        for itself.

      - [x] ~~**Whether to run with `seccomp=unconfined`**~~ — **decided the
        same day (user): added**, with `cap_drop: ALL` and `no-new-privileges`
        kept. The left column was never the safe option, it was the broken one:
        a container whose agent cannot execute anything is a service missing its
        tool loop, and the operator who discovers that reaches for
        `--privileged`, giving up the filter *and* the capabilities. **This is
        the one place `codex-python` is less hardened than `claude-python`, and
        it is not a preference** — that build's agent needs no user namespace,
        so it keeps the default profile and loses nothing. Do not harmonise the
        two compose files.
      - [x] ~~**`token_usage` published five nulls on every turn**~~ — **found
        while writing the document up, fixed the same day.** The mapping read
        camelCase keys at the wrong nesting level while the raw `usage` beside
        it carried the numbers, and `.get` degrading to `null` made a wrong key
        indistinguishable from an absent one. **It shipped with no test on
        either build**; both have one now, driven by a verbatim measured
        payload.

        **The general form is AS-34** (user, 2026-08-09): *a count the build
        reports is not published as `null`*. Live tier, never names an SDK
        spelling. It is AS-17a made checkable, and **the only one of the four
        defects found today that a test could have caught on its own** — the
        other three needed someone to look.
      - [x] ~~**The paid conformance tier could not run against this build at
        all**~~ — **fixed 2026-08-09.** `test_spec_turns_live.py` opened every
        session with `{"model": "claude-haiku-4-5", "max_turns": 1,
        "allowed_tools": []}`: one SDK's model name, plus an option this build
        answers **400** to. Every test in the tier died at session creation,
        before a clause was reached, for a reason no clause is about — **and
        nothing noticed, because the tier is deselected by default.**

        Replaced by a `cheap_options` fixture built from `/v1/capabilities`,
        which is **AS-32 earning its keep inside the suite that defines it**: it
        drops what `unsupported_options` names, and only when the value is
        non-empty — the same truthiness rule the service refuses on, so
        `allowed_tools: []` survives on a build that lists it. The model comes
        from `AGENT_SERVICE_TEST_MODEL` or not at all.

        **The stripping rule was written backwards on the first attempt** and
        the container said so. It is a pure function now, pinned for free in
        `test_suite_integrity.py` against both builds' real published lists.

        **Verified free, not by spending:** against a codex container the old
        literal returns 400 and the fixture's payload returns **201**; against
        the claude container nothing is stripped and the payload is identical to
        the old literal.
      - [x] ~~**A paid run against codex has never happened**~~ — **run
        2026-08-09 with `AGENT_SERVICE_TEST_MODEL=gpt-5-mini`: 7 passed, 0
        failed.** The first attempt was 5/2, and both failures were worth the
        few cents:

        - **The suite's**: `test_as7_as10` supplied an `sdk_session_id`
          unconditionally and met the 400. AS-13 stopped being absolute in
          0.18.0 and this assertion had not followed — the **third** place in
          the package found encoding one SDK's ability as everyone's
          requirement, after four in `test_boot_gates.py` and the `CHEAP`
          literal.
        - **The build's**: `last_turn.sdk_session_id` was `null` while the
          record beside it carried the thread id, which **AS-16 forbids**. Same
          defect as `token_usage` one field along — `null` where the build
          knows. `_turn_record` hardcoded it; the session's id is the turn's id
          and there was never a value to look up, only one to pass through.

        **AS-34 passing on a real turn is the end-to-end proof of the
        `token_usage` fix**, on a payload rather than a fixture. And the whole
        exercise is the argument for the tier existing: four free suites and a
        document diff all missed the AS-16 defect.

        **Then the same tier against `claude-python` on `claude-haiku-4-5`: 7
        passed, 0 failed** — so **both builds pass the paid tier, and one suite
        measured them**, which is the property the whole platform is shaped
        around and the first time it has actually been demonstrated with money.

        Two things that only the claude run could establish:

        - **The `cheap_options` change cost that build nothing.** It publishes
          `unsupported_options: []`, so the payload is byte-identical to the
          literal it replaced — argued from the code beforehand, now observed.
        - **Its `token_usage` mapping is right on a real payload**, not only
          against the fixture added the same day. AS-34 **did not skip** on
          either build, which is what says the raw `usage` carried counts and
          the named fields carried them too. A vacuous pass would have looked
          identical in the summary line, and that is worth checking for rather
          than assuming.
      - [x] ~~**`default_model: gpt-5-codex` 404s on `/v1/responses`**~~ —
        **re-measured 2026-08-10 with a control, same answer, and the decision
        is now recorded rather than deferred.** Every codex-family model 404s on
        this key while `gpt-5.1` / `gpt-5-mini` / `gpt-4.1-mini` answer 200 —
        and those three being the control is what makes the 404s a fact about
        the models rather than about the key.

        **The default moved to `gpt-5.1`** (user, 2026-08-10). The first answer
        was to leave `gpt-5-codex` alone — one account is not a population, and
        codex-family models are the pairing this SDK is built around. **The
        argument that won is this build's own rule about guessed values**: a
        default nobody here has ever seen work is a guess, one measured twice is
        not, and the failure it produced was not graceful — every unqualified
        turn failing after 30 s. It claims nothing about which model is better
        for coding work; `AGENT_SERVICE_DEFAULT_MODEL` and `options.model`
        remain the levers, and `capabilities.default_model` publishes the value
        so a consumer reads the change rather than inferring it.

        **Proved with one paid turn through `/v1/query`, no model named** (user
        authorised): `result: "READY"`, `is_error: false`, **3.9 s**,
        `token_usage` populated. **3.9 s against 30.5 s is the change**, on the
        same key an hour apart. A `/v1/responses` probe was not this
        measurement — it says the endpoint serves the model, not that a turn
        through this service returns an answer.

        **`0.19.0-snapshot` needed no edit**: all three documents regenerate
        byte-identical, because `default_model` carries no default in the
        schema. **`IMPLEMENTATION_VERSION` is `0.0.10`** (user) — `0.0.9` is
        tagged and delivered, and a tagged version is never free.

        **What a caller actually gets had never been measured, and it is not an
        exception**: the turn completes `status: "failed"` after **30.5 s** —
        the app-server retries the 404 five times, twice — with
        `terminal_reason` naming the model, the URL and a request id. The
        failure is legible; what it costs is half a minute of retrying something
        that can never succeed. `spike/probe_models.py` is the probe, and it
        honours `OPENAI_BASE_URL` so an operator answers this for their own key
        rather than reading ours.
      - [x] ~~**No turn has ever succeeded**~~ — **one has, 2026-08-08.**
        `send()`'s event stream, `turn/completed` absorption and usage reporting
        are exercised.
      - [x] ~~**Resume across a container restart is unmeasured**~~ — **measured
        2026-08-09 through `/v1`: it works.** A turn planted a number, the
        container was restarted with the volume kept, a session created with
        `options.resume` returned the same `sdk_session_id`, and the agent
        recalled the number. **The counter-case is what makes it a finding about
        the volume**: `down -v` and the identical resume is a 400.

        Two things a consumer reads off it: the service's session list is empty
        after a restart and that is correct — `session_id` is this process's
        handle, the conversation is `sdk_session_id` — and **a consumer wanting
        continuity must keep that id**, because without a database the 201 was
        the only place it appeared.

        One rough edge recorded here as unfixed, and **it was fixed the same
        day**: resuming a thread whose rollout is gone answered `400 detail:
        "InvalidRequestError"`, indistinguishable from any other invalid
        request. It is `ResumeTargetNotFound` now, translated at the one call
        site that can raise it, carrying the problem `type`
        `.../resume-target-not-found` and a `detail` that names the remedy. No
        version was needed after all — a problem `type` is a value, not a
        schema. Two tests: the type itself, and that the failed resume leaks no
        session slot even though it happens after a subprocess has started.
      - [x] ~~**Per-session memory cost**~~ — **measured 2026-08-09, and the
        answer was not about memory.** ~20 MiB and **~30 pids** per session, so
        against `mem_limit: 2048m` and `pids_limit: 512` the container carries
        about **16 sessions** — memory at that point is 20% of its budget and
        processes are at 95% of theirs. **`pids_limit` is the binding
        constraint**, which inverts the expectation the item was written with.

        And `max_sessions` is configured independently of it, so a deployment
        can advertise a cap the container cannot carry. Measured: at 510 pids the
        create failed with `500 "Unhandled error" / BlockingIOError` — the
        unclassified case. Now a **503** with a named type, and declared under
        AS-33.

      - [x] ~~**Proposed, not built: a boot check on
        `/sys/fs/cgroup/pids.max`**~~ — **built 2026-08-10 as a WARNING, and the
        judgement about how strict to be was the whole of the work.** The
        lifespan logs when `max_sessions` exceeds `(pids.max − 5) / 30`, naming
        both numbers and the 503 the operator would otherwise meet.

        **It refuses nothing, on this project's own rule rather than a
        preference:** *report what can recover, refuse what cannot*. Exceeding
        the process cap is recoverable without a restart — somebody closes a
        session — and it already has a named 503. A gate would refuse a boot
        about to become correct, which is the argument that settled the
        schema-revision gate in the other direction. **And 30 pids is an
        average**: an agent running a parallel build spends far more, so a
        refusal would promote a conservative estimate to a policy.

        `process_limit()` answers `None` for three situations — not in a
        container, cgroup v1 laid out differently, and `pids.max` reading `max`
        — and all three mean *nothing to compare, so nothing claimed*.
      - [x] ~~**`close_all()` has no shutdown budget, so `stop_grace_period` is
        imposed from outside rather than derived**~~ — **built 2026-08-10.**
        `Settings.shutdown_budget_s` is 60 s, `stop_grace_period` is 100 s = 30
        s drain + 60 + 10 margin, and a test reads all three out of the three
        files that own them.

        **The budget is itself a derivation and that is what makes it
        arithmetic**: the SDK's close is already bounded — `terminate()`,
        `wait(timeout=2)`, `kill()` on any exception, two 0.5 s joins, so ~3 s —
        and a container carries ~16 sessions, so 48 s. **What had no bound was
        N of them adding up**, not any one of them.

        **No force-kill phase, where the Claude build has one, and the SDK is
        why.** `AsyncCodexClient.close()` is `asyncio.to_thread` around a
        synchronous close: cancelling ends the *task* at once and leaves the
        thread running regardless, there is no handle on the subprocess, and the
        SDK's own close already ends in `proc.kill()`. So an overrun close is
        cancelled and abandoned with no grace period for an acknowledgement that
        cannot arrive — spending budget there would only take time from the
        sessions after it. Found by reading the SDK while writing the bound,
        which is the part that would have been guessed otherwise.

        One behaviour change: **only a close that RETURNED deregisters a
        session** now. It used to pop on failure, which made a subprocess that
        may still be alive indistinguishable from one that shut down cleanly.
      - [x] ~~**No persistence**~~ — **built 2026-08-08.** It shares
        `impl/common/agent-spec`'s `db/` layer and the 0.17.0 schema, so
        `ci.py`'s `container` stage now runs **both** deployments against this
        image and the two-kinds-of-404 negative control is reachable here too.
        It is what took 123 keys off the AS-24 delta.

### Cost

Steps 1–4: a day of careful mechanical work, all of it verifiable by a command
that already exists. Step 5: half a day of thinking plus an additive release.
Steps 6–7: the real work, gated on a second SDK being chosen.

### Out of scope

**A gateway multiplexing implementations behind one endpoint.** That is Plan 5's
shape, removed the same day Plan 8 was written, and it does not return by the
back door.

## 5. Release mechanics — the step that had no owner — CLOSED 2026-08-14, it has one

**Superseded by [`versioning.md`](./versioning.md) §5**, which carries this
step in more detail than this item ever did: build and tag, never `latest`,
verify **against the tag** on four checks, push to the local registry, write
the availability note. The registry and Maven host are named there too, and
`CLAUDE.md`'s permission table points at it.

**It has now been executed rather than merely written**: `0.18.10`, `0.0.15`
and `0.0.4` were built, verified from their tags, pushed and announced. The
step that belonged to nobody belongs to a documented procedure that has run.

**The one thing here that `versioning.md` does not say, kept because it is a
design note rather than a step:** automating the *build and verify* half while
leaving the note to a person is the obvious shape if this ever happens often
enough to be worth it. The original item follows.

**Small, and it is here because it bit.** Five versions shipped — 0.6.0 through
0.10.0, including both features Agent Studio had asked for — and **none of them
was reachable by the consumer**, because nothing had put a version-tagged image
on the daemon. Studio's ADR-0020 has its core *assume the image is already
there*, so "somebody builds it" belonged to nobody. It was found by being asked,
not by being noticed.

**The step, so it is not rediscovered:** when a version ships, build and tag
`agent-service-python:<version>`, verify it, and write an availability note into
`docs/to-agent-harness/`.

Verify means *against the tag*, not against a CI image that happens to share a
commit: version served, credential gate exits 3, `agent-service-openapi`
answers without booting, and `spec/conformance/test_boot_gates.py` passes with
`AGENT_SERVICE_TEST_IMAGE` pointed at it.

**Never `latest`.** On this host `agent-service:latest` is the *TypeScript port*
at version `0.0.0`, and it boots and serves with **no credential** where this one
exits 3. A tag is never moved once published.

**Not automated on purpose, yet.** `ci.py` builds an image for the `container`
stage already, so the pieces exist — but publishing is an outward-facing act and
the boundary rule says the user delivers. Automating the *build and verify* half
while leaving the note to a person is the obvious shape if this ever happens
often enough to be worth it. It has happened twice.

**0.12.0 is cut and OWED both halves of this** (2026-08-07, Plan 8 step 5). The
in-repo work is done and green — version, published document, `spec/0.12.0/`
and its manifest row. **No image was built or tagged and no availability note
was written**, deliberately: those are the two outward-facing acts, and the user
is the channel. The pre-boot specification command now also reports
`document_version`, so a release verification against the tag has one more
answer to check.

**0.13.0 is cut, BUILT and VERIFIED; only the availability note is owed**
(2026-08-07). In-repo work green on all five stages: `spec/VERSION`,
both constants in `versions.py`, `pyproject.toml`, `spec/openapi/openapi-0.13.0.json`,
`spec/0.13.0/` and its manifest row, plus AS-28/AS-29 and the index of
where a post-v3.1 clause lives in `spec/README.md`.

`agent-service-python:0.13.0` is on the daemon and was verified **against the
tag**, which is what this section asks for: `info.version` and both
`capabilities` version streams read `0.13.0`, the credential gate exits 3, the
contract module answers without booting and now prints `listen`, and
`test_boot_gates.py` passes 10/10 with `AGENT_SERVICE_TEST_IMAGE` pointed at it
— two of those ten being AS-28 and AS-29 themselves.

**The availability note into `docs/to-agent-harness/` is the one thing outstanding**,
and it is outstanding on purpose for the reason above: it is publishing, and the
user delivers. Note that 0.12.0 has no image and no note, so a 0.13.0 note is
the first Studio would hear of either — it should say so rather than read as
though 0.12.0 had been delivered.

**0.13.0 is now fully shipped** — image tagged, availability note published as
`docs/to-agent-harness/image-0.13.0-available.md`, which also carries 0.12.0 and says
so. Both halves done.

**0.14.0 is cut, built, verified and noticed** (2026-08-07). `contract/` became
`spec/`, and the capabilities join was renamed as a **pair** — `.contract` →
`.spec` and `.implementation` → `.impl` — both removed rather than deprecated.
**It is the first breaking change since the signed bundle**, so AS-23's "notice"
is a real obligation and not a formality:
`docs/to-agent-harness/spec-rename-breaking.md` is it, and it also corrects
`image-0.13.0-available.md`, which names both old fields and cannot be edited.

**The `implementation` half was a second thought, and that is the lesson.**
`contract` → `spec` was cut, committed and noticed before anyone noticed that
`spec` beside `implementation` is a mismatched pair — the fix for one
inconsistency introducing another. It was foldable only because 0.14.0 had not
been delivered yet; an hour later it would have been 0.15.0 and two breaking
changes back to back on the same two fields.

**So: when renaming one half of a pair, check the other half in the same pass.**
`spec`/`impl`, and `sdk` beside them, are now all short and all consistent. The
tie-breaker for the direction was that they name the platform's own two product
directories, `spec/` and `impl/`; `specification`/`implementation` would have
been equally self-consistent and matched neither.

`agent-service-python:0.14.0` is on the daemon and verified against the tag.

**The one thing to watch, so it is not rediscovered as a surprise:** the release
ritual above now has a fourth kind of change in it. A version can be additive
(0.6.0–0.13.0), boot-behaviour-only (0.10.0), a clause without a surface
(0.13.0), or **breaking** (0.14.0) — and only the last obliges a notice under
AS-23 §6 whether or not anyone is known to be affected. `spec/README.md`'s
version table now carries a `Signed` column value of ⚠️ BREAKING for exactly
one row, which is the cheapest place for that fact to live.

**Nothing is required of Studio by 0.13.0.** Reading `listen.port` from the
pre-boot probe instead of their hardcoded `8000` is optional, and their
hardcode keeps working.

**0.18.0 is built, verified and noticed — and so is a SECOND IMAGE** (2026-08-08,
user asked for both). `agent-service-python:0.18.0` and
`agent-service-codex-python:0.0.1` are on the daemon;
`docs/to-agent-harness/images-0.18.0-available.md` is the note. **0.15.0 through
0.17.0 never got a note**, so this one carries them: it says what changed since
0.13.0, which was the last image Studio was told about.

Verified against the tags, both of them, which is what this section asks for:

| | claude 0.18.0 | codex 0.0.1 |
|---|---|---|
| `agent-service-openapi`, no credential, no mounts | 0.18.0 / doc 0.18.0 | 0.0.1 / doc 0.18.0 |
| credential gate | **exit 3** | **exit 3** |
| boot-gate tier | **10/10** | **9 passed, 1 skipped** (AS-3 has no subject) |
| full suite over HTTP | **43 passed, 0 failed** | 43 passed, **1 failed — AS-24 only** |
| bearer auth in the container | works | **works, new today** |

**Three things this release added to the ritual, all of them firsts:**

- **A second image needs a name, and the first one's was wrong.**
  `agent-service-python` predates there being two Python builds. **Renamed to
  `agent-service-claude-python` on 2026-08-10** (user), matching
  `agent-service-codex-python`. The old name stays on the daemon as an alias
  because delivered availability notes tell Studio to pull it; new images get
  the new name only.
- **The two images' tags come from different version streams by necessity.** The
  Claude build's implementation version is 0.18.0 and the Codex build's is
  **0.0.1**; both serve document 0.18.0. Tagging by implementation version is
  what keeps a tag identifying a build rather than a contract. **0.0.1 was not
  bumped**, per the never-cut-a-version rule — if that number should reflect
  today's work (auth, persistence, the turn deadline), that is the user's call.
- **An image can now be published that fails a clause on purpose.** The Codex
  image fails AS-24 by 55 keys and the note says so in its own section, with the
  route-by-route reachability behind all 13 non-prose differences. **A preview
  that states which clause it fails is deliverable; one that hides it is not.**

**`0.19.0-snapshot` has two images and they are the first SNAPSHOT images ever
built** (2026-08-09, user asked). `agent-service-python:0.18.2` and
`agent-service-codex-python:0.0.3`, both verified against the tag, both serving
document `0.19.0-snapshot`. The note is
`docs/to-agent-harness/integration-test-0.19.0-snapshot.md`, and it is an **ask**
rather than an availability announcement: Studio tests, and the cut follows if it
passes.

| | claude 0.18.2 | codex 0.0.3 |
|---|---|---|
| `agent-service-openapi`, no credential, no mounts | 0.18.2 / doc 0.19.0-snapshot | 0.0.3 / doc 0.19.0-snapshot |
| credential gate | **exit 3** | **exit 3** |
| boot-gate tier | **12/12** | **11 passed, 1 skipped** |
| full suite over HTTP | **63 passed, 0 failed** | **64 passed, 0 failed** |
| AS-24 | **passes** | **passes** — it failed by 55 keys as 0.0.1 |

**Then `0.0.4` was superseded by `0.0.5` an hour after that** — `token_usage`
fixed and `seccomp=unconfined` added — and **three rounds of one thread in a day
is the real cost of testing a snapshot**. It is still the right trade: each was a
fact that changed under the consumer rather than a second opinion, and all three
would otherwise have been found after a hash was published. Round 3 says
explicitly that nothing further is sent until they report, which is the discipline
that keeps this from consuming the five-round budget before Studio has spoken.

**`agent-service-codex-python:0.0.3` was superseded by `0.0.4` within the hour,
and the reason is the best argument yet for testing before cutting.** The
sandbox measurement found `plan` self-approving out of read-only in the image
Studio had just been told to pull. The tag was not moved — 0.0.4 was built,
verified against the tag (11+1 gates, 64 passed, exit 3) and announced as round
2 of the same thread. **A snapshot image can be superseded in an hour; a release
image cannot be superseded at all.**

**A snapshot image does NOT freeze the document, and that is the whole point of
§6 of `versioning.md` being about *delivery*.** What froze 0.18.0 was an image
announced as the thing to pull. These are announced as the thing to *test*, the
tag says `-snapshot` nowhere but the document it serves does, and the note says
in its first paragraph that it can change. **If that turns out to be too fine a
distinction for a consumer to hold, the rule to change is this one and not the
other** — but the alternative is that nothing can ever be tested before it is
frozen, which is the failure that produced `versioning.md` in the first place.

**Two implementation versions were bumped rather than reused** (user, 2026-08-09).
0.18.1 and 0.0.2 were set earlier the same day and never tagged; the second round
of changes made them describe a build nobody could pull, so the tags are 0.18.2
and 0.0.3. **An untagged implementation version is still free**; a tagged one
never is.

**A ROW IN A PUBLISHED DOCUMENT WAS TRUE AND UNMEASURED, WHICH IS THE WHOLE
PATTERN OF THIS DAY IN MINIATURE** (2026-08-09). The round-4 verification table
sent to Studio listed *"Paid tier — real turns: 7 of 7"* for
`agent-service-python:0.18.4` and `agent-service-codex-python:0.0.8`. Every other
row was measured on those tags; **that one was carried over from `0.18.2` and
`0.0.6`** — and MCP had changed the session-open path on the Codex build in
between.

**Re-run on both new tags before Studio started: 7 of 7 each.** So the claim was
true, and it was true by luck rather than by measurement, which is the same
distinction `token_usage` and `allow_mcp_servers` turned on. **No correction was
sent, because none was owed** — a document saying "the row I wrote is now
verified" is a round spent on nothing.

**The rule worth keeping: a carried-over number in a table whose heading says
"verified against the tags" is a claim about tags nobody checked.** Re-measure
the row or drop it from the table.

**AGENT STUDIO INTEGRATION-TESTED `0.19.0-snapshot` AND THE VERDICT IS "CUT IT"**
(2026-08-09). Twelve suite failures across the two images and **none attributable
to either build** — every one a Studio-side clause written against one
implementation, or harness rot proved to predate the day by reproducing at an
older commit. Their document lists all twelve with the evidence, which is more
than was asked for.

**They found two things before the cut and one was a real defect of ours.** Both
are fixed, and the pair is the best argument yet for testing a snapshot:

- **`unsupported_options` published prose.** Six entries were identifiers and the
  seventh was `"system_prompt (preset form)"`, so `contains(fieldName)` — the
  obvious client — never matched `system_prompt`. **A difference published in a
  form nobody can branch on is exactly what AS-32 exists to prevent**, and this
  side wrote it deliberately. Entries are `{field, types?}` objects now.
  **Studio offered a cheap fix and a correct one; this side took the correct
  one**, because publishing `system_prompt` as wholly unsupported would have been
  machine-readable and *wrong* — the string form works on that build.
- **`total_cost_usd: 0.0` on a zero-turn session**, against `null` on the Codex
  build for the same state. They raised it as a question. **The answer was that
  `0.0` was the defect and it was the Claude build's**: a cost becomes *known*
  when a turn reports one. It is `null` now, and **no new capability field was
  needed** — `turns` is in the same response, so `turns: 0` + `null` is "nothing
  ran" and `turns: 3` + `null` is "this build cannot price".

**And the answer to "is the Codex image worth pinning" is no, for one reason
nobody had measured:** Studio sets `options.setting_sources` on **every** session
create — it is how its two agent modes become wire-level — so every create is a
400 against that build. The refusal is this side's mechanism working exactly as
designed and is still disqualifying. `setting_sources` as a whole field is not
buildable on Codex; **the narrower distinction they actually need may be**, via
`project_doc_max_bytes`, which is unmeasured and stated to them as a candidate
rather than an offer.

## 4. Small, and genuinely optional — CLOSED 2026-08-14 as a record, not as work

**Neither remaining entry is actionable, and each says so itself.** The
`sessions.py` comments are *local* invariants sitting beside the line they
govern, which this repository's conventions require to stay — the entry
explicitly declines to answer whether any should go. The `sandbox` question is
conditional on bash confinement becoming a goal, which it is not, and the
service cannot set the option today in any case: `RunOptions` does not expose
it. What the SDK source already settles is recorded below.

**So this was never open work.** Its own preamble says these exist "so they are
not rediscovered as gaps" — that is a record, and it keeps its outcome here.

None of these blocks anything. They are here so they are not rediscovered as
gaps.

### ~~`Capabilities.sdk`'s description names a term Studio has retired~~ — FIXED in 0.16.0

It says the word "provider" is *"taken twice over"*, one of those being **Agent
Studio's "LLM Provider"** — renamed **"LLM Endpoint"** on 2026-08-07.

**Not correctable in place.** That sentence is in the published 0.7.0, 0.8.0,
0.9.0 and 0.10.0 documents, AS-24 freezes them, and `ci.py`'s `freeze` stage now
enforces it — so it is not editable even by mistake. The correction belongs in
the next version's description, folded into whatever release happens next rather
than cut for it.

**Cosmetic, and worth stating why.** The point the sentence makes — do not call
the agent-SDK axis a "provider" — is unaffected by what the *other* concept is
called. The distinction still exists; only one of its two labels moved.

**Closed 2026-08-07 as 0.16.0, and the instruction above is why it needed its
own version.** *"Folded into whatever release happens next rather than cut for
it"* was the right call and was not followed: 0.14.0 and 0.15.0 both shipped
without it. A correction that waits for a convenient release does not get one —
it gets skipped until it needs a version to itself. Worth remembering the next
time something is parked as "fold this in later".

### `sessions.py` is still 62% prose, and the bulk is inline comments

317 lines of `#` comment vs 226 of docstring. Unlike the docstrings, these sit
next to the line they govern and are mostly *local* invariants — "ORDERED, not
merely adjacent", "BEFORE the yield, not after" — which this repo's conventions
require to stay. Whether any of it should go is a different question from the one
the original item asked (that one trimmed docstrings and moved the share 63% →
62%), and is deliberately not answered here.

### Does `sandbox` actually confine bash inside *this* container?

Unmeasured, and worth doing only if bash confinement specifically becomes the
goal — note the service cannot set it today: `RunOptions` does not expose
`sandbox` and `options.py` never sets it.

What the SDK source already settles: it is **macOS/Linux only** (a Windows no-op,
as suspected), the nested-container mode is `enableWeakerNestedSandbox` which
*"reduces security"*, and — the premise this question got wrong — it sandboxes
**bash commands**, not the agent. Filesystem and network limits come from
permission rules instead, so `Bash` remains the thing every other decision works
around.

---

## 11. `codex-python` publishes `max` effort and silently narrows it — FIXED 2026-08-14

**Found 2026-08-14**, same pass as item 10.
[`capability-divergence.md`](./capability-divergence.md) §6 has it beside the
other one.

That build publishes the **full** `effort_levels` vocabulary including `max`, and
`options.py` maps `max` to `xhigh` because the SDK's `ReasoningEffort` has no
higher member. **The mapping is deliberate and is defended in the code** — failing
a caller for asking for more effort than an SDK can express helps nobody — and
the narrowing is the right behaviour. What is wrong is that it is **invisible**:
a client optimising for maximum reasoning is told `max` is available, sends it,
and cannot tell it received `xhigh`.

**Smaller than item 10 and worth doing with it**, since both are the same
question — *is what this build publishes what it does*. Two shapes, and the
second is better: drop `max` from that build's published list, or keep it and add
`{field: "effort", values: ["max"]}` to `unsupported_options`, which is exactly
the shape `gemini-python` already uses for `strict_mcp_config: false`. The second
keeps the field working and makes the narrowing readable.

**Either way it moves a published capability value**, so
`capability-divergence.md` moves in the same change — and if it happens after a
cut it needs a version, which is why it is worth folding into whatever ships
next rather than doing alone.

## 8. Two defects ACP's design exposed — `stop_reason` and `PermissionMode` — BOTH CLOSED 2026-08-14

**Closed, and the second half cost no document change at all.** `PermissionMode`
was built 2026-08-11. `stop_kind` — the typed field this item asked for — turned
out to be **already designed, already published on all three documents and
already in the computed core**, with `StopKind`, a shared `derive_stop_kind`, and
the live turn path populating it on every build.

**What was actually left was two surfaces where the field was published and
never filled**, found 2026-08-14 by reading the three builds rather than the
item:

- **`StoredRun.stop_kind` came back null from history on all three.** A stored
  run was rebuilt straight from its database row, and no row carries the field.
  It is now derived on read in `agent_spec.db.queries.stop_kind_of`, from six
  columns the `runs` table already has — **no DDL revision**, so
  `agent-service-database` is untouched. This is the surface the field is worth
  most on: a turn that ran out of wall clock answered `504` and produced no run
  response, so `timed_out` in that row is the only surviving statement that it
  did.
- **`gemini-python`'s `last_turn` did not carry it** where the other two builds
  did, which on that build is the *only* place a timeout is ever readable, for
  the same reason. `GP-58`.

**Nothing in any published document moved** — the field was already declared, so
the `freeze` stage is unchanged and no image is implicated. Seven tests, four
shared and three in the build.

**The original argument is kept below.** Full argument, with the model shapes read
from ACP's official Python SDK: `docs/history/acp-review.md` (removed 2026-08-19; in `git log`) §8. Summary,
because both are ours and both are the failure AS-32 exists to prevent:

- **`subtype`, `stop_reason` and `terminal_reason` are three free-form strings
  side by side with NO descriptions**, and no stated relationship to each other
  or to the four typed flags carrying the same information. **The first version
  of this item overstated it** — it said a client could not tell whether a turn
  ran out of turns, and `limit_hit: Literal["turns","budget"]` answers exactly
  that. The defect is fragmentation, not absence: we answer *why did this turn
  end* in **seven places** where ACP's closed `StopReason` — `end_turn`,
  `max_tokens`, `max_turn_requests`, `refusal`, `cancelled` — uses one, and the
  endings our flags do not cover are reachable only by matching vendor prose.
  **The fix is ADDITIVE and owes no notice**: one typed field beside the three
  unchanged strings, the `usage`/`token_usage` pattern we already own.
- ~~**`PermissionMode` is a union of two vendors' spellings**~~ — **built
  2026-08-11, and the framing was wrong twice over.** `dontAsk` is Claude's too:
  **all six values are `claude_agent_sdk`'s own enum**, adopted as the
  specification's because this was the first implementation. Worse than a union
  of two, not better. Each build now declares `{id, name, description}` objects
  on `/v1/capabilities`, `permission_mode` is an opaque string, and a build
  refuses an id it did not declare with a 400 — `default` and `plan` kept as
  well-known ids, which Agent Harness asked for if cheap. **Breaking in exactly
  one leaf** (`permission_modes.items.type`); the six removed input enum values
  are a widening. See CP-143 and CX-49. This is the union type
  `plan-8-design.md` rejected for the document, surviving in one field, and it
  already produces nonsense: `full_access` is unreachable on Codex and Gemini's
  `auto_edit` maps only by translation. **ACP inverts it** — the agent declares
  `available_modes: [{id, name, description}]` and a `current_mode_id` at
  session creation, and the host presents what it is told. No vocabulary to
  negotiate and no union to grow.

**Only one is breaking, and only half of it** — corrected from "both are". The
`stop_reason` fix is purely additive. `permission_mode` widening from a `Literal`
to an opaque string accepts everything it accepted before; **the breaking part is
just `capabilities.permission_modes` changing from `[string]` to `[{id, name,
description}]`**, which is the same shape as the `unsupported_options` change
Studio asked for and got in `0.19.0-snapshot`. That precedent went cleanly.

**Still after the 0.19.0 cut**, not because they are blocked by it but because a
snapshot with an open ask against it should not move under the consumer testing
it. Order: `stop_reason` first (additive, no notice), then `PermissionMode` —
and ask Studio how they use it before touching a field they may send on every
create.

**Two more from the same review, not defects but real gaps:** tool calls are not
normalised at all here, so a console cannot render *"the agent is editing
`src/foo.py`"* from our document alone (§8.4); and `config_options` (§8.3) is a
better answer to item 7 than item 7 has.

## 10. `gemini-python` accepts `disallowed_tools` and never reads it — FIXED 2026-08-14

**Found 2026-08-14** while refreshing the request-side table for item 7, by
reading the three builds rather than the 2026-08-08 document. Full context:
[`capability-divergence.md`](./capability-divergence.md) §6.

**The field is not in that build's `unsupported_options` and no module consumes
it.** A caller sending `disallowed_tools: ["write_file"]` and no `allowed_tools`
gets the build's default allow-list — **which contains `write_file`** — so a tool
the caller explicitly asked to deny stays available for the whole session. It
does not fail, warn, or appear in any response.

**This is the *accepted and silently ignored* class**, which this platform has
already shipped twice and corrected twice, and which `gemini-python`'s own notes
describe having corrected elsewhere: it is why `effort`, `setting_sources`,
`max_turns` and `max_budget_usd` are refused with a 400 on that build rather than
dropped. `disallowed_tools` was missed.

**Two fixes, and the choice is a real one.** Refusing the field is one line and
is consistent with the other four refusals. Applying it to the generated policy
is the better answer if it is cheap — the policy denies `*` and allows
explicitly, so a deny list is expressible as removing names from the allow set,
and the caller gets what they asked for rather than a 400. **Refusing is not
obviously wrong**: a deny list is redundant against a deny-`*` policy whenever
`allowed_tools` is also sent, and only bites in the default-list case above.

**Not a security boundary either way** — `run_shell_command` is in
`always_disallowed_tools` and the container is the outer boundary — but a caller
that believes a deny list is in force when it is not is exactly the belief the
400 exists to prevent.

## 0a. Three dead paths inside the PUBLISHED document — DONE 2026-08-10

**Closed, and ahead of the cut rather than at it** (user asked). The four field
descriptions carry their fact and name no path; both documents were regenerated;
`core-0.19.0-snapshot.json` came back byte-for-byte identical, so AS-31 never
moved and a generated client changes only in docstrings. New tags because AS-24
is byte equality and a tag is never moved: `agent-service-claude-python:0.18.5`
and `agent-service-codex-python:0.0.9`, both verified from their tags. The
reasoning below is kept because it is the argument for *when* such a change may
be made, and that recurs.


**`schemas.py` has four field descriptions naming a markdown file, and pydantic
publishes a description into `/openapi.json`.** Three of the four name documents
that no longer exist: `docs/spike-findings.md` twice (lines ~374 and ~1121) and
`docs/plan-02-followups.md` once (~1055). The fourth names
`docs/security-posture.md`, which does exist. **A consumer cannot resolve any of
them** — they are paths into a tree they do not have — so the fix is to keep the
fact and drop the path, exactly as every comment in this repository just did.

**It was deferred for a day and the reason was the rule rather than the effort:**
editing a description changes `/openapi.json`, which breaks AS-24 byte equality
against `openapi-0.19.0-snapshot-*.json` — **for the two images Agent Studio was
told to pull and was testing at the time**. What made it doable a day later is
that a snapshot is not frozen until it is cut, and that the fix ships as new
tags rather than as an edit to a delivered one.

**The `references` stage cannot catch these** — they are string literals, not
prose, and that exemption is deliberate (a path in executable code fails a test;
this one is published instead, which is the gap). So the same class of defect
can return without CI noticing.

**The one item with a deadline is closed**: item 6 shipped as 0.15.0 on
2026-08-07, inside the window where both projects were pre-release and the
rename cost one string on each side. **Everything remaining can wait
indefinitely**, so what to do next is a choice about value, not about a queue.

## 6. Rename `agent_service.contract` — DONE, shipped as 0.15.0

**Closed 2026-08-07.** The module is `agent_service.spec` and the invocation is
`python -m agent_service.spec`. It was the last place the word `contract`
survived in code, and it is worth keeping the reasoning because the *shape* of
the decision recurs.

**Why it was not in the 2026-08-07 sweep.** That sweep replaced `contract` with
`specification`/`spec` throughout comments, docstrings, identifiers and the
conformance module names. The module was held back because it is the one place
the word is load-bearing for somebody else: **AS-25 and AS-29 name the
invocation, and Agent Studio's ST-1 runs that exact string before every
container start.** Renaming it is not an edit this side can make alone.

**Why it went ahead anyway.** Neither project has released. The signoff records
ST-1 as *Live* — which means built and passing, **not** immutable — so with no
release on either side, no deployment existed that either spelling would break.
The change was one string on each side. The first release on either side would
have made the same change a flag day: two images, or a module answering to both
names.

**The generalisable bit, since this will come up again:** a consumer's working
code is a *coordination cost*, not a constraint, until somebody ships. What
makes a rename expensive is a release, not a dependency. Check which one you are
actually looking at before deciding a thing cannot be changed.

### What it took

1. **Rename the module**, keeping `main()` as `-m`'s entry point. `contract()`
   became `specification()` — internal, named by no clause.
2. **Restate AS-25 and AS-29** in `spec/0.15.0/README.md`, which
   supersedes them. Neither could be edited where it lives: AS-25 is in the
   signed instrument, AS-29 in 0.13.0's write-once README. Same mechanism 0.13.0
   used to state AS-28/AS-29 rather than amend an instrument that cannot be
   amended.
3. **Record the two newly-stale citations** in `spec/README.md`,
   beside the six from the sweep.
4. **Notice under AS-23 §6**, folded into the existing undelivered notice rather
   than sent as a second document — 0.14.0 had not been handed over either, so
   Studio takes one adoption instead of two.

**Studio's half is one string** in ST-1's probe, and the user is telling them to
align with 0.15.0 directly.

## 0. The argv measurement — RUN 2026-08-07, promise closed

**Done.** `spike/probe_mcp_argv.py`, written up as **M2** in `spike-findings.md`,
delivered to Studio as `docs/to-agent-harness/mcp-secret-argv.md`.

**Answer: yes, and worse than argv.** The whole MCP configuration is serialised
into one `--mcp-config` argument, both transports; measured readable from
`/proc/<pid>/cmdline` as uid 1000, the agent's own user. **And no channel
withholds it** — the CLI runs *as the agent* and must use the secret, so a file
path moves it out of the process table without hiding it, and `hidepid` hides
other users' processes rather than your own. What is available is **audience,
not secrecy**.

Split by how it ages: *the agent can read any MCP secret* is structural;
*the secret is in argv* is true of 0.2.128 and the probe exits non-zero if that
changes.

The original commitment, kept for the record:

**The question:** does programmatic MCP configuration reach the CLI subprocess as
an **argv**, such that a substituted `${secret:NAME}` is readable from
`/proc/<pid>/cmdline` by the agent it was withheld from?

**Transport-independent** — it applies to `headers` on an `http` server exactly
as to `env` on a `stdio` one, because it is about how the SDK hands configuration
to the CLI rather than about which shape carried it.

Three things the write-up must state, because a partial answer here is worse than
none, and all three were promised:

1. **Which channel carries it** — argv, stdin, environment, or a file — and
   whether that differs by transport.
2. **What is readable from inside the container**, tested rather than reasoned:
   the agent's own view of `/proc/<pid>/cmdline`, not an inference from how the
   flag looks.
3. **Whether the answer is pinned to the SDK version.** Measured against
   `0.2.128`; if it is an implementation detail rather than a contract, the
   write-up says so and the finding carries an expiry.

Until it runs, the honest claim — agreed by both sides — is *"not in the
workspace and not in the document"*, never *"not readable"*.

Goes in `spike/` as a numbered case, per this repo's convention, and the result
opens a new thread rather than reopening a closed one.

## 1. Adopt CI — DONE 2026-08-06

**Shipped as `scripts/ci.py`, `compose.ci.yaml` and `.ci/hooks/pre-commit`.
The reference is [`ci.md`](./ci.md)** — process, every setting, troubleshooting,
and a recheck-on-change index. Kept as an item here rather than moved to
*Closed* because the decision it records is *what shape*, not *whether*, and that
is the part someone will want to re-open.

**The decision: no CI service, and no git remote.** The item as first written was
misleading — this repo has no remote (`git remote -v` is empty), so it was never
"add a job", it was "adopt infrastructure". The call was to keep it that way and
drive the same stages from one local command. Nothing to authenticate to, no
secret to store, no queue. The cost is that it only runs when you run it; the
pre-commit hook is the partial answer and deliberately carries only the fast
half.

Two follow-on decisions, both the user's, both reversing something written
earlier the same day:

- **`freeze` also checks `spec/`'s two delivery copies**, against a
  documented decision that they were not enforced. The reasoning it reversed was
  about the *test suite*, and `ci.py` is not a test — [`ci.md`](./ci.md) has the
  full argument and the three checks, one of which reports rather than fails.
- **There is a pre-commit hook**, where this section previously said there was
  not. It runs `--fast --fail-fast` only.

**Read [`ci.md`](./ci.md) before changing any of it.** Three things look
simplifiable and are not: `container` runs the conformance suite *twice* (the
second pass is the only place a negative control is reachable), the script
applies migrations *itself* before starting the service (nothing in the service
does, and the unmigrated state is exactly what the fixture skips on), and the
`spike-findings.md` bundle check *reports* rather than fails (drift there is
normal, and a check that cries wolf takes the real ones down with it).

## 1b. Two asks from Agent Studio — BOTH SHIPPED

Both arrived 2026-08-06/07 through `docs/to-agent-service/` on Studio's side.
**Both are now built and released** — `AGENT_ID` in 0.9.0 and the gate in
0.10.0, on the day they were accepted. Kept here rather than moved to *Closed*
because each records a decision someone will want to re-open: what `AGENT_ID` is
*not*, and the rule that let a boot gate coexist with Q16 and 0.6.0.

### `AGENT_ID` — accepted, all three parts, one migration

Read `AGENT_ID` from the environment; stamp it on `sessions`; stamp it on
`transcript_entries` **in the same migration**. Reply:
`docs/to-agent-harness/agent-id-requirement.1.md`.

**Why part C is not optional.** Stamping `sessions` covers `runs` and `events`
through their existing foreign keys. `transcript_entries` has none — `PRIMARY KEY
(seq)`, keyed by `session_key VARCHAR(256)` against `sessions.id VARCHAR(64)`.
A join *looks* available, because `session_key` is `project_key/session_id[…]`
and that middle segment matches `sessions.sdk_session_id`; it is unsound anyway.
The adapter's own comment records that a `project_key` containing a slash can
collide with a `session_id`, `sdk_session_id` is null until the first turn, and
no index serves a derived substring. **Unsound, and looks sound** — the worst of
the three states.

Design settled in the reply: opaque, unvalidated, nullable, no boot gate, written
at create and never updated, and **structurally unsettable by a caller** because
it is a process constant with no request field to arrive through.

**Plus `SessionRecord.agent_id`, added at turn 4 after Studio corrected an
assumption of this side's.** The reply had decided "DB only, Studio reads the
shared schema under D-08" — inferred from D-04 putting both schemas in one
instance and Studio holding the connection config. **Holding it is not using
it**: Studio queries only its own schema and reaches this service over `/v1`
alone. The column without the field would have been readable by `psql` and
nothing else.

The argument that settled it is worth keeping, because it generalises past this
field: **the version scheme cannot protect a coupling it does not know exists.**
`agent-service-<revision>.sql` is published but is not one of the four bundle files, so a
consumer reading those tables depends on a shape neither side agreed to keep
stable — and a renamed column is a runtime exception in a component that was not
part of the release, where a missing API field is a `null` a client handles.

So: nullable but **not optional** on the record, present always, `null` meaning
"no `AGENT_ID` on that container" and never "not told" — the `database_usable`
rule, and the ambiguity AS-17a rejects.

Two things to watch when building it, both already named to Studio:
- **Both write paths gain the column, and they have opposite failure contracts.**
  `RunRecorder` must never raise; `SessionStore.append` must. Exactly the place
  that gets forgotten when one change touches both.
- **This is the second migration ever**, so the downgrade path does real work for
  the first time.

### The schema-revision boot gate — SHIPPED in 0.10.0

Refuse to start when persistence is configured and the revision this image
expects differs from the one the database is at — **either direction**. Reply:
`docs/to-agent-harness/schema-revision-gate.1.md`.

**It reverses Q16 and 0.6.0, and the reconciliation is a principle rather than an
exception**, which is the part to preserve:

> **Report what can recover; refuse what cannot.**

Q16's three states all recover without a restart — measured, an unmigrated
database flips `database_usable` to `true` under `alembic upgrade head` with the
service still running — so a gate would have refused a boot that was about to
become correct. A revision mismatch cannot do that: the expectation is baked into
the image, so no change to the database makes *this process* right. Second
difference, and the one Studio leads with: those states fail loudly and discard,
while a container *behind* the schema succeeds and **writes wrong** — rows
missing a column the fleet relies on, nothing raising, and D-09 making it
permanent.

**The obstacle, measured: the image ships no migration tree.** `/app` holds
`pyproject.toml`, `uv.lock`, `README.md` and `src/` and nothing else — the same
fact that makes migration out-of-band. So the expected revision must be a **baked
constant** in the package, pinned by a test against the Alembic head. Shipping
`migrations/` instead would put a migration tool inside a container deliberately
forbidden to migrate. The test is part of the feature, not a check on it.

**The window closed the same day.** The second revision shipped in 0.9.0 and the
gate in 0.10.0, so the interval in which a fleet could straddle the `agent_id`
migration undetected was one release rather than an open period.

**One behaviour change**, called out in the delta note because it is the only
case where a container that started yesterday will not start today: persistence
configured against an unmigrated database used to boot and fail on the first
history request. It now exits 3 naming the remedy.

**A refinement the reply to Studio did not make, recorded here because it does
not change what shipped.** The two directions do not share a justification.
*Image behind the database* is the real one — it succeeds and writes rows missing
a column the fleet relies on. *Image ahead* is a convenience: it IS recoverable
by migrating while the service runs, and it fails loudly on first use anyway. The
reply compressed both into "no change to the database makes this process right",
which is true only of the first.

Deliberately **not** bundled: publishing the expected revision on
`/v1/capabilities`. Studio offered it as a nicety; folding it in would stop this
thread closing until two things were settled.

## 2. Authentication — Q6, SHIPPED in 0.11.0 (optional, off by default)

**Read [`security-posture.md`](./security-posture.md) first** (2026-08-07). It
works this up as a threat model and answers "production ready" as an ordered
list — and the order is the useful part: **network isolation, then a relay, then
authentication.** Items 1 and 2 are Studio's, so the largest risk reduction
available is not work in this repository. It also states plainly what
authentication cannot do: prompt injection arrives through an authorised call,
and every auth control is intact and unengaged while it happens.

**Shipped 2026-08-07 as optional bearer auth on `/v1`** — `AGENT_SERVICE_AUTH_TOKEN`
to enable, `AGENT_SERVICE_REQUIRE_AUTH` to refuse booting without one, and
`auth_required` published on `/healthz` and `/v1/capabilities`.

**Off by default, and the deferral was right until now.** What unblocked it was
not a decision to build but a *client with a stated position*: Studio said it
wants this service to prove it is talking to Studio and would rather this service
could **not** know which user is calling. Q6's own note said not to design against
no client; there is one now, and the design followed what it asked for rather than
what a generic answer would look like.

**It is still third.** `security-posture.md` puts network isolation and a relay
ahead of it, both Studio's, and says that if the relay lands this may need no
authentication at all for that client. Built so the option exists.

**What remains true and is not fixed by this:** the token is readable by the agent
this service runs, so it must be per-instance; and prompt injection arrives
through a perfectly authorised call, which no authentication reduces.

The original deferral, kept for the record: (2026-07-31, user) no auth, no TLS,
`127.0.0.1` only.
Adequate for the only deployment that exists, inadequate for every one since
proposed. Recorded in [`open-questions.md`](./open-questions.md) Q6.

It is above item 3 because it **blocks** it: a browser origin in front of an API
whose documented capability is arbitrary shell execution is not something to ship
without it. It is also what stands between this service and any deployment that
is not one operator on one machine.

Do not design it against no client — that is *why* it is deferred rather than
half-built. Revisit when the console becomes real, and design it against that.

## Black-box conformance against a running container — CLOSED 2026-08-06

Was "0. HIGHEST PRIORITY" and earned it: every item under it is now done bar
CI, which is open item 1 above.

**User decision, 2026-08-06.** Every test in `tests/` today drives the app
**in-process** through `ASGITransport`, with a `FakeSession` or a `FakeClient`
standing in for the agent. That suite is green while the following are entirely
unverified:

- the **container** — image, entrypoint, mounts, the boot gates that exit 3
- **uvicorn's HTTP layer** — real status lines, real headers (including
  `x-sdk-session-id`, which no in-process test proves survives a real server),
  real SSE framing and chunk boundaries
- the **real CLI subprocess** — every clause resting on measured SDK behaviour
- the **published spec** as a description of a *running service* rather than of
  the app object it was generated from

A contract signed by two parties cannot rest on a suite that never leaves the
process. `spec/conformance/` is that suite: it imports nothing from
`agent_service`, and each test is named for the contract clause it verifies.
**Three tiers** — a *document* tier over published JSON (no service, runs
everywhere, and includes the negative control); a *free live* tier over HTTP to
a running container; and a *paid live* tier that takes real turns.

**Tiering is by cost, and the split is deliberate:** creating a session spawns
the CLI but sends no prompt, so almost the whole contract is verifiable for
**zero tokens** (T2 measured that creation alone does not even consume a session
id). Only the clauses about turns cost money, and those carry the existing
`live` marker.

See the 0.5.1 conformance write-up (removed 2026-08-19; in `git log`) for the clause-by-clause map.

- [x] Harness + free tier — `spec/conformance/`, skipped unless
      `AGENT_SERVICE_TEST_BASE_URL` points at a running service.
- [x] **Run against a real container** (`docker compose up -d --build --wait`),
      2026-08-06: **21 free tests passed**. AS-24 passed, so the running image
      serves exactly the published `openapi-0.5.1.json`.
- [x] Paid tier: **5 passed** on `claude-haiku-4-5`, one turn each, a few cents.
      AS-8 is now verified through uvicorn rather than an ASGI transport — the
      claim a consumer deletes a stream scanner on.
- [x] **A negative control — done 2026-08-06.** Adopted from Studio's suite at
      sign-off (`spec/history/contract-conformance.md` §3). The suite
      gained a **document tier** it did not have: `predicates.py` holds nine
      clause predicates (AS-1, 5, 7, 8, 11, 13, 17, 17a, 23) as plain functions,
      `test_contract_document.py` runs them over the published spec for
      `pyproject.toml`'s version, and `test_contract_negative_control.py` runs
      the same functions over `openapi-0.2.0.json` and asserts the ones that
      must fail **do**. None of it needs a service, Docker, or a token, so it
      runs on a bare checkout.
      * **It found a defect in its own first run.** AS-8's predicate raised
        `KeyError` on a document with no header at all — which
        `pytest.raises(AssertionError)` does *not* catch, so the check would
        have passed the control while being unable to report the clause. The
        predicate now asserts presence first. This is precisely the class of
        thing a negative control exists to find.
      * **Three predicates cannot tell the two documents apart, and that is
        recorded rather than hidden.** AS-11, AS-17 and AS-23 already held in
        0.2.0 — `RunResponse.sdk_session_id` and the nullable per-turn cost
        fields were there all along, and no route has been removed. They are
        asserted in the *passing* direction instead, so the file is honest about
        what it does and does not discriminate.
      * A `test_every_predicate_is_classified` guard makes adding a tenth
        predicate force the same must-fail/already-held decision.
      * **What this buys the live tier:** AS-24 proves the service serves
        exactly the published document, so a clause proved against the document
        holds for the service. The declaration-only assertion in
        `test_contract_meta.py` was removed rather than duplicated.
- [x] **A harness for the boot gates — done 2026-08-06.**
      `spec/conformance/test_boot_gates.py` starts deliberately misconfigured
      containers and reads the exit code, which the live suite structurally
      cannot: a service that exited 3 is not one anything can talk to. Gated on
      `AGENT_SERVICE_TEST_IMAGE`, **with no default on purpose** — the first
      probe written for this measured a stale `agent-service:latest` from
      2026-08-02 that boots with no credential at all, and reported that the
      gate did not fire. Compose builds `<project>-agent-service`, so the caller
      must name the image. **8 tests, 27 s, no credential, no turn.**
      What it now pins, none of which was verified before:
      * **AS-2 both halves.** No credential → exit 3 naming what to set and the
        escape hatch. Every one of the five published variables satisfies the
        gate — driven from the image's own `agent-service-openapi`
        output, so the matrix cannot drift from the contract. And
        `ANTHROPIC_TOKEN`, the plausible near-miss, does **not**.
      * **An empty value does not satisfy the gate.** `ANTHROPIC_API_KEY=` is
        what `${MISSING}` expands to in a compose file.
      * **AS-25 in the container**: the contract module prints both lists with
        no credential and no mounts, so it demonstrably does not boot the app.
      * **The mounts gate** refuses and names `AGENT_SERVICE_WORKSPACE_DIR`.
      * **A control that boots.** Both gates off → `Application startup
        complete`. Without it, an image broken for an unrelated reason would
        exit non-zero every time and read as perfectly enforced gates.
- [x] **Persistence routes — done 2026-08-06.**
      `spec/conformance/test_contract_persistence.py` covers
      `/v1/sessions/{sid}/transcript` and `/v1/runs/{run_id}` in **both**
      deployments: it probes once over HTTP to see whether the service has a
      database, then asserts what that deployment must do. Verified against
      both stacks — default (41 passed, 3 skipped) and
      `--profile persistence` (50 passed, 2 skipped, three consecutive runs).
      The property under test is that **two 404s are distinguishable**: history
      switched off for the whole service (`type:
      .../persistence-disabled` — the one non-default `type` in `errors.py`) vs
      this id was never recorded. A client acts differently on each, and telling
      them apart by the title's prose would break on a reworded sentence.
      Three things it measured:
      * **A session is recorded at creation, before any turn** — so a console
        can open a new session and get an empty conversation rather than a 404.
      * **But not instantly.** `DatabaseRecorder.session_opened` enqueues to
        `QueueWriter` and returns, by design — no database round trip on the
        request path. **Measured window: 0.25–0.38 s (n=6)** between the 201 and
        the transcript answering 200. The first version of the test asserted 200
        immediately and failed about one run in three. Consumer-visible: a UI
        that opens a session and immediately fetches its history will hit it.
      * **The transcript outlives the live session** — `DELETE`, then
        `GET /v1/sessions/{sid}` 404s while the transcript still answers 200.
- [x] **The 500 that leaked the SQL — fixed 2026-08-06** (user decision).
      Found while covering the routes above, on a fresh volume: a service
      pointed at a database with no tables answered
      `GET /v1/sessions/{sid}/transcript` with `detail` carrying
      `relation "sessions" does not exist`, the full `SELECT` and a bound
      parameter — on an API with **no authentication at all**.
      **The leak was never SQLAlchemy-specific.** It was `to_problem`'s
      fallthrough passing `str(exc)` through for *any* exception this service
      does not classify — which is, by construction, an exception whose message
      nobody has read. Every classified branch above it names a type someone
      chose and whose message was judged; the fallthrough is precisely the
      branch that cannot make that judgement. It now emits the exception's
      **class name and nothing else**, mirroring the line `api.py` already drew
      for logging ("the exception CLASS NAME -- never `str(exc)`"), and keeps
      the name so a report can be matched to the ERROR line holding the
      traceback. Verified against the original reproduction: the client now
      gets `An unhandled ProgrammingError reached the API boundary…` and the
      operator still gets the full traceback in the log.
      Three tests had pinned the old behaviour by asserting the message reached
      `detail`; they now assert it does **not**, plus a new
      `test_the_fallthrough_500_never_echoes_the_exception_message` that also
      covers an exception whose `__str__` is overridden.
      **No version bump and no contract change.** `/openapi.json` is byte-for-byte
      unchanged (the published-spec test would have failed otherwise) and no
      clause covers what `detail` *contains* — AS-21 promises the RFC 7807 shape
      and nothing more. Worth mentioning to Studio anyway if they read `detail`
      on a 500 for diagnostics: on unclassified failures there is now less in it,
      by design.
- [x] **Should an unmigrated schema get its own problem document? NO** —
      decided 2026-08-06, recorded as **Q16** in
      [`open-questions.md`](./open-questions.md#q16-does-an-unmigrated-schema-need-its-own-problem-document).
      Nothing shipped; the question closes a door. Driving every database
      misconfiguration against a real container showed the schema case is not
      distinct — **three of them are indistinguishable from outside**, all boot
      **healthy**, all answer `{"status":"ok"}` on `/healthz`, and all fail the
      first history request with a fallthrough 500: schema never migrated
      (`ProgrammingError`), host unresolvable (`gaierror`), wrong password
      (`InvalidPasswordError`). Classifying one of them names whichever was
      measured first — the same trap the `str(exc)` fix avoided by landing at
      the fallthrough instead of in a SQLAlchemy branch. And the distinction is
      operator-actionable, not client-actionable: `PersistenceDisabled` earned
      its own `type` because two 404s needed different *client* actions, which
      is not the case here.

- [x] **A configured database could be entirely unusable while the service
      reported healthy — fixed 2026-08-06 in `0.6.0`** (user chose `/healthz`
      over a boot gate). The real defect behind Q16, and worse than a 500 on a
      read route: `QueueWriter` catches, counts and **discards every batch**, so
      sessions and events were being thrown away while callers got 201s and
      `/healthz` said `ok`. `Persistence.__init__` builds an engine and never
      connects, so nothing checked the database anywhere.
      `GET /healthz` now reports `database_configured` and `database_usable`.
      Three decisions, each avoiding a measured failure:
      * **It queries a real table, not `SELECT 1`.** A connection check catches
        an unreachable host and a rejected credential and **passes an unmigrated
        schema** — which is the likeliest state of all three, because migrations
        do not run on startup and the image ships no `migrations/`.
      * **`status` stays `"ok"` and the container stays healthy.** The
        healthcheck is `curl -fsS /healthz`, so it reads the status code; a
        non-200 would restart a service whose agent side works, for as long as
        the database is down. Verified: rejected credential →
        `healthy, RestartCount=0`, 200, `database_usable: false`.
        `Health.status` was left as `Literal["ok"]` rather than widened —
        adding an enum member is a re-typing, which AS-23 treats as breaking.
      * **Bounded (2 s) and warns once.** The timeout is what makes the previous
        decision hold when a database *hangs* rather than refusing. The first
        version logged unconditionally and the healthcheck polls every 30 s
        forever; measured at **1 line** per outage afterwards, with an INFO on
        recovery.
      The reason never reaches the caller — boolean out, exception class name to
      the log — per Q16, because `/healthz` is unauthenticated.
      **A boot gate was considered and not taken.** `/healthz` covers the same
      three states *plus* the one a gate cannot: a database that fails after
      boot, and one that recovers without a restart. Reversible if a deployment
      ever wants hard refusal.
      It also simplified the conformance suite, which had been inferring the
      deployment from an unknown-run 404 — an inference blind to exactly this
      state, since a broken database answers 500 and matches neither branch.

## A. Unblocked, small, self-contained — done 2026-07-31

**Done 2026-07-31** (commits `eba512c`, `b2ead56`). Kept here with outcomes,
because three of the six turned out to be different from how they were written.

- [x] **`sessions.py` prose** — five longest docstrings trimmed (`interrupt`
      39→24, `close` 28→24, `kill` 24→20, `set_model` 18→15, `context_usage`
      17→13), safe because `implementation-notes.md` already carries 1,106 lines
      on this module and the docstrings link out to it 29 times.
      **The premise was half wrong:** it blamed the docstrings, but measured,
      docstrings are 226 lines and inline `#` comments are **317**. Cutting 30
      docstring lines moved the prose share 63% → 62%. See the leftover below.
- [x] **`test_registry.py` prose** — it was *backwards*, not merely stale. It
      claimed "in practice create() always wins"; measured 200/200, the
      cancellation wins. Docstring corrected; the dead branch kept and marked
      `# pragma: no cover` as a guard.
- [x] **Env-override tests** for the three registry-sizing settings, plus a
      drift test asserting every `Settings` field appears in `design.md`.
- [x] **`design.md` config table** — **six** fields were missing, not one:
      `include_raw_events`, `database_url`, `log_level`, `require_mounts`,
      `session_store_load_timeout_ms`, `shutdown_budget_s`. The "not settings"
      note below the table also still claimed `database_url` "does not exist
      yet"; corrected in place.
- [x] **The CLI's stderr warning** — measured at once per session (3 sessions, 3
      copies). Documented in the README, including that
      `AGENT_SERVICE_LOG_LEVEL` cannot suppress it, because it is the CLI's
      output rather than this service's logging.
- [x] **Multi-reference directories, verified in a container.** Two mounted and
      listed: boots, `/v1/capabilities` reports both, both readable. Second
      listed but not mounted: exit 3, naming only the missing one.

- [→] **Moved to open item 4:** `sessions.py` is still 62% prose, and the bulk is inline comments** (317
      lines vs 226 of docstring). Unlike the docstrings, these sit next to the
      line they govern and are mostly *local* invariants — "ORDERED, not merely
      adjacent", "BEFORE the yield, not after" — which this repo's conventions
      require to stay. Whether any of it should go is a different question from
      the one the original item asked, and is deliberately not answered here.

## B. Needed a decision first — done 2026-07-31

**Done 2026-07-31.** Every question in
[`open-questions.md`](./open-questions.md) now carries a Decision line; none is
`_pending_`. Six were **already answered by shipped code** and only needed
recording — the same drift the plan checkboxes had. Four were real calls.

- [x] **`require_mounts` now defaults `true`** (Q14, user decision). The
      deployment that most needs the check was the one least likely to remember
      a flag. Cost accepted and paid up front: a checkout exits 3 until
      `AGENT_SERVICE_REQUIRE_MOUNTS=false`, which `.env.example` now carries and
      the suite sets via one autouse fixture. Auto-detecting a container was
      rejected — detection that fails inside one turns the guard silently off.
- [x] **Q1, Q2, Q3, Q4, Q9, Q10 — recorded, not chosen.** The code had already
      decided each: `None` system prompt · `[]` setting sources set explicitly ·
      `raw` on by default · pin + validated subdir · generated mount description ·
      no database access (enforced by popping `AGENT_SERVICE_DATABASE_URL` from
      the environment, since the agent's subprocess has `Bash`).
- [x] **Q6 authentication — DEFERRED, explicitly.** No auth, `127.0.0.1` only.
      Adequate for the only deployment that exists, inadequate for every one
      since proposed. **This is still the gate**: see section C.
- [x] **Q11 retention — indefinite.** Matches shipped behaviour; recorded so the
      absence is a decision. `stream_event` rows are the first thing to prune.
- [x] **Q12 `sandbox` — not used, and settled from the SDK source for $0.**
      L5 was authorised; the installed `types.py` answered it without a probe,
      and reversed the premise. See the leftover below.
- [x] **Q15 — no change.** The three `sessions.py` shapes are already correct in
      asyncio terms; anyio expressing them more directly makes them explicable,
      not wrong.

- [→] **Moved to open item 4:** does `sandbox` actually confine bash inside *this* container?** Unmeasured.
      Worth doing only if bash confinement specifically becomes the goal — and
      note the service cannot set it today: `RunOptions` does not expose
      `sandbox` and `options.py` never sets it. What the SDK source already
      settles: it is **macOS/Linux only** (a Windows no-op, as suspected), the
      nested-container mode is `enableWeakerNestedSandbox` which *"reduces
      security"*, and — the premise this question got wrong — it sandboxes
      **bash commands**, not the agent. Filesystem and network limits come from
      permission rules instead, so `Bash` remains the thing every other decision
      works around.

## B1a. Contract v3.1 — corrections folded in, nothing pending (2026-08-06)

**CLOSED the day it opened. There is no v3.2 and none is owed.** User decision:
a second version to fix a path string and a label costs both sides more than it
buys, so v3.1 carries its own corrections, listed in a change table in its §8 so
that no edit is silent.

- [x] **AS-24 was false when both sides signed it.** The clause promised every
      released version's OpenAPI document was published in this repo; ST-14 has
      Studio pin it and R-20 settles disputes against it. Measured:
      `git log --all -- '*openapi-*.json'` returned **nothing**. `.gitignore`
      carried an unanchored `schema/` pattern, matching that directory name at
      every depth, and it had been swallowing `docs/schema/` since the directory
      was made. A fresh clone had none of them.
      **Neither conformance suite could see it** — both compare the served
      document to a local file, and the local file was there. Fixed: specs
      committed at `schema/`, nothing under it ignored, and the publication test
      now asserts `git ls-files`, because existence on disk is not publication.
      AS-24 reworded to the real path.
- [x] **AS-17 mislabelled `RunResponse.total_cost_usd` as a "per-turn" cost
      field**, and R-14 keyed ownership off that phrase. On a session turn it is
      the SDK's cumulative figure for the connection (S6); `turn_cost_usd` is the
      per-turn one. Found by Studio while checking the clause for its sign-off.
      AS-17 reworded, and **AS-17b added** so the scope of each cost field is a
      guarantee rather than an adjective.
- [x] **§8's tie-breaker names `spike-findings.md`**, which now **ships in the
      bundle** (user decision, reversing an earlier call not to). A rule that
      says "the measurements win" is decided by one party if only one party holds
      them. No rewording needed; the file travels.

## B2. From the Agent Studio requests (2026-08-05)

`spec/history/agent-service-openapi-requirements.md` asked for three additions. All three
shipped the same day (`/v1/capabilities` gains `credential_sources`,
`provider_selectors`, `max_sessions`, `require_credentials`, `require_mounts`;
both turn endpoints gain an `x-sdk-session-id` response header). Version 0.2.0 →
0.3.0. What is left is one decision and two open questions the probe surfaced.

**CLOSED 2026-08-05 in `0.4.0`.** Every item below shipped or was answered with
evidence; the contract in
`spec/agent-service-studio-contract.md` (`git show release-0.5.1:spec/0.5.1/agent-service-studio-contract.md`) carries
the dispositions. Kept here with outcomes.

- [x] **Caller-supplied `session_id` on `POST /v1/sessions`** — shipped. UUID
      required, rejected with `resume` (X5), reported as `sdk_session_id` on the
      201. Reuse of an id that already has a transcript is rejected by the CLI
      (P1) and surfaces as 502.
- [x] **Cost `null` rather than `0`** — shipped, but NOT on the trigger that was
      proposed. `ANTHROPIC_BASE_URL` is not the cause (C3 prices normally); the
      trigger is the reported shape — `subtype: success` with all-zero `usage`
      and empty `model_usage` (C2). Cause of the underlying zero remains
      unestablished and does not need to be known.
- [x] **Mid-connection id change** — still unmeasured (needs a long, costly
      session to force a compaction), now **detectable**: a CLI-reported id that
      differs from the session's is logged at WARNING and not adopted.
- [x] **Wire equality for a CLI-generated id** — measured equal (C2-wire). X4 had
      only covered a pre-assigned id.
- [x] **`include_partial_messages` first message** — measured (P2): still the
      init carrying the session id, so the header is present there too.

<details><summary>The original entry, kept for the record</summary>

- [ ] **Pre-assign the SDK conversation id at `POST /v1/sessions`?** The caller's
      preferred shape — `sdk_session_id` as a *field* on the session record
      rather than an observation — and X1–X5 say it is buildable **today**:
      `ClaudeAgentOptions.session_id` pins the id exactly (X2), it holds across
      turns (X3), and it is the same string the CLI puts on the wire (X4). Two
      things make it a decision rather than a chore:
      * The CLI **rejects `--session-id` alongside `--resume`** unless
        `--fork-session` is set (X5, exit 1), and a fork is a different
        conversation, not a continuation. So pre-assignment must skip the resume
        path — and can, because a plain resume was measured to come back
        reporting **the same id it resumed** (X5 control), which the caller
        already supplied. Both branches are therefore knowable at creation.
      * `sessions.py` currently takes the first init's id and never overwrites
        it. With a pre-assigned value, the init capture never fires and a
        divergence between what we asked for and what the CLI used would go
        unnoticed. Any implementation should still compare and complain.
- [ ] **Can the CLI change its conversation id mid-connection** (after a
      compaction, say)? Unmeasured — every X-case ran short turns. If it can,
      this service reports a stale id and a relay's join goes quietly wrong
      rather than absent. Pre-assignment would not fix it either.
- [ ] **Cost accounting through a third-party gateway reads zero.** X4's proxied
      turn reported `total_cost_usd: 0` while identical un-proxied turns reported
      real figures. Cause not established (n=1). It means a caller relaying model
      traffic through its own gateway cannot use this service's cost fields at
      all and must price from its own token counts. Worth its own probe before
      anyone bills on it. See `spike-findings.md` X4.

</details>

## Deferred and explicitly out of scope

Recorded so they are not rediscovered as gaps.

- **Plan 5 (multi-workspace router) and Plan 7 (Projects) are out of scope**
  (2026-08-06, user decision) and have been removed from the documents, along
  with `router-stack-evaluation.md`. Plan 7 had already been rejected on
  2026-07-31. See the note at the top of [`plans.md`](./plans.md); the full text
  of both is in `git show b7be5fc:docs/plans.md`.
- **Idle accounting uses wall clock**, not monotonic. A clock adjustment can only
  make the reaper fire early or late — not corrupt anything — and `created_at` /
  `last_used_at` are client-facing and *should* be wall-clock. Noted, not a
  defect.
- **`asyncio.timeout` around a `yield` can deliver cancellation outside the
  guarded block.** Pre-existing in `runner.py`; `sessions.py` mirrors it verbatim.
  A shared concern, not a Plan 2 defect — changing it means changing both, and
  Plan 1's path is live-verified.
- ~~**`schema/` is gitignored.**~~ **No longer true, and it was a defect, not a
  choice.** An unanchored `schema/` pattern had been swallowing the published
  OpenAPI documents at every depth, which made AS-24 false while both
  conformance suites passed against local files a fresh clone did not have. The
  specs are committed; see B1a above.
