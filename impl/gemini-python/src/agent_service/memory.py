"""The agent's memory, kept past the session home it is written in (GP-76).

**The agent keeps memory by editing Markdown** under
`$HOME/.gemini/tmp/<project>/memory/`, and this build gives every session its
own `HOME` and deletes it at close (GP-39). So without this module a memory
lasts exactly one session.

**Copied, not linked.** A link from the home into the store would be live, but
the agent's file tools resolve a path before deciding whether it may write
there, and a store outside every allowed directory is a write the agent may
refuse; links on a Windows host need a privilege besides. A copy is a plain
directory where the agent expects one.

**So the copy is per TURN, both ways**, because this build spawns the agent
per turn (GP-41): `pull` before the process starts, so a turn reads what any
session wrote before it, and `push` when the turn ends, however it ends. `push`
sends only what THIS turn changed, measured against the snapshot `pull` took,
so a session never writes back a stale copy of a file another session has
since rewritten. Two sessions changing one file in overlapping turns: the
later `push` wins, which is what the published field says.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)


def project_slug(cwd: Path) -> str:
    """The agent's own name for the project folder: its `slugify` of the
    working directory's basename (GP-76).

    In a fresh home nothing else has claimed the name, so the agent's
    collision suffixes never apply -- and pre-creating the folder without the
    agent's ownership marker does not count as a claim.
    """
    slug = re.sub(r"[^a-z0-9]", "-", cwd.name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "project"


def home_folder(home: Path, cwd: Path) -> Path:
    """Where the agent reads and writes memory, in one session's home."""
    return home / ".gemini" / "tmp" / project_slug(cwd) / "memory"


def store_folder(store: Path, cwd: Path) -> Path:
    """Where that memory is kept between sessions: one folder per project."""
    return store / project_slug(cwd)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def pull(store: Path, home: Path) -> dict[str, str]:
    """Replace the home's memory folder with the store's. Returns the snapshot
    `push` compares against: relative path -> content digest.

    **Never fails the turn.** An unreadable store is logged and the turn runs
    with no memory, which is what it would have had before this module.
    """
    try:
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir(parents=True, exist_ok=True)
        snapshot: dict[str, str] = {}
        for rel, src in _files(store).items():
            dst = home / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            snapshot[rel] = _digest(dst)
        return snapshot
    except OSError as exc:
        _log.warning("memory store %s was not read into %s: %s", store, home, exc)
        return {}


def push(home: Path, store: Path, snapshot: dict[str, str]) -> None:
    """Send this turn's changes to the store, and nothing else.

    A file is sent when it is new or its content differs from the snapshot. A
    file the turn deleted is removed from the store **only if the store still
    holds the version this turn started from**, so a deletion never erases a
    newer write by another session. Each write lands by rename, so a reader
    never sees half a file.

    **Never fails the turn**, which has already happened by the time this runs;
    a failure is logged with both paths.
    """
    try:
        present = _files(home)
        for rel, src in present.items():
            if snapshot.get(rel) == _digest(src):
                continue
            dst = store / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        for rel, digest in snapshot.items():
            if rel in present:
                continue
            dst = store / rel
            if dst.is_file() and _digest(dst) == digest:
                dst.unlink()
    except OSError as exc:
        _log.warning("memory in %s was not kept in %s: %s", home, store, exc)
