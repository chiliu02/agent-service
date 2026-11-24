"""Where a conversation's transcript is: `transcript_path` on `RunResponse` and
`SessionRecord`. CP-160

The CLI writes a conversation to `<home>/projects/<a slug of its cwd>/<sdk
session id>.jsonl`. The slug is the CLI's rule, not ours, so this FINDS the file
the turn just caused instead of rebuilding its name: one directory listing of
`projects/`, then one existence check per project directory.

**Never raises.** It runs inside the response builders that also serve the
streaming routes; an unreadable store is a null, not a failed turn.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from pathlib import Path

from agent_service.config import AGENT_HOME_SOURCE, Settings

#: The store relative to the home, as `PrebootSpec.agent_home.conversations`
#: publishes it. Read from the same mapping so the two cannot disagree.
CONVERSATIONS_PATH: str = AGENT_HOME_SOURCE["conversations"]["path"]  # type: ignore[index]

#: Found paths kept per process, so a `GET /v1/sessions` listing costs one
#: existence check per session rather than a scan. Bounded: one-shot runs add
#: entries too.
_CACHE_MAX = 4096


def conversations_dir(settings: Settings) -> Path:
    """The store: the configured home's `projects/`, or the CLI's default
    home's when none is configured -- the same resolution as `memory_dir`."""
    home = settings.agent_home if settings.agent_home is not None else Path.home() / ".claude"
    return home / CONVERSATIONS_PATH


class TranscriptLocator:
    """Finds `<store>/*/<sdk_session_id>.jsonl` and reports it relative to the
    store, with forward slashes. CP-160"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._found: OrderedDict[str, str] = OrderedDict()

    def locate(self, sdk_session_id: str | None, *, written_elsewhere: bool = False) -> str | None:
        """The path, or None when there is no ONE file holding the whole
        conversation: no id yet, part of it written elsewhere (a resume
        materialised from the session store), no file, or more than one."""
        if sdk_session_id is None or written_elsewhere:
            return None
        try:
            # Session ids are UUIDs. Anything else is not looked up at all,
            # which also keeps a caller's string out of a glob pattern.
            uuid.UUID(sdk_session_id)
        except (ValueError, TypeError, AttributeError):
            return None
        try:
            store = conversations_dir(self._settings)
            cached = self._found.get(sdk_session_id)
            if cached is not None:
                if (store / cached).is_file():
                    return cached
                del self._found[sdk_session_id]
            matches = [p for p in store.glob(f"*/{sdk_session_id}.jsonl") if p.is_file()]
            if len(matches) != 1:
                return None
            relative = matches[0].relative_to(store).as_posix()
        except Exception:  # noqa: BLE001 - this field never fails a response
            return None
        self._found[sdk_session_id] = relative
        if len(self._found) > _CACHE_MAX:
            self._found.popitem(last=False)
        return relative
