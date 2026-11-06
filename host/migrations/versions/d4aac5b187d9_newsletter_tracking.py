"""newsletter tracking

Adds what open and click tracking needs (PR 5), on ``newsletter_click``:

- ``click_count`` (``INTEGER NOT NULL DEFAULT 1``): how many times the recipient
  clicked the link. ``clicked_at`` now means the first click.
- ``uq_newsletter_click_send_link (tenant_id, send_id, link_id)``: one row per
  recipient per link, so the table is bounded by sends x links and a replayed
  token cannot grow it.

No branch label (``542504340136`` carries ``newsletter``).

Revision ID: d4aac5b187d9
Revises: 5a1f7e77d9c6
Create Date: 2026-11-05 22:12:00.275077
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4aac5b187d9"
down_revision: str | None = "5a1f7e77d9c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("newsletter_click", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("click_count", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.create_unique_constraint(
            "uq_newsletter_click_send_link", ["tenant_id", "send_id", "link_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("newsletter_click", schema=None) as batch_op:
        batch_op.drop_constraint("uq_newsletter_click_send_link", type_="unique")
        batch_op.drop_column("click_count")
