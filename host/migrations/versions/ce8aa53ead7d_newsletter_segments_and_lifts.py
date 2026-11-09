"""newsletter segments and lifts

Adds ``newsletter_segment.rules`` (the editor's rows) and
``newsletter_campaign_render.audience_filters`` (the compiled terms snapshot),
both ``JSON NOT NULL DEFAULT '[]'``; the ``newsletter_suppression_lift`` audit
table; and the ``ix_newsletter_send_record`` and
``ix_newsletter_suppression_reason_at`` indexes. On SQLite ``newsletter_segment``
is rebuilt with ``AUTOINCREMENT`` so a segment id is never reused. No branch label.

Revision ID: ce8aa53ead7d
Revises: d4aac5b187d9
Create Date: 2026-11-06 00:19:34.099818
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce8aa53ead7d"
down_revision: str | None = "d4aac5b187d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "newsletter_suppression_lift",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("list_type_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifted_by", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_suppression_lift")),
    )
    op.create_index(
        "ix_newsletter_suppression_lift_at",
        "newsletter_suppression_lift",
        ["tenant_id", "lifted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_newsletter_suppression_lift_tenant_id"),
        "newsletter_suppression_lift",
        ["tenant_id"],
        unique=False,
    )
    with op.batch_alter_table("newsletter_campaign_render", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audience_filters", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )
    # A campaign names its segment as ``segment:<id>``, so on SQLite the table is
    # rebuilt with ``AUTOINCREMENT``: a plain ``INTEGER PRIMARY KEY`` hands the
    # highest id out again once its row is deleted. Postgres sequences never do.
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table(
        "newsletter_segment",
        schema=None,
        recreate="always" if sqlite else "auto",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch_op:
        batch_op.add_column(
            sa.Column("rules", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )
    op.create_index(
        "ix_newsletter_send_record",
        "newsletter_send",
        ["tenant_id", "record_uuid", "id"],
        unique=False,
    )
    op.create_index(
        "ix_newsletter_suppression_reason_at",
        "newsletter_suppression",
        ["tenant_id", "reason", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_newsletter_suppression_reason_at", table_name="newsletter_suppression")
    op.drop_index("ix_newsletter_send_record", table_name="newsletter_send")
    with op.batch_alter_table("newsletter_segment", schema=None) as batch_op:
        batch_op.drop_column("rules")
    with op.batch_alter_table("newsletter_campaign_render", schema=None) as batch_op:
        batch_op.drop_column("audience_filters")
    op.drop_index(
        op.f("ix_newsletter_suppression_lift_tenant_id"), table_name="newsletter_suppression_lift"
    )
    op.drop_index("ix_newsletter_suppression_lift_at", table_name="newsletter_suppression_lift")
    op.drop_table("newsletter_suppression_lift")
