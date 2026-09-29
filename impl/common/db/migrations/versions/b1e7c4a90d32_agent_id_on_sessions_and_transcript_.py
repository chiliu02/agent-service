"""agent_id on sessions and transcript_entries

Revision ID: b1e7c4a90d32
Revises: a5cf3bd007f9
Create Date: 2026-08-07

BOTH COLUMNS IN ONE REVISION, DELIBERATELY. Requested by Agent Studio
(Agent Studio's agent-id requirement) and the "both" is the whole
point of the ask rather than a convenience:

  * Stamping `sessions` covers `runs` and `events` for free -- each has a
    foreign key up the chain, so a stamped session is reachable by join.
  * `transcript_entries` has NO foreign key. It is keyed by
    `session_key VARCHAR(256)`, the SDK's `project_key/session_id[/subpath]`
    encoding, against `sessions.id VARCHAR(64)`.

A join looks available, because that middle segment corresponds to
`sessions.sdk_session_id`. It is unsound for three independent reasons and the
first alone settles it: `key_to_string`'s own comment records that a
`project_key` containing a slash can collide with a `session_id`;
`sdk_session_id` is null until the first turn mints one; and no index serves a
derived substring. So transcripts stay unattributable unless stamped here too.

The consumer's own argument for doing it in ONE revision: a schema change costs
a drained window on their side, and deciding the second column afterwards costs
a second window. Nothing here is retroactive -- rows written before this stay
null, which is the status quo rather than a regression.

INDEXED ON `sessions`, NOT ON `transcript_entries`. The session query this
exists for is "which rows are this agent's". A transcript is read for a session
already resolved, so an index on the highest-volume table in the schema would
cost every append and serve nothing.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1e7c4a90d32"
down_revision: Union[str, Sequence[str], None] = "a5cf3bd007f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("agent_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_sessions_agent_id"), "sessions", ["agent_id"], unique=False)
    op.add_column(
        "transcript_entries", sa.Column("agent_id", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transcript_entries", "agent_id")
    op.drop_index(op.f("ix_sessions_agent_id"), table_name="sessions")
    op.drop_column("sessions", "agent_id")
