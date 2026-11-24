# Herdr: can agent-service host it and put an OpenAPI in front of it?

**This describes Herdr, the third-party terminal multiplexer, and what an HTTP
front for it would look like. Nothing in this repository uses it.** Written
2026-11-15 against **Herdr 0.9.5** (released 2026-10-14) and source commit
`ee5bfb5` (2026-10-29). Herdr is pre-1.0 and ships about once a week, so none of
this is a stability contract.

**Every claim carries one of three labels:**

- *read* — from Herdr's docs or source. Source and doc citations are
  `path:line` at commit `ee5bfb5` in
  <https://github.com/herdrdev/herdr/tree/ee5bfb5041bb3e4a49d591c72308aae3c81ecdde>.
  The website's pages are built from
  `docs/versions/0.9.5/website/src/content/docs/*.mdx` in that tree, and the
  live page agrees with it (<https://herdr.dev/tui/docs/socket-api/>, which
  shows "Latest 0.9.5").
- *measured (Linux)* — the official `herdr-linux-x86_64` 0.9.5 binary, run
  headless in a throwaway container. Details in §8.
- *measured (Windows)* — verified locally against herdr 0.9.5 on Windows on
  2026-11-15. This was a separate run, which tested the wire protocol by hand.

---

## 0. Verdict

**Hosting works, and a thin HTTP proxy is cheap to build.** Herdr has a
headless server mode (`herdr server`) that needs no TTY. It ships one static
musl binary for Linux. Its whole control surface is a documented,
schema-published, newline-delimited JSON protocol over a local socket, with
server-side waits and push events. In our own pi-python image it started, ran a
shell command, recognised `pi`, and reported its state, all with no terminal
attached and no network.

**Herdr cannot back the agent-service specification as a fifth build.** What it
gives a client is *screen text plus a five-value lifecycle state*
(`idle | working | blocked | done | unknown`). Most of that state is inferred
from regexes over the bottom of the screen. agent-service sells structured
turns: typed `AgentEvent`s, a `RunResponse` with `stop_kind`, usage and cost,
`RunOptions`, and a transcript. The builds we already have get these from the
same agents' own JSON or SDK output. Herdr has no equivalent for any of them
(§5).

**§10 revises that last point, and §11 is the recommendation that follows.** The
agent in a pane still writes its own transcript and still runs its own hooks.
So a build can take structured content from those files and hooks, take input
through Herdr, and parse nothing off the screen. §11 recommends that build,
`herdr-python`, behind the existing specification, over replacing
agent-service with Herdr. Its OpenAPI has no streaming routes; live output is
watched in Herdr's TUI.

**So an HTTP front over Herdr is a different product.** It would be an
interactive terminal-agent control plane, with panes, keystrokes and "needs
input" alerts. It would get its own specification and would not join
`spec/openapi/`. In the scope the user set, it has request and response
endpoints plus blocking waits and no streaming (§6). Humans watch live output by
attaching Herdr's own TUI (§6a). What Herdr does better than us is the `blocked` signal and
running agents that a human can also attach to. That is a capability we do not
sell, not a gap in what we do sell.

---

## 1. What Herdr is

- A terminal multiplexer for coding agents. A background server holds the PTYs
  and clients attach and detach. It detects 22 agent CLIs, among them Claude
  Code, Codex, Pi and Gemini CLI. Source: <https://herdr.dev/tui/>, *read*.
- **Licence: Apache-2.0.** `LICENSE` is the Apache 2.0 text, and
  `Cargo.toml:7` says `license = "Apache-2.0"`. *read*
- Written in Rust, version `0.9.5` (`Cargo.toml:3`). It vendors `ghostty-vt`
  for terminal emulation (`crates/ghostty-vt`). *read*
- Releases: the latest is `v0.9.5` (2026-10-14), with assets
  `herdr-linux-{x86_64,aarch64}`, `herdr-macos-{x86_64,aarch64}` and
  `herdr-windows-x86_64.zip`
  (<https://api.github.com/repos/herdrdev/herdr/releases/latest>). The Linux
  builds target `*-unknown-linux-musl` (`.github/workflows/release.yml:81-90`),
  so they are static and fit any base image. *read*
- Cadence: `CHANGELOG.md` lists 0.4.10 on 2026-04-14 (`:1078`) through 0.9.5
  on 2026-10-14 (`:5`). That is about 40 releases in six months. *read*
- Platforms: "stable-channel binaries for Linux, macOS, and Windows. Windows is
  generally available, with documented platform-specific limitations"
  (`install.mdx:6`). Windows uses ConPTY (`windows-beta.mdx:8`). *read*

## 2. (a) The programmatic interface that already exists

**There is one control surface with three wrappers: the agent skill, the CLI and
the raw socket** ("The layers share the same control surface",
`socket-api.mdx:10-18`). *read*

**Transport.** Newline-delimited JSON over a Unix domain socket, or a named pipe
on Windows. A request is `{"id","method","params"}` and a success is
`{"id","result":{...}}` (`socket-api.mdx:608-630`). An error is
`{"id","error":{"code","message"}}` (`:930-940`). *read*

- *measured (Windows)*: the pipe is `\\.\pipe\<socket path>`, and the file on
  disk holds only `pid:timestamp`. Each request is one newline-terminated JSON
  object and the response is one JSON line.

**The schema is published by the binary.** `herdr api schema --json` prints a
JSON Schema that covers requests, responses, errors, events and subscription
events (`socket-api.mdx:20-34`). *read*

- *measured (Windows)*: the dump is protocol `22`, `schema_version` `1`, with
  128 methods and events.
- The development tree's copy is `docs/next/api/herdr-api.schema.json`. *read*

**Methods** (`socket-api.mdx:97-112`, *read*). The ones an HTTP front would use:

| Area | Methods |
|---|---|
| Topology | `workspace.create/list/get/close`, `tab.create/list/close`, `pane.split/list/get/close`, `session.snapshot`, `layout.export/apply` |
| Raw terminal | `pane.send_text`, `pane.send_keys`, `pane.send_input`, `pane.read`, `pane.wait_for_output`, `pane.process_info` |
| Agents | `agent.start`, `agent.list`, `agent.get`, `agent.read`, `agent.prompt`, `agent.wait`, `agent.send_keys`, `agent.explain`, `agent.rename` |
| Events | `events.subscribe`, `events.wait` |
| State reporting | `pane.report_agent`, `pane.report_agent_session`, `pane.report_metadata` |
| Server | `ping`, `server.stop`, `server.reload_config`, `server.agent_manifests` |

**Parameter shapes, from the schema dump** (*read*):

- `agent.start {name, kind, pane_id, args[], timeout_ms}`. `timeout_ms` must be
  more than 3000 and at most 300000. **There is no `cwd`, `env` or `model`
  field.** Native flags go in `args`.
- `agent.prompt {target, text, wait?: {until: [status], timeout_ms}}`
  (`socket-api.mdx:114`). It submits and waits in one request, so there is no
  race between separate calls. It refuses a `blocked` agent with
  `agent_blocked`.
- `pane.read` and `agent.read`:
  `{pane_id|target, source, lines?, format?, strip_ansi=true}`.
  - `source` is one of `visible`, `recent`, `recent_unwrapped` or `detection`
    (`socket-api.mdx:845-855`).
- `pane.wait_for_output {pane_id, source, match, lines?, timeout_ms?}`.
  - *measured (Windows)*: `match` is `{type:"substring", value}`.

**Events** (`socket-api.mdx:773-841`, *read*):

- `events.subscribe {subscriptions:[...]}` keeps the connection open. The first
  line is the acknowledgement, and later lines are pushed events.
- The pane events are `pane.created`, `updated`, `closed`, `exited`,
  `agent_detected`, `output_matched`, `agent_status_changed` and
  `scroll_changed` (`:824-826`).
- `pane.agent_status_changed` carries
  `{pane_id, workspace_id, agent_status, agent?, display_agent?, title?, state_labels}`.
  This shape is from the schema dump.
- **Event history is not durable.** A subscriber that falls behind gets
  `events_lost` and its connection is closed. Recovery means resubscribing and
  reconciling against `session.snapshot` (`:796-817`).
- *measured (Windows)*: the acknowledgement is
  `{"id","result":{"type":"subscription_started"}}`, followed by
  `{"event","data"}` lines.
- *measured (Windows)*: `pane.output_matched` and pane creation events were
  received. `pane.agent_status_changed` requires `pane_id`.

**A raw byte stream exists, but only through the CLI.**
`herdr terminal session observe <pane> --cols --rows` prints NDJSON
`terminal.frame` records that hold base64 ANSI. `... session control` also reads
`terminal.input/resize/scroll/mouse/release` on stdin
(`persistence-remote.mdx:141-164`). *read*

- It goes through the private client socket and its numbered binary protocol,
  not the JSON API (`src/client/terminal_sessions.rs:19-27`, `:81`). *read*
- That protocol is "for same-install and internal operations"
  (`socket-api.mdx:955-957`). So a bridge would spawn the CLI rather than speak
  that protocol. *read*
- Direct attach is "available on Linux and macOS, not native Windows"
  (`persistence-remote.mdx:117`). *read*
- **Not confirmed:** whether `terminal session observe` works on Windows.

## 3. (b) Headless, in a container

- `herdr server` dispatches straight to `server::headless::run_server()`
  (`src/main.rs:569-570`). That function starts the JSON API socket, the app and
  the client socket, and then prints a ready message
  (`src/server/headless/bootstrap.rs:4-100`). It does not read or require a
  terminal at any point. *read*
- "`herdr server` runs the headless server explicitly. Use it for supervised or
  service-style setups" (`cli-reference.mdx:132`). *read*
- With no client attached, panes get a virtual terminal of
  `[server] headless_cols = 120`, `headless_rows = 40` (`src/main.rs:229-232`).
  *read*
- The server ignores `SIGHUP` and stops on `herdr server stop` or `SIGTERM`
  (`persistence-remote.mdx:16`). *read*
- Named sessions are separate servers with separate sockets, under
  `~/.config/herdr/sessions/<name>/herdr.sock`. The socket is resolved from
  `--session`, then `HERDR_SOCKET_PATH`, then `HERDR_SESSION`, then the default
  (`socket-api.mdx:632-650`). The config directory follows `XDG_CONFIG_HOME`
  (`src/config/io.rs:31`). *read*
- **Process detection in containers.** "Some restricted Linux runtimes do not
  expose a terminal foreground process group". The opt-in for that case is
  `HERDR_PROCESS_DETECTION=child-groups` (`agents.mdx:72`). *read*
- *measured (Linux)*: native detection worked under Docker Desktop's default
  runtime without the opt-in. **Not measured:** gVisor, rootless Podman, or
  Kubernetes with a restricted PSA.
- *measured (Linux)*: with stdin not a TTY and `--network none`, the server
  started and served the whole sequence in §8.
- *measured (Windows)*: `herdr --session <name> server` runs headless with no
  TTY.
- *measured (Windows)*: a session server restores its earlier workspaces when it
  restarts, so IDs cannot be predicted. Our container would start from an empty
  config directory each time. Persisting that directory would restore the old
  layout.

## 4. (c) How Herdr knows an agent's state, and how far to trust it

- **Screen detection is the default.** Herdr finds the agent's process in each
  pane and reads "the live bottom of the pane". "Rules in a detection manifest
  decide whether that screen means `idle`, `working`, or `blocked`"
  (`agents.mdx:62-66`). *read*
- A manifest is a TOML file of regex rules over named screen regions. For
  example, Claude's `osc_title_working` and `live_turn_working` match spinner
  glyphs and `esc to interrupt` (`src/detect/manifests/claude.toml:1-25`). The
  manifest's own comments track Claude's version-specific glyphs ("Braille
  covers <= 2.1.227; half-circles are the 2.1.228 busy spinner"). *read*
- **Some integrations report state themselves.** "When an integration also
  reports state, Herdr uses those reports instead of reading the screen"
  (`agents.mdx:64`). *read*
  - For Pi, `herdr integration install pi` writes
    `~/.pi/agent/extensions/herdr-agent-state.ts` (`integrations.mdx:62`, `:81`).
    That extension calls `pane.report_agent` and `pane.report_agent_session`
    (`src/integration/assets/pi/herdr-agent-state.ts:122`).
  - OpenCode, Kimi, Kilo, OMP and MastraCode work the same way.
  - Claude Code, Codex and Gemini CLI are **screen-only**. Gemini is marked
    "state only, less tested" (`agents.mdx:43`). Codex returned to screen
    detection in 0.9.5 (`CHANGELOG.md:9`).
- **`blocked` is strict, and an unknown blocking screen reads as `idle`.**
  "If no manifest rule matches for a known agent, Herdr falls back to `idle`".
  "Automation that trusts a mistaken idle state can type into an approval
  dialog" (`agents.mdx:74-78`). *read*
- `done` means idle but not yet seen. `unknown` "does not prove completion"
  (`cli-reference.mdx:361`). Antigravity and Grok read `idle` while their own
  background jobs still run (`agents.mdx:80`). *read*
- *measured (Linux)*: `pi`, with no credential, was classified `idle` by
  `default_known_agent_idle_fallback` with `rule: none`. That was the fallback,
  not a positive match, even though the screen showed a "No models available"
  warning.
- *measured (Windows)*: Claude Code's workspace-trust dialog was correctly
  classified `blocked`.
- **Manifests update themselves from the network.** Herdr fetches
  `https://herdr.dev/agent-detection/index.toml`
  (`src/detect/manifest_update.rs:16`) and applies newer rules "without
  requiring a Herdr restart" (`agents.mdx:86`). *read*
  - `[update] manifest_check = false` turns this off. The version check
    (`https://herdr.dev/latest.json`, `src/update.rs:25`) is turned off with
    `[update] version_check = false`.
  - *measured (Windows)*: `server.agent_manifests` reported `source_kind: remote`
    for pi, claude, codex, gemini, cursor and others. The rules in use were not
    the ones in the binary.

**Reliability, in summary.** The state is good for "should a human look at this
pane". It is not good for "this turn ended, and here is how". It has no
`stop_kind` and no error-versus-success. Its correctness depends on a regex
matching the current release of each agent's UI.

## 5. (d) Mapping agent-service's specification onto Herdr

The specification side is `spec/openapi/core-0.34.0-snapshot.json`. Herdr's side
is the socket methods above.

| agent-service | Herdr provides | Gap |
|---|---|---|
| `POST /v1/sessions` (`SessionCreate`, `RunOptions`) | `workspace.create` or `pane.split` (accepts `env`, `cwd`), then `agent.start {kind, args}` | `RunOptions` has no carrier. `model`, `system_prompt`, `allowed_tools`, `permission_mode`, `effort`, `mcp_servers` and `max_turns` become native CLI flags in `args`, different for each kind, and are fixed at start. Nothing validates them, so `unsupported_options` cannot be answered |
| `GET /v1/sessions`, `GET /v1/sessions/{sid}` (`SessionRecord.status idle/running/closed`) | `agent.list`, `agent.get` (`agent_status`, `agent_session` reference, `cwd`) | The status values map: `working` to `running`, `idle`/`done` to `idle`, exit to `closed`. `blocked` and `unknown` have no slot. There is no `turns`, `total_cost_usd`, `model` or `context_usage` |
| `DELETE /v1/sessions/{sid}` | `pane.close` | none |
| `PATCH /v1/sessions/{sid}` | `agent.rename` only | Model or permission changes mean typing the agent's own slash commands |
| `POST /v1/sessions/{sid}/messages` (`TurnRequest`, then `RunResponse`) | `agent.prompt {text, wait}` | Returns when the state *settles*, not when the turn ends (`socket-api.mdx:114`). The reply exists only as screen text from `agent.read`. `result`, `is_error`, `stop_kind`, `usage`, `token_usage`, `model_usage`, `total_cost_usd`, `num_turns` and `permission_denials` cannot be produced |
| `POST .../messages/stream` (SSE of `AgentEvent`: `assistant/user/result/stream_event/...`) | **Intentionally not provided; watch through TUI attach (§6a).** Herdr has the primitives (`events.subscribe`, `terminal session observe`), but this scope does not use them | Even if it were built, there is no typed message, tool call or result event. It would carry state transitions and screen deltas, which is a different event vocabulary |
| `POST .../interrupt` | `agent.send_keys esc` or `ctrl+c` | Best effort. The effect is read back from the screen |
| `POST /v1/query` (one-shot) | create a pane, start, prompt with wait, read, close | The same gaps as a turn, plus the start-up latency of a TUI |
| `POST /v1/query/stream` | **Intentionally not provided; watch through TUI attach (§6a)** | as above |
| `GET .../transcript` (`TranscriptPage`) | `agent_session` gives the agent's own session ID or path (`socket-api.mdx:708-721`) | A wrapper could parse the agent's native session file, for example Pi's JSONL. That is per-agent work that agent-service already does without Herdr |
| `GET /v1/runs/{run_id}` | nothing | Runs would be a wrapper-side ledger |
| `GET /v1/deployment` | `ping` (version, protocol, capabilities), `server.agent_manifests` | It describes Herdr, not the agent's options or limits |
| *no equivalent in agent-service* | `blocked` state, `agent.wait --until blocked`, human attach through `terminal session control`, layouts, worktrees | This is what Herdr adds |

**Conclusion of the mapping.** Herdr can satisfy the session lifecycle and a
lossy `messages` call. It cannot produce `RunResponse` or `AgentEvent` without
per-agent screen or transcript parsers, and the existing builds already avoid
those by using `--mode json` and the SDKs. It would fail the conformance suite
wherever a result or event is asserted. **It is not a fifth build.** Our builds
are one product per target agent. Herdr is a host for many targets, and its
subject is the terminal.

## 6. Architecture sketch, if built as its own product

**A thin proxy over the JSON socket, recommended, using request and response
only.** One container holds a `herdr server`, the agent CLIs it may start, and a
small HTTP process. That process opens one socket connection per HTTP request
and holds no subscription. Do not drive a TUI through our own PTY: Herdr
already owns the PTYs, keeps the virtual screen, and runs the waits on the
server side. Scraping a second terminal would only add a layer.

**There is no streaming endpoint (user's scope).** A human watches live output
by attaching Herdr's own TUI (§6a). A client learns that a turn finished from a
**blocking wait**. Herdr's `agent.wait` and `agent.prompt {wait}` are
server-owned and event-driven, and they pin the pane's current occupant so a
replacement agent cannot satisfy the wait (`socket-api.mdx:114`). So a blocking
HTTP call maps one-to-one onto one socket request.

```
POST   /v1/workspaces                {cwd, label?, env?}              -> {workspace, tab, root_pane}  workspace.create
GET    /v1/workspaces                                                 -> [WorkspaceInfo]             workspace.list
DELETE /v1/workspaces/{ws}                                                                           workspace.close
POST   /v1/panes                     {split_from, direction, cwd?, env?} -> PaneInfo                 pane.split
GET    /v1/panes?workspace=          -> [PaneInfo]                                                   pane.list
GET    /v1/panes/{pane_id}           -> PaneInfo                                                     pane.get
DELETE /v1/panes/{pane_id}                                                                           pane.close
GET    /v1/panes/{pane_id}/output    ?source=recent_unwrapped&lines=N -> {text, truncated, revision} pane.read (snapshot)
POST   /v1/panes/{pane_id}/agent     {name, kind, args?, timeout_ms?}   -> AgentInfo                 agent.start
GET    /v1/agents                                                     -> [AgentInfo]                agent.list
GET    /v1/agents/{name}             -> AgentInfo (agent_status, agent_session, ...)                agent.get
POST   /v1/agents/{name}/prompt      {text, wait?:{until[], timeout_ms}} -> {submitted, status}     agent.prompt
POST   /v1/agents/{name}/keys        {keys:[...]}  allow-listed: esc, ctrl+c, enter, arrows, y/n    agent.send_keys
GET    /v1/agents/{name}/output      ?source=&lines=  -> {text, truncated}                          agent.read (snapshot)
POST   /v1/agents/{name}/wait        {until[]?, timeout_ms} -> 200 {status} | 408 timeout           agent.wait (blocking)
POST   /v1/panes/{pane_id}/wait      {match:{type,value}, source, timeout_ms} -> {matched_line, read} | 408   pane.wait_for_output
GET    /v1/info                      -> {herdr_version, protocol, capabilities, manifests}          ping, server.agent_manifests
```

**Design points:**

- **Cap the wait.** `timeout_ms` on the HTTP side must be at most the proxy's
  and any load balancer's idle timeout. A client that wants longer re-issues
  the wait, which makes it a long poll. A wait with no timeout waits forever on
  the server side (`cli-reference.mdx:419`), so the proxy must always pass one.
- **A timeout proves nothing about delivery.** "A timeout or stalled response
  does not prove the prompt was never delivered; do not blindly submit it
  again" (`skills/herdr/SKILL.md:171`). So `prompt` is not safely retryable.
  Return `agent_prompt_stalled` and `timeout` as distinct problem types.
- **A disconnect cancels nothing.** If the HTTP client goes away, the socket
  request is dropped. Herdr's documentation does not say whether that cancels
  anything server-side. **Not confirmed.**
- **Raw `pane.send_text` stays out of the HTTP surface by default.** See §7.

## 6a. How a human attaches to the Herdr server in our container

**Herdr opens no network port.** Every path below reaches the server through its
local Unix sockets: the JSON API socket and a separate client socket
(`src/server/headless/bootstrap.rs:44-96`). A remote client runs over SSH and
spawns `herdr remote-client-bridge` or `herdr remote-api-bridge` on the server
side (`src/main.rs:560-566`). No `TcpListener` exists outside tests in `src/`.
*read*

| Path | How | Source |
|---|---|---|
| `docker exec -it <ctr> herdr` | Opens the full TUI inside the container, against the running server. It needs a TTY, so use `-it`. Running `herdr` with no arguments "launches or attaches the TUI" | `skills/herdr/SKILL.md:43`; `persistence-remote.mdx:12` ("Reattach by running `herdr` again") |
| `docker exec -it <ctr> herdr session attach <name>` | The same, for a named session. Our server would run as `herdr --session <name> server` | `persistence-remote.mdx:18-30`; `cli-reference.mdx:146` |
| `docker exec -it <ctr> herdr agent attach <name>` | One agent's terminal, not the whole UI. Linux and macOS only. `--takeover` replaces the input owner | `persistence-remote.mdx:113-139` |
| `herdr --remote <ssh-target> [--session <name>]` | Draws the UI locally and runs the server's panes remotely, over **SSH**. Requires an sshd in the container, or a host the container is reachable from | `persistence-remote.mdx:46-111`; `how-to-work.mdx:73-82` |
| `herdr machine add <ssh-target> [--remote-session <name>]` | Saves the container as a "machine" beside Local in one window. Also over SSH. Setup may offer to **install or replace** the remote Herdr; the default answer is No | `connecting-machines.mdx:20-52` |

**What this means for ports, sockets and auth:**

- **`docker exec` needs no port at all.** Its auth is whoever may call the
  Docker API, and that is root-equivalent on the host. It is the simplest path,
  and it is an operator path, not a user path.
- **`--remote` and `machine add` need an SSH endpoint** (port 22 or a mapped
  port) and an `sshd` in the image, which none of our images ship today. Auth is
  "your normal OpenSSH authentication" (`persistence-remote.mdx:80`). Host keys
  are checked as normal (`connecting-machines.mdx:16`).
  - The SSH user must be **the same uid as the server**, because the sockets are
    `0600` (`src/api/server.rs:29`).
  - Anyone who can SSH in as that user has full control of every pane. Herdr
    has no per-user or read-only role. "Multiple Herdr clients can also view
    different tabs on the same server" (`connecting-machines.mdx:66`), and every
    attached client has full control.
- **Never publish the socket.** Bind-mounting the socket directory to the host,
  or relaying it over TCP with something like `socat`, would expose an
  unauthenticated control channel equivalent to a shell.
- **The HTTP proxy and an attached human share one server.** The agent the API
  started is the agent the human sees, and a human can type into it. That is the
  point of this scope, and it also means the API's view of state can change
  under it. A human approving a `blocked` dialog moves the agent to `working`
  with no API call.
- **Some docs are platform-specific.** Direct `agent attach` is not available on
  native Windows (`persistence-remote.mdx:117`). That does not affect a Linux
  container.

## 7. (e) Risks

- **Command injection is the product.** `pane.send_text` and `pane.run` type
  into a shell. `pane.split`, `workspace.create` and `layout.apply` take argv
  and `env`. `plugin.link` and `plugin.action.invoke` run commands from
  manifests. `integration.install` writes into agents' config directories
  (`socket-api.mdx:97-112`, `:212-251`, `:449-606`). *read*
  - An HTTP front that forwards these grants remote shell access in the
    container. Expose an allow-listed subset, and keep the shell, plugin and
    integration methods off the network.
- **The socket's auth is file mode 0600 and nothing else.**
  `SOCKET_PERMISSION_MODE = 0o600` (`src/api/server.rs:29`) is applied at bind
  (`:91`). *read*
  - Anything running as the same user can drive every pane, and every pane
    process gets `HERDR_SOCKET_PATH` (`socket-api.mdx:253-257`). So the agent in
    pane A can drive pane B. That is a documented feature and it crosses tenant
    lines.
  - Run one server per tenant or session, and put HTTP auth in front.
- **Protocol churn.** About 40 releases in six months. The public API has
  removed methods outright: `pane.graphics.*` "are no longer available. There
  is no replacement" (`socket-api.mdx:185-188`). The private protocol is at
  version 22. *read*
  - The mitigation is in the docs: "ignore unknown fields and handle
    unsupported methods as normal errors" (`:958`). Pin the binary by sha256.
- **Fragile detection.** The state comes from regexes over a UI that the agent's
  vendor changes at will. Remote manifest updates move the regexes under a
  running server (§4).
  - Pinning means `manifest_check = false`, which means stale rules after an
    agent upgrade.
  - The remote fetch is also a supply-chain input. It changes behaviour without
    an image change. We do not let the agent CLIs do that either: images pin
    them.
- **Output is screen text.** `--lines` reads only what the virtual terminal and
  scrollback hold. "not every application or response can be recovered this
  way" (`skills/herdr/SKILL.md:200`, identical to the locally installed skill).
  - *measured (Linux)*: `pane wait-output --match hello-from-herdr` matched the
    **echoed command line** `$ echo hello-from-herdr`, not the output. A
    substring match on input the caller typed proves nothing.
- **Network egress by default** to `herdr.dev`, for version and manifest checks
  (§4). Turn both off in an image.
- **Pane env exposes credentials.** A key placed in a pane's env can be read by
  anything typed into that pane (§9).

## 8. What was run (*measured (Linux)*)

**Binary.** `herdr-linux-x86_64` v0.9.5, downloaded from the release into the
session scratchpad. Its sha256
`14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d` matches the
value in `https://herdr.dev/latest.json`. Nothing was installed on the host.

**Container.**
`docker run --rm -i --network none --entrypoint sh agent-service-pi-python:0.33.0`.
That image already ships `pi` 1.4.0. The binary was mounted read-only, stdin
was not a TTY, `HOME=/tmp/h`, and the config set `version_check = false` and
`manifest_check = false`.

**Sequence and results:**

1. `herdr server &` printed `api socket: /tmp/h/.config/herdr/herdr.sock`.
2. `herdr status` reported server `running`, protocol `22`,
   `endpoint_compatible: yes`.
3. `workspace create --cwd /tmp/work` returned `root_pane.pane_id = "w1:p1"`.
   The pane was `viewport_rows: 40` and `agent_status: "unknown"`.
4. `pane run w1:p1 "echo hello-from-herdr"` printed nothing on success.
5. `pane wait-output --match hello-from-herdr` returned `output_matched`, with
   the echo caveat in §7.
6. `pane read --source recent-unwrapped` returned the shell text.
7. `agent start probe --kind pi --pane w1:p1` returned `agent_started`,
   `argv: ["pi"]`, `agent_status: "idle"`, `interactive_ready: true`.
   - *measured (Windows)*: by contrast, `agent.start` with `kind:"claude"`
     returned `launch_pending: true`. It types the command into the pane's
     shell.
8. `agent read` showed Pi's TUI ("No models available", plus the failed
   `fd`/`ripgrep` downloads caused by `--network none`).
9. `agent explain` gave `state: idle`, `manifest: bundled 2026.10.01.1`,
   `rule: none`, `fallback_reason: default_known_agent_idle_fallback`.
10. `server stop` made the server exit with status 0.

**Not run here:** a real prompted turn, because there was no credential, and
`events.subscribe`, which the Windows run covered.

## 9. Agent-gateway settings under Herdr

**How our builds configure a gateway.** Each build reads its vendor's
environment variables. The `endpoint_source` and `gateway_map_source` rows of
[`capability-divergence.md`](./capability-divergence.md) list them:

- endpoints: `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` and
  `GOOGLE_GEMINI_BASE_URL`, plus `HTTPS_PROXY` and
  `AGENT_SERVICE_PROVIDER_GATEWAYS` for pi;
- credentials: `ANTHROPIC_API_KEY` and the equivalents for the other vendors;
- CA bundles: `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS`.

**How environment reaches an agent under Herdr** (*measured (Windows)*):

- the env of the `herdr server` process is inherited by every pane;
- `env` on `workspace.create` reaches that workspace's root pane shell;
- `env` on `pane.split` reaches the new pane;
- `HERDR_ENV=1` is set in panes;
- `agent.start` has no env field, so the agent inherits its pane's env.

The docs say the same thing: launch `env` applies "to the newly launched
process only", and Herdr's own variables win any conflict
(`socket-api.mdx:253-257`). *read*

**So a gateway can be set at three scopes:** per container (the server's env),
per workspace, or per pane.

**What carries over, and what does not:**

- **The vendor variables carry over unchanged.** The native CLIs read
  `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `GOOGLE_GEMINI_BASE_URL`,
  `HTTPS_PROXY` and the CA-bundle variables themselves, whoever spawned them.
- **`AGENT_SERVICE_PROVIDER_GATEWAYS` does not.** Neither do our seeded agent
  homes. Both are agent-service's own machinery, and Herdr would not apply them.
  Pi under Herdr gets only `HTTPS_PROXY` unless something writes Pi's own
  models configuration first.
- **Credentials in pane env are readable by anything typed into that pane.**
  Through `HERDR_SOCKET_PATH`, any other pane can type into that pane.
- **Not verified:** nothing was ever sent to a gateway end to end.

## 10. Structured events from an agent CLI running in a Herdr pane

**The verdict in §0 assumed the only output is the screen. It is not, and that
changes what a Herdr build could carry.** An interactive agent CLI in a pane
still writes its own structured record and still runs its own hooks. Herdr's
own integrations already use the hooks to tie a pane to a session. So the
design is: **Herdr hosts the terminal and takes the input; the agent's own
hooks and transcript provide the events. Nothing is parsed off the screen.**

Written 2026-11-15. The Herdr facts are *read* from the source at `ee5bfb5`.
The Claude Code facts are *read* from <https://code.claude.com/docs/en/hooks>
on the same day. **Nothing in this section has been run end to end.**

### 10.1 Four sources, one job each

| Need | Source | Why this one |
|---|---|---|
| Which session a pane holds | **Herdr's own integration**: a `SessionStart` hook that reports to Herdr | Already built and maintained upstream, for Claude Code and Codex |
| Content: messages, tool calls, tool results, usage | **The agent's transcript file**, followed as it grows | The CLI writes it in interactive mode anyway, and it holds the same records our builds already translate |
| Turn boundaries and "needs approval" | **Our own hooks**, sent to a collector inside the build | The agent fires these itself, so they are exact. They replace the screen regexes of §4 |
| Usage and cost | The transcript's usage fields where the agent writes them; otherwise the gateway's per-call records | No dependency on Herdr at all |

### 10.2 Pane to session: what Herdr already does

- `herdr integration install claude` adds a `SessionStart` command hook to
  Claude Code's settings (`src/integration/claude_settings.rs:44`, `:65-76`).
  The hook script reads the hook's JSON input and drops every event except
  `SessionStart` from a main agent (subagents are skipped). It takes
  `session_id` and `transcript_path` and sends `pane.report_agent_session` to
  Herdr's socket, with `agent_session_path` set to the transcript path
  (`src/integration/assets/claude/herdr-agent-state.sh:50-80`).
- `herdr integration install codex` does the same through Codex's `hooks.json`
  and `config.toml` (`src/integration/targets.rs:162-171`). Its script also
  forwards only `SessionStart`, also with `transcript_path`
  (`src/integration/assets/codex/herdr-agent-state.sh:51-80`).
- The upstream purpose is session restore after a server restart
  (`integrations.mdx:6`, `:64`). For our purpose, the effect is that
  `agent.get` on a pane returns the agent's own session ID and transcript path
  (`AgentSessionInfo` in the event schema: `source`, `agent`, `kind`
  `id | path`, `value`). **The wrapper never has to guess which file belongs to
  which pane.**
- **These hooks report identity, not state.** State for Claude Code, Codex and
  Gemini stays screen-only (§4). That is why 10.4 adds hooks of our own.

### 10.3 Content: follow the transcript

| Agent | Where it writes | Fit | What our builds already know |
|---|---|---|---|
| Claude Code | JSONL under `<home>/projects/<cwd-slug>/<session>.jsonl`; the path arrives as `transcript_path` | **Good.** Append-only, one record per message, usage on each assistant message | `agent_home.conversations` is under `projects/` ([capability-divergence.md](./capability-divergence.md)) |
| Codex | Rollout JSONL under `$CODEX_HOME/sessions/...`; the path arrives as `transcript_path` | **Good** | `conversations` under `sessions/` (same table) |
| Pi | Session JSONL; Pi's own integration reports the session | **Good** | Our build keeps sessions in `AGENT_SERVICE_SESSION_STORE` |
| Gemini CLI | A saved chat file | **Unconfirmed.** Not known to be append-only, and Herdr marks Gemini "state only, less tested" (`agents.mdx:43`) | Our build keeps its own transcript store, which suggests the native file was not enough |

**How it works.** Follow the file by byte offset. Translate each new record into
the `AgentEvent` vocabulary the existing builds already emit, so the event
*shapes* stay the same. That translation is per-agent code, but it reads the
same record types that `claude-python` and `codex-python` already handle from
the SDKs.

**What this is not:** a documented interface. A transcript format is the CLI's
own internal format and can change in any release. **Pin each CLI's version in
the image, and cover the parser with a conformance fixture per pinned version.**

### 10.4 Turn boundaries and approvals: hooks of our own

Claude Code fires the same hook events "wherever it runs: sessions in the
terminal, IDE extensions, the Desktop app, and cloud sessions", so interactive
mode in a pane is covered (*read*, hooks reference).

- **Every hook's input carries** `session_id`, `prompt_id`, `transcript_path`,
  `cwd`, `permission_mode`, `effort` and `hook_event_name` (*read*).
- **The events a turn needs:**

  | Event | Turn meaning |
  |---|---|
  | `UserPromptSubmit` | the turn began; `prompt_id` keys it |
  | `PreToolUse` / `PostToolUse` / `PostToolUseFailure` | tool start and end, with `tool_name`, `tool_input` and `tool_use_id` |
  | `PermissionRequest`, `Notification` (matcher `permission_prompt`) | **`blocked`, exact rather than inferred**, so §4's "unknown dialog reads as idle" goes away |
  | `Stop` | **the turn ended.** `last_assistant_message` carries the final text, which becomes the result. Screen scraping is not needed |
  | `StopFailure` | the turn ended in error |
  | `SessionEnd` | the session closed |

- **No script is needed.** Claude Code has an `http` hook type. It POSTs the
  event's JSON, with `Content-Type: application/json`, to a URL, with optional
  headers taken from allow-listed environment variables (*read*). The build
  writes these hooks into the agent's settings, pointing at a collector on
  loopback inside the container.
- **Keep our hooks off Herdr's socket.** The agent can already reach that socket
  (§7). Our hooks talk to our collector, with its own token, and nothing else.
- **Codex:** Herdr's integration proves Codex runs command hooks from
  `hooks.json` (10.2). Which turn events Codex fires has **not been checked
  here**.

### 10.5 One turn, end to end

1. **Session start.** `pane.split` with the gateway environment (§9), then
   `agent.start`. Herdr's `SessionStart` hook reports the transcript path, and
   `agent.get` returns it.
2. **Prompt.** `agent.prompt` without a wait. The `UserPromptSubmit` hook opens
   the turn and supplies its `prompt_id`.
3. **During the turn.** Each new transcript record becomes an `AgentEvent`.
   Tool hooks mark tool boundaries. A `PermissionRequest` sets the session to
   `blocked`.
4. **End.** `Stop` closes the turn: `result` comes from
   `last_assistant_message`, and usage comes from the transcript. `StopFailure`
   is an error result.
5. **Interrupt.** `agent.send_keys esc` sends the key. Its effect is confirmed
   by `Stop` or `StopFailure`, not read off the screen.

**None of this is streamed to the HTTP client** (user, 2026-11-15: the OpenAPI
does not stream, and Herdr's TUI is where live output is watched). The events
are collected for three uses: the blocking turn's `RunResponse`, the session's
`GET .../transcript` and the run record behind `GET /v1/runs/{run_id}`. A
person who wants to watch the turn happen attaches the TUI (§6a).

`stop_kind` comes from which hook ended the turn. A turn that only Herdr's
screen state says has finished, with no `Stop`, is reported as `unknown` and
never as success.

### 10.6 Not confirmed

- Whether the whole loop runs for Claude Code in a pane under the consumer's
  container restrictions (no `SYS_ADMIN`, `no-new-privileges`, uid 1000). This
  is the trial to run first.
- How a hook behaves when the collector is down. Hook timeouts and failure
  semantics must be set so a dead collector never stalls the agent.
- Which turn events Codex and Gemini CLI fire, and whether Gemini's chat file
  can be followed.
- Whether a turn can be lost between `Stop` and the transcript's last record
  being flushed. The collector must wait for both.

### 10.7 Capturing communication between agents in different panes

**Requirement (user, 2026-11-15): every exchange between agents in different
panes is captured** — who sent what to whom, and what came back. Not streamed;
recorded, and readable afterwards.

**Herdr does not record it, and cannot be made to** (*read* at `ee5bfb5`):

- Agents talk by running `herdr` commands from their own shell tool, or by
  writing to the socket directly: `agent prompt <other>`, `pane send-text`,
  `agent read <other>`. Each is one socket request.
- The event list has output, state and topology events (`pane.output_matched`,
  `pane.agent_status_changed`, `pane.created`...) and **no event for input**.
  Nothing tells a subscriber that pane A typed into pane B.
- The API server does not log requests.
- `HERDR_SOCKET_PATH` cannot be redirected to a recording proxy. "Herdr-managed
  variables are authoritative when they conflict with caller-provided env"
  (`socket-api.mdx:253-257`), and every pane runs as the server's own user, so
  a pane can always reach the real socket.

**So capture has to come from the agents, at both ends of each exchange:**

| End | Captured by | What it gives | Gap on its own |
|---|---|---|---|
| **Sender** | A tool the build serves to every agent, over MCP: `send_to_agent {to, text, wait?}` and `read_agent {name}`. The build calls Herdr's `agent.prompt` / `agent.read` and writes the record first | The sender's session (the MCP connection is per pane, so the sender is known and not self-declared), the receiver, the text, the reply, timestamps, and a message ID | An agent that ignores the tool and calls `herdr` or the socket directly is not seen here |
| **Receiver** | Our `UserPromptSubmit` hook (§10.4) on every agent | **Every** prompt that reaches an agent, whoever typed it: the text, the receiving session and its `prompt_id` | It does not know the sender, because typed input carries none |

**Joining the two ends makes the record complete:**

- A receiver prompt that matches a sender record (same receiver, same text,
  inside a short window; better, a message ID the tool prefixes to the text)
  becomes **one exchange**: sender, receiver, request, reply turn.
- A receiver prompt with **no** sender record is still recorded, as
  `unattributed`. It is either a human typing in the attached TUI or an agent
  that bypassed the tool. **Nothing reaches an agent unrecorded**, even though
  not everything is attributed.
- `read_agent` gives the sender's view of the receiver's reply, and the
  receiver's own transcript (§10.3) gives the reply as written. The record
  keeps both.
- The sender's own `PreToolUse` hook on a shell command that starts with
  `herdr ` is a third, weaker signal. It attributes a bypass, but only when the
  command is legible, so treat it as a hint.

**Make the tool the path of least resistance.** Our build writes the agents'
instructions and the MCP configuration, so it can tell each agent to use
`send_to_agent` and leave Herdr's own `herdr` skill uninstalled. That does not
*prevent* a bypass, because the socket is reachable (§7). It makes a bypass
rare, and visible when it happens.

**Where the record goes.** A ledger in the build, beside the run ledger, read
through a new route such as `GET /v1/exchanges?session=&since=`. Each record
carries `exchange_id`, `from_session` (or `unattributed`), `to_session`,
`request_text`, `request_prompt_id`, `reply` (result, `stop_kind`), and
timestamps. **That route is a proposal.** It is new surface in the
specification and would need its own version and agreement before it exists.

**Why this also answers §11.3.** Routed through the build's tool, agents talk to
each other *through* something that owns identity and the record. That is the
mediated channel §11.3 asks for, not the shared socket. A consumer can later
put its own policy on the same tool, deciding who may prompt whom, without
changing the agents.

**Not confirmed:** none of this has been run. Two things to test first: whether
the tool's prefix survives into the receiver's `UserPromptSubmit` text
unchanged, and how often agents ignore the tool and run `herdr` directly.

## 11. Should Herdr replace agent-service?

**The proposal (user, 2026-11-15):** put Herdr behind the consumers in place of
agent-service. The argument has three parts:

- Herdr supports many agent CLIs.
- Agents in one Herdr server can talk to each other with Herdr commands.
- The consumers would benefit, and nobody would have to maintain agent-service
  build by build.

**Recommendation: no. Use Herdr *inside* agent-service, as the host for one new
build, and keep agent-service as the contract.** The reasons follow, then the
shape that gets most of the benefit.

### 11.1 Herdr does not remove the per-agent work

**What a build costs is the agent's own behaviour, not the process it runs in.**
The evidence is this repository's own history:

- The third build, `gemini-python`, cost the shared core nothing and needed
  eleven fixes in the build itself.
- Every one of them was about the agent's own behaviour: a relative
  `CODEX_HOME`, a CLI inferring a provider from a base URL, a model silently
  substituted for the one asked for, gateway maps keyed on the agent's own
  provider IDs ([capability-divergence.md](./capability-divergence.md),
  [running-locally.md](./running-locally.md)).
- Herdr removes none of that, because it is in the agent and not in the
  terminal.

**Under Herdr, the per-agent work moves; it does not disappear.** For each
agent the consumers need:

- an option mapping, from `RunOptions` to that CLI's flags and settings;
- a gateway setup (§9), where Pi's provider map and our seeded homes are not
  applied by Herdr;
- MCP configuration, which a workflow that moves work items through MCP tools
  cannot do without;
- a transcript parser and a hook installer (§10);
- version pinning, because a TUI changes faster than a vendor's JSON mode.

**"Supports 22 CLIs" means Herdr recognises them on screen,** and for most of
them guesses state from regexes (§4). It does not mean structured integration.
A CLI we have no parser for gives a consumer screen text and a five-value state.

### 11.2 A TUI is the wrong automation surface

- **Vendors support headless JSON modes for automation.** Our builds use them:
  the Agent SDK, Codex's SDK, Gemini's and Pi's JSON output.
- **The TUI is built for a human.** Trust dialogs, onboarding screens, update
  prompts and spinners all change between releases. Herdr's Claude manifest
  already tracks spinner glyphs version by version (§4).
- **Driving it with keys** is best effort, and confirming the result needs the
  hooks of §10.

### 11.3 Agents talking through Herdr bypasses the consumer

- **Agent-to-agent control through Herdr works by every pane being able to
  drive every other pane through one socket** (§7). That is the same property
  §7 lists as a risk.
- **What the consumers have today is orchestration they own.** They decide who
  may prompt whom, they hold the budget and the audit trail, and they isolate
  one agent per container. Moving coordination into a shared terminal socket
  gives that up: no authorisation between agents, no per-agent identity at the
  gateway, and shared files and credentials across agents in one container.
- **If agents should hand work to each other, the consumer can expose that as a
  tool** (for example an MCP tool) that routes through its own control plane.
  The agent asks; the orchestrator decides.

### 11.4 Replacing the contract costs the consumers more than it saves

- **The consumers depend on agent-service's specification**: typed events,
  `RunResponse`, capabilities and the conformance suite. They do not depend on
  the builds behind it.
- **Swapping agent-service for raw Herdr** would move every per-agent
  difference into each consumer. That is the work this repository exists to
  absorb once.
- **Herdr itself is pre-1.0,** with about 40 releases in six months and methods
  removed with no replacement (§7). It is a poor thing to make the contract
  itself.

### 11.5 What to do instead: one Herdr-hosted build

**Add one build, `herdr-python`, that implements the existing specification on
top of Herdr, with a per-agent adapter inside it.**

- **Shared once, inside the build:**
  - the HTTP surface;
  - the session and run ledger;
  - pane and workspace management;
  - the hook collector;
  - the transcript follower;
  - the image, with Herdr and its manifests pinned.
- **Per agent:** a small adapter: option mapping, gateway setup, MCP
  configuration, the hook installer and the transcript parser. That is smaller
  than a build today, because the HTTP, ledger, process and image layers are
  shared.
- **Published honestly.** `/v1/capabilities` names the agent kinds it serves
  and what each one degrades. [capability-divergence.md](./capability-divergence.md)
  gets the column.
- **What the consumers gain without changing:**
  - more agent CLIs, one adapter each;
  - a `blocked` signal that comes from the agent;
  - a human able to attach to the live TUI (§6a).
- **What the consumers would change:** they would recognise the new build name
  and use the blocking turn route. **The OpenAPI has no streaming route at all
  (user, 2026-11-15).** Live output is Herdr's TUI's job (§6a), so this build
  publishes no `.../stream` paths and does not imitate one.
- **Order:**
  1. Run the trial in 10.6 for Claude Code.
  2. Build the Pi adapter first, because Pi reports its own state to Herdr.
  3. Measure against the conformance suite before adding a second agent kind.
- **Keep the existing builds** until a Herdr adapter for the same agent passes
  the same conformance checks. The SDK builds stay the reference for what a
  turn must contain.

### 11.6 Direction (user, 2026-11-15)

**The new agent-service hosts Herdr, and only Herdr.** It replaces the four
per-CLI builds: one image, one build, Herdr in front of the agent CLIs. It does
not keep a build per CLI. agent-service stays the contract the consumers
depend on. Herdr is what it runs on, not what they call.

**What "only Herdr" still contains**, so the scope is not underestimated:

- **The agent CLIs themselves.** Herdr starts them and does not ship them, so
  the image still installs and pins each CLI it offers.
- **One adapter per CLI inside the build**, as listed in 11.5. Supporting a new
  CLI in Herdr is free. *Serving* it through this contract costs one adapter.
  Until a CLI has one, the build can offer it only as degraded (screen text and
  Herdr's state), and `/v1/capabilities` must say so.

**Order:** retire each existing build when the Herdr adapter for the same agent
passes the conformance checks that build passes, not before. Each existing
build is the reference for what its agent's turn must contain, and retiring it
first would leave nothing to measure the adapter against. Pi goes first (11.5).

## 12. Can Herdr's plugin mechanism do the work instead?

**Question (user, 2026-11-15):** can Herdr's plugins serve the purposes of
§10 and §11, so that less of the build is our own code?

**Verdict: no, for every purpose that matters. Keep the design in §10 and §11.**
A plugin extends Herdr *outwards*. It is a command that Herdr starts, and that
command calls back into the same CLI and socket that any client can use. A
plugin cannot extend Herdr *inwards*. It cannot add a socket method, intercept a
request, see input, or read pane output through a hook. Each thing §10 needs is
one of those.

Every fact in this section is *read* from the source at `ee5bfb5`. **Nothing in
this section was run.** Linking a plugin writes to the user's global Herdr
configuration, which is outside this repository.

### 12.1 What a plugin is

- A plugin is a directory with a `herdr-plugin.toml` manifest. The manifest
  declares `[[build]]`, `[[startup]]`, `[[actions]]`, `[[events]]`,
  `[[panes]]` and `[[link_handlers]]`. Each entry is an argv command
  (`plugins.mdx:54-121`).
- "There is no separate plugin SDK or restricted command set. The entire Herdr
  CLI is the plugin API" (`plugins.mdx:23-29`). A plugin has no capability that
  an ordinary client does not also have.
- "Runtime action registration and native non-terminal plugin UI are not part of
  plugin v1" (`plugins.mdx:31-33`). Everything is declared in the manifest.
- Each command runs as the server's user, with the server's environment and
  socket. Herdr adds `HERDR_SOCKET_PATH`, `HERDR_BIN_PATH`, `HERDR_PLUGIN_*`
  and, for an event hook, `HERDR_PLUGIN_EVENT_JSON`
  (`src/app/api/plugins/runtime.rs:16-75`, `plugins.mdx:265-275`). Herdr "does
  not review or sandbox plugin code" (`plugins.mdx:49-52`).
- Installed and linked plugins are "global to the current user and available in
  every Herdr session" (`plugins.mdx:204-206`).

### 12.2 What an event hook can see

- Every emitted event goes through `run_plugin_event_hooks` before it reaches
  subscribers (`src/app/api.rs:798-801`).
- That function returns at once unless the event is in
  `PLUGIN_HOOK_EVENT_KINDS` (`src/app/api/plugins/runtime.rs:203-207`). The list
  is workspace, worktree and tab lifecycle, plus `pane.created`, `closed`,
  `focused`, `moved`, `exited`, `agent_detected` and `agent_status_changed`
  (`src/api/schema/events.rs:286-309`).
- `pane.output_changed`, `pane.updated` and `layout.updated` are excluded on
  purpose, "until high-volume output-change hook semantics are implemented"
  (`src/api/schema/events.rs:320-322`). A test asserts the exclusion (`:351-358`).
- **No event kind describes input** (`EventKind`, `src/api/schema/events.rs:195-220`).
  This is the same gap §10.7 found for subscribers.
- Each hook is a new process for each event. At most 32 plugin commands can run
  at once (`MAX_PLUGIN_COMMANDS_IN_FLIGHT`, `runtime.rs:12`). Above that limit,
  Herdr does not start the command and logs it as `Failed` with "maximum
  concurrent plugin commands reached" (`runtime.rs:82-100`). Only the last 200
  logs are kept (`runtime.rs:13`). **So a hook is not a reliable event feed.**
  Under load, hooks are dropped. `events.subscribe` is the reliable feed, and it
  tells a subscriber when events were lost (§2).

### 12.3 Each purpose, against the mechanism

| Purpose (section) | Can a plugin do it? | Why |
|---|---|---|
| Find the session a pane holds (§10.2) | **Not needed** | Herdr's own integrations already report it, through the agent's `SessionStart` hook. A plugin adds nothing |
| Structured content: messages, tool calls, usage (§10.3) | **No** | No hook receives output. The content is in the agent's transcript, and the build follows that file directly |
| Exact turn end and `blocked` (§10.4) | **No** | The only state a hook receives is `pane.agent_status_changed`. That is the screen-inferred state of §4, the thing §10.4 replaces. The exact signals come from the agent's own hooks |
| Record agent-to-agent exchanges (§10.7) | **No** | No input event exists, a plugin cannot add a socket method or intercept one, and a pane can always reach the real socket. Capture at both ends, through our MCP tool and the agent's `UserPromptSubmit` hook, remains the only design |
| Policy on who may prompt whom (§11.3) | **No** | A plugin runs as the server's user with the full CLI. It adds no authorisation layer, and pane-to-pane control does not go through it |
| Run the hook collector and transcript follower (§11.5) | **Worse than our own process** | `[[startup]]` commands are "one-shot initialization commands rather than supervised daemons" (`plugins.mdx:256-260`). A long-running `[[panes]]` command dies with its pane, and nothing restarts it. The build already owns a supervised process |
| Install each CLI's hooks before it starts (§10.4) | **Too late** | `pane.agent_detected` fires after the agent is running, so settings written then miss that session. The build writes them before `agent.start` |
| One Herdr server per tenant (§7) | **Works against it** | Plugins are global to the user and load in every session, so a plugin meant for one tenant runs in all of them |

### 12.4 What follows for the build

- **Ship no plugins, and install none.** The image keeps Herdr's plugin registry
  empty. The `plugin.*` socket methods stay off the HTTP surface, as §7 already
  requires. A plugin can run any command from its manifest. That makes it a
  second path to shell access, and a startup hook runs on every server start
  (`src/server/headless/bootstrap.rs:97`).
- **Nothing in §10 or §11 changes.** Identity comes from Herdr's integration,
  content from the transcript, turn boundaries from the agent's hooks, and
  exchanges from our MCP tool plus `UserPromptSubmit`.
- **The one plausible use is outside the contract.** A plugin can show a human,
  in the attached TUI, a notification or a summary pane built from the build's
  ledger. That is a convenience for an operator, not a part of the
  specification. Do not build it until somebody asks for it. 12.5 lists the
  kinds of use that suit a plugin.

### 12.5 What a plugin is good for

**A plugin suits a convenience for a person who works in Herdr's TUI.** It
reacts to Herdr's own low-volume lifecycle events, and nothing breaks if one
run is missed. Herdr says the same about plugins: they exist "so Herdr can stay
lean", as "reusable workflows that people can build, install, and share"
(`plugins.mdx:13-16`).

**Good uses:**

| Use | Mechanism | Example |
|---|---|---|
| Tell a person when an agent changes state, for example to `blocked` or `done` | `[[events]]` on `pane.agent_status_changed` | `agent-telegram-notify`. A missed alert costs little, and a person acts on it |
| Set up workspaces: build a project's standard layout, restore a saved view, open a pane for each new worktree | `[[startup]]`, `[[actions]]`, `[[events]]` on `worktree.created` | `dev-layout-bootstrap`; the manifest example at `plugins.mdx:84-86` |
| Bind workflow actions to keys, for example "send this selection to agent X" | `[[actions]]` plus `[[keys.command]]`. The action receives the workspace, focused pane, agent and selected text in `HERDR_PLUGIN_CONTEXT_JSON` (`plugins.mdx:286-289`, `:345-355`) | — |
| Small UI tools: a picker, a project board, a status summary | `[[panes]]` with `placement = "popup"` or `"overlay"` (`plugins.mdx:299-338`) | — |
| Act on a clicked URL instead of opening the browser, for example preview an issue or start an agent on it | `[[link_handlers]]` (`plugins.mdx:357-371`) | `github-link-preview` |

The three named examples are in `ogulcancelik/herdr-plugin-examples`. Herdr
calls them "examples to copy" and does not maintain them as official plugins
(`plugins.mdx:227-230`).

**Bad uses** (12.2, 12.3):

- **Anything that must be reliable.** Each event starts a new process. Above 32
  commands in flight, Herdr does not start the command.
- **High-volume data, such as pane output.** Output events are excluded from
  hooks on purpose.
- **Intercepting, enforcing or recording input.** Plugin v1 has no way to do
  this.
- **A security or tenant boundary.** A plugin runs as the server's user with the
  full CLI, and every installed plugin loads in every session.
- **A long-running service.** Startup commands run once, and nothing supervises
  them.

**For agent-service, only an operator feature fits.** It serves a person who
has attached the TUI to our container (§6a). Two examples:

- a popup that shows the build's run record for the focused pane;
- an alert when an agent becomes `blocked`.

Both read data that the build already records. Neither is part of the
specification. A plugin of this kind conflicts with 12.4's "ship no plugins", so
it needs its own decision, made when somebody asks for it.

**Would reverse this verdict:** a later Herdr release that lets a plugin
register a socket method or intercept a request, or that adds an input event.
Plugin v1 has none of these (`plugins.mdx:31-33`). Check the changelog when
Herdr is pinned to a new version.

## 13. Open questions

- Does native foreground-process detection work under gVisor, rootless Podman
  or a restricted Kubernetes PSA? Or is `HERDR_PROCESS_DETECTION=child-groups`
  needed, with its "best effort" caveat (`agents.mdx:72`)?
- Does `terminal session observe` work on native Windows? Direct attach does
  not (`persistence-remote.mdx:117`).
- How much reply text can `agent.read` recover after a long turn, for each agent
  kind? The documented fallback is to ask the agent to write a file
  (`skills/herdr/SKILL.md:202`).
- Is there a stability or deprecation policy for the JSON API beyond "ignore
  unknown fields"? None was found in `socket-api.mdx`. That is not proof that
  none exists.
- Would the consumer want the `blocked` / needs-input signal from our existing
  builds instead? That would be a feature for those builds and would not need
  Herdr.

## 14. One image, four CLIs, many worktrees, roles

**The target (user, 2026-11-16).** One agent image has Claude Code, Codex,
Gemini CLI and Pi installed. One container runs several of them at once, each in
a Herdr pane. The agents work on several worktrees at different times, in
different roles. Each agent either starts a new conversation or resumes an
existing one. **At most one agent is active on a worktree at a time.**

**Two scopes make up an agent's prompt:**

- **Project scope** comes from the worktree: the context file in the pane's
  `cwd`, plus that project's tools and skills. It is the same for every role.
- **Role scope** is the instructions for this session's role. Herdr cannot
  carry it in any other way, so it is passed at `agent.start` as a CLI flag in
  `args` or as an env var on the pane, and it is fixed for the life of the
  process (§5, the `POST /v1/sessions` row).

**One role is one session.** The same role resumes its own session while it
works on the same work item. A different role on the same worktree is a
different session in a different pane. Nothing restarts the container.

### 14.1 What the probe found

**The full report is [context-file-placement.md](./context-file-placement.md).**
It was measured 2026-11-16 on Windows against Claude Code 2.1.325, Codex CLI
0.146.0, Pi 0.85.1 and Gemini CLI 0.66.0. Each CLI was pointed at a local
capture proxy, and nothing was forwarded upstream. Every point below is
*measured* from the captured request bodies unless it is marked otherwise.

**The design holds on all four CLIs.**

- **The project file and the role prompt travel separately in all four.**
  Replacing the system prompt never drops the project file (report §2–§5).
  - **Only Pi puts the project file inside the system prompt.**
  - Claude Code, Codex and Gemini send it as a user-role message.
- **One canonical project file serves all four** (report §8). The worktree
  holds an `AGENTS.md`, and a `CLAUDE.md` whose only line is `@AGENTS.md`.
  Gemini gets `context.fileName: ["AGENTS.md"]`, which belongs in the
  user-level settings under `GEMINI_CLI_HOME` so that an agent cannot rewrite
  it. Each request carries the file exactly once.
- **The interactive TUI takes the same role flags as print mode** in each CLI
  (report §11, the `it-*` cases).

**Re-pass the role prompt on EVERY launch, including every resume** (report
§6). That is the only rule that is right for all four:

| Resume without re-passing the role | Result |
|---|---|
| Pi, Gemini | falls back to the **default** prompt |
| Claude | keeps the role, but only until the conversation is compacted |
| Codex | keeps the role, stored with the rollout |

A *different* role prompt on resume is ignored by Claude. Codex keeps the old
`developer_instructions`. That confirms one role per session.

**An edited project file is picked up on the next launch** (report §6):

- **Pi and Gemini** rebuild the request from disk, and the old copy is gone.
- **Claude and Codex** keep the old copy in history and add the new text as a
  message that replaces it.

**A session belongs to its worktree, and the adapter must enforce that itself**
(report §7). Resuming a session from a different worktree:

| CLI | Result |
|---|---|
| Claude, Codex | resumes silently, and switches to the other worktree's project file |
| Pi | stops at a `[y/N]` fork prompt, which would block a pane |
| Gemini | refuses, with exit code 42 |

**Session stores:**

| CLI | Where sessions are stored |
|---|---|
| Claude | by working directory |
| Pi | by working directory |
| Gemini | by a short name from the worktree's basename. Two worktrees with the same basename are *not probed* |
| Codex | by date |

**New constraints, added to §14.2:**

- Claude reads the real `~/.claude/CLAUDE.md` and `~/.claude/rules/` even with
  `CLAUDE_CONFIG_DIR` set.
- Interactive Claude shows a workspace-trust dialog that defaults to "No, exit".
- Gemini needs `GEMINI_CLI_TRUST_WORKSPACE=true`, or it exits with code 55.

**The launch recipes are in report §11**, one table per CLI: the `args` and
`env` for a new role session, for a resume, and what never to rely on.
**Gemini takes the role only from `GEMINI_SYSTEM_MD`**, a pane env var that
names a file. The other three accept a flag in `args`.

### 14.2 Constraints of the shared container

- **The container gets the strictest CLI's security settings.** Codex needs
  `seccomp=unconfined`, or its bubblewrap sandbox cannot run a single command
  (codex-python's references, `CX-01`). In a shared container that profile
  applies to every CLI. Accept it on purpose, or give Codex its own container.
- **Size `pids_limit` from the sum of the processes.** Codex uses about 30
  processes per session, and the process limit is reached long before the
  memory limit (`CX-19`). Add up what every CLI that may run at the same time
  needs.
- **The service enforces one agent per worktree, not Herdr.** The adapter
  keeps a lock per worktree and refuses `agent.start` on a worktree that
  already has a live pane. `agent.list` and `agent.get` report each pane's
  `cwd` and state, so the lock can be checked against what Herdr actually runs.
- **A conversation belongs to one CLI.** A Claude session cannot be resumed in
  Codex. The ledger key is **(worktree, work item, role, CLI) → the agent's
  session id**. Herdr's `agent_session` reports that id (`socket-api.mdx:708-721`,
  *read*).
- **Keep worktree paths fixed, and keep each session in its worktree.** Claude
  and Pi store sessions by working directory, and Gemini by the worktree's
  basename (§14.1). So a resume must start in the same path, and moving a
  worktree breaks resume for every conversation in it. Claude and Codex do not
  refuse a resume from another worktree, so the ledger is the only guard. Give
  worktrees unique basenames until Gemini's same-basename case is probed.
- **Make the container user's own config deliberate.** Claude reads
  `~/.claude/CLAUDE.md` and `~/.claude/rules/` even when `CLAUDE_CONFIG_DIR`
  points elsewhere, so the image's home must hold exactly what every session
  should see, or nothing.
- **Pre-accept workspace trust for every worktree.**
  - Interactive Claude shows a trust dialog that defaults to "No, exit". Set
    `hasTrustDialogAccepted` for the worktree in its config.
  - Gemini needs `GEMINI_CLI_TRUST_WORKSPACE=true`, or it exits with code 55.
  - Pi asks before forking a session across directories.

  A pane that is waiting on one of these prompts looks `blocked` to Herdr.
- **One home per CLI, shared by all its panes.** Two Claude panes in two
  worktrees share `~/.claude`, and two Codex panes share `CODEX_HOME`. Sessions
  stay apart because each has its own id. Concurrent writes to shared per-user
  files, such as Claude's `~/.claude.json`, are not verified. Soak-test two
  panes of the same CLI before relying on it.
- **Credentials live in each CLI's home, on a volume, never in a worktree.**
  Codex keeps `auth.json` beside its sessions.
- **Role prompt files live outside every worktree, mounted read-only**, for
  example `/roles/<role>.md`. A prompt file inside a worktree can be rewritten
  by the agent, and the next role session would run with the changed prompt.

### 14.3 Toolchain: in the agent's container, from a separate image

**Recommendation (proposed, 2026-11-16, not yet decided):** build the toolchain
as its own base image, and build the agent image `FROM` it. At runtime it is one
container. Use a separate *container* only for steps that need one, and reach it
through an explicit tool, never through the Docker socket.

**Why the toolchain runs in the agent's container:**

- **Every CLI runs commands locally.** Claude's Bash tool, Codex's shell,
  Gemini's `run_shell_command` and Pi's bash expect `mvn`, `sbt`, `python` and
  so on to be on `PATH` in their own filesystem. A separate container needs a
  shim on `PATH` that forwards each command.
- **That shim defeats the agents' own controls.** Codex confines a command with
  bubblewrap, and each CLI's approval and permission modes decide on the
  command they see. A shim that calls `docker exec` runs the real work outside
  the sandbox, so what is approved is not what runs.
- **The usual shim needs `/var/run/docker.sock`,** and that gives the agent
  container root on the host. [security-posture.md](./security-posture.md)
  would no longer hold.
- **The two containers must agree on everything:** the worktree path and UID,
  env, network, caches, and the tool output that comes back. Each mismatch is a
  bug.

The existing images already work this way, in a small form: they install only
what the agent itself runs (`git`, and `ripgrep` for Claude's Grep tool) in the
agent's own image.

**Why the toolchain is a separate image:**

- **It releases on its own schedule.** A JDK or Python bump does not need a CLI
  release, and a new CLI version does not rebuild the toolchain. The layers are
  `toolchain base` → `Herdr + the four CLIs`.
- **Retention.** Images are kept for the last three releases per
  implementation ([versioning.md](./versioning.md)). A heavy base shared as one
  layer costs much less than one repeated in every image.
- **Profiles, if size forces it:** `toolchain-jvm`, `toolchain-python`, and so
  on, each with the same agent layer on top. Start with one.

**Different tool versions per worktree.** Install a version manager, such as
mise, in the base. Each worktree pins its versions in a committed file
(`.mise.toml` or `.tool-versions`), and the pane gets them from its `cwd`. That
is the same way the project scope already comes from the worktree. Keep the
downloaded tools in a cache volume.

**When a separate container is justified:**

- the step needs privileges or a daemon: Docker builds, Testcontainers,
  emulators, GPUs;
- its code is untrusted enough to need stronger isolation than the agent's
  sandbox, for example the tests of an outside pull request;
- the toolchain is shared by many agent containers and is expensive to
  duplicate.

Then offer it as an explicit MCP tool, for example
`run_in_toolchain {worktree, command}`, backed by a runner that owns the Docker
access and applies its own policy. The agent asks for the step openly, and the
socket never enters the agent's container.

**Codex's relaxed seccomp profile (§14.2) also covers the toolchain** when they
share a container. That adds no new kind of risk, because the agent can already
run anything its sandbox allows. It is one more reason to decide on purpose
whether Codex shares the container.
