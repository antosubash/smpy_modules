"""events subscriptions

Events PR 10: ``events_subscription`` (a calendar's link to a remote ICS feed: the address only
sealed, the fetch state, the beat's lease) and ``events_external_item`` (the events of the last
fetch, cached read-only). No branch label (``events`` is already named by ``b8e1d0783868``).

Revision ID: d1847b1d68bb
Revises: 00a990d5c813
Create Date: 2026-11-19 11:55:02.067613
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1847b1d68bb"
down_revision: str | None = "00a990d5c813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events_subscription",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("url_enc", sa.Text(), nullable=False),
        sa.Column("url_display", sa.String(length=300), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("refresh_minutes", sa.Integer(), nullable=True),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("may_use_private", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.String(length=200), nullable=True),
        sa.Column("last_modified", sa.String(length=64), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("last_counts", sa.JSON(), nullable=False),
        sa.Column("lease_owner", sa.String(length=32), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["events_calendar.id"],
            name=op.f("fk_events_subscription_calendar_id_events_calendar"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_subscription")),
    )
    op.create_index(
        "ix_events_subscription_calendar",
        "events_subscription",
        ["tenant_id", "calendar_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_subscription_calendar_id"),
        "events_subscription",
        ["calendar_id"],
        unique=False,
    )
    op.create_index(
        "ix_events_subscription_due",
        "events_subscription",
        ["status", "next_fetch_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_subscription_tenant_id"), "events_subscription", ["tenant_id"], unique=False
    )
    op.create_table(
        "events_external_item",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("rrule", sa.String(length=500), nullable=True),
        sa.Column("recurrence_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("span_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("span_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("private_class", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("seen_generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["events_subscription.id"],
            name=op.f("fk_events_external_item_subscription_id_events_subscription"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_external_item")),
        sa.UniqueConstraint(
            "tenant_id", "subscription_id", "uid", name="uq_events_external_item_uid"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(
        op.f("ix_events_external_item_subscription_id"),
        "events_external_item",
        ["subscription_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_events_external_item_tenant_id"),
        "events_external_item",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_events_external_item_window",
        "events_external_item",
        ["tenant_id", "subscription_id", "span_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_external_item_window", table_name="events_external_item")
    op.drop_index(op.f("ix_events_external_item_tenant_id"), table_name="events_external_item")
    op.drop_index(
        op.f("ix_events_external_item_subscription_id"), table_name="events_external_item"
    )
    op.drop_table("events_external_item")
    op.drop_index(op.f("ix_events_subscription_tenant_id"), table_name="events_subscription")
    op.drop_index("ix_events_subscription_due", table_name="events_subscription")
    op.drop_index(op.f("ix_events_subscription_calendar_id"), table_name="events_subscription")
    op.drop_index("ix_events_subscription_calendar", table_name="events_subscription")
    op.drop_table("events_subscription")
