# Deriving `RunOptions` from `/v1/deployment`

**One container answers three questions about every request field: which values
are legal, what the field means, and what happens if you leave it alone.** A
client that asks all three can generate the whole `RunOptions` form — a dropdown
carrying this build's valid values, a tip carrying the field's own description,
and a default that is the server's rather than one the client invented.

**Since 2026-09-03 there is a shortcut, and most clients should take it.**
`GET /v1/schemas/run-options` serves the answer already computed — the published
model narrowed by this deployment — so §2's overlay is the *service's* algorithm
now, not homework. Read §1.1 and §2 anyway if you are deciding what to render:
the schema says what is legal and nothing about what a caller cannot control.

**This is the ALGORITHM. [`capability-divergence.md`](./capability-divergence.md)
is the SNAPSHOT.** That document exists so a reader can see the three builds side
by side without starting three containers; this one exists so a client never has
to read it at all. Where they disagree, the running service wins and both are
wrong.

**Provenance.** Every published value quoted in §7 was read from the three
builds' capability constructors on 2026-09-02, at implementation versions
matching document `0.20.0-snapshot`. They are here to make the algorithm
concrete, **not to be depended on**: a client that hard-codes them has rebuilt
the problem this document is about.

---

## 1. The contract this rests on

**Every `RunOptions` field is either honoured or published as refused.** Both
halves are enforced in CI and in the conformance suite, and two failure modes are
treated as the same defect wearing opposite coats:

- an option accepted and silently ignored — the caller believes a limit is in
  force;
- an option published as refusable that can never be sent — the caller is
  promised a `400` that cannot happen.

So a field absent from `unsupported_options` does something, and a field present
there produces a `400` rather than a shrug.

**`unsupported_options[].field` is a typed foreign key into `RunOptions`
property names** — an identifier, never prose, so it can be compared directly
against the key you were about to send:

```
refused(field, value) =
      entry.field == field
   && (entry.types  == null || entry.types.includes(jsonTypeOf(value)))
   && (entry.values == null || entry.values.includes(value))
```

Each `null` is *no constraint of that kind*. An absent key and an explicit `null`
mean the same thing, everywhere in the document.

### 1.1 What this algorithm CANNOT derive, on any build

**The contract above is about FIELDS. The agent has a second input that is not a
field, and no `RunOptions` value can supply it.**

Inside the container the agent reads its own configuration off disk — memory
files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`), skills, subagents, slash
commands, plugins, hooks, settings files. That input is real, it changes what the
agent does, and **a complete, correct, fully derived form covers none of it.**

| | claude-python | codex-python | gemini-python |
|---|---|---|---|
| Send ambient configuration in the request | **no** | **no** | **no** |
| Switch off what is on disk | **yes** — `setting_sources: []`, the server default | **partly** — the project doc only; the runtime's own `config.toml` is always read | **no** — `setting_sources` is a `400`; the mounted workspace's files are read every turn |

**Read that as: a form generated from these two documents is complete with
respect to the request and silent about half the input.** It is not a gap in
this algorithm — there is nothing in either document to derive it from. An
OpenAPI document describes a payload's shape; nothing in it says whether the
service's agent also reads a file the caller has never seen.

**`system_prompt` is not the missing lever, and mistaking it for one is the
trap.** On every build it *replaces* the agent's own framing with the text you
send; it does not become memory, register a skill, define a subagent, or stop a
single file on disk being read. On gemini-python the workspace's context files
are appended *after* it.

**So: the container's disk is part of the deployment, not part of the request.**
A client that needs a reproducible session provisions the image and the workspace
deliberately, and — only on claude-python — sends `setting_sources: []` to say
so in the request. The per-kind table is
[`capability-divergence.md` §3.1](./capability-divergence.md#31-ambient-configuration--no-build-lets-the-api-replace-it-and-the-document-never-said-so).

---

## 2. The derivation is a SCHEMA transform — and the service now does it for you

**`GET /v1/schemas/run-options` is the answer this section used to make you
compute.** It serves the published `RunOptions` already narrowed by that
deployment's `accepts` group — JSON Schema 2020-12, self-contained `$defs`,
served as `application/schema+json`. Hand it to a validator or an off-the-shelf
form renderer and you can stop reading here.

```
GET /v1/deployment            → four groups; `accepts` is the request half
GET /v1/schemas/run-options   → that same `accepts`, rendered as a schema
```

**Two shapes of one fact, and a conformance clause asserts they agree.** The
payload is what you *branch* on — `unsupported_options` as
`{field, types, values}` is directly actionable — and the schema is what you
*validate* against. Neither is derived from the other by a consumer at runtime;
the service publishes both, and a build whose schema offered a field its payload
refuses would be telling two readers two different stories.

**Why the service does this rather than the client.** The narrowing is a
*deployment-time* fact: two containers of one image answer differently, so it
cannot sit in a frozen document, and no standard says a deployment narrows a
published contract at runtime. What a client would otherwise write is the table
below — once per client, from prose.

**The rest of this section is what the service does.** It is kept because a
client that would rather compute the overlay itself, or audit the one it was
served, needs the rules written down. These documents are OpenAPI **3.1**, whose
schemas *are* JSON Schema 2020-12, so `components.schemas.RunOptions` is already
a valid JSON Schema and the whole job is one function:

```
effective_schema = RunOptions_schema  ⊕  deployment.accepts
```

### The overlay, keyword by keyword

Each row is mechanical. Nothing here needs a per-field branch in your code — the
only thing that varies is which capability key feeds which property.

| Capability | JSON Schema edit on `RunOptions` |
|---|---|
| `unsupported_options` entry, no `types`/`values` | **delete the property.** Nothing is `required`, so removal is always valid |
| entry with `types` | delete that branch from the property's `anyOf` — `system_prompt` keeps `{"type":"string"}` and loses `{"type":"object"}` |
| entry with `values` | `"not": {"enum": [<values>]}` on the property, or narrow an existing `enum` |
| `permission_modes[].id` | `enum` on `permission_mode` — and see the labelling note below |
| `setting_sources[]`, `effort_levels[]` | `enum` on the array's `items`. **Empty published list ⇒ delete the property**, not an empty select |
| `default_allowed_tools` + `always_disallowed_tools` | **`examples`, never `items.enum`** — an unpublished tool name is *accepted and dropped*, so an enum would promise a 400 that never happens. See §4.1 |
| `default_model`, `default_allowed_tools`, `strict_mcp_config` | `default` on the property |
| `limits.max_allowed_*` | `maximum` on the matching number |
| `limits.default_*` | `default` on the matching number |
| `allow_mcp_servers: false` | delete `mcp_servers` — it is a gate, and it is **not** mirrored into `unsupported_options` on two builds (§8) |
| `allow_supplied_sdk_session_id: false` | delete `sdk_session_id` from the **create body**, not from `RunOptions` |

### The four steps that remain

1. **Fetch both, once per CONTAINER — not once per build.**
   `GET /v1/deployment` and `GET /openapi.json`. **`/openapi.json` needs no
   bearer token**: auth covers paths under `/v1` and nothing else, on all three
   builds. **Cache per instance, keyed by the base URL you called**, and
   re-fetch when it restarts — `impl.version` is not a safe cache key, because
   roughly a third of the payload comes from the deployment's environment rather
   than from the build (§7.4).
2. **Apply the overlay above.** One pass, one table.
3. **Render the effective schema** with whatever you already use.
4. **Submit only what the user touched.** This one is genuinely outside the
   schema: omission means *server default*, so a prefilled control that always
   submits converts a default into a pin. A renderer that emits every property
   it drew will do exactly that — strip untouched properties before sending.

### Three wrinkles worth knowing before you pick a library

**Labelled options need `oneOf`, not `enum`.** `permission_modes[]` carries
`{id, name, description}` and the ids alone are unreadable — `dontAsk` next to
`bypassPermissions`. The renderer-friendly encoding is one branch per value:

```json
{"oneOf": [{"const": "plan", "title": "Plan", "description": "Read-only …"}]}
```

Common renderers label a select from `oneOf` + `const` + `title`. Per-option
*description* is where they differ, and that is a UI-layer concern rather than a
schema one — which is the honest boundary of what this transform buys you.

**Nullability is spelled `anyOf: [{…}, {"type": "null"}]`**, from Pydantic, on
almost every property. It is valid 2020-12 and some renderers draw it as a
one-of picker rather than an optional field. Collapsing the null branch before
rendering is usually right — and is the same operation the `types` row performs.

**No property is `required`**, deliberately: every field falls back to server
config, so an empty object is a valid request. Do not add `required` when you
narrow.

### If you would rather not compute the overlay at all

Two standards-shaped alternatives, neither of which this service implements
today:

- **The service serves the effective schema** — one document per deployment, no
  client-side merge. That is a specification change and a new operation, so it is
  a decision rather than a suggestion; raise it if you want it.
- **The narrowing ships as an [OpenAPI Overlay](https://spec.openapis.org/overlay/v1.0.0)
  document** — `actions` with a `target` and `update`/`remove`, which is exactly
  the shape of the table above. It is a young specification with thin tooling;
  worth knowing it exists, not worth depending on yet.

**§6's reference generator predates this framing and does the overlay by hand**,
field by field, which is what a library would do for you. It is there to be read
as a worked example of the table, not copied as an architecture.

---

## 3. Three sources, three questions

**Why the overlay reads two documents rather than one.** A schema alone answers
*what shape is legal*; it does not answer *which values this deployment
accepts*, and it carries no server-side default for a field whose default lives
in configuration. The three sub-sections below are the evidence for the three
columns of §2's table — which key wins when both documents speak, and why.

### 3.1 Values — the dropdown comes from `/v1/deployment`

**The OpenAPI enum is the union across builds; the capability list is THIS
build's subset. Render the capability list.** The document is one specification
served by three implementations, so its `effort` enum carries all five levels
while a build that delivers four publishes four — and offering the fifth is
offering a `400`.

| Control | Options from | Note |
|---|---|---|
| `permission_mode` | `permission_modes[].id` | **Not an enum in the document at all** — it is a bare string there, precisely because each build declares its own set. |
| `effort` | `effort_levels[]` | Document enum has five; a build may publish fewer. **Empty means hide the control.** |
| `setting_sources` | `setting_sources[]` | Refused *per value* on at least one build, so send only published members. |
| `allowed_tools`, `disallowed_tools` | `default_allowed_tools` ∪ `always_disallowed_tools` | The build's own tool vocabulary. An empty `default_allowed_tools` means the build does not govern by tool list — hide both. |
| `model` | `default_model` (a value, not a list) | No build publishes a model catalogue. Free text, prefilled. |
| `mcp_servers[].type` | `mcp.transports[]` | Drop the rows for transports not listed. |
| `strict_mcp_config` | `strict_mcp_config` + `unsupported_options[].values` | A checkbox with possibly one legal position. |

### 3.2 Tips — the description comes from the per-implementation document

**`components.schemas.RunOptions.properties.<field>.description`, from
`<impl>-<version>.json` — NOT from `core-<version>.json`, which carries none.**
The core document is the structural intersection; the descriptions live in each
build's own document and in what that build serves at `/openapi.json`.

**Eleven of the sixteen fields carry a description; five do not.** Identical on
all three builds as of `0.20.0-snapshot`:

| | Fields |
|---|---|
| **Has a tip** | `model`, `resume`, `system_prompt`, `allowed_tools`, `disallowed_tools`, `setting_sources`, `max_budget_usd`, `working_directory`, `include_raw`, `mcp_servers`, `strict_mcp_config` |
| **No tip in the document** | `permission_mode`, `effort`, `max_turns`, `timeout_s`, `include_partial_messages` |

For the five, the text comes from elsewhere and a form should supply it:

- **`permission_mode`** — the richest source in the whole payload:
  `permission_modes[]` is `{id, name, description}`, so **render `name` as the
  option label and `description` as per-option help.** Those descriptions say
  what a mode actually permits on that build, which is where the builds diverge
  most.
- **`max_turns`, `timeout_s`** — describe them from `limits`: which figure is the
  default, which is the ceiling.
- **`effort`, `include_partial_messages`** — no source. Write your own, or omit
  the tip; do not invent semantics.

The descriptions are Markdown and some are several paragraphs — `allowed_tools`
alone carries the warning that it grants a *capability* and not a path
restriction. **Render them as a popover, not a title attribute**; truncating them
loses exactly the sentence that prevents a mistake.

### 3.3 Defaults — the capability, then the schema, then nothing

**Only one `RunOptions` property has a JSON-Schema `default`:
`include_partial_messages: false`.** Everything else is nullable with no default
in the document, because the default lives in the running container's
configuration — which is what `/v1/deployment` is for.

| Tier | Source | Fields |
|---|---|---|
| **1** | the capabilities response | `model` ← `default_model`; `max_turns` ← `limits.default_max_turns`; `max_budget_usd` ← `limits.default_max_budget_usd`; `timeout_s` ← `limits.default_request_timeout_s`; `allowed_tools` ← `default_allowed_tools`; `strict_mcp_config` ← `strict_mcp_config`; `working_directory` ← relative to `workspace_dir` |
| **2** | the document's `default` keyword | `include_partial_messages` (`false`) |
| **3** | **nothing is published** | `resume`, `system_prompt`, `disallowed_tools`, `permission_mode`, `effort`, `setting_sources`, `include_raw` — and any tier-1 field whose `limits` key this build omits |

**A tier-3 field gets a placeholder reading *server default* and submits
nothing.** That is not a cosmetic choice: the server's default may differ per
deployment and may change under the caller, and a client that prefills its own
guess has silently pinned a value the operator meant to control.

**A tier-1 default is a display value, not a submission.** Show
`default_request_timeout_s` in the box so the user knows what they are getting;
send it only if they change it. `limits` keys with a `default_` prefix are what
the build will use, and `max_allowed_` keys are what it will accept — a form
needs both and they are frequently different numbers.

---

## 4. Field by field

`RunOptions` has sixteen properties. This is every one of them — **the overlay of
§2 worked out concretely**, with the control a renderer would pick from the
narrowed schema shown alongside, so the table can be checked against a real form
rather than only against a spec.

| Field | Control | Options from | Tip | Default |
|---|---|---|---|---|
| `model` | text | — (prefill only) | document | `default_model` |
| `resume` | text | — | document | none — placeholder |
| `system_prompt` | textarea (+ preset picker) | — | document — **it REPLACES the agent's own framing**; only claude-python's preset object appends to it | none |
| `allowed_tools` | checkbox group | `default_allowed_tools`, `always_disallowed_tools` disabled | document | all of `default_allowed_tools` |
| `disallowed_tools` | checkbox group | same vocabulary | document | none |
| `permission_mode` | **select** | `permission_modes[].id` | **`permission_modes[].description`, per option** | none — the build applies its own |
| `effort` | **select** | `effort_levels[]` | none published | none |
| `setting_sources` | checkbox group | `setting_sources[]` | document — **a switch over what is on DISK, never a way to send it** (§1.1) | none |
| `max_turns` | number, `min=1` | — | none published | `limits.default_max_turns`, capped by `limits.max_allowed_turns` |
| `max_budget_usd` | number, `>0` | — | document — **it is not a spend cap** | `limits.default_max_budget_usd`, capped by `limits.max_allowed_budget_usd` |
| `timeout_s` | number, `min=1` | — | none published | `limits.default_request_timeout_s`, capped by `limits.max_allowed_timeout_s` |
| `working_directory` | text | — | document | none; show `workspace_dir` as the prefix |
| `include_partial_messages` | checkbox | — | none published | **`false`, from the schema** |
| `include_raw` | checkbox | — | document | none |
| `mcp_servers` | repeatable group | `mcp.*` (§5) | document | none |
| `strict_mcp_config` | checkbox | `unsupported_options[].values` | document | `strict_mcp_config` |

Two capabilities govern `POST /v1/sessions` itself and belong on the same form:
**`allow_supplied_sdk_session_id`** (whether the create body may carry an
`sdk_session_id`; `false` is a `400`, never a silent drop) and
**`max_sessions`** (the concurrent cap, and the denominator of the `429`).

And these shape the *result* view rather than the form — read them in the same
pass: `model_usage_scope` (sum, difference, or skip), `reports_cost_usd`,
`usage_counts_tool_calls`, `turn_token_overhead`, `llm_correlation`,
`query_reports_sdk_session_id`, `query_consumes_a_session_slot`,
`permission_enforcement`, `sandbox`, `require_mounts`.

---

### 4.1 Tool names — three sources, and an unknown one is ignored

**A tool control cannot be a closed list, and a typo in it is silent.** Both
facts were measured on 2026-09-03 against all three builds, and both change what
a form should render.

**Where a legal name can come from:**

| Source | Publishable? | Notes |
|---|---|---|
| **Built-ins** — the agent's own tools | **only these** | a property of the binary, its version and the *platform*, never of the model. Wider than `default_allowed_tools`: one build advertises 31 built-ins while publishing 8 |
| **MCP tools** — from the servers in *this* request | no | named `mcp__<server>__<tool>` on one build, `mcp_<server>_<tool>` on another. They cannot exist before the request does |
| **Ambient** — skills, subagents, plugins on the container's disk | no | no request supplies them; `setting_sources` is the only lever, and one build does not have it |

**An unrecognised name is accepted and dropped — `201`, not `400`.** Verified in
both directions: `["__nope__"]` in `allowed_tools` opens a session on the builds
that take the field. So:

* **do not validate against `default_allowed_tools`** — it is a default grant,
  not a vocabulary;
* **render the published names as suggestions**, not as the only options, or a
  legitimate `mcp__…` name becomes unsendable;
* **warn on an unknown name rather than blocking it**, because a typo silently
  grants nothing and the first symptom is an agent that cannot do its job;
* **show `always_disallowed_tools` as disabled**, since naming one is not an
  error either — it is filtered out.

**And `allowed_tools` grants permission, not visibility.** The model is told
about tools the list does not name, will attempt one, and is denied — a spent
turn, which surfaces in `RunResponse.permission_denials`. `disallowed_tools` is
what removes a capability.

## 5. The MCP sub-form

`mcp.*` is a form spec in its own right:

| Capability | Effect |
|---|---|
| `allow_mcp_servers: false` | Hide the whole section. Sending servers is a `400`. |
| `mcp.transports` | The transport radio's options. Absent `sse` means no SSE row. |
| `mcp.http_headers: "bearer_only"` | Replace the free header map with a single token field — only `Authorization: Bearer …` is expressible. `"any"` keeps the map. |
| `mcp.server_name_pattern` | A regex to validate the server **name** against, client-side, before the request. `null` means this service refuses no name. |
| `mcp.tool_call.*` | Help text, not validation: `request_timeout_s` is how long the agent waits for a response to **begin**, `total_timeout_s` is wall clock for the whole call. `null` is *no bound published*, never *no bound*. |

---

## 6. A reference generator

Data-driven, so it is the same code against all three builds. This is the whole
of the logic; the rest is markup.

```js
const jsonType = (v) =>
  v === null ? "null" : Array.isArray(v) ? "array" : typeof v === "object" ? "object" : typeof v;

/** Is `field` refused outright, or for this particular value? */
function refused(caps, field, value) {
  return (caps.unsupported_options ?? []).some(
    (e) =>
      e.field === field &&
      (e.types == null || e.types.includes(jsonType(value))) &&
      (e.values == null || e.values.some((x) => JSON.stringify(x) === JSON.stringify(value))),
  );
}

/** A field is renderable when SOME value of it is accepted. */
const available = (caps, field) => !refused(caps, field, undefined);

/**
 * caps    -- GET /v1/deployment
 * openapi -- GET /openapi.json from the SAME container (no bearer token needed)
 */
function buildForm(caps, openapi) {
  const props = openapi.components.schemas.RunOptions.properties;
  const lim = caps.limits ?? {};
  //  tip: the document's own words. 5 of 16 fields have none -- see  3.2.
  const tip = (f) => props[f]?.description ?? null;
  //  default: capability first, schema second, nothing third.
  const dflt = (f, capValue) => capValue ?? props[f]?.default ?? null;

  const f = [];
  const add = (field, spec) =>
    available(caps, field) && f.push({ field, help: tip(field), ...spec });

  add("model", { control: "text", value: dflt("model", caps.default_model) });

  if (caps.permission_modes?.length)
    add("permission_mode", {
      control: "select",
      // The one field whose per-OPTION help is published.
      options: caps.permission_modes.map((m) => ({ value: m.id, label: m.name, help: m.description })),
      value: null, // no build publishes a default mode
      placeholder: "server default",
    });

  // An empty vocabulary is a HIDE, not an empty select.
  if (caps.effort_levels?.length)
    add("effort", { control: "select", options: caps.effort_levels, placeholder: "server default" });
  if (caps.setting_sources?.length)
    add("setting_sources", { control: "checkboxes", options: caps.setting_sources });

  // Tool lists: the build's own names, or no control at all.
  if (caps.default_allowed_tools?.length) {
    const vocab = [...caps.default_allowed_tools, ...caps.always_disallowed_tools];
    add("allowed_tools", {
      control: "checkboxes",
      options: vocab,
      disabled: caps.always_disallowed_tools,
      value: caps.default_allowed_tools,
    });
    add("disallowed_tools", { control: "checkboxes", options: vocab, value: [] });
  }

  for (const [field, dKey, maxKey, min] of [
    ["max_turns", "default_max_turns", "max_allowed_turns", 1],
    ["max_budget_usd", "default_max_budget_usd", "max_allowed_budget_usd", 0],
    ["timeout_s", "default_request_timeout_s", "max_allowed_timeout_s", 1],
  ])
    add(field, {
      control: "number",
      min,
      max: lim[maxKey] ?? null, // absent = no ceiling PUBLISHED, not no ceiling
      value: dflt(field, lim[dKey]),
      placeholder: lim[dKey] == null ? "server default" : null,
    });

  add("system_prompt", {
    control: "textarea",
    // The preset object is a separate shape and may be refused on its own.
    presets: refused(caps, "system_prompt", {}) ? null : ["claude_code"],
  });
  add("working_directory", { control: "text", prefix: caps.workspace_dir });
  add("include_partial_messages", { control: "checkbox", value: dflt("include_partial_messages", null) });
  add("include_raw", { control: "checkbox", value: false });

  if (caps.allow_mcp_servers)
    add("mcp_servers", {
      control: "server-list",
      transports: caps.mcp.transports,
      headers: caps.mcp.http_headers,
      namePattern: caps.mcp.server_name_pattern,
      toolCall: caps.mcp.tool_call,
    });

  add("strict_mcp_config", {
    control: "checkbox",
    value: dflt("strict_mcp_config", caps.strict_mcp_config),
    // Refused for one value = the checkbox has one legal position.
    locked: refused(caps, "strict_mcp_config", !caps.strict_mcp_config),
  });

  return f;
}

/** Submit only what the user changed: omission IS the server default. */
const toRunOptions = (form, values) =>
  Object.fromEntries(
    form
      .filter((c) => {
        const v = values[c.field];
        if (v == null || v === "" || (Array.isArray(v) && !v.length)) return false;
        return JSON.stringify(v) !== JSON.stringify(c.value); // unchanged -> omit
      })
      .map((c) => [c.field, values[c.field]]),
  );
```

---

## 7. What that generator produces, per build

Values as published on 2026-09-02. **An illustration of the shape, never a
substitute for the response.**

### 7.1 `claude-python` — the permissive one

| Capability | Value | Form consequence |
|---|---|---|
| `permission_modes` | `default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions`, `auto` | six options, each with its own description as help |
| `effort_levels` | `low`, `medium`, `high`, `xhigh`, `max` | full select |
| `setting_sources` | `user`, `project`, `local` | three checkboxes |
| `default_allowed_tools` | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebSearch`, `WebFetch` — **operator-configurable** | eight prechecked boxes |
| `always_disallowed_tools` | `AskUserQuestion` | one disabled box |
| `limits` | `default_max_turns`, `max_allowed_turns`, `default_max_budget_usd`, `max_allowed_budget_usd`, `default_request_timeout_s`, `max_allowed_timeout_s`, `session_idle_ttl_s` | **all three numeric fields prefilled and capped** — the only build where that is true |
| `unsupported_options` | **empty**, unless an operator turned MCP off | nothing hidden |
| `mcp` | `stdio`/`sse`/`http`, headers `any`, pattern `null` | full sub-form |
| `sandbox` | `network_access: true`, `confines_writes_to_workspace: false` | warn: the container is the boundary, and `Bash` is unconfined |

```json
{"options":{"model":"claude-sonnet-5","permission_mode":"acceptEdits","effort":"high",
 "allowed_tools":["Read","Grep","Edit"],"max_turns":8,"timeout_s":300}}
```

### 7.2 `codex-python` — the one that governs by sandbox

| Capability | Value | Form consequence |
|---|---|---|
| `permission_modes` | the same six ids | six options |
| `effort_levels` | `low`, `medium`, `high`, `xhigh` — **no `max`** | four options; `max` is still *accepted* and mapped to `xhigh`, but is not offered |
| `setting_sources` | `user`, `project` | two checkboxes; `local` is refused **per value** |
| `default_allowed_tools` / `always_disallowed_tools` | **both empty** | **hide both tool controls entirely** |
| `unsupported_options` | `allowed_tools`, `disallowed_tools`, `max_turns`, `max_budget_usd` (whole field); `system_prompt` for `["object"]` | four fields gone; the preset picker gone, the textarea stays |
| `limits` | `default_request_timeout_s`, `max_allowed_timeout_s`, `session_idle_ttl_s` | only `timeout_s` is prefilled and capped |
| `mcp` | `stdio`/`http`, headers **`bearer_only`**, pattern `null`, all four timeouts `null` | no SSE row; a single token field instead of a header map |
| `sandbox` | `network_access: false`, `confines_writes_to_workspace: true` | **see trap 8** |

**Empty tool lists are not "everything permitted"** — they mean the axis is the
sandbox, not the tool name, which is why `allowed_tools` is a `400` here rather
than a no-op. A form that renders a tool picker for this build is offering a
control that cannot be submitted.

```json
{"options":{"permission_mode":"acceptEdits","effort":"xhigh","timeout_s":600,
 "system_prompt":"Be terse."}}
```

### 7.3 `gemini-python` — the one with a different vocabulary

| Capability | Value | Form consequence |
|---|---|---|
| `permission_modes` | **`default`, `auto_edit`, `yolo`, `plan`** | four ids — `acceptEdits` is not one of them, and the `yolo` description carries a real warning worth surfacing |
| `effort_levels` | **empty** | hide the control |
| `setting_sources` | **empty** | hide the control |
| `default_model` | `"auto"` when unset — **a routing policy, not a model** | prefill it, and note that a turn under it names two models in its usage |
| `default_allowed_tools` | `read_file`, `write_file`, `list_directory`, `glob`, `grep_search` | five prechecked boxes |
| `always_disallowed_tools` | `run_shell_command` | one disabled box — **filtered, not refused** (trap 3) |
| `unsupported_options` | `effort`, `setting_sources`, `max_turns`, `max_budget_usd`; `strict_mcp_config` for `values: [false]` | four fields gone; the strict checkbox rendered **locked on** |
| `limits` | `turn_timeout_s`, `max_sessions`, `session_idle_ttl_s` | **no `default_*` and no `max_allowed_*`** — so `timeout_s` gets a *server default* placeholder and no cap |
| `mcp` | all three transports, headers `any`, pattern **`^[^_]+$`**, `request 60` / `total 600` | validate server names client-side; show both timeouts |
| `turn_token_overhead` | `7000` | show it: turn COUNT predicts spend here, not prompt length |

```json
{"options":{"permission_mode":"auto_edit","allowed_tools":["read_file","grep_search","write_file"],
 "timeout_s":900,"strict_mcp_config":true}}
```

### 7.4 The same image can answer differently

**A capabilities response is NOT a property of the build alone.** Every build
reads its settings from the environment once, at startup — `AGENT_SERVICE_`
prefixed, plus a `.env` file — and publishes them. The values are stable for the
life of the process and are never mutated by a request, so one *container*
answers consistently; two containers of one *image* need not agree.

| | Fields |
|---|---|
| **Fixed by the build** — same in every deployment of an image | `spec`, `impl`, `permission_modes`, `effort_levels`, `setting_sources`, `always_disallowed_tools`, `model_usage_scope`, `reports_cost_usd`, `usage_counts_tool_calls`, `turn_token_overhead`, `sdk_session_id_scope`, `llm_correlation`, `allow_supplied_sdk_session_id`, `query_reports_sdk_session_id`, `query_consumes_a_session_slot`, `sandbox`, `mcp.*`, `credential_sources`, `provider_selectors` |
| **Set by the deployment** — moves with the operator's environment | `default_model`, every figure in `limits`, `workspace_dir`, `reference_dirs`, `max_sessions`, `require_credentials`, `auth_required`, `require_mounts`, `allow_mcp_servers`, and on `claude-python` also `default_allowed_tools`, `strict_mcp_config` and `permission_enforcement` |
| **Measured at startup** | `sdk.version` / `sdk_version` — `gemini-python` execs `gemini --version` and falls back to its pinned string, so a mismatch between what the build measured and what is installed is visible in the payload rather than hidden |

**Two consequences for a form.** The tool checkboxes and every numeric bound are
*operator* choices on `claude-python` and constants on the other two — so a
generated form is per-deployment there in a way it is not elsewhere. And
`unsupported_options` **itself moves with configuration on `claude-python`**: it
is computed from `allow_mcp_servers`, so turning MCP off adds an `mcp_servers`
entry that no other build's list would grow. A client that cached the refusal
list against `impl.version` would keep offering a field the container now
refuses.

---

## 8. Traps a generated form walks into

1. **`allow_mcp_servers` is not mirrored into `unsupported_options` on two of the
   three builds.** Only `claude-python` computes the entry from the setting, so
   elsewhere an operator can turn MCP off while `unsupported_options` stays
   silent and the `400` arrives at request time. Read the boolean on its own.
2. **An empty container is not a refusal.** At least one build tests truthiness,
   so `allowed_tools: []` is accepted where a populated `allowed_tools` is a
   `400`. Never send an empty collection as a probe.
3. **EVERY unrecognised tool name is a filter, not a rejection** — not only the
   always-disallowed ones. `allowed_tools: ["__nope__"]` opens a session, and so
   does a misspelled `disallowed_tools` entry, which denies nothing. The
   published lists are the only notice you get; there is no error to catch. §4.1.
4. **`permission_mode` ids are not a shared enum**, which is why the document
   types the field as a bare string. `default` and `plan` are well-known ids a
   build uses *where it has an equivalent*; a build without one omits them
   rather than mapping them onto something else.
5. **`limits` keys differ, and an absent key publishes nothing.** Do not infer a
   ceiling that is not there, and do not treat an enforced figure such as
   `turn_timeout_s` as a bound on the caller's `timeout_s`.
6. **Capability is not acceptance.** `strict_mcp_config` appears on both schemas:
   the capability is the server-side **default**, `unsupported_options[].values`
   is which settings are **refused**. A form needs both to decide whether the
   checkbox is editable.
7. **Tool names are the agent's own vocabulary and mean permission, not scope.**
   `Read` on one build, `read_file` on another — and naming a read tool permits
   reading *any* path; a scoped syntax such as `Bash(git status:*)` is not
   enforced by this service.
8. **`sandbox.network_access: false` does not mean the agent cannot reach the
   web.** It is exactly and only a statement about the sandboxed shell. Measured
   on `codex-python` on 2026-09-02 and written up as `CX-63`: with that field
   published `false`, a turn ran the provider's hosted web tool, searched, opened
   a URL and quoted the live page, while `curl` in the same session could not
   resolve a hostname. A form that renders "no network" from that field is
   telling the user something untrue.
9. **`max_budget_usd` is not a spend cap** on any build that accepts it — it is
   checked against a cumulative figure that does not move for an interrupted
   turn. Its own description says so; render it.
10. **`resume` takes the `sdk_session_id`, not `session_id`** — and where
    `sdk_session_id_scope` is `turn`, that value names one turn rather than the
    conversation, so a "resume last session" button is wrong there.
11. **A complete form is still not the whole input.** The agent reads ambient
    configuration off the container's disk, no field can supply it, and only
    `claude-python` can switch it off — §1.1. A UI that presents the generated
    form as "everything that shapes this run" is asserting something false on
    all three builds, and the strongest case is `gemini-python`, where a
    `GEMINI.md` in the mounted workspace reaches every turn and no request can
    prevent it.

---

## 9. One payload that works on all three

```json
{"prompt":"…","options":{"permission_mode":"default","timeout_s":300,
 "include_partial_messages":true}}
```

`permission_mode: "default"` is a well-known id, `timeout_s` is enforced by every
build, and `include_partial_messages` is governed by no capability. **Anything
beyond this is worth deriving rather than assuming** — which is the point of §6.

---

## 10. Where to look next

- **The three generated pages** —
  [`run-options-claude-python.html`](../impl/common/web/run-options-claude-python.html),
  [`run-options-codex-python.html`](../impl/common/web/run-options-codex-python.html),
  [`run-options-gemini-python.html`](../impl/common/web/run-options-gemini-python.html).
  §6's generator, running, against each build's own `/v1/deployment` example as
  carried by its OpenAPI document. Open one from disk; nothing is fetched.
  **They share one template and differ only in the two JSON blobs at the top**,
  which is the claim this document makes — paste another build's capabilities
  into any of them and the form becomes that build's.
- [`capability-divergence.md`](./capability-divergence.md) — the three builds
  side by side, §2 for what they publish and §3 for what they accept.
- [`../impl/claude-python/docs/claude-python-guide.md`](../impl/claude-python/docs/claude-python-guide.md),
  [`../impl/codex-python/docs/codex-python-guide.md`](../impl/codex-python/docs/codex-python-guide.md),
  [`../impl/gemini-python/docs/gemini-python-guide.md`](../impl/gemini-python/docs/gemini-python-guide.md)
  — each build's own consumer guide.
- `spec/openapi/<impl>-<version>.json` — `components.schemas.RunOptions` and
  `components.schemas.Capabilities` carry the field descriptions this document
  routes to, and they are the authority over it.
