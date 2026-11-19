"""events registration

Events PR 9: the registration settings on ``events_event`` (mode, provider, target, capacity,
window, "show seats left", reminder lead), and two tables, ``events_registration_count`` (one
counter per occurrence, the row an admit locks) and ``events_registration_seat`` (one row per
holder: an opaque id, never personal data). Events that already carry a ``registration_url`` are
backfilled to mode ``external``. The added columns are nullable or carry a server default. No
branch label (``events`` is already named by ``b8e1d0783868``).

Revision ID: 00a990d5c813
Revises: 19adf24acec2
Create Date: 2026-11-19 05:23:29.440772
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00a990d5c813"
down_revision: str | None = "19adf24acec2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BIG = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "events_registration_count",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("id", _BIG, autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(length=80), nullable=False),
        sa.Column("taken", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events_event.id"],
            name=op.f("fk_events_registration_count_event_id_events_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_registration_count")),
        sa.UniqueConstraint(
            "tenant_id", "event_id", "occurrence_key", name="uq_events_registration_count"
        ),
    )
    op.create_index(
        op.f("ix_events_registration_count_event_id"),
        "events_registration_count",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_registration_count_tenant_id"),
        "events_registration_count",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "events_registration_seat",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("id", _BIG, autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=100), nullable=False),
        sa.Column("holder", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events_event.id"],
            name=op.f("fk_events_registration_seat_event_id_events_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_registration_seat")),
        sa.UniqueConstraint("tenant_id", "provider", "holder", name="uq_events_registration_seat"),
    )
    op.create_index(
        op.f("ix_events_registration_seat_event_id"),
        "events_registration_seat",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_events_registration_seat_occ",
        "events_registration_seat",
        ["tenant_id", "event_id", "occurrence_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_registration_seat_tenant_id"),
        "events_registration_seat",
        ["tenant_id"],
        unique=False,
    )
    with op.batch_alter_table("events_event") as batch:
        batch.add_column(
            sa.Column(
                "registration_mode",
                sa.String(length=16),
                server_default="none",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("registration_provider", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("registration_target", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("registration_capacity", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("registration_opens_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("registration_closes_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "registration_show_seats",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("registration_reminder_minutes", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE events_event SET registration_mode = 'external' WHERE registration_url IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("events_event") as batch:
        batch.drop_column("registration_reminder_minutes")
        batch.drop_column("registration_show_seats")
        batch.drop_column("registration_closes_at")
        batch.drop_column("registration_opens_at")
        batch.drop_column("registration_capacity")
        batch.drop_column("registration_target")
        batch.drop_column("registration_provider")
        batch.drop_column("registration_mode")
    op.drop_index(
        op.f("ix_events_registration_seat_tenant_id"), table_name="events_registration_seat"
    )
    op.drop_index("ix_events_registration_seat_occ", table_name="events_registration_seat")
    op.drop_index(
        op.f("ix_events_registration_seat_event_id"), table_name="events_registration_seat"
    )
    op.drop_table("events_registration_seat")
    op.drop_index(
        op.f("ix_events_registration_count_tenant_id"), table_name="events_registration_count"
    )
    op.drop_index(
        op.f("ix_events_registration_count_event_id"), table_name="events_registration_count"
    )
    op.drop_table("events_registration_count")
