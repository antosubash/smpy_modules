"""events calendar redirect

Adds ``events_calendar_redirect``: a calendar's old slug, so ``/events/c/<old>`` (and its
``.ics`` subscription) answers 301 after a rename. Unique on ``(tenant_id, old_slug)``;
the calendar's row cascades. Nothing else is altered; no data migration. No branch label
(``events`` is already named by ``b8e1d0783868``).

Revision ID: 8e5853254f79
Revises: f3c0b2daeaf2
Create Date: 2026-11-18 05:54:14.770780
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8e5853254f79"
down_revision: str | None = "f3c0b2daeaf2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events_calendar_redirect",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("old_slug", sa.String(length=80), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["events_calendar.id"],
            name=op.f("fk_events_calendar_redirect_calendar_id_events_calendar"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_calendar_redirect")),
        sa.UniqueConstraint("tenant_id", "old_slug", name="uq_events_calendar_redirect"),
    )
    op.create_index(
        op.f("ix_events_calendar_redirect_calendar_id"),
        "events_calendar_redirect",
        ["calendar_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_calendar_redirect_tenant_id"),
        "events_calendar_redirect",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_events_calendar_redirect_tenant_id"), table_name="events_calendar_redirect"
    )
    op.drop_index(
        op.f("ix_events_calendar_redirect_calendar_id"), table_name="events_calendar_redirect"
    )
    op.drop_table("events_calendar_redirect")
