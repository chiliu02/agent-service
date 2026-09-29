"""The index that outlives a session, so `options.resume` can find a transcript.

**Why this exists at all** (GP-70). Continuity on this build is per service
session: turn 2 resumes from the copy turn 1 left behind (GP-10, GP-11). The
map from an SDK id back to that copy lived in `Registry._sessions`, and
`_close` deletes the entry -- so a `DELETE`, or the idle sweep, took the only
route to a transcript that was still sitting on disk. `options.resume` was
therefore accepted and applied to nothing.

**One file per issued id, never one file for all of them.** A single index
document would need read-modify-write from every turn of every session, which
is a race this build has no lock for. A marker named by the id is written once
and never edited, so two sessions finishing a turn at the same moment cannot
lose each other's entry.

**The marker holds a NAME, not a path.** A deployment that remounts the store
somewhere else keeps working, because the name is resolved against wherever the
store is now -- an absolute path recorded a month ago would resolve to nothing
and read as *no such conversation*.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

#: **What may become a filename.** The agent mints UUIDs, so this is not a
#: narrowing in practice -- it is what stops an id shaped like `../../etc` from
#: naming a file outside the index, on the one route where a caller's string
#: reaches the filesystem.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: Beside the transcripts rather than above them, so one volume carries both. A
#: transcript whose index entry is on a different mount is a transcript that
#: becomes unreachable when only one of the two is restored.
_INDEX_DIRNAME = "by-id"


class UnknownConversation(LookupError):
    """No transcript is indexed under that id. **A 404**, and never a fresh
    conversation: a caller that asked to continue one must not silently be
    given another (GP-35)."""


class ConversationIndex:
    """SDK id -> the transcript that carries that conversation.

    **Every id a session ever issued resolves**, not only the newest (GP-35).
    The caller most likely to resume is the one whose connection dropped, and it
    is holding an old one.
    """

    def __init__(self, store: Path) -> None:
        self._store = store

    @property
    def directory(self) -> Path:
        return self._store / _INDEX_DIRNAME

    def remember(self, sdk_session_id: str | None, transcript: Path) -> None:
        """Index one id against the transcript that now carries its turn.

        **Never raises.** This runs after a turn has already succeeded and its
        answer is on its way to the caller; failing here would turn a completed
        turn into a 500 over bookkeeping. The cost of a lost write is that one
        id does not resume, which the log says.

        **Repeated ids are written again rather than skipped.** On a resumed
        session the agent mints a new id per turn (GP-34), but a build that
        reported the same id twice must still end with the marker pointing at
        the transcript that has the most history in it.
        """
        if not sdk_session_id or not _SAFE_ID.match(sdk_session_id):
            return
        if not transcript.exists():
            # Nothing to point at. A turn that produced no transcript is not a
            # conversation anything can be resumed from.
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / sdk_session_id).write_text(
                transcript.name, encoding="utf-8"
            )
        except OSError:
            log.warning(
                "could not index conversation %s; a resume from that id will "
                "answer 404 although its transcript is on disk",
                sdk_session_id,
                exc_info=True,
            )

    def resolve(self, sdk_session_id: str) -> Path:
        """The transcript for an id, or `UnknownConversation`.

        **An id we never issued is a refusal, not an empty conversation.** So is
        one whose transcript has since gone: the distinction between *never
        existed* and *no longer here* is not one this index can draw, and both
        mean the same thing to a caller -- there is nothing to continue.
        """
        if not sdk_session_id or not _SAFE_ID.match(sdk_session_id):
            raise UnknownConversation(sdk_session_id)
        marker = self.directory / sdk_session_id
        try:
            name = marker.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise UnknownConversation(sdk_session_id) from exc
        # The recorded NAME, resolved against the store as it is now. A marker
        # that somehow holds a path is refused rather than followed.
        if not name or "/" in name or "\\" in name:
            raise UnknownConversation(sdk_session_id)
        transcript = self._store / name
        if not transcript.exists():
            raise UnknownConversation(sdk_session_id)
        return transcript
