"""images billing subject

Adds the billing subject a hold was taken under (#284): ``images_billing_op.subject``
and ``images_image.storage_subject``. In billing's ``user`` mode images bills
``user:<collection owner>``, and settle, repair and growth replay the recorded
subject instead of deriving it again.

No backfill: ``NULL`` already means the row's ``tenant_id``, which is what every
existing hold was taken under.

Revision ID: c4e9b2a7d613
Revises: a7c2e4d81b35
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e9b2a7d613"
down_revision: str | None = "a7c2e4d81b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("images_billing_op") as batch:
        batch.add_column(sa.Column("subject", sa.String(length=64), nullable=True))
    with op.batch_alter_table("images_image") as batch:
        batch.add_column(sa.Column("storage_subject", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("images_image") as batch:
        batch.drop_column("storage_subject")
    with op.batch_alter_table("images_billing_op") as batch:
        batch.drop_column("subject")
