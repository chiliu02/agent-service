"""The index that outlives a session, so `options.resume` can find one (`PI-52`).

**Why this exists at all.** Continuity on this build is per service session: the
agent stores its conversation under the `--session-dir` we give it, one
directory per session, and turn 2 resumes by id inside that directory. The map
from an SDK id back to the directory holding it lived in `Registry._sessions`,
and `_close` deletes the entry -- so a `DELETE`, or the idle sweep, took the
only route to a conversation that was still sitting on disk. `options.resume`
was therefore accepted and applied to nothing.

**One file per issued id, never one file for all of them.** A single index
document would need read-modify-write from every turn of every session, which is
a race this build has no lock for. A marker named by the id is written once and
never edited.

**The marker carries the cwd as well as the directory**, and that is not
bookkeeping. A conversation created under one working directory and resumed
under another is **found** by the agent -- `--session` falls back to a search
across every project -- and what it does next is print *"Session found in
different project"* and ask, interactively, whether to fork it. A `-p` run
cannot answer that: measured, it prints the prompt and ends with **exit 0, no
turn and no envelope**, which is a refusal wearing the shape of a success.

So this is not a lookup that fails; it is a turn that silently does not happen.
Recording the cwd is what turns it into a 404 at creation, before a caller has
been told a session was opened (`PI-52`).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: **What may become a filename.** The agent mints UUIDs, so this is not a
#: narrowing in practice -- it is what stops an id shaped like `../../etc` from
#: naming a file outside the index, on the one route where a caller's string
#: reaches the filesystem.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: Inside the session store, so one volume carries the conversations and the way
#: back to them. An index on a different mount is an index that goes missing
#: exactly when half a deployment is restored.
_INDEX_DIRNAME = "by-id"


class UnknownConversation(LookupError):
    """No conversation is indexed under that id. **Never a fresh one**: a caller
    that asked to continue a conversation must not silently be given another."""


class WrongWorkingDirectory(LookupError):
    """The conversation exists and this session must not open it.

    Raised rather than folded into `UnknownConversation` because the remedies
    differ: this one is *ask for the same `working_directory`*, and the other is
    *there is nothing to continue*.

    **The agent would find it and then stall** (`PI-52`) -- a cross-project
    match becomes an interactive fork prompt, and a non-interactive turn ends at
    exit 0 having done nothing. Refusing is what stops that becoming an empty
    answer a caller reads as a real one.
    """

    def __init__(self, sdk_session_id: str, wanted: str, recorded: str) -> None:
        super().__init__(sdk_session_id)
        self.wanted = wanted
        self.recorded = recorded


@dataclass(frozen=True)
class Conversation:
    """Where a conversation lives, and the cwd it answers to."""

    session_id: str
    directory: Path
    cwd: str


class ConversationIndex:
    """SDK id -> the session directory that holds that conversation.

    **Every id a session ever answered to resolves**, not only the newest. The
    caller most likely to resume is the one whose connection dropped, and it is
    holding an old one -- which on this build is usually the same id, since a
    conversation keeps its id across turns (`PI-13`), but a session that was
    resumed more than once has answered to several.
    """

    def __init__(self, store: Path) -> None:
        self._store = store

    @property
    def directory(self) -> Path:
        return self._store / _INDEX_DIRNAME

    def remember(self, sdk_session_id: str | None, session_id: str,
                 cwd: str) -> None:
        """Index one id against the session directory now holding its turn.

        **Never raises.** This runs after a turn has already succeeded and its
        answer is on its way to the caller; failing here would turn a completed
        turn into a 500 over bookkeeping. The cost of a lost write is that one
        id does not resume, which the log says.
        """
        if not sdk_session_id or not _SAFE_ID.match(sdk_session_id):
            return
        if not _SAFE_ID.match(session_id):
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / sdk_session_id).write_text(
                json.dumps({"session": session_id, "cwd": cwd}),
                encoding="utf-8",
            )
        except OSError:
            log.warning(
                "could not index conversation %s; a resume from that id will "
                "answer 404 although its session directory is on disk",
                sdk_session_id,
                exc_info=True,
            )

    def resolve(self, sdk_session_id: str, cwd: str) -> Conversation:
        """The conversation for an id, checked against the cwd it needs.

        **An id we never issued is a refusal, not an empty conversation.** So is
        one whose directory has since gone: *never existed* and *no longer here*
        are not distinguishable from this side, and mean the same thing to a
        caller -- there is nothing to continue.
        """
        if not sdk_session_id or not _SAFE_ID.match(sdk_session_id):
            raise UnknownConversation(sdk_session_id)
        try:
            payload = json.loads(
                (self.directory / sdk_session_id).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise UnknownConversation(sdk_session_id) from exc
        name = payload.get("session")
        recorded_cwd = payload.get("cwd") or ""
        # A marker that somehow holds a path is refused rather than followed.
        if not isinstance(name, str) or not _SAFE_ID.match(name):
            raise UnknownConversation(sdk_session_id)
        directory = self._store / name
        if not directory.is_dir():
            raise UnknownConversation(sdk_session_id)
        if recorded_cwd and recorded_cwd != cwd:
            raise WrongWorkingDirectory(sdk_session_id, cwd, recorded_cwd)
        return Conversation(session_id=name, directory=directory,
                            cwd=recorded_cwd or cwd)
