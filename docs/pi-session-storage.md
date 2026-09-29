# How Pi stores a conversation

**This describes the AGENT, not this repository's build of it.** Everything below
is true of anyone driving `@earendil-works/pi-coding-agent` from a command line,
whether `agent-service` exists or not. What `pi-python` does on top of it — the
directory it chooses, the index it keeps, what it never deletes — is `PI-52`,
`PI-53` and `PI-54` in
[`../impl/pi-python/docs/pi-python-references.md`](../impl/pi-python/docs/pi-python-references.md).

**Written 2026-09-08 against version 0.85.1**, which is the version this
repository's image pins (`ARG PI_VERSION=0.85.1`, verified at build time). Pi is
under active development and none of this is a stability contract.

**Every claim is one of two kinds and each is labelled:** *measured* by running
the binary, or *read* from the installed bundle. Nothing here rests on the
agent's own documentation alone — two of the traps in §4 are places where that
documentation is easy to read the wrong way.

---

## 1. The session directory

`--session-dir <dir>` is, in the agent's own words, *"Directory for session
storage and lookup"*. Both halves matter: it is where files are written **and**
the only place an id is searched for.

**Without the flag, one directory is derived per project** (*read*,
`getDefaultSessionDirPath`):

```js
const safePath = `--${resolvedCwd.replace(/^[/\\]/, "").replace(/[/\\:]/g, "-")}--`;
return join(resolvedAgentDir, "sessions", safePath);
```

→ `~/.pi/agent/sessions/--C-Users-chili-project--/`. This is the `--<cwd>--`
layout the agent's `session-format.md` documents.

**With the flag, that encoding never runs** (*read*). `getSessionDir()` returns
the stored value verbatim, so files land **flat** in the directory named. See §4:
building on the documented default while passing the flag is the easiest mistake
to make here.

**A relative value resolves against the PROCESS's working directory** (*read* +
*measured*). The session manager stores `normalizePath(sessionDir)` — normalize,
not resolve — which only expands `~`, `file://` and Windows shell forms. Node
resolves what remains against `process.cwd()`. Note that is the *process's* cwd,
not the `cwd` the agent carries for itself; they coincide for a plain invocation
and need not in general.

**The agent creates the directory, recursively, before any model call**
(*measured*):

```
invocation dir: <tmp>/proj
$ pi -p "hi" --session-dir "sess-here"     # relative, missing, no credential
→ <tmp>/proj/sess-here      created, and empty
```

The run ended at *"No API key found for the selected model."* and the directory
was still there — the `mkdirSync` is in the session-manager constructor, ahead of
authentication. The *file* appears only when an entry is first persisted, which
is why it was empty.

## 2. What is in it

**One file per conversation** — not per turn. Named
`<timestamp>_<session uuid>.jsonl`, the timestamp being the ISO creation time
with `[:.]` replaced by `-`, so the name is stable for the life of the
conversation and sorts chronologically.

**Turns append in place.** Entries carry `id` and `parentId` and form a **tree**,
which is how the agent branches without writing a new file — `/tree` moves the
leaf. `--fork` and `/clone` are the operations that do produce a new file, with a
**new** id.

A real two-turn conversation, first four entries (*measured*):

```json
{"type":"session","version":3,"id":"c7e4e172…","timestamp":"…","cwd":"…\\workspace"}
{"type":"model_change","id":"2b43816a","parentId":null,"provider":"google","modelId":"gemini-3.1-flash-lite"}
{"type":"thinking_level_change","id":"a6627c9c","parentId":"2b43816a","thinkingLevel":"medium"}
{"type":"message","id":"3d0d1ede","parentId":"a6627c9c","message":{"role":"user","content":[{"type":"text","text":"Remember this number: 8675309…"}]}}
```

**The file identifies the project and the model, not only the text.** `cwd` is in
the session header — which is what makes a session belong to a project, and §3
depends on it — and `provider`/`modelId` arrive in a `model_change` entry.

**Content blocks go well beyond text** (*read*, `session-format.md`): `text`,
`image` (base64 inline), `thinking`, `toolCall`, plus tool-result and
bash-execution entries. **A session that read files or ran commands writes file
contents and command output into this file.** Not measured here — the live turns
used no tools — but it is what the format defines, and it is what makes this file
sensitive rather than incidental.

**Versions 1, 2 and 3 exist and are migrated on load** (*read*), so opening an
older file rewrites it.

## 3. Finding one, and resuming it

**Measured keylessly on 0.85.1** — no model was called for any row:

| run | result |
|---|---|
| `--session <id>`, empty session dir | `No session found matching '<id>'` |
| `--session <id>`, file present | **loads it** — the ORIGINAL header is echoed, original timestamp |
| `--session <prefix of an id>` | **loads it** — exact match first, then `startsWith` |
| `--session <a path>` | **opens that file, wherever it is.** The session directory is not consulted |
| `--session-id <id>`, no such session | `Warning: No project session found with id '…'; creating a new session with that id.`, then a FRESH timestamp |
| `--session-id <id>`, file present | **loads it** — original timestamp, no warning |
| `--session-id <prefix>` | **no match** — creates a new session whose id is the literal prefix |
| both flags together | `Error: --session-id cannot be combined with --session` |

**`--session-id` is use-or-create**, exactly as `--help` says: *"Use exact
project session ID, creating it if missing"*. Given an id that exists, it
resumes. The warning line is the only discriminator between the two behaviours,
so a caller that does not read stderr cannot tell them apart.

**The two flags do not search alike.** `--session` matches a prefix and falls
back to a global search; `--session-id` is exact-only, current-project only, and
**creates on a miss rather than failing** — which is why a prefix handed to it
becomes a new conversation with a non-UUID id instead of an error.

**A path-shaped argument bypasses the directory entirely** (*read*,
`resolveSessionPath`): the argument is tested for `/`, `\` or a `.jsonl` suffix
*first*, and resolved as a filesystem path if any matches.

### Resuming across projects asks a question

`--session <id>` resolves in three steps (*read*): a path-like argument is a
path; otherwise the id is matched against the sessions of the **current project**
— those whose header `cwd` matches — and failing that against **every project**
in the session directory.

So a conversation created under a different working directory **is found**. What
happens next is the trap (*measured*):

```
Session found in different project: C:\Users\chili\SomeOtherProject
Fork this session into current directory? [y/N]
```

That is an interactive read on stdin. **A `-p` run cannot answer it**: the
process prints the prompt and ends with **exit 0, no turn taken and no JSON
envelope**. A non-interactive caller sees a successful exit and an empty result,
which is the worst shape a failure can take.

## 4. Two things that are easy to get wrong

Both were got wrong in this repository first, from reading rather than running.

**"`--session-id` names a new conversation."** It does not — it is use-or-create,
and given an existing id it resumes. The flag's name suggests otherwise; `--help`
does not.

**"Sessions live under a `--<cwd>--` subdirectory."** That is the agent's
documented **default** path and applies only when `--session-dir` is omitted.
With the flag, files are flat in the directory given. The difference decides
whether copying a conversation means copying a file or copying a tree.

A third, narrower one: the cross-project case in §3 is not *"the conversation is
not found"*. It is found; the turn then stalls on a question nothing can answer.

## 5. Elsewhere

- [`../impl/pi-python/docs/pi-python-references.md`](../impl/pi-python/docs/pi-python-references.md)
  — what this repository's build does with all of the above. `PI-13` (a
  conversation resumes across processes, measured on three providers), `PI-14`
  (a caller-supplied id), `PI-52` (the resume wiring, the id index, and what an
  id means after a resume), `PI-53` (what a deployment must keep) and `PI-54`
  (the store layout, and what is never deleted). **Where this file and an entry
  disagree, the entry is right** — entries are permanent and cited by code.
- The agent's own `docs/sessions.md` and `docs/session-format.md`, shipped in the
  npm package. Accurate about the default layout and silent about what changes
  when `--session-dir` is passed, which is §4's second trap.
- **The binary is the authority.** Where this file and version 0.85.1 disagree,
  the binary is right and this file is stale.
