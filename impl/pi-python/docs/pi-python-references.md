# pi-python references

**The only document this build's code may cite, and it links to nothing.** A
reader holding this file alone never hits a dead end, which is the property the
platform's citation rule exists to guarantee. Every entry is complete on its own:
if a comment needs two entries to make sense, the entries are split rather than
the comment lengthened.

**An ID is permanent.** A superseded entry is struck through and kept, never
renumbered, so a stale citation in an old commit still resolves.

**Measured against Pi 0.85.1** (`@earendil-works/pi-coding-agent`, MIT,
Node >= 22.19) and MCP adapter 2.32.1, on a Windows host driving Docker Desktop,
between 2026-09-06 and 2026-09-07. Total live spend across every measurement
below: **about 0.07 USD**, three provider keys, the most expensive single turn
being an MCP one at 0.015474 because discovery costs three round trips.

**Where a fact was read rather than run, the entry says so** -- and several
entries record a claim that was written from documentation and later measured,
with the correction kept rather than the original edited away.

---

## PI-01 — the `-python` suffix names a real fork in the road here

Pi ships a TypeScript SDK. The other three targets ship no SDK this service
could use (`gemini-cli`), or one already in Python. So `pi-nodejs` is a coherent
*second build of the same target*: it would publish this build's `model_api` and
a different `impl.name`, which is precisely the case those two fields were
separated for.

What a Node build would gain: the SDK in-process — `createAgentSession()`,
`session.subscribe()`, `abort()` as a method — and `createMcpAdapter()`, which
takes an isolated MCP config snapshot rather than a file on disk. What it would
pay: `impl/common/agent-spec` is Python, and it is the shared models *and* the
database layer, so a Node build re-implements both while keeping the published
document byte-identical.

## PI-02 — the credential gate checks three variables, not thirty

Pi resolves credentials for 30-plus providers; its bundled `docs/providers.md`
maps each to its own variable. This build's boot gate checks
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` — the three that have
each driven a real turn through this agent. A gate listing all thirty is a list
nobody maintains; a gate listing none lets every session spawn an agent that
cannot authenticate. A deployment on a fourth provider sets
`AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, and the refusal message says so.

## PI-03 — there are no provider *selector* variables on this target

On the other builds a provider selector is an environment switch (Bedrock,
Vertex, Foundry). Pi selects with a per-request flag, so the choice lives in
`RunOptions.model` and not in the container's environment. `provider_selectors`
is published empty because naming a variable would name a lever that does not
exist.

## PI-04 — `auth.json` outranks every environment variable, and no gate sees it

Pi reads credentials from `<agent dir>/auth.json`, which is what `/login`
writes, and that file takes priority over the environment. A mounted agent
directory carrying an earlier login is therefore authenticated with nothing set.
The boot gate cannot see it, so the refusal message names the case.

## PI-05 — `PI_CODING_AGENT_DIR` relocates the agent's whole state, and it is complete

Measured: with the variable set to a temp directory, that directory afterwards
held `auth.json`, `models-store.json`, `sessions/` and `settings.json`, and
`~/.pi` was never created on a machine that had never run Pi.

**One thing escapes it.** Skills load from `~/.agents/skills/` — a tool-agnostic
path outside the agent directory — confirmed by `get_commands` listing skills
belonging to another tool entirely. An image must mask that path as well as
setting this variable. This build additionally passes `--no-skills` (see
`PI-19`), so nothing is loaded from either place.

## PI-06 — `model_api` is `pi`, and it is the first value that names no vendor

`claude` maps to the Anthropic API, `codex` to OpenAI, `gemini` to Gemini: one
mapping each, which is what the field was built for. Pi is one agent in front of
30-plus providers chosen per request — three of them were driven in a single
afternoon from one binary — so no vendor mapping exists to publish and inventing
one would be false for every request that chose otherwise.

A consumer keys on `pi` and reads the request's own `model` for the vendor.

## PI-07 — `endpoint_source` is `HTTPS_PROXY`, because there is no single base URL

The pre-boot contract requires *the one environment variable that redirects this
image's model traffic*, singular, and a non-empty string. Every other build has
one: `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `GOOGLE_GEMINI_BASE_URL`.

Pi's own environment-variable page documents `HTTP_PROXY` and `HTTPS_PROXY` as
routing outbound requests, and its `httpProxy` setting is applied as both. So the
proxy is the lever that redirects all of it regardless of provider, and the only
honest singular answer on a multi-provider target.

**This entry used to say the alternative was a per-provider base URL "which is
exactly the list a consumer would have to guess from", and that was wrong in the
consumer's favour** — it implied such a list exists and works. It does not: see
`PI-41`, where all three are measured to redirect nothing, with a control. The
reasoning above survives the correction and is in fact stronger, because the
proxy is not merely the best singular answer but the only working one.

**A gateway cannot sit behind it**, though, which is why `PI-42` exists.

**Written from Pi's documentation, and MEASURED since** — see `PI-40`. A turn
with `HTTPS_PROXY` pointed at a local socket opens
`CONNECT api.anthropic.com:443`, with no `NODE_USE_ENV_PROXY` set, so the agent
implements this itself. The claim held; the platform's own redirect check could
not see it, which is a separate story and the more interesting one.

## PI-08 — `NODE_EXTRA_CA_CERTS` is the RUNTIME's variable, not Pi's

Grepping the installed package finds the name only in `@types/node`, a type
declaration: Pi's own code does not read it. Node does, process-wide, before any
application code runs — verified by starting `node` with the variable set. It
adds to the root store rather than replacing it, so a container can reach a
public host and a privately-signed one at once.

**What was not measured:** no turn has been taken against a privately-signed
endpoint on this build. The claim is about the runtime and is labelled as such.

`SSL_CERT_FILE` does nothing here, which is what makes the field worth
publishing: it is what two of the other three builds read, so one variable set
fleet-wide covers those two and silently fails on this one.

## PI-09 — Pi does not destroy its own transcript, so this build keeps no copy

The Gemini target deletes every file sharing an eight-character id prefix with a
record it considers empty, and a resume produces such a record — so that build
copies each transcript out after every turn. Pi does not: `--session-dir` is
honoured, the JSONL it writes stays put, and a second process resumed from it.

So this registry holds a handle, not a rescued copy, and `GET /v1/sessions` is
answered from this service's own map rather than from the agent — as on every
build, because a service-side session is not the same object as an agent-side
one.

## PI-10 — `RunOptions.model` carries the provider inside it, and the core needed no new field

Pi addresses a model as provider plus id, and `--help` says `--model` accepts
`provider/id`. **Measured**: `--model anthropic/claude-haiku-4-5` with no
`--provider` flag billed anthropic and answered, for 0.000803 USD.

This is the resolution of the sharpest question raised before the build started
— whether a multi-provider target forces a companion field into `RunOptions`.
It does not. A qualified model string is self-contained, so `--provider` is only
ever passed for a deployment default paired with a bare id, and the shared core
is untouched.

## PI-11 — `--mode json` per turn, and `--mode rpc` is the upgrade not taken

Pi offers three programmatic surfaces: the TypeScript SDK (`PI-01`), a JSONL RPC
mode over a long-lived process, and this one. RPC is richer — correlated request
and response, a real `abort`, `get_session_stats` — and every documented command
was measured to dispatch.

This build spawns per turn anyway, because a spawn-per-turn driver has no process
to lose: a crash costs one turn, there is no reconnect path to get wrong, and
interrupt is a process kill that always works. The cost is that stopping a turn
is abrupt, and that is the first thing a second version should change.

## PI-12 — with the MCP adapter installed, `pi -p` hangs forever on an inherited stdin

Measured, and it cost the most of anything here. With `pi-mcp-adapter` present,
`pi -p …` and `pi --mode json …` emit **nothing at all** — no session header, no
error — and never exit; killed after five minutes. The same command with stdin
closed answers instantly.

It is not the config (moving `mcp.json` away does not help) and not the
extensions (`--no-extensions` does not help). `--mode rpc` is unaffected, because
there stdin *is* the protocol.

**The image now ships that adapter** (`PI-43`), so the hang is reachable from
here and `stdin=DEVNULL` is the only thing between a request carrying an MCP
server and a turn that never returns. It was passed from the first commit of this
build, when the adapter was absent and the flag cost one keyword argument -- which
is the cheapest a defence ever is.

## PI-13 — a conversation resumes across processes, and the documentation says it does not

Pi's usage page states that print mode does not resume. **Measured on all three
providers**: a first `-p` process wrote a file; a second `-p` process given
`--session <id>` against the same `--session-dir` named that file back. The
session header carried the same id in both.

So `sdk_session_id_scope` is `conversation` here, and a client may key on the id
— which is expressly forbidden on the Gemini build, where a new id is minted
every turn.

## PI-14 — a caller may supply the conversation id

`--session-id <uuid>` is echoed back verbatim in the opening `session` event.
**Measured free**, on a keyless run: the id appeared in the header before the
agent failed for want of a credential.

So `allow_supplied_sdk_session_id` is true, where the Codex and Gemini builds
refuse. `--session` and `--session-id` are mutually exclusive — one resumes, the
other names — and passing both is refused in the runner rather than discovered at
run time.

## PI-15 — the exit code says almost nothing; the message says everything

Pi answers `0` or `1`. An unknown flag, a missing credential and an unknown
session id are all exit 1, so a numeric table like the Gemini build's seven-code
map would classify nothing here.

Measured strings, matched case-insensitively as substrings:

- `No API key found for the selected model.` — no usable credential
- `No session found matching '<id>'` — the resume target does not exist
- `Error: Unknown option: --xyz` — a flag this build should not have sent

Anything unrecognised stays a plain error rather than being forced into a
category.

## PI-16 — usage is per turn, and this was checked rather than assumed

One `pi` invocation runs the agent's whole loop, so a single HTTP turn contains
several model calls, each ending in a `turn_end` carrying its own usage.

**Measured**: an anthropic run's two calls reported 2,150 and 2,095 input tokens.
The second is lower than the first, so it is not a running total. Summing the two
costs (0.002710 + 0.002210) gives the 0.004920 actually spent.

So `model_usage_scope` is `per_turn`: summing across turns is correct here and
would double-count on the Claude build.

**And `message_update` usage must not be billed from.** It is a rolling snapshot
of the call in flight and it goes *down* across a run — the same run's first
update reported 2,150 input tokens and its last reported 2,095, because the run
had moved to a second call. A client sampling the latest frame gets a partial
figure that looks final. Bill from `turn_end`.

## PI-17 — cost is reported in USD, on every provider

Every `turn_end` carries
`usage.cost = {input, output, cacheRead, cacheWrite, total}`, priced from Pi's
own model catalogue. Measured on anthropic, openai and google.

Of the four builds only the Claude one has also been able to fill
`total_cost_usd`, and it fills it from a figure that accumulates over a
connection. This build sums the run's own model calls, so a `runs` row is that
turn's spend and nothing else.

`None` is used where a turn produced no usage at all — an interrupted turn is
killed before any `turn_end`. Never `0.0`, which would read as *free*.

## PI-18 — the per-model breakdown is assembled here, not reported by the agent

Pi publishes no per-model map. Each assistant message names its own `provider`
and `model` and carries its own usage, so the breakdown the specification wants
is a regrouping of what is already in the stream. Keyed `<provider>/<model>`,
which matches the form `RunOptions.model` accepts (`PI-10`).

## PI-19 — this build reads no ambient configuration, and passes three flags to guarantee it

Pi loads skills from `~/.agents/skills/` (`PI-05`), and context files,
extensions and prompt templates from the workspace — which is mounted from the
host and writable by the agent. A turn whose behaviour depends on what a
repository happens to contain is not reproducible.

So every invocation carries `--no-skills --no-extensions --no-context-files`,
and `setting_sources` is published empty.

**`setting_sources` is also refused rather than honoured**, and the reason is a
shape mismatch rather than a missing capability: Pi's switches are per *kind* —
context files, skills, extensions, prompt templates — and the field's vocabulary
is per *layer* — user, project, local. The two do not map onto each other, so
honouring the field would mean choosing which lie to tell.

## PI-20 — `--system-prompt` REPLACES the agent's framing

A flag taking the text itself: no file to write, no environment variable, no path
resolved against a workspace the agent can write to. It stands in for the
built-in prompt entirely, so a caller sending three words gets an agent with
three words of framing — the same semantics the Codex build documents for
`base_instructions`.

**`--append-system-prompt` also exists and is not wired.** It is the preset
object's keep-and-add semantics, but the object names a preset belonging to
another agent, so there is nothing to keep. The object form is refused by type;
the string form is honoured. This is the obvious second version of the field.

## PI-21 — the conversation id exists before the first model call

The opening `session` event carries a UUID and is emitted even on a run that then
fails for want of a credential — measured on a keyless run, which produced the
header and then the error.

So a session has a durable handle from the moment it starts, the streaming route
can set its id header on the first frame, and `/v1/query` can report an id.

## PI-22 — one permission mode, and `plan` is omitted rather than faked

Pi has no per-operation approval in headless use. Its trust gate is binary and
project-level (`defaultProjectTrust: ask|always|never`, `--approve` /
`--no-approve`), and `-p`, `--mode json` and `--mode rpc` skip it entirely.

**`--plan` does not exist.** A stock install answers
`Error: Unknown option: --plan`, character for character what it answers for a
flag invented on the spot. Pi's own usage page: *"It intentionally does not
include built-in MCP, sub-agents, permission popups, plan mode, to-dos, or
background bash."* Plan mode is an extension.

The specification says a build with no equivalent omits a well-known id rather
than mapping it onto something that does not mean the same thing. So this build
publishes `default` alone — the thinnest vocabulary of the four, accurately.

## PI-23 — `effort_levels` is empty although the agent has a thinking dial

This is the one place this build gives up a capability the target has.

`--thinking off|minimal|low|medium|high|xhigh|max` exists. But the dial is per
**model**: `get_available_thinking_levels` returned `["off"]` with no model
configured, and `--list-models` marks thinking yes/no per model. The field means
*levels this build delivers exactly*, and a level silently mapped onto another is
not listed.

Publishing the full vocabulary would claim exact delivery for models that ignore
it. Publishing an intersection across reachable models is narrower than the truth
for most requests and depends on which credentials a deployment holds, which is
not a build fact. So: empty, and `effort` refused.

**The alternative worth revisiting** is a per-model answer, which the field's
flat shape cannot currently express. That is a specification question, not an
implementation one.

## PI-24 — neither shell is granted by default

Pi has `bash` **and** `powershell` built in, has no sandbox of its own (`PI-30`),
and says so itself. A shell is therefore unrestricted access to the container.

The default grant is `read, write, edit, ls, grep, find`. A caller may still ask
for a shell through `allowed_tools` — this is a default, not a prohibition — and
`always_disallowed_tools` names what is refused outright, which is a different
list (`PI-25`).

There is no denial *event* to record: a tool absent from `--tools` is never
offered to the model, so nothing is refused at run time and
`permission_denials` is null rather than an empty list.

## PI-25 — `ask_question` is always refused

The tool exists to put a question to a human. In a headless service there is no
human, so it can only waste a turn or block one. Pi's own documentation shows it
being excluded in two separate examples (`pi --exclude-tools ask_question`).

The Claude build refuses `AskUserQuestion` for exactly this reason under a
different name.

## PI-26 — `max_turns` and `max_budget_usd` are both refused, and the second is the interesting one

One invocation runs the agent's whole loop. There is no flag to cap it, and the
loop's cost is known only as each model call ends — by which time the work is
done.

Enforcing either would mean killing mid-loop and discarding the answer the caller
is paying for. So both are refused rather than half-honoured.

**`reports_cost_usd: true` is what makes this acceptable** (`PI-17`): a client
sums `total_cost_usd` across turns and enforces its own budget between them. The
pairing — a build that reports cost precisely and refuses to enforce a budget —
is the sort of thing `unsupported_options` exists to make legible.

## ~~PI-27~~ — MCP was deliberately not wired, and now it is (`PI-45`)

**Measured end to end.** `pi install npm:pi-mcp-adapter` installs 42 packages
inside `PI_CODING_AGENT_DIR`, registers a `--mcp-config` flag and three commands,
and honours an `mcp.json`. A real stdio server was discovered and called, and the
model repeated a string it could not have invented.

**The shape is why it is not wired.** The agent sees ONE proxy tool named `mcp`:

    toolName "mcp"  args {"server": "spikeserver"}         -> lists that server
    toolName "mcp"  args {"tool": "spikeserver_magic_word"} -> calls it

It never sees the server's own tool names, and there is no `mcp__server__tool`
for anything to name. So `allowed_tools` cannot govern an individual MCP tool
here, which is a design question rather than a wiring job — and shipping it
half-answered is precisely the defect this platform treats as its worst.

Two further measurements for whoever takes it up: discovery costs turns (three
to answer one question, where a build with real tool names takes one), and
servers are lazy — nothing is spawned until a tool is actually called.

**SUPERSEDED 2026-09-07.** Agent Harness answered the question this entry left
open -- they asked for the whole-or-nothing grant knowing exactly what it costs --
so MCP is built. `PI-45` is the shape it took, `PI-43` how the adapter ships,
`PI-48` the silent trap in granting it, and `PI-46` what is published.

**The entry is kept rather than deleted** because the reasoning is still the
reason the feature has the shape it does, and because a decision reversed by a
consumer's answer is worth being able to find. What is now WRONG in it:
`mcp_servers` is honoured, `allow_mcp_servers` is true when the image carries the
adapter, `mcp.transports` is `["stdio", "http"]`, and the four null timers now
mean *no bound found* rather than *no MCP here*.

## PI-28 — about 550 tokens of overhead before the prompt is read

Measured with `--no-tools` and every ambient source suppressed: 548 input tokens
for a six-word prompt. With the default tool set on it is roughly 1,150–1,400.

Published because it changes how a client should batch, and because the
comparison is stark: the Gemini build publishes 7,000. Approximate by nature —
it moves with the agent's version and its tool set.

## PI-29 — no correlation header has been looked for

`llm_correlation` is `{header: null, measured: false}`, and the `false` is the
point. The Gemini build publishes a *measured* absence: it pointed its endpoint
variable at a local sink, took a turn, and found no header carrying the session
id. That experiment has not been run here — this build's redirect is a proxy
(`PI-07`) and nothing has been placed behind it.

`null` with `measured: false` means *nothing known*; `null` with `measured: true`
means *looked for and absent*. A gateway attributing spend must not read the
first as the second.

## PI-30 — there is no sandbox, and Pi says so itself

*"Pi does not include a built-in sandbox."* And: *"A partial in-process sandbox
would be easy to misunderstand as a security boundary."*

So `sandbox.network_access` is true and
`sandbox.confines_writes_to_workspace` is false — not out of conservatism about
an unmeasured guard, but because there is no guard. The container is the entire
boundary.

**`working_directory` is therefore not a boundary here**, which differs from the
Gemini build, where the agent's own guard refuses a file tool outside the
directory it started in. Here it chooses where the agent begins and confines
nothing. It is still validated and refused with a 400 when it escapes the
workspace root — a field accepted and ignored is the defect above.

## PI-31 — *(reserved; not yet used)*

## PI-32 — *(reserved; not yet used)*

## PI-33 — the cache counters are disjoint from `input`, and both halves are real

Pi reports `input`, `output`, `cacheRead` and `cacheWrite` separately, and
`totalTokens` is their sum. So `input` **excludes** the cached half here, where
on the Gemini build the same sum double-counts because its `input_tokens`
contains `cached`.

That is a convention a consumer aggregating across builds must know, and it is
why the raw usage block stays beside the named counts. This build can fill four
of the five named counters; the Gemini build fills three.

## PI-34 — `reasoning` is present on some providers and not others

Measured across one tool turn each: openai and google carry `usage.reasoning` on
every turn (as `0` when nothing thought); anthropic carries it only when the
model actually thought, and carries `cacheWrite1h`, which the other two do not.

**This is a divergence INSIDE one build**, which no other build in this
repository has — every other column is a single vendor. A client billing per
model hits it on the first container that swaps its key. The mapper reads the key
rather than assuming it.

One further measured oddity, recorded unreconciled because nobody has explained
it: an openai turn reported `input 67`, `output 18` and `totalTokens 1621`.
Two of three turns in the same run were internally consistent.

## PI-35 — Pi already speaks in content blocks

A `turn_end` message carries a list of `{"type": "text"|"thinking", …}` objects,
so the mapping into `AgentEvent.content` passes them through rather than
converting a bare string. That makes this build's mapper thinner than the other
three.

`tool_execution_*` normalises to `assistant`, which is the established answer
across the other builds: the closed enum has no `tool` member because the Claude
SDK delivers tool use inside assistant messages. Inventing a member would change
a closed enum in the shared document for one build's convenience. A consumer
wanting the distinction reads `subtype`.

**`agent_end` is the result frame and `agent_settled` is not**, which is the
opposite of what the names suggest: `agent_end` carries the finished message list
and `agent_settled` is a bare marker after it.

## PI-36 — tool results carry real text here

`tool_execution_end` carries the tool's own content list — measured:
`"Successfully wrote to hello.txt"`, and `"MAGIC-WORD-FROM-MCP"` from an MCP
server. On the Gemini target every work tool reports an empty or absent output,
so a client waiting for tool text waits forever. Here it gets something.

## PI-37 — the agent times nothing, so `duration_ms` is zero

Pi's events carry wall-clock timestamps but no turn duration, and there is no
stats block reporting one on this interface. Wall clock measured out here would
include process spawn, which is this service's cost rather than the model's, so
it is not substituted.

`get_session_stats` on the RPC interface has figures this one does not, which is
another entry on `PI-11`'s list.

## PI-38 — a browser that closes an SSE stream must not leave a turn running

A disconnected stream lands `GeneratorExit` on the generator's `yield`. Without
handling it the agent subprocess keeps running to completion — and on a paid
model that is spend attributable to nobody, on a session slot nothing will
release until the idle sweep.

So the disconnect path kills the turn first and discards the directory second:
discarding a directory out from under a live process leaves it writing into a
path that no longer exists.

## PI-39 — AS-14: adopting a caller's id costs two obligations, and this build shipped neither

`allow_supplied_sdk_session_id: true` is a privilege (`PI-14`), and the
specification attaches two duties to it. This build had neither until the
container tier ran, which failed four clauses at once:

- **A supplied id must be a UUID**, refused with a 400 otherwise. The id this
  build is given is the id it reports and resumes from, so an unparseable one
  would be *adopted* rather than corrected.
- **A supplied id together with `options.resume` is a 400.** One names a new
  conversation and the other continues an existing one, so sending both asks for
  two conversations in one session. The agent refuses the equivalent pair of
  flags outright; this refuses it before a turn is taken.

**The empty string is the case that matters**, and it is why the first fix was
still wrong. `""` is falsy, so reading the field with an `or` chain treats an
empty supplied id as *no id supplied* and answers 201. Two of AS-14's three
parametrised values passed against that bug. Read key **presence**, never truth.

**Nothing free could have found this.** The three builds that refuse a supplied
id outright never reach the validation; this is the first build in the repository
to accept one, so the clause had never been exercised from this side.

## PI-40 — `HTTPS_PROXY` really does move this agent's traffic, and the CI sink could not see it

`endpoint_source` was published (`PI-07`) from the agent's own documentation
rather than from a measurement, and the container tier promptly reported that a
turn with `HTTPS_PROXY` set **reached nothing**.

**The claim was right and the check was blind.** Measured directly against a
listener: with `HTTPS_PROXY` pointed at a local socket, the agent opens

    CONNECT api.anthropic.com:443 HTTP/1.1

four times, once per retry — with no `NODE_USE_ENV_PROXY`, so the agent
implements this itself rather than relying on the Node 24 switch. The traffic
moves.

**What could not see it** is the platform's redirect sink, which implemented
`do_GET`/`do_PUT`/`do_POST`. A proxied HTTPS request never becomes any of those:
`BaseHTTPRequestHandler` routes `CONNECT` to `do_CONNECT`, which did not exist,
so the request arrived at the socket and not at the recorder. The fix is in
`ci.py` and is general — the sink now records a `CONNECT` and answers `502`,
which also makes the agent fail fast instead of waiting out the turn timeout.

**The distinction worth keeping**: this stage exists to catch a build whose
published `endpoint_source` does not work. Here the variable worked and the
*instrument* did not, and those must not be reported alike — a check that
answers "nothing arrived" when it cannot observe arrival is worse than no check,
because it reads as a measurement.

## PI-41 — the per-provider `*_BASE_URL` variables redirect NOTHING on this build

`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` and `GOOGLE_GEMINI_BASE_URL` all appear
inside the installed package. **None of them moves a request.** A sink on this
machine received nothing under any of the three.

**The control is what makes that a measurement**, because "nothing arrived" also
describes "nothing was sent". With `ANTHROPIC_BASE_URL` pointed at the sink *and*
the proxy switched on together, the agent opened

    CONNECT api.anthropic.com:443

— the real host, byte-identical to a proxy-only run. A request was certainly
made, and the variable did not touch it. Those names belong to the vendor SDKs
this agent bundles; they are not on its own resolution path.

**This is why `endpoint_source` is a proxy** (`PI-07`) and not one of these, and
it is the answer to a consumer who asked for the set: publishing it would publish
variables that do nothing, which is this platform's oldest defect wearing a
helpful face.

`spike/probe_pi_endpoints_live.py` is the probe. It costs about nothing — every
redirected run dies at the sink's 401 before a token is billed.

## PI-42 — a `models.json` provider override routes a built-in provider anywhere, with headers

The agent reads `models.json` from its own configuration directory, and a
provider entry carrying only a `baseUrl` **reroutes a built-in provider while
keeping every built-in model available**. Measured, all four properties:

| | Observed at the sink |
|---|---|
| a chosen path per provider | `POST /harness/anthropic/v1/messages?beta=true` — the base URL is ours, the API suffix is the agent's |
| plain HTTP rather than a tunnel | a normal `POST` with a JSON body; no `CONNECT` |
| the credential, interceptable | the `x-api-key` header arrived carrying the container's key |
| a header of our own | a declared `x-harness-token` was delivered unchanged |

**Do not put the API suffix in the base URL.** `baseUrl` ending `/v1` produced
`/v1/v1/messages`; the agent appends its own.

**This is the mechanism that makes the build frontable by a gateway**, which a
proxy is not: behind `CONNECT` an intermediary sees a host name and ciphertext,
so it can neither swap a credential nor count tokens.

**One measured hazard that any such deployment must close**: a provider with NO
override **reaches the vendor directly**. With only `anthropic` overridden, a
request naming `openai` sent nothing to the sink and opened
`CONNECT api.openai.com:443` once the proxy was watching. A container fronted by
a gateway holding three providers of thirty must therefore refuse the other
twenty-seven rather than leak them, and that refusal belongs to this service.

## PI-43 — the adapter ships in the image, and `--no-extensions` can stay

The MCP adapter is 42 packages and `pi install` writes them into whatever agent
directory it is given. Installing it per session would put that cost on every
`POST /v1/sessions`, so the image installs it **once** into `/opt/pi-agent-tools`
and symlinks `/opt/pi-mcp-adapter` at it, published to the service as
`AGENT_SERVICE_MCP_ADAPTER_PATH`.

**The flag interaction is the part worth knowing.** `--no-extensions` disables
the adapter: measured, the adapter's commands drop from four to one. But the
agent's own help says *"Disable extension discovery (explicit -e paths still
work)"*, and that is exactly true — `--no-extensions --extension <absolute path>`
loads the adapter and nothing else. Measured: the three adapter commands come
back and no others do.

So this build keeps `--no-extensions` on every invocation and names the adapter
by path when a request carries servers. `PI-19`'s guarantee — that nothing in the
caller's mounted workspace reaches a turn — survives MCP intact.

## PI-44 — the gateway map, and a provider with no entry is refused

`AGENT_SERVICE_PROVIDER_GATEWAYS` maps a provider to `{base_url, headers}` and
becomes the session's `models.json` (`PI-42`). Built for Agent Harness, whose
gateway holds the account credential and counts every relayed call, and which
cannot do either behind a `CONNECT` tunnel.

**A malformed value is a BOOT refusal, never a silent empty map.** An operator
who sets this expects every turn behind their gateway; falling back to
"unfronted" would send the container's own credential straight to the vendor,
which is the failure the setting exists to prevent.

**Non-empty, the map IS the allow-list.** A request naming a provider with no
entry is refused with a 400 rather than reaching its vendor directly — the
hazard Harness asked us to confirm, and the answer to their question was the bad
one until this existed (`PI-41`'s probe: only `anthropic` overridden, a request
naming `openai` left the container).

**Three defects, none of which a unit test caught**, all found by running a
fronted container:

- **`compose.yaml` never forwarded the variable.** The service read an empty map
  and had no opinion about any provider — configured, and applied to nothing,
  which is this platform's oldest defect in its compose form.
- **`check_provider` ignored the deployment's DEFAULT MODEL.** The provider is
  inside `AGENT_SERVICE_MODEL` on this build (`PI-10`), so reading only the
  separate provider setting made a fronted container answer 400 to its own
  default. Every unit test configured a model and a gateway together.
- **`json.dumps` on the servers raised `TypeError`.** The registry holds pydantic
  `McpStdioServer` objects and the tests all built sessions from plain dicts, so
  the first real MCP turn was a 500.

## PI-45 — MCP is whole-or-nothing, and that was decided WITH the consumer

The adapter presents every registered server through a single proxy tool named
`mcp`. The agent never sees a server's own tool names, so `allowed_tools` can
permit or deny all MCP and nothing finer.

**Agent Harness was told that and asked for it in that form anyway** (2026-09-07),
because without MCP their worker cannot commit — committing is a tool call to
Harness rather than the agent running `git` — and because their own server
already varies its listing by caller and re-checks authority at call time. The
per-tool grant was a third layer for them, not the boundary. They also said they
will refuse a worker registration where their per-worker dials cannot bind to an
individual tool, which is this build's own principle pointed back at us.

**The config is ours and the agent is pointed at it by flag.** `--mcp-config`
names this service's file, so the adapter's six-file precedence chain — two of
whose paths are inside the caller's mounted workspace — never runs. That is what
`strict_mcp_config: true` means here: structural rather than a setting, and
`false` is refused because it is not a behaviour this build has.

**The server name may not contain an underscore.** The proxy addresses a tool as
`<server>_<tool>`, so `a_b_c` is ambiguous. `SERVER_NAME_PATTERN` is both the
published value and the check that runs, because a published pattern that
disagreed with the real refusal is the drift AS-32 exists to prevent.

## PI-46 — the transports published, and the timers that were not measured

`stdio` and `http`. **`sse` is deliberately absent**: the adapter folds it into
its HTTP transport as a fallback rather than offering it as a choice, so listing
it would name a transport a caller cannot select.

**stdio measured end to end through the image** — a Node MCP server in the
workspace, and the model repeated a string it could not have invented. HTTP is
accepted and validated by shape and has **not** been driven to a real server on
this build.

**The four `mcp_tool_call` timers are null meaning NO BOUND FOUND**, which is
the codex reading rather than the earlier pi one: nothing in this path imposes a
tool-call timeout that has been located. **This is not a measurement to expiry** —
no server that stalls deliberately has been run against this build — so the
honest ceiling to plan against is the turn's own wall clock in
`behaviour.limits`.

## PI-47 — a stdio MCP server must be spawnable by the IMAGE, so it is Node here

The image is `node:24-slim` and carries no Python interpreter. The Python spike
server beside `spike/mcp_spike_server.js` can drive the agent on a developer's
machine and **can never be spawned inside the container** — measured as a turn
that produced an empty result and a 500 on the next attempt.

A stdio MCP server is a subprocess the image has to start, which makes the
image's own runtime the only safe language for one. `spike/mcp_spike_server.js`
is the Node twin, and it is what the container-tier proof uses.

## PI-48 — granting MCP means granting one tool by NAME, and forgetting it is silent

The proxy tool is called `mcp`. This build's default allowlist is six read and
write tools and does not contain it, so a session carrying servers had the
adapter loaded, the servers registered, and a model that could not see any of it.

**Measured**: the turn answered helpfully that no such tool existed, listed the
tools it did have, exited 0, emitted no `tool_execution` events, and cost money.
Nothing failed. That is the whole-or-nothing grant made concrete — there is one
name to add, and adding it admits every server the request carried.

The runner appends `mcp` to the effective allowlist whenever a request carries
servers and the adapter is present. With the name added, the same prompt answered
`MAGIC-WORD-FROM-MCP` through three proxy calls — discover, list, call — for
0.015474 USD, which is also the measured cost of the discovery round trips.

## PI-49 — the MCP tool-call bound is 60 s TOTAL, cleared by nothing

**This value has been wrong twice and the second time was worse than the first.**
It published `null` meaning *no bound found*; then `request_timeout_s: 60` on a
reading that was an artifact; it is `total_timeout_s: 60`.

**Three shapes, measured against a server that stalls on purpose. All three are
cut at about a minute:**

| what the server did | outcome |
|---|---|
| never responded at all | cut at **61.6 s** and **63.6 s** |
| sent SSE headers at once, body never | cut at **61.9 s** |
| sent headers AND data every 20 s | cut at **61.5 s**, with ticks delivered at 20, 40 and 60 s |

The client reports `Failed to call tool: Request timed out` in every case. So
**responding does not clear it and a frame that counts does not reset it**, which
is exactly this specification's definition of the third timer: *cleared by
nothing; it expires while the call is healthy*.

Published as `total_timeout_s: 60`, with `request_timeout_s` and
`idle_timeout_s` null and `progress_resets_idle` **false** — the last measured
rather than assumed, because ticks were delivered and the call died anyway.

### The methodological error, which is the part worth keeping

The wrong middle answer came from trusting the **socket** instead of the
**client**. The server watched `res.on("close")` and reported a streamed call
"still open at 268 s" — but that event did not fire until the agent process
exited. The adapter had already given up at about a minute and told the model
`Request timed out`; the TCP connection simply had not been torn down.

**A tool result is evidence. An unclosed socket is not.** Every timer figure here
is now read from what the client reported, and the server log is only used to
confirm what it sent and when.

### Why this one matters beyond the number

Agent Harness hosts an MCP server whose first tool holds the call open until
another agent replies, and they had told us their design already survives —
*"the stream opens on the POST and progress ticks every thirty seconds inside a
five-minute deadline"*. **On this build it does not.** Neither the stream nor the
ticks help; the call is cut at a minute regardless. A tool needing longer than
that has to return promptly and be polled.

**This build is therefore NOT like claude-python and gemini-python**, which the
previous version of this entry claimed. Those two publish `request_timeout_s: 60`
and a server that responds at once clears it. Here nothing clears it, which makes
this the only build of the four where *respond at once* is not the remedy.

### The bound does not CANCEL anything, and that is the sharper half

**A client giving up is not a cancellation.** Nothing is sent to the server when
the sixty seconds expire; the socket is simply dropped. Our stalling server went
on ticking to its own cap, unaware, and only noticed when the agent process
exited.

**So a tool that started work keeps doing it while the agent is told it timed
out.** Agent Harness reported the same thing from the other side, independently
and about their own tool: their `run_command` runs an agent-supplied command in a
container for up to ten minutes, and on this build the agent is told it failed at
one minute *while the command continues*.

**What that means for anyone writing an MCP server for this build**: work that
can outlive a minute must be startable and pollable, and the server must expect
to finish work nobody is listening for. A server that treats a dropped connection
as a cancellation will be wrong here, and a server that does not will leak.

## PI-50 — HTTP MCP transport works, measured end to end

`stdio` was measured through the image; `http` was accepted by shape and never
driven, which mattered because the consumer's own server is the HTTP one.

**Driven now.** A dependency-free Node streamable-HTTP MCP server
(`spike/mcp_http_delay_server.js`), reached through the adapter, and the model
returned `MAGIC-WORD-OVER-HTTP` — a string it could not have invented. The server
logged the whole handshake: `initialize`, `notifications/initialized`,
`tools/list`, `tools/call`.

**One label worth recording**: the adapter described the connection as
*"legacy notification path"* in its own listing. It works; the phrase suggests a
newer path exists that this server did not offer, and nothing here depends on
which one is taken.

So `accepts.mcp.transports` publishes `["stdio", "http"]` with both halves
measured, and neither is a claim resting on documentation.

## PI-51 — the mode an omitted `permission_mode` gets is `default`, the only mode there is

**Published as `accepts.default_permission_mode` at document version
0.23.0-snapshot, on Agent Harness's ask of 2026-09-07.**

This build's answer is the least interesting of the four and is published on the
same terms as the rest: `permission_modes` holds `default` and nothing else
(`PI-22`), so an omitted `RunOptions.permission_mode` can only resolve to
`default`.

**A caller still cannot infer that without reading it.** *One mode* and *this is
the mode you get* are different claims, and a client that has to special-case
"this build publishes one mode, so the default must be it" is doing the
service's work. The field makes the four builds answerable by one code path.

| | |
| --- | --- |
| Constant | `capabilities.DEFAULT_PERMISSION_MODE` |
| Value | `default` |
| Applied at | `api` — the ephemeral route and `POST /v1/sessions` |
| Published at | `capabilities.build_capabilities`, from the same constant |

**What `default` means here is the caveat worth carrying**, and it is `PI-22`'s:
Pi has no per-operation approval in headless use, so this mode is not a
permission setting that was chosen over others. What confines a turn is the tool
allowlist and the container.

**Named rather than left as a literal** in the two places that apply it, so a
build that ever acquires a second mode cannot drift the published copy from the
applied one. `Accepts` refuses at assembly if the value is not one of
`permission_modes[].id`.
