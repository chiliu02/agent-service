# `claude-python` — references

**Every claim this build's code relies on, in one file, each with a permanent
ID.** The code cites an ID; nothing in the code cites a path. Merged on
2026-08-10 from five documents whose names are no longer worth knowing — 50 of
the 170 citations in this repository had already rotted, and one directory move
was all it took.

## The rules

1. **Code cites this file, by ID, and nothing else.** Not a todo, not a plan,
   not another build's document. `.ci/ci.py`'s `references` stage fails a build
   whose code names any markdown file, and fails an ID with no entry.
2. **This file links to nothing.** A reader holding only this file can never
   hit a dead path, which is the whole failure being fixed.
3. **Each entry is complete.** If a comment needs two entries to make sense,
   the entries are wrong, not the comment.
4. **The comment stays short.** The evidence lives here; the comment says what
   is true and which entry holds the evidence.
5. **An ID is permanent.** A superseded entry is struck through and kept, never
   renumbered — a stale ID in an old commit still resolves.

**Two documents were deliberately NOT merged**, because no code cites them and
neither is evidence: the remote-host runbook and the async-Python primer. They
remain ordinary documents under this build's `docs/`.

## A. The index

| ID | What it settles |
|---|---|
| CP-001 | how to read the code notes |
| CP-002 | Recheck on SDK upgrade — the index |
| CP-003 | Measured SDK facts this codebase is built on |
| CP-004 | db/writer.py — the drop policy |
| CP-005 | api.py — persistence shutdown ordering |
| CP-006 | Guards that are deliberately not test-killable |
| CP-007 | sessions.py — module constants |
| CP-008 | sessions.py — InterruptTimeout |
| CP-009 | sessions.py — TurnResult |
| CP-010 | sessions.py — AgentSession.\_\_init\_\_ |
| CP-011 | sessions.py — AgentSession.close() |
| CP-012 | sessions.py — AgentSession.kill() |
| CP-013 | sessions.py — AgentSession.\_finalize\_live\_turn() |
| CP-014 | sessions.py — AgentSession.\_interrupt\_until() |
| CP-015 | sessions.py — AgentSession.\_acquire\_lock\_until() / \_acquire\_lock\_now() |
| CP-016 | sessions.py — AgentSession.\_sdk\_message\_buffer() / \_discard\_residue() |
| CP-017 | sessions.py — AgentSession.send() / \_send\_impl() |
| CP-018 | sessions.py — AgentSession.\_record\_turn() |
| CP-019 | sessions.py — AgentSession.interrupt() |
| CP-020 | sessions.py — AgentSession.set\_model() / set\_permission\_mode() |
| CP-021 | sessions.py — AgentSession.context\_usage() |
| CP-022 | registry.py — module concurrency model |
| CP-023 | registry.py — SessionRegistry.create() |
| CP-024 | registry.py — SessionRegistry.close() |
| CP-025 | registry.py — SessionRegistry.close\_all() |
| CP-026 | registry.py — SessionRegistry.reap\_once() |
| CP-027 | registry.py — SessionRegistry.start\_reaper() |
| CP-028 | runner.py — \_LIMIT\_MARKERS / detect\_limit() |
| CP-029 | runner.py — build\_outcome() / OutcomeSource |
| CP-030 | runner.py — \_as\_stream() |
| CP-031 | runner.py — Run.events() |
| CP-032 | runner.py — Run.turn\_cost\_usd |
| CP-033 | runner.py — sdk\_version() |
| CP-034 | api.py — the import boundary and `from __future__` |
| CP-035 | api.py — \_summary() / \_turn\_record() / \_record() |
| CP-036 | api.py — create\_app.lifespan() |
| CP-037 | api.py — run\_query\_stream() |
| CP-038 | api.py — create\_session() / get\_session() / delete\_session() |
| CP-039 | api.py — send\_turn() |
| CP-040 | api.py — stream\_turn() |
| CP-041 | api.py — interrupt\_session() |
| CP-042 | api.py — update\_session() (PATCH) |
| CP-043 | errors.py — the fallthrough 500 does not echo the exception |
| CP-044 | db/wiring.py — Persistence.usable() and what `/healthz` may do |
| CP-045 | `options.py` — MCP servers (0.8.0) |
| CP-046 | what the probes are and which SDK they measured |
| CP-047 | Summary of what changed in the design |
| CP-048 | F1 — `ResultMessage` (resolves N1) |
| CP-049 | F2 — `options.env` merges; it is not a whitelist |
| CP-050 | F3 — Undocumented: `SandboxSettings` |
| CP-051 | F4 / F5 — The unions are wider than the design assumed |
| CP-052 | F6 — `session_id` is not uniform |
| CP-053 | F7 — Hook allow/deny shape (resolves the Part C uncertainty) |
| CP-054 | F8 — Setting `skills` re-enables ambient config |
| CP-055 | F9 — Hook events, actual list |
| CP-056 | F10 — Bundled binary |
| CP-057 | Other confirmations (no design change) |
| CP-058 | Live results (L1–L4) |
| CP-059 | L3 — `add_dirs` does not confine anything (design-changing) |
| CP-060 | L4 — `setting_sources=[]` is honoured |
| CP-061 | L2 — message-structure surprises |
| CP-062 | Cost — the finding with the widest blast radius |
| CP-063 | Tool surface is much wider than documented |
| CP-064 | L7 — scoped permission rules are NOT enforced (negative result) |
| CP-065 | Limit-stop markers — measured, not guessed (added during Task 7) |
| CP-066 | Permission enforcement — measured, not guessed (added during Task 11 follow-up) |
| CP-067 | `ClaudeSDKClient` — measured before Plan 2 was written |
| CP-068 | M1 — mid-turn control requests, measured live |
| CP-069 | Windows: the SDK needs the Proactor event loop |
| CP-070 | B1 — an interrupted turn is billed but not accounted, and `max_budget_usd` cannot see it |
| CP-071 | X1–X5 — the SDK conversation id: when it exists, and what reaches the wire |
| CP-072 | C1–C3, P1–P2 — the gateway zero, and the supplied-id edges |
| CP-073 | T1 — a create() that times out in open() does NOT leak the subprocess |
| CP-074 | T2 — creation does not consume a supplied session id; only a turn does |
| CP-075 | M2 — an MCP secret reaches the CLI as an **argv**, and the agent can read it |
| CP-076 | Still unverified — needs a container build |
| CP-077 | Spend |
| CP-078 | what the container is for |
| CP-079 | What crosses the mount boundary |
| CP-080 | Why the container matters for the design |
| CP-081 | Security posture |
| CP-082 | Git configuration inside the container — measured |
| CP-083 | Image requirements — measured |
| CP-084 | The Dockerfile — built, and what it cost |
| CP-085 | The compose file — as shipped |
| CP-086 | Boot without credentials — measured |
| CP-087 | Logging — configured at the entrypoint, measured in the container |
| CP-088 | Shutdown, signals and reaping — measured |
| CP-089 | End to end, live, in the container — measured (Task 7) |
| CP-090 | `max_budget_usd` is blind to interrupted turns — measured |
| CP-091 | Network egress — unrestricted, deliberately, for now |
| CP-092 | Persistence under a real agent — measured (plan-03 Task 9) |
| CP-093 | What is still unverified |
| CP-094 | Environment variable reference |
| CP-095 | Open items this raises |
| CP-096 | the design in one paragraph |
| CP-097 | Purpose |
| CP-098 | Background: what the SDK gives us |
| CP-099 | Architecture |
| CP-100 | Configuration (`config.py`) |
| CP-101 | Workspace layout |
| CP-102 | Permission posture |
| CP-103 | API |
| CP-104 | Data flow |
| CP-105 | Concurrency and lifecycle |
| CP-106 | Error handling |
| CP-107 | Testing |
| CP-108 | Verification |
| CP-109 | Deferred |
| CP-110 | the two halves of the persistence question |
| CP-111 | Part A — Service-side persistence |
| CP-112 | A.1 — Why not hooks |
| CP-113 | Schema |
| CP-114 | Write path |
| CP-115 | Stack |
| CP-116 | Module layout addition |
| CP-117 | A.2 — Conversation continuity via the SDK session store |
| CP-118 | The seam |
| CP-119 | Why this is a safer bet than the `Transport` seam |
| CP-120 | Properties that matter for the write path |
| CP-121 | Schema |
| CP-122 | Retention is ours |
| CP-123 | Module layout addition |
| CP-124 | What this does *not* solve |
| CP-125 | Part B — Agent database access |
| CP-126 | B1. In-process SDK MCP server (recommended) |
| CP-127 | B2. External MCP server (stdio or HTTP) |
| CP-128 | Guardrails, whichever is chosen |
| CP-129 | Part C — Hooks, used for what they are actually good at |
| CP-130 | The credential-leak interaction |
| CP-131 | Deployment additions |
| CP-132 | Open questions this raises |

---

# B. The code, location by location

## CP-001 — how to read the code notes

The reasoning behind the non-obvious code in `src/agent_service/`, organised by
source location. The code carries short comments that state what is true and
link here; this file carries the evidence — what was tried, what failed, what was
measured, and what must be re-checked when the SDK moves.

Everything here is either **measured** (a live probe or a reproduced repro) or
**read from the installed SDK source**. Claims that were once stated absolutely
and later disproved by execution are recorded as corrections, because the fact
that they were wrong is itself the load-bearing part.

Pinned SDK: `claude-agent-sdk==0.2.128`. Spike cases `S1`–`S6`, `L1`–`L7`, the
`M1` mid-turn probe and the `X1`–`X5` session-id probe live in
`spike-findings.md` (CP-046).

## CP-002 — Recheck on SDK upgrade — the index

Every place whose correctness depends on behaviour of the **pinned** SDK version
rather than on a documented contract. Re-verify all of these when the pin moves.

| Where | The assumption | What breaks if it changes |
|---|---|---|
| `sessions.py` `AgentSession._record_turn()` | `receive_response()` ends at the **first** `ResultMessage` (S1), so one drain == one turn | A stream yielding two results would count two turns for one `send()` |
| `api.py` `stream_turn()._frame()` | Same S1 assumption, from the other side: `turn_ended` is set when a `result` frame is *built* | A stream continuing past one result leaves `turn_ended` set for the rest of the turn, so an abandonment after it is not interrupted |
| `sessions.py` `_finalize_live_turn()` | `aclose()`'s unwind is synchronous — `receive_response` → `client.receive_messages` → `Query.receive_messages` → the anyio memory stream has no `try/finally` and no `await` on the unwind path | The `asyncio.timeout(remaining)` around `gen.aclose()` turns an SDK teardown regression into a slow `close()` instead of a wedged registry. It is the belt for exactly this |
| `sessions.py` `_STALE_INTERRUPT_BUDGET_S` | `Query._send_control_request` does `await transport.write(...)` **before** `await event.wait()` (`_internal/query.py`) | Abandoning the wait would stop being "we lose only the acknowledgement" |
| `sessions.py` `_STALE_INTERRUPT_BUDGET_S` | Abandoning that wait leaks exactly **one** entry each in `pending_control_responses` and `pending_control_results` — they are popped only on success and in `_send_control_request`'s `except TimeoutError`, and `asyncio.timeout` delivers a `CancelledError`, which takes neither path | A larger leak per abandoned courtesy interrupt |
| `sessions.py` `_sdk_message_buffer()` | Private internals: `client._query`, `query._message_receive`, `receive_nowait` | Every step is probed; anything unexpected yields `None` and the residue guard silently does nothing. A rename degrades the guard, it does not raise |
| `sessions.py` `_RESIDUE_DISCARD_LIMIT` | The SDK buffer is created with `max_buffer_size=100` (`query.py:138`) | The 1000 cap can never be reached in practice; it exists so the loop is bounded by construction, not by someone else's constructor argument |
| `sessions.py` `_interrupt_until()`, `api.py` `interrupt_session()` | The SDK bounds control requests at its own **60 s** (`_internal/query.py`, `timeout: float = 60.0`, `anyio.fail_after`) and then raises a plain `Exception("Control request timeout: interrupt")` | The 500 declared on `POST .../interrupt` and `GET /v1/sessions/{sid}` is for exactly that unclassified exception |
| `runner.py` `_LIMIT_MARKERS` | `budget_exhausted` rests on a single live observation and is documented nowhere in the SDK | A rename silently regresses budget stops to `limit_hit: null` — indistinguishable from a clean finish |
| `runner.py` `_as_stream()` | The dict shape is what the SDK's own non-streaming path builds internally for a string prompt (`_internal/client.py`) | Behaviour is unchanged either way today; if the wrapping is ever removed, first confirm nothing sets `can_use_tool` anywhere |
| `sessions.py`, `api.py` mid-turn setters | `set_model` / `set_permission_mode` take effect on the **current** turn (M1) | See set_model / set_permission_mode (CP-020) — this is n=1 for `set_model` and Windows-only |
| `registry.py` `create()`'s `except TimeoutError` arm | The SDK tears down a **cancelled `connect()`**, so dropping the un-opened `AgentSession` without calling `disconnect()` leaks nothing (T1: five timeouts aimed inside the measured 0.46s–3.47s spawn window, zero survivors in every case) | A regression there turns every 504 on create into an orphaned CLI subprocess, one per client retry. The code has no defensive cleanup **because none is needed** — if this stops holding, add one rather than assuming it still does |

---

## CP-003 — Measured SDK facts this codebase is built on

| Fact | Source | Consumed by |
|---|---|---|
| `receive_response()` drains exactly one turn and ends on `ResultMessage` | S1 | `_send_impl`, `_record_turn`, `stream_turn` |
| An interrupted turn is reported identically to a genuine failure: `is_error=True`, `subtype="error_during_execution"`. Only `terminal_reason="aborted_streaming"` differs, and that does **not** prove we asked for it | S2 | `ABORTED_TERMINAL_REASONS`, `interrupt()`, `_record_turn` |
| A concurrent `query()` does **not** raise — it queues silently, and turns can be misattributed between callers. The lock is ours to enforce | S3 | `AgentSession._lock`, `SessionBusy` |
| `disconnect()` reliably kills the CLI subprocess (1 child spawned, 0 leaked one second later) | S5 | `close()`, the reaper, `close_all()` |
| `total_cost_usd` is **cumulative for the whole connection**, not per-turn | S6 | `_record_turn` assigns rather than sums; `turn_cost_usd` is a difference |
| An **aborted** turn is attributed nothing at all: `usage` all-zero with `iterations: []`, `model_usage` unchanged (or the model absent entirely), `total_cost_usd` unmoved — while real inference ran. The cost is **lost, not deferred**: the next completed turn's delta is exactly its own usage priced | `spike/probe_interrupt_cost.py` | `_record_turn` reports `turn_cost_usd: null`, never `0.0`, for that shape |
| `model_usage` is **cumulative for the connection** (unlike `usage`, which is per-turn) | `spike/probe_interrupt_cost.py` | `RunResponse.model_usage` schema warning — summing it across turns multiplies by the turn count |
| `max_budget_usd` is enforced inside the CLI against that same unmoved cumulative, so it is **blind to interrupted turns**: 8 start-then-interrupt turns moved it $0.000649 against a $0.05 budget that never tripped, while 6 ordinary turns tripped it at $0.0585 | `spike/probe_interrupt_cost.py` | not fixable here — documented as a security limitation in `README.md` / `deployment.md` |
| `SystemMessage(subtype="init")` arrives on **every** turn, not once per connection | S1/S3 | `_send_impl` takes the first id it ever sees and never overwrites it |
| `receive_response()` does **not** create a fresh stream per call — `Query.__init__` creates exactly one `anyio.create_memory_object_stream(max_buffer_size=100)` for the whole connection (`_internal/query.py:138`), and every `receive_response()` re-wraps it (`client.py:571-610`) | read from SDK source | the entire residue guard |
| Only conversation messages land on that buffer — `control_response` / `control_request` / `control_cancel_request` / `transcript_mirror` frames are `continue`d out of the read loop before the send (`query.py:273-367`) | read from SDK source | discarding residue cannot disturb `interrupt` / `set_model` / `get_context_usage`, which resolve through `pending_control_responses` |
| A mid-turn control request does not disturb the in-flight turn; **no lock is needed for safety**. Both setters apply to the **current** turn | M1 | `set_model`, `set_permission_mode`, the PATCH route's prose |
| The SDK conversation id **does not exist until the first turn**: `get_server_info()` carries no session id and nothing arrives on the connection before `query()` | X1 | why `sdk_session_id` cannot be a field on `POST /v1/sessions` today, only a header on a turn |
| The id the CLI reports on init/result is byte-for-byte the `x-claude-code-session-id` it sends to the model API | X4 | what makes `x-sdk-session-id` usable as a relay's join key at all |
| `ClaudeAgentOptions.session_id` pins the conversation id exactly (`--session-id=<uuid>`), and it holds across turns — but the CLI **rejects it alongside `resume`** unless `fork_session` is set | X2, X3, X5 | not consumed yet; it is the mechanism behind the open pre-assignment decision in `dev-todo.md` |
| A plain `resume` comes back reporting the **same** SDK id it resumed | X5 control | a resumed conversation is not a new conversation; n=1 |

---

## CP-004 — db/writer.py — the drop policy

`enqueue()` is a plain `def` that appends to a deque. That is not a style choice:
an `async def` would put an await point between `normalize()` and the `yield`
that hands a frame to the SSE consumer, and would add a cancellation point inside
`_send_impl`'s drain — the one function whose `recorded` / `_turn_abandoned` /
`except BaseException` interplay is the most delicate code here. `registry.create()`'s
insert has the same no-suspension-point property for the same class of reason.

**The drop order is per-item-kind, and O(1).** Above `soft_capacity` an incoming
`stream_event` is refused; run and session rows are still accepted, because losing
a run row orphans every event referencing it. Above `hard_capacity` anything is
dropped, loudly — an unbounded queue kills the process, which takes the agent with
it.

The first version scanned the deque to *evict* the oldest queued `stream_event`,
which is O(n) per enqueue with n up to `soft_capacity`: quadratic under exactly the
sustained pressure that makes the policy matter. Refusing the incoming item achieves
the same goal without touching what is queued.

Pinned by `tests/test_writer.py::test_stream_events_are_dropped_before_anything_else`,
`::test_run_and_session_rows_survive_past_the_soft_mark` and
`::test_past_the_hard_ceiling_even_run_rows_are_dropped_and_logged`.

**A claim here that did not survive testing.** The `await asyncio.sleep()` on the
batch-failure path was added partly as a starvation fix, reasoning that a
synchronously-failing sessionmaker never reaches an await and so the drain loop
would discard a whole backlog without yielding. A test written to pin that
**passed with the sleep removed** — at the configured bounds the worst case is
~100 iterations of a raise, which a co-running task does not detectably notice.
The sleep stays, justified as backoff against a slowly-failing database; the
vacuous test was deleted rather than kept as false coverage.

## CP-005 — api.py — persistence shutdown ordering

`close_all()` → drain writer → dispose engine. Both arrows are load-bearing:

1. **Drain AFTER `close_all()`.** Closing the sessions is what *produces* the final
   `session_closed` rows, so draining first records every session as still open.
2. **Dispose AFTER the drain.** The writer must finish with the pool before the
   engine disposes it, or that last batch fails against a closed pool.

Bounded by `wiring.DRAIN_TIMEOUT_S` (5s), well inside `shutdown_budget_s` (60s),
which is dominated by closing agent sessions. A healthy database drains in
milliseconds; a slow one is exactly when waiting is pointless, and spending a
meaningful slice of the budget on observability rows would trade an agent's clean
exit for a log entry.

## CP-006 — Guards that are deliberately not test-killable

Three places keep a guard that no test can kill on its own. They are listed here
so nobody spends a round trying to pin them, and so nobody deletes them for
being "uncovered".

| Where | The guard | Why no test can kill it | Pin the behaviour instead |
|---|---|---|---|
| `sessions.py` `_send_impl` | `or self._closing` appears in **both** the pre-lock and the in-lock check | A first advance can only suspend between the two by queueing behind `close()` itself — which implies `_closing` is already set, so whichever check survives catches it | `test_a_turn_cannot_start_while_close_is_disconnecting`, which kills removing **both** |
| `sessions.py` `interrupt()` branch 2 | `or self._closing` in `if not self._turn_abandoned or self.status == "closed" or self._closing` | Defensively unreachable: every path that sets `_closing` also ends with the turn finalized, so `_turn_abandoned` is already false by the time a courtesy interrupt could arrive | Nothing. It costs one comparison and means this branch cannot become the next hole in `_closing` if either of those two facts changes |
| `sessions.py` `interrupt()` branch 2 | the re-check of `status` / `_turn_abandoned` **under** the lock | Nothing awaits between the checks above and the acquisition, so on a single-threaded loop the state cannot have changed yet | Nothing. It re-reads exactly the fields a concurrent turn rewrites; the day someone adds an `await` between those two points — a one-line, harmless-looking change — this is what keeps the branch honest |
| `registry.py` `close_all()` | `session = self._sessions.get(sid); if session is None: continue` | No suspension point between the scan and the get (releasing `_lock` does not yield), so the session cannot have vanished | Belt-and-braces for the day someone adds one |

---

## CP-007 — sessions.py — module constants

### `ABORTED_TERMINAL_REASONS`
`{"aborted_streaming", "aborted_tools"}` — the measured `terminal_reason` values
for a turn stopped mid-stream (S2). **Necessary but not sufficient** evidence of
an interrupt: pair it with the session's own request stamp. An aborted turn
nobody asked to stop is a crash, not an interrupt.

### `_RESIDUE_DISCARD_LIMIT = 1000`
Hard ceiling on the residue pre-drain. The SDK's buffer is created with
`max_buffer_size=100` (`query.py:138`), so this can never be reached in
practice. It exists so the loop is bounded **by construction** and not merely by
an assumption about someone else's constructor argument.

### `_ACLOSE_RETRY_INTERVAL_S = 0.005`
How long `close()` waits between re-attempts at `aclose()`ing the live turn's
generator. Large enough not to spin the event loop, small enough that a turn
abandoned right after an advance returns is reclaimed in ~one tick.

**Measured:** the tick is not 5 ms everywhere — 5 ms is a *floor*. On this
project's Windows development machine `asyncio.sleep(0.005)` takes a **median of
15.5 ms** (min 8.2, max 16.4 over 60 samples), because the platform timer
granularity is ~15.6 ms. The fuzz's median `close()` of **15.9 ms** is exactly
that one tick. Linux should be far closer to the requested 5 ms, but this
project has only ever been run on Windows — treat that as expectation, not
measurement. Either way the loop is bounded by the deadline, not by this
constant.

### `_STALE_INTERRUPT_BUDGET_S = 1.0`
How long `interrupt()`'s abandoned-turn branch may hold the session lock waiting
for its control request to be answered.

**A dedicated constant, deliberately NOT `self._limits.timeout_s`.** An earlier
version borrowed the turn budget, and that was measured: with the service default
`timeout_s=600` and the SDK's control bound modelled at 2 s, **one ordinary SSE
hangup** (`close_stream()` → `interrupt()` → branch 2) stalled `registry.close`
at **1.960 s** and `create` / `reap_once` / `close_all` at **1.944 s** each — the
whole registry, behind one session's courtesy interrupt. Real-world that is
`min(timeout_s, the SDK's 60 s control bound)`, and if the SDK's bound ever fails
to fire it is `timeout_s`: 600 s by default and up to 1800 s. That second bound is
precisely what bounding `close()` existed to remove, reintroduced one level of
indirection away.

A courtesy interrupt is not a turn and must not borrow a turn's budget. What it
is worth waiting for is one control round-trip on a healthy CLI —
milliseconds — so 1 s is roughly an order of magnitude of headroom over healthy
and small enough that no registry-visible operation can be blamed on it.

**Why giving up is safe, precisely.** Three explanations were tried; only the
third survives.

1. *"The residue guard covers it."* **False, measured.** The abandoned turn's
   trailing `ResultMessage` arrives **during** the next turn's drain, so
   `_discard_residue` — which can only drop what is already buffered when that
   turn starts — misses it, and the next turn is recorded as
   `result='LEFTOVER FROM TURN 1'` with `last_residue_discarded=0`. That is
   exactly the misattribution `api.py`'s `close_stream()` comment says is not
   coverable from inside `sessions.py`. Nor does `close()`/`disconnect()` cover
   this path: `close_stream()` swallows the failure and leaves the session
   **open** for the next turn.
2. *"Already on the wire, so the CLI is still told to stop."* **An over-claim,
   disproved by execution.** Run against the real `Query` with a transport whose
   `write` blocks, the cancellation lands **inside** `transport.write` and
   `write_completed == 0` — nothing was sent at all.
3. **What actually holds** is the order inside the SDK: `Query._send_control_request`
   does `await self.transport.write(...)` **before** `await event.wait()`
   (`_internal/query.py`). So in the normal case the request is on the wire by the
   time we stop waiting, abandoning the wait cannot un-send it, and what we give
   up is the **acknowledgement** rather than the interrupt. That is why this
   raises `InterruptTimeout` instead of returning quietly, and why the residue
   window above stays open exactly as wide as it already was. The residual bad
   case is a **wedged STDIN pipe** (the subprocess not draining it), as distinct
   from a subprocess that reads the request and never answers. That residual is a
   strictly worse-off version of the same trade this constant already accepts — a
   missed courtesy plus the pre-existing residue window — and it does not change
   the decision, only the honesty of the reason.

**Leak, bounded and accepted.** Abandoning the wait leaks exactly **one** entry
each in the SDK's `pending_control_responses` and `pending_control_results`
(measured; previously only read from source). They are popped only on the success
path and in `_send_control_request`'s `except TimeoutError`, and what
`asyncio.timeout` delivers into `event.wait()` is a `CancelledError`, which takes
neither. One pair per abandoned courtesy interrupt, on a connection that is
usually being torn down anyway — preferable to the registry-wide stall this
constant exists to prevent. **Recheck on any SDK upgrade.**

---

## CP-008 — sessions.py — InterruptTimeout

Typed rather than the bare `TimeoutError` that `asyncio.timeout` raises, for two
reasons measured at the HTTP boundary.

- ~~`str(TimeoutError())` is `''`, so a bare one reaches `errors.to_problem`'s 500
  fallthrough as `{'title': 'Internal server error', 'detail': ''}` — strictly
  less than the SDK's own `Exception("Control request timeout: interrupt")` said
  before this branch was bounded, in a service whose stated purpose is
  observability.~~ **No longer true as of 2026-08-06:** the fallthrough stopped
  echoing exception messages, so a bare `TimeoutError` and the SDK's `Exception`
  now produce the *same* detail. This reason is dead; see
  errors.py — the fallthrough 500 (CP-043).
- A time-budget overrun is a **504** everywhere else in this codebase
  (`RunTimeout`; `SessionOpenTimeout`, whose docstring reads "same bucket as
  RunTimeout"). A 500 would answer the same class of condition two ways.

---

## CP-009 — sessions.py — TurnResult

`turn_cost_usd` is what **this** turn cost, as opposed to `outcome.total_cost_usd`,
which is the connection's running total (S6). The delta is computed once, in
`_record_turn`, at the only moment both numbers are in hand.

`None` means "nobody can say" — no `ResultMessage`, one with no price, or an
**aborted** turn whose cumulative did not move — and is deliberately distinct from
`0.0`, a turn that genuinely cost nothing. Every other construction of `TurnResult`
in `_send_impl` leaves it `None`, which is correct: none of them reached a
`ResultMessage`. The aborted case is the one that had to be *added*; see
`_record_turn` (CP-018).

---

## CP-010 — sessions.py — AgentSession.\_\_init\_\_

The state fields, and why each has the shape it has.

### `_turn_seq` / `_interrupt_for_turn`
An interrupt is recorded against the **specific turn** it was raised against,
never as a bare boolean. A bare flag can only answer "was an interrupt requested
at some point", which is the wrong question the moment the turn it was meant for
ends without consuming it. `_turn_seq` counts turns **started** (unlike the
public `turns`, which counts turns that reached a result), so it is a stable
identity for the turn in flight.

### `_residue_suspected`
Set whenever a turn ends without consuming its own `ResultMessage`; tells the
next turn to pre-drain the connection-scoped buffer first.

### `_turn_abandoned`
Set when a turn ends **abnormally** — cancelled, abandoned, force-closed or timed
out mid-drain — as opposed to merely ending without a `ResultMessage`. The
distinction is the whole point: `_residue_suspected` covers both, but only
`_turn_abandoned` means the CLI subprocess is **still producing** the rest of that
turn and can still be told to stop. Read (and consumed) by `interrupt()`.

### `_closing`
Set **once**, by `close()`, the moment it commits to tearing the session down —
before it finalizes any live turn and before it disconnects. A one-way latch,
never cleared.

It exists because `status` **cannot** carry this. `status = "closed"` is assigned
only *after* a successful `disconnect()`, deliberately, so a **failed** disconnect
leaves the session non-terminal and a retried `DELETE` genuinely retries (pinned
by `test_close_does_not_report_success_when_disconnect_fails`, which kills the
obvious "just hoist the assignment" fix). That leaves a window — `close()`
suspended inside `disconnect()` with `status` still `"idle"` — which the
courtesy-interrupt change **widened**, because `close()` now skips the lock when a
courtesy interrupt holds it, so the lock can fall free during that window.

**Measured in that window:** a turn started there ran to completion against a
session being torn down (`queries == ['hi', 'second turn']`, `turns=1`), putting
`disconnect()` against a draining turn — behaviour `registry.py` explicitly
records as unmeasured.

Read by `_send_impl` (both guards), by `interrupt()`'s courtesy branch, by both
setters, and by `context_usage()`: once `close()` has committed, this session
takes **no new work of any kind**.

### `_courtesy_interrupt`
True only while `interrupt()`'s abandoned-turn branch holds `self._lock` across
its control request. A courtesy interrupt is not a turn: `close()` reads this and
refuses to spend its budget waiting for a lock held only by one. Written and
cleared inside that lock, so it can never outlive it.

### `self.model` / `self.permission_mode`
The **resolved** configuration, echoed by `SessionRecord`. Read off `sdk_options`,
not off `options`: `build_options` is where a null model becomes
`settings.default_model` and a null permission mode becomes
`settings.default_permission_mode`, and reporting the request's nulls would say
"no model" about a session that certainly has one. Kept in step by `set_model` /
`set_permission_mode`, which are the only things that can change them — and which
write **after** the control request returns, so this reports what the SDK took
rather than what was asked for.

**Only these two.** Every other resolved option is fixed for the session's
lifetime, and some of it is not ours to hand back: `sdk_options.system_prompt`
carries caller-supplied content with this service's own workspace layout
appended, and `SessionRecord` is what `GET /v1/sessions` returns for every session
at once.

### `last_residue_discarded`
How many stale messages the last pre-drain discarded. Observability only — a
non-zero value means a previous turn was abandoned with messages still in flight.
**Reset at the top of every turn**, so it describes the current turn rather than
the last abnormal one. It used to be written only inside the residue branch, so
after one abnormal turn left a count behind, every ordinary turn afterwards kept
reporting it — a stale number describing a turn two turns ago, on the one field
whose entire purpose is to say what just happened.

### `_active_gen`
The generator behind the turn currently holding `self._lock`, or `None` between
turns. Published from **inside `_send_impl` itself**, immediately after it wins the
lock — see `send()` / `_send_impl()` (CP-017)
for the measured failure of publishing it eagerly. Read only by `close()`, to
force-finalize an abandoned turn.

---

## CP-011 — sessions.py — AgentSession.close()

Idempotent. `disconnect()` reliably kills the subprocess (S5).

`registry.py`'s reaper never force-closes a `"running"` session, but
`SessionRegistry.close()` — driven by an explicit `DELETE /v1/sessions/{sid}` —
has no such guard and calls this unconditionally, including while a turn is in
flight. Racing `disconnect()` against an actively draining turn was **never
measured**, so this never disconnects out from under a running turn: it always
gives that turn a defined way to end first.

### The two cases, and why they are not a stable property

* **Actively driven** — some task still holds an in-flight `send()` advance.
  `interrupt()` (the measured S2 path) plus waiting on `self._lock` is correct
  here and stays bounded for as long as that remains true: the other task's own
  `asyncio.timeout(self._limits.timeout_s)` is live and will fire on *its*
  schedule.
* **Abandoned** — nobody has an outstanding advance at all. A caller advanced the
  generator partway and simply stopped (no `aclose()`, no cancellation), exactly
  what a disconnected SSE consumer leaves behind. Nothing will ever resume it, so
  it will **never** reach its own `finally`, and `async with self._lock:` alone
  hangs forever. Worse, that generator's `asyncio.timeout()` scope is still armed
  (its `__aexit__` never runs either): a dangling `call_at` callback that cancels
  whichever task *originally* advanced it, whenever its deadline arrives,
  wherever that task happens to be by then — reproduced landing inside this
  method's own lock-wait when that task later also drove `close()`, delivering a
  bare `CancelledError` no `except Exception` can catch.

A turn can flip from the first to the second at any moment. That is the whole
difficulty.

### Why `aclose()` first, and why `RuntimeError` is retried rather than swallowed

Calling `self._active_gen.aclose()` directly (rather than waiting) mirrors
`api.py`'s `close_stream()` `BackgroundTask` — the same "an abandoned generator is
otherwise reclaimed only by non-deterministic GC" problem, solved the same way.
`aclose()` throws `GeneratorExit` at the exact suspension point, which unwinds
through the turn's `try/except BaseException: ... raise` and `finally`
**synchronously** — releasing `self._lock` and exiting the dangling
`asyncio.timeout()` scope (cancelling *its* timer via a normal `__aexit__`, for
once) deterministically, with no wait and hence nothing for a stray cancellation
to land on.

`aclose()` on a generator with a genuinely in-flight advance instead raises
`RuntimeError` (Python refuses to re-enter a running generator from a second
task).

> **Tried and failed:** reading that `RuntimeError` as "this is the actively
> driven case, so that task's own `timeout_s` bound will end it", swallowing it,
> and falling through to a bare `async with self._lock:`. **That inference is
> false, and it was an unbounded hang.**

`RuntimeError` proves only that an advance is in flight **at that instant** — not
that anyone will keep driving the generator. The failing sequence is exactly the
SSE consumer this design protects: a consumer parked inside `gen.__anext__()` (so
`aclose()` does raise `RuntimeError`), that advance returns, the consumer takes
the event and **abandons** the generator, and its task exits. The turn is now
abandoned, but `close()` has already committed to the lock-wait, and the turn's
own `asyncio.timeout()` cannot save it: its dangling `call_at` cancels the task
that *first* advanced the generator, and that task is gone, so `.cancel()` is a
no-op.

**Measured against that shape:** with `timeout_s=0.05`, `close()` was still hung
**1.03 s** later, `status == "running"`, the lock held and the interrupt stamp
leaked. A randomised **400-round** interleaving fuzz hung in **7 %** of rounds.
Blast radius at the time: `SessionRegistry.close()` held the registry-wide lock
across `await session.close()`, so one `DELETE` in that window deadlocked
`create()`, `reap_once()` and `close_all()` — and the orphaned session stayed
`"running"`, which the reaper skips forever.

So `RuntimeError` is an **observation, not a verdict**, and it is re-taken:
`_finalize_live_turn` retries `aclose()` while the session lock is still held,
every `_ACLOSE_RETRY_INTERVAL_S`, until the deadline.

**Measured after the fix:** the repro above closes in **~30 ms** end to end (of
which ~10 ms is the repro's own scaffolding) instead of hanging, and **2500**
randomised rounds produced **0 violations** with a **77 ms** worst case. A turn
that is genuinely, continuously driven keeps raising `RuntimeError` — on a
single-threaded loop a consumer that is always inside `__anext__` is never
observed otherwise — so it drains normally and `close()` waits for it, exactly as
originally intended. A consumer caught in a **gap between advances** does get its
generator force-closed; that is deliberate, and it is what `DELETE` means.
`GeneratorExit` reaches that consumer as an ordinary end-of-iteration, not an
error.

> **Correction:** that consumer has **not** necessarily been interrupted first.
> The docstring used to claim it had; reordering `aclose()` ahead of `interrupt()`
> made that false. A turn finalized on the first `aclose()` attempt never
> receives a control request at all (measured: `interrupts == 0`).

### Order matters: `aclose()` before `interrupt()`

Earlier versions interrupted first. That was both slower and, in one case, fatal.

* `interrupt()` is a **control request**, and the SDK bounds those by its own
  **60 s** (`_internal/query.py`, `timeout: float = 60.0`, `anyio.fail_after`),
  then raises a plain `Exception("Control request timeout: interrupt")`.
  `RunOptions.timeout_s` is caller-supplied with `ge=1`, so `timeout_s=1` against
  a 60 s control bound is *ordinary usage*. The pre-fix code computed `deadline`
  before that await and neither bounded nor caught it, so its own "every path is
  bounded" claim was false.
* Worse, on a CLI that never answers control requests, `interrupt()` **raised
  before the turn-finalizing machinery was ever reached**, bypassing all of it.
  **Measured through the real `SessionRegistry`** (control timeout scaled to
  0.4 s, `timeout_s=0.05`): three `DELETE`s in a row 500'd at **~402 ms each**,
  8× the advertised bound, each stalling `create()`, `reap_once()` **and**
  `close_all()` for its whole duration, and afterwards
  `reclaimed=0 status='running' registered=True disconnected=False` — a
  **permanent cap-slot and subprocess leak**, because the reaper skips
  `"running"` by design and every retry repeats the same wait and the same
  failure.

Trying `aclose()` first removes the control request from that path entirely: an
abandoned turn is finalized outright, there is no in-flight caller left to give a
defined ending to, so nothing is owed an interrupt — `disconnect()` (S5) stops the
subprocess regardless. **Measured:** the leak scenario now closes without touching
the wedged channel at all (`interrupts == 0`). Only a turn that is genuinely being
advanced still gets the interrupt — the case it was added for, where its caller
does deserve the measured S2 shape rather than a forced abort — and that call is
bounded by a share of the same deadline (`_interrupt_until`) and can never be
fatal.

### One shared deadline

Every **wait** is bounded by one deadline of `self._limits.timeout_s` from entry:
the interrupt, **each `aclose()`** (it was once the third unbounded wait, and it
made the "every wait is bounded" sentence false as written), the retry loop, and
the final lock acquisition (`_acquire_lock_until`), which gives up rather than
waiting forever.

That final acquisition is **skipped outright** when the only thing holding the
lock is a courtesy interrupt (`_courtesy_interrupt`) — waiting for that was a
registry-wide stall, measured at the default `timeout_s` as **1.944 s** for
`create` / `reap_once` / `close_all`. When it gives up, `close()` disconnects
**without** the lock rather than leaving the session permanently unreclaimable and
the registry deadlocked. That backstop is rare but real: it fired in **3 of 2500**
fuzz rounds, always where a genuinely-driven turn outlived the whole `timeout_s`
budget. In every one, the session still ended `status == "closed"` and
disconnected, and the turn finished on its own within **~15 ms** afterwards — its
own `finally` then reads `status == "closed"`, leaves it terminal, releases the
lock and clears the interrupt stamp.

> **Correction:** the courtesy-interrupt skip was once justified as "this method
> sets `status` to `'closed'` before anything can acquire the lock". That is
> **false** — `status = "closed"` is assigned *after* `disconnect()` returns, and a
> real `disconnect()` suspends. **Measured:** the courtesy interrupt released the
> lock while `close()` was parked inside `disconnect()`, and a new turn acquired
> it, read `status == "idle"` and ran to completion (`queries == ['hi', 'second
> turn']`, `turns=1`). The guard that actually holds is `_closing`, latched before
> any await and checked by `_send_impl` **inside** the lock.

### The one deliberately unbounded step: `disconnect()`

Not an oversight. S5 measured it killing the subprocess deterministically, it is
the only step whose completion is actually required for the session to be gone,
and cutting it short would mean reporting a subprocess as dead while it is alive
— the precise failure `delete_session` exists to avoid.

For the same reason `status` is set to `"closed"` only **after** `disconnect()`
returns. Setting it first made a **failed** disconnect look terminal, so the retry
`registry.py` documents became a silent no-op that returned 204 with the
subprocess still alive (**measured:** `DELETE #2 -> 204 with disconnect_calls=1
client.disconnected=False`). A failing `disconnect()` now leaves the session
non-terminal and still registered, so a retry genuinely retries.

### On `CancelledError`

No cancellation this method *creates* escapes it — `asyncio.timeout` converts its
own into `TimeoutError` inside `_interrupt_until` and `_acquire_lock_until`, and
both catch it. A cancellation aimed at this task from **outside** still
propagates, as it must — and one such cancellation is not really from outside: an
abandoned turn's dangling `asyncio.timeout` cancels whichever task made that
turn's *first* advance, wherever it happens to be, which can be inside this
method's own retry sleep (**measured:** `close(): RAISED CancelledError in 125 ms,
status='idle' disconnected=False`). It is not distinguishable from a genuine
caller cancellation — both are just `Task.cancel()`, and both bump `cancelling()`
— so it is **not** swallowed.

The handler instead tries to disconnect and mark the session terminal before
re-raising. That is **best effort, not a guarantee**: it wraps its own
`disconnect()` in `suppress(Exception)`, so if the cancellation lands **and** that
disconnect then fails, the exception is swallowed, `status` is never assigned, and
the session is left non-terminal and still connected. Cancellation can no longer
leave a leak *unless* the disconnect itself also fails. Leaving it non-terminal is
the deliberate direction (it stays registered, so a retried `DELETE` genuinely
retries), but it is a leak until that retry arrives. Exposure is low — a `DELETE`
handler is never a turn's first advancer — but "low" is not "none".

---

## CP-012 — sessions.py — AgentSession.kill()

Last resort: `disconnect()` **now**. No turn finalisation, no lock, no retry.

Not reachable from the HTTP API and not a substitute for `close()`. The one caller is
`SessionRegistry.close_all()` (CP-025)'s force-kill
phase, reached only after a session has already failed to close inside its fair share
of the shutdown budget — at which point the choice is not "clean or dirty teardown"
but **dirty teardown or a subprocess that outlives the container**.

### Why it can skip everything `close()` does
Every step `close()` takes before `disconnect()` — `_finalize_live_turn()`, the
`aclose()` retry loop, `_acquire_lock_until()` — is a **wait**. This is called
precisely because there is no time left to wait; a bounded shutdown that spends its
last 5 s waiting politely has spent it on nothing.

### What that costs, stated plainly
`disconnect()` was measured to kill the subprocess (S5) **at a clean turn boundary**.
What it does against an actively draining turn has never been measured — which is why
nothing else in this codebase does it, and why `reap_once()` skips `running` sessions
rather than force-closing them. That unmeasured shape is accepted here and only here,
because the alternative on this path is a leaked process. It is recorded as an open
item in deployment.md (CP-095).

### It latches `_closing`, and assigns `status` only after `disconnect()` returns
Both for the same reasons `close()` does: `_closing` first, before any await, so no
turn, control request or setter can start behind it; `status = "closed"` only once
`disconnect()` has **returned**, so a kill that fails leaves the session non-terminal
and honestly still-connected rather than claiming a teardown that did not happen. The
registry reports that as "neither closed nor killed" — the honest answer, and the one
an operator needs.

It is **not itself bounded**, deliberately: `disconnect()` is not a wait that can be
shortened. The caller bounds it, from the shutdown budget's reserve.

---

## CP-013 — sessions.py — AgentSession.\_finalize\_live\_turn()

Ends the turn holding `self._lock`, or gives up at `deadline`. Returns as soon as
the lock is free or the live generator is gone — it does **not** itself take the
lock. See `close()` (CP-011) for why `aclose()` comes
before `interrupt()` and why `RuntimeError` is retried.

### The bound on `gen.aclose()`
The unwind `aclose()` drives is synchronous **with the pinned SDK** —
`receive_response` → `client.receive_messages` → `Query.receive_messages` → the
anyio memory stream has no `try/finally` and no `await` on the unwind path, so
nothing in it can suspend. But "every wait is bounded by one `timeout_s`
deadline" is a claim `close()` makes and `registry.py` rests its registry-wide
lock on. It should be true **by construction** rather than by accident of someone
else's teardown code. **Recheck on any SDK upgrade:** this bound turns a
regression there into a slow `close()` rather than a wedged registry.

> **Correction:** the bound does **not** cost the turn its unwind. This was once
> stated as "the turn would then be left un-finalized". A reviewer built both
> teardown shapes reachable here and the cancellation this bound delivers ran the
> turn's own `finally` in each. What is lost is only whatever the teardown had
> left to do past the suspension point that outlived the deadline.

### The three `except` arms
* `TimeoutError` — the turn could not be ended cleanly. Log and return; that must
  never stop `close()` from disconnecting, and `disconnect()` (S5) stops the
  subprocess regardless.
* `RuntimeError` — an advance is in flight *at this instant*. That is all it
  proves. Re-check and retry.
* `Exception` — `aclose()` runs the turn's **whole** unwind, including the SDK
  generator's own `aclose()`, so a teardown failure (an `OSError` from a transport
  that is already gone, say) surfaces here. The turn is over either way — that
  unwind releases `self._lock` and runs the `finally` on its way out. This used to
  propagate before `status` was set and before `disconnect()`, making `DELETE #1`
  a 500 with the client still connected.

---

## CP-014 — sessions.py — AgentSession.\_interrupt\_until()

Asks the SDK to stop the running turn. Bounded, and never fatal.

Takes **half** the remaining budget, not all of it: the interrupt is a courtesy to
the turn's own caller, while actually ending the turn and taking the lock is what
`close()` is *for*. A wedged control channel must not consume the whole deadline
and leave nothing for the steps that make the session terminal.

Every failure mode is swallowed deliberately. The SDK raises a plain
`Exception("Control request timeout: interrupt")` after its own 60 s
(`_internal/query.py`), and `asyncio.timeout` raises `TimeoutError` when this
bound bites first. Neither says anything about whether the session can be closed,
and `close()` has a forced teardown (`_finalize_live_turn`) plus `disconnect()`
(S5) that work without the control channel. Letting either propagate is what made
a wedged CLI a permanent leak.

---

## CP-015 — sessions.py — AgentSession.\_acquire\_lock\_until() / \_acquire\_lock\_now()

Both return `True` iff the lock was acquired; the caller must release it iff so.

### Why the bound is not optional
`asyncio.Lock.acquire()` is bounded rather than awaited bare because a bare await
genuinely can be unbounded: the turn holding the lock may be abandoned (nothing
will ever release it), and **even an unlocked lock suspends the acquirer when it
already has a non-cancelled waiter ahead of it** (`asyncio.Lock` is FIFO-fair).
That is how `close()` can end up queued behind something else.

### Why `_acquire_lock_now` is not `if not self._lock.locked()`
`locked()` alone is **not** the test, for the same FIFO-fairness reason: there is
a real window between `release()` waking the first waiter and that waiter
resuming, so `if not locked: await acquire()` can park for a whole turn. Bounding
at zero is what makes "immediately or not at all" true rather than usually-true.

`asyncio.timeout(0)` is **exact** here, not approximate. Its deadline is already
past on entry, so the cancellation is delivered at the first suspension point
*inside* the block — and `Lock.acquire()` returns without suspending when the lock
is genuinely free, in which case `__aexit__` cancels the timer before the loop
ever gets to run it. Either the lock was free and we hold it, or we were cancelled
inside `acquire()` and `asyncio.timeout` converts that into `TimeoutError`.

> **Correction, both methods:** the docstrings once claimed "never a
> `CancelledError` escaping to the caller". **False as written** — a cancellation
> aimed at the *calling task* from outside still propagates, and a reviewer
> confirmed by execution that it does. No lock is leaked when it happens:
> `Lock.acquire()`'s own cancellation handler hands the lock to the next waiter if
> it was granted in the same instant. The accurate claim is "no cancellation
> **this method creates** escapes it".

---

## CP-016 — sessions.py — AgentSession.\_sdk\_message\_buffer() / \_discard\_residue()

### `_sdk_message_buffer()`
Returns the SDK's **connection-scoped** message buffer, or `None`.

`receive_response()` does not create a fresh stream per call: `Query.__init__`
creates exactly one `anyio.create_memory_object_stream(max_buffer_size=100)` for
the whole connection (`_internal/query.py:138`), and every `receive_response()`
re-wraps it (`client.py:571-610` → `receive_messages()` →
`Query.receive_messages()`). Only conversation messages land there —
`control_response` / `control_request` / `control_cancel_request` /
`transcript_mirror` frames are all `continue`d out of the read loop before the
send (`query.py:273-367`) — so discarding from it **cannot** disturb `interrupt` /
`set_model` / `get_context_usage`, which resolve through
`pending_control_responses` instead.

This reaches through private internals **deliberately, and defensively**: a future
SDK release may rename or restructure them, and a guard that raised
`AttributeError` on the next turn would be strictly worse than the misattribution
it defends against. Every step is probed; anything unexpected yields `None` and the
guard simply does nothing.

### `_discard_residue()`
Drops whatever is already queued on that buffer and returns a count.

**Provably non-blocking and bounded.** `receive_nowait()` is a plain synchronous
method (there is no `await` anywhere in the function, so it cannot yield to the
event loop, let alone park); it *raises* rather than waits when the buffer is
empty (`anyio.WouldBlock`), when the producer side has closed
(`anyio.EndOfStream`), or when the receive side has closed
(`anyio.ClosedResourceError`) — all three subclass `Exception` — and the loop is
capped at `_RESIDUE_DISCARD_LIMIT` regardless. A blocking read here would hang the
next turn forever, which is far worse than the defect, so it must stay this shape.

**Safe by construction:** it only ever runs at the top of `send()`, **before**
`query()` has been written, so nothing in the buffer can belong to the turn about
to start. Anything present is by definition a previous turn's abandoned output.

**What it cannot cover:** messages still *in flight* from the subprocess. Those
arrive **during** the next turn's drain, and a stray `ResultMessage` among them
ends that turn early. Only telling the SDK to stop covers that — see
`interrupt()` (CP-019) and `api.py`'s
`stream_turn()` (CP-040).

---

## CP-017 — sessions.py — AgentSession.send() / \_send\_impl()

### Why `send()` is a thin wrapper with a one-element box
`send()` returns an async generator; **nothing in it runs until first advanced**,
so the `SessionBusy` / `SessionClosed` raises are `_send_impl`'s body, not
`send()`'s. An async generator has no built-in way to hand a caller a reference to
itself, so the box is how `_send_impl` gets one: created empty here, filled with
the just-created generator **before** it is returned to the caller (so it is
always populated by the time anyone can advance it), and read — never written — by
`_send_impl`.

### Why `_active_gen` is published inside the lock
> **Tried and failed:** stashing `_active_gen` eagerly from `send()`'s wrapper at
> call time, for **every** call — including one about to lose to `SessionBusy`.

That check is lazy: it only runs on first advance. A losing call raises before
reaching the publish line, so publishing from inside the lock means only the turn
that actually **wins** `self._lock` can ever become `_active_gen`.

**Reproduced concretely with the eager version:** A's turn running (possibly
abandoned), a concurrent B correctly gets `SessionBusy`, but the wrapper still
overwrote `_active_gen` with B's own, already-exhausted generator. `close()` would
then `aclose()` B's spent generator (a silent no-op), believe it had finalized the
abandoned turn, and hang forever on the lock A's **real** generator still holds —
the exact hang class that bookkeeping existed to eliminate, reintroduced by its
own bookkeeping.

### Why `status` is re-checked *inside* the lock
The pre-lock check runs before the acquisition, and `close()` re-checks inside it,
so there was a window where both guards passed and the turn still ran against a
closed, disconnected session: a first advance landing after a queued `close()` has
been woken (lock released, `status` back to `"idle"`) but before it resumes sees a
free lock and a live status, queues behind `close()` (FIFO-fair), and acquires only
once the session is closed and the client disconnected — then runs a full turn
against a dead client and resurrects `status` from `"closed"` to
`"running"`/`"idle"`, breaking the terminal-status invariant. **Reproduced**
(`queries == ["A", "B"]`, disconnected, final status `"running"`). Raising there is
the same lazy `SessionClosed` the pre-lock check raises, so callers see no new
behaviour — only an honest one in that window.

`_closing` is checked alongside `status` and is the half that actually holds while
`close()` is suspended inside `disconnect()`; see
`_closing` (CP-010) for the measured turn that ran in
that window, and
Guards that are deliberately not test-killable (CP-006)
for why the pair cannot be pinned separately.

### Clearing `_turn_abandoned` at the top of a turn
This turn now owns the connection, so any **previous** turn's abandoned-mid-drain
condition is spent: whatever the subprocess was still producing then is either
already drained by `_discard_residue()` or is this turn's problem now. Interrupting
on behalf of that older turn from here on could only kill **this** one. Cleared
inside the lock, before the first await.

### `aclosing()` around `receive_response()`
Mirrors `runner.py`'s `Run.events()`: `async for` does **not** close its iterator
when the loop is abandoned via `GeneratorExit` or a raised exception (PEP 533 was
deferred), so an SSE disconnect mid-turn would otherwise leave this generator
wrapper cleaned up only by non-deterministic GC.

Unlike `Run.events()`, this does **not** tear down the CLI subprocess — the session
owns that across the whole connection, killed only by `close()`/`disconnect()`
(S5) — so it bounds the **local** generator's cleanup only. It does not by itself
stop the CLI from continuing to produce the rest of an abandoned turn into the
connection-scoped stream. That residue is dealt with at the top of the next turn
by `_discard_residue()`.

### The `except TimeoutError` arm
`asyncio.timeout()` cancels the drain and raises `TimeoutError` on exit once the
deadline is exceeded — mirroring `runner.py`'s `Run.events()`. A timed-out turn
never produces its own `ResultMessage`, so `outcome` stays `None` exactly like any
other abandoned drain, and the `finally` makes the next turn pre-drain.

It is distinguished from both an interrupt and a generic crash: `interrupted` is
still keyed only to `_interrupt_for_turn` (a caller that happened to both
interrupt *and* hit the timeout — or neither — is still reported honestly),
`timed_out=True` names this specific cause for anyone inspecting `last_turn`, and
re-raising **`RunTimeout`** — the same type `runner.py`'s one-shot `/v1/query`
path raises, not a new session-only type — lets a caller `except RunTimeout`
uniformly across both paths. `errors.to_problem` already maps it to a 504.

**This bound is what makes the reaper's policy safe.** A turn that never produces a
`ResultMessage` used to hang forever: `self._limits` was assigned in `__init__` and
never read again. Because `registry.py`'s reaper deliberately never force-closes a
`"running"` session, a hung turn's session was neither finished nor reclaimable —
`max_sessions` such hangs would **permanently exhaust** the service's ability to
create sessions.

### Why both handlers check `recorded`
The `except TimeoutError` and `except BaseException` arms both skip their
bookkeeping once the turn has been **recorded**.

The deadline can still expire while the drain sits at its final `yield` waiting for
a consumer that has stalled, and a turn whose own `ResultMessage` was already
consumed **did not time out** — its reader did. `RunTimeout` still reaches that
reader; what must not happen is the completed turn being overwritten with
`outcome=None`.

The same for `except BaseException`. It used to run unconditionally, and the
reachable case mislabelled a **completed** turn: the consumer takes the `result`
frame, its write never completes, and the cleanup's `aclose()` arrives here as a
`GeneratorExit` — overwriting a turn that had a real result and
`total_cost_usd=0.42` with `outcome=None, interrupted=True, turns=0, cost=0.0`
(**measured**). The turn ended when its `ResultMessage` was consumed; what died
afterwards was the *delivery* of the last frame, which is the consumer's business,
not the turn's.

Otherwise a mid-drain failure must not leave `last_turn` pointing at the
**previous** turn's result — that would read as a stale success for a turn that
never finished. `outcome=None` mirrors `Run.outcome`'s own "stream ended without a
`ResultMessage`" case. The interrupt label is still honest there: "we asked this
turn to stop and it then died or was cancelled". Reading the stamp is safe because
the `finally` that clears it runs after the handler.

### Why `_turn_abandoned` is not re-armed for an already-interrupted turn
`api.py`'s `close_stream()` does interrupt-then-`aclose()`, and that `aclose()`
arrives in `except BaseException` as a `GeneratorExit`. An unconditional `True`
re-armed the flag on behalf of the very turn the interrupt had just stopped, and
the next caller to reach `interrupt()` fired a second, pointless control request
(**measured:** `interrupts=1, _turn_abandoned=True`, then a third `interrupt()` on
the idle session made it 2). That broke the "at most once per abandoned turn"
property and resurrected the spurious fire the design ruled out.

It is deliberately keyed to the **stamp**, not to whether the control request
actually succeeded. If `interrupt()` raised after stamping, this leaves the flag
clear and no retry is owed. That is the conservative direction:
`close()`/`disconnect()` (S5) still stops the subprocess unconditionally and
`_discard_residue` still guards the next turn, so the cost is a **missed courtesy**
rather than a correctness gap — whereas the other direction is a control request
aimed at a turn that no longer exists. A **recorded** turn is likewise owed
nothing: its `ResultMessage` is in, so the subprocess has finished producing it.

### Why the interrupt stamp is cleared in `finally`
> **Tried and failed:** clearing it in the postscript after the drain. That fixed
> the "read before the interrupt could arrive" half but not the leak — `raise`
> skips a postscript, so an interrupt landing mid-drain on a turn that then dies
> (interrupt, then the client disconnects and cancels the drain) left the stamp set
> for the **next** turn to consume.

`finally` is the only placement that cannot be skipped. **The invariant: no turn
may ever begin with an interrupt recorded during a previous turn.**

The same `finally` sets `_residue_suspected = outcome is None`, which is exactly
the "never consumed its own `ResultMessage`" condition and covers both exits — a
drain abandoned before the result, and a stream that ended without one — and clears
`_active_gen` on every exit path, including when `close()`'s own `aclose()` unwinds
through this exact `finally`.

### Why `turns` is not incremented on a resultless drain
The drain ended of its own accord but without a `ResultMessage`: there is no
outcome to report and nothing this session can honestly call a completed turn.
`last_turn` is still assigned — leaving the previous turn's result standing would
read as a stale success — but `turns` is not.

`turns` used to be incremented **only** there, so a resultless drain counted while
a turn that raised did not, and the straddle case lost a turn that genuinely
completed. `turns` now means exactly one thing — **turns that reached a
`ResultMessage`** — which is what `_turn_seq` has always claimed it means, and it
no longer depends on how the consumer behaved after the result arrived.

---

## CP-018 — sessions.py — AgentSession.\_record\_turn()

Records a turn that reached its own `ResultMessage`. **Never awaits.**

### Why it is called from inside the drain, before the yield
> **Tried and failed:** recording from a postscript after the drain resumes one
> final time. The postscript can be skipped — a consumer whose write of the
> `result` frame never completes leaves the drain suspended at that `yield`
> forever, and the cleanup's `aclose()` then unwinds it through
> `except BaseException` instead.

**Measured against that shape:** a turn with real result text and
`total_cost_usd=0.42` recorded as `outcome=None, interrupted=True, turns=0,
cost=0.0`, plus a control request aimed at a turn that had already finished.

Everything the SDK told us about the turn is known at the moment the
`ResultMessage` is consumed, so that is where it is written down. Being
**synchronous** is what makes it unskippable once the message is in hand.

### Two consequences, both deliberate
* `interrupt_requested` is read **here** rather than in `send()`'s `finally`, so an
  interrupt landing *after* the `ResultMessage` was consumed — while the drain is
  parked at its final `yield` — no longer labels the turn. On an already-aborted
  turn that flips `interrupted` from `True` to `False`. That is the honest answer:
  an interrupt cannot have caused an abort the SDK had already reported. It is
  still a change to the one field this module exists to get right.
* This runs once per `ResultMessage` **consumed**, not once per `send()`. With the
  pinned SDK those are the same thing (S1), but a stream yielding two would count
  two turns. **Recheck on any SDK upgrade.**

### `interrupted` needs both conjuncts
`bool(interrupt_requested and aborted)`. A stop request that lost the race to a
turn that then completed normally must report `False` (`aborted` is the measured
S2 shape), and an aborted turn nobody asked to stop is a crash, not an interrupt.

### The cost delta, and why the two lines are ordered
`total_cost_usd` is cumulative for the connection (S6), so this turn's own price is
the difference against the running total **as it stands now** — i.e. **before** the
assignment at the bottom of the method. Computing it after would make every delta
`0.0`. The two lines are **ordered, not merely adjacent**;
`test_the_delta_is_taken_before_the_running_total_is_updated` is the named guard (a
one-turn test cannot fail on it, because the running total starts at `0.0` and the
first delta is the cumulative value either way).

Three cases, all deliberate:
* **First turn** — the running total is `0.0`, so the delta is the whole cumulative
  figure. Correct: there is no earlier turn.
* **No price on the `ResultMessage`** (the SDK's field is optional) — `None`,
  "nobody can say", never `0.0`, which would claim the turn was free.
  `self.total_cost_usd` is likewise left alone.
* **A previous turn that produced no `ResultMessage`** — its cost is still inside
  the connection's running total, so this turn's delta covers both. That is the
  honest answer available: the SDK never itemised the abandoned turn, and this
  service does not invent a split. `last_turn.outcome_recorded` on that earlier turn
  is what says its own price was never reported.

The running total **assigns** the latest cumulative value rather than summing, or
it would double-count on every turn.

### The fourth case: an aborted turn whose cumulative did not move

Added after a live measurement (`spike/probe_interrupt_cost.py`; raw data and analysis
in `conversations/.superpowers/sdd/interrupt-cost/`). An interrupted turn used to fall out of the
three cases above as a perfectly ordinary **zero delta** — the SDK's cumulative figure
did not move, so `cumulative - self.total_cost_usd == 0.0` — and was reported as
`turn_cost_usd: 0.0`, i.e. *this turn was free*. It is not.

What the SDK actually reports for such a turn, measured:

* `usage` — every count **zero**, `iterations: []`. Not "tokens with no price": no
  tokens at all. This is true of any non-`success` subtype, a budget stop included.
* `model_usage` — **unchanged**, still carrying the connection's running totals from
  earlier *completed* turns. On a connection whose first turn was interrupted the
  model that did the work has **no key at all**.
* `total_cost_usd` — unchanged.

Meanwhile the CLI ran ~8 s of streamed inference per turn, and the conversation prefix
grew from ~24.6k to 29,135 tokens across eight such turns — tokens that every later
turn then pays **cache-read** on, though nothing is recorded as having created them.

The cost is **lost, not deferred**. The turn after an interrupted one moves the
cumulative by exactly its *own* `usage` priced at published rates, to seven decimal
places ($0.0096021 for 568 cache-write + 24,687 cache-read + 2 in + 4 out). Nothing
from the interrupted turn is folded in later.

So the rule is `runner.unattributed_abort` (CP-029),
shared with the one-shot path:

```python
return price == 0.0 and outcome.terminal_reason in ABORTED_TERMINAL_REASONS
```

`_record_turn` applies it to the delta and leaves everything else alone: the delta
arithmetic above it and the `total_cost_usd` assignment below it are untouched.

**Why the exact `== 0.0` is correct rather than sloppy.** Both operands come from the
same JSON number decoded to the same float when the price does not move, so the
difference is exactly `0.0` (and `-0.0 == 0.0` holds). A tolerance would have to guess
how small a genuine price can be; and the drift it would guard against — one ULP,
reporting a nonsense micro-cost instead of `null` — is strictly less wrong than the
`0.0` this replaces.

Both conjuncts and the guard **body** are mutation-pinned
(`conversations/.superpowers/sdd/interrupt-cost/mutate.py`, seven mutants, all killed):

| Mutant | Killed by |
|---|---|
| `return False` (the pre-fix behaviour) | `test_an_interrupted_turn_reports_no_cost_rather_than_zero` |
| price conjunct dropped | `test_an_aborted_turn_whose_cumulative_did_move_still_reports_the_delta` |
| aborted conjunct dropped | `test_a_turn_the_sdk_priced_the_same_is_a_zero_delta_not_unknown` |
| `return True` (the body, not the condition) | `test_a_turn_records_its_own_cost_as_a_delta` and 11 others |
| negated | 15 tests |
| `price is None` instead of `== 0.0` | `test_an_interrupted_turn_reports_no_cost_rather_than_zero` |
| marker set widened to `!= "completed"` | `test_a_limit_stopped_turn_is_not_treated_as_an_aborted_one` |

Two rows are worth reading twice. The **aborted-conjunct** row is why the change is
safe: a *completed* turn the SDK priced the same as its predecessor is still a genuine
`0.0`, and that pre-existing test doubles as the guard against over-reaching. The
**widened-marker-set** row *survived the first mutation round* — a guardrail stop
(`budget_exhausted`, `max_turns`) is a different measured shape, one that moves the
cumulative and grows `model_usage` like any ordinary turn, so its zero delta means what
a zero delta always meant. Nothing covered that until
`test_a_limit_stopped_turn_is_not_treated_as_an_aborted_one` was written for it.

This is the most the service can do. `max_budget_usd` is enforced **inside the CLI**
against the same unmoved figure and is therefore blind — measured, and not fixable
here. See `docs/deployment.md` (CP-090),
which also records why a service-side spend guard was rejected. **Recheck on any SDK
upgrade:** if an aborted turn ever starts reporting `usage`, this guard is where the
condition is already detected and the fix would become "surface it" rather than
"decline to price it".

> **Caveat added by the M1 probe.** A mid-turn `PATCH` that changes the model
> re-prices the remainder of the turn already in flight, so a turn's delta can
> legitimately span two models and `model_usage` can report both. See
> set_model / set_permission_mode (CP-020).

---

## CP-019 — sessions.py — AgentSession.interrupt()

Stamps the running turn as deliberately stopped, then asks the SDK. Returns
whether a control request was actually **issued**.

### Why it returns a bool rather than being inferred from outside
`POST /v1/sessions/{sid}/interrupt` answers with a body reporting what happened,
and **nothing the endpoint can observe from outside reconstructs that**. The
obvious `interrupted = status == "running"` is wrong in exactly the case the second
branch exists for: an abandoned turn leaves `status == "idle"` and still sends a
real control request, so the endpoint would report `false` for a request that
measurably fired. Two states identical from outside (`"idle"`, one firing and one
not) can only be told apart in here.

This is **additive**: a no-op still returns normally, it just says so.

**Alternatives rejected.** Exposing `_turn_abandoned` duplicates this method's
decision in `api.py` where it would drift, and reading it before the call is racy
on top. An `interrupts_issued` counter adds state to a class whose state is already
the hard part, and would have to be diffed across the await. Pinned by
`tests/test_sessions.py::test_interrupt_returns_true_for_an_abandoned_turn_on_an_idle_session`.

### Branch 0 — no turn running is a no-op, not an error
There is nothing to interrupt, and recording the request could only mislabel some
later, unrelated turn that happens to come back in the measured aborted shape (S2)
for reasons of its own — precisely the misattribution this bookkeeping exists to
prevent. **Raising was rejected:** "the turn finished just as I asked to stop it" is
a race no caller can avoid, and turning that into an error would punish correct
clients for losing it. A caller that needs to distinguish the two can read `status`.

### Branch 1 — a running turn
The stamp is written **before** the await so a turn already draining sees it;
`send()`'s `finally` reads and clears it when that turn ends, whichever way.
Nothing awaits between the `status` check and the stamp, nor between the read and
the clear, so on a single-threaded event loop the stamp cannot outlive its turn.

`_closing` is deliberately **not** checked in this branch: `close()` itself reaches
it via `_finalize_live_turn` → `_interrupt_until`, and gating it would stop
`close()` giving a genuinely-advancing turn's caller the measured S2 ending.

### Branch 2 — a turn already abandoned mid-drain
`status == "running"` is **not** the only state in which the CLI subprocess is
still working, and keying solely off it made this method a silent no-op on the
commonest disconnect there is.

When an SSE consumer on a real socket hangs up, the cancellation lands **inside**
`stream.__anext__()`. `_send_impl` therefore unwinds through its own
`except BaseException`/`finally` immediately, and `status` is already back to
`"idle"` before any downstream cleanup runs — so the branch-0 guard returned and no
control request was ever sent, while the subprocess carried on producing that turn.
(The other interleaving — a stalled **write**, leaving the turn parked at a `yield`
— *does* still report `"running"`, which is why this went unnoticed: it depends
entirely on where the cancellation lands.)

Those still-in-flight messages are **not** coverable by `_discard_residue`, which
can only drop what is already buffered when the next turn starts. They arrive
**during** the next turn's drain, and a stray `ResultMessage` among them ends it
early — one caller's turn reported as another's.

`_turn_abandoned` names exactly that condition and is deliberately **narrower** than
`_residue_suspected`, which is also set when a turn ends normally without a
`ResultMessage`, where the subprocess has already finished and interrupting would
be the "interrupt nothing" no-op branch 0 exists to prevent. It is **consumed**
here rather than latched, so an abandoned turn is interrupted at most once.

"At most once" needs **both ends** to cooperate; consuming the flag here is not
enough on its own, because `close_stream()` interrupts and *then* calls `aclose()`,
which re-enters `_send_impl`'s `except BaseException` — where the flag is recorded.
Those handlers therefore skip the re-arm for a turn carrying this turn's stamp.

**No stamp is written in branch 2**, deliberately: the turn is already over and its
`TurnResult` already recorded. Stamping would be a claim about a turn nobody can
still observe, and the invariant is that no turn may begin with an interrupt
recorded during a previous one.

A closed session is excluded outright: `close()` → `disconnect()` already stops the
subprocess (S5), and pushing a control request down a disconnected client can only
raise.

### Why branch 2 holds the session lock
It used to issue its control request with **no lock held and no turn running**, and
that is a race, not a theoretical one: a turn **started** during that await is
killed by the *previous* turn's in-flight control request.

**Measured** against a client that models the SDK honestly (a landed interrupt
aborts whatever turn is draining, S2): `interrupt()` entered at `status='idle',
_turn_seq=1` and the new turn came back `terminal_reason='aborted_streaming',
is_error=True, interrupted=False` — deliberately stopped by the service and reported
to its caller as a plain failure. No stamp is written for that turn (this branch
writes none), so it cannot even be labelled honestly. Reachable from
`POST /v1/sessions/{sid}/interrupt` **and** from `close_stream()`'s cleanup on an
ordinary SSE hangup, so a disconnect-and-retry client hits it without ever touching
the interrupt endpoint.

Holding the lock makes that new turn lose the ordinary way — a 409 `SessionBusy`,
the same answer any concurrent turn gets — instead of being aborted mid-flight.

**Two bounds keep the cure from becoming the disease** (a wedged control channel
awaited under a lock):

* The lock is taken **only if it can be had without waiting** (`_acquire_lock_now`).
  If a turn already owns the connection there is nothing for this branch to do
  anyway — `_send_impl` clears `_turn_abandoned` when it starts, precisely because
  interrupting on the old turn's behalf could only kill the new one — so giving up
  is the correct answer, not a compromise. A bare `async with self._lock` would be
  an **unbounded** wait (FIFO fairness again).
* The control request itself is bounded by `_STALE_INTERRUPT_BUDGET_S` — **one
  second**, emphatically not `self._limits.timeout_s`. See
  the constant (CP-007) for the measured registry-wide
  stall that motivated it and for why abandoning the wait is safe.

**A second, independent bound:** `close()` does not queue behind this branch. While
it holds the lock it publishes `_courtesy_interrupt`, and `close()` reads it — a
courtesy interrupt is not a turn, so `close()` owes it nothing and takes the
disconnect-without-the-lock path it already has. Between the two, a wedged control
channel costs a stale interrupt (up to 1 s of 409s on that **one** session) and
nothing registry-visible at all.

`close()` never reaches branch 2 itself: it interrupts only a turn it has just
proved is being advanced, i.e. `status == "running"`, which is branch 1.

---

## CP-020 — sessions.py — AgentSession.set\_model() / set\_permission\_mode()

### The closed-session guard
After `close()` the client is disconnected, so pushing a control request at it can
only raise `CLIConnectionError`, which `errors.to_problem` classifies as **502
"Agent process failed"**. That would report a session the operator closed
**deliberately** as an agent-process failure, and it would answer the identical
condition two incompatible ways — `POST /v1/sessions/{sid}/messages` already
returns **409 "Session closed"** for it, via the same exception. One condition, one
answer.

This is deliberately **not** the shape `interrupt()` uses for a closed session.
Interrupting is a courtesy whose no-op is a legitimate outcome and whose response
body can *say* so; setting a model is a mutation the caller expects to take effect,
and `PATCH` answers with a `SessionRecord` that has nowhere to report "I did
nothing". Silence would read as success.

`_closing` is checked for the same reason: while `close()` is suspended inside
`disconnect()`, `status` is still `"idle"`, so without it a `PATCH` landing in that
window pushes a control request at a client being torn down and gets exactly the
502 this guard exists to avoid.

### Why the attribute is assigned *after* the await
`self.model` / `self.permission_mode` are the read-back `SessionRecord` reports, so
they must say what the SDK actually **took**: a control request that raises leaves
the session advertising the model it still has, not the one that never arrived.

### Mid-turn behaviour — measured (M1), and it is not what the route used to say

**No lock is needed for safety.** A mid-turn control request does not disturb the
in-flight turn: control calls returned in **4 ms, 5 ms and 161 ms**, no exception in
either the control coroutine or the drain, no stall, no reordering, no lost or
duplicated message, and every turn ended on a clean `ResultMessage`
(`subtype='success'`, `is_error=False`, `terminal_reason='completed'`).

**Both setters take effect on the CURRENT turn, at the very next inference —
not the next turn.** Within one `receive_response()` drain, `AssistantMessage.model`
went `claude-haiku-4-5-20251001` → `claude-sonnet-5` after a `set_model` fired
mid-drain, and **that single turn's `model_usage` billed both**:

```
turn1 model_usage[claude-haiku-4-5-20251001] = in=551 out=14  cost=$0.000621
turn1 model_usage[claude-haiku-4-5]          = in=10  out=735 cost=$0.02704375
turn1 model_usage[claude-sonnet-5]           = in=2   out=289 cost=$0.09827475
```

`set_permission_mode` behaves the same way: with `acceptEdits` → `plan` fired
mid-turn, the pre-switch `Write` landed on disk and the **next** `Write` in the
**same turn** was denied (`ResultMessage.permission_denials` carried it
structurally). A denied tool call is **not** a turn failure — the turn still ended
`success` / `completed`.

**Consequence for the service:** a `PATCH` that lands mid-turn does not "apply to
the next turn". It **re-prices the remainder of the turn already in flight.** A
client that PATCHes haiku → sonnet during a long turn is billed at sonnet rates for
the rest of that turn, and `session.total_cost_usd` will move by more than the
caller expects. The PATCH route's prose says "immediately, including on a turn
already in flight" for exactly this reason; the older "mid-session" wording was
materially misleading and has been corrected.

**Two more measured hazards:**
* `ResultMessage.model_usage` keys are **not stable identifiers** — one turn
  reported *three* keys for *two* models (canonical `claude-haiku-4-5-20251001`,
  alias `claude-haiku-4-5`, alias `claude-sonnet-5`). Anything that groups or sums
  by `model_usage` key will **double-count** across an alias/canonical pair. And
  `AssistantMessage.model` is sometimes the dated canonical id and sometimes the
  alias, so "did the model change take effect" cannot be an equality check against
  the requested string.
* `set_permission_mode` injects a `SystemMessage(subtype='status')` into the message
  stream ~10 ms later. Benign — the service already tolerates `SystemMessage` — but
  "a control request never adds anything to the stream" is **not** true.
  `set_model` produced no such message, so this differs per subtype.

**Recheck on any SDK upgrade.** `set_model` here is **n=1** and Windows-only;
`set_permission_mode` is n=2. See
`spike-findings.md` M1 (CP-068)
for the full transcript, the cost, and the list of what remains unverified.

---

## CP-021 — sessions.py — AgentSession.context\_usage()

Asks the SDK how much context this session has used, or returns `None`.

`None` means **"not asked"**, and it is returned rather than raised. This was the
one hole in `_closing`: `context_usage()` had **neither** guard the setters have, so
a `GET /v1/sessions/{sid}` landing while `close()` was suspended inside
`disconnect()` ran a live control request down a client being torn down — the very
thing the setters' guard exists to prevent — and reported `status: "idle"` for a
session that answered PATCH and POST with 409 "Session closed" in the same instant.
**Measured over real ASGI:** `GET 200 status='idle' control_requests=1 | PATCH 409 |
POST 409`. It also made `_closing`'s own claim ("this session takes no new work of
any kind") false.

**Not the setters' `raise SessionClosed`, deliberately.** A setter is a **mutation**
whose silent no-op would read as success. This is a **read**, and everything else in
the record it feeds — `status`, `turns`, `total_cost_usd`, `last_used_at` — is still
true and is exactly what a caller asks for when a session is being torn down.
Raising would take the one endpoint that can say what happened and make it answer
409 for a session that is still registered, on a route that declares no 409 at all.

"I could not ask" already has a representation on the wire and needs no change in
`api.py`: `SessionRecord.context_usage` is `ContextUsage | None`, documented as
"Populated on the detail endpoint only", and `_record()` renders any falsy usage as
`null`. So `GET` stays 200 with `context_usage: null`.

The route's declared **502 is untouched and still reachable**: it is for a **live**
session whose control channel cannot deliver, which is a different condition from a
session nobody may talk to any more.

---

## CP-022 — registry.py — module concurrency model

Each entry owns a CLI subprocess, so the cap is a real resource bound.

### One lock, held only for synchronous bookkeeping
A single `asyncio.Lock` (`_lock`) guards every mutation of `_sessions` plus a
`_reserved` counter — but it is **never held across an `await`** on a session.

> **Tried and failed:** holding `_lock` across `AgentSession.open()`. A slow or hung
> subprocess spawn for one session then blocked `close()`/`reap_once()` on every
> **other**, already-open session too, destroying the one mechanism an operator has
> to shed load while something is wedged. `open()` is not measured to be fast or
> reliably bounded (unlike `disconnect()`, which S5 covers), so it must never run
> under the exclusive lock.

> **Tried and failed:** holding `_lock` across `await session.close()`, justified by
> "`disconnect()` is measured (S5) to be fast at a clean boundary". But
> `AgentSession.close()` is bounded by `timeout_s`, **not** by `disconnect()`: a turn
> that does not end gives `_finalize_live_turn`'s retry loop the whole deadline
> (600 s default, 1800 s cap), and the registry waited with it. **Measured** with a
> wedged real session and a *healthy* control channel: at the default
> `timeout_s=600`, `reap_once` and `create` were both still blocked at a 5 s probe
> bound while one `DELETE`'s close was in flight; at `timeout_s=4`, `reap_once` took
> **3.938 s**. **Post-change, the same probes: `reap_once` 0.000 s, `create`
> 0.000 s**, while the `DELETE` still waits its full close — which is correct; the
> caller who asked for the close waits, nobody else does.

### The reservation scheme
`create()` takes the lock exactly **once**: briefly, to check
`len(_sessions) + _reserved` against the cap and increment `_reserved` (a slot
"spoken for" but not yet a real session). `open()` then runs with **no lock held at
all**.

* **The cap stays watertight** because the reservation counts against it for the
  whole time `open()` is in flight: a second concurrent `create()` sees `_reserved`
  and cannot overshoot, exactly as if the slot were already occupied.
* **The reaper can never observe a half-created session**: a session is added to
  `_sessions` only in the final synchronous reconcile step, strictly after `open()`
  has succeeded. There is no partial insert to observe, and a reservation with no
  session behind it is invisible to the reaper regardless.

### `open_timeout_s` — why 30 s
Default 30 s, constructor-overridable. Connecting spawns the CLI subprocess and
performs the SDK handshake, a low single-digit-second operation when healthy. 30 s
is generous headroom above that for a slow-but-alive spawn, while staying far
shorter than any turn timeout (the smallest `default_request_timeout_s` is 600 s) —
so a genuinely wedged spawn fails the `create()` call with `SessionOpenTimeout`
(releasing its reservation) instead of hanging the caller.

### The three consequences of running closes unlocked
* **Order.** Each path still closes **first** and removes from `_sessions` only once
  `close()` has returned. The other obvious shape — unregister-then-close — fixes the
  stall but reintroduces the orphan: `registered=False, connected=True`, a live
  subprocess with no handle and no retry.
* **Counting.** Two paths can now be inside the **same** session's `close()` at once
  (a `DELETE` and a reap tick, say). `AgentSession.close()` tolerates that — the
  second caller queues on the session's own lock and returns once it sees
  `status == "closed"` — but both callers then reach their removal. So removal is
  `pop(sid, None)` everywhere and **only a pop that actually removed something may
  claim the teardown**. Without that guard a concurrent reap and `DELETE` both
  claimed one teardown (**measured:** `reap_once returned=1, DELETE ok,
  close_calls=2`, for a single deregistration).
* **The removal is a bare synchronous `pop` with no lock re-acquisition** — the same
  reasoning as `create()`'s reconcile (below). A lock-free pop is safe for the cap
  too: it only ever *shrinks* `len(_sessions)`, so a concurrent `create()`'s check can
  only be conservative, never overshoot.

### Reaper vs. a busy session — the unresolved question, decided
`AgentSession.send()` holds the session's own lock for the whole turn, and on the
abandon-without-close path that lock stays held. `disconnect()` is measured to
terminate the subprocess cleanly **at a clean turn boundary** (S5); what it does
when **raced against an actively draining turn** — block, raise out of the drain
into the caller, or something else — has **never been measured**.

Given that gap, the reaper **skips** any session whose `status == "running"` on a
given tick and leaves it for the next one, rather than force-closing it. Skipping
costs one attribute read; no `await` touches the busy session at all.

> **Correction.** Two claims here used to read "can never block on that session" and
> "can never wedge the registry", full stop. **Both were too strong.** The skip guard
> is `status == "running"`, so it does **not** cover an **idle** session whose lock is
> held across an await — which `interrupt()` does, briefly, for a courtesy interrupt
> after an SSE hangup. A first version of that branch borrowed the turn budget and was
> measured stalling `reap_once` (and `create`, and `close_all`, and any `DELETE`) for
> the whole control-request duration — **1.944 s** in the repro, and `timeout_s`
> (600 s default, 1800 s max) if the SDK's own bound ever failed to fire.

**What is true now, and why the reaper is still safe:**
* That branch is bounded by its own 1 s constant, not by `timeout_s`, so no
  registry-visible wait can scale with a caller-supplied turn budget.
* `AgentSession.close()` refuses to **wait** for a lock held only by a courtesy
  interrupt (`_courtesy_interrupt`) — it disconnects without the lock — so a reap, a
  `DELETE` or a shutdown that lands mid-interrupt does not queue behind it at all.
* Everything else the reaper awaits is a `close()` bounded by one `timeout_s`
  deadline, and since the closes run outside `_lock`, that bound caps how long one
  **sweep** can take, not how long the **registry** can be wedged.

**The accepted cost:** a session wedged in `"running"` forever (a hung turn that never
reaches a `ResultMessage`) would never be reclaimed by this reaper and would hold its
cap slot indefinitely. That gap was closed **at the source** rather than left
aspirational: `sessions.py`'s `send()` enforces `timeout_s` on the turn itself, so a
turn that never produces a `ResultMessage` is force-ended and the session returns to
`status == "idle"` — reclaimable on the very next tick.

**Force-closing a busy session from `registry.py` was rejected.** Without a
measurement of what disconnecting mid-drain actually does, "the reaper might
occasionally kill a live turn's connection" is not a risk this module gets to accept
on the caller's behalf. Bounding the turn at its source is the fix, not reaching in
from outside.

---

## CP-023 — registry.py — SessionRegistry.create()

### Why the factory call is inside the `try`
A reservation must be released on **any** failure between the increment and the
insert — including the factory itself raising (bad options, for instance), not just a
failing or timing-out `open()`.

### Why the reconcile is synchronous and does not re-take the lock
> **Tried and failed:** `async with self._lock: self._reserved -= 1` on the failure
> path, and a second lock acquisition on the success path.

A reviewer reproduced, **against the real `SessionRegistry`**, that if a second
coroutine held `_lock` at that exact moment (an entirely realistic in-flight
`close()`/`reap_once()`) and this `create()` call's task was cancelled while
**awaiting that contended lock**:
* on the failure path, `_reserved` was never decremented — a **permanent capacity
  leak**, once per occurrence;
* on the success path, `_reserved` stayed incremented **and** the already-opened
  session was left unregistered — unreachable via `get()`/`list()`, so nothing could
  ever close it either.

Every reconcile-side mutation of `_reserved`/`_sessions` is now a **bare synchronous
statement**. On a single-threaded event loop a task can only be preempted (including
by cancellation) at a suspension point, and there is none left between "`open()`
returned" and "the reservation is released / the session is registered" — so that
sequence is atomic and **cancellation-immune by construction, not by locking**.

Correctness does not depend on serializing a plain `int` decrement against anything;
only the check-and-increment the reservation came from needed the lock.

The `except BaseException` arm is the release path for a `create()` **cancelled while
genuinely suspended inside `open()`** — `CancelledError` is a `BaseException`, not an
`Exception`.

This also retires the second half of an older finding — "an opened session must be
closed rather than leaked if it won't be registered" — because registration is now
unconditional once `open()` succeeds.

---

## CP-024 — registry.py — SessionRegistry.close()

Looks the session up (does not remove it) before awaiting `close()`, and removes it
only once `close()` has actually succeeded. If `close()` raises, the session stays
registered and reachable via `get()`/`list()` rather than silently vanishing with no
way to retry or even observe that teardown failed. A second `close(sid)` is a safe
retry (`AgentSession.close()` is idempotent).

**Measured against the code that popped first**, with a session whose `close()`
always raises: `close()` left `still_registered=True`, while `reap_once()` and
`close_all()` both left `still_registered=False, disconnected=False` — the registry's
only handle on a still-connected subprocess, dropped. All three paths now share the
"remove only after `close()` returned" rule and differ **only in what they do with the
failure**: raise it (here), retry next tick (`reap_once`), report it (`close_all`) —
never in whether the handle survives it. It matters here in particular because
`api.py`'s `DELETE` turns the raised failure into a real problem document precisely so
it does not answer 204 for a subprocess that is still alive.

**Deliberately no "is a turn running" guard**, unlike `reap_once()`.
`AgentSession.close()` itself interrupts an in-flight turn and waits for it to end
before disconnecting, so this stays correct calling it unconditionally — an explicit
`DELETE` genuinely tears the session down rather than leaving a busy session
permanently un-reclaimable by any means.

`_lock` is held only for the lookup; `session.close()` runs **unlocked** — see the
module note (CP-022) for the measured stall that
motivated it. Removal is `pop(sid, None)`, synchronous, with no lock re-acquisition: a
contended re-acquire is the cancellation strand described under `create()`, and a
concurrent reap tick may have already popped the session — in which case this caller's
`close()` still succeeded (the same teardown, observed by two callers), so this
`DELETE` reports success rather than inventing a failure. `SessionNotFound` is decided
at **lookup** time, before the close begins.

---

## CP-025 — registry.py — SessionRegistry.close\_all()

Closes every session, most-recently-created first, removing each only once its
`close()` has returned — rather than snapshotting and clearing `_sessions` up front.
If this coroutine is cancelled partway (an ASGI shutdown timeout, realistically),
whatever it has not yet reached is still tracked and still closeable, instead of being
silently orphaned by an early `clear()`.

### "One failure does not stop the rest" means one `Exception`
A `BaseException` — cancellation above all — propagates and **aborts** the sweep, so
sessions it had not yet reached are never attempted at all (**measured:**
`never_even_attempted=['a']`). Recorded rather than fixed: widening the catch to
`BaseException` would swallow the shutdown cancellation that is telling this method to
stop.

### Why a failed close stays registered even though nobody will retry
Unlike `reap_once()`, nobody will retry here — the process is on its way out. Keeping
the session is still right, for three reasons that do not depend on a retry:
* The failure mode being avoided is **dropping the only handle on a subprocess that is
  still connected**. A shutdown that pops first does that at exactly the moment the
  handle can no longer be recovered — worse than doing it mid-flight, not better.
* `list()` afterwards then names every session **not known to have shut down
  cleanly** — observability at the one moment the service can no longer be asked
  anything. The summary `_log.error` carries the same list into the log, so the record
  survives even though nothing calls `list()` after shutdown.
* A caller wanting another attempt just calls `close_all()` again; it is idempotent and
  terminates.

> **Correction.** The exact claim is "not known to have closed", **not** "still
> connected". A close cancelled *after* `disconnect()` already succeeded leaves a
> session both registered and disconnected — precisely what `AgentSession.close()`'s
> `except CancelledError` handler produces. **Measured** with a fake whose `close()`
> disconnects and then raises `CancelledError`: `left=['a', 'b'],
> registered_and_still_connected=['a'], registered_but_NOT_connected=['b']`. An earlier
> draft claimed the exact-record version and was false.

### Termination
Each session is attempted exactly **once** per call — the loop tracks what it has
already tried instead of relying on the pop to make progress, so it terminates even
when every `close()` fails, and it still picks up a session inserted by a `create()`
whose `open()` was in flight when the sweep started (that insert does not take
`_lock`).

### The shutdown bound
Closes run sequentially **within** this method but no longer under `_lock`, so a sweep
parked in one session's slow close no longer blocks a concurrent `create()`,
`reap_once()` or `DELETE`.

That fixed *who waits*, not *how long*. Until the Plan 4 follow-up the aggregate was
**O(N × per-session wait)**, up to N × `timeout_s` (600 s default, 1800 s max) each —
8 × 600 s = 80 minutes worst case. This method runs from the ASGI lifespan, so that
total **is** the shutdown, and Docker `SIGKILL`s at `stop_grace_period` regardless.
Reproduced against `2638616` with N sessions closing at the cost a container actually
measured for a session wedged mid-turn (5.4–5.9 s):

| | | | |
|---|---|---|---|
| n=0 | 0.000 s | n=8 × 0.5 s | 4.043 s |
| n=1 × 0.5 s | 0.506 s | n=8 × 2.0 s | 16.085 s |
| n=3 × 0.5 s | 1.523 s | **n=8 × 5.9 s** | **47.255 s** |

Exactly N × per-session cost, and that is the benign shape — a close that genuinely
hangs never returns at all.

### The aggregate budget, and why it is split in two
Every wait is now charged against **one deadline** taken at entry, from
`Settings.shutdown_budget_s` (60 s), in two phases:

1. **Clean closes**, until `budget − reserve`. Each attempt gets a **fair share** of
   what is left: `remaining ÷ sessions still to attempt`.
2. **Force kills**, with the reserve (`min(5 s, 25 % of the budget)`).

*Why fair share and not a fixed per-session slice.* A per-session bound is exactly
what `timeout_s` already is, and the whole defect is that N of them add up to nothing.
Fair share also means one wedged session cannot eat the budget and cost the healthy
ones their clean teardown — the LIFO sweep hits the most recent session first, and
with a fixed "give the first one everything" slice, three healthy sessions behind a
wedged one get nothing. A close that returns early hands its unused time back.

*Why a reserve at all.* A kill with no time left is not a kill. It is a fraction with
a ceiling so the split still works for the sub-second budgets the tests use: 5 s out
of 60 s, 0.25 s out of 1 s.

*Why the closes run in tasks.* Each `close()` runs as its own task and is awaited with
`asyncio.wait(timeout=...)`, rather than `await`ed directly under `asyncio.timeout`.
A close whose **cancellation** also hangs would otherwise overrun the budget from
inside its own cleanup — `AgentSession.close()`'s `except CancelledError` arm does a
best-effort `disconnect()`, which is not itself bounded. Instead it is cancelled,
given `_CANCEL_GRACE_S` (0.5 s, itself charged against phase 1's deadline, so it can
only shorten to zero), then abandoned with a strong reference held so the GC cannot
turn a bounded shutdown into `Task was destroyed but it is pending!`.

*Cancellation from our own caller is unchanged.* It still **aborts** the sweep — the
in-flight close is cancelled with it rather than detached, since nothing would ever
observe it again.

### Phase 2: killing what would otherwise leak
Anything not closed cleanly — ran out of time, raised, or was never reached — is
offered `session.kill()`: `disconnect()` with no turn finalisation and no lock (see
AgentSession.kill() (CP-012)). The alternative is a subprocess
that outlives the container, which is the failure this whole path exists to prevent.

The kills run **concurrently**, unlike the closes: a kill neither waits on a turn nor
takes the session lock, so there is nothing for fair share to arbitrate, and the
reserve is small enough that doing them one at a time would mean only the first one
happened.

`kill()` is looked up with `getattr` and is **optional**: a session object without one
(the HTTP-level fakes, anything the SDK grows later) is reported as not killed rather
than crashing the last few milliseconds of shutdown.

**A killed session is not deregistered.** A kill is not a clean close, so `list()`
keeps meaning "not known to have shut down cleanly", and only a `close()` that
*returned* removes a session — the close-first-then-remove-on-success ordering is
untouched. The one thing that does change is the older summary line: a session that
was successfully killed is excluded from "their subprocesses may still be alive",
because `kill()` returned.

### Saying what happened
Task 4 measured this logging **nothing** on success, so a clean sweep and a sweep that
never ran were indistinguishable in a container's logs. One line, always, naming every
outcome and whether the budget was hit — `INFO` when everything closed cleanly,
`ERROR` otherwise:

```
close_all: swept 3 session(s) in 0.000s of a 60.0s budget: 3 closed cleanly, 0 killed, 0 neither
close_all: swept 4 session(s) in 0.949s of a 2.0s budget: 1 closed cleanly, 3 killed, 0 neither (shutdown budget hit)
```

### The budget is `compose.yaml`'s `stop_grace_period`, minus the drain
`stop_grace_period` (100 s) = `--timeout-graceful-shutdown` (30 s, the request drain)
+ `shutdown_budget_s` (60 s) + 10 s margin. That is not a comment anybody has to
honour: `test_the_compose_grace_period_follows_the_shutdown_budget` reads all three
numbers out of `compose.yaml`, the `Dockerfile` and `config.py` and fails if the
arithmetic stops holding. Raising the budget without raising the grace is a red test,
not a `SIGKILL` in production.

### Mutation-pinned
Nine mutations over the bound, every one killed: bound removed (each close awaited
directly), bound loosened (× 10), bound applied per-session instead of in aggregate,
the clean-phase deadline check deleted, the budget hardcoded past `Settings`, the
force-kill phase removed, the summary log removed, "budget exhausted" never reported,
and the default budget raised past what the grace period covers. The fourth of those
survived the first pass and needed
`test_close_all_does_not_start_a_teardown_it_cannot_wait_for` written for it: a
negative fair share still "bounds" each attempt (`asyncio.wait()` just returns), so
the total stayed bounded while the sweep started teardowns nobody was left to wait
for — which latches `_closing` on a session it is about to kill anyway.

Plus 600 randomised rounds of concurrent `create`/`close`/`reap_once`/`close_all` with
slow, hanging, failing and `BaseException`-raising teardowns and killable/unkillable
subprocesses, asserting the aggregate bound alongside the cap, `_reserved`, and
"nothing deregistered while still connected": **0 violations**. It discriminates:
the same harness at `2638616` (which has no budget at all) reported **35 violations in
100 rounds** — every round that drew a hanging teardown, `close_all()` never returned.

---

## CP-026 — registry.py — SessionRegistry.reap\_once()

Closes every idle-beyond-TTL session and returns how many it **closed**.

### The return value counts teardowns, not attempts
It used to be `len(stale)` — so a tick on which every `close()` failed still reported a
full sweep, meaning the one number the reaper reports was at its **least truthful
exactly when something was wrong**.

The count is additionally guarded: `closed += 1` only when this sweep's own
`pop(sid, None)` actually removed the session. With the closes unlocked, a `DELETE` can
be inside the same session's `close()` concurrently and claim the teardown first;
counting on the close alone reported one deregistration twice (**measured with the
unguarded shape:** `reap_once returned=1, DELETE ok, close_calls=2`).

> **Correction.** An earlier docstring called this number "the reaper's only
> observability", which was **false at the time** — `start_reaper()`'s loop was a bare
> `await self.reap_once()` with the value unbound, so a background reaper that closed
> two sessions emitted **zero** log records. Fixing the claim by fixing the code was the
> better half of the choice.

### A failed close is retried next tick
The session stays registered, is still idle and still past its TTL, so it re-enters
`stale` unchanged; `AgentSession.close()` is idempotent and deliberately leaves
`status` non-terminal when `disconnect()` fails, so the retry genuinely retries.

**The accepted cost, stated precisely.** `AgentSession.close()` latches `_closing`
before its first await and never clears it, so a session left behind by a failed close
stays visible in `list()`/`GET` but **refuses every PATCH and every message with
`SessionClosed` (409)** until a later tick succeeds. **Measured against the real
`AgentSession`:** `returned=0, registered=True, status='idle', _closing=True,
client_connected=True`; `set_model()` → `SessionClosed`; the reaper's retries succeeded
on the **third** tick. It is a **tombstone that still holds a cap slot**, not a usable
session — identical to what an explicit `DELETE` already leaves behind on the same
failure, which is why it is accepted rather than special-cased.

### Why the skip is re-checked immediately before each close
The closes run unlocked, so a turn can start on a later stale session while this sweep
is parked inside an earlier one's `close()` — and a session freshly used in that window
is no longer stale either. Both re-checks (`status == "running"`, `idle_seconds <= ttl`)
plus the `session is None` check for a concurrent `DELETE`/`close_all` are synchronous
with the `close()` call that follows them.

---

## CP-027 — registry.py — SessionRegistry.start\_reaper()

The loop logs `reap_once()`'s count. Until it did, nothing read the value — **measured:
a background reaper that closed two sessions emitted zero log records**, so the only way
to learn a session had been reclaimed was to notice it missing from `GET /v1/sessions`.
A service whose stated purpose is to make the agent loop observable should not compute
the one fact its only background task knows and then discard it.

A quiet tick stays quiet (the common case is nothing to do, once a minute, forever); a
tick that **failed** to close something is already loud, via `reap_once()`'s per-session
exception log.

---

## CP-028 — runner.py — \_LIMIT\_MARKERS / detect\_limit()

`ResultMessage.terminal_reason` / `subtype` values that mean a **guardrail stopped the
run** rather than the agent finishing.

**Observed 2026-07-26 via `spike/probe_limits.py`** (two real API calls against
`claude-agent-sdk==0.2.128`):

| Limit hit | `subtype` | `terminal_reason` |
|---|---|---|
| `max_turns=1` | `error_max_turns` | `max_turns` |
| `max_budget_usd=0.01` | `error_max_budget_usd` | `budget_exhausted` |

`"max_turns"` as a `terminal_reason` value is additionally corroborated by
`ResultMessage.terminal_reason`'s own docstring in `types.py`.

**Why measuring mattered.** The plan had guessed the budget markers as `max_budget`,
`error_max_budget` and `budget_exceeded`. All three are wrong and none appears anywhere
in the installed SDK. Had they shipped, a budget-exhausted run would have matched no
marker and been reported as `limit_hit: null` — indistinguishable from a normal
completion. The *turn* markers were guessed correctly, which is precisely what makes
this class of error dangerous: **half the table looked fine.**

`budget_exhausted` rests on a **single observation** and is documented nowhere in the
SDK. If a future CLI renames it, budget stops silently regress to `limit_hit: null`. A
periodic re-run of the probe is the only defence. **Recheck on any SDK upgrade.**

---

## CP-029 — runner.py — build\_outcome() / OutcomeSource

`build_outcome()` is shared by `Run.events()` (one-shot) and `AgentSession.send()` (a
session turn) so the ~15-field construction cannot drift between the two — the same kind
of drift that forced `outcome_recorded` to be hand-carried between endpoints in Plan 1.

`OutcomeSource` is the protocol `api.py`'s `_summary` needs. Both `Run` and `TurnResult`
satisfy it, so the two endpoints share one summary builder. `turn_cost_usd` is on the
protocol for the same reason: `Run` computes it as a property, `TurnResult` carries the
delta `AgentSession._record_turn` measured, and `_summary` reports it without knowing
which surface it is summarising. The alternative — `api.py` branching per endpoint — is
exactly the hand-carrying that caused the Plan 1 drift.

### `unattributed_abort()` — the same drift, caught once

`RunResponse.turn_cost_usd` documents **one** meaning for **four** routes, so the rule
that decides `0.0` versus `null` has to be one function, not two copies. It is applied
by `AgentSession._record_turn` (to the delta) and by `Run.turn_cost_usd` (to the
one-shot cumulative, which *is* that run's cost because the connection lasts exactly
one run).

It was very nearly two: the guard was first written inline in `_record_turn`, which
left `/v1/query` answering `0.0` for precisely the case the shared description called
`null` — the `outcome_recorded` drift, reintroduced inside the field added to prevent
it. `/v1/query` has no interrupt endpoint so no caller can reach it, which is exactly
why an inline guard would have survived indefinitely. **Narrowing the description to
name the routes it applied to was the alternative, and was rejected:** a response shape
used by four routes should not need a per-route footnote to be read correctly.

`ABORTED_TERMINAL_REASONS` lives in `runner.py` for the same reason — `sessions.py`
already imports from `runner.py`, so the constant had to move that way rather than the
reverse (a cycle). It is re-imported into `sessions.py`, so the old import path still
resolves and nothing that referenced it there had to change.

---

## CP-030 — runner.py — \_as\_stream()

Wraps a plain prompt as the SDK's single-message streaming format.

The installed SDK raises `ValueError` from a plain string prompt whenever
`options.can_use_tool` is set — *"can_use_tool callback requires streaming mode"* —
confirmed live against `claude-agent-sdk==0.2.128`.

`options.py` no longer sets `can_use_tool` by default (`permission_enforcement` defaults
to `"none"`, and its `"hook"` mode attaches a `PreToolUse` hook, which has no such
requirement), so this wrapping is **not currently load-bearing** for any request most
callers will make. It stays unconditional so the code path is uniform regardless of
`permission_enforcement` — a future caller of `create_run`/`Run` directly, or a future
config that reintroduces `can_use_tool`, should not silently depend on which branch
happened to run — and because the dict shape is exactly what the SDK's own non-streaming
path constructs internally for a string prompt (`_internal/client.py`), so behaviour is
unchanged either way.

**If this wrapping is ever removed, first confirm nothing still sets `can_use_tool`
anywhere in this codebase.**

---

## CP-031 — runner.py — Run.events()

### `aclosing()` is not decoration
`async for` does **not** close its iterator when the loop body raises or is abandoned
via `GeneratorExit` (PEP 533 was deferred) — the SDK's own `_internal/client.py` carries
this exact warning about its inner generator. Without `aclosing`, a
cancelled/disconnected consumer (routine for the SSE endpoint) leaves the underlying
`query()` generator — **and the Claude Code subprocess it owns** — cleaned up only by
non-deterministic GC finalization, **burning the caller's budget in the background**.

### `outcome is None` is a distinct case
`Run.outcome` stays `None` if the message stream ends without ever producing a
`ResultMessage` (CLI crash, early exit, client disconnect before the run finished).
Callers — including the HTTP layer — must handle that as distinct from a normal or
limit-hit finish, not assume a `ResultMessage` always arrived.

`RunTimeout` is raised from `asyncio.timeout(self._limits.timeout_s)`, the same type
`AgentSession.send()` raises, so a caller can `except RunTimeout` uniformly across both
paths.

---

## CP-032 — runner.py — Run.turn\_cost\_usd

A **property** rather than a stored field because there is nothing to compute: a one-shot
`query()` owns its connection for exactly one run, so the SDK's cumulative
`total_cost_usd` **is** this run's cost. The cumulative-per-connection behaviour (S6) is
what makes the two differ on a **session**, where the connection spans many turns — see
`_record_turn` (CP-018), which does have to difference
them.

---

## CP-033 — runner.py — sdk\_version()

Lives in `runner.py` rather than `api.py` so the boundary rule — **`api.py` never imports
`claude_agent_sdk`** — holds without exception.

---

## CP-034 — api.py — the import boundary and `from __future__`

### `api.py` must never import `claude_agent_sdk`
Everything agent-related comes through `runner.create_run`, which is injectable so tests
never make API calls. `sdk_version()` lives in `runner.py` for the same reason.

### `api.py` must NEVER contain `from __future__ import annotations`
PEP 563 stringifies the `Annotated` aliases defined **inside `create_app`**
(`SettingsDep`, `FactoryDep`, `RegistryDep`), which FastAPI then cannot resolve: every
route answers **422**, and `/openapi.json` raises `PydanticUserError`. If the import is
absent, keep it absent — this is the one file in the package where it is forbidden.

### Streaming routes carry no return type annotation
FastAPI infers a `response_model` from the return annotation when a route has no explicit
one (both streaming routes use `response_class` instead), and
`StreamingResponse | JSONResponse` is not a valid Pydantic field type. Annotating it
breaks route registration entirely — a `FastAPIError` at **app-creation** time, not just
at request time.

---

## CP-035 — api.py — \_summary() / \_turn\_record() / \_record()

### `_summary()`
Builds the response from anything satisfying `OutcomeSource`, so `/v1/query` and the
session turn routes cannot drift — exactly what forced `outcome_recorded` to be
hand-carried in Plan 1.

`sdk_session_id` is the **same value** as `session_id` under a name that says which id it
is. Additive, never a rename — `session_id` already ships. Both are filled from one
attribute here rather than from two places, so they cannot drift into genuinely different
answers.

### `_turn_record()`
Renders `AgentSession.last_turn` for `SessionRecord`. None in, None out — a session that
has never taken a turn reports `last_turn: null`, the unambiguous answer a nested model
buys over flat fields.

It reads the very same `TurnResult` that `_summary` reads, so the two surfaces cannot
disagree about a turn. The three fields both report — `outcome_recorded`, `interrupted`
and the SDK's id — are pinned against each other **over HTTP** by
`tests/test_api_sessions.py::test_the_record_and_the_turn_response_agree_about_the_same_turn`,
because "they read the same attribute" is the kind of claim this project has had
disproved by execution before.

### `_record()`
`model` and `permission_mode` are the two options `PATCH` can write, **and only those** —
see `AgentSession.__init__` (CP-010) for why the rest is not
echoed.

`last_turn` is on **every** route that builds a record, not just `GET`: `PATCH` answers
with a `SessionRecord` too, and a record whose contents depended on which verb produced it
would be a second `outcome_recorded`.

---

## CP-036 — api.py — create\_app.lifespan()

`verify_credentials()` runs **before** `start_reaper()` and **outside** the `try`.

Raising there aborts startup, and an ASGI server turns that into a non-zero exit —
uvicorn's `Server.startup()` calls `sys.exit(STARTUP_FAILURE)` on a failed lifespan, so a
container **restarts** instead of serving requests it cannot fulfil.

Outside the `try` deliberately: nothing has been started yet, so there is nothing for the
`finally` to tear down, and running `stop_reaper()`/`close_all()` against a registry that
never started would only add noise to the one message an operator needs to read.

### `verify_mounts()` sits beside it, and after it

Same mechanism, same placement, same reasons. **After** `verify_credentials()` because a
missing key is the more common mistake and should be the first thing an operator reads.

Gated on `Settings.require_mounts`, which unlike `require_credentials` defaults **false** —
outside a container there is nothing to verify, since `workspace_dir` defaults to
`./workspace` and the validator creates it on first run. `compose.yaml` turns it on.

**Why it exists.** Both failure modes it catches are silent, and neither Docker nor compose
will catch them for you. Measured on Docker Desktop for Windows: `-v`, `--mount type=bind`
**and** compose's `bind: {create_host_path: false}` all create a missing host directory and
start the container anyway. (`--mount` is stricter on Linux Docker Engine; that does not
reach this platform.) So:

- a missing `-v …:/workspace` leaves an empty directory the service itself created — it
  boots, reports healthy, and everything the agent writes is discarded on stop;
- a `AGENT_SERVICE_REFERENCE_DIRS` entry that does not match its mount target is accepted
  without complaint, and is then invisible to `Read`/`Glob`/`Grep` while `docker exec ls`
  shows the files at the real path.

**Why the two directories are checked differently.** `workspace_dir` must be *under a mount
point*, not merely exist — "it exists" is precisely the state the bug produces. `exists()`
therefore cannot answer the question, and bare `os.path.ismount(path)` is too strict,
because pointing `workspace_dir` at a subdirectory of a mount (`-v host:/data` with
`AGENT_SERVICE_WORKSPACE_DIR=/data/ws`) is a legitimate layout. `_mounted_under()` walks up,
stopping before the anchor: **a container's `/` is itself a mount**, so counting it would
make the check pass for every path and quietly do nothing — the exact failure this exists to
remove. Pinned by `test_the_root_is_not_counted_as_a_mount`.

A reference directory is only required to **exist**. It is never created by this service, so
existence already separates a good config from a typo, and demanding a mount point would
reject naming a subdirectory of one.

**Measured end to end**, against the built image: no workspace mount → `MissingMounts`,
`Application startup failed`, **exit 3**; a reference entry with no matching mount → the
same; both mounted correctly → running, `/healthz` ok.

---

## CP-037 — api.py — run\_query\_stream()

### Where the status-code boundary is
Building options (`LimitExceeded`, `InvalidWorkspacePath`) is pure request validation and
happens **synchronously, before the response is committed** — so it can still become a real
status code, exactly like `/v1/query`. Once `run.events()` starts being iterated, the 200
and the SSE headers are already on the wire; `RunTimeout` and SDK errors raised during
iteration cannot become a status code any more and stay in-band as `event: error`.

### Why `close_stream()` is an `async def` wrapper
**Not** `background=BackgroundTask(stream.aclose)` directly. An async generator's bound
`.aclose` is a builtin/C method, not a plain `async def`, so `inspect.iscoroutinefunction`
— what Starlette's `is_async_callable` uses to decide sync vs. async — returns `False` for
it. `BackgroundTask` would then run it via `run_in_threadpool`, which calls
`stream.aclose()` **synchronously**, creating a coroutine object and immediately
discarding it *without ever awaiting it* (*"coroutine method 'aclose' … was never
awaited"*), leaving the generator open until Python's asyncgen-GC finalizer eventually
reaps it — exactly the non-determinism this exists to remove. The `async def` wrapper makes
Starlette detect it correctly and `await` it in-line.

### Why the background task is needed at all
Starlette **never** calls `aclose()` on `generate()` (its `body_iterator`) when the client
disconnects while `generate()` is suspended at a `yield` — the realistic stalled-client
case. The cancellation lands in Starlette's own `send()` call, not inside either
generator's frame, so neither `generate()` nor `stream` unwinds through a `finally`. Left
alone, `stream` — and the Claude Code subprocess it owns via `aclosing(query(...))` in
`runner.py` — is reclaimed only by the cyclic GC finding the reference cycle,
non-deterministically.

The background task runs **unconditionally** once Starlette's response is done, including
on the disconnect path (Starlette runs `response.background` after its task group has
swallowed the disconnect cancellation). On normal completion `stream` is already exhausted
and `aclose()` on an exhausted async generator is a documented no-op, so it is inert there.

---

## CP-038 — api.py — create\_session() / get\_session() / delete\_session()

### `POST /v1/sessions` — why 400 is declared
`registry.create()` calls `build_options()`, so a bad `options` payload raises
`LimitExceeded` (e.g. `max_turns=99999`) or `InvalidWorkspacePath` (e.g.
`workspace_subdir="../../etc"`) **before any subprocess is started**. Confirmed by driving
both requests. `/v1/query` has always declared it; this route creates a session from the
identical `RunOptions` model and must say so too, or a client reads 400 as undocumented.

### `GET /v1/sessions/{sid}` — why 500 **and** 502 are declared
This is **not a pure lookup**: it awaits `session.context_usage()`, a live **control
request** down the SDK channel.

* **502** — a disconnected or wedged client raises `CLIConnectionError`, which `errors.py`
  maps to 502. Confirmed by driving a `GET` against a session whose control channel never
  answers.
* **500** — the SDK bounds its own control requests at 60 s and then raises a **plain**
  `Exception("Control request timeout: ...")`, which `errors.py` does not classify, so it
  falls through to 500. The identical condition `PATCH` already declares 500 for. Driven by
  `tests/test_api_sessions.py::test_get_surfaces_an_unclassified_control_failure_as_500`.

A session being torn down is a **different** condition and is *not* an error here — see
`context_usage()` (CP-021).

### `DELETE /v1/sessions/{sid}` — why a teardown failure is not flattened into the 204
`registry.close()` lets `AgentSession.close()`'s exception propagate, so it is mapped to a
real problem document rather than a 204 that would falsely report the subprocess as gone.
Anything not otherwise classified falls through `errors.py` to **500**, which is declared.
Already exercised by `tests/test_api_sessions.py`'s dedicated close-raises case, so the
declaration documents behaviour that is pinned, not merely possible.

---

## CP-039 — api.py — send\_turn()

`POST /v1/sessions/{sid}/messages` drains the **whole** turn inside its `try`, so every
failure the drain can raise is still uncommitted and becomes a real status code — unlike
the streaming route, where only failures up to the first message can. All confirmed by
driving real requests:

* **504** — `AgentSession.send()` bounds the drain with `asyncio.timeout(timeout_s)` and
  raises `RunTimeout` on expiry.
* **502** — a `ProcessError` / `CLIConnectionError` / `CLIJSONDecodeError` from the agent
  subprocess mid-drain.
* **500** — `to_problem`'s fallthrough. `errors.py` classifies `ProcessError` /
  `CLIConnectionError` as 502 and `RunTimeout` as 504; everything else the drain can raise —
  a broken anyio stream, an SDK internal, a plain `RuntimeError` from a transport that has
  gone away — reaches the 500 at the bottom. Driven by
  `tests/test_api_sessions.py::test_a_turn_failing_in_an_unclassified_way_is_500`.
* **409** — a turn is already running (`SessionBusy`) or the session is closed
  (`SessionClosed`).

`/v1/query` declares 502/504 for the identical drain; this route was simply never updated
to match until now.

### `x-sdk-session-id` — why a header, and why it is read off the summary

Added 2026-08-05 for a relay that runs these containers, sees every model request they
make (each carrying the SDK's `x-claude-code-session-id`), and keys its own records on
`SessionRecord.session_id`. Those two never join. The join key is `sdk_session_id`, and the
only place it was reachable was **inside a turn's response body** — so the relay was
running a scanner over every SSE stream with a tail buffer for chunk boundaries, on the hot
path of every conversation, to recover one string.

The header carries the same value where a relay already looks. Two details:

* **Read off `summary.sdk_session_id`, not `session.session_id`.** The body's field and the
  header must be the same value by construction. This API's known trap is that two
  identifiers once shared the name `session_id`; a header that could disagree with the field
  printed beside it would be a third instance of the same problem.
* **Omitted, never sent empty.** An empty header is a value a relay can key on — one that
  would join every id-less turn to the same non-existent conversation. Pinned by
  `test_the_header_is_omitted_rather_than_empty_when_the_id_is_unknown`.

It is declared in the OpenAPI document, not merely sent, including the fact that it can be
absent. That is the standard the `sdk_session_id` / `session_id` field distinction set, and
the reason the caller's own version of this bug took an afternoon rather than a week.

---

## CP-040 — api.py — stream\_turn()

### Why the first event is advanced before the response is committed
`AgentSession.send()` is an async **generator**: nothing in its body runs until it is first
advanced, so its `SessionBusy` / `SessionClosed` raises do **not** happen at the call site —
a `try` around a bare `send()` catches nothing. Advancing it once forces them to surface
while the response is still uncommitted and a real 404/409/504 can still be returned.

The cost, deliberate: response headers are withheld until the turn's first message arrives.
For a real session that is the SDK's `system`/init message, which is prompt.

This is why this route differs from `/v1/query/stream`, which commits its 200 before the
first message and therefore reports even a zero-message failure in-band.

**That cost turned out to be what makes `x-sdk-session-id` possible here.** The init message
this route already waits for is exactly where `_send_impl` reads `session_id` from, so the
value exists *before* the response is committed — the header needs no buffering and delays
no frame. `/v1/query/stream` has no counterpart for precisely the same reason it reports
failures in-band: there is nothing read yet when its headers go out. If the `anext` above is
ever removed, `test_the_streaming_turn_carries_the_header_before_the_first_frame` fails
rather than the header silently degrading into one a relay cannot rely on.

### `turn_ended` — both assignments are load-bearing
> This comment has been **wrong in both directions**. It once said "the placement is
> load-bearing" (true then, for the wrong reason) and was then replaced with "moving either
> does not cause a spurious control request", which a change to `interrupt()` had already
> falsified. Prefer a named test over a claim in the source.

* Deleting the assignment in the `except` branch takes the SDK control-request count on a
  mid-drain failure from **0 to 1**, because a turn that raised leaves
  `AgentSession._turn_abandoned` set and `interrupt()` acts on that. Pinned by
  `tests/test_api_sessions.py::test_a_mid_drain_failure_does_not_issue_a_control_request`.
* Deleting the one after the loop does the same for a turn that completed normally. Pinned
  by `::test_clean_completion_does_not_interrupt_the_session`.

### Why `_frame()` sets `turn_ended` when the frame is *built*
The turn has **ended** — the SDK's `ResultMessage` is what ends it, and `AgentSession` has
already recorded the turn by the time that frame exists. Everything after is delivery, and
delivery is the consumer's business.

Load-bearing for the straddle case: if **that write** never completes, the assignment after
the loop never runs, and `close_stream()` would interrupt a turn whose `ResultMessage` was
already consumed — a control request aimed at a turn the subprocess had finished producing
(**measured:** `interrupts == 1` on a turn that completed with a real result). Setting it
here rather than after the write says what is true *at this instant*, regardless of whether
the frame ever reaches anyone.

This keys off "a result frame was **built**" rather than "the loop ended", which depends on
the SDK ending a turn at its first `ResultMessage` (S1). A stream carrying on past one would
leave this set for the rest of the turn, so the cleanup would not interrupt an abandonment
after it. **Recheck on any SDK upgrade** — the same caveat `_record_turn` carries.

### `close_stream()` — two steps, and their order is load-bearing
It runs unconditionally once Starlette is finished with the response, **including** the
client-disconnect path.

**1. Interrupt, but only if the turn did not end on its own.** A consumer that takes an
event and goes away leaves the CLI subprocess still producing the rest of that turn.
`AgentSession` discards whatever is already sitting in the SDK's connection-scoped buffer at
the top of the next turn (`_discard_residue`), but messages still **in flight** from the
subprocess are not coverable from inside that module: they land during the **next** turn's
drain, and a stray `ResultMessage` among them ends that turn early — one caller's turn
attributed to another. Only the SDK can stop the subprocess producing, so this is a
**correctness step**, not a latency or cost optimisation.

Which state the session is in when this runs depends entirely on **where the disconnect's
cancellation landed**, and both interleavings are real:
* **stalled write** — the turn is parked at a `yield`, the session lock is still held and
  `status == "running"`.
* **real socket hangup (the common one)** — the cancellation lands inside
  `stream.__anext__()`, so the turn has already unwound through its own `finally` and
  `status` is back to `"idle"` before this runs.

`AgentSession.interrupt()` covers **both** (running **or** a turn abandoned mid-drain),
which is what makes this call meaningful rather than a silent no-op on the second one. The
first version keyed only off `"running"` and did nothing on the common path.

**Why interrupt comes before `aclose()`** — narrower than it looks. On the stalled-write
path, interrupting while the turn is genuinely `running` is what makes `AgentSession`
**stamp** that turn, so the `TurnResult` says `interrupted=True`. Closing first would still
get the control request out (the abandoned-turn fallback catches it), but the turn would
already have been recorded as a plain failure — we would have stopped it deliberately and
then reported that we had not. Pinned by
`tests/test_sessions.py::test_interrupt_then_aclose_labels_the_turn_as_interrupted` and its
reverse-order counterpart.

**This is the OPPOSITE order to `AgentSession.close()`**, which tries `aclose()` first. Not
an inconsistency: `close()` goes on to `disconnect()`, which kills the subprocess outright
(S5), so nothing is owed an interrupt there and issuing one only risked hanging on a wedged
control channel. Here the session **survives** and will take further turns, so the
subprocess must actually be told to stop.

Failure is logged and swallowed: `interrupt()` is a control request, already bounded by the
SDK's own 60 s control-request timeout, and a wedged control channel must not stop the turn
being force-ended below. Unlike `AgentSession.close()`, nothing here holds the registry-wide
lock, so a slow interrupt degrades this one session and nothing else.

**2. `aclose()`, always, from a `finally`.** Starlette never calls `aclose()` on a
`StreamingResponse`'s `body_iterator`, and when the disconnect lands while `generate()` is
suspended at a yield, the cancellation is delivered inside Starlette's own `send()` —
outside both generators' frames — so neither unwinds through a `finally` on its own. Left
alone, the abandoned turn keeps the session lock (**every later turn 409s**) until the
cyclic GC happens to reclaim it. This is also the **only** thing that makes
`AgentSession.close()`'s abandoned-turn handling reachable in the common case.

The `async def` wrapper is load-bearing for the same
`is_async_callable`/`run_in_threadpool` reason as
`run_query_stream` (CP-037).

### `done` vs. `error`
Once the 200 and the SSE headers are on the wire, a failure cannot become a status code. The
problem document is emitted as `event: error` and the stream ends **without** a `done`
frame — that is the whole signal. A client that reads `done` knows the turn completed; a
client whose stream ends on `error` (or ends with neither, i.e. a dropped connection) knows
it did not.

---

## CP-041 — api.py — interrupt\_session()

`interrupted` is the **return value** of `AgentSession.interrupt()`, never inferred from
`session.status` — see `interrupt()` (CP-019) for why the two
are not interchangeable. A failure to **deliver** the request is a third outcome and becomes
a problem document, never `interrupted: false`, which would be indistinguishable from the
honest no-op.

`status` is read **after** the await, deliberately: the turn can end while the control
request is in flight (that is what a successful interrupt looks like), so reading it
beforehand would report a finished turn as still draining. Pinned by
`tests/test_api_sessions.py::test_interrupt_reports_the_status_from_after_the_control_request`.

The route returns **200 whether or not there was anything to stop**. Asking to stop a turn
that has already finished is not an error — that race is unavoidable for any client.

The declared **500** is the SDK's own 60 s control timeout on a running turn, which this
service does not bound (branch 1 of `interrupt()` is unbounded by design; only the courtesy
branch has `_STALE_INTERRUPT_BUDGET_S`). The **504** is `InterruptTimeout` from that
courtesy branch.

---

## CP-042 — api.py — update\_session() (PATCH)

### The `is not None` guards are load-bearing
The SDK reads `set_model(None)` as **"use the default"**, so forwarding an omitted field
would turn `PATCH {}` from a no-op into a silent **reset**. Pinned by
`tests/test_api_sessions.py::test_patch_with_no_fields_calls_neither_setter`, which asserts
on call **counts** — asserting on the resulting values cannot tell "never called" from
"called with `None`".

### No `context_usage` on this route
Unlike `GET`, this route has not fetched it, and `_record` leaves the field null rather than
inventing one.

### Why 409 is genuinely reachable
Rare, but real — worth stating exactly, because the obvious reading is that it is not.
`SessionClosed` requires a session that is **closed yet still registered**, and the three
ordinary teardown paths never leave that state: `registry.close()`, `close_all()` and
`reap_once()` all remove the session from `_sessions`, so a closed session is a 404 from
outside.

What reaches it is the **cancellation path**. `registry.close()` only removes the session
*after* `session.close()` returns, and `AgentSession.close()`'s `except CancelledError`
handler disconnects, sets `status = "closed"`, and then **re-raises**. The `CancelledError`
is not caught in `registry.close()`, so the removal is skipped — leaving exactly the
closed-but-registered session this 409 describes, reachable by any later `PATCH`. (A
`session.close()` that fails some *other* way is **not** this case: `AgentSession.close()`
deliberately leaves `status` non-terminal when `disconnect()` fails, so a retry genuinely
retries.)

Pinned from both ends:
`tests/test_api_sessions.py::test_patch_a_closed_session_is_409_like_the_messages_route`
drives the state over real HTTP, and `::test_patch_openapi_declares_its_reachable_errors`
asserts the declaration exists. **Do not drop either** — the guard in `sessions.py` is what
stops a closed session pushing a control request down a disconnected client and answering
as a 502 "agent process failed".

### The route's prose — corrected by the M1 probe
The description used to say the change applies **"mid-session"**, which readers took as "on
the next turn". The M1 live probe measured the opposite: **both setters take effect on the
turn already in flight, at the very next inference**, and a mid-turn model change **re-prices
the remainder of that turn** — `model_usage` for that single turn billed both models
($0.027 haiku + $0.098 sonnet). The wording is now "immediately, including on a turn already
in flight". No lock was added: the same probe showed a mid-turn control request is safe.
Full detail: set_model / set_permission_mode (CP-020).

Omitted fields are still left unchanged, an empty body is still a valid no-op, and every
option other than these two is fixed for the session's lifetime.

---

## CP-043 — errors.py — the fallthrough 500 does not echo the exception

`to_problem`'s last line is the branch that means *this service does not know what
this exception is*. Every branch above it names a type someone chose to classify,
having read what its message contains; this one, by construction, has not. Until
2026-08-06 it still put `str(exc)` in `detail`.

**The measurement that changed it.** A service pointed at a database with no
tables — which it boots against quite happily, since migrations do not run on
startup — answered `GET /v1/sessions/{sid}/transcript` with:

```
500 {"title": "Internal server error",
     "detail": "(sqlalchemy...ProgrammingError) <class
       'asyncpg.exceptions.UndefinedTableError'>: relation \"sessions\" does not
       exist\n[SQL: SELECT sessions.id FROM sessions WHERE sessions.id =
       $1::VARCHAR]\n[parameters: ('7d177d9b...',)]"}
```

The query, the schema and a bound parameter, on an API with **no authentication
at all**. Found while writing `../../spec/conformance/test_contract_persistence.py`.

**Nothing about it was SQLAlchemy-specific**, and that is the reason the fix is
here rather than in a database-error branch. A `ProgrammingError` was simply the
first unclassified exception anyone happened to look at; the next one arrives
with a message nobody has read either.

**What is kept: the class name, and only the class name.** This is not a fresh
judgement — `api.py`'s `_problem` already draws exactly this line for the log
("the exception CLASS NAME — never `str(exc)`, never the prompt, never options"),
and the response body now follows the rule the logger already had. The name is
worth keeping because it is what lets an operator match a client's bug report to
the ERROR line carrying the traceback, and it is the one thing a caller can
usefully quote under contract C-4.

The operator loses nothing: this branch is the only one `api.py` logs at ERROR
with `exc_info`, so the full traceback and message were already going to the log
and still are. Verified against the original reproduction — client gets
`An unhandled ProgrammingError reached the API boundary…`, log gets the
asyncpg traceback.

**One earlier argument is weakened by this, and is recorded rather than left to
be discovered.** sessions.py — InterruptTimeout (CP-008)
gives two reasons for typing the SDK's bare `TimeoutError`, and the first is that
`str(TimeoutError())` is `''`, so the fallthrough answered with an empty
`detail` — "strictly less than the SDK's own `Exception(...)` said". That
comparison no longer holds: neither reaches `detail` now, so both would read
identically. **The second reason is untouched and is the load-bearing one** — a
time-budget overrun is a 504 everywhere else in this codebase, and answering the
same class of condition with a 500 would be the real defect. `InterruptTimeout`
stays.

Pinned by `tests/test_errors.py::test_the_fallthrough_500_never_echoes_the_exception_message`,
which also covers an exception whose `__str__` is overridden, and by the two
`tests/test_api_sessions.py` cases that previously asserted the opposite.

---

## CP-044 — db/wiring.py — Persistence.usable() and what `/healthz` may do

`/healthz` gained `database_configured` and `database_usable` in **0.6.0**, closing
the gap Q16
identified: a configured database could be entirely unusable while the service
reported healthy and discarded every row.

**Three decisions here, and each one has a failure it is avoiding.**

### It queries a real table, not `SELECT 1`

Measured, one state at a time, against a container:

| Misconfiguration | Where it fails | Caught by `SELECT 1`? |
|---|---|---|
| Host unresolvable | connect (`gaierror`) | yes |
| Wrong password | connect (`InvalidPasswordError`) | yes |
| **Schema never migrated** | the query (`ProgrammingError`) | **no** |

The third is the one worth the probe. Migrations do not run on startup and the
image ships no `migrations/`, so an unmigrated schema is the *default first
state* of any deployment that enables persistence — the likeliest failure is
exactly the one a connection check would pass. `select(SessionRow.id).limit(1)`
touches the table the read routes read.

### `status` stays `"ok"` when `database_usable` is `false`

The container healthcheck is `curl -fsS http://127.0.0.1:8000/healthz`, so it
reads the **status code**. Making a broken database non-200 would have compose
restart a service whose agent side is working, for as long as the database is
down — turning an outage in an optional subsystem into an outage in the required
one. That inverts the design: `RunRecorder` may never raise, the writer discards
rather than failing turns, and persistence is off by default.

`Health.status` was also left as `Literal["ok"]` rather than widened to include
`"degraded"`. Adding a member to a response enum is a **re-typing**, which AS-23
treats as the breaking kind of change, and a generated client with a closed enum
can throw on an unknown value. The new information is additive instead.

Verified: with a rejected credential the container reports `healthy`,
`RestartCount=0`, and `/healthz` returns 200 with `database_usable: false`.

### The probe is bounded, and it warns once

`HEALTH_PROBE_TIMEOUT_S = 2.0`, under the healthcheck's own 5s timeout. A
database that **hangs** rather than refusing would otherwise hang `/healthz` with
it and produce the restart loop by the slower route — the timeout is what makes
the previous decision hold in the hanging case, not just the refusing case.

The WARNING fires once per contiguous outage, with a matching INFO on recovery,
copied from `QueueWriter._warned`. The first version logged unconditionally; the
healthcheck polls every 30s forever (every 1s inside `start_period`), so a
sustained outage wrote a line per poll. Measured at **1 line** afterwards.

**The reason never reaches the caller** — the response is a boolean and the
WARNING carries the exception class name only. `/healthz` is unauthenticated,
and Q16 decided that which of an operator's database mistakes is in force is not
something an anonymous caller is told. Same line `errors.py` and `api.py` draw.

### It made the conformance suite simpler

`../../spec/conformance/test_contract_persistence.py` used to infer the deployment
from an unknown-run probe: 404 with the disabled `type` meant no database. That
inference had a blind spot this work created the evidence for — a configured but
unusable database answers **500**, matching neither branch. It reads `/healthz`
now and skips with an explanation naming the likely cause.

---

## CP-045 — `options.py` — MCP servers (0.8.0)

Added because Agent Studio's ADR-0023 substitutes `${secret:NAME}` into an MCP
server's `headers` and `env` *"on the way to agent-service"*, and until 0.8.0
there was no route by which that could arrive: `mcp` appeared nowhere in `src/`
and nowhere in the published document.

**Three of the SDK's four shapes.** `McpSdkServerConfig` carries
`instance: McpServer` — a live in-process object — so no HTTP request could
produce one. It is **absent from the union rather than rejected at runtime**, so
the OpenAPI document says so and a generated client cannot express it. A runtime
error would have been a worse answer to a request that could never have worked.

**`model_dump(exclude_none=True)`, and it is load-bearing.** `args`, `env` and
`headers` are `NotRequired` in the SDK's TypedDicts, and this crosses to the CLI
as JSON, where an explicit `null` is not the same as absent. Without the
exclusion an HTTP server would carry `env: null`. Pinned by
`test_mcp_servers_reach_the_sdk_without_null_placeholders`.

**`mcp_servers={}` and not `None` when unset.** `{}` is the SDK's own default;
`None` is not a type the field declares. The empty case is the shipped default,
so it is the one that must not surprise the SDK.

**`strict_mcp_config` defaults to `True` here — the SDK's default is `False`.**
The workspace is mounted from the host and is writable by the agent, so a
`.mcp.json` in it could add servers the caller never sent and cannot see in its
own request. Whether the existing `setting_sources=[]` already suppresses
`.mcp.json` is **not measured**; the flag deliberately does not depend on the
answer.

**`stdio` is allowed, and refusing it would have been theatre.** It grants no
capability the caller lacks: `Bash` is enabled with
`permission_enforcement="none"`, so any prompt can already run any command. What
it changes is **attribution** — a `Bash` command is the agent's decision and
lands in the transcript, while a stdio server starts with the session, before any
prompt, and appears in no turn's events. `Settings.allow_mcp_servers` exists for
operators who need every process start attributable, defaults `True`, and is
published as `Capabilities.allow_mcp_servers` for the same reason
`require_credentials` is — a caller that provisions containers should be able to
ask rather than discover it from a 400.

**A forbidden request is refused, never silently stripped.** Dropping the servers
leaves a request that succeeds while doing something other than what it says: the
agent runs without tools the caller believes it has, and the failure surfaces as
the agent being inexplicably bad at its job. `McpServersNotAllowedError` → 400,
naming what was refused and where to check.

`env` on a stdio server reaches **that subprocess only** — the SDK passes it to
the spawned server, not to the agent's CLI — so it cannot alter the agent's own
model traffic. That is why it needs no allowlist, unlike a hypothetical
passthrough into the CLI's environment (`../../spec/draft/llm-provider-and-auth.md`
S2).

---

# C. What was measured against the SDK

## CP-046 — what the probes are and which SDK they measured

Date: 2026-07-26 · Python 3.13.5 · Windows host
Method: static introspection of the installed package plus reading its source.
**No API calls made** — everything below is verified from the package itself, not
from documentation or inference.

Scripts: `spike/introspect.py`, `spike/introspect2.py`.

Where the published docs and the installed package disagree, **the package wins**
and the discrepancy is called out.

---

## CP-047 — Summary of what changed in the design

| # | Finding | Impact |
|---|---|---|
| F1 | `ResultMessage` field set confirmed, richer than assumed | N1 resolved; response model can be finalized |
| F2 | `options.env` **merges over** `os.environ` — cannot act as a whitelist | Invalidates a documented mitigation in `persistence.md` |
| F3 | `SandboxSettings` exists — OS-level sandbox, absent from the docs page | New Q12; may change Q4/Q6 and the container story |
| F4 | Message union has **6** members, not 5 (`RateLimitEvent`) | Serialization and the run loop must handle it |
| F5 | `ContentBlock` union has **6** members (server tool blocks) | Serialization list was incomplete |
| F6 | `session_id` is **not** uniformly present on messages | `AgentEvent` shape must change |
| F7 | `PreToolUse` deny payload shape confirmed | Part C of `persistence.md` can be written concretely |
| F8 | Setting `skills` silently turns ambient config back on | Q2 has a trap |
| F9 | Hook events: no `SessionStart`/`SessionEnd`, contra the docs | Design must not plan around them |
| F10 | Bundled binary is 265.7 MB | Container image size |

---

## CP-048 — F1 — `ResultMessage` (resolves N1)

The spec listed these as provisional. Confirmed present:

```
subtype              str            required
duration_ms          int            required
duration_api_ms      int            required
is_error             bool           required
num_turns            int            required
session_id           str            required
stop_reason          str | None
total_cost_usd       float | None
usage                dict | None
result               str | None
structured_output    Any
model_usage          dict[str, ModelUsage] | None
permission_denials   list | None
deferred_tool_use    DeferredToolUse | None
errors               list[str] | None
api_error_status     int | None
uuid                 str | None
terminal_reason      str | None
```

Plus three more the first pass of this document did not list, confirmed during
Task 2: `structured_output`, `deferred_tool_use` (carries the paused-run
payload), and `uuid`. Full field count: **18**.

Everything the response model wanted exists. Four fields are worth capturing that
the spec did not anticipate:

- **`permission_denials`** — what the agent tried to do and was refused. Directly
  useful for the audit story, and cheaper than reconstructing it from hooks.
- **`model_usage`** — per-model `ModelUsage`: `inputTokens`, `outputTokens`,
  `cacheReadInputTokens`, `cacheCreationInputTokens`, `webSearchRequests`,
  `costUSD`, `contextWindow`, `maxOutputTokens`, optional `canonicalModel` /
  `provider`. Far better cost attribution than a single `total_cost_usd`.
- **`terminal_reason`** and **`api_error_status`** — distinguish "agent finished"
  from "agent was stopped" from "the API returned an error", which the design's
  `is_error` / transport-error split could not express on its own.
- **`errors`** — list of error strings alongside `is_error`.

**Schema change:** `runs` gains `permission_denials JSONB`, `model_usage JSONB`,
`terminal_reason TEXT`, `stop_reason TEXT`, `api_error_status INT`.

## CP-049 — F2 — `options.env` merges; it is not a whitelist

`_internal/transport/subprocess_cli.py`:

```python
inherited_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
process_env = {
    **inherited_env,                    # the ENTIRE parent environment
    "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
    **self._options.env,                # merged on top — adds/overrides only
    "CLAUDE_AGENT_SDK_VERSION": __version__,
}
```

**The agent subprocess receives the full parent environment.** `options.env` can
add or override keys; it cannot remove them, and there is no option that does.

This **invalidates mitigation 2** in `persistence.md` ("set `ClaudeAgentOptions.env`
explicitly so the subprocess receives a curated environment"). It does not work.
That section is corrected.

The remaining mitigation is the one already recommended: **pop secrets from
`os.environ` after loading them into settings.** That is now the only mechanism,
not one of two. It becomes a hard requirement in `config.py`, not a nice-to-have.

Note `ANTHROPIC_API_KEY` must stay in the environment — this is how the subprocess
authenticates. So the agent can always read the Anthropic key. Budget caps and key
scoping are the controls there, not concealment.

## CP-050 — F3 — Undocumented: `SandboxSettings`

Not mentioned anywhere on the Agent SDK docs pages read on 2026-07-26.
`ClaudeAgentOptions.sandbox` accepts:

```
SandboxSettings:
  enabled                    bool
  autoAllowBashIfSandboxed   bool
  excludedCommands           list[str]
  allowUnsandboxedCommands   bool
  network                    SandboxNetworkConfig
  ignoreViolations           SandboxIgnoreViolations
  enableWeakerNestedSandbox  bool

SandboxNetworkConfig:
  allowedDomains / deniedDomains / allowManagedDomainsOnly
  allowUnixSockets / allowAllUnixSockets / allowLocalBinding
  allowMachLookup / httpProxyPort / socksProxyPort
```

Delivered to the CLI by merging into the `--settings` JSON
(`settings_obj["sandbox"] = self._options.sandbox`).

**Why this matters.** The design's entire security posture assumes the *container*
is the only boundary and that `Bash` is unconstrained within it. If this provides
OS-level filesystem and network confinement, then:

- `Bash` becomes far less alarming, changing Q4 and Q6.
- `autoAllowBashIfSandboxed` suggests a supported "sandboxed, so auto-approve"
  posture — potentially a better default than `dontAsk` + allowlist.
- `network.allowedDomains` could restrict egress at the agent level rather than
  the container level.
- **`enableWeakerNestedSandbox`** implies sandbox-inside-container is anticipated
  — which is exactly our deployment.

**Unverified and important:** whether it works at all on Windows (OS sandboxing is
typically seatbelt on macOS / bubblewrap or seccomp on Linux), and whether it
functions nested inside a container. Needs a live test. Tracked as **Q12**.

## CP-051 — F4 / F5 — The unions are wider than the design assumed

```
Message      = UserMessage | AssistantMessage | SystemMessage
             | ResultMessage | StreamEvent | RateLimitEvent      # 6, spec said 5

ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock
             | ToolResultBlock | ServerToolUseBlock
             | ServerToolResultBlock                             # 6, spec listed 4
```

**Correction (found during Task 2 review, after this section was first written):
the six-member message union undercounts what you actually receive.**
`SystemMessage` has **six subclasses**, each a dataclass in its own right:

```
TaskStartedMessage   TaskProgressMessage   TaskNotificationMessage
TaskUpdatedMessage   MirrorErrorMessage    HookEventMessage
```

Their docstrings state that existing `isinstance(msg, SystemMessage)` checks
continue to match — so they are delivered as system messages, not as a seventh
union member. The practical consequence is concrete: **dispatching on
`type(msg).__name__` silently types all six as unknown.** Dispatch by
`isinstance`, or walk the MRO. Counting union members from the type alias is not
sufficient; check for subclasses too.

`RateLimitEvent` carries `rate_limit_info: RateLimitInfo` with `status`
(`allowed` / `allowed_warning` / `rejected`), `resets_at`, `rate_limit_type`
(`five_hour` / `seven_day` / `seven_day_opus` / `seven_day_sonnet` / `overage`),
`utilization`, and overage fields. Worth surfacing to callers rather than
swallowing — a rejected rate limit otherwise looks like an unexplained stall.

`ServerToolUseBlock.name` is a closed literal: `advisor`, `web_search`,
`web_fetch`, `code_execution`, `bash_code_execution`,
`text_editor_code_execution`, `tool_search_tool_regex`, `tool_search_tool_bm25`.

This vindicates the spec's decision to make `serialization.py` fall back on
unknown types rather than raise — the union is wider than any doc page states and
will keep moving.

## CP-052 — F6 — `session_id` is not uniform

| Message | `session_id` |
|---|---|
| `SystemMessage` | **Absent as a field** — only `subtype` and `data: dict`; the id lives at `data["session_id"]` |
| `AssistantMessage` | Present, `str \| None` |
| `UserMessage` | **Absent entirely** |
| `ResultMessage` | Present, required |
| `StreamEvent` | Present, required |
| `RateLimitEvent` | Present, required |

The spec's `AgentEvent` put `session_id` on every event. That cannot be populated
from `UserMessage`.

**Correction:** track `session_id` at the *run* level — capture it from the init
`SystemMessage` (`data["session_id"]`) and confirm from `ResultMessage` — and drop
it from the per-event model. It is a property of the run, not of each message.

## CP-053 — F7 — Hook allow/deny shape (resolves the Part C uncertainty)

```python
# SyncHookJSONOutput
{
  "continue_": bool,              # trailing underscore — keyword avoidance
  "suppressOutput": bool,
  "stopReason": str,
  "decision": "block",
  "systemMessage": str,
  "reason": str,
  "hookSpecificOutput": { ... },
}

# PreToolUseHookSpecificOutput
{
  "hookEventName": "PreToolUse",                          # required
  "permissionDecision": "allow" | "deny" | "ask" | "defer",
  "permissionDecisionReason": str,
  "updatedInput": dict,                                   # rewrite tool args
  "additionalContext": str,
}
```

Note the **mixed casing**: hook *inputs* are snake_case (`tool_name`,
`tool_input`, `tool_use_id`), hook *outputs* are camelCase (`hookEventName`,
`permissionDecision`). Python keywords get a trailing underscore (`continue_`,
`async_`) and are converted by `_convert_hook_output_for_cli`.

`permissionDecision` supports four values, not two — `ask` and `defer` exist
beyond `allow`/`deny`.

`PostToolUseHookSpecificOutput` can rewrite results via `updatedToolOutput` /
`updatedMCPToolOutput`, which is more power than the design assumed hooks had.

**Conclusion for Part C:** both mechanisms are viable. `can_use_tool` has the
cleaner typed interface (`PermissionResultAllow` / `PermissionResultDeny`, the
latter with an `interrupt` flag); hooks offer pattern matching via
`HookMatcher.matcher` plus a `timeout`, and can rewrite inputs and outputs. Use
`can_use_tool` for policy, hooks for audit — as the spec proposed, now for
evidenced reasons rather than assumed ones.

## CP-054 — F8 — Setting `skills` re-enables ambient config

From `_compute_skills_config`: when `options.skills` is set and
`setting_sources` is `None`, the SDK **defaults `setting_sources` to
`["user", "project"]`** so the CLI can discover installed skills.

This is a trap for Q2. Choosing "no ambient config" is not achieved by leaving
`setting_sources` unset — setting `skills` would silently load your `~/.claude`
and the project's `.claude`. **`setting_sources` must be set explicitly**, which
the design already does; this makes it mandatory rather than tidy.

Unverified: whether `setting_sources=[]` (which emits `--setting-sources=` with an
empty value) is honoured by the CLI as "none". Needs a live check.

## CP-055 — F9 — Hook events, actual list

`ClaudeAgentOptions.hooks` accepts exactly:

```
PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit,
Stop, SubagentStop, PreCompact, Notification, SubagentStart, PermissionRequest
```

**`SessionStart` and `SessionEnd` are not accepted**, despite the overview page
listing `SessionStart` and `SessionEnd` among available hooks. A
`SessionStartHookSpecificOutput` type exists but no matching event key does.
Do not design around session lifecycle hooks.

## CP-056 — F10 — Bundled binary

`claude_agent_sdk/_bundled/claude.exe` — **265.7 MB**. Wheel download was 81.6 MB.

Implications: the container image carries a quarter-gigabyte binary; multi-stage
builds will not help since it is a runtime dependency. It is a native executable,
so the glibc-vs-musl concern in `deployment.md` is real and must be tested rather
than assumed. `ClaudeAgentOptions.cli_path` exists as an override if the bundled
binary proves unusable.

---

## CP-057 — Other confirmations (no design change)

- **Permission modes:** `default`, `acceptEdits`, `plan`, `bypassPermissions`,
  `dontAsk`, `auto`. `dontAsk` confirmed.
- **Effort:** `low`, `medium`, `high`, `xhigh`, `max`.
- **Setting sources:** `user`, `project`, `local`.
- **`SdkBeta`:** only `context-1m-2025-08-07`.
- **`add_dirs`** becomes repeated `--add-dir <path>` CLI flags — a CLI-level
  concept, not a Python-side filter.
- **`TaskBudget`** is `{total: int}` only.
- **MCP configs:** `sdk` (in-process), `stdio`, `http`, `sse` — all four available,
  confirming the in-process option in `persistence.md` Part B.
- **`ClaudeSDKClient`** has more surface than the docs listed, notably
  **`get_context_usage()`** (→ `ContextUsageResponse`), plus `rewind_files`,
  `stop_task`, `toggle_mcp_server`, `reconnect_mcp_server`, `set_model`,
  `set_permission_mode`. `get_context_usage` is a good addition to
  `GET /v1/sessions/{id}`.
- **`ClaudeSDKClient.query(prompt, session_id="default")`** — that `session_id`
  parameter is a *stream* identifier within the connection, not the SDK session id.
  Easy to misread.
- **`tool()` annotations** parameter is typed `mcp.types.ToolAnnotations`, not the
  SDK's own class; the docs example implies otherwise. `McpToolAnnotations` is
  exported.
- **Escape hatches:** `extra_args` (arbitrary CLI flags), `cli_path`, `settings`,
  `plugins`, `session_store` (+ `InMemorySessionStore`), `enable_file_checkpointing`.
- **Transitive deps** already include `pydantic`, `pydantic-settings`, `uvicorn`,
  `starlette`, `sse-starlette`, `httpx`, `mcp`. FastAPI is the main addition.

---

## CP-058 — Live results (L1–L4)

Run against the real API on 2026-07-26 via `spike/live.py`. Total spend ≈ $0.31.

| ID | Result |
|---|---|
| L1 | ✅ PASS — bundled binary ran; trivial `query()` completed in 5.0 s |
| L2 | ✅ Full message sequence captured; three structural surprises (L2a–L2c) |
| L3 | ❌ **`add_dirs` is not an access boundary** — the central finding |
| L4 | ✅ PASS — `setting_sources=[]` is honoured as "load nothing" |

## CP-059 — L3 — `add_dirs` does not confine anything (design-changing)

Setup: `cwd` = an empty scratch dir; a file containing `OUTSIDE-TOKEN-9931`
placed in a sibling directory *outside* it; `permission_mode="dontAsk"`,
`allowed_tools=["Read", "Bash"]`. The agent was asked to read that outside file
both with `Read` and with `cat` via `Bash`.

| Configuration | `Read` outside cwd | `Bash cat` outside cwd | `permission_denials` |
|---|---|---|---|
| `add_dirs=[]` | **succeeded** | **succeeded** | `[]` |
| `add_dirs=[outside]` | succeeded | succeeded | `[]` |

The agent's own words on the `add_dirs=[]` run: *"No permission prompt or sandbox
denial occurred in either case, even though the path is outside the current
working directory."*

**Conclusions, all correcting the spec:**

1. **`cwd` is not a boundary.** It sets the starting directory, nothing more.
2. **`add_dirs` is not required for access, and does not gate it.** Reading
   outside `cwd` worked identically with and without it. The spec called
   `add_dirs` "load-bearing" for the read-only reference mount — **it is not**.
   Treat it as discovery/registration, not enforcement.
3. **`allowed_tools=["Read"]` approves *every* use of `Read`, at any path.** The
   allowlist is per-*tool*, not per-*path*. `dontAsk` governs which tools may run,
   never which files they may touch.
4. **The only real boundary is the mount** (and the container). Q8's `:ro` flag is
   doing all of the work; the `workspace_subdir` validation in the spec provides
   approximately nothing against a determined agent and should be described as
   input hygiene rather than confinement.
5. **Running this service outside a container is unsafe.** With `Bash` enabled the
   agent can read any file the service process can read — the whole host
   filesystem. `deployment.md`'s container is not a deployment convenience, it is
   the security model.

**Follow-up (new, unresolved):** Claude Code supports *scoped* permission rules
such as `Bash(git status:*)` and `Read(./src/**)`. Whether
`ClaudeAgentOptions.allowed_tools` accepts that scoped syntax — and enforces it —
was not tested and would materially change the picture. Tracked as **Q13**.

## CP-060 — L4 — `setting_sources=[]` is honoured

A `CLAUDE.md` in `cwd` instructed the model to append `ZEBRA-7788` to every reply.

| Configuration | Marker in reply |
|---|---|
| `setting_sources=[]` | **absent** — reply was exactly `ready` |
| `setting_sources=["project"]` | **present** — `ready ZEBRA-7788` |

Q2's default is safe. Combined with F8 (setting `skills` silently re-enables
`["user", "project"]`), the rule stands: **always set `setting_sources`
explicitly.**

Corroborating evidence from the L1 init payload: with `setting_sources=[]` the
reported `agents` and `skills` contained only Claude Code built-ins — none of the
host user's plugin-provided agents or skills appeared.

## CP-061 — L2 — message-structure surprises

**L2a — one API message can arrive as several `AssistantMessage` objects.** The
text block and the tool-use block arrived as two separate `AssistantMessage`s
sharing `message_id: msg_011CdQD7mLLUsuZMkKicuebM`. Anything that assumes
one `AssistantMessage` per assistant turn will mis-group the transcript. Group by
`message_id`, not by arrival.

**L2b — the observed sequence** for a one-tool run:

```
SystemMessage(init)      → session_id, tools, model, permissionMode, cwd
AssistantMessage         → TextBlock  "I'll read the file."   ┐ same message_id
AssistantMessage         → ToolUseBlock Read                  ┘
UserMessage              → ToolResultBlock (+ tool_use_result with parsed file)
AssistantMessage         → TextBlock  "BANANA"
ResultMessage            → subtype=success, terminal_reason=completed
```

`UserMessage.tool_use_result` carries a **parsed, structured** version of the tool
result (for `Read`: `filePath`, `content`, `numLines`, `totalLines`) alongside the
raw `ToolResultBlock.content` string. Richer than the docs suggest and worth
persisting.

**L2c — the init payload is a capabilities goldmine.** `SystemMessage.data`
carries `session_id`, `cwd`, the full `tools` list, `model`, `permissionMode`,
`apiKeySource`, `claude_code_version`, `agents`, `skills`, `slash_commands`,
`mcp_servers`, and `memory_paths`. `GET /v1/capabilities` should report this from
a real init rather than from hard-coded constants.

## CP-062 — Cost — the finding with the widest blast radius

| Run | Cost | Notes |
|---|---|---|
| L1 (cold cache, one file read) | **$0.157** | 22,980 cache-*creation* tokens |
| L3-A (warm) | $0.051 | 43,310 cache-*read* tokens |
| L3-B (warm) | $0.034 | 46,285 cache-read |
| L4-A (warm, no tools) | $0.027 | trivial prompt |

**The default model is `claude-opus-5[1m]`** — Opus 5 with the 1M context window.
Nobody chose that; it is what the CLI picks when `model` is unset.

**A trivial run costs ~$0.16 cold.** The cost is almost entirely the ~23k tokens of
system prompt plus tool definitions written to cache on every cold start — it is a
*floor*, essentially independent of how small the task is. Warm runs inside the
cache TTL drop to $0.03–0.05.

Consequences:

- **Q5 (`max_budget_usd = 1.0`) allows roughly six cold runs.** That is far tighter
  than intended. Either raise it substantially or pin a cheaper default model.
- **Q7 (default model) is now a cost decision, not a reproducibility one.** Pinning
  `claude-sonnet-5` or `claude-haiku-4-5` would cut the per-run floor several-fold.
- **Prompt caching does most of the work.** Keeping the options prefix byte-stable
  across requests is worth real money; per-request option variation that changes
  the prefix silently multiplies cost.

**Two models appear in every run.** `model_usage` consistently showed
`claude-opus-5[1m]` *and* `claude-haiku-4-5` (~500 input tokens, ~$0.0006) — the
CLI uses Haiku internally for auxiliary work. This confirms `model_usage` must be
stored as a map, not a scalar, and that "which model did this run use?" has no
single answer.

## CP-063 — Tool surface is much wider than documented

The L1 init reported **31** built-in tools:

```
Task, Bash, CronCreate, CronDelete, CronList, DesignSync, Edit, EnterWorktree,
ExitWorktree, Glob, Grep, Monitor, NotebookEdit, PowerShell, PushNotification,
Read, ReportFindings, ScheduleWakeup, SendMessage, Skill, TaskCreate, TaskGet,
TaskList, TaskOutput, TaskStop, TaskUpdate, ToolSearch, WebFetch, WebSearch,
Workflow, Write
```

The docs page listed ten. Note `PowerShell` (platform-specific), plus scheduling,
worktree, and task-orchestration tools the design never considered.

**`allowed_tools` does not hide tools from the model.** All 31 were advertised in
the init payload even though `allowed_tools` named three. The allowlist governs
*permission*, not *visibility* — so the model can and will attempt a disallowed
tool, burn a turn, and be denied. `disallowed_tools` is the field that actually
removes capability, and `/v1/capabilities` should report the real list rather than
the spec's assumed ten.

---

## CP-064 — L7 — scoped permission rules are NOT enforced (negative result)

Setup: a real git repo as `cwd`, `permission_mode="dontAsk"`, and
`allowed_tools=["Bash(git status:*)"]` — nothing else allowed. The agent was asked
to run `git status --short` and then `git log --oneline`.

| Command | Expected under scoping | Actual |
|---|---|---|
| `git status --short` | allowed | ran |
| `git log --oneline` | **denied** | **ran** |

`permission_denials: []`. The agent's summary: *"Both commands ran successfully —
neither was denied."*

**Conclusion: `allowed_tools` does not honour scoped rules.** The entry
`Bash(git status:*)` behaved as a grant of the whole `Bash` tool. Combined with
L3, the picture is now complete and consistent:

> `allowed_tools` is a **coarse capability switch**. It cannot express *which
> paths* a tool may touch (L3) or *which commands* it may run (L7).

> **⚠️ Superseded (2026-07-26).** The claim and the code block immediately below
> are wrong and must not be copied. Five live probes (`spike/probe_permissions.py`,
> written up in "Permission enforcement — measured, not guessed" further down
> this file) found `can_use_tool` never fires under any configuration this
> service actually uses — not with a whole-tool `allowed_tools` grant, not
> without one, and not alongside a hook. The `PreToolUse` hook is the mechanism
> verified to actually run and actually block a write; it is what
> `permission_enforcement="hook"` wires up in `options.py`/`policy.py`. Read
> that section, not this one, for the current design.

**This promotes `can_use_tool` from optional to primary.** It is the only
mechanism that receives the actual tool input — the `Bash` command string, the
`Read` file path — and can allow or deny per invocation. Everything the spec
hoped to get declaratively from `allowed_tools` must be written there instead:

```python
# SUPERSEDED (2026-07-26) -- do not copy. Five live probes found can_use_tool
# never fires under any configuration this service actually uses; see
# "Permission enforcement -- measured, not guessed" below. The PreToolUse
# hook (policy.py's make_permission_hook) is the mechanism that works.
async def policy(tool_name, input_data, context):
    if tool_name == "Bash" and not ALLOWED_CMD.match(input_data.get("command", "")):
        return PermissionResultDeny(message="command not permitted")
    if tool_name in ("Write", "Edit"):
        path = Path(input_data.get("file_path", "")).resolve()
        if not path.is_relative_to(WORKSPACE):
            return PermissionResultDeny(message="writes confined to /workspace")
    return PermissionResultAllow()
```

Caveat on interpretation: it is possible the scoped syntax is honoured under a
different `permission_mode` and that `dontAsk` short-circuits it. Not pursued —
`can_use_tool` is available, typed, testable, and does not depend on undocumented
CLI matching semantics.

## CP-065 — Limit-stop markers — measured, not guessed (added during Task 7)

`ResultMessage.terminal_reason`'s docstring lists `completed`, `max_turns`,
`aborted_streaming`, `aborted_tools`. `subtype` is a bare `str` whose values come
from the compiled CLI, so they cannot be read off the Python package at all. None
of the L1–L7 runs above ever hit a limit, so the project had no evidence for what
a turn or budget stop actually looks like.

Two probes (`spike/probe_limits.py`, ~$0.16) settled it:

| Limit hit | `subtype` | `terminal_reason` |
|---|---|---|
| `max_turns=1` | `error_max_turns` | `max_turns` |
| `max_budget_usd=0.01` | `error_max_budget_usd` | `budget_exhausted` |

**Why this mattered.** The plan had guessed the budget markers as `max_budget`,
`error_max_budget`, and `budget_exceeded`. All three are wrong, and none appears
anywhere in the installed SDK. Had they shipped, a budget-exhausted run would have
matched no marker and been reported as `limit_hit: null` — indistinguishable from
a normal completion, defeating the Q5 requirement that a limit stop never look
like a crash or a clean finish. The turn markers were guessed correctly, which is
precisely what makes this class of error dangerous: half the table looked fine.

`budget_exhausted` rests on a single observation and is documented nowhere in the
SDK. If a future CLI renames it, budget stops silently regress to `limit_hit:
null`. A periodic re-run of the probe is the only defence.

## CP-066 — Permission enforcement — measured, not guessed (added during Task 11 follow-up)

Task 11's live verification found that a real out-of-workspace `Write` succeeded
under this service's shipped defaults, with `permission_denials: []` — `policy.py`'s
`can_use_tool` callback was never consulted. The SDK's own `CanUseToolShadowedWarning`
pointed at the cause (a whole-tool `allowed_tools` entry auto-approves before the
callback runs), but the plan had already been burned twice by inferring SDK
behaviour instead of measuring it (F2, and the limit markers below). Real API
calls (`spike/probe_permissions.py`) settled the full matrix instead: five
cases (~$0.34) in the initial round, plus a sixth added during code review
(Finding 4) to check an inference the first round left untested.

| Case | `allowed_tools` | `permission_mode` | `can_use_tool` | hook | Fired? | Write/Edit succeeded | `permission_denials` | Cost |
|---|---|---|---|---|---|---|---|---|
| 1 | `["Write"]` (whole) | `dontAsk` | set | — | **NO** (shadow warning) | **YES** | `[]` | $0.1130 |
| 2 | `[]` (not listed) | `default` | set | — | **NO** | NO | one `Write` denial | $0.0336 |
| 3 | `[]` (not listed) | `dontAsk` | set | — | **NO** | NO | two denials (`PowerShell`, `Write`) | $0.0479 |
| 4 | `["Write"]` (whole) | `dontAsk` | — | set, matcher `"Write"` (deny) | **YES** | NO | one `Write` denial | $0.1099 |
| 5 | `["Write"]` (whole) | `dontAsk` | set (deny) | set, matcher `"Write"` (deny) | hook YES / `can_use_tool` NO | NO | one `Write` denial | $0.0322 |
| 6 | `["Read","Write","Edit"]` | `dontAsk` | — | set, **shipped matcher `"Edit\|NotebookEdit\|Write"`** (deny), tool exercised is **`Edit`** | **YES** | NO | one `Edit` denial | $0.1184 + $0.0390† |

†Case 6 ran twice. The first attempt used `allowed_tools=["Write","Edit"]`
(no `Read`) and measured nothing: the agent tried `Read` first to see the
file's content, was denied outright (same CLI-level pre-empt as cases 2/3,
since `Read` wasn't allow-listed), and gave up without ever attempting `Edit`
— `fired: False` there is a measurement failure, not a negative result, and is
excluded from the conclusion below. The second attempt added `Read` to
`allowed_tools` and stated the file's current content in the prompt so the
agent had no reason to read first; it went straight to `Edit`, which the hook
caught and blocked.

Total spend: **≈$0.494** across cases 1–5 ($0.3366) plus case 6's two attempts
($0.1184 + $0.0390 = $0.1574).

**`can_use_tool` fired zero times, across every configuration this service would
realistically use:**

- **Case 1** reproduces the Task 11 bug directly: with `Write` whole-tool-allowed,
  the callback never runs (confirmed by the captured `CanUseToolShadowedWarning`)
  and the write succeeds outside the workspace.
- **Cases 2 and 3** are the more surprising result. With `Write` *not* allow-listed
  at all, the natural guess was that `can_use_tool` would be consulted as the
  "should I allow this?" delegate — that is what the mode's own docstring implies
  (`"default": CLI prompts for dangerous tools`). It was not. The CLI denied the
  tool call itself, before the callback ever ran, under **both** `default` and
  `dontAsk` — the callback fired in neither. Case 3's second denied entry
  (`PowerShell`, attempting a `Set-Content` redirect) shows this is not
  `Write`-specific: with an empty `allowed_tools`, no tool call reaches the
  callback at all.
- **Case 5** confirms the shadow in case 1 is not affected by also registering a
  hook: `can_use_tool` still does not fire when a hook is present alongside it.

**The `PreToolUse` hook is the only mechanism observed to actually enforce a
decision.** Case 4 shows it fires *despite* the whole-tool `allowed_tools` grant
that shadows `can_use_tool` — the SDK's own shadowing-warning text ("use a
PreToolUse hook" to gate every call) checks out. Cases 4 and 5 both show the
hook's `deny` decision genuinely prevents the write (file never created) and is
correctly reflected in `ResultMessage.permission_denials`.

**Case 6 (review round 1, Finding 4) — does the shipped matcher actually match
`Edit`, or only the literal `"Write"` every other case exercised?** Cases 4 and
5 only ever registered `HookMatcher(matcher="Write", ...)` — a single literal
tool name. `options.py`'s real `_WRITE_TOOL_MATCHER` is
`"Edit|NotebookEdit|Write"`, built from `policy.WRITE_TOOLS` via
`"|".join(sorted(...))`, and whether the SDK's pipe-alternation syntax actually
matches a tool name other than the first one listed had never been observed —
only inferred from the SDK's own docstring example
(`"Write|MultiEdit|Edit"`). Importing `_WRITE_TOOL_MATCHER` directly from
`options.py` (rather than retyping it) and asking the agent to `Edit` — not
`Write` — a file outside the workspace confirmed it: the hook fired
(`tool_name: "Edit"`), the edit was blocked (file content verified unchanged
after the run), and the denial was recorded correctly. **The shipped
three-way matcher does gate `Edit`, not just `Write`.**

**Conclusion for the design.** `can_use_tool`, exactly as this service would need
to use it (a whole-tool `allowed_tools` grant plus a callback deciding per-path),
cannot be relied on for enforcement — it is dead code under every tested
configuration. `policy.py`'s decision logic is correct in isolation (`test_policy.py`
exercises it directly, as a plain function call), but the SDK never reaches it in
a live run shaped like this service's. The `PreToolUse` hook is the verified,
working alternative and is what `permission_enforcement="hook"` wires up (see
`config.py`/`options.py`), and it is now confirmed live to cover all three tools
its matcher names (`Write` directly in cases 4/5, `Edit` via alternation in case
6; `NotebookEdit` remains untested — see the open question below).
`permission_enforcement="can_use_tool"` was **not** added as a selectable mode —
offering a control measured to never run would repeat the exact mistake this
probe was written to catch.

**Open, untested questions** (not pursued — outside this probe's budget and
matrix):

- Whether a genuinely non-whole-tool `allowed_tools` entry, or
  `permission_mode="auto"`/`"acceptEdits"`/`"plan"`, would let `can_use_tool`
  actually fire. L7 already found scoped `Bash(...)` syntax is not enforced as
  a restriction, which makes a working non-whole-tool entry unlikely, but this
  was not directly retested here. If the SDK's callback interface is ever
  revisited, probe this first rather than assuming either way.
- `NotebookEdit` specifically was never exercised live (case 6 tested `Edit`,
  not `NotebookEdit`). The alternation mechanism is now confirmed to work for
  a second name beyond the first-listed one, which is the load-bearing part,
  but `NotebookEdit` itself remains an inference from the same matcher string.

## CP-067 — `ClaudeSDKClient` — measured before Plan 2 was written

`spike/probe_sessions.py`, five live cases, ~$0.28. Run **before** planning the
multi-turn service, because Plan 1 was burned three times by inferring SDK
behaviour instead of measuring it. A sixth case (S6) was added in Plan 2's Task 2
fix round 1, after code review flagged that the cost-accumulation logic was an
unverified assumption; ~$0.31 for the three additional short turns it ran.

| # | Question | Measured answer |
|---|---|---|
| S1 | Does `receive_response()` end cleanly at one turn? Is context retained? | Yes to both. Ends on `ResultMessage`; turn 2 recalled a fact from turn 1 without re-reading the file |
| S2 | What does `interrupt()` do mid-turn? | Returns in ~0 s. Drain then yields `UserMessage("[Request interrupted by user]")` then `ResultMessage(subtype="error_during_execution", is_error=True, terminal_reason="aborted_streaming")` |
| S3 | Second `query()` before the first turn is drained? | **Does not raise.** It queues silently; the first `receive_response()` returned only the first turn |
| S4 | `get_context_usage()`, `set_model()`, `set_permission_mode()` mid-session? | All work. Context usage returns a per-category token breakdown |
| S5 | Does `disconnect()` kill the subprocess? | **Yes** — 1 child spawned, 0 leaked one second after `disconnect()` |
| S6 | Is `ResultMessage.total_cost_usd` per-turn or cumulative for the connection? | **Cumulative.** Three short turns on one client: `0.0926565`, `0.100344` (Δ`0.0076875`), `0.10803255` (Δ`0.00768855`) — monotonically non-decreasing, and the per-turn deltas after the first turn are small and consistent, exactly what a cheap cache-warm follow-up costs on top of a running total. Summing these across turns would compound the double-count with every additional turn. |

**Five consequences for the design:**

1. **An interrupted turn looks exactly like a failed one.** `is_error=True` with
   `subtype="error_during_execution"` — the same shape a genuine failure produces.
   `terminal_reason="aborted_streaming"` is the only distinguishing signal, and it
   is not self-evidently an interrupt. The service must track that *it* sent the
   interrupt and label the response accordingly, or every deliberate stop will be
   reported to the caller as a crash. This is the limit-marker problem again, found
   before the code was written rather than after.

2. **A per-session lock is required, and not for the reason assumed.** The danger
   is not that a concurrent `query()` errors — it doesn't. It queues *silently*,
   and each `receive_response()` drains exactly one turn, so two concurrent HTTP
   requests would each receive a turn with no guarantee it is their own. Silent
   misattribution is worse than a 409; the lock must be ours.

3. **`SystemMessage(subtype="init")` arrives on EVERY turn**, not once per
   connection. Any "capture the session id from the first init" logic carried over
   from the one-shot runner is wrong here. Also newly observed:
   `SystemMessage(subtype="thinking_tokens")`.

4. **`disconnect()` is trustworthy** — unlike abandoning a `query()` generator,
   which leaks until generational GC. The TTL reaper can rely on it, and the
   registry's shutdown path does not need the `BackgroundTask` gymnastics the SSE
   endpoint required.

5. **`total_cost_usd` is cumulative for the connection, not per-turn (S6).** A
   session must therefore *assign* the latest `ResultMessage.total_cost_usd` as
   its running total, not sum successive turns' values — summing would compound
   an already-wrong number with every turn. This was caught by code review before
   any caller shipped: `AgentSession` originally summed, on the untested
   assumption (carried over uncritically from one-shot `Run`, where there is only
   ever one `ResultMessage` so summing and assigning are equivalent) that each
   turn's cost was independent.

`get_context_usage()` returns `{"categories": [{"name", "tokens", "color", ...}]}`
with entries such as *System tools*, *System tools (deferred)*, *Skills*,
*Messages*, *Autocompact buffer*, *Free space* — directly usable as the payload for
a session-detail endpoint. `get_server_info()` returns keys including `account`,
`agents`, `commands`, `models`, `output_style`, `pid`.

> **⚠️ S2's numbers are degraded on Windows.** `probe_sessions.py` passes
> `allowed_tools=["Bash", ...]`, and M1 below established that **`Bash` does not
> authorise the shell on Windows — the CLI offers `PowerShell` instead**. So S2's
> turn was already collapsing on a denied shell call before the interrupt landed.
> The *shape* S2 reports (`error_during_execution` / `aborted_streaming`) is
> unaffected and is corroborated by M1; the turn length and cost figures are not
> measuring what they claim. Re-run S2 with `PowerShell` in `allowed_tools` before
> trusting them.

## CP-068 — M1 — mid-turn control requests, measured live

`spike/probe_midturn_control.py`, three runs (P1 ×1, P2 ×2), **$0.2749**. Run to
settle one question Plan 2 had only inferred: **is `PATCH /v1/sessions/{sid}` safe
mid-turn, and when does it take effect?** Driven through `ClaudeSDKClient`
directly rather than over HTTP — the open question is the SDK's behaviour, not the
endpoint's, and a background drain task makes the interleaving deterministic.

**Method.** `receive_response()` runs in an `asyncio.Task` that timestamps every
message. The main coroutine blocks on a gate that releases only once **≥ 3
`AssistantMessage`s have arrived AND the drain task has not finished** — a control
request that lands after the turn already ended proves nothing, so this gate is
the whole point. Both runs report `fired_mid_turn=True`, and in both the drain went
on producing for another 5–13 s afterwards and terminated on its own
`ResultMessage`.

| # | Question | Measured answer |
|---|---|---|
| M1a | Does a mid-turn `set_model` / `set_permission_mode` corrupt or disturb the in-flight turn? | **No.** Control calls returned in **4 ms / 5 ms / 161 ms**, no exception in either coroutine, no stall, no reordering, no lost or duplicated message. Every turn ended on a clean `ResultMessage` (`subtype='success'`, `is_error=False`, `terminal_reason='completed'`). **No lock is needed for safety** |
| M1b | When does a model change take effect — current turn or next? | **The CURRENT turn, at the very next inference.** Inside one drain, `AssistantMessage.model` went `claude-haiku-4-5-20251001` → `claude-sonnet-5`, and that one turn's `model_usage` billed **both** models. It persists to later turns too |
| M1c | Same for `set_permission_mode`? | **Same — current turn, immediately** (measured twice). `acceptEdits` → `plan` mid-turn: the pre-switch `Write` landed on disk, the next `Write` **in the same turn** was denied, and the denial appeared structurally in `ResultMessage.permission_denials` |
| M1d | Does a control request interleave safely with the message stream? | **Yes** — confirming S3's inference, with one correction (see below) |

**M1b raw evidence** (P1, one single `receive_response()` drain, one `ResultMessage`):

```
  t+  7.84s  AssistantMessage[model=claude-haiku-4-5-20251001](ThinkingBlock)
  t+  7.85s  AssistantMessage[model=claude-haiku-4-5-20251001](tool_use(PowerShell ...))
             *** set_model("claude-sonnet-5") fired t+7.90s, returned t+8.06s (161ms) ***
  t+  8.06s  UserMessage(...)
  t+ 11.52s  AssistantMessage[model=claude-sonnet-5](ThinkingBlock)
  t+ 12.83s  ResultMessage(subtype='success' is_error=False num_turns=2
             stop_reason='end_turn' terminal_reason='completed')

  turn1 model_usage[claude-haiku-4-5-20251001] = in=551  out=14   cost=$0.000621
  turn1 model_usage[claude-haiku-4-5]          = in=10   out=735  cost=$0.02704375
  turn1 model_usage[claude-sonnet-5]           = in=2    out=289  cost=$0.09827475
```

The next stream message arrived at `t+8.06s` — the same instant the control call
returned. No gap.

**Consequences for the design:**

1. **A mid-turn `PATCH` does not "apply to the next turn". It re-prices the
   remainder of the turn already in flight.** A client that PATCHes haiku → sonnet
   during a long turn is billed at sonnet rates for the rest of that turn, and
   `session.total_cost_usd` (which assigns the connection-cumulative
   `total_cost_usd`, S6) moves by more than the caller expects. **The PATCH route's
   "mid-session" prose was materially misleading and has been corrected** to
   "immediately, including on a turn already in flight".
2. **`ResultMessage.model_usage` keys are not stable identifiers.** P1's single
   turn reported **three keys for two models**: `claude-haiku-4-5-20251001`
   (canonical), `claude-haiku-4-5` (alias) and `claude-sonnet-5` (alias). Anything
   that groups or sums by `model_usage` key will **double-count** across an
   alias/canonical pair. `AssistantMessage.model` is likewise sometimes the dated
   canonical id and sometimes the alias — so "did the model change take effect?"
   cannot be an equality check against the requested string.
3. **A control request is not entirely invisible to the message stream.** This
   corrects S3's model. `set_permission_mode` caused a
   `SystemMessage(subtype='status')` to appear in the drain 10 ms later, in **both**
   P2 runs. It is not the control *response* frame — it is a CLI-emitted status
   notification travelling the normal message path, and it is benign (a
   `SystemMessage` the service already tolerates). But *"control frames never enter
   the stream"* is not the same claim as *"a control request never adds anything to
   the stream"*. `set_model` produced no such message, so the behaviour differs per
   subtype.
4. **Windows: `allowed_tools=["Bash"]` does not authorise the shell.** The CLI
   offers a **`PowerShell`** tool on Windows, so under `permission_mode="dontAsk"`
   the agent's shell call was denied (*"Permission to use PowerShell has been
   denied"*) and P1's intended slow-count turn collapsed after 2 inferences. **This
   also degrades S2 in `spike/probe_sessions.py`**, which passes the same
   `allowed_tools=["Bash", ...]` and was therefore measuring an already-degraded
   turn. See the warning above the S1–S6 table.
5. **`allowed_tools` is not an exclusive whitelist** (consistent with L3/L7). With
   `allowed_tools=["Bash","PowerShell","Read","Glob","Write"]` the agent
   successfully invoked `ToolSearch` and `ExitWorktree`.
6. **A mid-turn permission *tightening* makes the agent thrash.** Blocked mid-turn,
   the agent did not simply stop: it hunted for an escape, calling `ToolSearch` for
   `ExitPlanMode` repeatedly and (P2 run 1) calling `ExitWorktree`, burning ~7 extra
   inferences and roughly **$0.05** before giving up. Safe, but wasteful and
   user-visible — more disruptive in practice than the "no error" result suggests.
7. **A denied tool call is not a turn failure.** Every turn still ended
   `subtype='success'`, `is_error=False`, `terminal_reason='completed'`.
8. **S6 re-confirmed.** P1's turn 1 reported `$0.12594` and turn 2 `$0.14674` on the
   same connection — cumulative, not per-turn.

**Spend** (last `ResultMessage.total_cost_usd` per connection, summed across
connections — *not* summed per turn, per S6):

| Run | Connection total |
|---|---|
| P1 (`set_model` mid-turn) | $0.14674 |
| P2 run 1 (`set_permission_mode` mid-turn) | $0.09746 |
| P2 run 2 (replication + full transcript) | $0.03073 |
| **Total** | **$0.27493** |

Budget was $1.00. No run was retried after a failure; P2 run 2 was a deliberate
replication.

**What remains UNVERIFIED — do not extrapolate past this list:**

- **Not tested over HTTP.** Everything is `ClaudeSDKClient` directly. The service's
  `PATCH` handler adds `AgentSession` state mutation and its own bookkeeping on
  top; whether `AgentSession` records the new model coherently while a turn is
  draining, and whether `session.total_cost_usd` accounting stays correct across a
  mid-turn model change, was not measured.
- **Not tested: a `PATCH` landing inside the *first* inference**, before any
  `AssistantMessage` exists. The gate deliberately waits for 3, so the earliest
  window is unmeasured.
- **Not tested: concurrent `PATCH`es**, or a `PATCH` racing an `interrupt()` or a
  `disconnect()`.
- **Not tested: `set_model` to an invalid or unavailable model id mid-turn.** Only a
  valid haiku → sonnet switch was exercised; failure handling mid-drain is unknown.
- **Not tested: *loosening* permissions mid-turn** (e.g. `plan` → `acceptEdits`).
  Only tightening was measured. Symmetry is plausible but unproven.
- **`set_model` is n=1** — one direction, one run. `set_permission_mode` is n=2.
- **Windows only.** The `PowerShell`-vs-`Bash` finding in particular is
  platform-specific, and the timings come from one machine.
- P1's mid-turn window was ~5 s rather than the ~20 s designed, because of the
  PowerShell denial (consequence 4). The control request was still verifiably
  mid-drain and the switch is visible inside a single turn, so the conclusion holds
  — but only **one** post-switch inference was observed in P1, versus several in P2.

## CP-069 — Windows: the SDK needs the Proactor event loop

Setting `WindowsSelectorEventLoopPolicy` makes every run fail at startup:

```
NotImplementedError            (asyncio/base_events.py, _make_subprocess_transport)
  → CLIConnectionError: Failed to start Claude Code:
```

The selector loop does not implement subprocess transports on Windows, and the SDK
spawns the CLI as a subprocess. Use the default Proactor loop. Relevant to local
development on Windows and to any ASGI server configured with a non-default loop;
not an issue in the Linux container.

---

## CP-070 — B1 — an interrupted turn is billed but not accounted, and `max_budget_usd` cannot see it

**This is the most consequential live finding in this document, and the only one
with a safety consequence.** `spike/`-style probe recorded in
`conversations/.superpowers/sdd/interrupt-cost/`, three parts, **$0.189 reported by the SDK
against ≈$0.41 actually spent**. That ~2× gap *is* the finding.

Run to settle a question Plan 4's live end-to-end run raised: an interrupted turn
reported `turn_cost_usd: 0.0` despite obviously having done work.

| # | Question | Measured answer |
|---|---|---|
| B1a | Did the interrupted turn cost money? | **Yes, and the SDK attributes none of it.** Real inference ran — 2 `AssistantMessage`s, ~8.0 s, `terminal_reason='aborted_streaming'` — while `usage` came back **all-zero with `iterations: []`**, `model_usage` carried **no key at all** for the model, and the connection's cumulative `total_cost_usd` did not move. There are no tokens to surface: the service cannot report what it is never told |
| B1b | Is the cost deferred to a later turn, or lost? | **Lost.** Every subsequent turn's delta priced out to exactly its own usage at published rates, to seven decimal places (0.0096021, 0.010557750000000001, 0.0092367 — independently re-derived in review), with nothing folded in. Six completed turns across two connections, no catch-up anywhere |
| B1c | **Is `max_budget_usd` blind to it?** | **Yes, conclusively.** With `max_budget_usd=0.05`: eight start-then-interrupt turns moved the accumulator **$0.000649** — bit-identical zero for turns 2 through 8 — and never tripped, across 64.09 s of streamed inference. Six ordinary turns on the **same connection, same budget, same options** then tripped it at $0.058531 (`limit_hit='budget'`, `terminal_reason='budget_exhausted'`, `subtype='error_max_budget_usd'`) |

**The positive control is what makes B1c a demonstration rather than an
inference.** The budget mechanism was provably live in the identical
configuration; the interrupt phase and the ordinary phase differed only in the
prompt and in whether `interrupt()` was called.

**Corroboration that the unattributed work was real.** In part C, cumulative
recorded cache-*creation* before the first ordinary turn is **zero** across all
eight interrupted turns — yet that turn reads **29,135** cached tokens. Around
4,500 of those are part C's own conversation content (~560 per interrupted turn,
consistent with 8 s of Sonnet streaming): prefix that no turn is recorded as
having created. Separately, later turns cache-read 24,687 tokens where only
24,578 were ever recorded as created.

**Consequences, in order of importance:**

1. **`max_budget_usd` does not bound spend against a start-then-interrupt loop.**
   Enforcement lives inside the CLI, against an accumulator this service never
   sees, and that accumulator does not move. **Budget at the account or
   organisation level**, and rate-limit turn starts and `/interrupt` upstream if
   the service is exposed to anything.
2. An interrupted turn now reports `turn_cost_usd: null` — "nobody can say" —
   rather than a false `0.0`. `null` versus `0.0` carries that distinction
   throughout this codebase.
3. A service-side spend guard was **deliberately not built**: it could only be
   built on the session's cumulative cost, which is precisely the figure proven
   blind to this attack. It would work only when it was not needed, while
   presenting as a second independent control. Revisit if the SDK ever begins
   reporting usage on an aborted turn — the condition is already detected in
   `_record_turn`.

**Not established:** whether a cost could be reconciled at connection close. The
probe reads `total_cost_usd` after `close()`, which is the last recorded value, so
a close-time `ResultMessage` would be invisible to it. No mechanism is known by
which the CLI could learn a cost it never received, and a post-hoc reconciliation
would not help `max_budget_usd` anyway — it must trip *during* the session to
bound anything.

---

## CP-071 — X1–X5 — the SDK conversation id: when it exists, and what reaches the wire

`spike/probe_session_id.py`, 2026-08-05, `claude-haiku-4-5`. Run to answer request 2
of `../../spec/history/agent-service-openapi-requirements.md` — a relay asked for
`sdk_session_id` somewhere cheaper than the body of a turn, and asked whether it
could be a field on `POST /v1/sessions` instead of a header. That question turns
entirely on **when the id comes into existence**, which nothing here had measured.
The model is irrelevant to all five: this is CLI argument plumbing.

| ID | Question | Result |
|---|---|---|
| X1 | Is the id knowable after `connect()`, before any turn? | **No.** `get_server_info()` returns 11 keys (`account`, `agents`, `models`, `output_style`, `pid`, …) and **not one** contains a session id; nothing arrives on the connection within 5s of `connect()` without a `query()`. Free — no inference |
| X2 | Does `ClaudeAgentOptions.session_id` pin it? | **Yes, exactly.** Requested `d92af8e1-…`; init and result reported that string and nothing else |
| X3 | Is it stable across turns of one connection? | **Yes.** 3 turns, 1 distinct id across every init *and* every result |
| X4 | What does the CLI send as `x-claude-code-session-id`? | **The same string**, on all 4 `POST /v1/messages` calls, equal to the requested UUID |
| X5 | `session_id` + `resume`? | **Rejected by the CLI**, exit 1: *"--session-id can only be used with --continue or --resume if --fork-session is also specified."* With `fork_session=True` it is accepted and the fork gets the requested id |

**X1 is the one that settles the design.** The id does not exist until the first
turn asks for one, so "return it from `POST /v1/sessions`" is impossible by
observation and possible only by *assignment* — the service minting a UUID and
passing `--session-id`. X2/X3 say assignment works and holds.

**X4 is the one worth the money.** It was run through a local forwarding proxy
(`ANTHROPIC_BASE_URL` pointed at an in-process ASGI app that logs headers and
streams the response back from `api.anthropic.com`), because every other case
here measures what the SDK reports *in-process*, and a relay joins on what the
CLI puts *on the wire*. They are the same string. Two incidental findings from
the same run: the CLI honours `ANTHROPIC_BASE_URL` over plaintext `http://` to a
loopback port, and it opens with a `HEAD /api/hello` health check that carries
**no** session header — so a gateway keying on the header must tolerate requests
without one.

**X4 also produced an unasked-for finding that a gateway-relaying caller needs
more than it needs the header.** The proxied turn reported
`total_cost_usd: 0` — while the identical un-proxied turns in X2 reported
`0.0029`, `0.0054`, `0.0079`. Same prompt, same model, real inference: the
response streamed back and the model answered. **With `ANTHROPIC_BASE_URL`
overridden, the CLI's own cost accounting came back zero.** Cause not
established (n=1) — it may be that the CLI prices only responses it recognises
as coming from the first-party endpoint, or that a header the proxy dropped
carries the pricing. The consequence is what matters and it is not subtle: a
caller that relays model traffic through its own gateway **cannot use
`total_cost_usd`, `turn_cost_usd` or `SessionRecord.total_cost_usd` from that
container**, because the SDK is not filling them in. Those figures are already
documented as a floor rather than a total (B1); through a gateway they may be
zero outright. Such a caller must price from its own gateway's token counts.
Worth a dedicated probe before anyone builds billing on it.

**X5's first attempt measured nothing**, and is recorded because the mistake is
easy to repeat: the fork arm was run in a different `cwd` and failed with *"No
conversation found with session ID"* — a transcript-lookup failure, not a verdict
on the flag combination. The CLI resolves a resumable session **per project
directory**. Re-run in the same `cwd`, with a plain-`resume` control turn to
prove the transcript was findable, it succeeded.

**The control turn produced a finding of its own, unasked:** a plain `resume`
(no `session_id`, no fork — what `options.py` does today) came back reporting
**the same** SDK id it resumed, `c485bc03-…`. So a resumed conversation is not a
new conversation to the CLI, and a caller storing an SDK id against its own
records does not need a new row for a resume. n=1, no fork; `fork_session=True`
is the case that *does* mint a new id, and this service never sets it.

What this does **not** establish: whether the CLI can change its conversation id
*mid-connection* — after a compaction, say. Every case here ran short turns.
`sessions.py` takes the first init's id and never overwrites it, so if that can
happen, this service would report a stale id and a relay's join would go quietly
wrong rather than absent. **Open.**

---

## CP-072 — C1–C3, P1–P2 — the gateway zero, and the supplied-id edges

`spike/probe_gateway_cost.py` and `spike/probe_supplied_id.py`, 2026-08-05,
`claude-haiku-4-5`. Run to close the questions X4 opened rather than leave them
as a consumer's problem.

| ID | Question | Result |
|---|---|---|
| C1 | Direct to the API, CLI-generated id — the baseline | `total_cost_usd: 0.027395`, real token counts, `model_usage` populated |
| C2 | Through a **verbatim-forwarding** proxy | `total_cost_usd: 0`, **every `usage` token count zero**, `model_usage` **empty** — on a turn whose `subtype` is `success` and which returned a real answer |
| C3 | `ANTHROPIC_BASE_URL` set to the **real** API host, no proxy | `total_cost_usd: 0.005131`, real counts — **prices normally** |
| P1 | A supplied `--session-id` that already has a transcript in that cwd | **Rejected**, exit 1 (`ProcessError`). Not a silent resume, not an overwrite |
| P2 | Is the first message still the init under `include_partial_messages`? | **Yes** — `SystemMessage` carrying `session_id`, ahead of the `StreamEvent`s |

**C3 disproves the obvious hypothesis, including the one this repo wrote down.**
X4 recorded the zero alongside an overridden `ANTHROPIC_BASE_URL` and the
consumer proposed keying off exactly that. The override is *not* the trigger:
pointed at the real host it prices correctly. Something about a proxy in the
path is, and the cause remains unestablished.

**C2 is what makes the shape actionable anyway.** The zero is not confined to
the dollar figure — `usage` and `model_usage` are empty too, on a *successful*
turn. A turn that consumed zero input tokens, produced zero output tokens and
billed no model did not happen; the reply exists. So the numbers are **missing,
not zero**, and that is detectable without knowing the cause. `runner.unpriced_turn`
matches that exact conjunction and `build_outcome` reports `total_cost_usd: null`
for it — the same rule `unattributed_abort` already applies to the aborted shape.

**P1 settles the reuse question** the caller-supplied-id feature raises: a client
bug that reuses an id fails loudly at session open rather than quietly
continuing somebody else's conversation. It reaches the API as a 502.

**P2 closes the last gap on the header**: the first message of a turn carries the
id even with partial messages enabled, so `x-sdk-session-id` is present on a
first streaming turn in that configuration too.

---

## CP-073 — T1 — a create() that times out in open() does NOT leak the subprocess

`spike/probe_open_timeout_leak.py` and `spike/probe_close_straggler.py`,
2026-08-06. **Free** — `connect()` spawns the CLI but no prompt is ever sent.

**The suspicion, and it was mine:** `SessionRegistry.create()`'s timeout arm
releases the reservation and raises, dropping the `AgentSession` **without an
explicit `disconnect()`** — so a 504 on create looked like it should leave a CLI
subprocess with no owner, once per retry.

**It does not.** Cancellation from `asyncio.timeout` lands inside the SDK's
`connect()`, and the process is torn down as that unwinds.

| `open_timeout_s` | Outcome | Children ever seen | Alive after 2s | Alive after `gc.collect()` |
|---|---|---|---|---|
| 0.762 | `SessionOpenTimeout` | 9 | **0** | 0 |
| 1.514 | `SessionOpenTimeout` | 1 | **0** | 0 |
| 2.266 | `SessionOpenTimeout` | 23 | **0** | 0 |
| 3.017 | `SessionOpenTimeout` | 25 | **0** | 0 |
| 3.378 | `SessionOpenTimeout` | 23 | **0** | 0 |

**The first run of this probe measured nothing, and said so loudly enough to be
caught.** Every case reported `spawned: 0` — not "no leak" but "the timeout fired
before the CLI was ever spawned". The control then timed the real window: the
child appears at **0.46s** and `open()` returns at **3.47s**, so the original
guesses (0.05–2.0s) mostly landed before the spawn. Timeouts are now *aimed*
inside that measured window, and a continuous watcher records every pid that
appears, because a single reading after the fact cannot tell "never spawned"
from "spawned and already gone".

**The control's `alive_after_close: 1` was an artifact**, not a second finding.
`probe_close_straggler.py` names the processes instead of counting them: a
session that never took a turn spawns **exactly one** child
(`_bundled/claude.exe`), and zero survive two seconds after `close()`. S5 holds
for a turn-less session too.

**No code change was made.** The defensive cleanup this probe was written to
justify is unnecessary, and adding it would have put an unreviewed edit into the
most carefully-reasoned concurrency path in the repo to fix a defect that does
not exist. **RECHECK ON SDK UPGRADE** — this rests on the SDK reclaiming a
cancelled `connect()`, which is its behaviour and not a contract.

## CP-074 — T2 — creation does not consume a supplied session id; only a turn does

`spike/probe_id_burn.py`, 2026-08-06. **Free** — no prompt is sent.

Written because a contract clause (AS-27) and a consumer obligation (ST-5) had
been **asserted from inference** rather than measurement: P1 showed the CLI
refusing an id whose conversation had taken a turn, and this side generalised
that to "a create returning 504 may have consumed the id".

| Case | Reusing the same id afterwards |
|---|---|
| A — create **timed out** inside the spawn window (T1), id supplied | **ACCEPTED** |
| B — create **succeeded**, closed with **no turn** taken | **ACCEPTED** |

So the generalisation was false in both directions that mattered:

* An id survives a failed create, so retrying with the **same** id is safe.
* An id survives a create that succeeded but took no turn.
* Only a conversation that has actually taken a turn makes the id un-reusable
  (P1).

**The advice this replaces was worse than merely unnecessary.** ST-5 told the
consumer to mint a fresh UUID per *attempt*, which orphans the session whenever
the first attempt actually succeeded and only its response was lost. The correct
recovery reconciles against `GET /v1/sessions` on `sdk_session_id` — reachable
because that field is now on the record — and retries with the same id when no
session holds it.

---

## CP-075 — M2 — an MCP secret reaches the CLI as an **argv**, and the agent can read it

**Promised to Agent Studio** in `../to-agent-harness/llm-provider-and-auth.2.md`
§6 and run 2026-08-07. Probe: `spike/probe_mcp_argv.py` (part 1) plus a container
run (part 2, reproduction in that file's docstring). SDK `0.2.128`.

**The question.** Studio's ADR-0023 substitutes `${secret:NAME}` into an MCP
server's `headers` (http/sse) or `env` (stdio) on the way here. Does that value
reach the CLI subprocess as a command-line argument, readable from
`/proc/<pid>/cmdline` by the agent it was withheld from?

#### 1. Which channel — argv, and it is not close

`_build_command` in `_internal/transport/subprocess_cli.py`:

```python
cmd.extend(["--mcp-config", json.dumps({"mcpServers": servers_for_cli})])
```

The whole configuration is serialised into **one argv entry**. Measured, both
positions, one command:

```
[6] --mcp-config
[7] {"mcpServers": {"remote": {"type": "http", ..., "headers": {"Authorization":
    "Bearer SEKRET-HEADER-9d41f"}}, "local": {"type": "stdio", ..., "env":
    {"ACME_TOKEN": "SEKRET-ENV-3b7a2"}}}}
```

**Transport makes no difference**, as Studio predicted: `headers` on an `http`
server and `env` on a `stdio` one land in the same string.

#### 2. What is readable from inside the container — measured, not reasoned

Container booted from the published image, one session created carrying marker
secrets, then read **as uid 1000, the agent's own user**:

```
$ docker exec -u agent argvprobe sh -c 'for p in /proc/[0-9]*/cmdline; ...'
READABLE in /proc/18/cmdline  (exe: …/claude_agent_sdk/_bundled/claude)
    found: PROBE-ENV-SECRET-3b7a2
    found: PROBE-HEADER-SECRET-9d41f
```

`id` inside that shell: `uid=1000(agent)`. So the answer to the question as asked
is **yes**.

#### 3. The stronger finding: nothing can withhold it from the agent

Two further measurements make this structural rather than a property of argv:

| | |
|---|---|
| owner of the CLI process | `uid=1000 gid=1000` — **the agent's own uid** |
| `/proc` mount options | `rw,nosuid,nodev,noexec,relatime` — **no `hidepid`** |

The CLI runs **as the agent** and must be able to use the secret. So no channel
withholds it from that uid:

- **A file instead of argv is available** — the SDK's `mcp_servers` accepts
  `str | Path`, and passes it through as `--mcp-config <path>` untouched. It
  moves the secret out of the process table. It does **not** withhold it: the
  same uid must read the file.
- **`hidepid` would not help either.** It hides *other* users' processes; this
  one belongs to the reader.

So the useful distinction is **audience, not secrecy**. argv is visible to
anything that can list processes — the host, a monitoring agent, another
container sharing a PID namespace. A file narrows that to the agent and root.
Neither reaches "the agent cannot read it".

#### 4. Is the answer pinned to the SDK version?

**Partly, and the write-up says which part.**

- **`--mcp-config` accepting either a JSON string or a file path is the CLI's
  interface**, and the SDK's own code path for `str | Path` shows both are
  supported.
- **Inlining the JSON into argv is the SDK's choice in 0.2.128**, not something
  the CLI requires. It could change to a temporary file in a later version
  without any interface changing.

So: treat "the secret is in argv" as **true of 0.2.128 and worth re-measuring on
an SDK bump**, and treat "the agent can read any MCP secret" as **structural**,
because it follows from the CLI running as the agent's uid rather than from how
the configuration is passed.

`probe_mcp_argv.py` exits non-zero if the argv answer ever changes, so the
version-pinned half is a regression detector rather than a one-off note.

---

## CP-076 — Still unverified — needs a container build

| ID | Question | Why it matters |
|---|---|---|
| L5 | Does `sandbox` work on Windows? Inside a Linux container? | Q12; would partly restore the confinement L3 and L7 showed is absent |
| L6 | Does the bundled binary run on Debian slim? | ~~`deployment.md` base-image choice~~ **Settled by Plan 4** — it runs (glibc, `2.1.220`). The real trap was musl: the build *succeeds silently* with an empty `_bundled/` and fails at the first turn. See `deployment.md` |

---

## CP-077 — Spend

Approximately **$0.37** across seven live runs (L1–L4 plus L7), plus **$0.16**
for the two `probe_limits.py` runs (see "Limit-stop markers" above) and
**≈$0.494** for the six `probe_permissions.py` cases — five in the initial
round plus case 6's two attempts, added during review round 1 (see "Permission
enforcement" above) — plus **$0.2749** for the three `probe_midturn_control.py`
runs (M1) — plus **$0.189** for the three interrupt-cost parts (B1), whose *real*
cost was ≈$0.41 for the reason B1 documents — plus **≈$0.06** for the two
`probe_session_id.py` runs (X1–X5; X1 is free, and the rest ran on
`claude-haiku-4-5` with one-word prompts) — **≈$1.55 reported / ≈$1.77 actual**
across all live spikes to date.

The discrepancy in that last line is not a rounding artifact. It is B1.

---

# D. The container

## CP-078 — what the container is for

Companion to `design.md` (CP-096). Target deployment: the agent service runs
in a Linux container; a directory from the host is bind-mounted as the agent's
workspace. This document covers what that boundary does and does not carry, and
the configuration needed to make git work inside it.

Host assumed to be Windows with Docker Desktop (WSL2 backend). Linux/macOS hosts
are simpler; differences are called out — **but note that no Linux or macOS host was
tested**; those differences are reasoned, not measured.

> **What this document is now.** It began as design input, written before anything was
> built, and asserted a great deal as fact. Plan 4 built the container and tested those
> assertions; several were wrong, and each has been replaced by what was actually
> measured, with the number and the method. Where something was *not* tested it now says
> so — there is a consolidated
> list of what is still unverified (CP-093) near the end, and
> individual claims carry the word **UNVERIFIED** in place. The discipline is that an
> unmeasured claim is a hypothesis.
>
> **Start with Security posture (CP-081)** if you are about to expose this
> anywhere. `Bash` is enabled, `permission_enforcement` is `"none"`, and there is no
> authentication on the API.

---

## CP-079 — What crosses the mount boundary

The container sees **a directory**, not your machine. This distinction drives
everything below.

| Thing | Visible in container? | Consequence |
|---|---|---|
| Files under the mounted path | Yes | The agent reads and edits real files |
| `.git/` of the mounted repo | Yes — it is just a directory | Full local history: `log`, `diff`, `status`, `branch`, `add`, `commit` |
| Repo-local hooks (`.git/hooks/*`) | Yes | **Measured: they execute inside the container**, as the container user, and block the commit when they reference host paths, host-installed tools, or have CRLF line endings — see §5 (CP-082) |
| The `git` binary | No | The image must install its own git |
| `~/.gitconfig` (identity, aliases, filters) | No | **Measured:** `git commit` fails exit 128 with *"Please tell me who you are"* until identity is supplied — and `core.autocrlf=true` is lost with it, which corrupts the repo on the agent's first `git add -A`. Both are now replaced from `compose.yaml`'s environment: identity as `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, line endings and filemode as `GIT_CONFIG_*` (CP-082) |
| SSH keys (`~/.ssh`), credential manager, GH tokens | No | `fetch` / `pull` / `push` against remotes fail |
| Anything outside the mounted path | No | Including sibling repos, home directory, other drives |

**Net effect:** the agent gets a fully functional *local* repository and is cut off
from your remotes. It can inspect, branch, and commit; it cannot push to GitHub.
For a sandbox this is a good split — keep it unless there is a concrete reason to
grant remote access.

## CP-080 — Why the container matters for the design

`design.md` notes that pinning `cwd` to a workspace directory is "convenience, not
containment" because `Bash` can `cd` anywhere the process can reach. **In a
container that stops being true**: the process cannot reach anything that was not
mounted. The container is the actual security boundary.

Two consequences:

- The `workspace_subdir` validation in the spec becomes defense-in-depth rather
  than the primary control. It stays, but it is no longer load-bearing.
- The blast radius of an enabled `Bash` tool is now "whatever you mounted, plus
  outbound network", not "the whole machine as your user". This is what makes
  running with the full toolset reasonable.

---

## CP-081 — Security posture

**This section is the one place the posture is stated. Read it before you change a
port binding, a mount, or a tool default.**

### Three facts, all true by default, all deliberate

1. **`Bash` is enabled.** `default_allowed_tools` is
   `['Read','Write','Edit','Bash','Glob','Grep','WebSearch','WebFetch']` — read back
   from `GET /v1/capabilities` on the running container (Task 3), not from the source.
2. **`permission_enforcement` is `"none"`.** No in-process control is wired up at all.
   `README.md` records why: the SDK auto-approves a whole-tool `allowed_tools` entry
   before `can_use_tool` is consulted, so that mode is not offered; the `hook` mode
   that *does* fire confines `Write`/`Edit`/`NotebookEdit` only, and a shell redirect
   (`echo x > /etc/foo`) walks straight past it.
3. **There is no authentication on the HTTP API.** No key, no token, no allowlist.
   Every route, including `POST /v1/sessions` and `POST …/messages`, is open to
   whoever can open a TCP connection to the port.

Put together: **anyone who can reach port 8000 has a shell in the container.** Not
"can ask the agent to do things" — a shell, via a tool that is on by default and
governed by nothing in-process.

### Which is why the port is bound to loopback

```yaml
ports:
  - "127.0.0.1:8000:8000"      # NOT "8000:8000"
```

`"8000:8000"` publishes on **every host interface**. On a laptop on a coffee-shop
network, or any machine on a corporate LAN, that hands container shell execution to
anyone who can route to the host. There is no second control behind it — no auth to
fail closed, no permission check to refuse the command. The bind is the control.

Measured (Task 3), from the host, against every interface it has:

```
docker port                      -> 127.0.0.1:8000
netstat -ano -p tcp | :8000      -> TCP  127.0.0.1:8000  LISTENING   (and nothing else)

Test-NetConnection 127.0.0.1     :8000  -> TcpTestSucceeded = True
Test-NetConnection 192.168.1.10 :8000  -> False      <- LAN address
Test-NetConnection 172.17.32.1   :8000  -> False      <- WSL vEthernet
curl http://192.168.1.10:8000/healthz  -> curl: (7) Failed to connect
```

The socket is bound to `127.0.0.1` specifically, not to `0.0.0.0` behind a firewall
that happens to be on. If you need the service reachable from another machine, put
an authenticating reverse proxy in front of it and keep this binding as it is — do
not widen it.

Inside the container `--host 0.0.0.0` is correct and is not a contradiction: that is
the container's own network namespace, and exposure is decided entirely by the
host-side publish above.

**The loopback binding excludes the LAN, not the container.** It governs who can
reach *in*; it says nothing about where the agent can reach *out*. Docker Desktop
gives the container a route to the host's own loopback services via
`host.docker.internal` (measured at `192.168.65.254`), and the final review used it
from inside: the agent called **this service's own unauthenticated API** on the host
and got `200`, and reached host TCP `445`. That is not an escape — the agent already
has a shell in the container, and egress is unrestricted (CP-091)
— but the consequence deserves saying plainly: **any database, dev server, model
runner or admin UI the operator has bound to `127.0.0.1` on the host is within the
agent's reach**, and it is bound to loopback precisely because it is not expected to
be. If something on the host must stay out of reach, loopback-only binding is not
what will keep it out.

### What the boundary actually is, and is not

**Is:** the container. The process cannot reach anything that was not mounted.
`design.md`'s note that pinning `cwd` is "convenience, not containment" stops being
true here — `workspace_subdir` validation becomes defense-in-depth rather than the
primary control.

**Is not:**

- **Confidentiality.** `:ro` stops writes through the mount. It does not make a
  directory safe to let the container *read*. The boundary is
  read-everything-mounted, write-only-`/workspace`.
- **Protection of the host directory from the host.** `:ro` protects the mount, not
  the underlying path.
- **A network boundary.** Egress is unrestricted and was confirmed working (Task 3:
  TLS to `api.anthropic.com` reachable with all capabilities dropped). The agent can
  reach anything the host can reach.

### Hardening that is in place — measured, and nothing broke

| Control | Where | Evidence |
|---|---|---|
| Non-root `agent`, uid 1000 | `Dockerfile` `USER agent` | `uid=1000(agent) gid=1000(agent)` in every task from 3 on |
| `/app` root-owned and not writable by the service | `Dockerfile` | the venv cannot be modified at run time; the one world-writable file uv left (`/app/.venv/.lock`, 0666) is `chmod o-w`'d in the image, and `find /app -perm -0002` now returns only inert symlinks |
| `cap_drop: [ALL]` | `compose.yaml` | `CapInh/CapPrm/CapEff/CapBnd/CapAmb` all `0000000000000000` in `/proc/self/status` |
| `no-new-privileges:true` | `compose.yaml` | `NoNewPrivs: 1`; `Seccomp: 2` (filter mode, 2 filters) |
| Only listed keys cross the boundary | `compose.yaml` uses `environment:`, never `env_file:` | compose reads `.env` for *interpolation*; anything else in it stays on the host. A boundary property, not a style choice |
| `restart: "no"` | `compose.yaml` | a permanent config failure stays visibly down instead of looping |

The image inherits **8 setuid-root** binaries from `python:3.13-slim` (`chfn`, `chsh`,
`passwd`, `mount`, `newgrp`, `umount`, `gpasswd`, `su`) plus **3 setgid** (`chage`,
`expiry`, `unix_chkpwd`). With `CapBnd` empty a setuid-root exec cannot acquire
capabilities at all, and `NoNewPrivs=1` blocks the transition itself. Measured:

```
su root -c id                        -> su: Authentication failure     (root has no password)
passwd                               -> Authentication token manipulation error
mount -o remount,rw /reference/...   -> mount: must be superuser to use mount.
```

**And nothing needed adding back.** Everything the service does was exercised with all
capabilities dropped (Task 3): uvicorn binds :8000 (port > 1024, so no
`CAP_NET_BIND_SERVICE`); `/healthz` and `/v1/capabilities` answer 200; the SDK's
subprocess spawn — `anyio.open_process` on the 275,012,592-byte bundled `claude`, the
exact call at `subprocess_cli.py:733` — returns `pid=157 rc=0 out='2.1.220 (Claude
Code)'` in 0.11 s; `git init` and `rg --version` work; TLS to `api.anthropic.com` is
reachable; `$HOME` is writable. **`cap_drop: [ALL]` + `no-new-privileges` are free
here.** Do not remove them on the theory that the SDK needs something.

### What is deliberately *not* done, and why

- **Egress is not restricted.** Out of scope for Plan 4 by decision, and worth doing
  eventually. Note the coupling: restricting egress to `api.anthropic.com` implicitly
  disables `WebSearch` and `WebFetch`, so drop them from `default_allowed_tools` at
  the same time or you get confusing tool failures instead of a clear absence.
- **No remote git access.** No SSH agent forwarding, no scoped token, no credential
  helper. This is not an oversight: **any credential placed in this container is
  readable by any command the agent runs**, because `Bash` is enabled and nothing
  in-process filters it. The current split — full *local* git, no remotes — is the
  good one. Revisit only against a concrete need.
- **`/workspace` stays a bind mount, not a named volume.** A named volume is far
  faster on Windows (§4: 223–561x on `git status`) and makes the scratch nature
  explicit, but it is harder to inspect from the host and the stated use case is
  mounting a real host repo. Trade-off recorded, decision unchanged.
- **No `mem_limit` or `pids_limit`.** A session costs ~110 MiB and ~17 pids on top of
  a ~250 MiB warm baseline (Task 7), so `max_sessions: 8` projects to **~1.1 GiB**
  with nothing bounding it. The session cap is a session cap, not a memory cap. Open
  item below.
- **No Postgres.** Plan 3 is skipped by decision; see `persistence.md` (CP-110).

### Two things to know before you trust the surface area

- **`pip` is on `PATH`**, so the agent can `pip install --user` at run time. Weak as a
  finding on its own — `python` plus network egress is already arbitrary code
  execution — but it should be stated rather than discovered. It is a reason the
  container, not the tool list, is the thing you rely on.
- **Repo-local hooks in a mounted repository execute inside the container**, as
  uid 1000, with the container's `PATH` — and on a Windows bind mount the exec bit is
  synthesized, so *any* file at `.git/hooks/<name>` runs regardless of what the host
  intended. A mounted repo can therefore run **more** code inside the container than
  it does on the host. See §5 (CP-082).

---

## CP-082 — Git configuration inside the container — measured

Everything in this section is measurement (Task 5), not inference. Method: the
compose stack via `docker compose --env-file <scratch>` (so `cap_drop: [ALL]`,
`no-new-privileges` and the non-root user all applied), with `/workspace` bound to a
real repository on the Windows host. No API call was made; **$0.00**. Every fix was
removed or overridden in turn, so "load-bearing" below means the failure was
reproduced, not assumed.

Baseline facts the rest of the section rests on, all observed inside the container:

```
uid=1000(agent) gid=1000(agent)          CapPrm/CapEff/CapBnd = 0000000000000000
git version 2.47.3
/workspace           uid=0 gid=0 mode=777      <- ownership and mode are SYNTHESIZED
/workspace/.git      uid=0 gid=0 mode=777
/workspace/README.md uid=0 gid=0 mode=777
/etc/gitconfig: [safe] directory = *   /   [core] filemode = false
```

`git status`, `git log`, `git diff` and `git commit` all work as shipped, and a
commit made inside the container **lands on the host** and is visible to Windows git
with the expected authorship. That is the headline: git works. The four problems
below are about *why* it works and what breaks it.

### 1. Dubious ownership — **fix is load-bearing**

Bind-mounted files carry synthesized ownership: `/workspace` is `uid=0` while the
service runs as `uid=1000`, so git sees a repo owned by another user.

| Configuration | `git status` |
|---|---|
| As shipped (`/etc/gitconfig` has `safe.directory = *`) | works, exit 0 |
| `git -c safe.directory= status` (resets the list) | **exit 128** |
| `GIT_CONFIG_NOSYSTEM=1 git status` | **exit 128** |

Both failures print exactly:

```
fatal: detected dubious ownership in repository at '/workspace'
```

**Correction to the previous advice.** This document used to offer
`safe.directory /workspace` as "a tighter setting if you prefer". It is not
sufficient. A nested repository — a submodule, a vendored checkout, a scratch
`git init` the agent makes — is a *separate* repo path and is not covered:

```
$ GIT_CONFIG_NOSYSTEM=1 git -c safe.directory=/workspace status   # in /workspace/nested
fatal: detected dubious ownership in repository at '/workspace/nested'
```

The baked `'*'` handles it. Use `'*'`; the tighter form buys nothing here (the
container is already the boundary) and fails on submodules.

### 2. Commit identity — **fix is load-bearing, and all four variables are needed**

With the compose defaults, an actual commit made inside the container:

```
$ git log -1 --format='%an <%ae> / %cn <%ce>'
agent-service <agent-service@localhost> / agent-service <agent-service@localhost>
```

Confirmed from the **host** afterwards, so the write crossed the mount. Unset the
variables and `git commit` fails with exit 128:

```
Author identity unknown

*** Please tell me who you are.
...
fatal: unable to auto-detect email address (got 'agent@b8a5d954cc85.(none)')
```

Unsetting **only** `GIT_AUTHOR_*` fails identically to unsetting only
`GIT_COMMITTER_*`, and identically to unsetting all four — git needs a resolvable
identity for both roles and there is no `~/.gitconfig` to fall back on. Do not drop
either pair.

`git commit` also works end to end **under `cap_drop: [ALL]`, as `uid=1000`, on a
mount whose ownership is synthesized as root** — no capability needed adding back.

### 3. Git settings that depend on the host

Two of git's settings are **correct on a Windows host and wrong on a Linux one**, and
neither fails loudly when it is wrong. Both are now supplied from `compose.yaml` as
`GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n`, with Windows defaults and a variable each:

| Variable | Setting | Windows host (default) | Linux / WSL2 host |
|---|---|---|---|
| `GIT_AUTOCRLF` | `core.autocrlf` | `true` | `input` |
| `GIT_FILEMODE` | `core.filemode` | `false` | `true` |

**Why the environment and not `git config --system` in the image.** Because `.git/`
is inside the mount and **repo scope beats system scope**. The image used to bake
`core.filemode false`; Task 5 measured that it was doing nothing (a
Git-for-Windows `.git/config` already says `false`, and removing `/etc/gitconfig`
entirely changed no result), and that on a repo whose `.git/config` says
`filemode = true` it was silently overridden. Task 6 measured the replacement
directly, on one repo, changing only the delivery mechanism:

```
$ git config core.filemode true          # simulating a Linux/WSL2-cloned repo
$ git config --get core.filemode                       # with GIT_CONFIG_VALUE_1=false
false                                                  <- the environment wins
$ git diff --summary | grep -c 'mode change'
0
$ ... with the GIT_CONFIG_* pair removed:              # what a baked value could do
66                                                     <- all 66 files, back
```

`git config --show-origin` reports the environment pairs as `command line:`, which is
the highest-precedence scope git has — read after every config file. It is the only
channel that can win against a mounted `.git/config`. `safe.directory '*'` stays baked
in the image because it is **not** host-dependent: every bind mount has synthesized
ownership.

**And the filemode case is a data-integrity problem too, not just noisy output.**
Measured on a throwaway clone with no repo-scope `core.filemode` and the environment
pair removed: the agent's `git add -A && git commit` wrote **mode 100755 for all 66
tracked files** into the commit, which the host then reads back as 66 reverse
`100755 => 100644` mode changes. Same shape as the line-ending corruption in §3b, and
it survives the same way — in history.

**GIT_CONFIG_COUNT must equal the number of pairs.** Git reads exactly that many and
silently ignores the rest — no warning, no error, the setting simply does not apply.
`tests/test_config.py::test_the_compose_git_config_env_block_is_self_consistent` pins
the count, the contiguity of the indices, and both key names.

#### The underlying mechanism, measured

Forcing filemode tracking back on, on a 66-file repo:

```
$ git -c core.filemode=true diff --summary | head -1
 mode change 100644 => 100755 .dockerignore
$ git -c core.filemode=true diff --summary | grep -c 'mode change'
66            <- every tracked file, 66 of 66
```

`git status --porcelain` goes from 53 lines to 66 — the whole tree. So the
consequence claimed here is confirmed, and it follows directly from the `mode=777`
Task 3 measured.

**But the baked system-scope setting is not what is preventing it on this host.** Any
repo cloned by Git for Windows already carries `filemode = false` in its own
`.git/config`, and `.git/` is mounted:

```
$ git config --show-origin --get-all core.filemode
file:/etc/gitconfig     false
file:.git/config        false        <- repo scope wins
$ GIT_CONFIG_NOSYSTEM=1 git -c safe.directory=/workspace status --porcelain | wc -l
53                                   <- unchanged with no system config at all
```

**And repo scope beating system scope cuts the other way.** `git init` / `git clone`
run on Linux — including inside WSL2, which this document elsewhere recommends
moving to — writes `filemode = true` into `.git/config`. Mount such a repo and the
baked fix is silently overridden:

```
$ git config core.filemode true          # simulating a Linux-cloned repo
$ git diff --summary | grep -c 'mode change'
66
```

**Verdict: converted, not kept.** The system-scope line was removed from the
`Dockerfile` and `core.filemode` now travels as `GIT_CONFIG_KEY_1`/`VALUE_1` from
`compose.yaml`, defaulted from `GIT_FILEMODE`. That is a strict improvement — same
cost, and it covers the two cases the baked value provably could not (a repo whose
`.git/config` sets `filemode = true`, and any Linux host where `false` would be the
wrong value and needs to be changed).

### 3b. The thing that actually shows the whole tree as modified: **line endings**

This is the finding this section did not have. The whole-tree "modified" listing on
this host is **not** caused by filemode at all:

```
$ git status --porcelain | wc -l
53
$ git diff --shortstat
53 files changed, 26261 insertions(+), 26261 deletions(-)
$ git diff --summary          # mode changes only
(empty)
```

Equal insertions and deletions, no mode changes: every line of every text file
differs. Cause, confirmed byte by byte:

```
working tree  .gitignore: '# Python-generated files\r\n'    <- CRLF
index blob    .gitignore: '# Python-generated files\n'      <- LF
host:      core.autocrlf=true   (file:.../Git/etc/gitconfig — Git for Windows default)
container: core.autocrlf unset  (git's default false on Linux)
```

The host's git normalizes on the way in and out, so the host sees a clean tree. The
container's git does not, so it sees every text file as rewritten.

**Why this is worse than cosmetic — it corrupts history.** A single agent commit
rewrites the entire repository's line endings. Measured on a throwaway clone, with
the image exactly as shipped:

```
$ git add -A && git commit -m 'agent: fix a typo'
64 files changed, 27433 insertions(+), 27433 deletions(-)
$ git cat-file -p HEAD:.gitignore | head -c 26 | od -c
0000000   #   ...   f   i   l   e   s  \r  \n                <- CRLF now committed
```

Visible from the host immediately. `git add -A` is not an exotic thing for an agent
to run.

It is also the single largest cost in `git status` — see the timings below: on a
5000-file repo it is **23.5 s per status instead of 1.9 s**, because git re-reads and
re-hashes every file on every invocation and can never mark the index up to date.

**Fix, measured.** Against a pristine index copy each time, on a 66-file repo where
64 files mismatch:

| `core.autocrlf` | files reported modified | what a checkout writes back to the host |
|---|---|---|
| unset (as shipped) | **64** | LF |
| `false` | **64** | LF |
| `input` | **0** | LF — creates a mixed-ending tree on the host |
| `true` | **0** | **CRLF — byte-identical to the host's own checkout** |

So the previous advice in this document — *"leaving it unset (git's default `false`
on Linux) is usually the safer choice for a mounted Windows repo; the files keep
whatever endings they already have"* — **is wrong on this host.** It is the setting
that produces the whole-tree diff, the 12x `git status` penalty, and the CRLF-into-
history commit.

#### Shipped, and verified end to end (Task 6)

`core.autocrlf=true` is correct for a Windows-host bind mount and wrong for a Linux
one, so it is not baked into the image. It ships in `compose.yaml` through the same
channel as the identity variables, defaulted for the host this document documents and
overridable in one place:

```yaml
    environment:
      GIT_CONFIG_COUNT: "2"
      GIT_CONFIG_KEY_0: core.autocrlf
      GIT_CONFIG_VALUE_0: ${GIT_AUTOCRLF:-true}     # Linux/WSL2 host: set to `input`
      GIT_CONFIG_KEY_1: core.filemode
      GIT_CONFIG_VALUE_1: ${GIT_FILEMODE:-false}    # Linux/WSL2 host: set to `true`
```

Verified by having the container do the exact thing that corrupts the repository.
Throwaway `git clone --no-hardlinks` of this repo on the Windows host (`git ls-files
--eol`: **64 files `i/lf w/crlf`**, `git status` clean), bind-mounted at
`/workspace`, agent writes a file and runs `git add -A && git commit`:

| | as shipped **before** Task 6 | **as shipped now** |
|---|---|---|
| `git status --porcelain` in the container, pristine index | **64** | **0** |
| `git diff --shortstat` | 64 files, **27,685 +/-** | *(empty)* |
| what `git add -A && git commit` touched | **67 files, 27,686 insertions, 27,685 deletions** | **1 file, 2 insertions** — only the file the agent wrote |
| `.gitignore` blob in the resulting commit | `# ... files \r \n` — **CRLF in history** | `# ... files \n` — unchanged LF |
| host `git status --porcelain` afterwards | **66** | **0 — clean** |
| host CR counts (`.gitignore`/`compose.yaml`/`Dockerfile`/`README.md`/`config.py`) | rewritten | **28 / 167 / 152 / 222 / 219 — identical to baseline** |
| host sha256 of those files | changed | **byte-identical** |

The "before" column is not a reconstruction: it is the same container image with the
`GIT_CONFIG_*` pairs removed from its environment, run against a second clone.

One residual, visible in the run and worth knowing: a file the agent *creates* is
written with LF and git says so — `warning: in the working copy of 'agent-note.txt',
LF will be replaced by CRLF the next time Git touches it`. The host sees it as
`i/lf w/lf` until the next checkout normalizes it. That is a new file only; no
existing file is touched.

(A repo-level `.gitattributes` with `* text=auto` fixes this properly and portably for
every clone on every host, and makes `GIT_AUTOCRLF` irrelevant — but that is a change
to *your* repository, not to this service.)

### 4. Performance — true, and much worse than "an order of magnitude"

Same repository, bind-mounted from `C:\` versus `tar`-copied into the container's own
overlay filesystem, same git binary, same container. Synthetic repo, **5000 tracked
files**, CRLF working tree + LF index (i.e. a realistic Windows clone):

| `git status` | bind mount | container fs | ratio |
|---|---|---|---|
| **as shipped** (CRLF mismatch, rehashes everything) | **23,545 ms** (23.2–23.8 s, n=5) | **42 ms** (37–51, n=5) | **561x** |
| with `core.autocrlf=true`, steady state (stat-only) | **1,882 ms** (1845–1932, n=5) | **8.4 ms** (8–9, n=5) | **223x** |
| first run after the index stat cache is refreshed | 32.9 s | 124 ms | |

This repository itself (66 tracked files, 3974 files on disk, 324 MB with `.venv`):

| Operation | bind mount | container fs | ratio |
|---|---|---|---|
| `git status --porcelain` | **409 ms** (377–442, n=5) | 6.2 ms (5–7, n=5) | 66x |
| `git log --oneline -200` | 562 ms (555–569, n=3) | 4.3 ms (4–5, n=3) | 131x |
| `git diff --stat` | 1207 ms | 18 ms | 67x |
| `tar` copy of the tree (excl. `.venv`) | 3.7 s | — | — |

Copying the 5000-file repo *out* of the bind mount took **27.8 s**.

Two things to take from this. First, "often an order of magnitude" understated it by
more than a factor of twenty: 223x is the *floor*, with the line-ending problem
already fixed. Second, the two problems compound — the CRLF mismatch costs a further
**12.5x** on top of the mount (23,545 ms vs 1,882 ms), and it is the cheaper of the
two to fix.

The advice stands and now has numbers behind it: for a repo of any size, **move it
into the WSL2 filesystem** (`\\wsl$\...`) and mount from there, or accept that
`git status` alone is a multi-second operation and that `Grep` / `Glob` walk the same
translation layer. Note that a WSL2-cloned repo will carry `filemode = true` in its
`.git/config` — see §3.

### 5. Repo-local hooks execute — confirmed, and they fail in three distinct ways

`.git/hooks/*` is inside the mount, so git runs it. Confirmed:

```
$ git commit -m ...
PRE-COMMIT HOOK RAN: uid=1000 host=b8a5d954cc85 pwd=/workspace
COMMIT-MSG HOOK RAN, msg file=.git/COMMIT_EDITMSG
[feat/container 0546caa] ...
```

They run as the container user, in the container, with the container's `PATH`. Three
failure modes, all measured, all of which **block the commit** (exit 1, `HEAD`
unmoved):

| Hook | Result |
|---|---|
| References a host path or host-installed tool | `.git/hooks/pre-commit: 2: C:/Users/.../python.exe: not found` |
| Has **CRLF line endings** (i.e. edited on Windows) | `fatal: cannot exec '.git/hooks/pre-commit': No such file or directory` |
| Not executable on the host | **Runs anyway** — every mount entry is mode `0777` |

The second is the nastiest: the message says the file does not exist, and it does —
the shebang is `#!/bin/sh\r` and it is the *interpreter* that is missing. Any hook a
Windows editor has touched is a candidate.

The third is the inverse trap: on a Windows bind mount the exec bit is synthesized,
so *any* file at `.git/hooks/<name>` executes regardless of what the host intended.
On a Linux host the same file would be skipped.

If a mounted repo has hooks and they are not container-safe, `git commit
--no-verify` works, or move the hooks aside — but the failure is loud, which is the
good case.

**This repository now has one** (`.ci/hooks/pre-commit`, since 2026-08-06),
so mounting *this* checkout as `/workspace` is the case above. It is written to
survive it: `core.hooksPath` lives in `.git/config` and is inside the mount, so
the container's git does run it — and it checks for `uv` first and exits 0 when
absent, which is row 1 of the table above turned from a blocked commit into a
printed line. Measured: `uv` is **not** in the runtime image (it is bind-mounted
into the build's `RUN` steps and never `COPY`ed), `git` is. Its line endings are
pinned to LF by `.gitattributes`, which is row 2. See `ci.md`.

---

## CP-083 — Image requirements — measured

Beyond Python and the service's own dependencies:

| Package | Why | Version in the shipped image |
|---|---|---|
| `git` | The `Bash` tool's git commands; nothing else provides it | 2.47.3 |
| `ripgrep` | The SDK's `Grep` tool is built on ripgrep | 14.1.1 |
| `ca-certificates` | TLS to `api.anthropic.com` | — |
| `curl` | **Not optional.** The compose healthcheck runs `curl` *inside* the container and there is no other HTTP client in the image | 8.14.1 |

Also absent and worth knowing: **`ps` is not installed** (no `procps`). Every process
fact in this document was read from `/proc/*/stat`, `/proc/1/cmdline` and
`/proc/self/mountinfo` instead. `procps` was deliberately not added — it would enlarge
the boundary to make a test more convenient.

### Base image: glibc, not musl — the conclusion is right and the old reason was wrong

This document used to say a musl-based image (Alpine) "is likely to fail to execute"
the bundled native binary, and to recommend verifying "at build time by running a
trivial query". **Both halves were wrong.** Task 2 measured it:

**The Alpine build does not fail. It succeeds, exit 0, with no warning, and produces
an image that has no Claude Code binary in it at all.** There is nothing to fail to
execute.

`uv.lock` pins five wheels for `claude-agent-sdk` 0.2.128 — macOS arm64/x86_64,
`manylinux_2_17_aarch64`, `manylinux_2_17_x86_64`, `win_amd64` — and **no `musllinux`
wheel**. On musl no tag matches, so uv silently falls back to the sdist that is also in
the lock and builds it:

```
#12 0.865    Building claude-agent-sdk==0.2.128
#12 1.987       Built claude-agent-sdk==0.2.128
BUILD_RC=0
Generator: hatchling 1.31.0
Tag: py3-none-any            <- locally built; PyPI's wheels are py3-none-manylinux_2_17_x86_64
```

The sdist's `_bundled/` ships only a `.gitignore` — *"# Ignore bundled CLI binaries
(downloaded during build)"* — and that download does not happen:

```
/app/.venv/lib/python3.13/site-packages/claude_agent_sdk/_bundled/
  -rw-r--r-- 74  .gitignore          <- and nothing else
```

`claude_agent_sdk` on Alpine: **500 KB**. On glibc: **263 MiB**. Whole `.venv`: 33.4 MB
vs 295 MB. A 262 MB difference that the build reports as success. The failure is
deferred to the first turn of the first session, at run time, as `CLINotFoundError`
("Claude Code not found. Install with: `npm install -g @anthropic-ai/claude-code`") —
**not** an `Exec format error` or a loader complaint. Anyone debugging this while
expecting a loader error will look in the wrong place.

On the glibc image the binary is there and runs, as the non-root user with no API key
present:

```
/app/.venv/lib/python3.13/site-packages/claude_agent_sdk/_bundled/claude
-rwxr-xr-x root root 275012592     (262.3 MiB)     magic: 177 E L F  -> ELF, x86-64
$ ... /_bundled/claude --version
2.1.220 (Claude Code)      exit=0
linked against: librt.so.1, libc.so.6, /lib64/ld-linux-x86-64.so.2, libpthread.so.0, libdl.so.2, libm.so.6
ldd (Debian GLIBC 2.41-12+deb13u3) 2.41        (the wheel requires >= 2.17)
```

`SubprocessCLITransport._find_bundled_cli()` resolves exactly that path, so no `PATH`
lookup and no npm install is involved. (The **265.7 MB** figure in
Plan 4's global constraints is the *Windows* `claude.exe`; the Linux
binary is `275,012,592` bytes = 262.3 MiB.)

**This is not an Alpine-only trap, and it does not need anyone to edit the `FROM`
line.** Any platform lacking a matching wheel takes the same sdist path:
`docker buildx build --platform linux/arm/v7` would silently ship a broken armv7 image,
because the lock carries `manylinux_2_17_aarch64` and nothing for armv7. So would any
SDK bump whose lock momentarily lacks a matching tag.

**The build now guards against it, for free.** A `RUN` layer immediately after the
dependency sync derives the path from the installed package, asserts the file is
executable and larger than 200 MB, and execs `--version` — a local exec, **$0.00**, no
API call, and it sits inside the cached dependency region so a source-only rebuild
costs 0 s. Negative path proved rather than assumed: built on `python:3.13-alpine`, the
sync still succeeded and the guard failed the build at `test -x`, with a sentinel layer
after it that never executed. Size *and* exec-bit are both checked because the SDK's own
`_find_bundled_cli()` guards on `exists() and is_file()` only — it would accept a
0-byte file and fail confusingly later.

**`HOME` must be writable** — confirmed, not inferred. The bundled binary and the SDK's
session storage write under it; `/home/agent` is writable, `/workspace` is writable
(created and `chown`ed in the image so it works even with no bind mount), and `/app` is
not. A fully read-only root filesystem will break the service unless you mount a
writable `tmpfs` at `HOME` and wherever session JSONL is written — **that variant has
not been tested.**

---

## CP-084 — The Dockerfile — built, and what it cost

**This is no longer a sketch.** `Dockerfile` at the repo root is the authority and
carries the reasoning inline; what follows is what building it measured, and the four
places the original sketch here was wrong.

| Measurement | Value |
|---|---|
| Cold build (`--no-cache`, uv cache pruned) | **43 s** |
| Source-only rebuild (touch `src/agent_service/main.py`) | **3 s** |
| Final image (`docker images`) | **753 MB** |
| Final image, actual filesystem content (`du -sm /`) | **540 MiB** |
| `import agent_service.main` inside a running container | **628–650 ms** |
| First successful `/healthz`, from container start | **1.247 s** |

Where the size goes: `/app` (venv) 295 MiB, of which **263 is the bundled `claude`
binary** and ~32 is every other Python dependency; `/usr` 221 MiB, the `python:3.13-slim`
runtime plus git/ripgrep/curl and their dependency closure. The image is not
mysteriously large — half of it is the SDK's binary, which is irreducible.

Cold-build breakdown: apt layer 11.0 s, dependency layer 8.2 s (85 MB wheel download +
unpack of the 262 MiB binary — a fast link here, expect longer on a slow one), project
install 0.5 s, image export 15.4 s. On a source-only rebuild every step up to and
including `uv sync --no-install-project` is `CACHED`; **the 262 MiB dependency layer is
never re-downloaded or re-exported for a source change.** That split is the difference
between 3 s and 43 s.

### Four corrections to the sketch this section used to carry

1. **`uv` is bind-mounted into the build steps, not `COPY`ed in.** `COPY --from=…uv…`
   puts a **63.1 MB** static binary — useless at run time — into a layer permanently,
   and deleting it later cannot reclaim it. `RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv`
   makes it a build-time mount that never lands in a layer. Measured: **820 MB → 730 MB**
   (more than the 63 MB, because the layer's own overhead goes too), zero caching cost.
2. **`uv` is pinned to `0.11.27` and the base image is pinned by digest.** `:latest` on
   either makes the image non-reproducible; on the base it would also let glibc, git and
   ripgrep versions drift with no change to the file. The apt packages are deliberately
   *not* pinned — a rebuild should pick up Debian security updates, and the base digest
   is what gets bumped on purpose.
3. **`CMD` runs `uvicorn` from the venv, not `uv run uvicorn`.** `uv run` re-validates
   the environment on every start, which as a non-root user against a root-owned `/app`
   is at best wasted work and at worst a hard failure — and it inserts a process between
   PID 1 and uvicorn, which is exactly what the exec-form requirement exists to avoid.
   With `ENV PATH=/app/.venv/bin:$PATH`, `/proc/1/cmdline` reads
   `/app/.venv/bin/python /app/.venv/bin/uvicorn …` — **uvicorn is PID 1 itself**, no
   `/bin/sh` and no `uv` in between.
4. **`UV_COMPILE_BYTECODE=1`.** `/app` is root-owned and the service runs as `agent`, so
   the venv can *never* write a `.pyc`: without this the image shipped **0 `.pyc` files**
   and Python recompiled pydantic, pydantic_core, fastapi, starlette, mcp, cryptography,
   jsonschema and uvicorn in memory on **every start, forever**.

   | | `.pyc` files | `import agent_service.main` | image |
   |---|---|---|---|
   | `UV_COMPILE_BYTECODE=0` | 0 | 1569 / 1619 / 1636 / 1723 ms | 730 MB |
   | `UV_COMPILE_BYTECODE=1` | 755 | **628 / 647 / 650 ms** | **753 MB** |

   ~1.0 s off every start for +23 MB (+3.2 %), and the time becomes *stable* rather than
   varying by 150 ms — which matters because it sets the floor for the healthcheck's
   `start_period` and for the no-credentials fail-fast timing.

The `git config --system --add safe.directory '*'` line stays, and it is the **only**
git setting baked in — `core.filemode` was removed and now travels as `GIT_CONFIG_*`
from compose, for the reason in §3 (CP-082).

Notes on the choices:

- **`--workers 1` is mandatory, not a default.** The multi-turn session registry
  holds live `ClaudeSDKClient` objects in process memory. A second worker would
  route follow-up requests to a process that has never heard of the session.
- **`--host 0.0.0.0` inside the container is correct** — the container's own
  network namespace. Exposure is controlled by the *host-side* port binding in
  compose (below), not here.
- **exec-form `CMD`** so the process receives `SIGTERM` directly. Shell form would
  put `/bin/sh` at PID 1, swallow the signal, and skip the lifespan shutdown that
  disconnects live sessions. **Measured** — see
  Shutdown, signals and reaping (CP-088): the
  signal arrives, the lifespan runs, and `close_all()` demonstrably kills the CLI
  subprocesses. But `--timeout-graceful-shutdown 30` and the compose stop grace
  interact badly, and that combination **was measured failing** — read that
  section before changing either number.
- **Non-root** is straightforward on a Windows host (bind-mount ownership is
  synthesized regardless of UID). On a **Linux host**, mounted files keep their
  real UID and a mismatch causes permission errors — there, either match the host
  UID via a build arg or run with `--user "$(id -u):$(id -g)"`.

## CP-085 — The compose file — as shipped

**Also no longer a sketch.** `compose.yaml` at the repo root is the authority; every
line below was measured and the file carries the reasoning at the setting. The shape:

```yaml
services:
  agent-service:
    build: .
    init: true                       # reaps ORPHANS, not the agent subprocess — measured
    ports:
      - "127.0.0.1:8000:8000"        # localhost only — see "Security posture"
    volumes:
      - ${WORKSPACE_HOST_PATH:?set WORKSPACE_HOST_PATH in .env}:/workspace
      - ${REFERENCE_HOST_PATH:?set REFERENCE_HOST_PATH in .env}:/reference/${REFERENCE_NAME:-reference}:ro
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      AGENT_SERVICE_WORKSPACE_DIR: /workspace
      AGENT_SERVICE_REFERENCE_DIRS: '["/reference/${REFERENCE_NAME:-reference}"]'
      AGENT_SERVICE_LOG_LEVEL: ${AGENT_SERVICE_LOG_LEVEL:-INFO}
      AGENT_SERVICE_REQUIRE_CREDENTIALS: ${AGENT_SERVICE_REQUIRE_CREDENTIALS:-true}
      GIT_AUTHOR_NAME: ${GIT_AUTHOR_NAME:-agent-service}
      GIT_AUTHOR_EMAIL: ${GIT_AUTHOR_EMAIL:-agent-service@localhost}
      GIT_COMMITTER_NAME: ${GIT_COMMITTER_NAME:-agent-service}
      GIT_COMMITTER_EMAIL: ${GIT_COMMITTER_EMAIL:-agent-service@localhost}
      GIT_CONFIG_COUNT: "2"                        # host-dependent — see §3
      GIT_CONFIG_KEY_0: core.autocrlf
      GIT_CONFIG_VALUE_0: ${GIT_AUTOCRLF:-true}
      GIT_CONFIG_KEY_1: core.filemode
      GIT_CONFIG_VALUE_1: ${GIT_FILEMODE:-false}
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
    stop_grace_period: 100s          # = 30s drain + 60s close_all() budget + 10s margin
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
      start_interval: 1s
    restart: "no"                    # fail visibly; see "Boot without credentials"
```

Key points, and the four places this differed from the sketch it replaces:

- **`127.0.0.1:8000:8000`, not `8000:8000`.** See Security posture (CP-081)
  for why this is the most important line in the file, and for the interface-by-interface
  measurement.
- **`init: true` — keep it, but the stated reason was wrong.** The claim used to be
  "every multi-turn session spawns a Claude Code subprocess; without an init process
  at PID 1 those become zombies and accumulate". **Measured: they do not.** The CLI
  subprocess is a direct child of the uvicorn process and asyncio reaps it either
  way (observed in `Z` state for ~21 ms before its parent collected it) — **0 zombies
  with `init: false` and 0 with `init: true`**, over 6 sessions created and deleted in
  each. What `init: true` actually buys is reaping **orphans**: 3 grandchildren whose
  parent exited first left **3 permanent zombies at ppid 1** under `init: false` and
  **none** under `init: true`. That is precisely what the agent's `Bash` tool produces
  when it backgrounds anything. Right setting, wrong reason.
  Numbers in Shutdown, signals and reaping (CP-088).
- **`security_opt` + `cap_drop` were not in the sketch and cost nothing.** Added after
  the image was found to inherit 11 setuid/setgid binaries. Measured: nothing broke,
  including the SDK's subprocess spawn — see
  Security posture (CP-081).
- **The required-variable form `${VAR:?…}` was not in the sketch.** With it, a missing
  mount path is a named error rather than a mount of something unintended:
  `required variable WORKSPACE_HOST_PATH is missing a value: set WORKSPACE_HOST_PATH in .env`.
  The cost is real and is an open item below: it fires on **every** compose subcommand,
  including `ps` and `logs`.
- **`REFERENCE_NAME` is one variable feeding two places** — the mount target and the
  `add_dirs` entry — because they must match exactly and a drift between them fails
  silently. Deriving both from one variable makes that mistake unrepresentable.
- **`environment:` with explicit keys, never `env_file:`.** Compose reads `.env` for
  *interpolation*, but only the listed keys cross into the container. Anything else in
  the operator's `.env` stays on the host. A boundary property, not a style choice.
- **`${WORKSPACE_HOST_PATH}`** comes from a `.env` beside the compose file. On
  Windows use forward slashes (`C:/Users/you/src/some-repo`) — backslashes are
  eaten by compose's interpolation.
- **Mount the repository root**, not a subdirectory. Mounting `repo/src` leaves
  `.git` outside the container and every git command fails with *"not a git
  repository"*.
- **The healthcheck uses `127.0.0.1`, not `localhost`** — the sketch used `localhost`,
  and uvicorn binds `0.0.0.0` (IPv4 only) while `localhost` can resolve to `::1` first
  inside this image. `start_period: 15s` and `start_interval: 1s` were sized against
  measurement: see The healthcheck (CP-086).

### `:ro` is a kernel boundary, not a convention — measured (Task 3)

This is the claim the whole security argument rests on, and on a Windows host it is not
academic: **Docker Desktop's 9p/drvfs translation synthesizes mode `0777` on every
file**, so the permission bits claim world-writable and the write still fails.

```
$ ls -la /reference/acme-api
drwxrwxrwx 1 root root  512 Jul 28 01:21 .
-rwxrwxrwx 1 root root   26 Jul 28 01:21 REFERENCE.md      <- 0777, owned by root
$ stat mode /reference/acme-api  ->  0o40777
```

If `:ro` were advisory, or if anything in the stack were relying on ownership or
permission bits, every one of these would have succeeded. All of them failed at the
kernel, as the same error, from three different callers:

| Route | Result |
|---|---|
| `echo nope > /reference/…/evil.txt` | `sh: cannot create …: Read-only file system` (rc 2) |
| `mkdir /reference/…/evildir` | `cannot create directory …: Read-only file system` (rc 1) |
| `rm -f /reference/…/REFERENCE.md` | `cannot remove …: Read-only file system` (rc 1) |
| `touch /reference/…/REFERENCE.md` | `cannot touch …: Read-only file system` (rc 1) |
| Python `open(path, "w")` | `OSError(30, 'Read-only file system')` — **errno 30 = EROFS** |
| Python `os.mkdir(...)` | `errno=30 (EROFS)` |
| Python `os.open(existing, O_WRONLY)` | `errno=30 (EROFS)` |

`os.access("/reference/acme-api", os.W_OK)` → `False`; `os.access("/workspace", os.W_OK)`
→ `True`. The mechanism is visible directly in `/proc/self/mountinfo`:

```
463 ... /scratchpad/ws  /workspace           rw,noatime - 9p ...
464 ... /scratchpad/ref /reference/acme-api  ro,noatime - 9p ...
                                             ^^
```

The writable side works and lands on the host: a shell redirect, a `mkdir` and a Python
`open(w)` under `/workspace` all succeeded and all appeared on the host with the
expected content, while the reference directory was byte-for-byte untouched.

**This is not an agent declining — it is `EROFS` from the kernel**, which is what makes
shipping `Write`/`Edit`/`Bash` enabled defensible. Whatever tool the model reaches for,
and whatever its intent, the syscall returns 30. Confirmed again at the model's own
level in the live run: see
the read-only mount as the agent experiences it (CP-089).

**One caveat, stated so it is not assumed away.** `:ro` protects the *mount*, not the
host: it stops writes through this path and nothing else, and it does not make a
directory safe to let the container **read**.

### Two-mount layout (Q8)

Two mounts with different modes, mapping onto two different SDK options:

| Mount | Mode | SDK field | Role |
|---|---|---|---|
| `/workspace` | read-write | `cwd` | Scratch working directory |
| `/reference/<name>` | read-only (`:ro`) | entry in `add_dirs` | Real repos to read, never modify |

**Mounting is not sufficient — three things must line up:**

1. **The volume**, with the correct mode (`:ro` on references).
2. **`AGENT_SERVICE_REFERENCE_DIRS`**, which becomes `ClaudeAgentOptions.add_dirs`.
   The SDK scopes file access to `cwd` plus `add_dirs`; a mounted-but-unlisted path
   is invisible to `Read`, `Glob`, and `Grep`. Symptom of getting this wrong: the
   agent reports the directory does not exist, even though `docker exec ls` shows
   the files.
3. **A description in the prompt** (see Q9). Even with both of the above correct,
   nothing tells the model the reference mount exists, so it will not look there.
   Symptom: the agent answers entirely from `/workspace` and never mentions the
   reference repo.

All three fail *silently and differently*. When a reference mount appears not to
work, check them in that order.

**All three verified aligned on the running container** (Task 3, no API call), which is
what turns the warning above into a check you can repeat:

```
AGENT_SERVICE_REFERENCE_DIRS = ["/reference/acme-api"]
mountinfo /reference paths   = ['/reference/acme-api']
settings.reference_dirs      = [PosixPath('/reference/acme-api')]
ClaudeAgentOptions.add_dirs  = ['/reference/acme-api']
ClaudeAgentOptions.cwd       = /workspace
add_dirs == mounts ?           True
```

and requirement 3 — the part that tells the model the mount exists at all —
`workspace_description()` renders:

```
Directories available to you:
- /workspace - your working directory, read-write.
- /reference/acme-api - read-only reference copy. You may read and search it; you cannot modify it.
```

`GET /v1/capabilities` from the host reports the same thing back, alongside the two
lines that make this layout load-bearing: `permission_enforcement = none` and `Bash` in
`default_allowed_tools`.

> **One residual, unverified in the failing direction.** `Settings._resolve_references`
> calls `.resolve()`, so a reference path that traversed a symlink inside the container
> would arrive in `add_dirs` *resolved* and no longer string-equal to the mount target.
> It does not here — both are the literal `/reference/acme-api` — and it would still be
> a working path; the `==` check above is simply the thing that would go false first if
> reference paths ever stopped being literal. Not measured.

Add reference repos by repeating the volume line and extending the JSON list:

```yaml
      - ${API_REPO_PATH}:/reference/acme-api:ro
      - ${WEB_REPO_PATH}:/reference/acme-web:ro
```
```
AGENT_SERVICE_REFERENCE_DIRS='["/reference/acme-api","/reference/acme-web"]'
```

**Read-only git is partial — UNVERIFIED.** The reasoning is that `git status` writes
index metadata, so refs and object-store operations should fail outright while `log`,
`show` and `diff` against committed state should work. **Nothing in Plan 4 tested git
on a `:ro` mount**: Task 5 measured git only on the read-write `/workspace`, and Task 3
measured `EROFS` on ordinary file operations, not on git. Treat this paragraph as a
hypothesis. If a reference repo needs full git behaviour, mount a second *writable*
clone rather than dropping `:ro`.

## CP-086 — Boot without credentials — measured

**This is the first place to look when the compose service will not stay up.**

The service refuses to boot when no Anthropic credential is configured
(`config.verify_credentials`, follow-up item 8). In a container that is a deliberate,
visible, terminal failure. Measured with the shipped `compose.yaml`, an empty
`ANTHROPIC_API_KEY` and `AGENT_SERVICE_REQUIRE_CREDENTIALS` left at its default:

```
$ docker compose ps -a
NAME                 STATUS
t6-agent-service-1   Exited (3) 3 seconds ago

State=exited  ExitCode=3  OOMKilled=false  RestartCount=0  Health=unhealthy
start -> exit: 0.93 s
```

- **Exit code 3**, which is uvicorn's `STARTUP_FAILURE`, not a crash or a signal.
- The log ends with the whole `verify_credentials` message, which names
  `ANTHROPIC_API_KEY`, the three cloud-provider alternatives, the fact that a `.env`
  is resolved relative to `main.py` and not the working directory, and the escape
  hatch `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`.
- **No port is bound.** `netstat` shows nothing on 8000 and a host `curl` gets
  `Failed to connect to 127.0.0.1 port 8000`. The listener never opens because the
  lifespan raises before uvicorn starts serving.

### How the failure reaches you depends on how you started it

| Command | Exit code | What you see |
|---|---|---|
| `docker compose up` (foreground) | **3** | the message, then the shell gets 3 |
| `docker compose up -d --wait` | **1** | `container t6-agent-service-1 exited (3)` |
| `docker compose up -d` | **0** | `Started` — **and nothing else.** The trap |

Plain `docker compose up -d` reports success for a container that is already dead. Use
`--wait` in anything scripted; it is the only detached form that fails.

### The restart policy: `restart: "no"`, stated explicitly

Measured with `restart: unless-stopped` and no credentials, over ~40 s:

```
RestartCount=9      Status oscillating between `restarting` and `running`
171 log lines       the 17-line boot-failure traceback, once per boot
```

Docker's backoff never gives up, so that continues indefinitely, and `docker compose
ps` intermittently shows the container as `running`. The one message an operator needs
scrolls past nine times instead of sitting at the end of a stopped container's log.

`restart: "no"` gives **one start, one message, `Exited (3)`**. It is Docker's default,
and it is written out anyway: the default is invisible, an operator cannot distinguish
"deliberately no restart" from "nobody considered it", and the obvious-looking edit
(`restart: unless-stopped`, which most compose files carry) reintroduces exactly the
loop above.

**The cost, accepted:** a genuine mid-life crash also stays down instead of
self-healing. That was never really available here — `SessionRegistry` holds live
`ClaudeSDKClient` objects in process memory, so a restart loses every session and the
caller's session IDs 404 afterwards. A restart policy would make the container look
healthy while silently discarding state. Put supervision outside the compose file,
where it can alert.

### The healthcheck, and what it does *not* check

With a credential present the container reaches `healthy` on the first check, about
2 s after start (`start_period: 15s`, `start_interval: 1s`), and `docker compose up -d
--wait` returns 0:

```
STATUS: Up 2 seconds (healthy)   PORTS: 127.0.0.1:8000->8000/tcp
healthcheck output: {"status":"ok","credentials_configured":true,"workspace_dir":"/workspace"}
```

**`/healthz` distinguishes "up" from "credentials configured", and the healthcheck
only reads the first.** With `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` and no key:

```
Health=healthy
{"status":"ok","credentials_configured":false,"workspace_dir":"/workspace"}
```

Container **healthy**, credentials **absent**. That is correct and deliberate — the
boot gate is a boot gate, and `verify_credentials` is not re-checked per request
because a transient blip would otherwise take down the very route whose job is to
report one. But it means **a credential that disappears after boot does not turn the
container unhealthy**. If you want to alert on that, alert on the
`credentials_configured` field, not on container health.

## CP-087 — Logging — configured at the entrypoint, measured in the container

**Before this, the service was silent about everything it does in the background.**
Nothing under `src/` configured logging at all, and uvicorn does not do it for you:
its `LOGGING_CONFIG` names only the `uvicorn*` loggers and never touches the root
logger. Records from `agent_service.*` therefore propagated to an unhandled root and
met Python's *last-resort* handler, which emits `WARNING` and above to stderr and
**drops everything below it**. Fourteen log calls across three modules, and the two
most operationally useful of them — both `INFO` — went nowhere:

- `reaper: closed N idle session(s) past the Ns TTL`, which is the only report of
  what the background reaper did (the count used to be computed and discarded);
- `close_all: swept N session(s) ...`, the shutdown summary that was made
  unconditional precisely so a clean sweep and a sweep that never ran would stop
  being indistinguishable.

Task 6 confirmed the consequence by searching a real shutdown's `docker compose logs`
for `swept` and `close_all`: **zero matches.**

`main.configure_logging()` now runs at the entrypoint — beside `load_dotenv`, and
deliberately **not** inside `create_app`, which the test suite calls directly dozens
of times per run. It is one `logging.basicConfig` call:

```python
logging.basicConfig(
    level=level,                       # AGENT_SERVICE_LOG_LEVEL, default INFO
    format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
```

`basicConfig` and not `dictConfig`: it adds a root handler only when root has none,
so it defers to any configuration that already exists, whereas
`logging.config.dictConfig` closes every handler in the process on its way past —
including uvicorn's. Nothing here touches the `uvicorn` logger, which carries
`propagate=False`, so **uvicorn's lines are not duplicated**; stderr is chosen for the
same reason uvicorn's own default handler uses it, so the two sources interleave in
the order they were written.

**Measured** — same container, `AGENT_SERVICE_SESSION_IDLE_TTL_S=5` and
`SESSION_REAPER_INTERVAL_S=3` so the reaper fires inside a test rather than after
1800 s, a session created and abandoned, two more created and then
`docker compose stop`:

```
agent-service-1  | INFO:     Application startup complete.
agent-service-1  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
agent-service-1  | 2026-07-28 03:59:37.049 INFO     [claude_agent_sdk._internal.transport.subprocess_cli] Using bundled Claude Code CLI: /app/.venv/lib/python3.13/site-packages/claude_agent_sdk/_bundled/claude
agent-service-1  | INFO:     172.20.0.1:51528 - "POST /v1/sessions HTTP/1.1" 201 Created
agent-service-1  | 2026-07-28 03:59:45.745 INFO     [agent_service.registry] reaper: closed 1 idle session(s) past the 5s TTL
...
agent-service-1  | INFO:     Waiting for application shutdown.
agent-service-1  | 2026-07-28 03:59:59.919 INFO     [agent_service.registry] close_all: swept 2 session(s) in 1.045s of a 60.0s budget: 2 closed cleanly, 0 killed, 0 neither
agent-service-1  | INFO:     Application shutdown complete.
agent-service-1  | INFO:     Finished server process [7]
```

Both lines are in `docker compose logs`, in the shipped image, at the default level.
Exit code 143.

**What else appears, and what does not.** Over that whole run the log was 20 lines.
Every non-uvicorn line came from exactly two loggers: `agent_service.registry` (2) and
`claude_agent_sdk._internal.transport.subprocess_cli` (3, all the same *"Using bundled
Claude Code CLI: …"*, which is the SDK's only `INFO`). **No credential, prompt, tool
input or model output reaches the log at the default level** — grepped for `sk-ant`,
`api[_-]?key`, `authorization`, `bearer` and the workspace's canary string: 0 hits.
Note that this is a property of `INFO`, not a redaction: `AGENT_SERVICE_LOG_LEVEL=DEBUG`
turns on the SDK's and anyio's debug output, which is verbose and has **not** been
audited for what it prints. Treat `DEBUG` as a debugging tool, not a production level.

**A third logger appears when a request fails: `agent_service.api`.** It was silent
for the run above because nothing failed. The acceptance run's transient, *unlogged*
500 on `GET /v1/sessions/{sid}` is why it now exists. What it emits, and only this:

| Condition | Level | Carries |
| --- | --- | --- |
| An exception `errors.to_problem` cannot classify — its fallthrough 500 | `ERROR` | Route, session id, exception class name, **and the traceback** |
| A *classified* fault: 502 (agent process failed or garbled) or 500 (CLI binary missing) | `WARNING` | Route, session id, exception class name. No traceback — errors.py already named the condition |
| Every 4xx (404, 409, 429, 400) **and 504** | *nothing* | These are ordinary API answers, already visible in the access line. A 504 is a budget this service set expiring — the budget working, not a fault |

The message is built from the route, the session id and `type(exc).__name__` — never
`str(exc)`, never the prompt, never the request body. The `ERROR` branch's traceback
carries the exception's own message, which is its purpose, and no frame locals
(`logging.Formatter.formatException` is `traceback` output, not a variable dump).
Pinned by `tests/test_api_logging.py`, including a canary test asserting that no
prompt and no `sk-ant-` credential reaches the log.

## CP-088 — Shutdown, signals and reaping — measured

Everything in this section is measurement, not inference. Method: the compose stack
(so `stop_grace_period` actually applies — `docker run` would not have), a bogus
`ANTHROPIC_API_KEY`, and `/proc/*/stat` polled at 20–50 ms from inside the container
(`ps` is not in the image). **A bogus key still spawns a real CLI subprocess** — the
binary starts and only fails when it first calls the API — so every process fact
below cost $0.00. A turn genuinely in flight was obtained for free by pointing
`ANTHROPIC_BASE_URL` at a black-hole listener inside the container: the CLI connects,
emits its `system/init` frame, and blocks. Session status `running`, SSE request in
flight, subprocess alive.

**An idle service proves nothing here.** With zero sessions the container stops in
~1.1 s under any grace period at all. Every result below therefore has a live session.

### 1. `SIGTERM` reaches uvicorn and the lifespan runs — TRUE

Exec-form `CMD` works. Under `init: true` PID 1 is `docker-init` with uvicorn as its
direct child, and the signal still arrives. On a clean stop the log shows the full
lifespan shutdown and the container exits **143** (128 + SIGTERM), not 137.

### 2. That shutdown calls `close_all()`, which disconnects live sessions — TRUE

The discriminator is the interval between uvicorn's `Waiting for application
shutdown.` and `Application shutdown complete.` — the lifespan's `finally`, i.e.
`stop_reaper()` + `close_all()`:

| Live sessions at `SIGTERM` | Lifespan shutdown took |
|---|---|
| 0 | **0.046 ms** |
| 1 (idle, connected) | **703 ms** |
| 3 (idle, connected) | **1578 ms** (~526 ms each) |
| 1 (wedged mid-turn) | **5.91 s** |
| 3 (wedged mid-turn) | **16.23 s** (~5.41 s each) |

Four orders of magnitude between 0 and 1 session, and linear in the session count —
`close_all()` is doing real per-session work and nothing else in that window is.

It is not merely *running*, it is **killing the subprocesses**. With three live
sessions the poller caught them dying one at a time, LIFO, inside that window, each
passing briefly through `Z` before its parent (uvicorn, PID 7 — *not* `docker-init`)
collected it:

```
01:35:05.517  SIGTERM -> "Shutting down"
01:35:05.618  "Waiting for application shutdown."   <- close_all() starts
01:35:06.159  claude pid 128 gone                   <- created last, closed first
01:35:06.667  claude pid  76 -> Z (ppid 7)
01:35:06.688  claude pid  76 reaped, 21 ms later
01:35:07.193  claude pid  25 -> Z
01:35:07.196  "Application shutdown complete." / "Finished server process [7]"
```

### 3. `init: true` reaps exited agent subprocesses — **FALSE as stated**

Same scenario run with `init: false` and `init: true`. `procdump` counts `Z` in
field 3 of `/proc/*/stat`:

| Scenario | `init: false` (uvicorn is PID 1) | `init: true` (docker-init is PID 1) |
|---|---|---|
| 6 sessions created + `DELETE`d (2 rounds × 3), i.e. 6 agent subprocesses | **0 zombies** | **0 zombies** |
| 3 orphaned grandchildren (parent exits first) | **3 zombies, permanent** — still there 10 s later, `ppid 1` | **0 zombies** |

The agent subprocess is a **direct child** of the uvicorn process, and Python's
asyncio machinery `waitpid()`s its own children. `init` is never involved. The
plan's claim, and the old note in the compose sketch, were both wrong.

**Keep `init: true` anyway**, for the case the second row measures: a grandchild
orphaned inside the container reparents to PID 1, and uvicorn's asyncio child
watcher only reaps PIDs it started — so an orphan is a *permanent* zombie without
an init. That is not hypothetical: `Bash` is in the default tool set, and anything
the agent backgrounds (`npm run dev &`, a stray `sleep`) becomes exactly this the
moment the CLI exits. Right setting, wrong reason.

### The defect this test found: `stop_grace_period: 35s` was not enough

Docker's stop grace has to cover **two sequential budgets**, and only the first is
what `--timeout-graceful-shutdown` bounds:

1. uvicorn's **request drain** — it waits for in-flight requests, and an SSE turn is
   an in-flight request. Bounded by `--timeout-graceful-shutdown` (30 s in the `CMD`).
2. **then** the lifespan shutdown, i.e. `close_all()`. Docker's grace covers this too,
   but nothing in uvicorn bounds it: it is up to `timeout_s` (default 600 s) per
   session, sequentially, for up to `max_sessions` (8).

With 30 s + 35 s those do not fit. Measured, with one turn in flight:

```
01:38:02.736  SIGTERM
01:38:32.835  "Cancel 1 running task(s), timeout graceful shutdown exceeded"   <- 30.1 s of drain
01:38:32.835  "Waiting for application shutdown."                              <- close_all() starts
              ... no "Application shutdown complete." ever ...
01:38:37.734  SIGKILL                                                          <- 35.0 s, ExitCode 137
```

`close_all()` got 4.9 s of the 5.9 s it needed and was killed mid-sweep; the CLI
subprocess was still alive 70 ms before the kill. **Exit 137 at exactly the grace
period is the signature** — this is precisely the failure the exec-form `CMD`
requirement exists to prevent, reintroduced by a stop grace that was sized against
`--timeout-graceful-shutdown` alone.

Two things this rules out as "just a wedged-API artefact": the same 30 s drain
happened when the fake endpoint went away entirely (the CLI retries), and it is not
specific to being wedged — *any* turn still running 30 s after `SIGTERM` gets there.

**Fix, measured: `stop_grace_period: 90s`.** Sized as drain (30 s) + `max_sessions` ×
worst measured per-session close (8 × 5.7 s ≈ 46 s) ≈ 76 s. Verified with the stock
`CMD` and a wedged turn: **36.73 s, ExitCode 143**, `Application shutdown complete.`
present.

Two alternatives were measured and rejected:

- `--timeout-graceful-shutdown 5` + `stop_grace_period: 35s` also exits cleanly
  (12.0 s, exit 143, and the poller caught the subprocess dying exactly as
  `close_all()` finished). Rejected because it cancels any turn still running 5 s
  after `SIGTERM`, costing the caller a result it would otherwise have got.
- Leaving 35 s and accepting the risk. Rejected: it fails on the ordinary case of a
  turn in flight, silently, as a `SIGKILL` that looks like a crash.

Note that 90 s was *sized*, not *guaranteed*: `close_all()` had no hard bound, so a
session whose close took its full `timeout_s` still blew through it. The bound
belongs in the application — see the next section, which is where it now lives.

### The follow-up: an aggregate bound, so the grace period is arithmetic

`stop_grace_period: 90s` covered the one-to-three-session case that was measured and
nothing more. Reproduced offline with N sessions closing at the per-session cost
measured above:

| Sessions × per-session close | `close_all()` |
|---|---|
| 0 | 0.000 s |
| 1 × 0.5 s | 0.506 s |
| 3 × 0.5 s | 1.523 s |
| 8 × 0.5 s | 4.043 s |
| 8 × 2.0 s | 16.085 s |
| **8 × 5.9 s** (the wedged cost) | **47.255 s** |

Exactly N × per-session cost, and that is the *benign* shape — a close that genuinely
hangs is bounded only by its own `timeout_s`, i.e. 8 × 600 s = 80 minutes. No grace
period covers that, so `SIGKILL` mid-`close_all()` (ExitCode 137, subprocess still
alive) was always reachable.

`close_all()` now runs under **one aggregate deadline**,
`AGENT_SERVICE_SHUTDOWN_BUDGET_S` (default **60 s**), in two phases:

1. **Clean closes**, until `budget − reserve` (60 − 5 = 55 s). Each close gets a
   *fair share* of what is left — `remaining ÷ sessions still to attempt` — so a full
   house of 8 gets 6.9 s each, comfortably above the 5.4–5.9 s a wedged session was
   measured to need, and one wedged session cannot eat the budget and cost the
   healthy ones their clean teardown.
2. **Force kills**, with the 5 s reserve. Anything not closed cleanly — out of time,
   raised, or never reached — gets `AgentSession.kill()`: `disconnect()` with no turn
   finalisation and no lock. A killed session is *not* deregistered; a kill is not a
   clean close, so `list()` keeps meaning "not known to have shut down cleanly".

And it says what it did, always — Task 4 found it logged **nothing** on success:

```
close_all: swept 3 session(s) in 0.000s of a 60.0s budget: 3 closed cleanly, 0 killed, 0 neither
close_all: swept 4 session(s) in 0.949s of a 2.0s budget: 1 closed cleanly, 3 killed, 0 neither (shutdown budget hit)
```

**So `stop_grace_period` is now derived, not measured:**

```
stop_grace_period  =  30 s  (--timeout-graceful-shutdown, the request drain)
                   +  60 s  (AGENT_SERVICE_SHUTDOWN_BUDGET_S, close_all())
                   +  10 s  (margin: uvicorn's own teardown and process exit,
                             ~1.5 s in the measurement above)
                   = 100 s
```

`tests/test_config.py::test_the_compose_grace_period_follows_the_shutdown_budget`
reads all three numbers out of `compose.yaml`, the `Dockerfile` and `config.py` and
fails if that arithmetic stops holding — so neither number can be changed without
the other being seen. Raising `shutdown_budget_s` without raising the grace period
is a test failure, not a `SIGKILL` in production six months later.

### The budget, measured in a container (Task 6)

Everything above about the aggregate bound was measured **in process**, against fakes.
Its author flagged that the end-to-end container number had not been run. It has now.

Four sessions on the shipped `compose.yaml`, **two of them with a turn genuinely in
flight** (black hole: `ANTHROPIC_BASE_URL` → a TCP listener inside the container that
accepts and never answers, so the CLI emits its real `system/init` frame and blocks;
`GET /v1/sessions` reports two `running`, two `idle`). Four `_bundled/claude`
subprocesses, all `ppid 7` (uvicorn). Then `docker compose stop`:

```
03:43:15.872  SIGTERM
03:43:45.971  ERROR: Cancel 2 running task(s), timeout graceful shutdown exceeded   <- 30.10 s drain
03:43:45.971  INFO:  Waiting for application shutdown.                              <- close_all() starts
03:43:58.265  INFO:  Application shutdown complete.                                 <- close_all() took 12.29 s
03:43:58.265  INFO:  Finished server process [7]
03:43:58.274  exit

              42.40 s wall      ExitCode=143      OOMKilled=false
```

**Exit 143, not 137**, at 42.4 s against a 100 s grace — 57.6 s of headroom.
`close_all()` used **12.29 s of its 60 s budget** and did not hit it.

Subprocess evidence, from a 50 ms `/proc` poller writing into the bind mount so the
samples survive the container. Deaths are **LIFO**, which is `close_all()`'s order and
not something a container teardown would produce:

| Wall clock | Since `close_all()` started | Claude pids alive |
|---|---|---|
| 03:43:45.97 | — | 216, 160, 104, 48 |
| 03:43:46.62 | 0.65 s | 160, 104, 48 &nbsp;&nbsp;*(216 = last created, idle)* |
| 03:43:47.24 | 1.27 s | 104, 48 &nbsp;&nbsp;*(160, idle)* |
| 03:43:52.78 | 6.81 s | 48 &nbsp;&nbsp;*(104 — **wedged mid-turn**, +5.54 s)* |
| ≤ 03:43:58.27 | ≤ 12.29 s | none *(48 — **wedged mid-turn**)* |

The two idle sessions closed in ~0.6 s each and the two wedged ones in ~5.5 s each,
matching the 5.4–5.9 s measured earlier — the budget's fair-share arithmetic is sized
against the right number. **Zero `Z`-state processes in any of the 1081 samples.**

One honesty note, the same one Task 4 recorded: `docker exec` processes are killed with
the container, so the poller's last sample is 03:43:58.218 — 47 ms before
`Application shutdown complete.` — with pid 48 still alive. Three of the four deaths
are therefore *directly observed inside* the `close_all()` window; the fourth is
bounded to the final 47 ms of it, i.e. before uvicorn printed `Finished server
process`. No subprocess outlived the sweep.

**What this did not verify.** Four sessions, not a full house of eight, and the two
wedged closes each finished well inside their fair share — so the force-kill phase
never ran and `AgentSession.kill()` remains unexercised in a container.

### Verified evidence that a clean stop is what the grace period buys

The clearest single measurement. One live session mid-turn, SSE client hangs up
12.55 s after `SIGTERM`:

```
01:42:16.567  SIGTERM
01:42:29.116  SSE client disconnects -> the in-flight request ends -> drain over
01:42:29.215  "Waiting for application shutdown."
01:42:29.839  "Application shutdown complete."   <- close_all(), 624 ms
              total 14.28 s wall, ExitCode 143
```

14.28 s. Docker's **default** 10 s grace would have `SIGKILL`ed this container 2.6 s
before uvicorn even reached the lifespan. That is what `stop_grace_period` is for,
and it is the thing an idle-service test can never show.

---

## CP-089 — End to end, live, in the container — measured (Task 7)

The first time the whole stack was driven the way a user would drive it: shipped
`compose.yaml`, a real `ANTHROPIC_API_KEY`, the two real mounts, everything over HTTP
on `127.0.0.1:8000`. **One session, three turns, $0.13946.**

Method: `/workspace` and `/reference/orbital-ref` each held one file containing a
**canary token generated at test time** — `WS-BC9760E0AE10` and `REF-FFBC94B1C85C`,
random hex the model cannot have seen. A turn that reports the token read the mount;
a turn that answers from context cannot produce it.

### The session

| | | wall | `turn_cost_usd` | cumulative `total_cost_usd` |
|---|---|---|---|---|
| `POST /v1/sessions` | 201, subprocess up | 1.6 s | — | 0.0 |
| **Turn 1**, `POST …/messages` (blocking) | read `PROJECT_NOTES.md` from `/workspace` | 8.9 s | **0.10502** | 0.10502 |
| **Turn 2**, `POST …/messages/stream` (SSE) | read `/reference/…` and try twice to write to it | 11.4 s | **0.03444** | 0.13946 |
| **Turn 3**, SSE + `POST …/interrupt` | five sequential `sleep 5` Bash calls, interrupted | 4.9 s | **0.0** | 0.13946 |
| `GET`, then `DELETE /v1/sessions/{id}` | 200 then 204, list empty afterwards | — | — | 0.13946 |

28.7 s wall for the whole thing. `total_cost_usd` is **cumulative per connection**
(spike S6), so the session's spend is the **last** value, 0.13946 — not the sum of the
column beside it, which coincides here only because there was one connection.

**Turn 1 read the mount.** It answered `'WS-BC9760E0AE10'` — exactly the token, nothing
else — with `Read` as the only tool used and `is_error: false`.

**The interrupt fired on a genuinely running turn**: `{"interrupted": true, "status":
"running"}`, and the turn's summary carried `interrupted: true`, `is_error: true`,
`subtype: "error_during_execution"`, `terminal_reason: "aborted_streaming"` — the
documented shape, where `interrupted` is the only field that separates an interrupt
from a failure.

### The read-only mount, as the *agent* experiences it

Task 3 measured the kernel refusing writes with `EROFS` from a shell redirect, a Python
`open()` and `mkdir`. This is what the model does with that. Asked to append a line to
`/reference/orbital-ref/API_CONTRACT.md` using both the `Edit` tool and a shell
redirect, it tried both, and reported both verbatim:

```
<tool_use Edit {"file_path": "/reference/orbital-ref/API_CONTRACT.md", ...}>
<tool_result "EROFS: read-only file system, open
              '/reference/orbital-ref/API_CONTRACT.md.tmp.31.1651357559ea'">

<tool_use Bash {"command": "echo 'agent was here' >> /reference/orbital-ref/API_CONTRACT.md 2>&1"}>
<tool_result "Exit code 1\n/bin/bash: line 1:
              /reference/orbital-ref/API_CONTRACT.md: Read-only file system">
```

and then said so in its answer, unprompted and accurately: *"Append attempts — both
failed, since `/reference/orbital-ref` is read-only."* It did **not** refuse in advance,
and it did **not** report a success it had not achieved. The host file is
byte-identical afterwards (132 bytes, original mtime).

**One thing to know before you read that error in a log.** `Edit` writes through a
temporary file and renames, so its `EROFS` names
`API_CONTRACT.md.tmp.31.1651357559ea` — a path that does not exist and never will.
The `Bash` message is the legible one. Do not go looking for the `.tmp.` file.

### Resource usage during the run

`docker stats`, 2 s sampling, one session:

| | mem (cgroup, incl. page cache) | pids | CPU |
|---|---|---|---|
| Idle, just booted | **59.3 MiB** | 3 | 0.2 % |
| One live session, mid-turn | **355–368 MiB** | **20–21** | 2.4–10.9 %, one sample at **63.4 %** |
| After `DELETE`, subprocess gone | **243–247 MiB** | 3 | 0.2 % |

Block I/O read 296 MB, which is the 262 MiB bundled binary being paged in; that is
almost certainly why memory does not return to 59 MiB after the session is deleted —
cgroup accounting includes page cache. Treat **~110 MiB and ~17 pids as the marginal
cost of a session**, on top of a ~250 MiB warm baseline. At the shipped
`max_sessions: 8` that projects to roughly **1.1 GiB of session memory plus baseline**,
which no compose `mem_limit` currently bounds. Network I/O for the whole run was
481 kB in / 1.09 MB out.

Image 753 MB. Warm `up -d --build --wait` to healthy: **3.5 s**. `stop` with no live
sessions: **3.4 s**, exit **143**.

### Two things worth knowing before you size a budget

**1. The first turn on a session costs ~3x the second.** $0.105 then $0.034, for
turns of comparable size (one file read each, the second doing strictly more work).
`GET /v1/sessions/{id}` shows why: `context_usage` reports **System tools 20,682
tokens**, plus 14,970 deferred and 1,495 for skills. Every session pays for that
preamble on its first turn and gets it cached afterwards. So a per-session
`max_budget_usd` sized from steady-state turn costs will be tripped by the first turn,
and a workload of many short-lived sessions pays the preamble every time. Restricting
`default_allowed_tools` does not shrink it — `allowed_tools` governs permission, not
what the CLI loads.

**2. An interrupted turn is billed to nobody, and `max_budget_usd` cannot see it.**
Turn 3 produced an assistant message and started a `Bash` call before the interrupt
landed, and still reported `turn_cost_usd: 0.0` with `total_cost_usd` unchanged.
Follow-up measurement (`spike/probe_interrupt_cost.py`) settled how far that goes: the
cost is **lost, not deferred**, and the budget is **blind**. `turn_cost_usd` now reports
`null` rather than `0.0` for such a turn, which is the most the service can honestly do.
See `max_budget_usd` is blind to interrupted turns (CP-090).

## CP-090 — `max_budget_usd` is blind to interrupted turns — measured

**This is a safety limitation, not a reporting one, and it cannot be fixed inside this
service.** A caller who can interrupt turns can spend without limit under any
`max_budget_usd`, and nothing in the API shows it happening.

`max_budget_usd` is passed straight into `ClaudeAgentOptions` (`options.py`) and
enforced **inside the CLI**, against the same cumulative figure the `ResultMessage`
reports as `total_cost_usd`. Three live connections, `spike/probe_interrupt_cost.py`:

**Part C — the decisive run.** One connection, `max_budget_usd = 0.05`. Eight
consecutive turns, each started and then interrupted after 8 s of streamed output,
followed by ordinary turns until the budget tripped:

| Phase | Turns | Reported cumulative after | `limit_hit` |
|---|---|---|---|
| Start-then-interrupt | 8 | **$0.000649** (all of it the Haiku sidecar; the Sonnet key never appears) | `null` throughout |
| Ordinary turns | 1–5 | $0.0112 → $0.0489, ~$0.0095 each | `null` |
| Ordinary turn 6 | 1 | **$0.0585** | **`"budget"`**, `terminal_reason: budget_exhausted`, `subtype: error_max_budget_usd` |

The trip on turn 6 is the positive control: the mechanism was live on that connection
the whole time. It simply never saw the eight interrupted turns. Sixty-four seconds of
streamed inference moved the accumulator by $0.000649 — and the same eight turns grew
the conversation prefix from ~24.6k to **29,135 tokens**, every one of which later turns
paid cache-*read* on. Work nothing is recorded as having created is being billed as
input from then on.

**Part A — lost, not deferred.** One connection: normal → interrupted → normal.

| Turn | cumulative | `turn_cost_usd` | own `usage` | `model_usage` (Sonnet) |
|---|---|---|---|---|
| 1 normal | $0.0928215 | $0.0928215 | in 2 / out 4 / cache-write 24,578 | cost $0.0922335 |
| 2 interrupted (8.0 s, 2 assistant messages) | **$0.0928215** (unmoved) | ~~0.0~~ → **`null`** | **all zero**, `iterations: []` | **unchanged** — still turn 1's |
| 3 normal | $0.1024236 | $0.0096021 | in 2 / out 4 / write 568 / read 24,687 | cost $0.1018356 |

Turn 3's delta of $0.0096021 is *exactly* its own usage priced at published Sonnet 5
rates — 568 × $3.75/M + 24,687 × $0.30/M + 2 × $3/M + 4 × $15/M — to seven decimal
places. Nothing from turn 2 is folded in. In Part C, where the connection's *first* turn
was interrupted, `model_usage` had **no Sonnet key at all**: the model that did the work
is simply absent.

**Consequences, in order of how expensive they are to learn the hard way:**

1. `max_budget_usd` does not bound spend. Budget at the account or organisation level.
2. `SessionRecord.total_cost_usd` is a **floor**, not a figure. Do not bill from it.
3. `model_usage` is **cumulative for the connection** while `usage` is per-turn — summing
   `model_usage` across turns multiplies the real number by roughly the turn count.
4. `usage` reads all-zero on any non-`success` result, including a budget stop. Zeros
   mean "the SDK reported nothing", never "nothing happened".

**Should the service add its own defence?** It was considered and **deliberately not
built.** The obvious shape — track cumulative spend per session and refuse further turns
past a ceiling — would have to track *something*, and the only figures available are the
ones just shown to be blind to exactly the turns that need catching. It would enforce the
same budget the CLI already enforces, with the same hole, while reading as a second,
independent control that had closed it. A defence that is only correct when it is not
needed is worse than none, because it invites the belief that spend is bounded. The
honest options are an account-level budget, or an upstream rate limit on
`POST /v1/sessions/{id}/interrupt` and turn starts (a *request* cap, which is
enforceable, rather than a *spend* cap, which is not). If the SDK ever reports usage on
an aborted turn, revisit this — the guard in `AgentSession._record_turn` is where the
condition is already detected.

## CP-091 — Network egress — unrestricted, deliberately, for now

The container needs outbound HTTPS to `api.anthropic.com`; Task 3 confirmed it is
reachable with all capabilities dropped (HTTP 405 to an unauthenticated `GET` —
connectivity proven, nothing billed). `WebSearch` and `WebFetch` are in
`default_allowed_tools`, so as shipped the container needs, and has, **general outbound
network access**.

Restricting egress to the Anthropic API is a reasonable hardening step and is
**deliberately out of scope for Plan 4** rather than overlooked. Two things to carry
into it whenever it is done:

- It implicitly disables `WebSearch` and `WebFetch`, so drop them from
  `default_allowed_tools` at the same time — otherwise the tools stay advertised and
  fail confusingly instead of being cleanly absent.
- It does not change the trust model on its own. `Bash` plus `python` plus a writable
  `/workspace` is already arbitrary code execution inside the boundary; egress
  restriction limits where the results can *go*, which is worth having and is not the
  same as containment.

---

## CP-092 — Persistence under a real agent — measured (plan-03 Task 9)

Three live runs against `claude-sonnet-5` with a real Postgres 17. Total spend
for the whole task was about **$0.20**, against a $0.30 budget.

### A. Three turns, one interrupted — the stored rows tell the truth

| Turn | `interrupted` | `outcome_missing` | `cost_usd` | `result_text` |
|---|---|---|---|---|
| 1 | false | false | **0.092297** | `ONE` |
| 2 | false | false | **0.008268** | `TWO` |
| 3 (interrupted mid-stream) | **true** | false | **NULL** | `''` |

11 `events` rows, 21 `transcript_entries` (the A.2 mirror), one `runs` row per
turn including the interrupted one.

**Two things this confirms that were previously only argued:**

1. **`cost_usd` is NULL for the interrupted turn, not `0.0`.** The stored column
   says "nobody can say" rather than claiming the turn was free —
   `runner.unattributed_abort` survives the whole path from `ResultMessage` to
   Postgres.
2. **`sessions.total_cost_usd` is demonstrably a FLOOR.** It landed at
   **0.100565**, which is exactly `0.092297 + 0.008268`. The interrupted turn ran
   real inference for ~2 s and contributed **nothing**. Anyone building a spend
   report on that column will under-report by however much interrupted work costs.

Also visible: **the first turn cost 11x the second** (0.0923 vs 0.0083), which is
the same first-turn premium plan-04 measured, larger here because the second
prompt was trivial.

### B. Resume across a restart, with the local transcript deleted

The point of A.2, and the only way to prove it is a store test rather than a file
test: after the first session closed, its `CLAUDE_CONFIG_DIR` was **deleted
outright (9 paths)** before a new service object resumed by `sdk_session_id`.

The agent still answered `8675309` — a number it had only been told before the
restart. That could only have been materialized out of Postgres.

### C. Killing Postgres mid-turn

`docker stop` on the database **during** an active turn:

- The turn **completed normally**: 4 events, outcome recorded, not timed out.
- Writer stats afterwards: `written=1`, `failed_batches=5`,
  `dropped_stream_event=0`, `dropped_over_hard_cap=0`.

So the failure mode is exactly the designed one — batches are discarded and
counted, the queue never grows past its soft mark at this volume, and **the agent
never notices**. Nothing dropped at the queue level because five batches' worth of
records is nowhere near `soft_capacity` (10,000).

### D. `CLAUDE_CONFIG_DIR` growth — measured

The CLI writes its own transcript regardless of the mirror. Measured on disk
after these runs:

| Session | Config dir total | Its `.jsonl` transcript |
|---|---|---|
| 3 turns (one interrupted) | **49,510 B** | **18,501 B** |
| 1 turn | **42,426 B** | **11,418 B** |

So roughly **40 KB of fixed overhead per project directory** plus **~3.5 KB per
turn** of transcript, for trivial prompts. Real prompts with tool use will be
larger, and this is a floor, not a projection.

`compose.yaml` therefore sets `CLAUDE_CONFIG_DIR=/tmp/claude-config`: the fixed
overhead is per project directory rather than per session, so it does not grow
without bound, but it has no reason to sit in the container's writable layer when
the durable copy is in Postgres. **Not yet decided:** whether `/tmp` warrants an
explicit `tmpfs` size bound — that wants a long-running deployment rather than
three test sessions.

---

## CP-093 — What is still unverified

Everything else in this document is a measurement. These are not, and are marked here
so no one has to reconstruct which is which:

| Claim | Status |
|---|---|
| A read-only root filesystem works with a `tmpfs` at `HOME` | **Untested.** The requirement that `HOME` be writable is measured; that particular mitigation is not |
| Git on a **`:ro`** mount is "partially" functional | **Untested.** Task 5 measured git on `/workspace` (read-write) only |
| `AgentSession.kill()` — `close_all()`'s force-kill phase | **Never reached in a container.** Tasks 6 and 7 both stopped short of it: four sessions, not a full house of eight, and every close finished inside its fair share |
| **A `SessionStore.load()` that TIMES OUT** | **Not simulated.** The bound is wired (`load_timeout_ms`, set inside `registry.create()`'s own 30s open timeout so the inner bound can fire first), and a `load()` returning `None` is tested — but a genuinely slow adapter has not been driven end to end |
| **Persistence at high volume** | **Only measured at low volume.** Task 9 above confirms the outage path, but five failed batches is nowhere near `soft_capacity` (10,000), so the *drop* policy has still only been exercised against a synthetic queue. Whether real load ever reaches the soft mark is unknown |
| **A `tmpfs` size bound for `CLAUDE_CONFIG_DIR`** | **Undecided.** Growth is now measured (~40 KB fixed + ~3.5 KB/turn for trivial prompts), but whether `/tmp` needs an explicit cap wants a long-running deployment |
| `close_all()` with the full `max_sessions: 8` | **Not run.** The 8-session numbers are an in-process reproduction against fakes |
| Two concurrent `disconnect()` calls on one `ClaudeSDKClient` | **Unmeasured.** Reachable only on the hung-cancellation path: `close_all()` cancels a close that overran its slice, that close's `except CancelledError` handler makes a best-effort `disconnect()`, and phase 2 then offers the same session `kill()` — which also disconnects. Bounded by `_kill_all`'s `asyncio.wait`, and the common case is a no-op via `kill()`'s `status == "closed"` guard, but the SDK's tolerance of a concurrent second `disconnect()` is not something this plan measured. **Recorded, not fixed:** the only alternative to letting `kill()` proceed is a subprocess that outlives the container |
| ~~Whether `max_budget_usd` itself is blind to interrupted work~~ | **Settled — it is blind.** Measured with a positive control: 8 start-then-interrupt turns moved the CLI's accumulator $0.000649 against a $0.05 budget that never tripped; 6 ordinary turns on the same connection tripped it at $0.0585. See `max_budget_usd` is blind to interrupted turns (CP-090) |
| A Linux or WSL2 host end to end | **Not run.** Both host-dependent git defaults, the synthesized `0777` mount permissions and the UID-mismatch note are Windows/Docker-Desktop observations; the Linux values are reasoned, not measured |
| A resolved-symlink reference path | **Not measured** — see the residual note under Q8 |
| Cost, timing and memory figures | **Single observations**, one host, one run. Unambiguous in kind (the canary tokens settle "did it read the mount"), not distributions |

---

## CP-094 — Environment variable reference

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | SDK authentication. **Required** — without it the container exits 3 at boot and binds no port; see Boot without credentials (CP-086) |
| `AGENT_SERVICE_REQUIRE_CREDENTIALS` | Default `true`. `false` starts the service without a credential, for docs-only use or tests that must not spend. `/healthz` then reports `credentials_configured: false` while the container is `healthy` |
| `AGENT_SERVICE_LOG_LEVEL` | Default `INFO`, case-insensitive. The level `main.configure_logging()` applies to the root logger at the entrypoint. `WARNING` silences the reaper and `close_all()` summaries again; `DEBUG` also enables the SDK's debug output, which is unaudited — see Logging (CP-087) |
| `AGENT_SERVICE_WORKSPACE_DIR` | Agent `cwd`; set to the writable mount path (`/workspace`) |
| `AGENT_SERVICE_REFERENCE_DIRS` | JSON list of read-only mount paths → SDK `add_dirs`. Must match the `:ro` volumes exactly |
| `AGENT_SERVICE_*` | All other settings from `config.py` (see `design.md`) |
| `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` | Commit authorship. Required — measured: dropping either pair fails `git commit` with exit 128 |
| `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` | Commit committer. Required, same measurement |
| `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n` | Arbitrary git config from the environment, at the highest precedence git has (above a mounted `.git/config`). `compose.yaml` sets **two** pairs: `core.autocrlf` and `core.filemode`. The count must equal the number of pairs — git silently ignores the rest |
| `GIT_AUTOCRLF` | Feeds `GIT_CONFIG_VALUE_0`. **`true` on a Windows host (default), `input` on Linux/WSL2.** Wrong value = the agent commits the whole repo's line endings — see §3 (CP-082) |
| `GIT_FILEMODE` | Feeds `GIT_CONFIG_VALUE_1`. **`false` on a Windows host (default), `true` on Linux/WSL2.** Wrong value = 66-of-66 phantom mode changes, or real ones hidden |
| `HOME` | Must be writable — bundled binary and session storage |
| `AGENT_SERVICE_DATABASE_URL` | Optional Postgres DSN. **Popped from the environment at startup** so the agent's `Bash` tool cannot read it — see `persistence.md` (CP-110) |
| `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY` | Alternative auth providers, if used instead of an API key |

---

## CP-095 — Open items this raises

- **Q8 — settled:** two mounts, writable `/workspace` + read-only `/reference/*`.
  Documented above.
- **Q9** in `open-questions.md`: how the mount layout gets
  described to the agent, since mounting alone does not make it visible to the
  model.
- **Postgres.** The compose sketch above omits the database service; the additions
  (service definition, healthcheck-gated `depends_on`, no published host port) are
  in `persistence.md` (CP-110) → Deployment additions. Q10 and Q11 cover
  the decisions.
- ~~**`core.autocrlf` on a Windows-host bind mount.**~~ **Closed.** Defaulted to
  `true` in `compose.yaml` via `GIT_AUTOCRLF`, with the Linux value documented at the
  setting, in `.env.compose.example` and in the table in
  §3 (CP-082). Verified end to end: an agent
  `git add -A && git commit` on a mounted Git-for-Windows clone now touches **1 file
  instead of 67**, and the host repo is byte-identical and `git status`-clean
  afterwards.
- ~~**`core.filemode` for a Linux- or WSL2-cloned repo.**~~ **Closed.** Removed from
  the image (system scope could never win against `.git/config`) and moved to
  `GIT_CONFIG_KEY_1`/`VALUE_1` via `GIT_FILEMODE`, which does. Measured beating a
  repo-scope `filemode = true`: 0 mode changes, against 66 without it.
- ~~**The `close_all()` summary line does not reach the container log.**~~ **Closed.**
  It was wider than the one line: three modules made 14 log calls and nothing under
  `src/` configured logging at all, so the reaper's report was invisible too.
  `main.configure_logging()` now runs at the entrypoint, level from
  `AGENT_SERVICE_LOG_LEVEL` (default `INFO`). Both lines verified present in
  `docker compose logs` in the shipped image, with no uvicorn duplication and nothing
  sensitive at the default level — see
  Logging (CP-087).
- ~~**An interrupted turn reports `turn_cost_usd: 0.0` and does not move
  `total_cost_usd`.**~~ **Settled, and it was worse than the open item said.** The
  Task 8 assessment left one half unverified — whether the CLI's own `max_budget_usd`
  accumulator was a *different* accounting that might still catch interrupted work. It
  is not, and it does not. Measured live over three connections with
  `spike/probe_interrupt_cost.py`: eight start-then-interrupt turns advanced the
  accumulator by **$0.000649** against a **$0.05** budget that never tripped, while six
  ordinary turns on the same connection tripped it at $0.0585. The cost is **lost, not
  deferred** — the next completed turn's delta is exactly its own usage priced.

  **Fixed as far as it can be:** `turn_cost_usd` now reports **`null`** rather than
  `0.0` for an aborted turn whose cumulative did not move — "nobody can say" instead of
  "this turn was free". The blindness itself is enforced inside the CLI and is **not
  fixable here**; it is documented as a security limitation in `README.md` and in
  `max_budget_usd` is blind to interrupted turns (CP-090),
  which also records why a service-side spend guard was considered and deliberately not
  built.
- **The first turn on a session costs ~3x the second, and `allowed_tools` cannot shrink
  it.** $0.105 vs $0.034 measured live (Task 7) for turns of comparable size, because of
  a ~37k-token preamble — `context_usage` reports **System tools 20,682 tokens**, plus
  14,970 deferred and 1,495 for skills. Consequences for anyone sizing a budget: a
  per-session `max_budget_usd` derived from steady-state turn costs **will be tripped by
  turn one**; a workload of many short-lived sessions pays the preamble every time; and
  narrowing `default_allowed_tools` does *not* reduce it, because `allowed_tools` governs
  permission, not what the CLI loads. This is the largest gap measured between what the
  service's configuration *looks* like it controls and what it actually controls. No fix
  is available at this layer.
- **Nothing bounds container memory.** A session costs ~110 MiB and ~17 pids on top of
  a ~250 MiB warm baseline (Task 7), and `max_sessions: 8` therefore projects to
  ~1.1 GiB of session memory with no `mem_limit` or `pids_limit` in `compose.yaml`.
  The cap is a session cap, not a memory cap.
- **`docker compose` fails on *every* subcommand until the mount paths are set,
  including read-only ones.** `WORKSPACE_HOST_PATH` and `REFERENCE_HOST_PATH` use the
  `${VAR:?…}` form, so a bare `docker compose ps` or `logs` in a fresh clone errors
  with `required variable WORKSPACE_HOST_PATH is missing a value` before showing
  anything. The message is the right message; it just also fires when you only wanted
  to look. The fix is the documented one — `cat .env.compose.example >> .env` and fill
  the two paths in — which is easy to miss because `.env` already exists and works for
  a local, non-container run.
- **`AGENT_SERVICE_REQUIRE_CREDENTIALS=false` is a foot-gun with a healthy
  healthcheck.** A container started that way is `healthy`, serves, accepts sessions,
  and fails on the first turn. `/healthz` says `credentials_configured: false` and
  nothing else does. See Boot without credentials (CP-086).
- Whether to grant the agent access to remotes at all (SSH agent forwarding or a
  scoped token). Currently: no. Revisit only with a concrete need — a token in the
  container is reachable by any command the agent runs.
- Whether `/workspace` should be a named Docker volume rather than a host bind
  mount. A named volume is faster on Windows and makes the scratch nature explicit,
  at the cost of being harder to inspect from the host. **Now quantified:** the
  overlay filesystem was 223–561x faster than the bind mount for `git status` on a
  5000-file repo — see §4 (CP-082).
- ~~**`close_all()` has no aggregate time bound.**~~ **Closed.** It was
  `max_sessions` × `timeout_s` in the worst case (8 × 600 s), which no
  `stop_grace_period` could cover, and 90 s was sized against the *measured*
  per-session close rather than that worst case. `close_all()` now runs under one
  aggregate deadline (`AGENT_SERVICE_SHUTDOWN_BUDGET_S`, 60 s) with a reserved
  force-kill phase, and reports what it closed, killed and could not — see
  the follow-up above (CP-088).
  `stop_grace_period: 100s` now follows from that budget arithmetically and is
  pinned by a test that reads both files.
- **A killed session's turn is never finalised.** Phase 2 disconnects without
  interrupting the turn or waiting for the session lock, which is deliberate (there
  is no time left to wait) but is a shape `disconnect()` has never been measured
  against — S5 measured it at a clean turn boundary only. It is reachable only when
  a session has already failed to close inside its fair share of the budget, i.e.
  only when the alternative is a leaked subprocess.

---

# E. The design, as decided

## CP-096 — the design in one paragraph

**Date:** 2026-07-26
**Status:** Implemented through Plan 2 (one-shot runs + multi-turn sessions).
Persistence (Plan 3) and the container (Plan 4) are still design only.

## CP-097 — Purpose

A FastAPI service that exposes `claude_agent_sdk` over HTTP with an auto-generated
OpenAPI spec. The first goal is **learning**: the service should make everything the
Agent SDK does visible — the agent loop, tool calls, tool results, thinking, session
state, cost and token usage. Task-specific workflows come later; this build is a
generic runner.

Non-goals for this build: authentication of API callers, persistent storage of
sessions or transcripts, multi-process deployment, rate limiting.

## CP-098 — Background: what the SDK gives us

Confirmed against <https://code.claude.com/docs/en/agent-sdk/python> and
`/overview` on 2026-07-26.

- PyPI package `claude-agent-sdk`, requires Python >= 3.10. It bundles a native
  Claude Code binary per platform — no separate CLI or Node install.
- Auth: `ANTHROPIC_API_KEY` env var. Third-party provider flags exist
  (`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`,
  `CLAUDE_CODE_USE_ANTHROPIC_AWS`). claude.ai login is not permitted for
  SDK-powered products.
- Two entry points:
  - `query(prompt=..., options=ClaudeAgentOptions(...)) -> AsyncIterator[Message]`
    — one-shot, fresh context each call.
  - `ClaudeSDKClient(options=...)` — persistent connection with `connect()`,
    `query()`, `receive_response()`, `interrupt()`, `set_permission_mode()`,
    `set_model()`, `disconnect()`.
- The message stream is the product: `SystemMessage(subtype="init")` (carries
  `session_id`), `AssistantMessage` with `TextBlock` / `ThinkingBlock` /
  `ToolUseBlock` content, `UserMessage` carrying tool results, and a terminating
  `ResultMessage`. With `include_partial_messages=True` the stream also yields
  `StreamEvent` objects for token-level deltas.
- Built-in tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch,
  Monitor, Agent (subagents), AskUserQuestion, plus notebook/todo/scheduling tools.

**Verified against the installed package** (0.2.128) rather than taken from the
docs — see `spike-findings.md` (CP-046). Corrections that matter:

- The message union has **six** members, not five: `RateLimitEvent` is also
  returned, carrying rate-limit status and reset timing.
- The content-block union has **six** members: the four above plus
  `ServerToolUseBlock` and `ServerToolResultBlock`.
- `ResultMessage` carries everything the response model needs, plus
  `permission_denials`, `model_usage` (per-model tokens, cache hits, `costUSD`),
  `terminal_reason`, and `api_error_status`.
- `session_id` is **not** uniform across messages — `UserMessage` has none, and
  `SystemMessage` carries it inside `data`. It is a run-level property.
- `ClaudeAgentOptions` also exposes an undocumented `sandbox` (OS-level sandboxing
  with network controls) — see Q12.

`serialization.py` still reads defensively, because the unions are wider than any
documentation page states and will keep moving.

## CP-099 — Architecture

`uv`-managed project, `src/` layout.

```
pyproject.toml
.env.example
README.md
src/agent_service/
  __init__.py
  config.py            # pydantic-settings: env-driven defaults and limits
  schemas.py           # pydantic request / response / event models
  serialization.py     # SDK dataclasses -> JSON-safe dicts
  options.py           # RunOptions (our model) -> ClaudeAgentOptions (SDK)
  policy.py            # write-confinement predicate + opt-in PreToolUse hook (not
                       # can_use_tool -- measured to never fire, see "Permission posture")
  runner.py            # one-shot runs via query()
  sessions.py          # one AgentSession: client, lock, turn draining, interrupt labelling
  registry.py          # the live session collection: cap, idle reaper, shutdown
  errors.py            # SDK exception -> HTTP problem mapping
  api.py               # FastAPI app, routers, lifespan
  main.py              # uvicorn entrypoint
  db/                  # optional persistence — see persistence.md
    engine.py          # async engine + sessionmaker, lifespan wiring
    models.py          # SQLAlchemy models (distinct from the API schemas)
    repository.py      # sole write path: start_run / finish_run / append_events
    writer.py          # background queue drain + batch insert
  migrations/          # alembic
tests/
  test_serialization.py
  test_options.py
  test_policy.py       # deny/allow decisions — pure functions, no API calls
  test_schemas.py
  test_session_schemas.py
  test_config.py
  test_errors.py
  test_runner.py
  test_sessions.py     # AgentSession: lock, residue, interrupt labelling, close()
  test_registry.py     # cap, reservation, reaper, shutdown
  test_api_query.py
  test_api_stream.py
  test_api_meta.py
  test_api_sessions.py
  test_live.py         # marked `live`, deselected by default
workspace/             # agent sandbox cwd, gitignored except .gitkeep
```

**Layering rule.** `runner.py`, `sessions.py`, `options.py`, and
`serialization.py` never import FastAPI. `api.py` never imports
`claude_agent_sdk` directly. This keeps the agent layer unit-testable without a
web server and reusable when task-specific workflows are added.

**Limits are two-valued (Q5).** Every guardrail has a default and a hard cap.
A request may set any value up to the cap; exceeding it is a **400 naming the
limit**, never a silent clamp — quietly running something cheaper than asked would
make results inexplicable. Whichever of budget, turns, or wall clock binds first
wins, so the response reports all three plus a `limit_hit` field naming which one
ended the run. A normal completion carries `terminal_reason: "completed"`, giving
a clean baseline to distinguish a limit stop from a crash.

**Persistence is optional and decoupled.** The agent layer depends on a narrow
`RunRecorder` protocol, not on SQLAlchemy. With `database_url` unset it gets a null
implementation and the service runs normally; tests use an in-memory one. The
database must never become a hard dependency of running an agent. Full design in
`persistence.md` (CP-110).

## CP-100 — Configuration (`config.py`)

Pydantic-settings, prefix `AGENT_SERVICE_`, `.env` supported.

Every row below is a real field on `Settings` and is settable as
`AGENT_SERVICE_<NAME>`. Three things that are **not** settings, and were listed
here as if they were, are described under the table instead.

| Setting | Default | Meaning |
|---|---|---|
| `workspace_dir` | `./workspace` | Writable sandbox root → SDK `cwd`; created at startup |
| `reference_dirs` | `[]` | Read-only reference paths → SDK `add_dirs`. See "Workspace layout" |
| `include_workspace_description` | `true` | Append the generated mount description to the system prompt (Q9) |
| `default_model` | `claude-sonnet-5` | Q7. Pinned explicitly — an unset model resolves to `claude-opus-5[1m]`, ~1.8× the cold-run cost. Overridable per request |
| `default_permission_mode` | `dontAsk` | Never blocks on a human |
| `default_allowed_tools` | full built-in list (below) | Overridable per request |
| `default_setting_sources` | `[]` | Do not load ambient `.claude/` or `~/.claude/` config |
| `permission_enforcement` | `none` | Opt-in in-process write confinement. `none`: container/mount is the only boundary. `hook`: a `PreToolUse` hook confines `Write`/`Edit`/`NotebookEdit` — measured to work. `can_use_tool` is not offered; measured to never fire (Task 11, `spike-findings.md`) |
| `default_max_turns` | `30` | Q5. Applied when the request says nothing |
| `max_allowed_turns` | `200` | Q5. Hard cap; a request above it is a 400 |
| `default_max_budget_usd` | `2.00` | Q5. ~20× the measured cold-run floor for `claude-sonnet-5`. **⚠️ Not a spend bound — see B1 below** |
| `max_allowed_budget_usd` | `10.00` | Q5. Hard cap on the *requested* value, not on actual spend |
| `default_request_timeout_s` | `600` | Q5. Wall clock per run |
| `max_allowed_timeout_s` | `1800` | Q5. Hard cap |
| `require_credentials` | `true` | Refuse to boot when no Anthropic credential is configured (follow-up item 8). Set `false` for docs-only use or a test harness; see "Concurrency and lifecycle" |
| `require_mounts` | `true` | Refuse to boot when `workspace_dir` is not on a mounted filesystem, or a `reference_dirs` entry does not exist. **On by default (Q14)** — the deployment that most needs the check is the one least likely to remember a flag. A plain checkout must set `AGENT_SERVICE_REQUIRE_MOUNTS=false`, because `./workspace` is an ordinary directory |
| `max_sessions` | `8` | Concurrent `ClaudeSDKClient` subprocesses |
| `session_idle_ttl_s` | `1800` | Idle sessions are closed by the reaper |
| `session_reaper_interval_s` | `60` | How often the reaper sweeps |
| `shutdown_budget_s` | `60.0` | Aggregate bound on `close_all()`, and therefore on the whole ASGI lifespan shutdown. `compose.yaml`'s `stop_grace_period` is derived from it. Before it existed a sequential unbounded sweep of 8 sessions was worth up to 80 minutes; 47.3 s measured at the per-session cost a container actually showed |
| `include_raw_events` | `true` | Include the untouched SDK payload as `AgentEvent.raw`. Overridable per request via `options.include_raw` |
| `auth_token` | `None` | Bearer credential required on `/v1`. **Unset = no authentication**, which is the documented single-operator posture; boot logs a WARNING and `auth_required` is published on `/healthz` and `/v1/capabilities`. Must be **per-instance**: a token this service holds is readable by the agent it runs |
| `require_auth` | `false` | Refuse to boot when `auth_token` is unset. Symmetric with `require_credentials`/`require_mounts` — for an operator who needs "authenticated" to be a fact rather than a hope |
| `agent_id` | `None` | **Read from `AGENT_ID`, not `AGENT_SERVICE_AGENT_ID`** — the name belongs to the consumer that injects it, like `ANTHROPIC_API_KEY`. Opaque, unvalidated, stamped on `sessions.agent_id` and `transcript_entries.agent_id` and published as `SessionRecord.agent_id`. Absent is a normal deployment: nullable column, no boot gate. Provenance only — this service enforces nothing with it, and it cannot be set by a caller |
| `allow_mcp_servers` | `true` | Whether `options.mcp_servers` is accepted. `false` makes such a request a **400**, never a silent drop. True by default because a stdio MCP server grants nothing `Bash` does not already grant; the switch exists for **attribution** — a stdio server starts with the session, before any prompt, and appears in no turn's events. Published as `Capabilities.allow_mcp_servers` |
| `default_strict_mcp_config` | `true` | Server default for `options.strict_mcp_config`. **Not the SDK's default of `false`**: the workspace is mounted from the host and writable by the agent, so a `.mcp.json` in it would otherwise add servers the caller never sent |
| `log_level` | `INFO` | The service's own logging. `WARNING` silences its reporting; `DEBUG` also turns on the SDK's and anyio's output, which is verbose and **not audited for what it prints** |
| `database_url` | `None` | Opt-in persistence. `postgresql://` and `postgres://` are rewritten to the asyncpg driver by `db.engine.normalize_url`; anything else is rejected loudly rather than silently selecting a sync driver inside the loop. **Popped from `os.environ` at startup** — see below |
| `session_store_load_timeout_ms` | `30000` | Bounds how long a `create()` with `resume` can hang on the A.2 store, not how long it tries before giving up gracefully. Pinned by `test_a_slow_store_fails_the_resume_rather_than_starting_fresh` |

Default allowed tools — the eight in `config.py`'s `DEFAULT_ALLOWED_TOOLS`:
`Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch`. (This list
previously also named `Monitor` and `Agent`; neither has ever been in
`config.py`. `allowed_tools` governs permission, not visibility, so the CLI
still advertises its full set — 31 tools in a live init payload — and the model
may attempt others and be denied.)

**Not settings, despite appearing in this table in earlier drafts:**

- **`ANTHROPIC_API_KEY`** is a plain environment variable, *not* an
  `AGENT_SERVICE_`-prefixed field on `Settings`, and it is deliberately not one:
  the agent subprocess reads it from the environment itself, so the service must
  leave it there rather than absorb it. `config.credentials_configured()` checks
  it (or `ANTHROPIC_AUTH_TOKEN`, or one of the `CLAUDE_CODE_USE_BEDROCK` /
  `_VERTEX` / `_FOUNDRY` provider flags). It is read by `GET /healthz` **and,
  since follow-up item 8, by the lifespan, which refuses to boot without one**
  — see "Concurrency and lifecycle" below. The `AGENT_SERVICE_`-prefixed field
  that governs that refusal, `require_credentials`, *is* a real `Settings`
  field; the credential itself still is not.
- **`always_disallowed_tools`** is a module-level constant
  (`config.ALWAYS_DISALLOWED_TOOLS = ["AskUserQuestion"]`), not a field.
  It is enforced on every request and is not overridable — including by
  environment: `Settings` sets `extra="ignore"`, so
  `AGENT_SERVICE_ALWAYS_DISALLOWED_TOOLS=` is accepted and silently discarded
  rather than rejected. Changing it means editing `config.py`.
- ~~**`database_url`** does not exist yet.~~ **Corrected (2026-07-31):** Plan 3
  shipped, and `database_url` *is* a real `Settings` field — now listed in the
  table above. One thing about it is unlike every other row: it is **popped from
  `os.environ` at startup**, in `get_settings()`. Not tidiness — the agent's
  subprocess inherits this process's environment and has `Bash`, so leaving it
  there hands the agent its own database credentials. `ANTHROPIC_API_KEY` cannot
  be hidden the same way, because the subprocess needs it (see the first bullet).

## CP-101 — Workspace layout

Settled in Q8. The container carries two kinds of mount, which map onto two
distinct `ClaudeAgentOptions` fields:

| Mount | Mode | SDK field | Role |
|---|---|---|---|
| `/workspace` | read-write | `cwd` | Where the agent works — writes, edits, commits |
| `/reference/<name>` | read-only | entry in `add_dirs` | Real code to read and search, never modify |

**`add_dirs` is NOT an access boundary — corrected by live testing.** The spec
previously claimed the SDK scopes file access to `cwd` plus `add_dirs`. It does
not. With `add_dirs=[]`, `permission_mode="dontAsk"` and `allowed_tools=["Read",
"Bash"]`, the agent successfully read a file outside `cwd` using *both* `Read` and
`cat` via `Bash`, with zero `permission_denials`
(`spike-findings.md` (CP-046) L3).

What follows from that:

- **`cwd` sets a starting directory, not a boundary.**
- **`add_dirs` is registration/discovery, not enforcement.** `options.py` still
  populates it from `reference_dirs` — it is good hygiene and may matter under
  other permission modes — but nothing may depend on it for confinement.
- **`allowed_tools` is per-tool, not per-path.** `["Read"]` approves *every* read
  at *any* path. `dontAsk` decides which tools may run, never which files they
  may touch.
- **The `:ro` mount and the container are the only real boundaries.**
  `workspace_subdir` validation is input hygiene, not confinement, and is
  described as such.
- **Running this service outside a container is unsafe.** With `Bash` enabled the
  agent can read anything the service process can read.

Whether `allowed_tools` accepts Claude Code's *scoped* rule syntax
(`Bash(git status:*)`, `Read(./src/**)`) is untested and would change this
materially — see Q13.

**`cwd` is never caller-selectable.** It must be writable, so it is always
`workspace_dir` (optionally a validated subdirectory via `workspace_subdir`).
Reference mounts are read-only and can never serve as `cwd`.

**The layout must be described to the agent in text.** Mounting a directory and
allow-listing it does not tell the model it exists; nothing in the prompt mentions
it. When `include_workspace_description` is true, `options.py` generates a short
block from the same configuration that produces `cwd` and `add_dirs` — so the
description cannot drift from reality — and appends it to whatever system prompt is
in effect:

```
/workspace — your working directory, read-write.
/reference/acme-api — read-only reference copy of the acme-api repository.
                      You may read and search it; you cannot modify it.
```

Suppressible per request, so the "agent ignores a mount it was never told about"
failure can be observed deliberately. Approach still open — see Q9.

**Read-only git is partial.** Git writes index metadata during `status` and fails
outright on anything touching refs or the object store. Read-side inspection of a
reference repo (`log`, `show`, `diff` against committed state) works; `status` may
warn or fail. If full git behaviour on a reference repo becomes necessary, add a
second *writable* clone rather than relaxing the `:ro` flag.

## CP-102 — Permission posture

**Corrected after Task 11's live verification — `can_use_tool` is NOT the policy
layer.** The design originally claimed it was, on the strength of L3 and L7
below. Both readings hold, but a further live result overturned the conclusion
drawn from them:

- **L3** — `allowed_tools=["Read"]` approves *every* read at *any* path. Neither
  `cwd` nor `add_dirs` constrains where a tool operates.
- **L7** — `allowed_tools=["Bash(git status:*)"]` did **not** restrict `Bash`; the
  agent also ran `git log`, with no denial recorded.

So `allowed_tools` answers "which capabilities exist", never "what may they do" —
that much still stands. The design then assumed `ClaudeAgentOptions.can_use_tool`
was the mechanism that filled the gap, because it is the only one that receives
the actual tool input and can rule on it per invocation. **Five live probes
(`spike/probe_permissions.py`, see `docs/spike-findings.md`, "Permission
enforcement — measured, not guessed") found it never actually runs, under any
configuration this service would use:**

- A whole-tool `allowed_tools` entry (`"Write"`, unscoped) auto-approves that
  tool before `can_use_tool` is ever consulted — confirmed by the SDK's own
  `CanUseToolShadowedWarning`, and reproducing the exact live bug Task 11 caught
  (a real write outside the workspace succeeded with `permission_denials: []`).
- When the tool is *not* in `allowed_tools` at all, the CLI denies the call
  outright, without consulting `can_use_tool` either — true under both
  `permission_mode="default"` and `"dontAsk"`.
- With a `PreToolUse` hook registered alongside it, `can_use_tool` still does not
  fire; only the hook does.

**The `PreToolUse` hook is the mechanism verified to work.** It fires despite a
whole-tool `allowed_tools` grant, and its `deny` decision genuinely blocks the
write and is recorded in `ResultMessage.permission_denials`. `policy.py` holds a
shared `_denial_reason` predicate that both the (now unused-by-default)
`can_use_tool` callback and the hook call, so the two cannot drift even though
only the hook is wired up:

```python
def _denial_reason(tool_name, input_data, root, base) -> str | None:
    if tool_name not in {"Write", "Edit", "NotebookEdit"}:
        return None
    target = Path(input_data.get("file_path", "")).resolve()
    if not target.is_relative_to(root):
        return "writes are confined to the workspace"
    return None
```

**In-process enforcement is opt-in and off by default (`Settings.
permission_enforcement`, default `"none"`).** We do not ship an in-process
control we cannot demonstrate works, and we do not ship one as a false sense of
depth when a container is the only thing actually holding. `"none"`: neither
`can_use_tool` nor a hook is wired; the container and its mount split
(`deployment.md`) are the only boundary — this is the accurate description of
what actually happens on a bare-metal run, not merely the safe default.
`"hook"`: the `PreToolUse` hook above is attached, confining `Write`/`Edit`/
`NotebookEdit` to the workspace. **This hook confines those three tools only —
`Bash` is enabled by default (`DEFAULT_ALLOWED_TOOLS`) and is NOT matched by
it, so a shell redirect (`echo x > /etc/foo`) bypasses it entirely; the
container is still the only real boundary against `Bash`.** `"can_use_tool"`
is **not offered** as a value
at all — offering a control measured to never fire would repeat the exact
mistake being corrected here. `GET /v1/capabilities` reports the resolved value
so an operator can see which mode is actually live without reading config.

`policy.py` has no FastAPI or SQLAlchemy imports and is tested directly
(`test_policy.py`, including parity tests that the callback and the hook agree
on every input).

### Declarative options, and what they are actually for

`permission_mode="dontAsk"` plus an explicit allowlist, rather than
`bypassPermissions`. Both permit the same tools in practice, but `dontAsk` denies
anything *not* named — so a newly added built-in tool or an MCP tool is denied by
default instead of silently allowed. The allowlist is a config value, so widening
or narrowing is a one-line change.

`AskUserQuestion` is always in `disallowed_tools`. There is no human on the other
end of an HTTP request; allowing it would hang the request until the timeout.

**`allowed_tools` does not hide tools — use `disallowed_tools` to remove them.**
The live init payload advertised all **31** built-in tools to the model even
though `allowed_tools` named three. The allowlist governs permission, not
visibility, so the model will attempt a non-allowlisted tool, spend a turn, and be
denied. `disallowed_tools` is what actually removes a capability. The real tool
list is far wider than the docs' ten — it includes `PowerShell`, `Task`,
`Monitor`, `ToolSearch`, `Workflow`, `EnterWorktree`, and the Cron/Task
scheduling family — so `default_allowed_tools` must be written against the
observed list, and `/v1/capabilities` should report it from a live init payload
rather than a hard-coded constant.

**Accepted risk, stated explicitly:** `Bash` is enabled by default. The agent can
run arbitrary shell commands with the service process's privileges. `workspace_dir`
sets the agent's starting directory; it is not a security boundary. Running this
service on a machine with sensitive data, or exposing it to untrusted callers,
requires narrowing `default_allowed_tools` (drop `Bash`, `Write`, `Edit`) or
running the service in a container. The README states this in a warning block.

`workspace_subdir` on a request is resolved against `workspace_dir` and rejected
with 400 if the resolved path escapes the root (`..`, absolute paths, symlinks).

## CP-103 — API

All routes under `/v1` except health. FastAPI generates `/openapi.json` and
`/docs` automatically; every request and response model is a pydantic model so the
generated schema is complete.

### Shared request model — `RunOptions`

Optional on every run endpoint; each field falls back to config when omitted:
`system_prompt` (string, or `{"type":"preset","preset":"claude_code","append":...}`),
`model`, `effort`, `allowed_tools`, `disallowed_tools`, `permission_mode`,
`max_turns`, `max_budget_usd`, `timeout_s`, `workspace_subdir`,
`setting_sources`, `include_partial_messages`, `include_raw`.

(As built there is no separate `thinking` field — extended thinking is driven by
`effort`.)

> **⚠️ `max_budget_usd` is not a spend bound.** It is enforced inside the CLI
> against an accumulator this service never sees, and **an interrupted turn moves
> that accumulator by nothing while still costing real money.** Measured (B1 in
> `spike-findings.md` (CP-046)): eight start-then-interrupt turns
> under a $0.05 budget moved it $0.000649 and never tripped, across 64 s of
> streamed inference; six ordinary turns on the same connection then tripped it as
> expected. So a start-then-interrupt loop can spend without limit.
>
> Treat `max_budget_usd` as a guard against a *runaway single turn*, not against a
> caller. Bound real spend at the account or organisation level, and rate-limit
> turn starts and `/v1/sessions/{sid}/interrupt` upstream if this service is
> exposed to anything.

`options.py` maps this to `ClaudeAgentOptions`, applying config defaults and
force-merging `always_disallowed_tools`.

### One-shot

| Method | Path | Behaviour |
|---|---|---|
| `POST` | `/v1/query` | Runs `query()` to completion. Returns `session_id`, final `result` text, `is_error`, `num_turns`, cost / usage / duration, and the **full list of normalized messages**. |
| `POST` | `/v1/query/stream` | Same body; SSE. One event per SDK message as it arrives. |

### Multi-turn

Backed by an in-process registry of `ClaudeSDKClient` instances. Each client owns a
subprocess, so the registry is capped and reaped.

| Method | Path | Behaviour |
|---|---|---|
| `POST` | `/v1/sessions` | Body: `{options: RunOptions, title?}`. Constructs and `connect()`s a client. 201 with a `SessionRecord`. 429 if `max_sessions` reached, 504 if `open()` exceeds `open_timeout_s`. |
| `GET` | `/v1/sessions` | List live sessions: id, status, created/last-used timestamps, turn count, cumulative cost. |
| `GET` | `/v1/sessions/{id}` | One session record, plus live `context_usage` fetched from the client. |
| `POST` | `/v1/sessions/{id}/messages` | Send a prompt, drain `receive_response()`, return the same payload shape as `POST /v1/query`. |
| `POST` | `/v1/sessions/{id}/messages/stream` | Same, as SSE — but it takes the turn's FIRST message before committing the response, so 404/409/504 stay real status codes and only failures from the second message onwards go in-band. This deliberately diverges from `/v1/query/stream`, which commits its 200 first and reports even a zero-message failure as `event: error`. |
| `POST` | `/v1/sessions/{id}/interrupt` | Calls `client.interrupt()`. Always 200 with `{interrupted, status}` — never 409: a turn can end between a client deciding to stop it and the request arriving, so "nothing to interrupt" is a routine outcome the body reports rather than an error. `interrupted` is not derivable from `status` (a turn abandoned mid-drain leaves the session `idle` and still issues a real control request). |
| `PATCH` | `/v1/sessions/{id}` | `permission_mode` and/or `model` via `set_permission_mode()` / `set_model()`. Omitted fields are not forwarded — a null model means "use the default" to the SDK. 409 if the session is closed, matching `POST .../messages`. |
| `DELETE` | `/v1/sessions/{id}` | `disconnect()` and drop from the registry. 204. A turn in flight is interrupted and given a bounded chance to end first. |

**The `{id}` in these paths is this service's own handle, not the SDK's.**
`SessionRecord.session_id` is the registry key (a uuid4 hex). The SDK's
conversation id is a separate value, reported as `session_id` on the
`RunResponse` a turn returns.

### Discovery

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/v1/capabilities` | Built-in tool names, permission modes, effort levels, and the resolved server defaults. A learning aid — makes the option space visible without reading the SDK source. **Also reports what the service *requires*** (2026-08-05): `credential_sources` / `provider_selectors` (the environment variables the boot gate accepts, kept as two lists because a selector is not a credential), `max_sessions` (the 429 cap, previously only in that error's prose), and the `require_credentials` / `require_mounts` boot gates. The principle: if a boot check can refuse to start the service, what it checked is worth publishing — a caller that provisions containers should not have to discover it from `exit 3`. |
| `GET` | `/healthz` | Liveness. Reports whether a credential is configured (does not call the API) and, since 0.6.0, whether the configured database is **usable** — probed against a real table per request, so it catches an unmigrated schema and not just an unreachable host. `status` stays `"ok"` when the database is broken: persistence is optional, the container healthcheck reads the status code, and an optional subsystem must not be able to restart a working service. Alert on `database_usable`, not on the code. |

## CP-104 — Data flow

```
HTTP request
  -> RunOptions (pydantic, validated)
  -> options.build(...) -> ClaudeAgentOptions
  -> runner.run() / session.send()      [async iteration over SDK messages]
       each SDK message -> serialization.normalize() -> AgentEvent (pydantic)
  -> blocking: collect into RunResponse   |  streaming: yield as SSE
```

### Normalized event shape

Every SDK message becomes one `AgentEvent`:

```json
{
  "seq": 3,
  "type": "assistant",
  "subtype": null,
  "content": [
    {"type": "text", "text": "I'll check the file."},
    {"type": "tool_use", "id": "toolu_...", "name": "Read",
     "input": {"file_path": "..."}}
  ],
  "raw": { }
}
```

`type` is one of `system`, `assistant`, `user`, `result`, `stream_event`,
`rate_limit`.

**No `session_id` on the event.** The spike found it is not uniformly available —
`UserMessage` has no such field and `SystemMessage` nests it under `data`. It is
captured once per run (from the init `SystemMessage`, confirmed by
`ResultMessage`) and returned at the response level.
`raw` carries the full dataclass-to-dict conversion so nothing is lost while
learning; a config flag can suppress it once the shapes are familiar.

`serialization.py` handles dataclasses, nested content blocks, `Path` objects, and
unknown/new types (falls back to `repr` under a `_unserializable` key rather than
raising). This module is where SDK version drift shows up first, so it is the most
heavily unit-tested.

### SSE format

`text/event-stream`, one JSON `AgentEvent` per `data:` line, with `event:` set to
the event type. A terminal `event: done` marks stream end; an `event: error`
carries a problem document if the run fails mid-stream. SSE responses cannot carry
a rich OpenAPI response schema, so the endpoint description embeds the `AgentEvent`
schema by reference and the models are registered so they appear in `/docs`.

## CP-105 — Concurrency and lifecycle

- One `asyncio.Lock` per session. A second concurrent message to the same session
  returns 409 rather than interleaving on one subprocess.
- A background reaper task disconnects sessions idle beyond `session_idle_ttl_s`.
- FastAPI `lifespan`: start the reaper on startup; cancel the reaper and
  `disconnect()` every live session on shutdown. The workspace dir is created
  eagerly too, but not by the lifespan — `Settings`' `workspace_dir` validator
  `mkdir(parents=True, exist_ok=True)`s it at config-load time.
- **Credentials ARE validated at startup, and the service refuses to boot
  without them** (follow-up item 8, user decision 2026-07-27). This bullet has
  now said all three things at different times, so state the history exactly: an
  early draft claimed the check existed when it did not; a later correction said
  it did not exist and would not be added; it now exists. `config.
  verify_credentials()` runs from the FastAPI lifespan *before* the reaper
  starts, and raises `MissingCredentials` when `credentials_configured()` is
  false. uvicorn's `Server.startup()` turns a failed lifespan into
  `sys.exit(STARTUP_FAILURE)`, so the process exits non-zero and a container
  restarts rather than serving requests it cannot fulfil.

  What this replaced: without credentials, `POST /v1/sessions` returned 201 and
  spawned a CLI subprocess that could not authenticate, so up to `max_sessions`
  (8) doomed sessions each held a cap slot until the reaper swept it at
  `session_idle_ttl_s` (1800s), and the failure surfaced on the first turn
  instead of at boot.

  **The accepted cost**, which is the reason this was deferred once: a
  credential blip at the wrong moment turns a restart into a crash-loop, and the
  service can no longer be started for docs-only use. The escape hatch is
  `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` (a real `Settings` field,
  `require_credentials`, defaulting to `True`), which the test suite itself runs
  on — so the hatch is exercised on every test run rather than merely offered.

  The gate is BOOT-ONLY and deliberately not re-checked per request:
  `GET /healthz` already reports `credentials_configured` live, and re-checking
  at request time would turn a transient blip into an outage on the one route
  whose job is to describe it. Credentials that disappear after a successful
  boot leave the process up and `/healthz` reporting `false`.
- `asyncio.timeout(timeout_s)` wraps every run and every session turn. On
  expiry both raise the same `RunTimeout` → 504. The multi-turn path does not
  interrupt from inside the timeout handler; it marks the turn abandoned, so the
  next `interrupt()` (or `close()`) is the thing that actually tells the
  subprocess to stop, and the next turn pre-drains whatever it produced
  meanwhile. `timed_out` is recorded on the internal `TurnResult` only — it is
  deliberately absent from `RunResponse`, since a timed-out turn never returns
  one.
- The registry is in-process. Running more than one worker breaks session affinity,
  so the README documents single-worker deployment for now.

## CP-106 — Error handling

`errors.py` maps SDK exceptions to RFC 7807 `application/problem+json`:

| Condition | Status |
|---|---|
| `CLINotFoundError` | 500 — bundled binary missing / unsupported platform |
| `ProcessError` | 502 — agent subprocess failed, includes exit code and stderr tail |
| `CLIJSONDecodeError` | 502 — malformed message from the agent process |
| Unknown session id | 404 |
| Session busy | 409 |
| Session closed (a turn or a `PATCH` against it) | 409 |
| `max_sessions` reached | 429 |
| Run or turn exceeded `timeout_s` | 504 |
| Session `open()` exceeded `open_timeout_s` | 504 |
| Path escaping `workspace_dir`, invalid options | 400 |

A `ResultMessage` with `is_error=True` is **not** an HTTP error — it is a
successful run whose agent reported failure. It returns 200 with `is_error: true`
in the body. Confusing the two would make agent-level failures indistinguishable
from transport failures.

Missing credentials **do** fail at startup, and are the one condition that is
not an HTTP status at all: the lifespan raises `MissingCredentials` and the
process exits non-zero before any route is served. It is deliberately absent
from `errors.py`'s mapping above, because it can only be raised at boot and a
problem-document entry would claim a status it can never produce. See
"Concurrency and lifecycle" above for the decision, its accepted cost and the
`AGENT_SERVICE_REQUIRE_CREDENTIALS=false` escape hatch. After a successful boot
nothing re-checks: `GET /healthz` reports `credentials_configured` live.

## CP-107 — Testing

- `pytest`, `pytest-asyncio`, `httpx.ASGITransport` — no live server needed.
- The agent layer is injected through a FastAPI dependency, so API tests use a fake
  runner that replays a canned message sequence. No API calls, no cost, fast.
- `test_serialization.py` covers every SDK message and content-block type,
  including an unknown-type fallback case.
- `test_options.py` asserts config defaults apply, per-request overrides win, and
  `always_disallowed_tools` cannot be overridden.
- `test_live.py` is marked `live` and deselected by default
  (`addopts = "-m 'not live'"`). Two cases, the canaries for SDK version drift:
  one real read-only query asserting a `ResultMessage` arrives (~$0.09), and a
  two-turn session asserting turn 2 answers from turn 1's context without
  re-reading the file (~$0.035 measured; an earlier "~$0.20" here was a 6x
  overstatement). "Without re-reading" is asserted as **zero `tool_use` blocks
  on turn 2**, not as the answer being correct — `Read` and `Glob` stay granted
  and the file stays in the workspace, so a context-less agent would simply
  read it again and any assertion on the answer alone would pass.

## CP-108 — Verification

Definition of done for the implementation:

1. `uv run pytest` passes with no live tests.
2. `uv run uvicorn agent_service.main:app` starts; `/docs` renders every endpoint
   with complete schemas.
3. `POST /v1/query` with `{"prompt": "List the files here"}` returns a result plus
   a message list containing at least one `tool_use` event.
4. `POST /v1/query/stream` emits events incrementally, not one buffered blob.
5. A multi-turn session demonstrates retained context: turn 1 establishes a fact,
   turn 2 references it without restating it.
6. `uv run pytest -m live` passes against the real API.

## CP-109 — Deferred

Task-specific workflow endpoints, custom `@tool` / `create_sdk_mcp_server`
examples, hooks, subagent configuration, persistent session storage, caller
authentication, and multi-worker deployment. The layering above is chosen so each
can be added without reshaping the existing modules.

---

# F. Persistence, and the agent's own database access

## CP-110 — the two halves of the persistence question

Companion to `design.md` (CP-096) and `deployment.md` (CP-078).

"Give the agent service a Postgres database" turns out to be **two unrelated
requirements** that happen to share a server. They differ in who connects, what
credentials are used, what can go wrong, and which mechanism is appropriate.
Building them as one thing is the main mistake available here.

| | A. Service persistence | B. Agent database access |
|---|---|---|
| Who connects | The FastAPI service | The agent, mid-run |
| Purpose | Store runs, events, sessions, cost | Let the agent query data as a capability |
| Mechanism | Direct SQLAlchemy writes in the service layer | MCP server or a custom `@tool` |
| Credentials | Read-write, owns its schema | Read-only, tightly scoped, **different role** |
| Model influence | None — the agent never sees it | The agent chooses the queries |
| Needed for "persist messages" | **Yes** | No |

The stated goal — persisting messages — is entirely (A). (B) is a separate,
optional capability. They are documented together only because both terminate at
the same Postgres instance, and because of the credential-leak interaction in the
final section, which is easy to miss and hard to undo.

> **Correction (2026-07-29).** An earlier version of this file treated "persist
> messages" as one job with one mechanism. It is **two jobs**, and Part A covers
> both — they are separated below as **A.1** and **A.2**. The original text
> described only A.1, which stores a queryable transcript but **cannot give the
> agent conversation continuity**: the CLI cannot resume from normalized
> `AgentEvent` rows. A.2 is the SDK's own `session_store` seam, which was
> available all along and is not mentioned anywhere in the original draft. The
> omission is recorded rather than quietly patched, because "we already persist
> messages" would otherwise read as covering a case it does not.

| | A.1 Observability transcript | A.2 Conversation continuity |
|---|---|---|
| Question answered | "What happened, and what did it cost?" | "Does the agent remember?" |
| Consumer | The service, a console, you | The CLI subprocess |
| Shape | Normalized `AgentEvent` — **you own it** | The CLI's internal JSONL — **opaque** |
| Mechanism | Service-layer writes (below) | SDK `ClaudeAgentOptions.session_store` |
| Queryable | Yes | **No — never parse it** |

Both land in the same Postgres under the same read-write role. They are not
alternatives; each is useless for the other's job.

---

## CP-111 — Part A — Service-side persistence

Two halves, per the correction above: **A.1** (this section through *Module layout
addition*) is the normalized, queryable transcript. **A.2** (*Conversation
continuity via the SDK session store*, below) is what makes the agent remember.

## CP-112 — A.1 — Why not hooks

The obvious-looking route is a `PostToolUse` hook that writes to the database. It
is the wrong layer, for four reasons:

1. **Hooks see a fraction of the stream.** Tool hooks fire on tool events. They do
   not see assistant text, thinking blocks, or the terminating `ResultMessage` —
   which is where cost, token usage, duration, and turn count live. Persisting from
   hooks means persisting the least interesting part.
2. **The service layer already sees everything.** `runner.py` and `sessions.py`
   iterate the full message stream and normalize each message into an `AgentEvent`.
   That loop is already the complete, correct vantage point; a hook would be a
   second, worse one.
3. **Hooks run inside the agent loop.** A slow or failing insert adds latency to
   the agent's turn, and hook errors perturb the run itself. Persistence should not
   be able to break the thing it is observing.
4. **Hooks are per-run configuration.** Persistence is a property of the service.

**Rule:** persist from the service layer. Use hooks only for things that must
happen *inside* the loop — chiefly policy enforcement, which can veto a tool call.
See Part C.

## CP-113 — Schema

Three tables. Design goals: reconstruct any run exactly, aggregate cost, and query
tool usage across runs.

> **Correction (plan-03 Task 2).** The `sessions.id` comment below said
> "SDK-assigned session_id". **It is not, and one-shot queries do not get a row.**
> The stored key is the **service-side `sid`** that `registry.py` mints as
> `uuid.uuid4().hex`, because that is what `SessionRecord.session_id` publishes
> (`api.py:130`) and therefore the only id any client has ever seen; because it
> exists at creation time, while the SDK's does not arrive until the first
> `SystemMessage` of the first turn; and because it is stable, while the SDK's
> can move under fork/resume. The SDK's is kept alongside as `sdk_session_id`,
> nullable and indexed — it is the join key to A.2's `transcript_entries` and
> the value the resume path needs.
>
> A one-shot `POST /v1/query` is never registered, so it has no `sid` and gets
> **no `sessions` row**; its `runs` row carries `session_id = NULL`. The SDK does
> assign it a session id, but this service never exposes that as a session, so a
> row here would be unreachable from any API path.
>
> The live schema is `src/agent_service/db/models.py`; the SQL below is kept as
> the design sketch it was. Pinned by
> `tests/test_db_models.py::test_the_session_key_is_the_service_sid_not_the_sdks`.

```sql
-- One row per multi-turn session (one-shot queries also get a row,
-- since the SDK assigns a session_id to those too).
CREATE TABLE sessions (
    id                TEXT PRIMARY KEY,          -- SDK-assigned session_id
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL,             -- active | closed | errored
    options           JSONB NOT NULL,            -- resolved ClaudeAgentOptions
    total_cost_usd    NUMERIC(12,6) NOT NULL DEFAULT 0,
    total_turns       INTEGER NOT NULL DEFAULT 0
);

-- One row per prompt submitted: a POST /v1/query, or one turn of a session.
CREATE TABLE runs (
    id                UUID PRIMARY KEY,
    session_id        TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    prompt            TEXT NOT NULL,
    options           JSONB NOT NULL,
    result_text       TEXT,
    result_subtype    TEXT,                      -- success | error_during_execution | ...
    is_error          BOOLEAN,
    num_turns         INTEGER,
    cost_usd          NUMERIC(12,6),             -- ResultMessage.total_cost_usd
    usage             JSONB,
    duration_ms       INTEGER,
    duration_api_ms   INTEGER,
    -- confirmed present on ResultMessage by the spike (N1 resolved, F1)
    stop_reason       TEXT,
    terminal_reason   TEXT,                      -- finished vs stopped vs ...
    api_error_status  INTEGER,                   -- upstream HTTP status, if any
    model_usage       JSONB,                     -- per-model tokens + costUSD + cache hits
    permission_denials JSONB,                    -- what the agent tried and was refused
    errors            JSONB,                     -- ResultMessage.errors
    error             JSONB                      -- transport/SDK failure, distinct from is_error
);

-- One row per SDK message. This is the transcript.
CREATE TABLE events (
    id                BIGSERIAL PRIMARY KEY,
    run_id            UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq               INTEGER NOT NULL,          -- ordering within the run
    at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    type              TEXT NOT NULL,             -- system | assistant | user | result | stream_event
    subtype           TEXT,
    content           JSONB,                     -- normalized content blocks
    raw               JSONB,                     -- full SDK dump, subject to Q3
    UNIQUE (run_id, seq)
);

CREATE INDEX events_run_seq   ON events (run_id, seq);
CREATE INDEX events_type      ON events (type);
CREATE INDEX runs_session     ON runs (session_id, started_at DESC);
```

`raw` is a JSONB column, so it inherits Q3: if `include_raw` becomes opt-in, this
column is mostly null and the transcript is smaller. Worth deciding before the
table has meaningful volume.

**`is_error` versus `error` — the same distinction as the HTTP layer.**
`is_error` is the agent reporting that its task failed: a normal, successful run
with a bad outcome. `error` is the machinery failing: subprocess crash, malformed
message, timeout. Collapsing them makes "how often does the agent fail?"
unanswerable.

## CP-114 — Write path

**Persistence must never stall a response.** The SSE endpoint streams events as
they arrive; if each event awaited a database round trip, streaming latency would
track database latency and a database outage would stall every run.

Design:

- The `runner` / `sessions` layer emits each normalized event to (a) the HTTP
  response and (b) an in-process `asyncio.Queue`, in that order.
- A background writer task drains the queue and inserts in batches (`executemany`,
  flushed on size or a short interval).
- The queue is bounded. When full, drop `stream_event` records first — they are
  token deltas, reconstructible from the assistant message that follows — and log
  the drop. Never block the response path on the writer.
- `runs` and `sessions` rows are written synchronously at start and finish. They
  are small, low-frequency, and losing them makes the events orphans.

**Persistence is optional.** If `AGENT_SERVICE_DATABASE_URL` is unset the service
runs fully with persistence disabled. The database must not become a hard
dependency for a service whose primary job is running an agent.

## CP-115 — Stack

| Concern | Choice | Why |
|---|---|---|
| Driver | `asyncpg` | Async, fast, the standard for async Postgres in Python |
| ORM / core | SQLAlchemy 2.0 async | Typed, and the async session integrates with FastAPI's lifespan |
| Migrations | Alembic | Schema will change as `ResultMessage` fields firm up (N1) |
| Models | SQLAlchemy models, distinct from the pydantic API schemas | Keeps wire format and storage format independently changeable |

Deliberately **not** reusing the pydantic API models as table models: the API shape
should be free to change for callers without forcing a migration, and vice versa.

## CP-116 — Module layout addition

```
src/agent_service/
  db/
    __init__.py
    engine.py       # async engine + sessionmaker, lifespan wiring
    models.py       # SQLAlchemy models
    repository.py   # the only module that writes: start_run/finish_run/append_events
    writer.py       # background queue drain + batch insert
  migrations/       # alembic
```

`repository.py` is the sole write path. `runner.py` and `sessions.py` depend on a
narrow protocol (`RunRecorder`), not on SQLAlchemy — so the no-database
configuration is a null implementation, and tests use an in-memory recorder.

---

## CP-117 — A.2 — Conversation continuity via the SDK session store

**Do not hand-roll this.** The SDK ships the seam, and the transcript format it
needs is explicitly internal.

Everything in this section was **read from installed source** —
`claude-agent-sdk==0.2.128`, `claude_agent_sdk/types.py` — on 2026-07-29.
RECHECK ON SDK UPGRADE.

## CP-118 — The seam

`ClaudeAgentOptions.session_store: SessionStore | None = None` (`types.py:2092`),
and **`resume` can materialize from the store** (`:2096`). Wiring it is one option
on the object `options.py` already builds.

| Method | Required | Contract |
|---|---|---|
| `append(key, entries)` | **Yes** | Mirror a batch. Called **after** the subprocess's local write succeeds — durability is already guaranteed locally. ~100 ms cadence during active turns. |
| `load(key)` | **Yes** | Called once in the parent **before subprocess spawn**; the SDK materializes the result to a temp JSONL file and the subprocess resumes from it with its existing resume code. Return `None` for a key never written. |
| `list_sessions`, `delete`, … | No | Optional. The SDK probes for presence at runtime and **never uses `isinstance`** — a duck-typed adapter need not subclass. |

## CP-119 — Why this is a safer bet than the `Transport` seam

`Transport` — the SDK's only exported transport-related name
(`claude_agent_sdk/__init__.py:54`; the one concrete implementation,
`SubprocessCLITransport`, lives under `_internal` and is not exported) — carries
an explicit *"may change or be removed in any future release"* warning in its own
docstring.
`SessionStore` carries **no such warning** and ships a conformance suite at
`claude_agent_sdk.testing.session_store_conformance`. That is a supported
extension point, not an escape hatch. Run the conformance suite against the
adapter.

## CP-120 — Properties that matter for the write path

The failure and latency problems A.1 solves by hand are **already solved here**:

- **`append` failure is non-fatal.** Three attempts with short backoff, then the
  batch is dropped and surfaced as a `MirrorErrorMessage` — a `SystemMessage`
  subclass with `subtype="mirror_error"`, so existing `isinstance(msg,
  SystemMessage)` checks still match. The session continues; the local transcript
  is already durable. Timeouts are **not** retried, since the in-flight call may
  still land.
- **`session_store_flush`** — `"batched"` (default) buffers and flushes once per
  turn, or at 500 entries / 1 MiB, keeping adapter latency off the streaming hot
  path. `"eager"` flushes after every mirror frame; a slow adapter still will not
  stall the read loop, but will see frames coalesced.
- **`uuid` is an idempotency key.** Most entries carry a stable one — upsert or
  ignore-duplicate on it. Entries *without* a `uuid` (titles, tags, mode markers)
  must be appended without dedup.
- **Deep equality, not byte equality.** `load()` must return entries deep-equal to
  what was appended; the SDK never hashes or byte-compares. Postgres `JSONB`
  reordering object keys is therefore fine.

## CP-121 — Schema

One table. Deliberately dumb — this is a blob store with an index.

```sql
-- The SDK's mirrored transcript. NEVER parsed by this service.
CREATE TABLE transcript_entries (
    session_key   TEXT NOT NULL,             -- SessionKey, stringified
    uuid          TEXT,                      -- stable idempotency key; NULL for
                                             -- titles/tags/mode markers
    seq           BIGSERIAL,                 -- append order within this process
    at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    entry         JSONB NOT NULL,            -- opaque pass-through
    PRIMARY KEY (seq)
);

-- Upsert target for entries that have a uuid.
CREATE UNIQUE INDEX transcript_entries_dedup
    ON transcript_entries (session_key, uuid) WHERE uuid IS NOT NULL;

CREATE INDEX transcript_entries_session ON transcript_entries (session_key, seq);
```

**`entry` is opaque and must stay that way.** `types.py:1391` describes the shape
as the CLI's on-disk transcript format — "a large discriminated union. That union
is internal" — and `SessionStoreEntry` guarantees only `type`, plus usually `uuid`
and `timestamp`. Anything else is pass-through JSON. Parsing this column to render
a UI or aggregate cost couples the service to an internal format; that is what
A.1's `events` table is for.

## CP-122 — Retention is ours

**The SDK never deletes from the store** unless `delete_session_via_store()` is
called with `delete` implemented. TTL, lifecycle policy, and scheduled cleanup are
this service's problem — see Q11.

Separately, the **subprocess still writes to local disk**; the adapter receives a
secondary copy. `types.py:1463` suggests `CLAUDE_CONFIG_DIR=/tmp` for an ephemeral
local copy. In the container this is a live decision: local transcripts otherwise
accumulate inside the container, swept only by the CLI's own `cleanupPeriodDays`.
See `deployment.md` (CP-078).

## CP-123 — Module layout addition

```
src/agent_service/
  db/
    session_store.py   # SessionStore adapter -> transcript_entries
```

Kept out of `repository.py`: that module is A.1's sole write path, and this one is
called by the SDK on its own schedule, not by `runner.py`/`sessions.py`.

## CP-124 — What this does *not* solve

`resume`-from-store resumes a **conversation on a new connection**. It does **not**
replay an in-flight SSE stream mid-turn. Browser reconnect during a running turn
needs turns to survive consumer disconnect plus a replayable frame log — see
Plan 6 Blocker 2, which this section
does not close.

---

## CP-125 — Part B — Agent database access

Distinct from (A) and **not required for persisting messages**. This is about
giving the agent a tool to query data during a run.

Two implementations:

## CP-126 — B1. In-process SDK MCP server (recommended)

`create_sdk_mcp_server` plus `@tool` builds an MCP server that runs inside the
service process — no subprocess, no separate container.

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("sql_query", "Run a read-only SQL query", {"sql": str})
async def sql_query(args):
    rows = await readonly_pool.fetch(args["sql"])   # separate read-only pool
    return {"content": [{"type": "text", "text": format_rows(rows)}]}

db_server = create_sdk_mcp_server(name="db", version="1.0.0", tools=[sql_query])
# options: mcp_servers={"db": db_server}, allowed_tools=[..., "mcp__db__sql_query"]
```

Advantages, in order of importance:

1. **You control the connection.** The tool uses a dedicated read-only pool with a
   statement timeout. The agent never receives a connection string — it sends SQL
   text and receives rows.
2. **Enforcement lives in Python.** Statement-type checks, row limits, result
   truncation, and per-run query budgets are ordinary code you can test.
3. **No extra process or container.**
4. **It demonstrates `@tool` and `create_sdk_mcp_server`** — directly relevant to
   the learning goal, and the same pattern any future custom tool will use.

## CP-127 — B2. External MCP server (stdio or HTTP)

```python
mcp_servers={"postgres": {"command": "npx", "args": ["@some/postgres-mcp-server"]}}
```

Less code, but the connection string goes to a third-party process, the tool
surface is whatever that server exposes, and it adds a dependency and a subprocess
per session. Reasonable if a well-maintained server offers schema introspection
worth having; otherwise B1 dominates.

## CP-128 — Guardrails, whichever is chosen

- **A separate Postgres role**, read-only, with `GRANT SELECT` on an explicit
  allowlist of tables. Never the service's own role.
- **`SET statement_timeout`** on the read-only pool — a few seconds. An agent can
  write a seq-scan over a huge table without meaning to.
- **Row and byte caps** on results before they enter the context window. A
  `SELECT *` returning 100k rows would blow the context and the budget.
- **Deliberate decision about the persistence tables.** Should the agent be able to
  read `events` — its own transcripts and those of other runs? Interesting, and a
  data-leak path between runs. Default: no.

---

## CP-129 — Part C — Hooks, used for what they are actually good at

Hooks are the wrong tool for persistence (Part A) but the right tool for one thing
nothing else can do: **inspecting and vetoing a tool call before it executes.**

`PreToolUse` runs before the tool, and can deny it. That makes hooks the natural
home for policy:

- Refuse `Bash` commands matching a deny pattern.
- Refuse writes outside `/workspace` — defense in depth behind the `:ro` mount.
- Record an audit row for every `Bash` command *with its outcome*, which is
  security-relevant in a way the general transcript is not.

```python
async def audit_bash(input_data, tool_use_id, context):
    cmd = input_data.get("tool_input", {}).get("command", "")
    await audit_log.record(tool_use_id, cmd)
    return {}          # {} = allow

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[audit_bash])]}
)
```

> **⚠️ Superseded (2026-07-26).** The last sentence below — that `can_use_tool`
> "may simply be the better mechanism for policy" — is wrong. Five live probes
> (`spike/probe_permissions.py`) found `can_use_tool` never fires under any
> configuration this service actually uses; the `PreToolUse` hook is the
> mechanism verified to work, and is what `permission_enforcement="hook"` wires
> up. See `spike-findings.md`, "Permission enforcement — measured, not guessed".

**To confirm during implementation:** the exact payload shape for *denying* from a
`PreToolUse` hook in the Python SDK. The allow/no-op case (`return {}`) is
documented; the deny form is not shown on the reference page. If the hook deny path
turns out to be awkward, `can_use_tool` (the `CanUseTool` callback returning
`PermissionResultAllow` / `PermissionResultDeny`) is a documented alternative with
an explicit deny result — and it may simply be the better mechanism for policy.

Audit rows go through the same repository layer as everything else — a hook that
opens its own database connection would reintroduce every problem Part A avoids.

---

## CP-130 — The credential-leak interaction

This is the non-obvious part, and it constrains both A and B.

**The agent's subprocess inherits the service process's environment.** With `Bash`
enabled, `env` is one tool call away. Any secret in the container's environment —
including `AGENT_SERVICE_DATABASE_URL` with the service's read-write password — is
readable by the agent, and therefore by anything that can influence the agent's
prompt.

The read-only role in Part B is irrelevant if the read-write credential is sitting
in `os.environ`.

**Verified, not assumed** (`spike/introspect2.py` plus the SDK source —
see `spike-findings.md` (CP-046) F2). From
`_internal/transport/subprocess_cli.py`:

```python
inherited_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
process_env = {
    **inherited_env,                    # the ENTIRE parent environment
    "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
    **self._options.env,                # merged on top — adds/overrides only
    "CLAUDE_AGENT_SDK_VERSION": __version__,
}
```

**Mitigations:**

1. **Drop the secret from the environment after loading it — the only mechanism
   that works.** `config.py` reads `AGENT_SERVICE_DATABASE_URL` at startup via
   pydantic-settings, then `os.environ.pop("AGENT_SERVICE_DATABASE_URL", None)`
   before any agent can run. The connection string then lives in the settings
   object, in process memory, out of the environment. This is a **hard requirement
   in `config.py`**, not a hardening option.
2. ~~**Set `ClaudeAgentOptions.env` as a whitelist.**~~ **Does not work.** The
   source above shows `options.env` merged *on top of* the full inherited
   environment: it can add or override keys, never remove them, and no option
   removes them. This mitigation was proposed before the spike and is withdrawn.
3. **Separate roles regardless.** Service role: read-write, owns its schema. Agent
   role: read-only, explicit table grants. Even if a credential leaks, the damage
   differs by orders of magnitude.
4. **Do not install `psql` in the image.** Weak — the agent could `pip install
   asyncpg` and write a script — but it raises the effort.

**`ANTHROPIC_API_KEY` cannot be hidden this way.** The subprocess authenticates
with it, so it must remain in the environment and is therefore always readable by
the agent. Controls there are `max_budget_usd`, key scoping, and spend monitoring
— not concealment.

**None of these are watertight while `Bash` is enabled.** The honest framing: the
agent is inside the trust boundary of the service process. Treat the Postgres
instance as reachable by the agent and scope its contents accordingly — do not put
data there that the agent must never see.

---

## CP-131 — Deployment additions

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: agent_service
      POSTGRES_USER: agent_service
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro   # creates the read-only role
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent_service"]
      interval: 5s
      timeout: 3s
      retries: 10
    # no host port published — reachable only on the compose network

  agent-service:
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      AGENT_SERVICE_DATABASE_URL: postgresql+asyncpg://agent_service:${POSTGRES_PASSWORD}@postgres:5432/agent_service

volumes:
  pgdata:
```

Notes:

- **Do not publish a host port for Postgres.** Compose-internal networking is
  enough; publishing widens exposure for no benefit.
- **`condition: service_healthy`**, not bare `depends_on` — otherwise the service
  starts before Postgres accepts connections and the first migration fails.
- **`postgres:17-alpine` is fine** — the musl caveat in `deployment.md` applies to
  the *agent service* image (which runs the SDK's bundled native binary), not to
  Postgres.
- ~~**Migrations run on startup**, in the service's lifespan, before the app
  serves traffic.~~ **FALSE, and corrected on 2026-08-06 by measurement.** They
  do not run, and nothing in the service ever ran them: `grep alembic src/`
  returns nothing, and the image `COPY`s only `pyproject.toml`, `uv.lock`,
  `README.md` and `src/` — no `alembic.ini`, no `migrations/`. **A deployment
  must apply migrations out of band**, and the compose Postgres publishes no
  host port, so that means a temporary port mapping or a one-off container that
  does have the migration tree.

  Two consequences, both measured against a fresh volume:

  - **The service boots against an unmigrated database.** ~~No gate covers this,
    and none is planned.~~ **A gate covers it since 0.10.0** — with a database
    configured, a revision that is not the one this image expects exits 3,
    including "no revision at all". Asked for by Agent Studio, whose fleet
    shares one schema, so a container on the wrong side of a migration writes
    silently-incomplete rows.

    **The sentence above was not wrong when written; the rule that supersedes it
    is `refuse at boot what should never have started; report at runtime what
    may recover`.** The gate is boot-only, so everything below still holds for a
    service that is already up: **`/healthz` says so**:
    `database_configured: true, database_usable: false`. The status code stays
    200 and the container stays healthy on purpose — persistence is optional and
    must not be able to restart a working service — so **alert on the field, not
    on the status code**. The probe queries a real table, which is what makes it
    catch this case rather than only an unreachable host.
  - **The first history request is a 500.** It *leaked the SQL* until
    2026-08-06 — `detail` carried `relation "sessions" does not exist` with the
    full `SELECT` and a bound parameter, on an API with no authentication.
    **Fixed**: `to_problem`'s fallthrough no longer echoes the message of an
    exception it does not classify, so the answer is now
    `An unhandled ProgrammingError reached the API boundary…` and the traceback
    goes to the log at ERROR. Verified against this exact reproduction.

    The 500 itself is still a 500. Whether an unmigrated schema deserves its own
    problem document, and whether a boot gate should check the schema the way
    the credential and mount gates check theirs, are open in
    `dev-todo.md` §0.
- **`./db/init`** holds the SQL that creates the read-only role used by Part B.
  Only needed if agent database access is enabled.

---

## CP-132 — Open questions this raises

- **Q10** — should the agent get database access (Part B) at all, and if so via
  in-process `@tool` or an external MCP server?
- **Q11** — persistence scope and retention: full transcripts including `raw`, or
  metadata only? How long is anything kept? **Now two retention policies, not
  one:** A.1's `events.raw` and A.2's `transcript_entries`. They overlap in
  content but not in purpose, and the SDK never prunes A.2 for us.

Both in `open-questions.md`.

---

# G. What the code needs from outside those five documents

**These entries exist so a comment never has to reach for a platform document, a
thread in the outbox, or the other build's tree.** Each states the fact and its
provenance; none of them links anywhere.

## CP-133 — three things about the bearer token, before relying on it

**Authentication is the THIRD control, not the first.** Network isolation and a
relay in front of this service remove more risk than a token does, and both sit
outside this repository. A token on an API that should not be reachable is a
second lock on a door standing in a field.

**It answers "is the caller the party that provisioned this container", not
"which user is calling".** Agent Studio asked for that explicitly: they resolve
the owner of a request from the Agent it belongs to, so a per-request caller
claim would be a second and weaker source of truth for something already
decided.

**The token is readable by the agent this service runs.** Measured: the CLI
subprocess runs as the agent's own uid, `/proc` carries no `hidepid`, and the
environment is inherited (CP-075). So it must be **per-instance** and must grant
access to nothing but this instance. A token shared across a fleet is readable
by any user who can take one turn, and then buys the fleet.

**Off by default, and that is not laziness.** The deployment this service
documents — one operator, loopback, `docker compose up` — has no second party to
authenticate. Turning it on by default would break every such deployment to
protect against nobody. What replaces the default is visibility: boot logs a
warning and both `/healthz` and `/v1/capabilities` publish `auth_required:
false`, so a caller can tell rather than assume.

**It does nothing about prompt injection**, which is the likeliest adversary and
arrives through a perfectly authorised call.

## CP-134 — Agent Studio's original OpenAPI requirements, and what request 2 asked for

Four asks against the first published document. **Request 2 is the one the code
keeps referring to**: the SDK's conversation id must be reachable without
parsing a body, because a relay routes on it. That is why `x-sdk-session-id` is
a response header and not only a field, and why `sdk_session_id` is published at
all rather than being treated as an internal detail.

The other three became `AGENT_ID` (CP-135), the discovery endpoint, and the
version split. Frozen in the delivered history bundle; restated here so no
comment has to name a path into `spec/`.

## CP-135 — `AGENT_ID` is opaque, optional, and never validated

Studio asked for a way to stamp which Agent a container belongs to. This service
**stores and publishes it and does nothing else**: no parsing, no
normalisation, no assumed format, and no refusal of a value it does not
recognise — the meaning is Studio's and a provider that validates it would be
guessing.

**Absent is a normal deployment.** A container run by hand is not misconfigured,
so there is no boot gate and no warning that implies one.

## CP-136 — the provisioning contract: configuration must not need a rebuild

Studio's position, adopted: *"a change of environment must not require a new
image."* Everything a deployment varies is an environment variable read at
startup; nothing that varies per deployment is baked into the image.

The reporting half of the same contract: **a container that refuses to start
must say why in a way a provisioner can read**, which is `exit 3` plus a message
naming the remedy — not a traceback, and not a restart loop. An orchestrator can
tell a configuration error from a crash, which is the whole point.

## CP-137 — the schema-revision gate, adopted verbatim

When persistence is configured, the service compares the database's Alembic
revision with the one this build expects and **refuses to boot on any mismatch,
in either direction**. Ahead is as wrong as behind: a newer database means a
newer writer exists, and this build's writes would be the corruption.

The image ships **no migration tree**, deliberately. Migrating is the operator's,
out of band, from the published DDL or the Alembic tree. The gate is what makes
that safe rather than merely stated.

## CP-138 — the agent-id clauses, in Studio's own words

Adopted verbatim rather than paraphrased, because a paraphrase of a consumer's
requirement is a second source of truth: the value is opaque to this service, it
is optional, it is published on `/v1/capabilities`, and its absence is not an
error. The tests assert the clauses, not this build's reading of them.

## CP-139 — three defects the Codex build found for this one

Kept here so no comment has to reach into the other build's tree.

**A helper covered six ways while nothing called it.** Its `unsupported()` was
well tested and unwired, so every field it named was silently dropped anyway. A
unit test of a helper cannot see that nothing calls it — **only a request
through the route can**, which is why the equivalent test here goes through the
route with the real factory.

**A status neither document declared.** That build could produce three statuses
its document did not declare, and one of them — 503 — was declared by *neither*
implementation, so the document-to-document comparison that found the other two
was structurally incapable of finding it. Reachability is a fact about source,
which is why AS-33's test lives in a build's own suite.

**A published field that was null while the SDK had the value.** Its
`token_usage` read camelCase keys at the top level when the payload carries
snake_case ones under `last`. The general rule that came out of it: publish the
raw payload beside the mapped fields, so a mapping bug is visible rather than
indistinguishable from "the SDK told us nothing".

## CP-140 — an image is verified against its tag, not against the source tree

Part of the release ritual: build, tag, then run the conformance suite **against
the tag** — because what a consumer pulls is the tag, and a suite run against a
working tree has proved nothing about it. **A tag is never moved once
published.** Two different images answering to one tag is unanswerable from
either side.

The Claude build's image is `agent-service-claude-python:<implementation
version>`; `agent-service-python` is the pre-rename alias that delivered notes
still name.

## CP-141 — one specification, several builds, and what that means here

The platform is one repository, one specification, one CI runner and more than
one implementation. What generalises is the specification, the conformance suite
and `/v1/capabilities`; **the code does not.** A second build is a separate build
rather than a mode of this one, because the targets are different products with
different tool loops, session lifecycles and sandbox models.

The consequence for this build's code: a value that differs between builds is
published on `/v1/capabilities` rather than assumed, and a clause two builds
cannot both satisfy becomes conditional on a capability rather than forked.

## CP-142 — `stop_kind` is derived in `agent-spec`, and this build only supplies facts

**0.19.0.** *Why did this turn end* was answerable only by reading seven things:
`subtype`, `stop_reason` and `terminal_reason` — each this SDK's own spelling,
passed through verbatim — plus `is_error`, `interrupted`, `timed_out` and
`limit_hit`. A client could reconstruct most endings from the flags and had to
match Anthropic's prose for the rest.

`stop_kind` is one closed word beside them: `end_turn`, `max_turns`,
`max_budget`, `max_tokens`, `refusal`, `interrupted`, `timed_out`, `error`,
`other`. **The three strings are unchanged** — this is `token_usage` beside
`usage`, a second time.

**The derivation is `agent_spec.openapi.stop_kind.derive_stop_kind` and it is
deliberately not here.** Two builds deriving it independently would put the
disagreement one layer up, where it is harder to see, and defeat the point of
adding the field. So `api.py` passes facts — it was interrupted, a guardrail
fired, the SDK said this — and the specification decides the word.

**The precedence exists because of this build.** `interrupted` is checked
before `is_error`, because the CLI reports an interrupted turn with
`is_error=true` and `subtype='error_during_execution'` — identical in shape to a
crash. Any ordering that took the error first would report every interrupt as a
failure, which is the exact confusion the `interrupted` flag was added to end.

**`None` and `"other"` are different answers.** `None` is *this build cannot
tell how the turn ended* — the process died, nothing was recorded. `"other"` is
*it ended and this build has no name for how*. A client retries on one and files
a bug on the other.

**Purely additive:** measured on the published documents, +33 leaves in the core
and **nothing removed and nothing re-typed**, so no notice is owed under AS-23.

## CP-143 — this build DECLARES its permission modes; the union is gone

**0.19.0.** `RunOptions.permission_mode` was a closed `Literal` of six values —
`default`, `acceptEdits`, `plan`, `bypassPermissions`, `dontAsk`, `auto` — and
**all six are this SDK's own enum**, in `claude_agent_sdk/types.py`. This build
was the first implementation, so its SDK's vocabulary became the
specification's, and every later build had to accept six Anthropic-shaped values
whether or not it could honour them. The Codex build maps them onto a sandbox
and an approval mode with one value deliberately unreachable.

**So a build declares what it has.** `capabilities.permission_modes` is a list
of `{id, name, description}` and `permission_mode` is an opaque string. This
build genuinely has all six, so it declares all six — the change costs it
nothing and costs the specification a union that grew by one entry per agent.

**`default` and `plan` are well-known ids**, kept stable so one payload works
against more than one implementation. Agent Harness asked for the set to be kept
if it is cheap and named those two; it is cheap here because this build has both.

**Two guards, because pydantic stopped guarding.** The `Literal` refused an
unknown value with a 422 before any route ran. Now `check_permission_mode`
refuses with a **400** on the create path *and* on `PATCH /v1/sessions/{sid}` —
that second one is easy to miss and was caught only by a test that had asserted
the 422. A 400 also buys a message naming the modes that exist, where a 422
could only say the value was outside a union the caller could not see.

**`auto` is in the SDK's union and absent from the SDK's own docstring**, which
documents the other five. It is declared with that stated rather than with a
guess written in its place.

**What the descriptions must not do is flatter the modes.** This service runs
with `permission_enforcement="none"` and `Bash` enabled, so the container is the
enforcement boundary — `bypassPermissions` bypasses checks that were never what
confined the agent, and its description says so.

## CP-144 — this build reads an extra CA from `SSL_CERT_FILE` **and** `NODE_EXTRA_CA_CERTS`, and both ADD to the trust store

**Measured 2026-08-14, free.** A private certificate authority, a TLS sink
serving a certificate it signed, and one turn per arm. The discriminator is
whether a request reaches the sink at all: an untrusted authority fails the
handshake, and nothing is logged whatever the credential.

| Variable set to the PEM | Requests reaching the sink |
|---|---|
| *(none — the control)* | **0**, *"SSL certificate verification failed"* |
| `NODE_EXTRA_CA_CERTS` | 6 |
| `SSL_CERT_FILE` | 6 |
| `REQUESTS_CA_BUNDLE` | **0**, same refusal as the control |

**Two work and it is not inferable from the image which.** There is no `node` on
the `PATH`, no `node_modules`, and `python3.13` is what the image looks like —
the runtime is compiled into `claude_agent_sdk/_bundled/claude`, a single-file
executable carrying `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`
and `NODE_TLS_REJECT_UNAUTHORIZED` as strings. Four candidates, two honoured, and
the surface says nothing about which.

### The default trust store SURVIVES here

Measured separately, because it is a different question from *is the variable
read*: with `SSL_CERT_FILE` pointing at the private authority **only**, this
build still reached a public HTTPS host whose certificate that authority did not
sign. So the variable ADDS. **The Codex build's answer is the opposite** — the
same variable REPLACES its Rust runtime's root store, and a container given a
private authority there can no longer reach a public host at all.

That asymmetry is why `ca_bundle_source` publishes `replaces_default_trust`
rather than a name alone.

### The value is a FILE, never a directory

Pointing the variable at the directory containing the PEM instead of the PEM
refused the handshake exactly as an unset variable does. Measured on all three
builds, and the failure is indistinguishable from a wrong variable name — which
is why `shape` is published beside the name.

### What is published, and why only one name

`ca_bundle_source: {variable: "SSL_CERT_FILE", shape: "file",
replaces_default_trust: false}`.

**One name, not both.** `NODE_EXTRA_CA_CERTS` is honoured identically and is
deliberately not published: a consumer handed two names has a choice with no
basis for making it, and the field exists to end a guess rather than move it.
`SSL_CERT_FILE` is the one published because the Codex build reads the same name,
so an operator's mental model stays *one name for two builds and a different one
for the third* rather than three unrelated facts.


## CP-145 — `impl` is published BEFORE boot as well as on `/v1/capabilities`

**Asked for by the consumer, 2026-08-14, and accepted as asked**: the same
`{name, version}` object, in a second place, with no change to
`/v1/capabilities` and no new field invented.

### Why the runtime copy was not enough

`GET /v1/capabilities` needs a **running** container, and two things a
provisioning consumer does happen strictly before there is one:

* the environment the container is **created** with, and
* a file written between `docker create` and `docker start` — a certificate
  authority among them, which cannot be added afterwards because the runtime
  reads its trust store once at startup.

`credential_sources` and `endpoint_source` are on this surface for exactly that
reason. **`impl` was the same kind of fact on the wrong side of the line**, and
it was already being computed and published twice — on `/v1/capabilities`, and
in the released document filenames `<impl>-<version>.json`.

### The two substitutes are both worse, and that is the argument

An image **tag** is a string an operator typed. A configured **provider** is a
field an operator chose. Either can disagree with what is actually running
inside the image; `impl.name` is the image's own statement about itself and
cannot.

### One value, not two copies

`impl.version` and the top-level `version` are the same local in one function, so
they cannot drift, and the conformance suite asserts they are equal. The name
comes from `IMPLEMENTATION_NAME`, which is what `/v1/capabilities` publishes —
so all three surfaces have one source.

**`document_version` is deliberately NOT inside `impl`.** It is the contract's
version rather than this build's, and the two have been free to differ since
they were split; nesting it under a build-identity object would imply otherwise.

## CP-146 — `model_api` names the agent TARGET, and the consumer maps it to a vendor API

**Agent Harness asked for a field on the pre-boot surface naming the model API
this build speaks, 2026-08-15.** The field is published. **Its values are the
target family — `claude` — and not the vendor API they proposed** (user,
2026-08-16), so a consumer relaying to a vendor maps `claude` to the
Anthropic API on their own side.

### What they asked for, and what was traded

Their proposal was `anthropic`, on the argument that the API and the build are two
facts that travel together today and are free to stop. **That argument is sound
and it was not the decision taken.** What it would have bought is one fewer
mapping in their gateway; what it costs is a field whose values are a vendor's
vocabulary rather than this platform's.

**The cost of the choice is theirs to carry and they were told plainly**: a
consumer keying an endpoint by vendor API needs `claude` -> Anthropic, and
that mapping lives in their code.

### Why it is NOT a restatement of `impl.name`

`impl.name` is `claude-python` and carries the implementation language. **`model_api`
carries the family and deliberately does not.** A second build driving the same
target in another language publishes the same `claude` here and a different
`impl.name` there — so a consumer keying behaviour to the target keys on this
field, and one keying to a specific program keys on that one.

That distinction is the whole reason the field is not redundant, and it is what a
reader should check before proposing to merge the two.

### What it does NOT claim

`model_api` describes the target reached through this build's own
`credential_sources` and `endpoint_source`. **A provider selector in use is
outside it**: `PROVIDER_SELECTOR_ENV_VARS` publishes the Bedrock, Vertex and Foundry switches, and engaging one moves the transport and the auth. They stay a separate field for that reason.

### Surface and cost

**Pre-boot, and asserted not to be on `/v1/capabilities`** — the question is asked
before a container is created, which is the same argument `credential_sources` and
`endpoint_source` sit here under. The conformance suite carries that assertion
beside the other pre-boot-only fields.

**No document version moves.** ~~The pre-boot specification is not in the OpenAPI
document at all, so this is an implementation change and nothing else.~~
**Superseded by CP-148 (0.19.0):** the pre-boot facts ARE in the OpenAPI document
now, as `PrebootSpec`, and `model_api` is pinned there with `const`. The sentence
above was true when written and the reasoning it rests on is what changed.

## CP-147 — an image publishes BOTH things it was built against, and the DDL was the missing one

**An image depends on two published artifacts and could only name one.**
`document_version` was on the pre-boot surface; the Alembic head it requires was
baked into the binary, gated the boot, and appeared nowhere a consumer could
read. Published since 2026-08-16 as `schema_revision`.

### The two streams do not predict each other

`spec/VERSION` moves when the HTTP surface or a clause changes; the schema moves
when a migration lands. Neither can be derived from the other, so an image
naming one of them leaves the other unanswerable. **Agent Harness declares
exactly this pair as two Maven dependencies** — the spec artifact at test scope,
the schema artifact executing inside their image — and an image has no pom, so
the pre-boot surface is where it says the same thing.

### The question it answers, and when it is asked

*Will this image accept my database?* Before 2026-08-16 the only way to find out
was to create a container and read the refusal, because the gate that compares
the baked revision against a live database runs at boot. **A database is chosen
before a container is created**, which puts the question on the same side of the
line as `credential_sources` — and off `/v1/capabilities`, where the conformance
suite now asserts it does not appear.

### It cost a module split, and the split is the point

The value lives beside the boot gate that enforces it, and **importing that
module pulls SQLAlchemy**. Two things cannot afford that: the pre-boot facts,
which were a command that had to answer in an image whose service cannot start
until 0.19.0 and are read at import to build the document's `PrebootSpec` now,
and the standing constraint that a build with no database configured never
imports a database stack — pinned by a fresh-interpreter test, because `sys.modules` is already
poisoned once any other test has run.

So the constant moved to an import-free leaf module, and the gate re-exports it.
**Still exactly one definition**: the alternative was a copy per build,
test-pinned to the original, which is a copy either way. A fresh-interpreter test
asserts the pre-boot specification imports no database code, which is what stops
the convenient import from creeping back.

### Identical on all three builds, deliberately

They migrate one database between them, so three images disagreeing about the
revision is a defect rather than a divergence — which is why this is **not** a
row in the capability-divergence table. The boot gate exists to catch exactly
that disagreement.

**No document version moves.** ~~The pre-boot specification is not in the OpenAPI
document, and nothing in `spec/` changed for this.~~
**Superseded by CP-148 (0.19.0):** `schema_revision` is pinned in the document's
`PrebootSpec` component, so it is part of `spec/` now and moving it needs a
document version.

## CP-148 — the pre-boot facts moved INTO the document, and the command was removed

**`agent-service-spec` is gone as of 0.19.0.** Every fact it printed is published
in this build's own OpenAPI document as `components.schemas.PrebootSpec`, with the
values pinned by `const` — `credential_sources`, `model_api`, `endpoint_source`,
`ca_bundle_source`, `provider_selectors`, `auth_enforced`, `schema_revision`,
`impl.name` and `listen`.

### Why the command was the wrong surface

**The consumer resolves the specification at BUILD time and loads an image at
RUNTIME.** Every decision these facts inform is made before a container exists:
the environment it is created with, a certificate written between create and
start, and the database it is pointed at. Requiring `docker run` to read them put
a runtime dependency in front of a build-time question — and the answer was
reachable from no path under `spec/`, which is the only tree the consumer was
told to depend on.

That is the same circularity the command itself was invented to cut, one level
up: the command existed because `/v1/capabilities` needs a running service, and
then the command needed a running container.

### `const` per build, and no enum anywhere

Each build states its own value, so nothing predicts how many builds will exist.
A closed set in a shared file would carry the half we know and imply the half we
do not, and a fourth build breaking no rule would falsify it. `const` is a real
constraint a validator enforces and a generator emits as a literal type.

`core-<version>.json` intersects the three documents, so the eleven-field shape
survives into the core and the per-build values drop out of it.

### Two fields are deliberately left open

`version` and `impl.version` carry no `const`. They move on the implementation
stream — a build bumps several times between two documents — and pinning either
would break AS-24 the first time one did. Read them from the image tag or from
`GET /v1/capabilities`.

### What replaced the command as the entry point

`docker inspect` carries `com.npf.agent-service.impl` and
`.document-version`, which together name the document holding everything else.
Nothing is executed. `ci.py`'s label check compares the labels against that
document, and the conformance suite's boot-gate tier reads the same pair.

### What this breaks, and it is not small

**AS-25's command no longer exists, and ST-1 in the signed 0.5.1 instrument runs
it.** That clause is frozen and cannot be edited, so a consumer implementing it
literally gets a container that fails to start. The notice went to Agent Harness
when this shipped. This is the first removal of a published surface rather than a
widening of one, and it needed a version because of that.

### The rule it creates

**A published document now ASSERTS these values, so moving one requires a new
document version rather than a rebuild.** Before this, the pre-boot surface could
change with nothing moving anywhere, which is how it drifted out of the
specification's reach.

## CP-149 — what holds an MCP tool call open: 60 s to respond, 300 s between frames, 100000 s in all

Published as `mcp.tool_call` at document version 0.19.0. **Read out of the CLI
bundled in `claude-agent-sdk 0.2.128`, not stopwatched** — the house rule, and the
distinctions below are the code's rather than a measurement's.

| Published | Value | What it is |
| --- | --- | --- |
| `request_timeout_s` | `60` | the POST carrying `tools/call` must be *answered* |
| `idle_timeout_s` | `300` | gap between frames once the response has begun |
| `total_timeout_s` | `100000` | wall clock for the whole call |
| `progress_resets_idle` | `true` | `notifications/progress` restarts the idle clock |

### The 60 s is on the POST alone, and responding is what clears it

The fetch wrapper the MCP client installs returns the underlying fetch untouched
when the method is `GET` — the SSE stream is exempt by an explicit branch — and
otherwise arms an `AbortController` that aborts with a `TimeoutError` named *The
operation timed out.* The timer is cleared in a `finally` around the fetch, so it
is satisfied the moment response **headers** arrive. A server that buffers its
whole answer into one JSON body is the shape this refuses; a server that opens an
SSE stream at once has already cleared it.

**It is a floor rather than a setting.** The value is
`min(max(override, 60000), 2147483647)` in milliseconds, so an override can raise
it and can never lower it.

### The idle timeout is transport-dependent, and the published figure is the strict one

`stdio` gets 1800 s, `sse` and `http` get 300 s, and the in-process and IDE
transports get `0` — disabled — which this build never sends. **300 is
published** because a value that is never more generous than the strictest
transport in `transports` is one a client can plan against; the `stdio`
generosity is recorded in the platform's capability-divergence snapshot instead
of complicating the field.

**An SSE comment is not a frame that counts.** The CLI's own error names what
does — *no response or progress for Ns* — so a keepalive-only stream dies at
exactly 300 s while looking healthy on the wire.

### 100000 s, and the two environment variables

The hard cap defaults to `1e8` milliseconds. `MCP_TOOL_TIMEOUT` (ms) moves the
request and total figures; `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (ms, `0` disables)
moves the idle one. **This service sets neither, and a caller cannot reach
either** — they are container environment, and `McpServer` carries no `timeout`
field on any variant — so the published values are what every request gets.
