"""events feed tokens and imports

Events PR 5: ``events_feed_token`` (private feed links, only a SHA-256 of the token kept),
``events_import`` and ``events_import_item`` (the staged ``.ics`` import).

Revision ID: 6dedd89ae3a8
Revises: 8e5853254f79
Create Date: 2026-11-18 11:58:32.973715
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "6dedd89ae3a8"
down_revision: str | None = "8e5853254f79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events_feed_token",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["events_calendar.id"],
            name=op.f("fk_events_feed_token_calendar_id_events_calendar"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_feed_token")),
        sa.UniqueConstraint("token_hash", name="uq_events_feed_token_hash"),
    )
    op.create_index(
        op.f("ix_events_feed_token_calendar_id"), "events_feed_token", ["calendar_id"], unique=False
    )
    op.create_index(
        "ix_events_feed_token_owner",
        "events_feed_token",
        ["tenant_id", "calendar_id", "user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_feed_token_tenant_id"), "events_feed_token", ["tenant_id"], unique=False
    )
    op.create_table(
        "events_import",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source", sa.LargeBinary(), nullable=True),
        sa.Column("publish", sa.Boolean(), nullable=False),
        sa.Column("may_publish", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("dropped", sa.JSON(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("lease_owner", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["events_calendar.id"],
            name=op.f("fk_events_import_calendar_id_events_calendar"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_import")),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_events_import_at", "events_import", ["tenant_id", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_events_import_calendar_id"), "events_import", ["calendar_id"], unique=False
    )
    op.create_index(
        "ix_events_import_status", "events_import", ["status", "lease_until"], unique=False
    )
    op.create_index(
        op.f("ix_events_import_tenant_id"), "events_import", ["tenant_id"], unique=False
    )
    op.create_table(
        "events_import_item",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "import_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False),
        sa.Column("existing_event_id", sa.Uuid(), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=True),
        sa.Column("outcome_code", sa.String(length=40), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["events_import.id"],
            name=op.f("fk_events_import_item_import_id_events_import"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_import_item")),
        sa.UniqueConstraint("tenant_id", "import_id", "seq", name="uq_events_import_item_seq"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        op.f("ix_events_import_item_import_id"), "events_import_item", ["import_id"], unique=False
    )
    op.create_index(
        op.f("ix_events_import_item_tenant_id"), "events_import_item", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_events_import_item_todo",
        "events_import_item",
        ["tenant_id", "import_id", "outcome"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_import_item_todo", table_name="events_import_item")
    op.drop_index(op.f("ix_events_import_item_tenant_id"), table_name="events_import_item")
    op.drop_index(op.f("ix_events_import_item_import_id"), table_name="events_import_item")
    op.drop_table("events_import_item")
    op.drop_index(op.f("ix_events_import_tenant_id"), table_name="events_import")
    op.drop_index("ix_events_import_status", table_name="events_import")
    op.drop_index(op.f("ix_events_import_calendar_id"), table_name="events_import")
    op.drop_index("ix_events_import_at", table_name="events_import")
    op.drop_table("events_import")
    op.drop_index(op.f("ix_events_feed_token_tenant_id"), table_name="events_feed_token")
    op.drop_index("ix_events_feed_token_owner", table_name="events_feed_token")
    op.drop_index(op.f("ix_events_feed_token_calendar_id"), table_name="events_feed_token")
    op.drop_table("events_feed_token")
