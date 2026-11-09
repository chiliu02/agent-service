# The database model

**What the schema is, what each table means, and what the words mean.** The DDL
itself is in [`spec/database/`](../spec/database/), one file per Alembic
revision, generated from the migrations and never hand-edited. This document is
the reading of it: the entities, the relations, the vocabulary, and the handful
of places where a column name invites a wrong conclusion.

The current revision is **`d3f9a0c15e27`** —
[`spec/database/agent-service-d3f9a0c15e27.sql`](../spec/database/agent-service-d3f9a0c15e27.sql).

The authority is the code, not this file: `impl/common/agent-spec/src/agent_spec/db/models.py`
is the ORM and carries the reasoning column by column. The migrations are under
`impl/common/db/migrations/versions/`.

---

## 1. What this schema is a model OF

**A record of an agent having been driven over HTTP.** Not a chat log, not a
job queue, not a workflow engine. The service fronts a local coding agent; the
database is where what the agent did survives the HTTP response that reported it.

The whole model is four tables and one shape:

> **a conversation holds submissions, a submission emits messages** —
> `sessions` → `runs` → `events`,
>
> plus `transcript_entries`, which is not part of that chain at all and is
> explained in §5.

Three properties fall out of that and are worth stating before the tables:

- **Everything is append-mostly and immutable in spirit.** A `runs` row is
  inserted at start and updated once at finish; an `events` row is never
  updated. Nothing in the schema is a mutable working state — the live state of
  a session lives in the process, not here.
- **The database is optional.** With `AGENT_SERVICE_DATABASE_URL` unset the
  service runs a `NullRecorder` and writes nothing. Every column therefore
  describes history, never behaviour: no code path reads a row to decide what
  to do next.
- **Writes never block the agent.** `recorder.py` is a synchronous protocol that
  enqueues; `writer.py` drains a bounded queue in the background. Under
  pressure it drops `stream_event` rows first (see §7).

---

## 2. The vocabulary — run, turn, query, session

This is the question the column names do not answer on their own, and the
answers are not symmetric.

### `run` — one prompt submitted

`models.Run`'s own docstring is the definition:

> One prompt submitted: a `POST /v1/query`, or one turn of a session.

So a **run is a unit of submission**. One row in `runs` per prompt the service
was asked to answer, whichever endpoint asked it. Its `id` is a `uuid4().hex`
minted by the service at submission time.

| Question | Answer |
|---|---|
| Is **run = query**? | A one-shot `POST /v1/query` is *a* run. But not every run is a query — a session turn is a run too. So *query ⊂ run*, not `=`. |
| Is **run = turn**? | **At the service's level, yes.** One turn of a session is exactly one `runs` row. |
| Then why does `runs.num_turns` exist? | Because "turn" means something else one level down. See below — this is the trap. |

### `turn` is overloaded, and the schema contains both meanings

| Meaning | Where it lives | Counts |
|---|---|---|
| **A submission to a session** — the service's meaning | `sessions.total_turns`, `SessionRecord.turns` | **`runs` rows** for that session that reached a result |
| **An iteration of the agent's internal loop** — the SDK's meaning | `runs.num_turns` | model round-trips *inside one run* (think→tool→think→answer) |

So a single `runs` row may legitimately report `num_turns = 7`, and still count
as **one** toward its session's `total_turns`. `options.max_turns` and
`limit_hit = 'turns'` are about the *inner* meaning; they bound one submission,
not the conversation.

`runs.num_turns` is filled only by the Claude build. Codex and Gemini write
`None` — their SDKs expose no such count (see §8).

### `session` — one multi-turn conversation the client can name

A `sessions` row exists because a client called `POST /v1/sessions` and got back
an id it can send further prompts to. A one-shot `POST /v1/query` gets **no**
`sessions` row: it is never registered, so there would be no id by which any API
path could reach it.

### The two session ids, and why both are columns

| Column | Whose | When it exists | Stability |
|---|---|---|---|
| `sessions.id` (the "sid") | **the service's** — `uuid4().hex` minted by `registry.py` | at create | stable for the session's life |
| `sessions.sdk_session_id` | **the agent SDK's** | not until the first turn produces a system message | **may move**, per build |

`sessions.id` is the primary key and the only id a client has ever seen.
`sdk_session_id` is kept because it is what the resume path needs and what
`transcript_entries` is keyed on — but it is nullable, late-arriving, and its
*scope differs per build*: `conversation` on claude and codex, **`turn` on
gemini**, where a resumed session mints a new one every turn (published as
`sdk_session_id_scope`; see [`capability-divergence.md`](./capability-divergence.md)).

**Group by `sessions.id`. Never by `sdk_session_id`.**

### Summary of the levels

```
session          one conversation                       sessions row
  └─ run/turn    one prompt submitted + its answer      runs row
       └─ event  one normalized SDK message             events row
            (and, inside a run, num_turns model round-trips — NOT rows)
```

---

## 3. The entities

### `sessions` — one multi-turn conversation

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(64)` **PK** | the service-side sid, `uuid4().hex` |
| `sdk_session_id` | `VARCHAR(128)` idx | the SDK's id, once known. Nullable, may move |
| `agent_id` | `VARCHAR(64)` idx | **provenance, not authorisation** — the container's `AGENT_ID`, stamped at create, never updated, never settable by a caller |
| `title` | `TEXT` | client-supplied |
| `status` | `VARCHAR(32)` **not null** | see below |
| `model`, `permission_mode` | | as requested at create |
| `created_at`, `last_used_at` | `TIMESTAMPTZ` not null | `last_used_at` moves on each completed turn |
| `closed_at` | `TIMESTAMPTZ` | set on close |
| `total_cost_usd` | `NUMERIC(12,6)` **nullable** | see the warning below |
| `total_turns` | `INTEGER` not null, default 0 | turns that **reached a result** |

**`status` is `idle | running | closed` in the API, but only two of those are
ever written here.** The repository inserts `idle` at open and writes the closing
status at close; `running` is live state that exists in the process and never
lands in a row. Reading `status = 'idle'` from the database therefore means "not
closed", not "not currently busy".

**`total_cost_usd` is a floor, not the figure — and the column name invites
exactly the wrong reading.** It mirrors the SDK's running total *for the
connection* and is **assigned, never summed**: summing per-turn costs across a
session would multiply the real number by roughly the turn count. An interrupted
turn runs real inference and does **not** move it (measured: eight consecutive
start-then-interrupt turns moved it $0.000649 in total).

`NULL` is not `0`. Since revision `d3f9a0c15e27` the column is nullable **and
its server default is gone**, because:

- `0` means *this build can price a turn, and the floor has not moved yet*;
- `NULL` means *this build cannot price a turn at all* — the honest answer for
  Codex and Gemini, which report tokens and no money. With the old default they
  would have read `0.000000` forever, indistinguishable from free.

**`total_turns` counts `runs`, not model round-trips** (§2). A turn that timed
out, failed, or was abandoned mid-drain is not counted; one whose result was
produced but never delivered to a client that hung up **is**.

Deliberately absent: an `options JSONB` column. "The resolved options" is a
dataclass that can hold callables, which would serialise as
`{"_unserializable": …}` — recording noise as if it were configuration.

---

### `runs` — one prompt submitted, and how it ended

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(64)` **PK** | `uuid4().hex`, minted at submission |
| `session_id` | `VARCHAR(64)` **FK → sessions.id** `ON DELETE CASCADE`, idx | **`NULL` for a one-shot `/v1/query`** |
| `sdk_session_id` | `VARCHAR(128)` idx | the SDK's id for this run |
| `started_at` / `finished_at` | `TIMESTAMPTZ` | `finished_at` null while in flight |
| `prompt` | `TEXT` not null | what was submitted |

**From the agent's terminating result:**

| Column | Notes |
|---|---|
| `result_text` | the answer |
| `result_subtype`, `stop_reason`, `terminal_reason` | **each SDK's own spelling, verbatim** — for a human reading a log, not for a client to match on |
| `limit_hit` | `'turns'` or `'budget'` — which guardrail ended it. Never `'timeout'` |
| `num_turns` | the SDK's *inner* turn count (§2) |
| `duration_ms`, `duration_api_ms`, `api_error_status` | diagnostics; deliberately not on `RunResponse` |
| `cost_usd` | **what THIS run cost.** `NULL` = nobody can say, **never `0.0`** — an aborted turn is unattributed, not free |
| `usage`, `model_usage` | `JSONB`, verbatim from the SDK. **`model_usage`'s aggregation rule differs per build** — sum on gemini (per-turn), difference on claude (cumulative), skip on codex (absent) |
| `permission_denials`, `errors` | `JSONB` |

**How it ended, from the service's point of view:**

| Column | Notes |
|---|---|
| `is_error` | **the AGENT reporting its task failed** — a successful run with a bad outcome |
| `error` | **the MACHINERY failing** — subprocess crash, malformed message, timeout |
| `interrupted` | not null, default false |
| `timed_out` | not null, default false |
| `outcome_missing` | not null, default false — no terminating result was ever consumed: crash, abandoned consumer, or timeout |

**`is_error` and `error` are two different questions and must not be
collapsed** — doing so makes "how often does the agent fail?" unanswerable.

**`stop_kind` is NOT a column.** The closed, cross-build ending vocabulary
(`end_turn | max_turns | max_budget | max_tokens | refusal | interrupted |
timed_out | error | other`) is **derived on read** by
`queries.stop_kind_of` from six columns already in the row. A column would have
meant a fourth DDL revision for a pure function, and a stored derivation can go
stale against its own inputs.

Indexes: `ix_runs_session_id`, `ix_runs_sdk_session_id`, and
`runs_session_started (session_id, started_at)` — the "this session's turns in
order" query.

> **`session_id` is NULL for a one-shot run and only for that.** Every build
> passes its sid to `start_run`, so a session turn always fills it — and the
> read path depends on that: a session's transcript is `events` joined through
> `runs` and filtered on this column, so a turn recorded without it is a turn no
> transcript can show. The failure is silent — an empty page, not an error.

---

### `events` — one normalized SDK message

**This is the transcript a UI reads.**

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL` **PK** | storage sequence, **and the pagination cursor** |
| `run_id` | `VARCHAR(64)` **FK → runs.id** `ON DELETE CASCADE`, not null | |
| `seq` | `INTEGER` not null | **position within its own run, as the driver counted it** — not arrival order at the writer, which batches |
| `at` | `TIMESTAMPTZ` not null | |
| `type` | `VARCHAR(32)` not null | closed set — §4 |
| `subtype` | `VARCHAR(64)` | build-specific — §4 |
| `content` | `JSONB` | **normalised** content blocks, or null |
| `raw` | `JSONB` | the originating SDK's whole payload, only when the run was made with `include_raw` |

Constraint `events_run_seq_unique (run_id, seq)`; indexes `events_run_seq`,
`events_type`.

**A session's transcript is ordered by `events.id`, not by `(run, seq)`.** Both
give the same answer — a session serialises its turns behind a lock and the
repository preserves queue order within a batch — but `id` is a single
monotonic column, so it doubles as a cursor. A compound sort would need a
compound cursor to paginate without gaps or repeats.

**`content` vs `raw`.** `content` is the specification's own normalised shape: a
list of blocks, each with a `type` discriminator, a `text` block carrying its
string in `text`. It is what a client renders a conversation from, and it is the
same on every build. `raw` is the SDK's own payload and its shape differs per
build. `content: null` means *this event carries no renderable content* (an init
frame, a rate-limit notice) — never that content was dropped.

---

### `transcript_entries` — the SDK's own resume log, mirrored

**Not part of the chain above.** See §5 for the whole story.

| Column | Type | Notes |
|---|---|---|
| `seq` | `BIGSERIAL` **PK** | append order — the entries carry no ordinal of their own |
| `session_key` | `VARCHAR(256)` not null | the SDK's composite key — §6 |
| `uuid` | `VARCHAR(128)` | the SDK's idempotency key. **Nullable, legitimately** |
| `at` | `TIMESTAMPTZ` not null | |
| `entry` | `JSONB` **not null** | stored **verbatim**, never parsed by this service |
| `agent_id` | `VARCHAR(64)` | the same provenance stamp as `sessions.agent_id`, needed as its own column because this table has no FK. **Not indexed** — it is provenance at rest, and this is the highest-volume table in the schema |

Indexes: `transcript_entries_session (session_key, seq)`, and a **partial**
unique index `transcript_entries_dedup (session_key, uuid) WHERE uuid IS NOT
NULL`. The partiality is load-bearing: entries without a uuid (titles, tags,
mode markers) must be appended **without** dedup, and Postgres skips a partial
index entirely for rows failing its predicate, so those never conflict. A plain
unique constraint would collapse them all into one row.

---

## 4. `events.type` and `events.subtype`

### `type` — a closed set the **specification** owns

```
system | assistant | user | result | stream_event | rate_limit | unknown
```

Seven members, and every build maps onto them. `unknown` is the required escape
hatch: a build that crashed on an SDK's new message kind would be broken by a
dependency bump it did not ask for.

**`type` is the authoritative discriminator — the SSE frame name is not.** The
`event:` line of a streamed frame is an implementation detail that differs
between builds; a client reading it instead of this field works on some builds
and silently renders nothing on others.

| Member | Means |
|---|---|
| `system` | the service's or SDK's own bookkeeping — init, lifecycle, environment notices. Not model output |
| `assistant` | the agent acting — **including all tool use** |
| `user` | the caller's turn, or a message attributed to the user |
| `result` | the turn's terminal event, carrying status and usage |
| `stream_event` | incremental output (token deltas). The only genuinely streaming category, and **the only droppable one** |
| `rate_limit` | a rate-limit notice on the account |
| `unknown` | not recognised — reported honestly rather than guessed |

**There is no `tool` member, and that is deliberate.** The Claude SDK delivers
tool use *inside* assistant messages, so tool activity is `assistant` with the
detail in `subtype`. Codex and Gemini reached the same place independently
rather than adding a member to a closed enum for one build's convenience.

### `subtype` — free text, **build-specific**, and where the detail goes

`VARCHAR(64)`, nullable, no closed set. It is what `type` had to drop. What it
carries depends on which build wrote the row:

**claude-python** — the SDK message's own `subtype` attribute, verbatim
(e.g. `init` on a system message, `success` / `error_during_execution` on a
result). Absent on message kinds that have none.

**codex-python** — the notification method, or `Kind.phase` for tool items:

| Event | `type` | `subtype` |
|---|---|---|
| `thread/started`, `turn/started`, `hook/completed`, `fs/changed`, … | `system` | the method string verbatim |
| `turn/completed` | `result` | `turn/completed` |
| `process/outputDelta` | `stream_event` | `process/outputDelta` |
| `item/started`, `item/completed` | `assistant` (or `user`) | **`<ItemKind>.<phase>`** — e.g. `CommandExecutionThreadItem.started`, `FileChangeThreadItem.completed` |
| anything matching `ratelimit` | `rate_limit` | the method string |
| unrecognised method | `unknown` | the method string |

`UserMessageThreadItem` and `HookPromptThreadItem` are the two item kinds typed
as `user`; everything else the agent does is `assistant`. Both `started` and
`completed` are emitted and told apart by the suffix — a caller watching a long
command needs to know it began.

**gemini-python** — the agent's own `stream-json` event name, with the tool name
appended when there is one:

| Agent event | `type` | `subtype` |
|---|---|---|
| `init` | `system` | `init` |
| `message` (role `assistant`/`user`) | that role | `message` |
| `tool_use` | `assistant` | **`tool_use:<tool_name>`**, or `tool_use` if unnamed |
| `tool_result` | `assistant` | **`tool_result:<tool_name>`** |
| `result` | `result` | `result` |
| anything else | `unknown` | the raw name, or null |

**So: branch on `type`, read `subtype` for detail, and treat `subtype` as
per-build.** A query matching `subtype = 'init'` finds claude and gemini rows
and no codex rows. `raw` is the fallback for anything the mapping did not
anticipate.

---

## 5. The relation between `transcript_entries`, `sessions` and `runs`

**There is no relation in the schema, and that is the design — not an
omission.** There are two independent write paths, and they were kept separate
on purpose.

```
                      ┌──────────────────────────────────────────┐
   A.1  the service's │  sessions ──< runs ──< events            │  the service
        own transcript│      FK          FK                      │  writes it,
                      │  (real foreign keys, cascading deletes)  │  a UI reads it
                      └──────────────────────────────────────────┘

                      ┌──────────────────────────────────────────┐
   A.2  the SDK's own │  transcript_entries                      │  the SDK writes
        resume log    │  keyed by session_key — NO foreign key   │  it, the SDK
                      │  entry JSONB stored verbatim             │  reads it back
                      └──────────────────────────────────────────┘
```

| | A.1 — `events` | A.2 — `transcript_entries` |
|---|---|---|
| Written by | the service, via the recorder → queue → repository | **the SDK itself**, calling `append()` on its own schedule from inside the subprocess read loop |
| Goes through the queue? | yes | **no** — a separate path entirely |
| Shape | normalised, specification-owned | the CLI's on-disk JSONL, "a large discriminated union" that the SDK documents as **internal** |
| Parsed by this service? | yes — it *is* the read model | **never** |
| Purpose | a client renders a conversation | the CLI can **resume** from it |
| Keyed by | `run_id` → `runs.id` → `sessions.id` | `session_key` string |
| On failure | swallowed and logged — must never raise into a turn | **raised**, so the SDK can retry and surface a mirror error |
| Which builds write it | **all three** | **claude-python only** |

### The join that looks available and is not

`session_key`'s middle segment corresponds to `sessions.sdk_session_id`, so it
looks like `transcript_entries` could be joined to `sessions`. It cannot be
done soundly, for three independent reasons — the first alone settles it:

1. **The encoding is ambiguous.** `project_key` may contain a slash, in which
   case it can collide with a `session_id`. The SDK's own store has the same
   property, so deviating would be a silent difference from the reference
   rather than a fix.
2. **`sdk_session_id` is null until the first turn mints one**, so a session
   created and not yet used has nothing to join on.
3. **No index serves a derived substring** — the join would be a scan of the
   largest table in the schema.

**Unsound *and* looks sound is worse than plainly unavailable**, which is why
`agent_id` is duplicated onto `transcript_entries` as its own column rather than
being reached through a join.

### The practical consequence

- To read **what happened** in a session — for a UI, a report, an audit — join
  `sessions → runs → events`. That is the supported path and the only one the
  read layer implements.
- `transcript_entries` is the SDK's private business. It exists so the agent can
  resume; treat it as opaque storage. Reading into `entry` from a query, a
  console, or a report couples you to a format that changes under an SDK
  upgrade.

---

## 6. `session_key`

`transcript_entries.session_key` is **the SDK's own composite key, rendered as a
string by the SDK's own encoding** — reproduced deliberately identically in
`impl/claude-python/src/agent_service/db/session_store.py::key_to_string` so
this adapter groups entries exactly the way the reference implementation does.

The SDK hands the adapter a dict, and it is flattened by joining with `/`:

```
project_key / session_id [ / subpath ]
```

| Segment | What it is |
|---|---|
| `project_key` | the SDK's scoping key — documented as a sanitized cwd, or a tenant id |
| `session_id` | **the SDK's** session id (i.e. corresponds to `sdk_session_id`, *not* `sessions.id`) |
| `subpath` | optional; present for sub-keyed entry groups |

`VARCHAR(256)`, not null. It is the sole grouping key for the table: `load()`
returns every entry for one `session_key` ordered by `seq`, and `append()`
dedups within one `session_key` on `uuid`.

**Its known limit is inherited, not introduced**: a `project_key` containing a
slash can in principle collide with a `session_id`. That is reason (1) in §5 for
why the apparent join is unsound.

---

## 7. How rows get written

```
turn/run code  ──enqueue()──>  bounded deque  ──drain task──>  repository  ──>  Postgres
(synchronous,                  (10k soft,                      (the sole
 never raises,                   50k hard)                      writer)
 never awaits)
```

- **The recorder protocol is synchronous by design.** An `await` on the producer
  side would put a suspension point inside the session drain loop, where a
  cancellation landing would mislabel a turn that had actually succeeded — a
  persistence layer corrupting the accounting of the thing it exists to observe.
- **One queue, not two, because order matters.** `events.run_id` references
  `runs.id`, so the run row must land before its events. The repository applies
  items **in queue order**, coalescing only *consecutive* `EventAppended`s into
  a bulk insert. Sorting a batch by type would be faster and would produce
  foreign-key violations under exactly the load that makes them hard to
  reproduce.
- **It is deliberately lossy under pressure, in a defined order.** Past the soft
  capacity, `stream_event` rows are sacrificed first — the assistant message
  that follows carries the same text, so what is lost is granularity, not
  content. Past the hard capacity anything is dropped, loudly; that is only
  reachable if the database has been unreachable for a long time, and the
  alternative is growing until the process dies and takes the agent with it.
- **`queries.py` is the sole reader, `repository.py` the sole writer.** Split so
  that "who can write?" stays answerable and so a slow scan degrades a page
  rather than losing a turn.

### Which endpoint touches what

| Endpoint | Rows |
|---|---|
| `POST /v1/query`, `POST /v1/query/stream` | a `runs` row with `session_id = NULL`, plus its `events` |
| `POST /v1/sessions` | a `sessions` row, `status = 'idle'` |
| `POST /v1/sessions/{sid}/messages`, `…/messages/stream` | a `runs` row with `session_id = sid`, its `events`, and a roll-up of `sessions.total_turns` / `total_cost_usd` / `last_used_at` |
| `DELETE /v1/sessions/{sid}` | `sessions.status`, `closed_at` |
| `GET /v1/sessions`, `GET /v1/sessions/{sid}` | reads `sessions` |
| `GET /v1/sessions/{sid}/transcript` | reads `events` joined through `runs`, paginated on `events.id` |
| `GET /v1/runs/{run_id}` | reads one `runs` row, `stop_kind` derived on read |

---

## 8. What each build actually fills

The schema is shared; what lands in it is not. Every build writes `sessions`,
`runs` and `events` through the same layer — the per-build cost of persistence
is one ~70-line `persistence.py` mapping its own outcome onto `RunOutcome`.

| Column | claude-python | codex-python | gemini-python |
|---|---|---|---|
| `runs.total_cost_usd` → `sessions.total_cost_usd` | filled (cumulative floor) | **NULL** — reports no monetary figure | **NULL** — reports no monetary figure |
| `runs.model_usage` | filled, **cumulative per connection** → *difference* consecutive turns | **NULL** | filled, **per turn** → *sum* is correct |
| `runs.num_turns` | filled | NULL | NULL |
| `runs.permission_denials` | filled | NULL — governs by sandbox, not a per-tool decision log | NULL — a denied tool is removed from context, so there is no denial event |
| `runs.duration_api_ms` | filled | NULL | NULL — the stats block times the whole turn |
| `runs.errors`, `api_error_status` | filled | NULL | NULL — a failure is an exit code and a text envelope |
| `runs.limit_hit` | filled | NULL | NULL — the turn-limit exit code was never reproduced |
| `runs.stop_reason` | filled | NULL — status is the whole answer | NULL — same |
| `transcript_entries` | **written** | not written | not written |

**`NULL` here means "this build cannot say", and it is written out explicitly
rather than defaulted, so a reader can tell it from "nobody has looked yet".**

[`capability-divergence.md`](./capability-divergence.md) is the maintained,
side-by-side statement of these differences and is the authority when this table
and it disagree.

---

## 9. Migration history

`spec/database/` is **a separate stream** from the specification version: it
moves when a migration lands, not when a document is cut. One file per revision,
each the full schema at that revision.

| Revision | Change |
|---|---|
| `a5cf3bd007f9` | initial — `sessions`, `transcript_entries`, `runs`, `events` |
| `b1e7c4a90d32` | `agent_id` added to `sessions` (indexed) and to `transcript_entries` (not indexed) |
| `d3f9a0c15e27` | `sessions.total_cost_usd` becomes nullable **and loses its `0` server default** — so a build that cannot price a turn records `NULL`, not a `0` indistinguishable from free |

The service checks the revision at boot; the migrations live under
`impl/common/db/migrations/versions/`.

---

## 10. Reading the schema without being misled

Six things the column names do not tell you:

1. **`sessions.total_cost_usd` is a floor, not a cost.** Interrupted turns spend
   real money and do not move it. It is assigned from the SDK's cumulative
   figure, never summed.
2. **`NULL` is never `0`** in any money or usage column. `NULL` = nobody can
   say; `0` = measured as zero.
3. **`runs.num_turns` and `sessions.total_turns` count different things** (§2).
4. **`runs.is_error` ≠ `runs.error`** — the agent failing its task versus the
   machinery failing.
5. **`sessions.status = 'idle'` means "not closed"**, not "not busy" —
   `running` is live state and is never written.
6. **`stop_kind` is derived on read**, not stored. Do not go looking for the
   column; do not add one.

And one structural rule: **join `sessions → runs → events`; never try to reach
`transcript_entries` from any of them.**
