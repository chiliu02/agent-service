# Where an agent CLI puts the project context file

**Date:** 2026-11-16. **Method:** every result here comes from the request body
the agent actually sent, captured by a local proxy that forwards nothing. Asking
an agent about itself is not evidence, and it was not used. Each claim is
labelled:

- **wire**: seen in a captured request body.
- **source**: read in the installed package, with file and line given.
- **help**: taken from the CLI's own `--help` text.

The case names in brackets (`cc-r2`, `xc-pi-B`, ...) are the probe runs, listed
in §9.

**Versions probed (Windows 11, all installed on this machine):**

| Agent | CLI | SDK |
|---|---|---|
| Claude Code | `claude` 2.1.325 | `claude-agent-sdk` 0.2.175 (Python, in `impl/claude-python`'s venv), which runs its **bundled** CLI 2.1.314 |
| Codex | `codex-cli` 0.146.0 | `openai-codex` 0.163.0 (Python, in `impl/codex-python`'s venv), which runs its **bundled** `codex-cli` 0.163.0 |
| Pi | `@earendil-works/pi-coding-agent` 0.85.1 (global npm) | the same package's `createAgentSession` export (TypeScript), 0.85.1 |
| Gemini CLI | `@google/gemini-cli` 0.66.0, installed into a scratch prefix (the version `impl/gemini-python/Dockerfile` pins) | **none exists**: this repository spawns the CLI |

**Order of priority.** The CLI path comes first (§1 to §7), because a
Herdr-hosted build ([herdr-tui.md](./herdr-tui.md) §5 and §11.5 to §11.6) runs
each agent as its interactive CLI in a pane. The SDK results are in §8. They
were run after the CLI cases and are not needed for the Herdr recipes.

---

## 0. Summary

| Agent | Files it reads (project dir) | Default prompt: where the project file lands | Custom system prompt: is the project file still sent, and where? |
|---|---|---|---|
| **Claude Code** CLI | `CLAUDE.md` only. Not `AGENTS.md`, not `GEMINI.md`. **wire** | **Not** in `system`. In `messages[0].content[0].text`, the first user turn, inside `<system-reminder>`, headed `Contents of <path> (project instructions, checked into the codebase):`. **wire** | **Yes, unchanged.** `--system-prompt-file` replaces `system[2]` only; the file stays in `messages[0]` `<system-reminder>`. **wire** (`cc-custom`, `cc-append`) |
| **Codex** CLI 0.146.0 | `AGENTS.md` only. Not `CLAUDE.md`, not `GEMINI.md`. **wire** | **Not** in `instructions`. In `input[1]` (`role: user`), `content[0]`, headed `# AGENTS.md instructions for <cwd>` and wrapped in `<INSTRUCTIONS>…</INSTRUCTIONS>`. **wire** | **Yes, unchanged.** `model_instructions_file` replaces `instructions`; `developer_instructions` adds `input[0].content[0]` (`role: developer`). The file stays in `input[1]`. **wire** (`cx-custom`, `cx-dev`) |
| **Pi** 0.85.1 | **One** file per directory, the first that exists of `AGENTS.override.md`, `AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD`. So with both present it reads `AGENTS.md` and not `CLAUDE.md`. Never `GEMINI.md`. **source** + **wire** | **In the system prompt**: `system[0].text`, after the built-in prompt, in `<project_context>` with one `<project_instructions path="…">` per file. **wire** | **Yes, still in `system[0]`**, appended after the custom text in the same `<project_context>` block. **wire** (`pi-custom`, `pi-append`) |
| **Gemini CLI** 0.66.0 | `GEMINI.md` by default, or the names in `context.fileName`. **wire** + **source** | **Project file: NOT in `systemInstruction`.** It is in `contents[0].parts[0].text` (the first user turn), inside `<session_context>…<loaded_context><project_context>`. The **global** `~/.gemini/GEMINI.md` **is** in `systemInstruction`. **wire** | **Yes, unchanged.** `GEMINI_SYSTEM_MD` replaces the base of `systemInstruction`. The global file is still appended there, and the project file stays in `contents[0]`. **wire** (`gm-custom`) |

**The interactive TUI builds the same request as print mode** in all four,
for both placement and the custom system prompt. Each takes the same flag or
env interactively: **wire** (`it-cc`, `it-cx`, `it-pi`, `it-gm`).

**Against the repository's earlier notes.** The note that Gemini's
`renderFinalShell` "appends context files in both branches" is true of the
function (`renderFinalShell`, `chunk-HJ5KJXNZ.js:337999`). But in 0.66.0 only
**global** memory reaches it. **Project** memory is routed to the first user
message (§4). The note's reading of Pi is confirmed on the wire.

---

## 1. Method, and how to rerun it

1. **Capture proxy** (`proxy.py`, below): a stdlib `ThreadingHTTPServer` on a
   high random port (47391 to 47433). It saves every request as `NNN.json`
   (method, path, headers with auth values redacted, JSON body). In `error`
   mode it answers 400. In `ok` mode it answers a minimal **valid** completion
   in the provider's own shape (Anthropic Messages SSE, OpenAI Responses SSE,
   Gemini `streamGenerateContent` SSE), so the CLI saves a session that a later
   run can resume. **Nothing is forwarded, and no real key is used.**
2. **Markers.** The probe project holds `CLAUDE.md`, `AGENTS.md` and
   `GEMINI.md`, each with its own marker (`MARKER-CLAUDEMD-7f3a`,
   `MARKER-AGENTSMD-7f3a`, `MARKER-GEMINIMD-7f3a`). Each agent's temp home holds a
   global file with its own marker (`MARKER-GLOBALCLAUDE-a1b2`,
   `MARKER-GLOBALAGENTS-c3d4`, `MARKER-GLOBALPI-e7f8`, `MARKER-GLOBALGEMINI-9a0b`).
   Custom prompts carry `MARKER-CUSTOMSYS-91c2`, `MARKER-ROLEA-1111` and
   `MARKER-ROLEB-2222`. The resume cases rewrite every `7f3a` project marker to
   `v2b9` between turns.
3. **Finder** (`find.py`): walks each captured JSON body and prints the JSON path
   and surrounding text of every marker. **A marker missing from that output is
   missing from the whole body**, because the walk covers every string, not a
   filtered grep.
4. **Isolation.** Each run used a temp home: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
   `PI_CODING_AGENT_DIR`, `GEMINI_CLI_HOME`. No user config was written.
   **Exception, wire-observed:** Claude Code still **read** the real
   `~/.claude/CLAUDE.md` and `~/.claude/rules/*.md` with `CLAUDE_CONFIG_DIR`
   set (§2). Those reads went only to the proxy.
5. **Interactive runs** used a real ConPTY: `node-pty` from the Gemini install,
   through `pty_drive.cjs`, which presses Enter every 4 s until the proxy holds
   the model call.
6. **Codex and the Windows sandbox.** The Codex runs here used the default
   `read-only` sandbox. On this machine each Codex start raised a modal
   *"Windows cannot find 'codex-windows-sandbox-setup.exe'"*, because the
   install has only `codex.exe` and `codex-code-mode-host.exe`. The interactive
   Codex run blocked on it and was killed by PID after its request had already
   been captured. All Codex probing was done before the dialog was reported, so
   **no run used `-s danger-full-access`**. A rerun should pass it: no tool call
   is ever returned, so no command runs. The sandbox mode changes only the text of
   the `<permissions instructions>` developer block. It does not change which
   message carries AGENTS.md. That last point was seen across `read-only` runs
   with different flags, not by toggling the sandbox.

<details><summary><code>proxy.py</code></summary>

```python
"""Capture proxy: records every request and forwards NOTHING upstream.

usage: python proxy.py <port> <capture-dir> [error|ok]
  error (default): reply 400 JSON, so the CLI gives up after one call.
  ok:              reply a minimal VALID completion ("ok") in the provider's own
                   shape, streamed when asked, so the CLI saves a session.
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, OUT = int(sys.argv[1]), sys.argv[2]
MODE = sys.argv[3] if len(sys.argv) > 3 else "error"
os.makedirs(OUT, exist_ok=True)
LOCK, N = threading.Lock(), [0]
SECRET = {"authorization", "x-api-key", "x-goog-api-key", "cookie", "api-key"}

def sse(events, named=True):
    return "".join((f"event: {n}\n" if named else "") + f"data: {json.dumps(d)}\n\n"
                   for n, d in events).encode()

def anthropic(body):
    msg = {"id": "msg_probe", "type": "message", "role": "assistant", "model": body.get("model", "x"),
           "content": [], "stop_reason": None, "stop_sequence": None,
           "usage": {"input_tokens": 1, "output_tokens": 1}}
    if not body.get("stream"):
        msg.update(content=[{"type": "text", "text": "ok"}], stop_reason="end_turn")
        return "application/json", json.dumps(msg).encode()
    return "text/event-stream", sse([
        ("message_start", {"type": "message_start", "message": msg}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"})])

def responses(body):
    rid, iid = f"resp_{time.time_ns()}", f"msg_{time.time_ns()}"
    item = {"type": "message", "id": iid, "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}]}
    usage = {"input_tokens": 1, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 1,
             "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 2}
    resp = {"id": rid, "object": "response", "status": "completed", "model": body.get("model", "x"),
            "output": [item], "usage": usage}
    return "text/event-stream", sse([
        ("response.created", {"type": "response.created", "response": {**resp, "status": "in_progress", "output": []}}),
        ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": iid, "output_index": 0, "content_index": 0, "delta": "ok"}),
        ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
        ("response.completed", {"type": "response.completed", "response": resp})])

def gemini(path):
    if ":countTokens" in path:
        return "application/json", b'{"totalTokens": 1}'
    chunk = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP", "index": 0}],
             "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
             "modelVersion": "probe"}
    if ":streamGenerateContent" in path:
        return "text/event-stream", sse([("", chunk)], named=False)
    return "application/json", json.dumps(chunk).encode()

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _cap(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        hdrs = {k: ("<redacted>" if k.lower() in SECRET else v) for k, v in self.headers.items()}
        with LOCK:
            N[0] += 1
            n = N[0]
        with open(os.path.join(OUT, f"{n:03d}.json"), "w", encoding="utf-8") as f:
            json.dump({"method": self.command, "path": self.path, "headers": hdrs, "body": body},
                      f, indent=1, ensure_ascii=False)
        status, ctype = 400, "application/json"
        out = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                          "message": "ctxprobe: captured, not forwarded", "code": 400,
                          "status": "INVALID_ARGUMENT"}}).encode()
        if MODE == "ok" and isinstance(body, dict):
            p = self.path
            if "count_tokens" in p:
                status, out = 200, b'{"input_tokens": 1}'
            elif p.startswith("/v1/messages"):
                status, (ctype, out) = 200, anthropic(body)
            elif "/responses" in p:
                status, (ctype, out) = 200, responses(body)
            elif "generatecontent" in p.lower() or ":countTokens" in p:
                status, (ctype, out) = 200, gemini(p)
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _cap
    def log_message(self, *a):
        pass

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
```

</details>

<details><summary><code>find.py</code> and the run harness</summary>

```python
"""usage: python find.py <capture-dir>  -- JSON path + context of every marker."""
import json, os, re, sys
MK = re.compile(r"MARKER-[A-Z]+-[0-9a-z]{4}")
def walk(o, p):
    if isinstance(o, dict):
        for k, v in o.items(): yield from walk(v, f"{p}.{k}" if p else k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{p}[{i}]")
    elif isinstance(o, str):
        yield p, o
d = sys.argv[1]
for fn in sorted(os.listdir(d)):
    if not fn.endswith(".json"): continue
    r = json.load(open(os.path.join(d, fn), encoding="utf-8"))
    print(f"== {fn} {r['method']} {r['path']}")
    for p, s in walk(r["body"], ""):
        for m in MK.finditer(s):
            a = max(0, m.start() - 160)
            print(f"   {m.group()} @ {p}\n      ...{s[a:m.end() + 60]!r}...")
```

```bash
# run.sh <case> <port> <command...>  -- proxy up, run once in the probe project, proxy down by PID
S="$(cd "$(dirname "$0")" && pwd)"; CASE=$1; PORT=$2; shift 2
mkdir -p "$S/caps/$CASE"
python -I "$S/proxy.py" "$PORT" "$S/caps/$CASE" "${MODE:-error}" & PPID_=$!
sleep 1; cd "${PROJ:-$S/proj}"
timeout 120 "$@" > "$S/caps/$CASE/_stdout.txt" 2> "$S/caps/$CASE/_stderr.txt" < /dev/null
echo "exit=$?" >> "$S/caps/$CASE/_stdout.txt"; kill $PPID_
```

</details>

**Run commands** (Git Bash; `$S` is the scratch dir, and `$(cygpath -w …)`
turns a path into a Windows path):

```bash
# Claude Code
export CLAUDE_CONFIG_DIR=$S/homes/claude ANTHROPIC_BASE_URL=http://127.0.0.1:47391 \
       ANTHROPIC_API_KEY=sk-ant-dummy CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
run.sh cc-default 47391 claude -p hi --max-turns 1
run.sh cc-custom  47391 claude -p hi --max-turns 1 --system-prompt-file "$(cygpath -w $S/custom-system.md)"

# Codex: $CODEX_HOME/config.toml holds the probe provider
#   model_provider="probe"
#   [model_providers.probe] base_url="http://127.0.0.1:47392/v1" wire_api="responses" env_key="PROBE_KEY"
#   request_max_retries=0  stream_max_retries=0
export CODEX_HOME=$(cygpath -w $S/homes/codex) PROBE_KEY=dummy
run.sh cx-default 47392 codex exec --skip-git-repo-check hi
run.sh cx-custom  47392 codex exec --skip-git-repo-check -c 'model_instructions_file="C:/…/custom-system.md"' hi
run.sh cx-dev     47392 codex exec --skip-git-repo-check -c 'developer_instructions="…"' hi

# Pi: $PI_CODING_AGENT_DIR/models.json = {"providers":{"anthropic":{"baseUrl":"http://127.0.0.1:47393"}}}
export PI_CODING_AGENT_DIR=$(cygpath -w $S/homes/pi) ANTHROPIC_API_KEY=sk-ant-dummy
run.sh pi-default 47393 pi --mode json --no-session --no-skills --no-extensions \
       --provider anthropic --model claude-sonnet-4-5 -p hi
run.sh pi-custom  47393 pi … --system-prompt "$(cygpath -w $S/custom-system.md)" -p hi

# Gemini: $GEMINI_CLI_HOME/.gemini/settings.json = {"security":{"auth":{"selectedType":"gemini-api-key"}}}
export GEMINI_CLI_HOME=$(cygpath -w $S/homes/gemini) GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:47394 \
       GEMINI_API_KEY=dummy GEMINI_CLI_TRUST_WORKSPACE=true
run.sh gm-default 47394 gemini -p hi -o json
GEMINI_SYSTEM_MD=$(cygpath -w $S/custom-system.md) run.sh gm-custom 47394 gemini -p hi -o json
```

The resume cases run the same commands with `MODE=ok`, in this order: turn 1
with role A, then the project files are edited, then (b) resume with no role
prompt, (a) resume re-passing A, and resume with B.

---

## 2. Claude Code CLI 2.1.325

**Placement (wire, `cc-default`).** `system` has three blocks: `system[0]` is the
billing header, `system[1]` is the one-line identity, and `system[2]` is the
6008-character built-in prompt. **None of them holds a CLAUDE.md.** Every
instruction file is in the first user turn:

```
messages[0].content[0].text  (len 9288)
<system-reminder>
Codebase and user instructions are shown below. Be sure to adhere to these instructions. IMPORTANT: These instructions OVERRIDE any default behavior …
Contents of …\ctxprobe\proj\CLAUDE.md (project instructions, checked into the codebase):
# Project notes
MARKER-CLAUDEMD-7f3a: this line exists only in CLAUDE.md.
</system-reminder>
messages[0].content[1].text  "hi"
messages[1]  role: "system"   "# Environment\nYou have been invoked in the following environment: …"
```

So the earlier self-report was right: **CLAUDE.md arrives as a
`<system-reminder>` in the first user message.** It is now confirmed on the
wire. The environment block is a **`role: "system"` entry inside `messages[]`**,
after the user turn. That is not the top-level `system` field.

**Files, in order (wire):** `$CLAUDE_CONFIG_DIR/CLAUDE.md`, then the real
`~/.claude/CLAUDE.md`, then `~/.claude/rules/*.md`, then the project
`CLAUDE.md`. **`CLAUDE_CONFIG_DIR` does not stop the real `~/.claude` from
being read.** In an image, the container user's `~/.claude` must be empty or
deliberate. `AGENTS.md` and `GEMINI.md` were not read.

**Custom system prompt (wire).** `--system-prompt-file` replaces `system[2]`
with the file's text, and `system[1]` becomes the SDK identity line.
`--append-system-prompt-file` keeps the built-in prompt and appends to the end
of `system[2]`. In both cases CLAUDE.md is still in `messages[0]`, unchanged.

**Interactive (wire, `it-cc`).** The TUI accepts `--system-prompt-file`, and its
request has the same shape (`system[2]` = role A, CLAUDE.md in `messages[0]`).
**One difference that matters:** the interactive TUI shows a workspace-trust
dialog whose default is **"No, exit"**. Enter quits it, and no request is made.
`-p` skips the dialog. The probe pre-accepted trust with
`projects["<path>"].hasTrustDialogAccepted: true` in
`$CLAUDE_CONFIG_DIR/.claude.json`, and set `apiKeyHelper` in `settings.json` so
the TUI did not ask whether to use a custom key.

---

## 3. Codex CLI 0.146.0

**Placement (wire, `cx-default`).** `instructions` is the 21335-character
built-in prompt, and **it holds no AGENTS.md.** The file is a **user** message:

```
input[0]  role: developer   <permissions instructions> …, <skills_instructions> …
input[1]  role: user  content[0].text
  # AGENTS.md instructions for …\ctxprobe\proj
  <INSTRUCTIONS>
  MARKER-GLOBALAGENTS-c3d4: user-level ~/.codex/AGENTS.md.
  --- project-doc ---
  # Project notes
  MARKER-AGENTSMD-7f3a: this line exists only in AGENTS.md.
  </INSTRUCTIONS>
input[1]  role: user  content[1].text   <environment_context> <cwd>…</cwd> …
input[2]  role: user  "hi"
```

The global `$CODEX_HOME/AGENTS.md` and the project `AGENTS.md` are **joined
into one block**, with `--- project-doc ---` between them. `CLAUDE.md` and
`GEMINI.md` were not read.

**Custom system prompt (wire).** `-c model_instructions_file="<abs>"` replaces
`instructions` entirely (49 characters, `cx-custom`).
`-c developer_instructions="…"` adds `input[0].content[0]`, a developer message
placed before the permissions text (`cx-dev`). **In both, AGENTS.md stays in
`input[1]` (user).**

**Interactive (wire, `it-cx`).** `codex -c model_instructions_file=… "hi"` gave
the same placement (`instructions` = role A, AGENTS.md in `input[1]`).

**A version change to watch (wire, `cx163-default`, `cx163-exec`).** The
bundled `codex-cli` **0.163.0** sends `"instructions": ""`. It moves the
built-in prompt, or the `model_instructions_file` text, into
**`input[0]`, `role: developer`**. AGENTS.md is still a user message. So **from
0.163, no Codex request carries anything in the system-level field**, and a
role prompt is a developer message. Probed through a custom provider. It is not
known whether the OpenAI provider behaves the same.

---

## 4. Pi 0.85.1

**Placement (wire, `pi-default`).** Everything is in `system[0].text`, and the
messages are only the user turns:

```
system[0].text (len 3319)
  You are an expert coding assistant operating inside pi, …
  …
  <project_context>
  Project-specific instructions and guidelines:
  <project_instructions path="…\homes\pi\AGENTS.md">
  MARKER-GLOBALPI-e7f8: agent-dir AGENTS.md.
  </project_instructions>
  <project_instructions path="…\ctxprobe\proj\AGENTS.md">
  # Project notes
  MARKER-AGENTSMD-7f3a: this line exists only in AGENTS.md.
  </project_instructions>
  </project_context>
  Current working directory: C:/…/ctxprobe/proj
messages[0]  role: user  "hi"
```

**Custom prompt (wire, `pi-custom`).** `--system-prompt <file>` makes the custom
text the head of `system[0]`, and the same `<project_context>` block is still
appended after it. `--append-system-prompt` adds its text before the block
(`pi-append`). This matches
`dist/core/system-prompt.js:15-27` (custom branch) and `:103-110` (default
branch). **source**

**Files (source, `dist/core/resource-loader.js:32-50` and `:82-108`).** In each
directory Pi takes the **first** of `AGENTS.override.md`, `AGENTS.md`,
`AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD`. It does this for the agent dir (global),
then for **every ancestor of cwd up to the filesystem root**. The walk does not
stop at a git root. So `AGENTS.md` shadows `CLAUDE.md` in the same directory
(wire: `pi-default` has no CLAUDE marker). A directory with only `CLAUDE.md` is
read (wire: `one-pi-claudeonly`).

**Trust (source, `resource-loader.js:256-262` and `:370-377`).** Context files
are not trust-gated. They are loaded unless `--no-context-files` (or
`noContextFiles`) is set. Project trust governs extensions and settings only.

**Interactive (wire, `it-pi`).** `pi --system-prompt <file> "hi"` gave the same
request.

---

## 5. Gemini CLI 0.66.0

**Pointing it at the proxy (source + wire).** `GOOGLE_GEMINI_BASE_URL` overrides
the endpoint (`chunk-HJ5KJXNZ.js:315036`). It also makes `getAuthTypeFromEnv`
return `gateway` (`:314877`), which the CLI's own validator rejects with exit 41.
So the settings file must name `security.auth.selectedType: "gemini-api-key"`.
The repository already knew this. An untrusted folder refuses the run with exit
55, and `GEMINI_CLI_TRUST_WORKSPACE=true` lets it proceed (wire:
`gm-untrusted`). **The trust gate is all-or-nothing: no request is made at all,
so there is no context-file-only gate.**

**Placement (wire, `gm-default`).** The main call is
`…/gemini-3.1-pro-preview:streamGenerateContent?alt=sse`. A
`gemini-3.5-flash-lite:generateContent` routing call comes first, and it already
carries the same `contents[0]`.

```
systemInstruction.parts[0].text (len 32035)
  You are Gemini CLI, an autonomous CLI agent …
  … # Contextual Instructions (GEMINI.md) …
  <loaded_context>
  --- Context from: …/homes/gemini/.gemini/GEMINI.md ---
  MARKER-GLOBALGEMINI-9a0b: user-level ~/.gemini/GEMINI.md.
  --- End of Context from: … ---
  </loaded_context>
contents[0]  role: user  parts[0].text
  <session_context>
  This is the Gemini CLI. We are setting up the context for our chat. …
  <loaded_context>
  <project_context>
  --- Context from: …/ctxprobe/proj/GEMINI.md ---
  MARKER-GEMINIMD-7f3a: this line exists only in GEMINI.md.
  --- End of Context from: …/proj/GEMINI.md ---
  </project_context>
  </loaded_context>
  </session_context>
contents[0]  parts[1].text  "hi"
```

**The split is deliberate (source, `chunk-HJ5KJXNZ.js:389005-389045`).**
`getSystemInstructionMemory()` returns *"Tier 1 memory … Global memory and user
project memory go in the system instruction; extension and project memory are
placed in the first user message instead, per the tiered context model"*.
`getSessionMemory()` builds the `<project_context>` block that
`getEnvironmentContext` puts into `<session_context>` (`:339783-339795`).

**Custom prompt (wire, `gm-custom`).** `GEMINI_SYSTEM_MD=<abs path>` replaces
the base of `systemInstruction` (1357 characters, starting with the custom
text). The global GEMINI.md is still appended there, and the project file is
still in `contents[0]`. **Source, `:339511-339556`:** the value `true` or `1`
means `.gemini/system.md` resolved **against the cwd**, which is inside the
worktree. Any other value is a path. A missing file throws. The file is read with
`readFileSync` **every time the prompt is built**.

**Files (wire + source).** It reads `GEMINI.md` only (`AGENTS.md` and
`CLAUDE.md` absent from `gm-default`). The names come from
`settings.context.fileName`, a string or an array (`gemini-22EOGL6O.js:8313`).

**Interactive (wire, `it-gm`).** `gemini -i "hi"` with `GEMINI_SYSTEM_MD` set
gave the same request.

---

## 6. Resuming a role's session

The model is one session per role, resumed while the role is still on the same
work item. Each agent was asked three things: (a) is the role prompt in the
system field when it is **re-supplied** on resume; (b) does the role **persist**
when it is **not** re-supplied; (c) is a project file edited between turns sent
again, or is a cached copy used. All rows are **wire** (proxy in `ok` mode, so
each turn completed and was saved). "History" means earlier turns are replayed
in the messages.

| | (a) A re-supplied on resume | **(b) no prompt on resume** | (c) project file edited between turns | Resume with a *different* prompt B | History replayed |
|---|---|---|---|---|---|
| **Claude** `--resume <id>` | A in `system[2]` (`cc-r3`) | **A persists** (`cc-r2`, `cc-sw3`), from the system-prompt snapshot | The original copy stays in `messages[0]` (it is history). A **new** `<system-reminder>` *"Instruction files were re-read when this session started; these differ from their earlier copies — each replaces its earlier copy"* carrying the new text is added to the next user turn (`cc-r2`, `cc-sw2`) | **B is ignored, A is sent** (`cc-r4`, `cc-sw2`, `cc-sw4` with `--continue`) | yes |
| Claude with `--system-prompt-snapshot off` | A (`ccs-1`) | **falls back to the DEFAULT prompt** (`ccs-2`) | as above | B is sent (`ccs-3`) | yes |
| **Codex** `exec resume <id>` | A in `instructions` (`cx-r3`) | **A persists** in `instructions` (`cx-r2`), stored with the rollout | The old block stays at `input[1]`. A **new user message** *"These AGENTS.md instructions replace all previously provided AGENTS.md instructions."* with the new text is added before the turn (`cx-r2`, `cx-sw2`) | `instructions` **becomes B** (`cx-r4`, `cx-sw2`). But `developer_instructions` **stays A**: it is history, and the new value is not added (`cx-sw2`, `cx-r4`) | yes |
| **Pi** `--continue` / `--session` | A in `system[0]` (`pi-r3`) | **falls back to the DEFAULT prompt** (`pi-r2`) | The **new** file is in `system[0]` and the old copy appears nowhere: the system prompt is rebuilt each launch (`pi-r2`) | B (`pi-r4`, `pi-sw2`) | yes |
| **Gemini** `--resume latest` / `<id>` | A in `systemInstruction` (`gm-r3`) | **falls back to the DEFAULT prompt** (`gm-r2`) | The **new** file is in `contents[0]`, and the old copy appears nowhere: the first `<session_context>` message is rebuilt (`gm-r2`) | B (`gm-r4`) | yes |

**Claude's behaviour is documented (help).** `--system-prompt-snapshot <on|off>`:
*"on (the default …): the prompt is rendered on the conversation's first request
— a --system-prompt or --append-system-prompt included — sent, and recorded;
every later request and resume sends the record as-is, even when a later launch
passes different text, until the conversation is compacted."* So the persistence
in (b) **ends at the first compaction**, and from then on whatever the launch
passes is used.

---

## 7. Sessions and the working directory

Session started in worktree A, then resumed **by id** from worktree B (each has
its own `AGENTS.md` with `MARKER-WTA-aaa1` or `MARKER-WTB-bbb2`). **wire**.

| Agent | Store (in the temp home) | Resume by id from B |
|---|---|---|
| **Claude** | `$CLAUDE_CONFIG_DIR/projects/<cwd-slug>/<session-id>.jsonl`, e.g. `C--…-ctxprobe-wtA/` | **Resumes** (`xc-cc-B`). The transcript stays under A's slug. The request replays A's file, then adds a *"re-read … replaces its earlier copy"* reminder with **B's** file and a `role: system` *"# Environment update — Primary working directory: …\wtB (was …\wtA)"* |
| **Codex** | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`, **by date, not by cwd** | **Resumes** (`xc-cx-B`). A's block stays in history. A new user message *"These AGENTS.md instructions replace all previously provided …"* carries **B's** file, with a new `<environment_context><cwd>…\wtB</cwd>` |
| **Pi** | `$PI_CODING_AGENT_DIR/sessions/--<cwd-slug>--/` (or `--session-dir`) | **Asks** *"Session found in different project: …\wtA. Fork this session into current directory? [y/N]"*. With stdin closed it answers N, makes no request, and exits 0 (`xc-pi-B`). In a pane this is a **blocking prompt** |
| **Gemini** | `$GEMINI_CLI_HOME/.gemini/tmp/<short-name>/chats/session-*.jsonl`. `.gemini/projects.json` maps each absolute path to a short name, which here is the lower-cased basename (`wta`, `wtb`) | **Refused**: *"Error resuming session: No previous sessions found for this project."*, exit 42 (`xc-gm-B`) |

Claude and Codex resume across worktrees without warning, and they move the
session onto B's project file. **The adapter must enforce "a role's session
belongs to its worktree" itself.** Gemini's short name comes from the basename.
Two worktrees with the **same basename** in different parents were not probed,
and that collision needs a check before relying on it.

---

## 8. One project file for all four

The project `proj1` has `AGENTS.md` (`MARKER-CANON-1a2b`), a `CLAUDE.md` whose
only line is `@AGENTS.md`, and `.gemini/settings.json` with
`{"context":{"fileName":["AGENTS.md"]}}`. **wire**, and each request carries the
marker **exactly once**:

| Agent | Result |
|---|---|
| Claude (`one-cc`) | The import works. `messages[0]` lists `CLAUDE.md` (`@AGENTS.md`) and then a separate `Contents of …\proj1\AGENTS.md (project instructions, checked into the codebase):` entry. |
| Codex (`one-cx`) | Reads `AGENTS.md` natively, in `input[1]`. |
| Pi (`one-pi`) | Reads `AGENTS.md` and **not** `CLAUDE.md` (first match wins), so there is no duplicate. With only `CLAUDE.md` present, it reads that (`one-pi-claudeonly`). |
| Gemini (`one-gm`) | `context.fileName: ["AGENTS.md"]` makes it read `AGENTS.md` into `contents[0]` `<project_context>`. It read no `GEMINI.md`. |

**So one `AGENTS.md` plus a one-line `CLAUDE.md` serves all four.** Gemini's
setting was probed in the **project** `.gemini/settings.json`, which is inside
the worktree. The same key in the user-level settings under `GEMINI_CLI_HOME`
is the place an image would put it, so agents cannot rewrite it. That placement
is source-read (same `settings.context`), not probed.

---

## 9. SDKs (after the CLI; for reference)

All **wire**, through the same proxy.

**Claude Agent SDK 0.2.175**, which runs its bundled CLI 2.1.314
(`subprocess_cli.py:258` prefers `_bundled/claude.exe`). Placement is the same
as the CLI, with CLAUDE.md in `messages[0]` `<system-reminder>`:

| Case | `system` | CLAUDE.md (project) | `~/.claude` CLAUDE.md (user) |
|---|---|---|---|
| `system_prompt` unset (`sdk-cc-noprompt`) | only the identity line: **no built-in prompt**, because unset is sent as `--system-prompt ""` (`subprocess_cli.py:577`) | yes | yes |
| `system_prompt="…"` (`sdk-cc-custom`) | `system[2]` = the string | yes | yes |
| preset `claude_code` + `append` (`sdk-cc-preset`) | built-in + appended text in `system[2]` | yes | yes |
| `setting_sources=[]` (`sdk-cc-noprompt+empty`) | | **no** | **no** |
| `setting_sources=["project"]` | | yes | no |
| `setting_sources=["user"]` | | no | yes |

**`setting_sources=None` loads everything in 0.2.175** (docstring at
`types.py:2653-2663`, *"When None, all sources are loaded … Must include
"project" to load CLAUDE.md files"*). The historical "the SDK loads no
CLAUDE.md by default" **does not hold** for this version.
**Resume** (`sdk-cc-r1..r3`): `resume=<id>` with `system_prompt` omitted keeps
role A, from the snapshot, as the CLI does.

**Codex SDK `openai-codex` 0.163.0**, which runs bundled `codex-cli` 0.163.0.
`instructions` is `""`. `base_instructions` becomes `input[0]` (developer),
`developer_instructions` becomes `input[1]` (developer), and AGENTS.md is
`input[2]` (user) (`sdk-cx-default`, `-base`, `-dev`). **Resume**
(`sdk-cx-r2`): `thread_resume(id)` with no instructions keeps both A messages,
which are history.

**Pi SDK** (`createAgentSession` + `DefaultResourceLoader({systemPrompt})`, 0.85.1):
the same as the Pi CLI. Project and global files are in `system[0]`, under the
custom prompt as well (`sdk-pi-default`, `sdk-pi-r1`). `continueRecent` with no
`systemPrompt` **falls back to the default** (`sdk-pi-r2`).

**Gemini: no SDK.** Only the CLI was probed.

---

## 10. What this means

For a design where **project scope comes from the ambient file** and **role
scope from a replaced or appended system prompt**:

- **Only Pi puts the project file inside the system prompt**, in every mode,
  with the role prompt directly above it. It is wire-observed for the default
  prompt, a custom one and an appended one.
- **Claude Code, Codex and Gemini never put the project file in the system
  field.** They send it as a user-role message: a `<system-reminder>` in the
  first user turn (Claude), a `# AGENTS.md instructions` user message (Codex),
  or `<session_context>` in the first user turn (Gemini). Gemini puts only the
  **global** file in `systemInstruction`.
- **Replacing the system prompt never drops the project file** in any of the
  four. The two scopes are independent channels everywhere, so the design works
  as intended.
- **The role does not reliably survive a resume.** Pi and Gemini always rebuild
  it from the launch (b → default). Claude and Codex persist it, but Claude only
  until compaction, and Codex 0.163 has moved it to a developer message.
  **Re-passing the role on every launch is the only rule that is right for all
  four.**

---

## 11. Launch recipes for a Herdr adapter

A Herdr session is `pane.split` / `workspace.create` (`cwd`, `env`) followed by
`agent.start {kind, args}` ([herdr-tui.md](./herdr-tui.md) §5, row
`POST /v1/sessions`). So the role is **fixed at start**, and a role change is a
new pane. Paths below are illustrative. **Role files belong in a read-only
location outside every worktree** (here `/etc/agent-roles/`). A prompt file
inside the worktree can be rewritten by the agent, and Gemini re-reads its file
on every prompt build (§5), so a rewrite takes effect **mid-session**.

### Claude Code

| | `args` | `env` / `cwd` | Proof |
|---|---|---|---|
| **New role session** | `--session-id <uuid> --system-prompt-file /etc/agent-roles/<role>.md` (or `--system-prompt "<text>"`: inline, no file needed; or `--append-system-prompt-file` to keep the built-in prompt) | `cwd=<worktree>`, `ANTHROPIC_BASE_URL`, credential, `CLAUDE_CONFIG_DIR=<per-container dir>` with `projects["<worktree>"].hasTrustDialogAccepted: true` in its `.claude.json` | wire `it-cc`, `cc-custom`, `cc-append`; trust dialog default "No, exit" wire `it-cc` (first run) |
| **Resume, same work item** | `--resume <uuid> --system-prompt-file /etc/agent-roles/<role>.md`, **always re-passed** | same pane `cwd` as the session's | wire `cc-r3`; persistence ends at compaction help `--system-prompt-snapshot`; without the snapshot (b) is default wire `ccs-2` |
| **Never rely on** | a *different* prompt on resume (ignored: wire `cc-r4`, `cc-sw4`); `--continue` picking the right session (it takes the cwd's most recent); resume being refused from another worktree (it is not: wire `xc-cc-B`); `CLAUDE_CONFIG_DIR` hiding `~/.claude/CLAUDE.md` (it does not: wire `cc-default`) | | |

A pane `env` is enough only with `--system-prompt "<text>"`. With
`--system-prompt-file` the file must exist, outside the worktree.

### Codex

| | `args` | `env` / `cwd` | Proof |
|---|---|---|---|
| **New role session** | `-c model_instructions_file="/etc/agent-roles/<role>.md"` (optionally `-c developer_instructions="…"`) | `cwd=<worktree>`, `CODEX_HOME=<per-container dir>` with the provider in `config.toml`, the provider key | wire `it-cx`, `cx-custom`, `cx-dev` |
| **Resume, same work item** | `codex resume <id> -c model_instructions_file="/etc/agent-roles/<role>.md"`, **re-passed** (harmless; it is what persisted) | same `cwd` | wire `cx-r2` (persists), `cx-r3`; `codex resume` is the interactive form of `exec resume` (help) |
| **Never rely on** | changing `developer_instructions` on resume (the old one stays: wire `cx-sw2`, `cx-r4`); the role being in `instructions` (empty from 0.163: wire `cx163-exec`); resume refused from another worktree (it is not: wire `xc-cx-B`) | | |

`model_instructions_file` is a **path**, so the file must exist, outside the
worktree. `developer_instructions` can be inline in `args`.

### Pi

| | `args` | `env` / `cwd` | Proof |
|---|---|---|---|
| **New role session** | `--session-id <uuid> --system-prompt /etc/agent-roles/<role>.md` (a path, or inline text: the value is read as a file when one exists) | `cwd=<worktree>`, `PI_CODING_AGENT_DIR=<per-container dir>` with `models.json`, credential | wire `it-pi`, `pi-custom`, `pi-r1`; path-or-text resolution source `resource-loader.js` `resolvePromptInput` |
| **Resume, same work item** | `--session <uuid> --system-prompt /etc/agent-roles/<role>.md`, **always re-passed** | same `cwd` | (b) falls back to default wire `pi-r2`; re-passed wire `pi-r3` |
| **Never rely on** | the session remembering its role (wire `pi-r2`); a cross-worktree `--session` proceeding (it blocks on a `[y/N]` fork prompt: wire `xc-pi-B`) | | |

A pane `env` is not a carrier for Pi's prompt. Inline text in `args` needs no
file.

### Gemini CLI

| | `args` | `env` / `cwd` | Proof |
|---|---|---|---|
| **New role session** | `-i "<first prompt>"`, or no args | `cwd=<worktree>`, **`GEMINI_SYSTEM_MD=/etc/agent-roles/<role>.md`**, `GEMINI_CLI_HOME=<per-container dir>` whose `settings.json` holds `security.auth.selectedType` and `context.fileName`, `GEMINI_CLI_TRUST_WORKSPACE=true`, `GOOGLE_GEMINI_BASE_URL`, key | wire `it-gm`, `gm-custom`; trust wire `gm-untrusted` (exit 55) |
| **Resume, same work item** | `--resume <session_id>` | the **same** `GEMINI_SYSTEM_MD`, **always set** on the pane | (b) falls back to default wire `gm-r2`; set again wire `gm-r3` |
| **Never rely on** | `GEMINI_SYSTEM_MD=true` (it resolves `.gemini/system.md` inside the worktree: source `:339549-339553`); a role file the agent can write (re-read every prompt build: source `:339557`); resuming from another worktree (refused: wire `xc-gm-B`); the project file being in `systemInstruction` (it is in `contents[0]`: wire `gm-default`) | | |

**The role is supplied only through an env var naming a file.** A pane `env`
can carry the path, but not the text. The file must exist at an absolute path
outside the writable worktree.

---

## 12. Probe cases

All captures were in the session scratch directory and are not kept.

| Case | What it was |
|---|---|
| `cc-default`, `cc-custom`, `cc-append` | Claude `-p`, default / `--system-prompt-file` / `--append-system-prompt-file` |
| `cc-sw1..sw5`, `cc-r1..r4` | Claude resume: A, edit, B / none / A / B, `--continue` |
| `ccs-1..4` | Claude resume with `--system-prompt-snapshot off` |
| `cx-default`, `cx-custom`, `cx-dev` | Codex 0.146 `exec`, default / `model_instructions_file` / `developer_instructions` |
| `cx-sw1..2`, `cx-r1..r4` | Codex `exec resume` matrix |
| `cx163-default`, `cx163-exec` | the SDK's bundled `codex-cli` 0.163.0 `exec` |
| `pi-default`, `pi-custom`, `pi-append`, `pi-sw1..2`, `pi-r1..r4` | Pi placement and resume |
| `gm-untrusted`, `gm-default`, `gm-custom`, `gm-r1..r4` | Gemini placement and resume |
| `it-cc`, `it-cx`, `it-pi`, `it-gm` | interactive TUIs under ConPTY |
| `one-cc`, `one-cx`, `one-pi`, `one-pi-claudeonly`, `one-gm` | the single-`AGENTS.md` project |
| `xc-*-A`, `xc-*-B` | start in worktree A, resume by id from B |
| `sdk-cc-*`, `sdk-cx-*`, `sdk-pi-*` | SDK cases (§9) |
