"""billing: swap records the hold it replaces

Revision ID: 4956d13dbf09
Revises: c349beffa40c
Create Date: 2026-10-29 09:42:27.975058

``billing_usage_hold.replaces_hold_id``: the old hold a ``swap`` named, so a
replay of its key that names another is an ``IdempotencyConflict``. A swap the
limit refused now leaves a ``refused`` row under its key (``status`` is a
plain string column: no constraint to change). A nullable column only: no
data migration. Chained after the images revision to keep one head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4956d13dbf09'
down_revision: str | None = 'c349beffa40c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'billing_usage_hold', sa.Column('replaces_hold_id', sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('billing_usage_hold', 'replaces_hold_id')
