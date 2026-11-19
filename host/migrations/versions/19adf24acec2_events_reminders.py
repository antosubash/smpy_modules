"""events reminders

Events PR 8: ``events_follow`` (one user's wish to be reminded a lead time before an event),
``events_reminder_sent`` (the at-most-once ledger of what was sent) and the nullable
``events_calendar.default_reminder_minutes`` (per-calendar default lead times; ``NULL`` means the
install-wide setting), and two indexes for the reminder beat (``ix_events_follow_lead``,
``ix_events_event_start``). No data migration, no branch label (``events`` is already named by
``b8e1d0783868``).

Revision ID: 19adf24acec2
Revises: 6dedd89ae3a8
Create Date: 2026-11-18 23:43:54.469306
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "19adf24acec2"
down_revision: str | None = "6dedd89ae3a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events_follow",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("lead_minutes", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events_event.id"],
            name=op.f("fk_events_follow_event_id_events_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_follow")),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "event_id", "lead_minutes", name="uq_events_follow"
        ),
    )
    op.create_index(
        "ix_events_follow_event", "events_follow", ["tenant_id", "event_id"], unique=False
    )
    op.create_index(op.f("ix_events_follow_event_id"), "events_follow", ["event_id"], unique=False)
    op.create_index(
        op.f("ix_events_follow_tenant_id"), "events_follow", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_events_follow_user", "events_follow", ["tenant_id", "user_id"], unique=False
    )
    op.create_index(
        "ix_events_follow_lead",
        "events_follow",
        ["tenant_id", "lead_minutes", "event_id"],
        unique=False,
    )
    op.create_table(
        "events_reminder_sent",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(length=80), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_id", sa.String(length=64), nullable=False),
        sa.Column("lead_minutes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events_event.id"],
            name=op.f("fk_events_reminder_sent_event_id_events_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_reminder_sent")),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "occurrence_key",
            "starts_at",
            "recipient_id",
            "lead_minutes",
            name="uq_events_reminder_sent",
        ),
    )
    op.create_index(
        "ix_events_reminder_sent_claimed",
        "events_reminder_sent",
        ["tenant_id", "claimed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_reminder_sent_event_id"), "events_reminder_sent", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_events_reminder_sent_tenant_id"),
        "events_reminder_sent",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_events_event_start", "events_event", ["tenant_id", "starts_at"], unique=False
    )
    with op.batch_alter_table("events_calendar") as batch:
        batch.add_column(sa.Column("default_reminder_minutes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events_calendar") as batch:
        batch.drop_column("default_reminder_minutes")
    op.drop_index("ix_events_event_start", table_name="events_event")
    op.drop_index(op.f("ix_events_reminder_sent_tenant_id"), table_name="events_reminder_sent")
    op.drop_index(op.f("ix_events_reminder_sent_event_id"), table_name="events_reminder_sent")
    op.drop_index("ix_events_reminder_sent_claimed", table_name="events_reminder_sent")
    op.drop_table("events_reminder_sent")
    op.drop_index("ix_events_follow_lead", table_name="events_follow")
    op.drop_index("ix_events_follow_user", table_name="events_follow")
    op.drop_index(op.f("ix_events_follow_tenant_id"), table_name="events_follow")
    op.drop_index(op.f("ix_events_follow_event_id"), table_name="events_follow")
    op.drop_index("ix_events_follow_event", table_name="events_follow")
    op.drop_table("events_follow")
