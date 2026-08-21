# `gemini-python` — references

**The one document this build's code cites, and it cites it by ID.** A comment
says `(GP-07)` and nothing else: no path, no heading, no section number.

**Why.** 170 code citations in this repository pointed at 14 documents; 50 were
unusable one hour after a directory move and nothing in CI noticed. An ID does
not rot, and a document that cannot be linked to cannot be linked *wrongly*.

## The rules

1. **Code cites this file, by ID, and nothing else.** Not the todo, not the
   plans, not another build's document. A temp document is never a citation
   target: it is written to be superseded and code outlives it.
2. **This file links to nothing.** Where an outside document is worth naming, it
   is named in prose and anything load-bearing is restated here.
3. **Each entry is complete.** Somebody holding only this file can act
   correctly.
4. **The comment stays short.** A sentence that changes what a maintainer does
   stays in the code; everything behind it lives here.
5. **An ID is permanent.** Superseded entries are struck through and kept, never
   renumbered — a stale ID in old code must still resolve.

**Every claim is measured against `@google/gemini-cli` 0.54.4 unless it says
otherwise**, and where a measurement has a control, the control is stated: *the
command failed* and *the command was blocked* look identical without one.

**This build has no code yet.** It has a specification's worth of evidence and
six probes, and this file is that evidence. It was seeded on 2026-08-11 from the
five spike documents written on 2026-08-10 and 2026-08-11, which remain in the
platform's `docs/` for their narrative; **everything a maintainer needs is
restated here.**

**Model note.** Every live measurement ran on the CLI's default `auto` routing,
which resolved to `gemini-3.5-flash` for the answering role, except where an
entry says the model was pinned. Interface behaviour does not depend on that;
agent behaviour does, and the entries that turn on it say so (GP-18, GP-20).

---

# A. The target, and the two interfaces

## GP-01 — there is no SDK, there are two interfaces, and both are incomplete

The programmatic surface is the CLI itself plus **ACP**, the Agent Client
Protocol, spoken as JSON-RPC 2.0 over stdio when the binary is started with
`--acp`. There is no Python package to import and no stability contract.

**Neither interface alone can satisfy `/v1`:**

| Interface | Has | Lacks |
|---|---|---|
| **ACP** | a host-side permission call, host-performed file I/O, a structured event stream, agent-declared model and mode catalogues | any session lifecycle beyond create — no list, close, cancel, resume or fork |
| **CLI** (`-p`, `-o stream-json`) | `--session-id`, `--resume`, `--session-file`, `--list-sessions`, `--delete-session` | no approval channel; interrupt means killing the process |

~~**So the build drives both**, and the split is forced rather than chosen:~~

| ~~`/v1` surface~~ | ~~Where it comes from~~ |
|---|---|
| ~~permissions, tool side effects, streamed events~~ | ~~**ACP**~~ |
| ~~session create and resume~~ | ~~**CLI**~~ |
| ~~`GET /v1/sessions`, `DELETE`, `POST …/interrupt`~~ | ~~**neither — our own store, and a process kill**~~ |

> **SUPERSEDED 2026-08-11 by GP-41: this build is CLI-only.** The table above is
> struck rather than deleted because it was acted on — `acp.py` existed, was
> tested and was removed. **Everything above the strike is still true**: there
> are two interfaces, neither is complete, and the id namespace is shared. What
> was wrong was the conclusion that both should be driven, and three
> measurements took it apart: ACP cannot resume (GP-38), its tool stream is not
> richer (GP-40), and its permission channel is a question this service would ask
> itself and answer from a policy file it wrote.

## GP-02 — six ACP methods are not registered, and it is not lazy registration

Sending each method over a real handshake and reading the JSON-RPC error code:
`-32601` means the method does not exist; `-32000` and `-32603` mean the handler
was reached and disliked the credential or the deliberately junk parameters.

| Registered | Absent (`-32601`) |
|---|---|
| `initialize`, `session/new`, `session/load`, `session/prompt`, `session/set_model`, `session/set_mode`, `authenticate` | `session/list`, `session/close`, `session/cancel`, `session/resume`, `session/fork`, `session/set_config_option` |

**Re-asked with a live `sessionId` and all six still answer `-32601`**, which
discharges the obvious caveat: they are not registered lazily after a session
exists.

**`session/cancel` is the one that costs us.** `POST /v1/sessions/{sid}/interrupt`
is a route of the specification and there is no verb behind it. Combined with
GP-18 — turns that do not terminate — a wall-clock timeout enforced by killing
the subprocess is **mandatory**, not a refinement.

**The handshake declares this for free.** ACP defines a capability per optional
method under `agentCapabilities.sessionCapabilities`; Gemini returns **no
`sessionCapabilities` at all**. A build that reads the declaration rather than
probing gets the same answer with no round trips.

## GP-03 — `initialize` and `session/new` are a capabilities document

`initialize` needs **no credential**. `session/new` does — it answers
`-32000 "Gemini API key is missing or not configured."` — so the free live tier
on this target is one method wide.

`initialize` returns:

- **`authMethods`** — `oauth-personal`, `gemini-api-key`, `vertex-ai`, and
  `gateway` ("Use a custom AI API Gateway", `_meta.gateway.protocol: "google"`).
  Whether `gateway` reaches a non-Google endpoint is **unmeasured**.
- **`agentInfo`** — `{name: "gemini-cli", title, version}`, which is
  `capabilities.sdk` without parsing `--version`.
- **`agentCapabilities`** — `loadSession: true`,
  `promptCapabilities: {image, audio, embeddedContext}`,
  `mcpCapabilities: {http: true, sse: true}`.

`session/new` returns two catalogues worth publishing rather than hand-maintaining:

- **`modes.availableModes`** — `default` ("Prompts for approval"), `autoEdit`,
  `yolo`, `plan`. Note the spelling; see GP-25.
- **`models.availableModels`** — `auto` ("Let Gemini CLI decide…"),
  `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.5-flash`.

## GP-04 — ACP hands the host the permission decision AND the file I/O

Measured on a turn that had to create a file. The agent called **into the
client**:

```
fs/read_text_file            {"path": "…/acp-hello.txt"}
session/request_permission   options: [{optionId: "proceed_always", kind: "allow_always"},
                                       {optionId: "proceed_once",   kind: "allow_once"}, …]
fs/read_text_file            {"path": "…/acp-hello.txt"}
fs/write_text_file           {"path": "…/acp-hello.txt", "content": "HELLO"}
```

**The file was written by the client, not the agent.** This is a materially
stronger position than either shipped build in this repository: one confines the
agent with the container alone, the other needs `seccomp=unconfined` for its
sandbox to start, and both had to work to become the approver. Here the approval
is a documented protocol method and the side effect is ours to perform or refuse.

**Answering `allow_always` changes the session mode**, and the agent announces it
in the message stream rather than as a structured event — see GP-05.

## GP-05 — what `session/update` streams, and the one wart in it

Kinds observed in a single turn: `agent_message_chunk` (×3, the answer in
pieces), `agent_thought_chunk` (reasoning, separated from the answer),
`tool_call_update` (`status`, `title`, and a **`diff`** content block carrying
path, old text and new text), `available_commands_update` (the slash-command
catalogue, unprompted).

**`tool_call_update` is richer than the CLI's `tool_result`**, whose `output` is
empty for most tools (GP-17).

**The wart: a mode change arrives as `agent_message_chunk` with the literal text
`[MODE_UPDATE] autoEdit`.** It is not a structured event. **A service that
streams `agent_message_chunk` straight through to a consumer will emit
`[MODE_UPDATE] autoEdit` into the conversation as assistant prose.** Filter it.

**`session/prompt`'s reply carries usage**: `stopReason: "end_turn"` and
`_meta.quota.model_usage`, a per-model token breakdown — the same figures the CLI
puts in `stats.models`, so either interface can feed `model_usage`.

---

# B. Boot, credentials, and exit codes

## GP-06 — the exit codes, all measured

| Code | Meaning | How it was produced |
|---|---|---|
| `0` | success — **including a run that declined to do the work** (GP-18) | any turn |
| `1` | invalid flag *value* (yargs), and mutually-exclusive flags | `--approval-mode nonsense`; `--session-file` with `--session-id` |
| `41` | **no auth method** — the code a boot gate keys on | a keyless run |
| `42` | **resume target not found** | `--resume <uuid>` after GP-10 has eaten the session |
| `44` | **sandbox requested, no runtime** | `--sandbox` inside a container (GP-30) |
| `55` | **untrusted folder** — a hard refusal, zero turns | any run without a trust override |
| `53` | turn limit exceeded — **documented, never reproduced here** | — |

**`42` maps to 404, not 400.** The published table calls it "input error" and the
only thing measured to produce it is a resume target that does not resolve.

## GP-07 — the credential gate publishes its own variable list

A keyless run exits `41` and names what it accepts:

> Please set an Auth method in your `<home>/.gemini/settings.json` **or specify
> one of the following environment variables**: `GEMINI_API_KEY`,
> `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_GCA`

**That is `credential_sources` and `provider_selectors` exactly** — one real
credential, two provider selectors — so the pre-boot specification publishes a
list nobody invented.

**`settings.json` is a fourth auth channel a boot gate cannot see.** A mounted
volume can be authenticated with no environment variable set. The Codex build
already meets this and says so in its own refusal message; reuse that sentence
rather than rediscover it.

## GP-08 — `--skip-trust` and `GEMINI_CLI_TRUST_WORKSPACE` are NOT equivalent

**The CLI offers them as alternatives and they behave differently.** Its refusal
reads *"either use `--skip-trust`, set the `GEMINI_CLI_TRUST_WORKSPACE=true`
environment variable, or trust this directory in interactive mode."*

Same workspace, same prompt, same registered MCP server:

| Override | Result |
|---|---|
| `--skip-trust` | the run proceeds — **and the agent has no MCP servers at all** |
| `GEMINI_CLI_TRUST_WORKSPACE=true` | the run proceeds and calls the MCP tool |

**Under the flag nothing warns.** stderr never mentions trust; the only symptom
is the model saying the tool is "not in my current toolset", which is
indistinguishable from a model that chose not to use it. `gemini mcp list` in the
same directory is explicit where the run is silent:

> Warning: MCP servers are configured but disabled because this folder is
> untrusted. **User-level servers are also suppressed** in untrusted folders.
> `○ spikeserver: … (stdio) - Disabled`

**And `gemini mcp list --skip-trust` prints usage and exits** — the subcommand
does not accept the flag at all.

**So the build sets the environment variable.** An untrusted folder otherwise
refuses the whole run with exit `55` (GP-06).

## GP-09 — the envelope is on stdout when it works, stderr when it fails, and absent when it fails early

- **Success**: ~2 KB of JSON on **stdout**; stderr carries terminal-capability
  noise only.
- **Failure with a credential problem** (exit `41`): **stdout is 0 bytes** and the
  whole JSON document — including a minted `session_id` and
  `error: {type, message, code}` — is on **stderr**.
- **Failure before startup completes** (exit `44`, GP-30): stdout 0 bytes and
  stderr carries **139 bytes of plain text, not JSON**.

**A wrapper must read both streams and must tolerate a bare string.** Reading
only stdout produces a wrapper that works against a good key and reports nothing
against a broken one; assuming stderr parses as JSON produces one that crashes on
the sandbox error.

**A `session_id` is minted even on a failed run**, so `sdk_session_id` exists
before the first model call.

---

# C. Sessions

## GP-10 — `--resume` works exactly ONCE and then destroys the transcript

Three turns, one supplied UUID, a fresh project directory:

| Turn | Result | On disk | `--list-sessions` |
|---|---|---|---|
| 1 `--session-id <U>` | works; `session_id` echoes `<U>` | `session-…-<short>.jsonl`, 15 KB | 1 session |
| 2 `--resume <U>` | **works** — the conversation is recalled | the 15 KB grows to 32 KB, **plus a new 1 KB stub** | **"No previous sessions found"** |
| 3 `--resume <U>` | **exit 42**, stdout 0 bytes | **the 32 KB transcript is GONE**; only the stub remains | none |

**The mechanism, read from the bundle**, and it is a collateral delete:

1. A record whose metadata fails `hasResumableContent` maps to `null`. The stub
   the resume writes contains only the injected `<session_context>` message, so
   it qualifies.
2. `identifySessionsToDelete` opens with
   `sessionsToDelete.push(...allFiles.filter(e => e.sessionInfo === null))` —
   **every unresumable file is queued for deletion unconditionally**, with no age
   or count test.
3. Deletion derives an **8-character short id from the filename** and removes
   *every file sharing it*. The stub and the real transcript share one.

**So the garbage stub takes the real transcript with it.** `sessionRetention.enabled`
defaults to `true` in the settings schema while the parent object's own default is
`undefined`; whether the cleanup pass is what fired was not chased further. **The
deletion is measured either way.**

**Consequence: never build `options.resume` on `--resume`.** See GP-11.

## GP-11 — `--session-file` is the only durable resume, and it costs the session id

Copy the transcript out, as a database would, then resume from the copy
repeatedly:

| Attempt | Result | The file afterwards |
|---|---|---|
| 1 | the conversation is recalled | unchanged, 30992 B |
| 2 | recalled again | unchanged, 30992 B |

**Each run mints a NEW `session_id`**, because the flag loads a transcript rather
than adopting an identity.

**And the three flags cannot be combined** — exit `1`:

> The flags `--resume`, `--session-id`, and `--session-file` are mutually
> exclusive. Please provide only one.

**So a caller-supplied `sdk_session_id` and durable multi-turn resume are
mutually exclusive on this target.** GP-34 decides which one this build keeps,
and GP-35 says what `options.resume` accepts as a result. The design that follows: persist the
transcript ourselves, materialise it to a temporary JSON on resume, pass
`--session-file`, and treat `sdk_session_id` as **per-turn** rather than
per-session. The service's own session id is stable because it is ours.

## GP-12 — an ACP session IS a CLI session, but ACP will not take an id

The `sessionId` minted by `session/new` appears verbatim in `--list-sessions`
from the same working directory, titled with its first prompt. **One object, one
namespace, two interfaces** — so the build may mix them.

**`session/new` accepts no caller-supplied id.** A caller-supplied UUID exists
only on the CLI's `--session-id`, which GP-11 rules out for durable use anyway.

## GP-13 — sessions live in `$HOME`, not the project, with no override

`Storage.getProjectTempDir()` is not under the project despite the name: a
session is written to **`$HOME/.gemini/tmp/<projectIdentifier>/chats/`**, where
`<projectIdentifier>` comes from a registry at `$HOME/.gemini/projects.json` and
is derived from the working directory's basename.

**There is no environment override** for the `.gemini` location; the only
fallback is `os.tmpdir()` when `homedir()` is empty, which is worse.

**In a container this means sessions die with the container.** Mounting a volume
over the whole `.gemini` directory would work — it must be the whole directory,
because `projects.json` sits at the top and the chats path is derived from it —
but it puts a writable host volume inside the agent's own HOME. **`--session-file`
plus our own store (GP-11) is the answer instead**, which is how the Claude build
already solves the same problem.

## GP-14 — `--list-sessions` cannot answer `GET /v1/sessions`

It filters on `hasResumableContent` and drops anything that fails it, which is
how a session that is still resumable disappears from the listing (GP-10, turn 2)
and how a session about to be deleted still appears. **Answer the route from our
own store.** The same goes for `DELETE`.

## GP-34 — a caller-supplied `sdk_session_id` is REFUSED, and the build mints one per turn

**Decision, 2026-08-11.** `capabilities.allow_supplied_sdk_session_id` is
**`false`**, and `POST /v1/sessions` carrying one answers **400** with a named
problem `type`, refused before any subprocess starts.

**It is forced by GP-11, not chosen.** Honouring the field needs
`--session-id`, which cannot be combined with `--session-file`; and
`--session-file` is the only resume that survives a second turn. ACP's
`session/new` takes no id either (GP-12). **So the only way to accept a
caller's id is to honour it for the first turn and silently stop honouring it
afterwards** — which breaks the one guarantee supplying it provides, and breaks
it invisibly. The specification's own description of the field says a build
returns `false` "when the underlying SDK mints its own conversation id with no
way to override it", and that is exactly this build.

**Never a silent drop.** A 400 that says why is the whole point; a build that
took the field and returned a different id would be worse than one that refuses.

### What is reported instead, and why it needs no specification change

**The build still reports an `sdk_session_id`; it simply chooses the value** —
which is what the field's description already anticipates. On this target the
value **changes every turn**, because `--session-file` mints a fresh id per run.

**That fits the published semantics unchanged**, and this was checked rather than
assumed. `RunResponse.session_id` is described as *"the SDK's OWN conversation id
for this run"* — **for this run**, not for the session — and
`SessionRecord.sdk_session_id` is defined as matching
`TurnRecord.sdk_session_id` on `SessionRecord.last_turn`. The specification
already models this identifier as per-turn and reports the most recent one.
**A build whose id genuinely changes each turn is the case those words describe.**

So: on a turn response, the id of that turn. On a `SessionRecord`, the most
recent turn's, and `null` before any turn has been taken.

**The service's own `session_id` is stable and is the key**, on this build as on
every other. Nothing a consumer needs to hold onto changes.

## GP-35 — `options.resume` takes any SDK id this build has issued for that session

**Decision, 2026-08-11**, and it is the consequence of GP-34 that a consumer
actually touches.

`options.resume` takes an **SDK** id, not the service-side handle — that is the
specification's, not this build's. But GP-34 means there is no single SDK id
naming a Gemini conversation: each turn has its own.

**So this build records every SDK id it has issued for a session and resolves any
of them back to that session's stored transcript**, which it then materialises
and passes to `--session-file` (GP-11). A caller that kept the id from turn 1 and
a caller that kept the id from turn 9 both resume the same conversation.

**The alternative — accepting only the most recent id — was rejected.** It makes
correctness depend on a client having read the newest response, which is exactly
the situation a resume exists to recover from: the client that lost its
connection is the one holding a stale id.

**An id this build never issued is a 400**, not a silent new conversation.

## GP-36 — resume needs a transcript WE control, which is not the same as a database

**Decision, 2026-08-11, and it corrects a claim made while writing GP-35.** The
first version of this build's manifest said persistence was mandatory here
because `options.resume` could not work without it. **That is wrong.**

GP-10 destroys the agent's own transcript on its first resume, so this build
cannot resume from the agent's storage. What it needs is **a copy the agent's
cleanup cannot reach** — and this service's own scratch directory is such a
place. `--session-file` takes a path; it does not care whether the path came
from a database.

| Configuration | What resume does |
|---|---|
| no database | works for the life of the container, from our own copy of the transcript |
| database configured | also survives a container restart, because the copy is re-materialised from the store |

**So persistence stays optional on this build, exactly as on the other two**, and
for the same reason: persistence is a feature of `agent-service`, not of the
agent. The difference here is only that the *local* copy is mandatory — on the
other builds the agent's own transcript would have served.

**Recorded because the wrong version was believed for the length of one file.**
A dependency declared for a reason that does not hold is how a build acquires a
requirement nobody can later explain.

## GP-37 — a `--admin-policy` path that does not exist is silently ignored

**Measured 2026-08-11, and it is worse than GP-25.** A malformed policy file at
least shouts on stderr. A *missing* one says nothing at all:

| `--admin-policy` argument | exit | stderr | policy applied |
|---|---|---|---|
| a valid file | 0 | — | yes |
| a **malformed** file (GP-25) | 0 | `[ADMIN] Policy file error …` | **no** — the whole file is discarded |
| **a path that does not exist** | **0** | **0 bytes** | **no** |
| a directory instead of a file | 0 | 0 bytes | no |
| an empty string | 0 | 0 bytes | no |

**So there are two ways to run with no boundary, and only one of them leaves
evidence.** A service that generates a policy to a path and mistypes it, or
writes it somewhere that is cleaned between generation and use, gets a fully
permitted agent and a completely clean run.

**Consequences for the preflight, all three now implemented:**

1. **Check the file exists in Python first.** The agent will not do it, and no
   amount of reading its output can distinguish "no policy named" from "policy
   named and fine".
2. **Pass an absolute path.** This was found because a relative path was resolved
   against a `cwd` that was already the file's own directory, so the file was
   simply not there — the same silent outcome as a typo.
3. **Require the probe run to have SUCCEEDED before believing its silence.**
   Absence of the error marker means nothing if the process never started.

### The negative control is what caught all of this

The first version of `validate_admin_policy` stripped the environment to `PATH`
alone. On Windows that is not enough to start the agent's `.cmd` shim: it exited
1 with **zero bytes on either stream**, so the marker was absent, so validation
**passed — always, for every file, valid or not.**

**The positive test passed too, and vacuously.** A preflight that cannot fail
looks exactly like a preflight that succeeds. What separated them was a test that
fed it a file known to be bad and demanded a rejection.

**So: a validator ships with its own negative control, or it ships unverified.**
This is the same defect this repository keeps finding — a capability published
and enforced by nothing — reproduced inside the very code written to prevent it.

## GP-38 — ACP cannot resume: `session/load` is registered and refuses regardless

**Measured 2026-08-11, and it decides the runner's architecture.** GP-02 found
`session/resume` and `session/fork` unregistered but `session/load` *dispatched*,
which left open the possibility that a conversation could be reloaded over ACP.
It cannot.

| Attempt | Result |
|---|---|
| `session/load` with a bogus id, no credential | `-32000 Authentication required` |
| …with `GEMINI_API_KEY` set | `-32000 Authentication required` |
| …after `authenticate {"methodId": "gemini-api-key"}`, **which returns `{}`** | `-32000 Authentication required` |
| …with the real session id, in a HOME holding that transcript | `-32000 Authentication required` |
| `session/prompt` on the id anyway | `-32602 Session not found` |

**So `authenticate` succeeds and changes nothing**, and `session/load` refuses in
every configuration tried. It is registered without being usable — the same
shape as a capability published and enforced by nothing, arriving from the other
side.

**`--session-file` does not feed it either.** Passing `--acp --session-file
<path>` is accepted, and `session/load` still resolves against the agent's own
chats directory: *"Searched for sessions in …\\.gemini\\tmp\\<project>\\chats"*.
The flag is a CLI-turn mechanism and does not reach the protocol.

### What this forces

**Within one session, nothing changes**: a live ACP process holds the
conversation, so turns 2..N are `session/prompt` on a session that never went
away. That is how the other two builds work too, and it is where the permission
channel and the `fs/*` inversion (GP-04) apply.

**`options.resume` is the only casualty** — continuing a conversation whose agent
process is gone. It cannot be done over ACP at all, so it can only be done on the
CLI with `--session-file` (GP-11), **where there is no permission channel and no
host-performed file I/O.** The boundary would silently become policy-only for
that turn, which is a different guarantee under the same name.

## GP-39 — the agent's storage location IS controllable, through `HOME`

**Measured 2026-08-11.** GP-13 said a transcript lands under `$HOME/.gemini/tmp/`
with no environment override, and treated that as fixed. **`HOME` itself is the
override.** Running the agent with `HOME` and `USERPROFILE` pointed at a
service-owned directory put the transcript exactly there:

```
<our dir>/.gemini/tmp/<workspace basename>/chats/session-<timestamp>-<short>.jsonl
```

**So this service can own the agent's session storage** rather than sharing the
container's home, which is worth having for three reasons: the transcript is
where we can copy it before the agent's own cleanup reaches it (GP-10), one
session cannot see another's history, and the project identifier — derived from
the *workspace basename*, lowercased — stops being a collision risk between
sessions that happen to mount directories of the same name.

**It does not rescue `session/load`** (GP-38): a transcript sitting in a HOME the
agent is using is still refused. What it buys is control of the file, not a way
to reload it.

## GP-40 — ACP's tool stream is NOT richer than the CLI's, measured side by side

**The same prompt on both interfaces** — a listing, a read, a search and a write
— run to decide whether ACP earns a second code path in this build.

**GP-17 is confirmed and generalised on the CLI side**, six calls across five
tools: `list_directory`, `grep_search` and `write_file` return **no `output` key
at all**, `read_file` returns an **empty string**, and the only content comes
from `update_topic`, the agent's own narration tool.

**ACP is no better.** Its `tool_call` / `tool_call_update` pairs carry
`content: []` for exactly those tools; content appears only on a *failed* write
(an error string), on `update_topic`, and on shell commands.

**So neither interface reports what a tool produced.** The `diff` recorded in
GP-05 was a *host-performed* write arriving back through `fs/write_text_file` —
not the agent reporting a result. In this run the agent's own `write_file` failed
three times and never delegated one.

### What each interface actually gives, since it is not what was assumed

| | ACP | CLI `stream-json` |
|---|---|---|
| tool identity | a human `title` (`seed.txt`, `'alpha'`) | `tool_name` **plus structured `parameters`** |
| lifecycle | `in_progress` → `completed` / `failed` | `tool_use` → `tool_result`, correlated by `tool_id` |
| result content | `[]` | absent or empty |
| the host performs the I/O | **yes** — six `fs/read_text_file` callbacks | no |

**The CLI's `parameters` are the better of the two for a consumer** rendering an
agent loop: `{"file_path": "seed.txt"}` is structured where a title is prose.

**So the case for ACP rests on one property only** — the host performs the file
I/O and can therefore refuse a path (GP-04). It is not richer and it is not
better instrumented, which is what this measurement was run to find out.

**One caveat, because the run was not clean.** That ACP turn carried **no admin
policy**, ran for over ten minutes, failed its writes repeatedly and escalated to
shell commands — the GP-18 flailing pattern that GP-19 shows a policy removes. It
is a single run, and the table above is about which fields carry content, not
about which interface behaves better.

## GP-41 — this build is CLI-only, and ACP is not used at all

**Decision, 2026-08-11 (user), reversing GP-01.** Every `/v1` surface is served
by the CLI plus this service's own store. `--acp` is not spoken, and `acp.py`
was deleted after being written and tested.

| `/v1` surface | Where it comes from |
|---|---|
| a turn, its events, its tool loop | **CLI** `-p … -o stream-json` |
| session create | **CLI** `--session-id` |
| `options.resume` | **CLI** `--session-file`, from our own transcript copy |
| `GET /v1/sessions`, `DELETE` | **our own store** — the agent's listing is unreliable (GP-14) |
| `POST …/interrupt` | **kill the process** — no verb exists on either interface (GP-02) |
| the tool boundary | **the generated admin policy** (GP-19), which both interfaces enforced identically anyway (GP-27) |

**Three measurements decided it, none of them available when GP-01 was written:**

1. **ACP cannot resume** (GP-38). `session/load` is registered and refuses in
   every configuration, so a two-interface build would have had to run resumed
   turns on the CLI regardless — with a *different* enforcement shape from a live
   turn, under the same name.
2. **ACP's stream is not richer** (GP-40). Measured side by side, its tool
   `content` is `[]` for the same tools the CLI leaves empty, and the CLI's
   structured `parameters` beat ACP's prose `title` for a consumer.
3. **Its permission channel has nobody to ask.** `session/request_permission` is
   a genuine host-side approval call, and this specification exposes no route for
   asking the *consumer* mid-turn — there is `permission_mode`, not a callback.
   The service would answer it from the policy file it had just written, which is
   the policy deciding twice rather than a second control.

**What is genuinely given up, stated plainly:** host-performed `fs/*`, and with
it the ability to refuse an individual path without the agent's cooperation
(GP-04). That was the strongest property this target had. It is redundant rather
than unique — the policy denies the tool, the agent's own guard refuses a file
tool that wanders (GP-19), and the container is the outer boundary — but
redundancy is worth something and this build no longer has it.

**What is bought:** one code path, one enforcement story that does not change
between a live turn and a resumed one, and no dependence on a protocol whose
session methods are half absent (GP-02) and whose `session/load` is registered
without working (GP-38).

**If ACP is revisited**, the trigger is a specification that carries approvals to
the consumer, or a release in which `session/load` works. Neither is true today.

## GP-42 — the endpoint variable is `GOOGLE_GEMINI_BASE_URL`, read from the binary

**Measured 2026-08-11, free**, and it closes a gap that two correct positions had
left open.

`process.env["GOOGLE_GEMINI_BASE_URL"]` appears **32 times** in the 0.54.4 bundle
and is interpolated into the request URL. `GOOGLE_VERTEX_BASE_URL` (20) is its
Vertex counterpart; `CODE_ASSIST_ENDPOINT` and `GEMINI_TELEMETRY_OTLP_ENDPOINT`
are for other subsystems.

### Why this was `null` first, and why both positions were right

`agent-service-openapi` published `endpoint_source: null` on the reasoning in
GP-03: the agent declares a custom-gateway auth method, nobody had tested
whether it reaches a non-Google endpoint, and **a plausible variable name is not
a measurement.**

The platform's boot-gate suite then refused the null outright — AS-29 requires
every image to name one variable a provisioner can set, and "unmeasured" is not
an answer a provisioner can act on.

**Neither position was wrong; what was missing was the measurement.** The name
was in the binary the whole time, free to read, and the caution had prevented a
guess rather than a fact. **The general form: when honesty and a clause
disagree, the resolution is usually a measurement neither side had taken.**

**Two claims, kept apart.** *Which variable the agent reads* is now measured.
*Whether pointing it at a non-Google endpoint actually works* is still
unmeasured, and GP-03's caution stands on that half.

## GP-15 — the `stream-json` events, as EMITTED

Keys observed on a real turn, which is not the same as the keys the emitter is
constructed with:

| Event | Keys beside `type` |
|---|---|
| `init` | `timestamp`, `session_id`, `model` |
| `message` | `timestamp`, `role`, `content`, **`delta`** |
| `tool_use` | `timestamp`, `tool_name`, `tool_id`, `parameters` |
| `tool_result` | `timestamp`, `tool_id`, `status`, `output` (and `error` when it failed) |
| `result` | `timestamp`, `status`, `stats` |

**Two things a source reading does not show.** `message` carries **`delta: true`**
— assistant text arrives in pieces and there is no terminal non-delta message —
and **`init.model` is the literal string `"auto"`**, the routing policy rather
than a model id.

**So a real model id does not exist until the `result` event.** Anything
promising one at stream-open must either withhold it or publish `"auto"`.

**`tool_id` correlates `tool_use` with `tool_result`**, which is more than the
Claude build's stream gives without bookkeeping.

## GP-16 — one turn bills TWO models, and there is no monetary figure

A one-word prompt under the default `auto` routing:

| Model | Role | Total tokens |
|---|---|---|
| `gemini-3.5-flash` | `main` | 8044 |
| `gemini-3.1-flash-lite` | `utility_router` | 1311 |

**`stats.models` is `model_usage` already**, keyed by model id and **per-turn** —
the opposite of the Claude build, where `model_usage` is cumulative for the
connection and summing it across turns multiplies the real figure.

**A router model is billed on every turn.** Reporting only the answering model
under-reports tokens.

**Pinning a model with `-m` removes the router**: the same prompt then bills one
model with role `main`. Measured on `gemini-3.1-flash-lite`.

**No USD anywhere** — tokens and latency only. Third target of three, which is
what made `SessionRecord.total_cost_usd` nullable.

## GP-17 — `tool_result.output` is empty for most tools

Measured: `read_file` returns `output: ''`, `write_file` and `list_directory`
return no `output` key at all, and only `update_topic` returned prose. **The tool
loop is observable in name, parameters and correlation id; its result content is
not.** ACP's `tool_call_update` carries a diff (GP-05) and is the better source
where both are available.

---

# E. The boundary: approval modes and the Policy Engine

## GP-18 — `--approval-mode` alone is neither a boundary nor deterministic

**Nine trials of one identical prompt** ("create a file containing HELLO") under
`--approval-mode default`, across two independent probe runs:

| Outcome | Count |
|---|---|
| wrote the file | **1** |
| finished having done nothing (`exit 0`, `result.status: "success"`) | 3 |
| **never terminated** (still running at the cap) | 5 |

`invoke_agent` — the subagent tool — appears in most of them, and one trial
reached `exit_plan_mode` and then wrote. **The agent can talk itself past the
mode.**

`auto_edit` and `yolo` wrote the file every time, in seconds, with two tool calls.

**Three consequences.** The mode cannot be the sandbox — GP-19 can. A refusal is
invisible: every finished trial exited `0` with `status: "success"` whether it did
the work or declined, so **a build that maps `status` to "the turn succeeded" will
report success for work that never happened.** And a turn can hang, which with
GP-02 means a timeout plus a process kill.

**This entry is model-dependent** and was measured on `gemini-3.5-flash`. GP-19
removes the behaviour entirely, which is the point.

## GP-19 — `deny *` plus an allowlist is the boundary, and it is deterministic

```toml
[[rule]]
toolName = "*"
decision = "deny"
priority = 900

[[rule]]
toolName = ["read_file", "write_file", "list_directory"]
decision = "allow"
priority = 950
```

**Under `yolo`, denied tools are gone from the registry**, and the refusal is
typed and machine-readable in the event stream:

```json
{"type": "tool_not_registered", "message": "Tool \"run_shell_command\" not found. Did you mean \"read_file\"?"}
```

**Under `default`, the same policy makes GP-18's chaos disappear**: three trials,
three writes, one `write_file` call each, 10–13 seconds. **The hangs were an agent
searching for a way to do a job it had not been told it could do.**

**A denied tool is removed from the model's context**, which is why this works and
why GP-20 does not.

**A second boundary holds unprompted**: reading outside the working directory
returns `{"type": "invalid_tool_params", "message": "Path not in workspace: …"}`.

**`denyMessage` never appears** — the tool was removed rather than refused, so the
model receives the generic not-found. Do not use it to explain a denial.

## GP-20 — deny-by-name is worthless while the shell is allowed

Denying `write_file` by name, under `yolo`: **the file was written anyway**, via
`run_shell_command` (`Set-Content …`; a second run produced
`[System.IO.File]::WriteAllText(…)`). The agent never attempted `write_file` —
by GP-19's mechanism it experiences a world where that tool was never offered and
solves the problem with what remains.

**Deny by wildcard and allow explicitly. Never deny by name, and never leave
`run_shell_command` unrestricted on an allowlist meant to prevent writes.**

## GP-21 — the tier model is real: admin beats user, priority does not save you

Two contradictory files loaded at once:

| Tier | Flag | Rule | In-tier priority |
|---|---|---|---|
| admin | `--admin-policy` | `toolName = "*"`, deny | 900 |
| user | `--policy` | `write_file`, allow | **999**, the maximum |

**Admin won** — no file, exit 0, clean termination — confirming
`final = tier_base + (priority / 1000)`: user `4.999` against admin `5.900`.

**Anything the service imposes goes in `--admin-policy`**, so a fragment derived
from a caller's `allowed_tools`, which would naturally load as `--policy`, can
widen nothing it was not given.

## GP-22 — `ask_user` does NOT become `deny` in headless, contrary to the documentation

The published reference states it twice: *"treated as deny in headless mode"*.
Measured with `write_file` set to `ask_user`:

```
tool_use    write_file
tool_result error  {"type": "unhandled_exception",
                    "message": "Tool execution for \"WriteFile\" requires user
                                confirmation, which is not supported in non-interactive mode"}
tool_use    write_file        ← it tried again
```

**Three differences from a `deny`:** the tool stays **registered**, so the model
calls it and gets an exception instead of adapting; the error type is
`unhandled_exception`, not a policy classification, so a wrapper mapping it to
5xx reports a server fault for a configuration decision; and the flailing of
GP-18 returns — of two runs, one hit the cap and the other finished only after
six tool calls and three distinct error types.

**Emit `allow` and `deny` only.**

## GP-23 — `commandPrefix` is sound: sub-commands, wrappers and unparseable input are all caught

With `deny *` plus `commandPrefix = "echo"`, under `yolo`:

| Command | Result |
|---|---|
| `echo hi && node -e "…unlinkSync('seed.txt')"` | **denied** — `{"type": "policy_violation"}` |
| `bash -c "rm seed.txt"` | **denied** — `policy_violation` |
| `node -e "console.log(1` (unparseable) | **denied** — `policy_violation` |

**Each sub-command is re-checked independently and any `DENY` short-circuits the
call**, so `&&` and `;` smuggle nothing past the prefix. `stripShellWrapper`
re-checks the *inside* of `bash -c "…"`. An unparseable command is denied because
the deny rule returns before the parse-failure branch — the fallback that turns
an unparseable command into an `ALLOW` under `yolo` sits behind a matched **allow**
rule, which the recommended shape never gives the shell.

**Matching is token-aware.** The generated pattern is `"command":"<prefix>`
followed by `(?:[\s"]|\\")`, so the prefix must end at whitespace or at the end of
the command: **`commandPrefix = "git"` does not match `gitleaks …`**.

**`policy_violation` is a third typed refusal**, beside `tool_not_registered`
(GP-19) and `unhandled_exception` (GP-22).

## GP-24 — the redirection guard is OFF under `yolo` and `auto_edit`

**`echo HELLO > hello.txt` writes an arbitrary file** under `yolo` with an
`echo`-only allowlist. Not a parser failure — an explicit branch:

```js
shouldDowngradeForRedirection(command, allowRedirection) {
  if (allowRedirection) return false;
  if (!hasRedirection(command)) return false;
  if (this.approvalMode === ApprovalMode.AUTO_EDIT ||
      this.approvalMode === ApprovalMode.YOLO) { return false; }
  return true;
}
```

**The guard is present in the two careful modes and switched off in the two
permissive ones**, so a service that sets `yolo` because it trusts its policy
gets the opposite of what it intended. And in `default` the guard does not deny —
it downgrades to `ask_user`, which by GP-22 is the broken path. **There is no
configuration in which a redirected command is cleanly denied by the built-in
guard.**

**Close it with a rule instead**, which works under `yolo`:

```toml
[[rule]]
toolName = "run_shell_command"
commandRegex = '[^"]*>'
decision = "deny"
priority = 990
```

`commandRegex` is anchored just after the opening quote of the serialized
command, so `[^"]*>` reads as "contains a `>`". Measured: `policy_violation`,
nothing written.

## GP-25 — `modes` scopes exactly; the spelling trap voids the ENTIRE file, fail-open

**Scoping works.** One file with `modes = ["yolo"]` on a deny rule: under `yolo`
the rule fires and the tool is deregistered; under `default` the same file allows
the write.

**The vocabulary trap.** Both spellings are printed by the tool itself:

| Where | Accepted spelling |
|---|---|
| `--approval-mode`, per its own `--help` | `default`, **`auto_edit`**, `yolo`, `plan` |
| policy `modes = [...]`, and ACP's `availableModes` | `default`, **`autoEdit`**, `yolo`, `plan` |

**A file whose *second* rule carries `modes = ["auto_edit"]` is discarded
entirely — including its valid first rule.** Measured with a `deny *` sitting
above the bad rule:

```
stderr:  [ADMIN] Policy file error … Invalid enum value.
         Expected 'default' | 'autoEdit' | 'yolo' | 'plan', received 'auto_edit'
exit:    0
result:  the file was created — no policy applied at all
```

**Exit code `0`. Nothing in the event stream. The only signal is stderr.** This is
the worst failure shape on this target: a boundary that silently ceases to exist,
on a typo, in the direction of more permission, while the run reports success.

**The defence is free** — see GP-26.

## GP-26 — validate every policy file keylessly, before use

```
gemini --list-sessions --admin-policy <file>
```

Loads and validates the policy with **no credential and no turn**. Measured:
`[ADMIN] Policy file error` on stderr for a bad file, nothing for good ones.
**The exit code is `0` either way**, so the check is on stderr text.

**Refuse to start a turn if the string appears.** Better still, **generate the
TOML from a typed structure rather than templating strings** — code that cannot
spell `auto_edit` into a `modes` field cannot fall into GP-25.

## GP-27 — the policy reaches ACP, and sits ahead of the permission channel

The same admin deny-all policy, applied to an ACP session:

| | Without policy | With the policy |
|---|---|---|
| the file was created | **yes**, by the host via `fs/write_text_file` | **no** |
| agent → host requests | **4** | **0** |
| `stopReason` | `end_turn` | `end_turn`, clean |

**Zero callbacks.** The host was never asked for permission and never asked to
write, because the tools were not in the registry to begin with. **So the policy
and `session/request_permission` compose rather than compete**: the policy is the
hard boundary, and the permission call decides only what the policy already
permits. One boundary covers both interfaces, which is what makes GP-01's split
safe.

---

# F. MCP

## GP-28 — MCP works, tools are `mcp_<server>_<tool>`, and server names must avoid underscores

Measured with a dependency-free stdio MCP server: the agent discovered and called
**`mcp_spikeserver_magic_word`** and returned a string it could not have invented.

**The naming is why a server name must not contain an underscore** — the parser
splits on the first `_` after `mcp_`, so `spike_server` makes a rule's
`mcpName`/`toolName` split ambiguous. Name servers `spikeserver`, not
`spike_server`.

**MCP requires the trust environment variable, not `--skip-trust`** — GP-08 is
where that was found and it is the single most consequential recipe change on
this target.

## GP-29 — `mcpName` governs MCP tools, but `toolName` is required despite the documentation

| Policy | Result |
|---|---|
| `deny *` + `mcpName = "spikeserver"`, `toolName = "*"`, allow | the MCP tool runs; every built-in is denied |
| …plus `mcpName` + `toolName = "magic_word"`, deny | **the tool is not even attempted** |

**So `allowed_tools` reaches MCP** — a whole server, or a server with one tool
carved out.

**The documented shape does not validate.** The reference says "target all tools
from a server by omitting `toolName`"; omitting it gives
`Field "rule.1.toolName": Invalid input`, and by GP-25 a rejected file is
discarded **entirely**, taking its `deny *` with it. **This is the second
documentation error in the Policy Engine**, after GP-22.

**GP-26's free preflight caught it before a turn was spent**, which is exactly
what that rule is for.

## GP-30 — ACP is the better MCP path: per-session servers, no trust override

`session/new` takes an `mcpServers` array, so the client hands the server over per
session with no `settings.json` and nothing written into the workspace.

**It works with no trust override at all** — measured with and without
`GEMINI_CLI_TRUST_WORKSPACE`, the tool ran either way and stderr mentioned trust
zero times. **The gate suppresses servers the workspace *configures*, not servers
the client *supplies*.** For a service assembling each session's MCP set from a
request, that is the natural shape.

**Permission still applies**: a `session/request_permission` callback arrived for
the MCP tool, and the `tool_call` update was titled
`magic_word (spikeserver MCP Server)`.

**One schema trap.** The stdio entry **requires `env`**, and `[]` is legal:

| Params | Result |
|---|---|
| `{name, command, args}` | `-32603`, `invalid_union`, complaining `path: ["headers"]` |
| `{name, command, args, env: []}` | **accepted** |
| `{type: "stdio", name, command, args, env: []}` | accepted |

**The error names the wrong branch** — `headers` belongs to the HTTP/SSE variant,
so omitting `env` makes the stdio branch fail and the union reports every
branch's complaint. Worth knowing before losing an hour to it.

**Unmeasured:** MCP over HTTP/SSE, which `mcpCapabilities` declares. Only stdio
was exercised.

---

# G. The container

## GP-31 — `--sandbox` does not work inside our container, and the container is the sandbox

The five backends are `docker`, `podman`, `sandbox-exec`, `runsc`, `lxc` — read
from the settings schema — and **every one is a container or VM runtime**, so
`--sandbox` inside a container needs a nested one.

Measured in a plain `node:22-slim` with the CLI installed and no docker socket
mounted:

| Run | Result |
|---|---|
| control, no `--sandbox` | **works** — full JSON envelope, real turn |
| `-s` / `--sandbox` | **exit 44**, stdout 0 bytes, before any model call |

```
GEMINI_SANDBOX is true but failed to determine command for sandbox;
install docker or podman or specify command in GEMINI_SANDBOX
```

**Do not mount the host's docker socket to fix this.** That hands the agent
control of the host's container runtime, which is a strictly worse boundary than
the one it was trying to add. **The container is the sandbox and the Policy
Engine (GP-19) is the tool boundary inside it.**

---

# H. Working on this build

## GP-32 — what costs nothing, and what the money actually goes on

**A large fraction of what decides this build's shape is free**: the ACP method
table and handshake (GP-02, GP-03), every exit code except the ones needing a
turn (GP-06), the credential gate (GP-07), `gemini mcp list` (GP-08), policy
validation (GP-26), and every source reading in this file.

**Run the free probe first.** It answers what it can with no credential, no turn
and no container.

**Where the money went, measured the hard way.** The spike that produced this file
was estimated at "cents" and cost about **10 USD**. The estimate was made from
prompt sizes and the prompts were never the cost: **a turn that cannot finish is
the expensive one** — GP-18's non-terminating runs each spent a full 150-second
cap driving `invoke_agent` subagents, and there were nine of them.

**So the two controls that matter are the cap and the model, not the prompt.**
Every live probe pins `-m gemini-3.1-flash-lite` (overridable by
`GEMINI_PROBE_MODEL`) and caps each run at 60 seconds — a run that is going to
finish finishes in 10–13 seconds. Pinning also removes the router model (GP-16).

## GP-33 — every finding here is pinned to 0.54.4, and there is no stability contract

There is no SDK and no semantic-versioning promise over the CLI's flags or over
which ACP methods it registers. **Every entry in this file is a measurement of one
build of one binary**, and the free tier in GP-32 is what makes re-verification
cheap enough to do on every upgrade.

**Recheck on upgrade, in this order**, because each is cheap and each invalidates
a lot if it moved: the ACP method table (GP-02), the handshake catalogues
(GP-03), the exit codes (GP-06), the policy schema and its enum spellings
(GP-25, GP-29), and the trust behaviour (GP-08).

## GP-43 — the agent calls `update_topic`, a tool it does not register, and its own `tool_calls` counter says 0

**Measured 2026-08-11 against the real binary in this build's container**, at a
cost of a few cheap turns.

The model emits a `tool_use` for **`update_topic`** — bookkeeping, with
`{title, summary}` parameters — and the CLI answers:

```json
{"type": "tool_result", "tool_id": "update_topic__UlHk6pUI", "status": "error",
 "output": "Tool \"update_topic\" not found. Did you mean one of: \"write_file\", \"read_file\", \"list_directory\"?",
 "error": {"type": "tool_not_registered", "message": "..."}}
```

**`tool_not_registered`, NOT a policy denial.** This matters because the obvious
reading — a generated allowlist denying a tool the agent wanted — is wrong, and
acting on it would mean adding `update_topic` to the allowlist, where it would do
nothing: the tool does not exist in headless mode at all. The agent's own
suggestion list (`write_file`, `read_file`, `list_directory`) is the allowlist
this service generated, which is what makes the misreading so easy.

**Intermittent, not per-turn.** "Say hello." produced no tool call; "Count from 1
to 5" produced one on two runs out of two. Treat it as a thing that happens, not
a thing that always happens.

**It is not free.** The failed call plus the recovery cost **1.6 s** on one
observed turn and **9.1 s** on another — the second more than doubling a turn
that would otherwise have taken four seconds.

**`stats.tool_calls` reported `0` on a turn carrying a `tool_use` and a
`tool_result`.** So the counter counts *successful registered* calls, and **a
consumer cannot use it to decide whether a turn used tools** — the event stream
is the only truthful account. This service reports both: `usage` passes the
agent's numbers through unchanged, and `events` carries what actually happened.

## GP-44 — a turn costs ~7,000 input tokens before the prompt is read

**Measured 2026-08-11** across six real turns through the HTTP surface, all with
`gemini-3.1-flash-lite` pinned:

| Prompt | `input_tokens` | `output_tokens` | `cached` |
|---|---|---|---|
| "Say hello." | 7,072 | 2 | 4,069 |
| "Reply with exactly the word: pineapple" | 7,076 | 1 | 4,069 |
| "Count from 1 to 5, one number per line." | 7,082 | 9 | 4,069 |

**The prompt is noise.** A three-word prompt and a nine-word prompt differ by ten
tokens against a floor of roughly seven thousand — the agent's system prompt and
tool declarations, of which about 4,069 come back cached. **The floor is the
cost of a turn on this agent**, and it is why GP-32's estimate-from-prompt-sizes
was wrong by two orders of magnitude even before the non-terminating runs.

**What this means for a consumer**: turn count, not prompt length, predicts spend
here, and a chatty client that sends many tiny turns pays far more than one that
batches. It is also why `total_cost_usd` being null (GP-16) is not a small gap —
there is no monetary figure at all, so a caller sizing a budget has to price
these token counts themselves.

## GP-45 — killing the agent does not end the turn; kill the process GROUP

**Measured 2026-08-11 through the HTTP surface, in the container.** An interrupt
issued exactly 6 seconds into a turn, three consecutive runs:

| | turn returned after |
|---|---|
| `proc.kill()` — the agent only | **7.7 s, 69.5 s, 30.5 s** |
| `os.killpg(os.getpgid(pid), SIGKILL)` — the group | **6.06 s, 6.04 s, 6.05 s** |

**The kill always lands. What does not end is the READ.** The turn completes when
`communicate()` sees EOF on stdout and stderr, and those pipes are inherited: a
grandchild the agent spawned holds the write end open long after its parent is
gone. So the service had already answered "interrupted: true" while the caller's
turn request sat there for another minute.

**Two things make this worse than it sounds on this target.** Interrupt is the
only way to stop a turn, since neither interface registers a cancel verb (GP-02);
and turns that fail to terminate are routine rather than exceptional (GP-18), so
the wall-clock kill runs the same path. Both now kill the group.

**Do not read the variance as "sometimes it works".** 7.7 s was the same defect
as 69.5 s — it just happened to have no surviving grandchild that time. The fix
is not a speed-up, it is the difference between a bounded stop and an unbounded
one.

**POSIX only, which is where this ships.** The image is Linux; on Windows the
process group is not requested and the fallback is the plain kill, so a
developer's test run behaves as before and nobody is told a guarantee that does
not hold there.

## GP-46 — MCP is configured from `$HOME/.gemini/settings.json`, and a WORKSPACE file merges into it

**Measured 2026-08-12, free** — `gemini mcp list` resolves every server and prints
what it found, with no credential and no turn (`spike/probe_gemini_mcp_config.py`).

**`$HOME/.gemini/settings.json` is read.** A server registered there is listed and
enabled, with nothing written into the working directory. That is what makes MCP
possible on this build at all: each session already owns its own agent HOME
(GP-39), so each session can have its own MCP set without touching the caller's
mounted workspace — which is one directory shared by every session, and theirs
rather than ours.

**All three transports validate**, contradicting nothing but worth having from the
binary rather than the bundle. Registered together and listed with the right type:

| Entry | Listed as |
|---|---|
| `{command, args}` | `(stdio)` |
| `{type: "sse", url, headers}` | `(sse)` |
| `{type: "http", url, headers}` | `(http)` |

The settings schema names `headers` as a free `string -> string` map with no
restriction, so this build publishes `mcp.http_headers: "any"` rather than the
Codex build's `bearer_only`.

**A BAD TRANSPORT DOES NOT DISCARD THE FILE**, which is the opposite of the Policy
Engine (GP-25) and worth knowing before assuming the two behave alike:

```
Error in: mcpServers.badprobe.type
    Invalid enum value. Expected 'stdio' | 'sse' | 'http', received 'carrier-pigeon'
```

...printed, and then **the other servers are still listed and the exit code is
still 0**. So a malformed entry costs that entry, not the whole set.

**The finding that shapes the design: a workspace `.gemini/settings.json` MERGES
with the home one.** With `oursserver` in HOME and `injected` in the workspace,
both were listed. **The workspace is caller-supplied content mounted from the
host and writable by the agent**, so without a further control any repository
could add MCP servers — that is, spawn subprocesses — that this service never
authorised and the requesting caller cannot see. GP-47 is the control.

## GP-47 — `--allowed-mcp-server-names` is the whole of `strict_mcp_config`, and an empty list is not expressible

**Measured 2026-08-12, free**, partly from the binary and partly from the bundle
where the binary cannot be asked.

**argv beats settings**, so it is a channel a mounted workspace cannot reach:

```js
allowed: argv.allowedMcpServerNames ?? settings.mcp?.allowed
```

**The filter is applied whenever the list is DEFINED**, and an empty list
therefore blocks everything rather than nothing:

```js
if (config.allowedList !== void 0) { ... if (!found) return { allowed: false,
    reason: `Server '${serverId}' is not in mcp.allowed list.`, blockType: "allowlist" } }
```

**So passing the caller's exact server names gives `strict_mcp_config: true`** —
what you sent is what runs, and GP-46's workspace merge is neutralised — while
omitting the flag gives the CLI's own discovery, which is `false`. Both values of
the published option are expressible, and the default is strict.

**But an empty list cannot be written on the command line.** `--allowed-mcp-server-names`
with no values is a parse error:

> Not enough arguments following: allowed-mcp-server-names

**So "allow nothing" needs a sentinel name**, and GP-28 supplies one that is
provably safe: a real server name may not contain an underscore, so a sentinel
that does can never collide with a caller's server.

**`gemini mcp list` does not accept the flag** — `Unknown arguments:
allowed-mcp-server-names` — exactly as it rejects `--skip-trust` (GP-08). The
subcommands take a different option set from the main command, so a flag verified
against `mcp list` has been verified against the wrong parser.

## GP-48 — MCP works end to end; allowing a server allows ALL its tools; and non-strict is not a behaviour this build can produce

**Measured 2026-08-12 through the container's HTTP surface**, a handful of
flash-lite turns.

**It works.** A server sent as `options.mcp_servers` reached the agent through the
session's own `settings.json` (GP-46) and its tool was CALLED:

```
tools called : ['update_topic', 'mcp_spikeserver_magic_word']
result       : 'The magic word is: MAGIC-WORD-FROM-MCP'
```

The magic word cannot be guessed, which is the only convincing proof an MCP tool
ran rather than a model being agreeable.

**Allowing a server allows every tool on it.** The same server also exposes
`delete_everything`, and `mcp_spikeserver_delete_everything` ran on request. The
policy rule is `mcpName = <server>, toolName = "*"` (GP-29), and `"*"` means what
it says. **A caller who wants one tool of a server cannot express that here** —
the rule shape exists (`toolName = "magic_word"`) but nothing in `RunOptions`
carries it.

### The probe that proved nothing, and how the tool list showed it

The first attempt asked for the magic word and searched the ANSWER for the
string. It reported a leak. It was wrong: the MCP server's source file sits in
the workspace, so the agent called **`read_file`**, found the constant, and
answered correctly with no MCP server involved at all.

```
tools called : ['update_topic', 'read_file']      <- no MCP call anywhere
result       : 'The magic word is `MAGIC-WORD-FROM-MCP`.'
```

**The lesson generalises: on an agent with file tools, any secret placed inside
the workspace can be reached without the mechanism under test.** Assert on the
`tool_use` events, which cannot be produced any other way, and give each fixture
its own distinct secret.

### Why `strict_mcp_config: false` is refused

With the allow-list flag omitted — genuine non-strict — a workspace-registered
server was *still* unusable, and `gemini mcp list` inside the same container
showed it **Connected**, so it was not a startup failure:

```
✓ injectedserver: /app/.venv/bin/python /workspace/injected_server.py (stdio) - Connected
```

...yet the turn reported *"The tool 'magic_word' is not available in this
environment."* That is the signature of a POLICY denial, not a refusal: a denied
tool is removed from the model's context rather than refused (GP-20). The
generated policy denies `*` and allows only the servers the request named, so a
discovered server's tools are invisible whatever the flag says.

**So there are two independent layers, and the weaker one is the flag.** Which
means accepting `strict_mcp_config: false` would change an argv and nothing else
— the accepted-and-ignored defect. It is refused with
`strict-mcp-config-required`, and `capabilities.strict_mcp_config` is `true`.

**It is a named refusal rather than an `unsupported_options` entry**, because the
field IS supported in its other value. `UnsupportedOption.types` cannot express
this either: it discriminates by JSON type, and only one value of a boolean is at
issue.

## GP-49 — persistence buys HISTORY here, never continuity, and the reason is `--session-file`

**Decided and measured 2026-08-12.** A database is optional on this build exactly
as on the other two (GP-36), but what it is *for* differs, and a consumer sizing
a deployment needs the difference.

**The Claude build can resume a conversation out of Postgres** — its SDK takes a
`SessionStore`, so the rows are a source. **This build cannot.** Durable resume
here is `--session-file` against a transcript on disk (GP-11), so the database is
a record and nothing reads it back into a turn. Losing it costs history; losing
the transcript volume costs continuity. They are different volumes and different
failures.

So `Persistence` is constructed with **no `session_store_factory`**, which is the
argument that exists for precisely that seam.

**Verified end to end against a real turn**, because the conformance suite runs
with no credential and therefore cannot check that a turn WRITES anything:

| | |
|---|---|
| `runs.session_id` | this service's sid — the stored key |
| `runs.sdk_session_id` | the agent's id **for that turn** (GP-34), stored beside it and never instead of it |
| `runs.result_text` | `"recorded"`, agreeing with what `/v1` returned |
| `runs.cost_usd` | **NULL**, never 0.0 (GP-16) |
| `runs.model_usage` | per turn, so summing across a session is correct here and would double-count on the Claude build |
| `events` | 4 rows, readable through `GET /v1/sessions/{sid}/transcript` |

**Both 404s are reachable and distinct**, which is the point of having the routes
exist rather than be absent: `session-not-found` and `run-not-found` against a
configured database, `persistence-disabled` without one. The conformance suite's
database pass is what makes the first two reachable at all — with no database
only the third exists, so a build that hard-coded it onto every 404 would pass.

## GP-50 — the idle sweep recursed until the stack ran out, and the published TTL is what would have fired it

**Found 2026-08-12 while wiring the session rows**, in code that had shipped
green through every stage.

`Registry.close(sid)` resolved its argument through `get()`, and `get()` calls
`sweep()`. So a session that was *genuinely* stale re-entered the sweep, found
itself stale again, and recursed:

    sweep() -> close(A) -> get(A) -> sweep() -> close(A) -> ...

**Every request after any session idled past `session_idle_ttl_s` would have
been a 500** — and that value is published in `limits` as a promise a consumer
sizes a reconciliation window from.

**Nothing caught it because no test had let a session age past the TTL**, and the
TTL is 1800 seconds. The suite exercised sweeping only where nothing was stale,
which passes for the same reason an empty loop passes.

The fix is a private `_close(session, status=...)` that does not resolve or
sweep. `status` also became load-bearing on the way: a caller's DELETE records
`closed` and the sweep records `expired`, because a client that tidied up and one
that walked away are different facts about the same row.

**The general shape, worth keeping:** a lazy cleanup that calls a public method
which triggers the same cleanup is a recursion waiting for the first real
expiry, and a test that never waits will never see it.

## GP-51 — popping a secret stops a CHILD inheriting it; it does not hide it from the agent

**Measured 2026-08-12 inside this build's own container**, because three builds
now pop a secret out of `os.environ` and the reason given for it deserved a
number rather than a plausible story.

The claim being tested: this service hands the agent `{**os.environ, ...}`
(`CliRunner.env`), so a secret left there is one `env` away from a process that
runs tools. Popping it is supposed to help. How much?

| | |
|---|---|
| after `os.environ.pop`, still in `os.environ` | **no** |
| after the pop, still in `/proc/self/environ` | **YES** |
| a child process inherits it | **no** |

**`/proc/<pid>/environ` is a snapshot of the environment at exec time and does
not track later `unsetenv`.** So the value survives there for the life of the
process.

**And the agent can read it.** The service runs as uid 1000 (`agent`) and so does
every subprocess it spawns, so a child enumerating `/proc` can read the
environment of every process in the container -- measured, including PID 1's,
which carries the original block:

```
child CAN read /proc/1/environ  (871 bytes)
child CAN read /proc/7/environ  (880 bytes)
...
```

**So the honest statement is narrow.** Popping means the agent is not HANDED the
secret; it does not mean the agent cannot obtain it. What it buys is that a tool
run that merely prints its own environment does not disclose it, which is the
common accident — not protection against an agent that goes looking, which is
the adversary that matters least here anyway, since prompt injection arrives
through a perfectly authorised call.

**The consequence for the auth token is a rule, not a caveat: per instance,
never per fleet.** A token this service holds is obtainable by anything that can
take one turn, so a fleet-wide token is bought with a single turn.

**The same applies to `AGENT_SERVICE_DATABASE_URL`**, popped since persistence
landed, and to `GEMINI_API_KEY`, which cannot be popped at all because the agent
authenticates with it — that one is readable by construction, and the pop was
never available.

### Do NOT measure the inheritance question with `docker exec`

It gives the wrong answer, confidently. Running

```
docker exec <container> sh -c env
```

shows the token, which reads as "the pop did nothing" — and it is measuring a
different process tree entirely. **`docker exec` starts a new process from the
CONTAINER's configured environment**, so it never passed through the service's
`pop`; measured, its own `os.environ` carries the token while the service's does
not.

The agent is not started that way. It is a child of the uvicorn process, spawned
with `{**os.environ, ...}` *after* the pop, which is the arrangement the
in-process measurement above models and a unit test pins.

**The trap is worth the paragraph** because the wrong measurement is the easier
one to reach for, and it disproves a true claim.

## GP-52 — `permission_enforcement: "none"` is what all three builds publish, and it means something different on each

**Established 2026-08-12 by reading all three builds' published values**, after a
question about whether the value should be namespaced per implementation.

The field asks one question: *does the service inspect each tool call in-process
before it runs?* On this build the answer is no — the boundary is a generated
admin-tier policy file that the AGENT loads when the session opens (GP-19), which
is not an in-process check. So `"none"` is the truthful answer, and it is also
the answer the other two give for reasons of their own:

| build | `permission_enforcement` | `confines_writes_to_workspace` | `network_access` | what actually confines it |
|---|---|---|---|---|
| claude-python | `none` (default; `hook` opt-in) | false | true | the container. **A shell is in its default tool list** |
| codex-python | `none` | **true** | **false** | an OS-level sandbox around each turn |
| **this build** | `none` | false | true | the generated tool policy. **`run_shell_command` is refused whatever the caller asks for** |

**So the field does not discriminate, and the two rows that look identical are
the furthest apart.** This build and the Claude build publish the same
`permission_enforcement` and the same `sandbox` pair, while one ships a shell by
default and the other will not enable one at all.

**A consumer must read `always_disallowed_tools` and `default_allowed_tools`
beside it.** Those do differ, and they are where this build's boundary is
visible.

**Namespacing the value was considered and rejected.** `codex:none` versus
`gemini:none` can only be read by a client that already knows the builds — and
`impl.name` is published on the same payload, so that client could always have
branched on it. AS-32 exists so a caller branches on a value it reads rather than
on which image it believes it has; a per-build prefix reintroduces exactly that,
with the field's authority behind it. It would also force the shared `Literal`
open to a bare string, so an unfamiliar value would degrade to *unknown* at every
client rather than merely coarse.

**The real gap is a missing dimension, not an ambiguous value**: *when* the
boundary is fixed. This build's policy is written before the first turn and
cannot be narrowed mid-turn; an in-process hook can refuse a call as it happens.
Both report through one field. Recorded here rather than fixed, because the field
is shared and changing it is a document version and a consumer notice.

## GP-53 — the endpoint variable really does redirect, the key rides in `x-goog-api-key`, and NO header carries the session id

**Measured 2026-08-12, and it cost nothing.** `GOOGLE_GEMINI_BASE_URL` was
pointed at a local HTTP sink — a socket that records the request and answers
`401` — and one turn was taken with a dummy key. No byte reached Google, no
tokens were spent, and three separate questions were answered by the same
captured request.

**This closes GP-42's open half.** That entry established which variable the
binary reads, from the bundle, and said plainly that *whether pointing it
elsewhere actually works is still unmeasured*. It works.

### What arrived

```
POST /v1beta/models/gemini-3.1-flash-lite:streamGenerateContent?alt=sse
user-agent:                       GeminiCLI-tui/0.54.4/<model> (win32; x64; jetbrains)
x-goog-api-client:                google-genai-sdk/1.30.0 gl-node/v25.9.0
x-goog-api-key:                   <the GEMINI_API_KEY value>
x-gemini-api-privileged-user-id:  3aa4d143-…
content-type:                     application/json
```

| Question | Answer |
|---|---|
| Does the endpoint variable redirect? | **Yes.** The request arrived at the sink; nothing reached Google |
| Which header carries the key? | **`x-goog-api-key`** — not `Authorization: Bearer`, not `x-api-key` |
| Which header correlates to `sdk_session_id`? | **None.** See below |

**The key header is worth stating because getting it wrong fails misleadingly.**
A gateway that expects a bearer token and receives `x-goog-api-key` refuses the
request with an authentication error naming neither the endpoint nor the
credential, which reads exactly like a wrong key.

### The correlation header is a measured ABSENCE

The turn's own `init` event reported `session_id: 40eb20c9-593a-458e-8871-…`.
**That string appears in no header of the request that followed.** The only
id-shaped header is `x-gemini-api-privileged-user-id`, whose value is a
different UUID and which names a user rather than a session or a turn.

**So a gateway fronting this build cannot attribute model spend to a session by
reading a header.** That is a finding rather than a gap, which is why
`llm_correlation` publishes `{header: null, measured: true}` — the two fields
exist precisely so *sends none* is distinguishable from *nobody looked*.

**The consumer asked for this and its shape is the consumer's own precedent.**
Agent Harness joins gateway spend to a session through the Claude CLI's
`x-claude-code-session-id` and had one vendor's name compiled in with no way to
discover the others. On this build the honest answer is that there is nothing to
discover, and knowing that is worth more than a null nobody can interpret.

### Reproducing it

`spike/probe_gemini_sink.py`, and it needs no credential worth the name — a
dummy string satisfies the CLI, and the sink answers before the model does. Two
things are required or the run ends before a request is made:

* **`security.auth.selectedType` must be `gemini-api-key`** in the HOME
  settings file, or the CLI exits `41` *Invalid auth method selected* with no
  request attempted. Setting `GEMINI_API_KEY` alone is not enough.
* **`GEMINI_CLI_TRUST_WORKSPACE=true`**, for GP-08's reason.

## GP-54 — the endpoint variable DISABLES authentication, and the session's settings file is the only fix

**Measured 2026-08-14 on `@google/gemini-cli` 0.54.4, free, three arms against
one local sink.** Setting `GOOGLE_GEMINI_BASE_URL` — the variable
`endpoint_source` publishes and every gateway deployment must set — makes the
agent exit `41` *Invalid auth method selected* with **no request attempted**,
whatever the key. This is the CLI's own defect, and it lands on the one path a
consumer behind a gateway has.

### The mechanism, read from the bundle

`getAuthTypeFromEnv()` in `packages/core` tests the endpoint variable **before**
the key, and returns a method the CLI cannot validate:

```js
if (process.env["GOOGLE_GENAI_USE_GCA"] === "true")   return LOGIN_WITH_GOOGLE;  // oauth-personal
if (process.env["GOOGLE_GENAI_USE_VERTEXAI"] === "true") return USE_VERTEX_AI;   // vertex-ai
if (process.env["GOOGLE_GEMINI_BASE_URL"])            return GATEWAY;           // "gateway"
if (process.env["GEMINI_API_KEY"])                    return USE_GEMINI;        // gemini-api-key
```

`validateAuthMethod()` in `packages/cli` has a case for `LOGIN_WITH_GOOGLE`,
`COMPUTE_ADC`, `USE_GEMINI` and `USE_VERTEX_AI` — and **none for `GATEWAY`**, so
it falls through to its default `return "Invalid auth method selected."`. The
core knows the method; the CLI's validator does not. **`gateway` is half
implemented in this version**, and the half that is missing is the one on the
path.

**So the redirect and the key are not in conflict — the inference order is.** A
`gateway` method is chosen ahead of the `gemini-api-key` one that would have
worked, and then rejected.

### The three arms

`GOOGLE_GEMINI_BASE_URL` pointed at a recording sink, dummy key, one turn each:

| Session `settings.json` | Exit | Requests | Key header |
|---|---|---|---|
| `{"mcpServers": {}}` — what this build wrote until today | **41** | **0** | — |
| `+ security.auth.selectedType: "gemini-api-key"` | 1 (sink `401`) | 1 | `x-goog-api-key` |
| `+ security.auth.useExternal: true` | 1 (sink `401`) | 1 | `x-goog-api-key` |

**Both workarounds reach the wire identically**, down to the header GP-53
recorded — so the choice between them is not about what a gateway sees.
`selectedType` is what this build writes, because `useExternal: true` skips
`validateAuthMethod` **entirely**: a deployment that forgot its key would get a
refusal from the far end naming neither the endpoint nor the credential instead
of the CLI's own message naming the three variables it reads.

### What this build does

`config.auth_selection()` mirrors the agent's own order **minus the `gateway`
branch**, and `mcp.write_settings` writes the result into the session's
`settings.json` beside `mcpServers`:

| Environment | `security.auth.selectedType` |
|---|---|
| `GOOGLE_GENAI_USE_GCA=true` | `oauth-personal` |
| `GOOGLE_GENAI_USE_VERTEXAI=true` | `vertex-ai` |
| `GEMINI_API_KEY` set | `gemini-api-key` |
| none of them | **no `security` block at all** |

**The selector outranks the key deliberately.** A Vertex deployment sets both —
the selector says which product, the key is read by one of them — so choosing by
key first would name `gemini-api-key` for it and fail at the far end rather than
here.

**An environment naming nothing gets nothing written.** Inventing a method there
would be this service choosing a credential channel on a deployment's behalf, and
the failure it buys is the misleading one GP-53 warned about. Writing nothing
leaves the agent's own message, which names all three variables.

### Why it was not caught

The prerequisite was known and never crossed the line into the product:
GP-53's own reproduction notes state that `security.auth.selectedType` must be
`gemini-api-key` or the run exits 41, and `spike/probe_gemini_sink.py` sets it.
**The spike set it; the build never did.** Nothing in the suite could see the
gap, because no test and no conformance probe sets an endpoint — a turn under
test uses the stand-in binary, and a turn in CI has no gateway in front of it.
The consumer found it in a deployment, which is the only place it exists.

### Reproducing it

Three homes, one sink, no credential worth the name, no tokens:
`security.auth` is the only variable and the endpoint points at a socket that
answers `401`. The arm that fails does so before a socket is opened at all.

## GP-55 — the extra CA comes from `NODE_EXTRA_CA_CERTS`, and `SSL_CERT_FILE` does NOTHING here

**Measured 2026-08-14, free**, against the same private-CA TLS sink as the other
two builds. The discriminator is whether a request reaches the sink at all: an
untrusted authority fails the handshake and nothing is logged.

| Variable set to the PEM | Requests reaching the sink |
|---|---|
| *(none — the control)* | **0** |
| `NODE_EXTRA_CA_CERTS` | 1 |
| `SSL_CERT_FILE` | **0** |
| `REQUESTS_CA_BUNDLE` | **0** |

**`SSL_CERT_FILE` is what the other two builds read, and it is inert here.** That
is the whole argument for publishing the variable per build: one name set
fleet-wide covers two of three and fails silently on this one. This is also the
only build of the three with a visible Node runtime — `node` is on the `PATH` and
the CLI is a bundle under `/usr/local/lib/node_modules` — so the name is at least
guessable here, which the other two are not.

### It ADDS to the trust store

With `NODE_EXTRA_CA_CERTS` pointing at the private authority **only**, a turn
still reached Google and came back with *"API key not valid"* — a live response
from a public host that authority never signed. So the root store survives, and a
container can reach a privately-signed gateway and a public host at once. The
Codex build's `SSL_CERT_FILE` is the opposite and replaces its store.

### The value is a FILE, never a directory

Pointing the variable at the directory holding the PEM refused the handshake
exactly as leaving it unset does.

`ca_bundle_source: {variable: "NODE_EXTRA_CA_CERTS", shape: "file",
replaces_default_trust: false}`.

**Measuring this at all required GP-54 first.** A turn on this build behind a
redirected endpoint exits 41 before any socket is opened, so every arm would have
read "untrusted" for a reason that had nothing to do with trust. The arms above
were run with `security.auth.selectedType` written into the session settings
file, which is what GP-54 made the build do.


## GP-56 — `impl` is published BEFORE boot as well as on `/v1/capabilities`

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

## GP-57 — `disallowed_tools` was accepted and never read, and the default list is what made it bite

**Found 2026-08-14** by reading this build's `RunOptions` handling against the
other two rather than against a document, and fixed the same day. The field was
not in `unsupported_options`, so it was not refused, and no module consumed it,
so it was not applied.

### The failing request, which needs nothing unusual

```
POST /v1/sessions   {"options": {"disallowed_tools": ["write_file"]}}
```

No `allowed_tools`, which is the ordinary case. The session was provisioned from
this build's **default** allow list — `read_file`, `write_file`,
`list_directory`, `glob`, `grep_search` — and `write_file` is in it. So the tool
the caller explicitly denied was allowed for the whole session, silently, with
nothing in any response to say so.

**The default list is what turns this from redundant into wrong.** When a caller
sends `allowed_tools` as well, a deny list is nearly redundant: the policy is
deny-`*` plus an explicit allow, so anything absent from `allowed_tools` is
already denied. It is only when the allow set comes from the default that a deny
list has work to do — and that is the request shape above.

### Why it is subtracted from the allow set and never written as a deny rule

A `[[rule]]` denying a tool **by name** does not confine the agent: the tool is
removed from its context and it reaches for the shell to do the same work
(GP-20). Under deny-`*` an absent name is simply never allowed, which expresses
the caller's intent with none of the routing-around. So the fix is one set
subtraction in `_permitted`, applied to whichever allow set is in force, and no
new rule shape at all.

### It is honoured rather than refused, and that was the choice

Refusing the field with a 400 would also have been honest and is one line. It was
not taken because this build **can** do what the caller asked, exactly and
cheaply — and a 400 for a thing the policy engine expresses natively would be a
refusal of our own making. Refusal is the right answer for `effort`,
`setting_sources`, `max_turns` and `max_budget_usd`, where no equivalent exists.

### What this class of defect is

**An option accepted and silently ignored**, which is the failure this build's
own notes describe correcting elsewhere and which the platform treats as its
worst: a caller who believes a limit is in force behaves as if it is. It is
indistinguishable from success at the wire, which is why `unsupported_options`
exists and why every other unhonoured field here answers 400.

**Not a security boundary either way.** `run_shell_command` is in
`always_disallowed_tools` and the container is the outer boundary, so no deny
list a caller sends is load-bearing for confinement. The defect is the false
belief, not an escape.

## GP-58 — `stop_kind` on a session's `last_turn`, because 504 is the only thing a timed-out turn ever said

**Found and fixed 2026-08-14**, closing the last gap in the platform's
`stop_kind` field on this build. The live turn path already derived it; the
`TurnRecord` on a session record did not, so `GET /v1/sessions/{sid}` returned a
`last_turn` with the field null while the other two builds filled it.

### Why this surface carries something the live one cannot

A turn that exceeds the wall clock is **killed** — the only way to end one on
this target — and this service answers **504 with a problem document**, never a
`200` carrying a flag. So `RunResponse.stop_kind` can never be `"timed_out"`
here: no `RunResponse` is produced at all.

`Session.finish(interrupted=..., timed_out=...)` runs on that path and records
both facts. **The session's `last_turn` is therefore the only place a client can
ever learn that the previous turn timed out**, once the 504 has been read and
discarded.

### Facts in, word out

The derivation stays in `agent_spec.openapi.stop_kind`. This build passes what
it knows — interrupted, timed out, whether an outcome was recorded — and the
shared function chooses the word. A second derivation living here would
reintroduce, one layer up, exactly the disagreement between seven fields that
`stop_kind` was added to end.

**`is_error` is passed as `interrupted or timed_out`** rather than as a separate
fact, because on this surface there is no SDK envelope to consult: a turn that
neither finished nor was stopped by us does not reach `finish` at all. The shared
function checks `interrupted` before `is_error` precisely so this cannot report
an interrupt as a crash.

## GP-59 — a closed browser tab left the agent running, and billing

**Found and fixed 2026-08-14** while scoping the web console. The console is a
development tool and will not resume a turn across a disconnect; what it must do
instead is leave nothing running.

### What happened

An SSE consumer that goes away — tab closed, laptop asleep, wifi dropped —
causes the response generator to be closed, which raises `GeneratorExit` at its
`yield`. The `_sse` generator's `finally` released the session lock, so nothing
was stranded and the session could take another turn.

**Nothing killed the agent.** `StreamingTurn` calls `kill_process_tree` in
exactly one place, its wall-clock branch, and that branch is abandoned along
with the generator: the `async with asyncio.timeout(...)` never fires because
nothing is awaiting it any more. So the `gemini` subprocess kept running, kept
calling the model **on the caller's key**, and wrote its transcript for a reader
that no longer existed. `session.finish()` was never called either, leaving
`status` at `"running"` and `process` set.

### The fix, and what it deliberately does NOT do

`_abandoned()` kills the process tree, finishes the turn as interrupted, and
records it. It is reached from a `finally` guarded by an `ended` flag that every
normal branch sets **before** its final `yield` — so a disconnect that lands on
the last frame does not re-mark a completed turn as interrupted.

**The session is left open on purpose.** A disconnect is not a statement that
the user is done, and a reload within `session_idle_ttl_s` should find its
conversation. The idle reaper already reclaims genuinely abandoned sessions and
sweeps on every operation, so nothing accumulates.

**One-shot streams are the exception and go entirely**, as they already did —
but the process is now killed *before* the directory is discarded. Removing a
HOME out from under a live agent left it writing into a path that no longer
existed, and left the process running regardless.

### Why not make the turn survive instead

Surviving a disconnect needs a durable replayable event log and a replacement
for the interrupt that keeps one turn's output out of the next. That is worth
building for a product and not for a dev tool, and the consumer's own relay
already treats a client disconnect as terminal — it releases its upstream within
half a second of a closed tab.

## GP-60 — `token_usage` was never mapped, and the raw counts were beside it all along

**Reported by the consumer on 2026-08-14 against the delivered
`gemini-python:0.0.5`, fixed 2026-08-15 and built as `0.0.6`.** A successful turn
returned all five named counts as `null` while the raw `usage` block on the same
response carried the numbers.

### What was wrong

`_turn_response()` built its `RunResponse` without passing `token_usage` at all,
so the model's default — a `TokenUsage` of five nulls — shipped on every turn
this build ever served. There was no wrong key and no wrong nesting level: the
mapper did not exist.

**That is the same defect the Codex build shipped, reached by a different
route**, and the specification names it: `null` means NOT REPORTED, never zero
and never *not bothered*, so a build that has a count and publishes `null` is
making a false statement about its own capability. The shape stays perfectly
valid, which is why no schema check and no document diff can see it.

### The shape the counts actually arrive in

The `result` event's `stats` is **not** the per-model telemetry block. It is the
output of the CLI's `convertToStreamStats`, read from the installed bundle:

| Published key | Filled from | Note |
|---|---|---|
| `total_tokens` | Σ `tokens.total` | includes reasoning |
| `input_tokens` | Σ `tokens.prompt` | **includes the cached half** |
| `output_tokens` | Σ `tokens.candidates` | excludes reasoning |
| `cached` | Σ `tokens.cached` | a SUBSET of `input_tokens` |
| `input` | Σ `tokens.input` | the non-cached half of the prompt |
| `duration_ms`, `tool_calls`, `models` | — | `models` carries the same five keys per model |

**`tokens.thoughts` and `tokens.tool` are dropped by that conversion**, and they
are the two the specification would otherwise want: `thoughts` is exactly
`reasoning_output_tokens`.

Measured on one real turn, per model, from the telemetry block before
conversion:

| Model | input | prompt | candidates | cached | thoughts | tool | total |
|---|---|---|---|---|---|---|---|
| `gemini-3.5-flash` | 2534 | 10637 | 3 | 8103 | 237 | 0 | 10877 |
| `gemini-3.1-flash-lite` | 614 | 614 | 36 | 0 | 384 | 0 | 1034 |

Two identities hold on both rows and both are load-bearing:
**`prompt == input + cached`**, which is what makes `cached` a subset rather
than a separate charge, and **`total == prompt + candidates + thoughts + tool`**,
which is why `total_tokens` is not the sum of the two published directions.

### The mapping, and the two deliberate nulls

`input_tokens` ← `input_tokens`, `output_tokens` ← `output_tokens`,
`cache_read_tokens` ← `cached`.

- **`cache_write_tokens` is `null` because no such counter exists** on this
  target. Same answer as the Codex build, for the same reason, and it means a
  cache write is a charge this API cannot show you.
- **`reasoning_output_tokens` is `null` because the conversion dropped
  `thoughts`.** It is **not** derived as `total - input - output`: that
  expression also absorbs `tool`, which the same conversion dropped, so it would
  publish a reasoning figure inflated by tool tokens on any turn that used one.
  A wrong number is worse than an honest `null` — the whole point of the field.

### The divergence a consumer must act on

**`input_tokens` here already includes `cache_read_tokens`; on the Claude build
it does not.** Anthropic reports the cache counts disjointly from
`input_tokens`, so summing the two is correct there and double-counts here. The
Codex build sits with this one — `cached_input_tokens` is a subset of its
`input_tokens`. This is why the raw block stays beside the named one, and it is
a row in the platform's capability-divergence document.

### Why nothing here caught it

**The clause exists and it is a LIVE one.** AS-34 says a count the build reports
is never published `null`, and it would have failed on the first real turn — but
it costs a real turn against a real model, so it had never run against this
build.

**The free suite could not have caught it either**, because the fake agent's
`result` event carried `total_tokens` and nothing per-direction: a fixture
consistent with the bug, against which an unmapped `token_usage` looks correct.
The fake now emits the measured shape above, and the mapping is pinned two ways
— the function against the measured payload, and the seam over HTTP.

**The consumer found it in one reading**, and said so: the raw block sits beside
the mapped fields, so a mapping defect is distinguishable from silence. That is
the argument for the pass-through, made by the thing it was for.

## GP-61 — `model_api` names the agent TARGET, and the consumer maps it to a vendor API

**Agent Harness asked for a field on the pre-boot surface naming the model API
this build speaks, 2026-08-15.** The field is published. **Its values are the
target family — `gemini` — and not the vendor API they proposed** (user,
2026-08-16), so a consumer relaying to a vendor maps `gemini` to the
Gemini API on their own side.

### What they asked for, and what was traded

Their proposal was `gemini`, on the argument that the API and the build are two
facts that travel together today and are free to stop. **That argument is sound
and it was not the decision taken.** What it would have bought is one fewer
mapping in their gateway; what it costs is a field whose values are a vendor's
vocabulary rather than this platform's.

**The cost of the choice is theirs to carry and they were told plainly**: a
consumer keying an endpoint by vendor API needs `gemini` -> Gemini, and
that mapping lives in their code.

### Why it is NOT a restatement of `impl.name`

`impl.name` is `gemini-python` and carries the implementation language. **`model_api`
carries the family and deliberately does not.** A second build driving the same
target in another language publishes the same `gemini` here and a different
`impl.name` there — so a consumer keying behaviour to the target keys on this
field, and one keying to a specific program keys on that one.

That distinction is the whole reason the field is not redundant, and it is what a
reader should check before proposing to merge the two.

### What it does NOT claim

`model_api` describes the target reached through this build's own
`credential_sources` and `endpoint_source`. **A provider selector in use is
outside it**: `PROVIDER_SELECTOR_ENV_VARS` publishes `GOOGLE_GENAI_USE_VERTEXAI` and `GOOGLE_GENAI_USE_GCA`, which move the transport and the auth selection; they stay a separate field for that reason.

### Surface and cost

**Pre-boot, and asserted not to be on `/v1/capabilities`** — the question is asked
before a container is created, which is the same argument `credential_sources` and
`endpoint_source` sit here under. The conformance suite carries that assertion
beside the other pre-boot-only fields.

**No document version moves.** ~~The pre-boot specification is not in the OpenAPI
document at all, so this is an implementation change and nothing else.~~
**Superseded by GP-63 (0.19.0):** the pre-boot facts ARE in the OpenAPI document
now, as `PrebootSpec`, and `model_api` is pinned there with `const`. The sentence
above was true when written and the reasoning it rests on is what changed.

## GP-62 — an image publishes BOTH things it was built against, and the DDL was the missing one

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
**Superseded by GP-63 (0.19.0):** `schema_revision` is pinned in the document's
`PrebootSpec` component, so it is part of `spec/` now and moving it needs a
document version.

## GP-63 — the pre-boot facts moved INTO the document, and the command was removed

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

## GP-64 — the timers on an MCP tool call: 60 s to begin, 600 s in all, and progress moves neither

Published as `mcp.tool_call` at document version 0.19.0.

| Published | Value | Why |
| --- | --- | --- |
| `request_timeout_s` | `60` | **measured at 60.2 s** — see GP-65, which corrects this row |
| `idle_timeout_s` | `null` | there is no between-frames timer at all |
| `total_timeout_s` | `600` | `MCP_DEFAULT_TIMEOUT_MSEC`, `10 * 60 * 1000` |
| `progress_resets_idle` | `false` | the flag that would do it is never passed |

### ~~`request_timeout_s` is `null`: no wrapper around `fetch`, so the build imposes nothing~~

**Struck 2026-08-19, and kept because being wrong here is the load-bearing
part.** That row was published on a bundle read and a live call refutes it. The
reasoning that produced it is in GP-65 along with the five separate checks that
each said *no bound*, because the interesting thing is not that one read was
wrong — it is that five agreed and the house rule is still *ask the binary*.

### The 600 s is total, and that is the whole point of the entry

The callable tool the CLI builds for each discovered MCP tool invokes
`client.callTool({name, arguments, _meta: {progressToken}}, undefined, {timeout})`
where `timeout` is the server's own `timeout` if it has one and
`MCP_DEFAULT_TIMEOUT_MSEC` otherwise. **`resetTimeoutOnProgress` is not among the
options passed**, and the MCP SDK's `_setupTimeout` defaults it to `false`. So the
clock runs from the call to its answer and nothing restarts it.

**This service writes no per-server `timeout`.** The settings document it renders
carries the transport, the URL or command, the headers and the environment, so
the default is what every call gets and 600 s is the ceiling on this build.

### `false` rather than `null`, and the trap it exists to name

**The agent asks to be told.** It generates a `progressToken` per call, registers
it against the tool-call id, and unregisters it in a `finally` — progress
notifications arrive and drive its own display. A client that sees the token and
concludes the call will be held open is reading an intention that is not there.

That is why the value is `false` and not `null`: there is no idle timer to reset,
but this build IS bounded, so the honest warning is that emitting progress **buys
nothing here** — which `null` would not say.

### ~~What a ~60 s failure is not~~

**Struck 2026-08-19.** It said no timer in this build's MCP path bounds a call at
60 s, and that a tool call dying at a minute with a bare transport error died
below the MCP client — so the path between the container and the server was what
to look at. **A live call against this image, with no proxy variables set at all,
gave up after 60.2 s.** GP-65 is the measurement.

What survives from it is narrow and still true: the CLI's own fetch wrapper does
only two things — swap a proxy dispatcher in when `NO_PROXY` is set, and rewrite
a `404` on `GET` into a `405`. **It is not where the 60 s lives, and neither is
anything else that has been read.**

## GP-65 — the response must BEGIN within 60 s, measured at 60.2 s, and five bundle reads said otherwise

**`request_timeout_s: 60`**, and it corrects the row GP-64 published for a day.
Raised by Agent Harness on 2026-08-19 against a `null` this side had argued for;
their four rows were reproduced here, in this image, with a paid run.

### The run

`spike/mcp_http_delay_server.py` is a streamable-HTTP MCP server with three tools
that differ only in what the server does *while* working.
`spike/probe_gemini_mcp_timeout_live.py` drives real turns through `/v1` against
`agent-service-gemini-python:0.0.8`, on `gemini-3.1-flash-lite`, with a workspace
mounted and **no `HTTP_PROXY`, `HTTPS_PROXY` or `NO_PROXY` set in the container**
— checked inside it rather than assumed.

| Tool | Server behaviour | Delay | Outcome |
| --- | --- | --- | --- |
| `quick` | answers at once | — | token returned, 6.7 s |
| `slowsilent` | no bytes at all, then one JSON body | 90 s | **failed** — *"failed to retrieve the token due to a fetch error"* |
| `slowstream` | SSE headers at once, comment frames every 10 s | 90 s | token returned, turn 150.4 s |

**The number came from a second run at a 240 s delay**, with the server watching
its socket for the peer closing rather than sleeping blind: `THE CLIENT GAVE UP
AFTER 60.2s`. That is the value, and it is why the published figure is `60`
rather than "about a minute".

### Why the comment frames are the whole argument

Comments carry no JSON-RPC and are invisible above the transport, so they cannot
reset an MCP-level timer and are not progress notifications. The streaming case
survived eight of them and answered at 90 s. **So what clears the bound is the
response having BEGUN**, which is exactly what `request_timeout_s` means and is
not what `idle_timeout_s` or `total_timeout_s` mean.

### Five reads that each said "no bound", and all five were beside the point

Kept because the failure mode is reusable, not because the reasoning was
careless:

1. the live tool path passes `{timeout: 600000}` to `callTool` explicitly;
2. the MCP SDK's own request timeout rejects with `McpError … "Request timed
   out"`, and the observed failure says `fetch failed`;
3. the transport's `requestInit` carries headers only — no `signal`, no timeout;
4. the CLI's fetch wrapper installs a proxy dispatcher and a `404`→`405` rewrite
   and no timer;
5. both dispatchers default `headersTimeout` to `3e5`.

Each is individually true and none of them is where the 60 s lives. **The
mechanism is still not located**, and the field is published on the behaviour
rather than on the mechanism — which is the honest order and the one the house
rule asks for: ask the binary, and where the bundle and the binary disagree, the
binary wins. It has now been wrong three times.

### What it changes for a client

**Responding at once is required on this build**, not merely advisable. A server
that thinks in silence and then answers is cut off at a minute however short the
rest of its work; a server that opens an SSE stream immediately may then take up
to the 600 s of GP-64. The two facts together are the whole recipe.
