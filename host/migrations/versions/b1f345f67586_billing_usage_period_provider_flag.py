"""billing: usage rollups record whether they count a provider's period (#99)

Revision ID: b1f345f67586
Revises: d6c76536d36d
Create Date: 2026-10-25 12:39:14.296241

``billing_usage_period.provider_period`` tells a rollup written for the
subscription's own period from a calendar month written while it lapsed, so
a lapsed snapshot that moves the period's end moves the first and spares the
second — boundaries alone cannot tell them apart when the two coincide.
Existing rows default to false: only the unreleased metering build wrote any.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1f345f67586'
down_revision: str | None = 'd6c76536d36d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'billing_usage_period',
        sa.Column('provider_period', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('billing_usage_period', 'provider_period')
