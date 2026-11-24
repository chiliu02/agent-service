"""Which file holds a thread's conversation: `transcript_path` (CX-75).

Codex writes a thread's rollout to
`<CODEX_HOME>/sessions/YYYY/MM/DD/rollout-<local timestamp>-<thread id>.jsonl`.
The date and the timestamp are the app-server's LOCAL time at the thread's
start, so the name cannot be derived from the id. It is found instead.

**The rule.** The rollout is the one file under `sessions/` whose name ends in
`-<thread id>.jsonl`. It is reported only when exactly one such file exists
and, when Codex reported `Thread.path`, that path names the same file. Anything
else is `None`. `Thread.path` is not used alone: it is marked UNSTABLE in the
SDK's schema, and it names the file before the file exists (CX-75).

**Never raises.** This field is reported on every turn and every record, so a
failure here is `None`, never a failed request.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: A thread id is a UUID. Anything else is never put in a glob pattern.
_THREAD_ID = re.compile(r"^[0-9A-Fa-f-]{1,64}$")

#: The prefix Windows adds to a verbatim path. Codex reports the path in this
#: form after a resume and without it before one (CX-75).
_VERBATIM = "\\\\?\\"


def _same_file(a: Path, b: str) -> bool:
    if b.startswith(_VERBATIM):
        b = b[len(_VERBATIM) :]
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(
            str(Path(b).resolve())
        )
    except (OSError, ValueError):
        return False


def find_rollout(
    home: str | os.PathLike[str] | None,
    thread_id: str | None,
    reported: str | None = None,
) -> str | None:
    """The rollout of `thread_id`, relative to `<home>/sessions`, or `None`.

    `reported` is the app-server's `Thread.path` when it was read; `None`
    skips the cross-check. The result uses forward slashes.
    """
    try:
        if not home or not thread_id or not _THREAD_ID.match(thread_id):
            return None
        store = Path(home).resolve() / "sessions"
        found = [
            p
            for p in store.glob(f"*/*/*/rollout-*-{thread_id}.jsonl")
            if p.is_file()
        ]
        # Two files for one thread means the conversation is split, and the
        # contract says null for that (CX-75).
        if len(found) != 1:
            return None
        if reported is not None and not _same_file(found[0], reported):
            return None
        return found[0].relative_to(store).as_posix()
    except Exception:  # noqa: BLE001 - see the module docstring
        return None
