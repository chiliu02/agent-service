# `setting_paths`: layering user scope over project scope

**Status: BUILT, 2026-09-17.** Proposed and implemented the same day; it rides
the `0.28.0` snapshot, so nothing was cut for it. `PI-60` is the entry in
`pi-python`'s own references file and is the authority on what the code does —
this document is the argument that produced it, kept for the reasoning rather
than as a description of the build.

It made one change to `pi-python`'s handling of `RunOptions.setting_paths.skills`,
and argues that the other half of the problem is not a problem at all.

**The case.** A caller holds a worktree carrying project-scope ambient
configuration (`CLAUDE.md`, `.claude/skills/`) and, outside it, user-scope
configuration (`~/.claude/CLAUDE.md`, `~/.claude/skills/`). It wants both on a
`pi-python` session. `PI-19` suppresses all discovery, so `setting_paths` is the
only route, and the question is whether naming two of each does what the caller
means.

---

## 1. The order is user scope first, project scope second

Both lists are read in the order given — `resolve_setting_paths` builds its
tuples in iteration order and `_build_argv` emits one flag per entry in that
order.

```json
{"options": {"setting_paths": {
  "instructions": ["/harness/user/CLAUDE.md", "/workspace/CLAUDE.md"],
  "skills":       ["/harness/user/skills",    "/workspace/.claude/skills"]
}}}
```

**User scope first is not a preference, it is what the agents themselves do.**
Pi's own discovery reads `~/.pi/agent/AGENTS.md`, then parent directories walking
down, then the working directory. Gemini's loader concatenates global before
project. In both, the more specific file lands later, so a caller reproducing
ambient layering by hand puts the broader file first.

**A tilde is refused, and the refusal is right.** `_existing` checks
absoluteness before `expanduser()`, so `~/.claude/CLAUDE.md` is a 400. It would
be wrong even if expanded: in the image `HOME=/home/agent`, not the caller's
home, and `/home/agent/.agents` is deliberately masked `0555`. User-scope
configuration is bind-mounted at a path the caller chooses, read-only, and named
absolutely. (`expanduser()` is therefore unreachable for the one input it exists
for — a dead branch worth deleting, not a defect anyone can trip over.)

---

## 2. Concatenation is not a deviation — all four agents do it

**This was raised as a divergence and it is not one.** Naming two instruction
files appends both, in order, with no override semantics: a project file that
contradicts the user file does not replace it, and both sentences reach the
model. That is what every one of the four subjects does with layered instruction
files.

| Agent | Layers | Combined how | Evidence |
|---|---|---|---|
| **Pi** | `~/.pi/agent/AGENTS.md`, each parent directory, cwd | *"All matching files are concatenated"* | README of `@earendil-works/pi-coding-agent` 0.85.1, the version the image pins |
| **Gemini CLI** | global, extension, workspace, user-project | `concatenateInstructions` wraps each in `--- Context from: <path> ---` and joins them; `loadMemoryContents` orders global, extension, project, user-project, deduplicated by file identity | read from the vendored bundle at `impl/gemini-python/node_modules/@google/gemini-cli` |
| **Codex** | user, project (`AGENTS.md` from the thread's `cwd`) | both present together: `user` is always on and not selectable, and `project_doc_max_bytes=0` suppresses *only* the project doc | `CX-14`, measured in this repository with the control run first. The relative order is not measured here |
| **Claude Code** | user (`~/.claude/CLAUDE.md`), project (`./CLAUDE.md`) | both loaded and combined; a project file does not delete a user file | documented behaviour, **not measured in this repository** |

**So `pi-python` reproducing concatenation is fidelity, not a shortfall.** An
earlier reading of this called it a semantic difference from Claude Code; it is
not, and the claim is withdrawn. No change is proposed for `instructions`.

**What the caller does owe itself** is that ordering is the only lever. If two
named instruction files genuinely conflict, the service will not adjudicate and
neither will any of the four agents — compose the files so they do not.

---

## 3. The real defect: a duplicate skill name fails the session

`resolve_setting_paths` accumulates `names` across **every** entry in `skills`
and raises on the first collision:

> `setting_paths.skills: 'review' is declared by both
> '/harness/user/skills/review/SKILL.md' and
> '/workspace/.claude/skills/review/SKILL.md'.`

400, session not created.

**The check is right to exist.** `PI-59` measured what Pi does unaided: it keeps
whichever skill it reaches first, drops the other, exits 0 and says nothing on
any channel. Without the check, *which skill a session got would be decided by
traversal order*.

**But refusing the session is the wrong resolution, and it is wrong for a
specific reason: the caller already expressed an order and the service ignores
it.** The list is ordered. Order already carries meaning for `instructions`.
Shadowing a user-scope skill with a project-scope one of the same name is the
ordinary shape of layered configuration — it is what a caller mounting both
trees means — and here it is a hard stop with no way to express the intent at
all.

Two consequences today, both bad:

- A caller cannot mount both trees without first deduplicating them by hand,
  outside the container, which is precisely the composition work
  `setting_paths` exists to let it do by mounting.
- The failure is at session creation, so it surfaces as a 400 on a request that
  looks correct, naming two paths the caller deliberately mounted.

---

## 4. Proposed: later entries shadow earlier ones, by name

**Across entries — resolve, do not refuse.** A skill name declared by more than
one entry in `skills` resolves to the one from the **latest** entry. The earlier
is shadowed and not passed to the agent.

**Within one entry — still a 400.** A directory whose recursive walk finds two
`SKILL.md` files declaring one name keeps the current refusal. There is no order
to appeal to inside a single named path, so traversal order would decide, which
is the exact thing `PI-59` refuses to let happen.

**This does not erode `PI-59`; it applies it.** `PI-59`'s complaint is that the
*agent* drops something the caller never chose. A shadow the caller wrote into
its own ordered list is chosen. The distinction is the same one `PI-19` and
`PI-59` already draw between discovery and an explicit path: what the caller
named is the caller's own.

Everything else in `PI-59` stands unchanged — absolute paths only, existence and
readability checked at session creation, `name` and `description` required in
frontmatter, a regular file required for `instructions`, and the three
suppression flags on unconditionally.

---

## 5. What it costs to build

**`resolve_setting_paths` must return per-skill file paths, not the entries as
given.** Today it appends the entry (a file or a directory) and `_build_argv`
emits `--skill <entry>`. A shadow cannot be expressed that way: passing both
directories hands Pi both skills and lets its first-wins rule decide, which is
what we are removing. So the resolver returns the winning `SKILL.md` paths and
the runner emits one `--skill <file>` per winner. `--skill` already accepts a
file path, and `tests/test_setting_paths.py` already exercises that form.

**A side benefit worth naming.** Today we validate the set *our* `rglob` finds
and Pi loads the set *its* traversal finds. If those ever diverged, the session
would be validated against one set and run with another. Emitting resolved files
closes that seam.

**Argv grows** — one flag pair per skill rather than per directory. Acceptable;
the paths are short and the count is the caller's own.

**The shared schema description must move**, because `skills` gains a rule.
`SettingPaths` lives in `impl/common/agent-spec/`, which **names no build and
must not**, so the wording is "where this field is published, a later entry
shadows an earlier one declaring the same skill name" — never "on pi-python".
All four OpenAPI documents regenerate; only one build honours the field, but the
description is shared.

**`PI-60` is the next free id.** `PI-59` is amended rather than renumbered: its
duplicate-name paragraph is struck through and `PI-60` carries the new rule and
the reasoning above. An ID is permanent.

---

## 6. Versioning

**A build changing how it honours a `RunOptions` field is a
`capability-divergence.md` trigger even without a refusal moving** — and here a
refusal does move. Two §3 rows change: the `setting_paths` row for `pi-python`,
and the "a path that is wrong" row, which currently says every mistake is a 400.

**`spec/VERSION` is `0.28.0-snapshot`, so this rides the snapshot.** A snapshot
is never frozen, no consumer has adopted it, and nothing needs cutting for the
change to land. The document version moves only when 0.28.0 is cut, whenever
that is warranted on its own merits.

**It is backward compatible.** A request that used to 400 now succeeds; no
request that used to succeed changes behaviour. No client breaks, and a client
that deduplicated by hand to work around the refusal keeps working — it simply
no longer has to.

---

## 7. Not proposed

- **No change to `instructions`.** §2 is why.
- **No change to the other three builds.** They refuse `setting_paths` for
  having the equivalent, not for lacking it (`GP-74` states it for Gemini, and
  the Claude and Codex guides state it for theirs), and nothing here touches
  that.
- **No change to `setting_sources`.** Still `[]` on this build and still
  refused; it switches whole layers of the agent's own discovery, none of which
  runs here.
- **No warning channel.** A shadow is not reported back, because the caller
  wrote the order that produced it. If a caller ever needs the resolved set,
  that is a separate ask against the session-creation response.
