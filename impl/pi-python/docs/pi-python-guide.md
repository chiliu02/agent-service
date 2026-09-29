# `pi-python` — the guide for someone integrating against it

**Read this before writing a client.** The OpenAPI document tells you the shape
of every request and response; it cannot tell you which of four builds you are
holding or what that one does differently. This does.

**What this build is.** An HTTP service in front of **Pi**
(`@earendil-works/pi-coding-agent`, MIT, a Node CLI), driven by spawning the
binary once per turn. It answers the same thirteen `/v1` operations, the same
`Deployment` payload and the same error vocabulary as the other three builds.

**The one sentence that matters most.** This is the only build of the four that
fronts **more than one vendor** — Anthropic, OpenAI, Google and thirty-odd
others, chosen per request — and almost everything surprising below follows from
that.

**Everything here was measured against agent `0.85.1` and MCP adapter `2.32.1`,
on a Windows host driving Docker Desktop.** Where something was read rather than
run, it says so. Where a figure was published wrongly and corrected, it says that
too, because you should be able to price the rest.

---

## 1. What it is, and how to run it

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e AGENT_SERVICE_MODEL=anthropic/claude-haiku-4-5 \
  -v /host/work:/workspace \
  <image>
```

**The credential.** Three variables are checked: `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`. Each has driven a real turn. The agent itself
reaches far more providers, so a deployment using a fourth sets
`AGENT_SERVICE_REQUIRE_CREDENTIALS=false` — and the refusal message says so
rather than leaving you to guess.

**A credential in the agent's own `auth.json` outranks every variable above** and
is invisible to the boot gate. If that is your deployment, start with the gate
off.

**The model is `provider/id` in one string.** `anthropic/claude-haiku-4-5`,
`openai/gpt-5-nano`, `google/gemini-3.1-flash-lite`. A bare id works when
`AGENT_SERVICE_PROVIDER` is set. **Leave both unset and the agent picks from
whatever credentials it finds**, which is a real deployment and an unpredictable
bill.

**Both boot gates exit 3** and stay down: no credential, and a workspace that is
not on a real mount. The container prints what to set and binds no port.

---

## 2. The OpenAPI document, and how to use it

`spec/openapi/pi-python-<version>.json` is what a running container serves at
`/openapi.json`, byte for byte. Two things live only there:

- **`components.schemas.PrebootSpec`** — everything you need *before* a container
  exists, every value pinned with `const`: which credential variables it reads,
  which variable moves its traffic, which one delivers a private certificate
  authority, the DDL revision, the port, and the uid it runs as.
- **The `example` on `GET /v1/deployment`** — what this build actually answers,
  so you can compare four builds without starting four containers.

**Read `GET /v1/deployment` at runtime rather than branching on the image tag.**
Everything in §3 is published there.

---

## 3. Things that will surprise you

### 3.1 `model_api` is `pi`, and it names no vendor

Every other build maps to one API: `claude` → Anthropic, `codex` → OpenAI,
`gemini` → Gemini. **This one maps to none**, because the vendor is chosen per
request. Read the request's own `model` for the vendor; the family tells you
which agent is underneath and nothing about which API will be called.

### 3.2 `endpoint_source` is `HTTPS_PROXY`, and the per-provider base URLs do nothing

The other three publish a base URL. This agent has one per *provider* — and
**none of them works.** Measured, with a control: with `ANTHROPIC_BASE_URL`
pointed at a local sink *and* a proxy switched on at the same time, the agent
still opened `CONNECT api.anthropic.com:443`. The names appear in the package
because its vendor SDKs carry them; they are not on the agent's own path.

**The proxy is the only environment variable that redirects anything**, and it
opens a `CONNECT` tunnel. That is enough to send traffic somewhere. It is **not**
enough to put a gateway in front of it: behind `CONNECT` an intermediary sees a
host name and ciphertext, so it can neither swap a credential nor count tokens.

### 3.3 If you need a gateway, use the provider map

```
AGENT_SERVICE_PROVIDER_GATEWAYS =
  {"anthropic": {"base_url": "https://gw.example/harness/anthropic",
                 "headers": {"x-tenant-token": "..."}}}
```

Deployment configuration, not a request field. What arrives at your gateway,
measured through the image:

```
POST /harness/anthropic/v1/messages?beta=true
     x-api-key: sk-ant-...        <- the container's, yours to strip and swap
     x-tenant-token: ...          <- the header you declared, delivered
```

**Do not put the API suffix in `base_url`.** The agent appends its own, so a
value ending `/v1` produces `/v1/v1/messages`.

**A provider with no entry is refused with a 400**, not sent to its vendor. That
is deliberate: without it, a gateway holding credentials for three providers of
thirty would have twenty-seven holes rather than three doors. An empty map means
unfronted, which is the default and a real deployment.

### 3.4 Cost is real, and `max_budget_usd` is refused anyway

`reports_cost_usd` is **true** — USD on every model call, on every provider, from
the agent's own pricing. Two of the four builds can say that.

`max_budget_usd` is **refused with a 400**, and the pairing is the point: one
invocation runs the agent's whole loop, so the figure arrives as each model call
*ends*. Enforcing a budget would mean killing mid-loop and discarding the answer
you already paid for. **Sum `total_cost_usd` between turns instead** — that is
what publishing it is for.

`max_turns` is refused for the same shape of reason: the agent decides its own
loop and no flag caps it.

### 3.5 `model_usage` is per turn — and its KEYS differ by provider

`model_usage_scope` is `per_turn`, checked rather than assumed: two calls in one
turn reported 2,150 then 2,095 input tokens, so the second is not a running
total. **Sum across turns.**

**And the usage object's own keys differ between providers inside this one
build**, which no other build here does:

| | anthropic | openai | google |
|---|---|---|---|
| `cacheWrite1h` | present | absent | absent |
| `reasoning` | only when it thought | always | always |
| `totalTokens == input + output` | yes | **no on one turn of three** | yes |

The named `token_usage` counts are normalised for you. The raw block is where the
divergence shows.

**`input_tokens` EXCLUDES the cached half here**, as on `claude-python` and
unlike the other two. So `input_tokens + cache_read_tokens` is the right prompt
figure on two builds of four and double-counts on the other two — and the split
does not follow which vendor is underneath.

**Bill from `turn_end`, never from `message_update`.** That frame's usage is a
rolling snapshot of the call in flight and it goes *down* across a run.

### 3.6 MCP is one proxy tool, and the call is cut at sixty seconds

MCP works — stdio and HTTP both measured end to end. But **the agent sees one
tool called `mcp`**, never a server's own tool names. There is no
`mcp__<server>__<tool>`, so `allowed_tools` can permit or deny *all* MCP and
nothing finer. Discovery also costs turns: three proxy calls to answer one
question.

**Server names may not contain an underscore** — the proxy addresses a tool as
`<server>_<tool>`, so `a_b_c` is ambiguous. Published as
`accepts.mcp.server_name_pattern`.

**And the tool call is cut at about sixty seconds, by a bound nothing clears.**
Measured three ways, all cut: no response at all (61.6 s, 63.6 s), headers sent
immediately (61.9 s), headers plus data every twenty seconds (61.5 s, with ticks
delivered throughout). Published as `total_timeout_s: 60`, with
`progress_resets_idle: false` measured rather than assumed.

**This is the only build of the four where *respond at once* is not the remedy.**
On `claude-python` and `gemini-python` opening a stream stops the clock. Here it
does not.

**The expiry cancels nothing.** No notification is sent; the socket is dropped.
So a tool that started work goes on doing it while the agent is told it timed
out. **A server written for this build must expect to finish work nobody is
listening for** — treating a dropped connection as a cancellation is wrong here,
and not treating it as one leaks.

**If your tool can take longer than a minute, it must return promptly and be
polled.** That is a different design, not a different timeout.

*This value was published wrong twice before it was right: `null`, then
`request_timeout_s: 60` on a reading that an unclosed socket had faked. The
figures above come from the client's own error rather than from a socket.*

### 3.7 There is no sandbox, and the container is the whole boundary

The agent's own documentation says so: *"Pi does not include a built-in
sandbox"*. So:

- `sandbox.network_access` is **true** and
  `sandbox.confines_writes_to_workspace` is **false** — not conservatism about an
  unmeasured guard, but the absence of a guard.
- **`working_directory` confines nothing.** It chooses where the agent starts.
  On `gemini-python` the same field is a boundary; here it is not.
- The agent has **two** built-in shells, `bash` and `powershell`. Neither is
  granted by default — but `allowed_tools` can ask for one, and that is
  unrestricted access to the container.

A read-only bind mounted under the workspace still holds: that is the kernel, not
the agent. Nothing inside the container adds to it.

### 3.8 One permission mode, and `plan` is omitted rather than faked

`permission_modes` holds `default` and nothing else — the thinnest of the four.
Pi has no per-operation approval headless: its trust gate is binary and
project-level, and non-interactive runs skip it entirely. `--plan` does not exist
on a stock install; plan mode is an extension the agent's own documentation names
among the things it omits.

`effort` is **refused**, and this is the one place the build gives up a
capability the agent has. The thinking dial is per **model**, and
`accepts.effort_levels` means *levels delivered exactly*; a flat list cannot say
"depends which model", and an intersection would depend on which credentials a
deployment holds.

### 3.9 The conversation id is stable, and you may supply it

`sdk_session_id_scope` is `conversation` — measured across two processes on three
providers. You may key on it. (On `gemini-python` you may not: a new id is minted
every turn.)

`allow_supplied_sdk_session_id` is **true**: send `sdk_session_id` on
`POST /v1/sessions` and it is adopted verbatim. It must be a UUID, and it cannot
be combined with `options.resume` — one names a new conversation, the other
continues an existing one.

### 3.10 Nothing on the container's disk reaches a turn

Every invocation passes `--no-skills --no-extensions --no-context-files`, so
context files, skills and extensions are not read — not from the workspace, and
not from `~/.agents/skills/`, which the image also masks.

`setting_sources` is **refused**, because the agent's switches are per *kind* and
the field's vocabulary is per *layer*; the two do not map. The practical effect
is that this build is more reproducible than the others and the API still cannot
*supply* ambient configuration — no build here can.

---

## 4. How this build differs, and where to read it at runtime

Everything in §3 is published on `GET /v1/deployment`. The fields worth reading
first:

| Field | Why |
|---|---|
| `service.impl.name` | which of four you are holding |
| `behaviour.model_usage_scope` | `per_turn` — sum it |
| `behaviour.reports_cost_usd` | `true` here |
| `behaviour.mcp_tool_call.total_timeout_s` | `60`, and nothing clears it |
| `behaviour.sandbox` | both false-ish; the container is the boundary |
| `accepts.permission_modes` | one entry |
| `accepts.unsupported_options` | what answers 400 rather than being ignored |
| `config.allow_mcp_servers` | false when the image carries no adapter |

**`unsupported_options` is a promise about refusals**, not a suggestion. This
build refuses `effort`, `setting_sources`, `max_turns`, `max_budget_usd`,
`strict_mcp_config: false`, and the preset-object form of `system_prompt`. Each
is a 400 naming the field.

---

## 5. Tested, expected, and the difference

**Measured, with a real model:** every turn shape in §3, resume across processes
on three providers, cost accumulation over a session, the gateway map end to end
through the image, MCP over stdio and over HTTP, and the sixty-second bound three
ways.

**Measured without a model:** the boot gates, the flag catalogue, the RPC command
table, agent-directory containment, and the refusals.

**Read rather than run:** `NODE_EXTRA_CA_CERTS` — Node honours it process-wide,
verified at the runtime level, but no turn has been taken against a
privately-signed endpoint. And the `$ENV_VAR` interpolation the agent documents
for `models.json` credentials, which this build does not use.

**Not measured at all:** anything on a Linux *host*. The image is Linux and its
container tier passes; every measurement behind this guide was taken from a
Windows host driving Docker Desktop.

---

## 6. Your responsibilities, not this service's

- **The container is the security boundary.** There is no sandbox. If the agent
  should not reach something, do not mount it and do not route to it.
- **Do not widen the published port** without an authenticating proxy. There is
  no authentication unless you set `AGENT_SERVICE_AUTH_TOKEN`, and the documented
  capability of this service is running tools.
- **Choose the model.** Left unset, the agent chooses and you pay for it.
- **Enforce your own budget** between turns, from `total_cost_usd`. This build
  will not do it inside one.
- **Poll long MCP work.** A tool that can exceed a minute cannot be held open,
  and abandoning it does not stop it.
- **One worker per session.** A second concurrent turn on one session is a 409,
  never a queue.
