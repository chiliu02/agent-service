"""Storage models. Deliberately NOT the pydantic API schemas.

Two shapes on purpose: the wire format should be free to change for callers
without forcing a migration, and a migration should be possible without breaking
callers, which is the persistence design's own rule.

Nothing in `runner.py` or `sessions.py` imports this module -- they see only
`recorder.RunRecorder`. If that ever stops being true, the seam has moved.

## Session identity -- resolved, plan-03 Task 2

The original schema comment said `sessions.id` was "SDK-assigned
session_id". **It is not.** The stored key is the service-side `sid` that
`registry.py` mints as `uuid.uuid4().hex`, because:

- it is what `SessionRecord.session_id` publishes (`api.py:130`), so it is the
  only id any client has ever seen or can send back;
- it exists at session-creation time, whereas the SDK's does not arrive until
  the first `SystemMessage` of the first turn -- a session created and never
  used would otherwise have no key at all;
- it is stable, while the SDK's can move under fork/resume.

The SDK's id is kept as `sdk_session_id`, nullable and indexed: it is the join
key to A.2's `transcript_entries` and the value the resume path needs. Both are
required; neither substitutes for the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Money. NUMERIC, never float: these values are summed for reporting, and a
# binary float would make two identical reports disagree in the sixth decimal.
_MONEY = Numeric(12, 6)

# TIMESTAMPTZ, not a naive timestamp. A naive column silently reinterprets
# every value in the server's local zone, which makes two deployments in
# different regions disagree about when the same run happened.
_TSTZ = DateTime(timezone=True)


class Session(Base):
    """One multi-turn session.

    A one-shot `POST /v1/query` gets NO row here -- it has no service-side `sid`
    because it is never registered. Its `Run` row carries `session_id = NULL`.
    That differs from the design's original text, which assumed one row per
    SDK session; the SDK assigns an id to one-shot runs too, but this service
    never exposes it as a session, so a row here would be unreachable by any API
    path.
    """

    __tablename__ = "sessions"

    # The service-side sid. See the module docstring for why this and not the
    # SDK's.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The SDK's session id, once it is known. Nullable because it is unknown
    # until the first turn produces a SystemMessage.
    sdk_session_id: Mapped[str | None] = mapped_column(String(128), index=True)

    # PROVENANCE, not authorisation (0.9.0). The `AGENT_ID` of the container
    # that created this session, stamped at create and never updated.
    #
    # It exists because a consumer may run many agents against ONE shared
    # schema, in which case every row here belongs to somebody and no column
    # said which -- so a session the consumer's own bookkeeping missed is not
    # untidy, it is one nobody can be shown to own. Indexed because the query
    # it exists for is "which rows are this agent's".
    #
    # NULLABLE AND UNVALIDATED ON PURPOSE. Absent `AGENT_ID` is a normal
    # deployment, and this service never parses the value. It cannot be set by
    # a caller: it is a process constant with no request field to arrive
    # through, which is structural rather than checked.
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)

    title: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    permission_mode: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(_TSTZ, server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(_TSTZ, server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(_TSTZ)

    # NOT the figure. This mirrors the SDK's running total for the connection,
    # which spike case S6 and `schemas.py` both record as a FLOOR
    # on what the session cost: an INTERRUPTED turn runs real inference and does
    # not move it. Measured -- eight consecutive start-then-interrupt turns
    # advanced it by $0.000649 in total. A dashboard that presents this as
    # "cost" is wrong, and the column name alone will invite exactly that, which
    # is why the warning lives here in the schema and not only in the docs.
    # NULLABLE SINCE d3f9a0c15e27, and `NULL` is not `0`. `0` means "the floor
    # has not moved yet" -- a build that CAN price a turn, whose priced turns
    # have so far cost nothing or have not happened. `NULL` means "this build
    # cannot price a turn at all", which is the honest answer for an SDK that
    # reports token counts and no money. Codex is measured to report no cost
    # anywhere in its package, so every one of its sessions would otherwise read
    # `0.000000` forever -- indistinguishable from free.
    #
    # `SessionRecord.total_cost_usd` in the published document has said exactly
    # this since 0.16.0 ("null means this build cannot price a turn at all,
    # which is not the same as 0.0"). The column was the half that had not caught
    # up, and it caught up before a second implementation started writing rows
    # rather than after.
    #
    # THE SERVER DEFAULT IS GONE TOO, and that is the operative half: a column
    # that is nullable but defaults to `0` still records `0` for every row
    # nobody prices, which is the state this change exists to stop.
    total_cost_usd: Mapped[float | None] = mapped_column(_MONEY, nullable=True)
    # Turns that reached a ResultMessage, matching `SessionRecord.turns`. A turn
    # that timed out, failed, or was abandoned mid-drain is NOT counted.
    total_turns: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)

    # Deliberately absent: `options JSONB`. "The resolved options" is a
    # ClaudeAgentOptions dataclass that can hold callables, which `to_jsonable`
    # renders as {"_unserializable": ...}. Storing that verbatim would be
    # recording noise as if it were configuration. What subset is worth keeping
    # is a real decision and has not been made -- see plan-03 Task 4.


class Run(Base):
    """One prompt submitted: a `POST /v1/query`, or one turn of a session."""

    __tablename__ = "runs"

    # uuid4().hex as minted by runner.Run / sessions._send_impl, stored as text
    # rather than UUID so the column holds exactly what the recorder was handed.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # NULL for a one-shot run, and ONLY for that: it is never registered, so it
    # has no service-side sid and no `sessions` row to reference. A session turn
    # always fills this -- every implementation passes its sid to `start_run`.
    #
    # THE READ PATH DEPENDS ON IT, which is what makes NULL here a defect rather
    # than a gap: a session's transcript is `events` joined through `runs` and
    # filtered on this column, so a turn recorded without it is a turn no
    # transcript can show. Worth knowing because the failure is silent -- an
    # empty page, not an error.
    session_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    sdk_session_id: Mapped[str | None] = mapped_column(String(128), index=True)

    started_at: Mapped[datetime] = mapped_column(_TSTZ, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(_TSTZ)
    prompt: Mapped[str] = mapped_column(Text(), nullable=False)

    # -- from ResultMessage, via runner.RunOutcome ------------------------
    result_text: Mapped[str | None] = mapped_column(Text())
    result_subtype: Mapped[str | None] = mapped_column(String(64))
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    terminal_reason: Mapped[str | None] = mapped_column(String(64))
    # "turns" or "budget" -- runner.detect_limit's answer, kept because the raw
    # markers it reads are undocumented and were measured, not guessed.
    limit_hit: Mapped[str | None] = mapped_column(String(32))
    num_turns: Mapped[int | None] = mapped_column(Integer())
    duration_ms: Mapped[int | None] = mapped_column(Integer())
    duration_api_ms: Mapped[int | None] = mapped_column(Integer())
    api_error_status: Mapped[int | None] = mapped_column(Integer())

    # What THIS run cost. NULL means "nobody can say", NEVER 0.0 -- an aborted
    # turn is unattributed, not free (runner.unattributed_abort). Distinct from
    # `Session.total_cost_usd`, which is cumulative for the connection.
    cost_usd: Mapped[float | None] = mapped_column(_MONEY)

    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    model_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    permission_denials: Mapped[Any | None] = mapped_column(JSONB())
    errors: Mapped[Any | None] = mapped_column(JSONB())

    # -- how the run ended, from the service's point of view ---------------
    # `is_error` is the AGENT reporting its task failed: a successful run with a
    # bad outcome. `error` is the MACHINERY failing: subprocess crash, malformed
    # message, timeout. Collapsing them makes "how often does the agent fail?"
    # unanswerable -- the same distinction the HTTP layer draws.
    is_error: Mapped[bool | None] = mapped_column(Boolean())
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    interrupted: Mapped[bool] = mapped_column(
        Boolean(), server_default="false", nullable=False
    )
    timed_out: Mapped[bool] = mapped_column(Boolean(), server_default="false", nullable=False)
    # No ResultMessage was ever consumed: crash, abandoned consumer, or timeout.
    # A real state, distinct from a clean finish, which runner.Run's docstring
    # already tells callers they MUST handle separately. Derived from
    # `outcome is None` at finish_run time and stored explicitly so a query does
    # not have to infer it from a dozen NULLs.
    outcome_missing: Mapped[bool] = mapped_column(
        Boolean(), server_default="false", nullable=False
    )

    __table_args__ = (Index("runs_session_started", "session_id", "started_at"),)


class Event(Base):
    """One normalized SDK message. This is A.1's transcript."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    # Ordering within the run, as assigned by the driver's own counter -- NOT
    # by arrival at the writer, which batches and could reorder.
    seq: Mapped[int] = mapped_column(Integer(), nullable=False)
    at: Mapped[datetime] = mapped_column(_TSTZ, server_default=func.now(), nullable=False)

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[Any | None] = mapped_column(JSONB())
    # The full SDK dump, present only when the run was made with
    # `include_raw`. Q3: if include_raw becomes opt-in this is mostly NULL and
    # the transcript is much smaller. Worth deciding before there is volume.
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB())

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="events_run_seq_unique"),
        Index("events_run_seq", "run_id", "seq"),
        Index("events_type", "type"),
    )


class TranscriptEntry(Base):
    """A.2: the SDK's mirrored transcript. NEVER parsed by this service.

    `entry` is the CLI's on-disk JSONL shape, which `claude_agent_sdk.types`
    describes as "a large discriminated union" that "is internal", guaranteeing
    only `type` plus usually `uuid` and `timestamp`. Reading into it from a
    query, a console, or a report couples this service to a format that can
    change under an SDK upgrade. `Event` above is what the console reads.
    """

    __tablename__ = "transcript_entries"

    seq: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(256), nullable=False)
    # The SDK's stable idempotency key. NULL for entries that legitimately have
    # none (titles, tags, mode markers), which the SDK says must be appended
    # WITHOUT dedup -- hence the partial index below rather than a plain unique
    # constraint, which would collapse them all into one row.
    uuid: Mapped[str | None] = mapped_column(String(128))
    at: Mapped[datetime] = mapped_column(_TSTZ, server_default=func.now(), nullable=False)
    entry: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)

    # THE SAME STAMP, AND IT NEEDS ITS OWN COLUMN. Stamping `sessions` covers
    # `runs` and `events` through their foreign keys; this table has none. It
    # is keyed by `session_key VARCHAR(256)` -- `project_key/session_id[/sub]`,
    # the SDK's encoding -- against `sessions.id VARCHAR(64)`.
    #
    # A join LOOKS available, because the middle segment corresponds to
    # `sessions.sdk_session_id`. It is unsound anyway, for three independent
    # reasons and the first alone settles it: `key_to_string`'s own comment
    # records that a `project_key` containing a slash can collide with a
    # `session_id`; `sdk_session_id` is null until the first turn mints one;
    # and no index serves a derived substring. Unsound AND looks sound is worse
    # than plainly unavailable.
    #
    # NOT INDEXED, unlike `sessions.agent_id`. This is provenance at rest --
    # read for a session already resolved, not scanned by agent -- and an index
    # on the highest-volume table in the schema costs every append.
    agent_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index(
            "transcript_entries_dedup",
            "session_key",
            "uuid",
            unique=True,
            # A raw SQL predicate, not `uuid.is_not(None)`: inside the class
            # body `uuid` is still a MappedColumn, not a Column, so the
            # operator form does not resolve here.
            postgresql_where=text("uuid IS NOT NULL"),
        ),
        Index("transcript_entries_session", "session_key", "seq"),
    )
