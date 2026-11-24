"""A.2: the SDK's `SessionStore`, backed by `transcript_entries`.

This is the OTHER write path, and it must stay separate from `repository.py`.
The SDK calls `append()` on its own schedule (~100ms during active turns,
flushed per turn by default) from inside the subprocess's read loop; nothing
here goes through the A.1 queue, and nothing here is ever parsed by this
service.

## What this is not

It is not a transcript the console reads. `SessionStoreEntry` is the CLI's
on-disk JSONL shape -- `claude_agent_sdk.types` calls it "a large discriminated
union" that "is internal", guaranteeing only `type` plus usually `uuid` and
`timestamp`. Its purpose is that the CLI can resume from it. `db.models.Event`
is what a UI reads.

## Only `append` and `load` are implemented

Both are required by the protocol; `list_sessions`, `list_session_summaries`,
`delete` and `list_subkeys` are optional, and the SDK probes for their presence
at runtime rather than using `isinstance`. The conformance suite skips the tests
for any method an adapter does not override, so this passes conformance without
claiming capabilities it does not have.

`delete` in particular is deliberately absent for now: the SDK never deletes
unless it is implemented, so leaving it off means retention is an explicit
decision rather than something that quietly starts happening. That decision is
Q11, scheduled for Task 8.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_spec.db.models import TranscriptEntry

log = logging.getLogger(__name__)


def key_to_string(key: dict[str, Any]) -> str:
    """`project_key/session_id[/subpath]`.

    Deliberately identical to the SDK's own `_key_to_string` in
    `_internal/session_store.py`, so this adapter groups entries exactly the way
    the reference implementation does.

    KNOWN LIMIT, inherited from that encoding: a `project_key` containing a
    slash could in principle collide with a `session_id`. The SDK documents
    `project_key` as a sanitized cwd or a tenant id, and its own store has the
    same property, so deviating here would be a silent difference from the
    reference rather than a fix.
    """
    parts = [key["project_key"], key["session_id"]]
    subpath = key.get("subpath")
    if subpath:
        parts.append(subpath)
    return "/".join(parts)


class PostgresSessionStore:
    """Satisfies `claude_agent_sdk.SessionStore` structurally.

    Not a subclass: the SDK never uses `isinstance` for this, and inheriting
    would drag in the Protocol's `NotImplementedError` defaults for the optional
    methods, which its capability probe reads as "implemented".
    """

    __slots__ = ("_sessionmaker", "_agent_id")

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent_id: str | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        # Same process constant the recorder holds, and held the same way: this
        # adapter's `append` signature is the SDK's, so there was never a route
        # for a caller value anyway. Stamped here because `transcript_entries`
        # has no foreign key to a stamped `sessions` row -- see the column's
        # comment in models.py for why the join that looks available is not.
        self._agent_id = agent_id

    async def append(self, key: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        """Mirror a batch. Called AFTER the subprocess's own local write.

        Durability is therefore already guaranteed on disk before this runs,
        which is why a failure here is non-fatal: the SDK retries three times,
        then surfaces a `MirrorErrorMessage` and carries on.

        `ON CONFLICT DO NOTHING` implements the documented idempotency rule --
        most entries carry a stable `uuid` that adapters should treat as an
        idempotency key. Entries WITHOUT one (titles, tags, mode markers) must
        be appended without dedup, which the partial index
        (`WHERE uuid IS NOT NULL`) allows: Postgres skips a partial index
        entirely for rows that fail its predicate, so those rows never conflict.
        """
        if not entries:
            # Contractually a no-op. Worth an early return rather than an empty
            # INSERT, which would still take a connection from the pool.
            return

        session_key = key_to_string(key)
        rows = [
            {
                "session_key": session_key,
                # The SDK's key, read off the entry itself -- NOT invented here.
                # Absent for the entry kinds that legitimately have none.
                "uuid": entry.get("uuid"),
                # Stored VERBATIM. `load` must return entries deep-equal to what
                # was appended, and anything this adapter added or dropped would
                # come back as a difference.
                "entry": entry,
                # A COLUMN, never folded into `entry`. Putting it inside the
                # JSONB would break the sentence above: `load` returns `entry`
                # and the SDK compares it to what it appended.
                "agent_id": self._agent_id,
            }
            for entry in entries
        ]
        statement = pg_insert(TranscriptEntry).values(rows)
        statement = statement.on_conflict_do_nothing(
            index_where=TranscriptEntry.__table__.c.uuid.isnot(None),
            index_elements=["session_key", "uuid"],
        )
        try:
            async with self._sessionmaker() as db, db.begin():
                await db.execute(statement)
        except Exception:
            # RAISING IS CORRECT HERE, and it is the opposite of the
            # `RunRecorder` specification -- worth stating plainly, because the two
            # write paths look alike and behave differently on failure.
            #
            # `RunRecorder` must never raise: it is called from inside
            # `_send_impl`'s drain, where an exception mislabels a turn. THIS is
            # called by the SDK, which catches, retries three times with
            # backoff, and then surfaces a `MirrorErrorMessage` -- so swallowing
            # here would deny it the failure it is designed to handle and make
            # a broken mirror look healthy.
            #
            # Logged first because the SDK's message says only that the batch
            # failed; the cause lives in this traceback and nowhere else.
            log.warning(
                "session-store mirror append failed for %s (%d entries); "
                "the SDK will retry, then report a mirror_error",
                session_key,
                len(rows),
                exc_info=True,
            )
            raise

    async def load(self, key: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Everything appended under `key`, in append order, or None.

        Ordered by `seq`, the insertion sequence, which is what makes append
        order recoverable -- the entries themselves carry no ordinal.

        `None`, not `[]`, for a key never written: the SDK uses that to decide
        whether there is anything to resume from. The specification explicitly
        permits an adapter that cannot tell "never written" from "emptied" to
        return None for both, which is what this does.
        """
        async with self._sessionmaker() as db:
            rows = (
                await db.execute(
                    select(TranscriptEntry.entry)
                    .where(TranscriptEntry.session_key == key_to_string(key))
                    .order_by(TranscriptEntry.seq)
                )
            ).scalars()
            entries = list(rows)
        return entries or None
