"""newsletter sending

Adds what sending needs (PR 4):

- ``newsletter_campaign_render``: the rendered email of a scheduled campaign,
  one row per campaign (the worker never builds the app, so scheduling stores
  the render). It cascades with its campaign.
- ``newsletter_send.first_name`` and ``retry_at``: the merge value stored at
  freeze, and the instant before which a queued row is not due.
- ``newsletter_campaign.freeze_gen`` / ``freeze_owner`` / ``freeze_until`` and
  ``newsletter_send.freeze_gen``: the fence that keeps an interrupted or
  overlapping freeze from writing recipients after an unschedule or a
  reschedule. Both ``freeze_gen`` columns are ``INTEGER NOT NULL DEFAULT 0``.

No branch label (``542504340136`` carries ``newsletter``).

Revision ID: 5a1f7e77d9c6
Revises: 0fa7184b108f
Create Date: 2026-11-05 18:28:18.317684
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a1f7e77d9c6"
down_revision: str | None = "0fa7184b108f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "newsletter_campaign_render",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sender", sa.String(length=600), nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("public_base", sa.String(length=2048), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["newsletter_campaign.id"],
            name=op.f("fk_newsletter_campaign_render_campaign_id_newsletter_campaign"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("campaign_id", name=op.f("pk_newsletter_campaign_render")),
    )
    with op.batch_alter_table("newsletter_campaign_render", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_newsletter_campaign_render_tenant_id"), ["tenant_id"], unique=False
        )

    with op.batch_alter_table("newsletter_campaign", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("freeze_gen", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("freeze_owner", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("freeze_until", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("newsletter_send", schema=None) as batch_op:
        batch_op.add_column(sa.Column("first_name", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("freeze_gen", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("newsletter_send", schema=None) as batch_op:
        batch_op.drop_column("freeze_gen")
        batch_op.drop_column("retry_at")
        batch_op.drop_column("first_name")

    with op.batch_alter_table("newsletter_campaign", schema=None) as batch_op:
        batch_op.drop_column("freeze_until")
        batch_op.drop_column("freeze_owner")
        batch_op.drop_column("freeze_gen")

    with op.batch_alter_table("newsletter_campaign_render", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_newsletter_campaign_render_tenant_id"))

    op.drop_table("newsletter_campaign_render")
