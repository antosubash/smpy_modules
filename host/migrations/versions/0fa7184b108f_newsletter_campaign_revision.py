"""newsletter campaign revision

Adds ``newsletter_campaign.revision`` (``INTEGER NOT NULL DEFAULT 1``): the
campaign editor's optimistic-concurrency token. A PATCH names the revision it
read and the write is one conditional ``UPDATE ... SET revision = revision + 1``;
existing rows start at 1. No branch label (``542504340136`` carries
``newsletter``).

Revision ID: 0fa7184b108f
Revises: 542504340136
Create Date: 2026-11-05 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fa7184b108f"
down_revision: str | None = "542504340136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("newsletter_campaign", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("newsletter_campaign", schema=None) as batch_op:
        batch_op.drop_column("revision")
